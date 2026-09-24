import asyncio, logging, os, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from dotenv import load_dotenv
from simkl_client import SimklAuthError, SimklClient, SimklSlowDown
from storage import EPOCH_ISO, storage
from tmdb_client import TmdbClient
from mdblist_client import MdbListClient
from imdb_client import ImdbClient

load_dotenv()

def positive_int_env(name, default, minimum=1):
    raw=os.getenv(name, str(default)).strip()
    try:
        value=int(raw)
    except ValueError:
        raise SystemExit(f"Invalid {name}={raw!r}. It must be an integer of at least {minimum}.")
    if value < minimum:
        raise SystemExit(f"Invalid {name}={value}. It must be at least {minimum}.")
    return value

DISCORD_BOT_TOKEN=os.getenv("DISCORD_BOT_TOKEN")
SIMKL_CLIENT_ID=os.getenv("SIMKL_CLIENT_ID")
TMDB_API_KEY=os.getenv("TMDB_API_KEY")
MDBLIST_API_KEY=os.getenv("MDBLIST_API_KEY")
GUILD_ID=os.getenv("GUILD_ID")
POLL_INTERVAL_MINUTES=positive_int_env("POLL_INTERVAL_MINUTES", 60)
POLL_CONCURRENCY=positive_int_env("POLL_CONCURRENCY", 5)
if GUILD_ID:
    try:
        int(GUILD_ID)
    except ValueError:
        raise SystemExit(f"Invalid GUILD_ID={GUILD_ID!r}. It must be a Discord server ID.")
if not DISCORD_BOT_TOKEN or not SIMKL_CLIENT_ID:
    raise SystemExit("Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID.")
if not TMDB_API_KEY:
    raise SystemExit("Missing TMDB_API_KEY.")

MEDIA_TYPES=("shows","anime","movies"); ACTIVITY_KEYS={"shows":"tv_shows","anime":"anime","movies":"movies"}
WATCHLIST_STATUSES=("watching","plantowatch","completed","dropped")
STATUS_TEXT={"watching":"started watching","plantowatch":"planned to watch","completed":"completed","dropped":"dropped"}
MEDIA_STYLES={"shows":(0x3498DB,"📺 TV"),"anime":(0xE91E63,"🌸 Anime"),"movies":(0xF1C40F,"🎬 Movie")}
HISTORY_FETCH_TIMEOUT_SECONDS=120; CHECKNOW_COOLDOWN_SECONDS=30
poll_lock=asyncio.Lock(); last_checknow_at=0.0; linking_users=set(); profile_lookup_attempted=set()
logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s"); log=logging.getLogger("simkl-bot")
simkl=SimklClient(SIMKL_CLIENT_ID); tmdb=TmdbClient(TMDB_API_KEY); mdblist=MdbListClient(MDBLIST_API_KEY) if MDBLIST_API_KEY else None; imdb=ImdbClient()
if mdblist is not None:
    log.info("MDBList IMDb ratings enabled.")
else:
    log.warning("MDBList IMDb ratings disabled: MDBLIST_API_KEY is not set.")

class SimklBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default()); self.tree=app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()
        await imdb.start()
        log.info("Slash commands synced globally.")
    async def close(self):
        poll_task = getattr(self, "_poll_task", None)
        if poll_task and not poll_task.done():
            log.info("Stopping polling task before shutdown.")
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Polling task failed while shutting down.")

        try:
            await storage.flush()
        except Exception:
            log.exception("Failed to flush persistent storage during shutdown.")

        for client in (simkl,tmdb,mdblist,imdb):
            try:
                await client.close()
            except Exception:
                pass
        await super().close()
bot=SimklBot()

def to_iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
def now_iso(): return to_iso(datetime.now(timezone.utc))
def parse_iso(v):
    if not v: return datetime.min.replace(tzinfo=timezone.utc)
    try:
        d=datetime.fromisoformat(v.replace("Z","+00:00")); return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: return datetime.min.replace(tzinfo=timezone.utc)
def calculate_token_expiry(v):
    try: s=int(v)
    except (TypeError,ValueError): return None
    return to_iso(datetime.now(timezone.utc)+timedelta(seconds=s)) if s>0 else None
def is_admin(i): return bool(i.guild and i.user.guild_permissions.manage_guild)
def guild_id(i): return i.guild.id if i.guild else None
def simkl_poster_url(p,size="_m"): return f"https://wsrv.nl/?url=https://simkl.in/posters/{p}{size}.webp&q=90" if p else None
def simkl_profile_url(i): return f"https://simkl.com/{i}/" if i else None
def account_id_from_settings(s): return (s.get("account") or {}).get("id") if isinstance(s,dict) else None
def simkl_title_url(t,i,slug=None):
    b={"movies":"https://simkl.com/movies","anime":"https://simkl.com/anime"}.get(t,"https://simkl.com/tv")
    return f"{b}/{i}/{slug}" if slug else f"{b}/{i}"
def episode_key(t,i,s,e): return f"{t}:{i}:{s}:{e}"
def movie_key(t,i): return f"{t}:{i}"

def iter_show_episodes(t,items):
    for item in items or []:
        show=item.get("show") or {}; ids=show.get("ids") or {}; sid=ids.get("simkl")
        if sid is None: continue
        mapped=item.get("mapped_tvdb_seasons") or []
        for season in item.get("seasons") or []:
            original=season.get("number")
            if original is None: continue
            mapped_season=mapped[original-1] if t=="anime" and isinstance(original,int) and 0<original<=len(mapped) else None
            sn=mapped_season if mapped_season is not None else original
            for ep in season.get("episodes") or []:
                en=ep.get("number")
                if en is None: continue
                wr=ep.get("watched_at")
                yield {"show_title":show.get("title","a show"),"simkl_id":sid,"tmdb_id":ids.get("tmdb"),"tvdb_id":ids.get("tvdb"),"slug":ids.get("slug"),"poster":show.get("poster"),"season_num":sn,"original_season_num":original,"mapped_tvdb_season_num":mapped_season,"episode_number":en,"episode_title":ep.get("title"),"watched_raw":wr,"watched_dt":parse_iso(wr) if wr else None,"key":episode_key(t,sid,sn,en)}

def format_episode_range(s,a,b):
    if s is None: return f"E{a:02d}" if a==b else f"E{a:02d}-E{b:02d}"
    return f"S{s:02d}E{a:02d}" if a==b else f"S{s:02d}E{a:02d}-E{b:02d}"
def group_consecutive(es):
    es=sorted(es,key=lambda x:x["episode_number"]); groups=[]
    for e in es:
        if not groups or e["episode_number"]!=groups[-1][-1]["episode_number"]+1: groups.append([e])
        else: groups[-1].append(e)
    return groups

async def episode_media(t,e):
    candidates=[]
    for v in (e.get("season_num"),e.get("mapped_tvdb_season_num"),e.get("original_season_num")):
        try: v=int(v)
        except (TypeError,ValueError): continue
        if v not in candidates: candidates.append(v)
    if t=="anime": r=await tmdb.find_anime_episode(e.get("tmdb_id"),e.get("tvdb_id"),candidates,e["episode_number"],episode_title=e.get("episode_title"))
    else:
        r=None
        if e.get("tmdb_id") is not None:
            d=await tmdb.get_episode_details(e["tmdb_id"],e.get("season_num"),e["episode_number"])
            if d: r={"series_id":int(e["tmdb_id"]),"season_number":int(e["season_num"]),"episode_number":e["episode_number"],"episode":d}
        if not r and e.get("tvdb_id") is not None:
            sid=await tmdb.find_series_by_tvdb(e["tvdb_id"])
            if sid:
                d=await tmdb.get_episode_details(sid,e.get("season_num"),e["episode_number"])
                if d: r={"series_id":sid,"season_number":int(e["season_num"]),"episode_number":e["episode_number"],"episode":d}
    if not r: return None,e.get("episode_title"),None
    episode=r.get("episode") or {}
    imdb_id=(episode.get("external_ids") or {}).get("imdb_id")
    still=await tmdb.get_episode_still(r["series_id"],r["season_number"],r["episode_number"])
    return still,e.get("episode_title") or episode.get("name"),imdb_id

async def prefs(g,u): return await storage.get_embed_preferences(g,u)
async def get_imdb_rating(media_type, tmdb_id):
    if mdblist is None or tmdb_id is None:
        return None
    try:
        return await mdblist.get_imdb_rating(media_type, tmdb_id)
    except Exception:
        log.warning("MDBList rating lookup failed for %s %s.", media_type, tmdb_id, exc_info=True)
        return None

async def get_movie_ratings(tmdb_id):
    if mdblist is None or tmdb_id is None:
        return None
    try:
        ratings = await mdblist.get_ratings("movie", tmdb_id)
        return {"imdb": ratings.get("imdb"), "mal": ratings.get("myanimelist")}
    except Exception:
        log.warning("MDBList movie rating lookup failed for %s.", tmdb_id, exc_info=True)
        return None

def build_embed(t,desc,ts,name,member,image,profile,title=None,title_url=None,poster=None,logo=None,preferences=None):
    color,label=MEDIA_STYLES[t]; p={"style":"rich","artwork":"auto","activity_text":"short","show_imdb":True,"show_mal":True}; p.update(preferences or {})
    e=discord.Embed(title=title,url=title_url,description=desc,color=color,timestamp=ts)
    e.set_author(name=f"{name}'s Activity",url=profile,icon_url=member.display_avatar.url if member else None)
    selected=poster if p["artwork"]=="poster" or p["style"]=="poster" else image
    selected=selected or poster or image
    if selected:
        if p["style"]=="minimal":
            e.set_thumbnail(url=selected)
        else:
            e.set_image(url=selected)
            if p["artwork"]=="backdrop" and logo:
                e.set_thumbnail(url=logo)
    e.set_footer(text=f"{label} · SIMKL"); return e
async def send_embed(ch,e,what):
    try:
        await ch.send(embed=e)
        return True
    except discord.Forbidden:
        log.error("Discord denied permission while sending %s embed to channel %s.", what, getattr(ch, "id", "unknown"))
    except discord.NotFound:
        log.error("Discord channel or destination was not found while sending %s embed.", what)
    except discord.HTTPException as exc:
        # discord.py handles normal Discord rate limits. Avoid blind retries
        # because a failed response may still have created the message.
        log.error("Discord HTTP error while sending %s embed (status=%s): %s", what, exc.status, exc)
    except Exception:
        log.exception("Unexpected failure while sending %s embed.", what)
    return False

async def refresh_user_token(uid,u):
    rt=u.get("refresh_token")
    if not rt: raise SimklAuthError("No refresh token.")
    tok=await simkl.refresh_token(rt)
    if not tok or not tok.get("access_token"): raise SimklAuthError("Token refresh failed.")
    access=tok["access_token"]; newrt=tok.get("refresh_token"); exp=calculate_token_expiry(tok.get("expires_in"))
    await storage.update_tokens(uid,access,newrt,exp); u["simkl_token"]=access; u["refresh_token"]=newrt or rt; u["token_expires_at"]=exp; return access
async def valid_token(uid,u):
    if not u.get("simkl_token"): raise SimklAuthError("No SIMKL token.")
    if u.get("token_expires_at") and parse_iso(u["token_expires_at"])<=datetime.now(timezone.utc)+timedelta(days=1):
        try: return await refresh_user_token(uid,u)
        except SimklAuthError: pass
    return u["simkl_token"]
async def call_refresh(uid,u,token,fn,*a,**kw):
    try: return await fn(token,*a,**kw),token
    except SimklAuthError:
        token=await refresh_user_token(uid,u); return await fn(token,*a,**kw),token

async def cached_simkl_items(uid,u,token,t,date_from=None,request_cache=None,timeout=None):
    if request_cache is None:
        return await call_refresh(uid,u,token,simkl.get_all_items,t,date_from=date_from,timeout=timeout)

    key=("all-items",uid,t,date_from,timeout)
    cached=request_cache.get(key)
    if cached is not None:
        return cached

    result=await call_refresh(uid,u,token,simkl.get_all_items,t,date_from=date_from,timeout=timeout)
    request_cache[key]=result
    return result

async def cached_simkl_activities(uid,u,token,request_cache):
    key=("activities",uid)
    cached=request_cache.get(key)
    if cached is not None:
        return cached

    result=await call_refresh(uid,u,token,simkl.get_activities)
    request_cache[key]=result
    return result

async def seed_history(g,uid,u,token,request_cache=None):
    last=await storage.get_last_checked(g,uid); keys=[]; statuses={}; watches={}
    for t in MEDIA_TYPES:
        since=parse_iso(last.get(t,EPOCH_ISO)); items,token=await cached_simkl_items(uid,u,token,t,request_cache=request_cache,timeout=HISTORY_FETCH_TIMEOUT_SECONDS)
        if t=="movies":
            for x in items or []:
                m=x.get("movie") or {}; sid=(m.get("ids") or {}).get("simkl"); wr=x.get("last_watched_at")
                if sid is None or (wr and parse_iso(wr)>since): continue
                k=movie_key(t,sid); keys.append(k)
                if x.get("status"): statuses[f"{t}:{sid}"]=x["status"]
                if wr: watches[k]=wr
        else:
            for x in items or []:
                m=x.get("show") or {}; sid=(m.get("ids") or {}).get("simkl")
                if sid is not None and x.get("status"): statuses[f"{t}:{sid}"]=x["status"]
            for e in iter_show_episodes(t,items):
                if e["watched_dt"] is None or e["watched_dt"]<=since:
                    keys.append(e["key"])
                    if e.get("watched_raw"): watches[e["key"]]=e["watched_raw"]
    await storage.mark_history_seeded(g,uid,keys); await storage.update_activity_state(g,uid,statuses=statuses,watch_times=watches); return token

async def resolve_member(g,uid):
    guild=bot.get_guild(int(g))
    if not guild: return None,"Someone"
    m=guild.get_member(int(uid))
    if not m:
        try: m=await guild.fetch_member(int(uid))
        except Exception: return None,"Someone"
    return m,m.display_name

async def process_shows(ch,g,uid,name,member,t,items,profile):
    announced=await storage.get_announced(g,uid); state=await storage.get_activity_state(g,uid); watches=state["watch_times"]; p=await prefs(g,uid); groups=defaultdict(list)
    for e in iter_show_episodes(t,items):
        if e["watched_dt"] is None: continue
        prev=watches.get(e["key"]); prevdt=parse_iso(prev) if prev else None
        rw=e["key"] in announced and prevdt and e["watched_dt"]>prevdt
        if e["key"] not in announced or rw: groups[(e["simkl_id"],e["season_num"],"rewatched" if rw else "watched")].append(e)
    count=0; ok=True; pending={}
    for (sid,sn,kind),es in groups.items():
        es=sorted(es,key=lambda x:x["episode_number"]); title=es[0]["show_title"]; url=simkl_title_url(t,sid,es[0]["slug"]); fallback=simkl_poster_url(es[0]["poster"])
        for grp in group_consecutive(es):
            try:
                image,ep_title,episode_imdb_id=await episode_media(t,grp[0])
            except Exception:
                log.warning("TMDB episode lookup failed for %s.", title, exc_info=True)
                image,ep_title,episode_imdb_id=None,grp[0].get("episode_title"),None
            label=format_episode_range(sn,grp[0]["episode_number"],grp[-1]["episode_number"]); verb=kind
            rating = await imdb.get_rating(episode_imdb_id) if len(grp) == 1 and p.get("show_imdb", True) else None
            desc=f"{verb} **{label}**"
            if p["activity_text"]=="detailed": desc=f"{verb} **{label}** of **{title}**"
            if len(grp)==1:
                if ep_title: desc+=f"\n*{ep_title}*"
                if rating is not None: desc+=f"\n⭐ IMDb {rating:.1f}/10"
            logo=None
            if p["artwork"]=="backdrop" and grp[0].get("tmdb_id") is not None:
                try:
                    logo=await tmdb.get_tv_logo(grp[0]["tmdb_id"])
                except Exception:
                    log.warning("TMDB TV logo lookup failed for %s.", title, exc_info=True)
            e=build_embed(t,desc,max(x["watched_dt"] for x in grp),name,member,image or fallback,profile,title,url,fallback,logo,p)
            if not await send_embed(ch,e,"episode"):
                ok=False
                continue
            keys=[x["key"] for x in grp]
            watch_times={x["key"]:x["watched_raw"] for x in grp}
            await storage.add_announced(g,uid,keys)
            await storage.update_activity_state(g,uid,watch_times=watch_times,flush=True)
            pending.update(watch_times)
            count+=len(grp)
    if pending: await storage.update_activity_state(g,uid,watch_times=pending,flush=False)
    return count,ok

async def process_movies(ch,g,uid,name,member,items,since,profile):
    announced=await storage.get_announced(g,uid); state=await storage.get_activity_state(g,uid); watches=state["watch_times"]; p=await prefs(g,uid); count=0; ok=True; pending={}
    for x in items or []:
        m=x.get("movie") or {}; ids=m.get("ids") or {}; sid=ids.get("simkl"); wr=x.get("last_watched_at")
        if sid is None or not wr: continue
        dt=parse_iso(wr); k=movie_key("movies",sid); prev=watches.get(k); prevdt=parse_iso(prev) if prev else None; rw=k in announced and prevdt and dt>prevdt
        if k in announced and not rw: continue
        if k not in announced and dt<=since: continue
        title=m.get("title","a movie"); poster=simkl_poster_url(m.get("poster")); image=None
        if ids.get("tmdb") is not None:
            try: image=await tmdb.get_movie_backdrop(ids["tmdb"])
            except Exception: log.warning("TMDB movie backdrop lookup failed for %s.", title, exc_info=True)
        anime_movie = bool(ids.get("mal") or m.get("anime_type"))
        movie_ratings = await get_movie_ratings(ids.get("tmdb")) if anime_movie else None
        imdb_rating = movie_ratings.get("imdb") if movie_ratings else await get_imdb_rating("movie", ids.get("tmdb"))
        mal_rating = movie_ratings.get("mal") if movie_ratings else None
        rating_parts = []
        if p.get("show_imdb", True) and imdb_rating is not None:
            rating_parts.append(f"⭐ IMDb {imdb_rating:.1f}/10")
        if anime_movie and p.get("show_mal", True) and mal_rating is not None:
            rating_parts.append(f"⭐ MAL {mal_rating:.2f}/10")
        rating_text = " · " + " · ".join(rating_parts) if rating_parts else ""
        verb="rewatched" if rw else "watched a movie"; desc=f"{verb}{rating_text}" if p["activity_text"]!="detailed" else f"{verb} **{title}**{rating_text}"
        logo=None
        if p["artwork"]=="backdrop" and ids.get("tmdb") is not None:
            try:
                logo=await tmdb.get_movie_logo(ids["tmdb"])
            except Exception:
                log.warning("TMDB movie logo lookup failed for %s.", title, exc_info=True)
        e=build_embed("movies",desc,dt,name,member,image or poster,profile,title,simkl_title_url("movies",sid,ids.get("slug")),poster,logo,p)
        if not await send_embed(ch,e,"movie"):
            ok=False
            continue
        await storage.add_announced(g,uid,[k])
        await storage.update_activity_state(g,uid,watch_times={k:wr},flush=True)
        pending[k]=wr
        count+=1
    if pending: await storage.update_activity_state(g,uid,watch_times=pending,flush=False)
    return count,ok

async def process_status(ch,g,uid,name,member,t,items,profile):
    state=await storage.get_activity_state(g,uid)
    statuses=state["statuses"]
    baseline=not state["statuses_seeded"]
    p=await prefs(g,uid)
    successful={}
    count=0
    ok=True
    for x in items or []:
        m=(x.get("movie") if t=="movies" else x.get("show")) or {}
        ids=m.get("ids") or {}
        sid=ids.get("simkl")
        status=x.get("status")
        if sid is None or status not in WATCHLIST_STATUSES:
            continue
        key=f"{t}:{sid}"
        if baseline or statuses.get(key)==status:
            successful[key]=status
            continue
        # Movies already generate a dedicated "watched" activity. Treat the
        # SIMKL "completed" status as internal state for movies so it does not
        # create a duplicate notification. TV/anime still use "completed".
        if t=="movies" and status=="completed":
            successful[key]=status
            continue
        title=m.get("title") or "Untitled"
        poster=simkl_poster_url(m.get("poster"))
        image=None
        if ids.get("tmdb") is not None:
            try:
                image=await (tmdb.get_movie_backdrop(ids["tmdb"]) if t=="movies" else tmdb.get_tv_backdrop(ids["tmdb"]))
            except Exception:
                log.warning("TMDB status artwork lookup failed for %s.", title, exc_info=True)
        rating = await get_imdb_rating("movie" if t=="movies" else "show", ids.get("tmdb")) if p.get("show_imdb", True) else None
        rating_text = f" · ⭐ IMDb {rating:.1f}/10" if rating is not None else ""
        desc=f"{STATUS_TEXT[status]}{rating_text}" if p["activity_text"]!="detailed" else f"{STATUS_TEXT[status]} **{title}**{rating_text}"
        logo=None
        if p["artwork"]=="backdrop" and ids.get("tmdb") is not None:
            try:
                logo=await (tmdb.get_movie_logo(ids["tmdb"]) if t=="movies" else tmdb.get_tv_logo(ids["tmdb"]))
            except Exception:
                log.warning("TMDB title logo lookup failed for %s.", title, exc_info=True)
        e=build_embed(t,desc,datetime.now(timezone.utc),name,member,image or poster,profile,title,simkl_title_url(t,sid,ids.get("slug")),poster,logo,p)
        if not await send_embed(ch,e,status):
            ok=False
            continue
        count+=1
        successful[key]=status
        await storage.update_activity_state(g,uid,statuses={key:status},statuses_seeded=True,flush=True)
    if successful and baseline:
        await storage.update_activity_state(g,uid,statuses=successful,statuses_seeded=True,flush=True)
    return count,ok

async def mark_poll_failure(g,uid,error,previous_failures=0):
    failures=max(int(previous_failures or 0),0)+1
    await storage.update_poll_health(g,uid,last_error=error,consecutive_failures=failures,flush=True)

async def poll_one(ch,g,uid,u,gu,request_cache=None):
    previous_failures=gu.get("consecutive_failures",0)
    await storage.update_poll_health(g,uid,last_poll_at=now_iso(),flush=False)
    try:
        token=await valid_token(uid,u)
    except SimklAuthError as exc:
        error=f"SIMKL authentication failed: {exc}"
        await mark_poll_failure(g,uid,error,previous_failures)
        log.warning("SIMKL authentication failed for %s.",uid)
        return 0
    except Exception as exc:
        error=f"token validation: {type(exc).__name__}: {exc}"
        await mark_poll_failure(g,uid,error,previous_failures)
        log.exception("Failed validating SIMKL token for user %s.",uid)
        return 0
    member,name=await resolve_member(g,uid)
    if not member:
        error=f"Discord member {uid} is no longer in guild {g}"
        await mark_poll_failure(g,uid,error,previous_failures)
        log.warning("User %s is no longer a member of guild %s; skipping.",uid,g)
        return 0
    try:
        activities,token=await cached_simkl_activities(uid,u,token,request_cache if request_cache is not None else {})
    except Exception as exc:
        error=f"activity fetch: {type(exc).__name__}: {exc}"
        await mark_poll_failure(g,uid,error,previous_failures)
        log.exception("Failed to get SIMKL activity timestamps for user %s.",uid)
        return 0
    if not gu.get("history_seeded"):
        try:
            token=await seed_history(g,uid,u,token,request_cache)
            gu["history_seeded"]=True
        except Exception as exc:
            error=f"history seed: {type(exc).__name__}: {exc}"
            await mark_poll_failure(g,uid,error,previous_failures)
            log.exception("Couldn't seed SIMKL history for user %s in guild %s.",uid,g)
            return 0
    if not u.get("simkl_account_id") and uid not in profile_lookup_attempted:
        profile_lookup_attempted.add(uid)
        try:
            settings,token=await call_refresh(uid,u,token,simkl.get_user_settings)
            aid=account_id_from_settings(settings)
            if aid:
                await storage.set_account_id(uid,aid)
                u["simkl_account_id"]=aid
        except Exception:
            log.warning("Profile lookup failed for %s.",uid,exc_info=True)
    profile=simkl_profile_url(u.get("simkl_account_id"))
    last=await storage.get_last_checked(g,uid)
    posted=0
    cycle_errors=[]
    for t in MEDIA_TYPES:
        since=last.get(t,EPOCH_ISO)
        sdt=parse_iso(since)
        a=activities.get(ACTIVITY_KEYS[t]) or {}
        stamp=a.get("all")
        log.info("Check %s/%s: SIMKL %s activity=%r checkpoint=%s",g,uid,t,stamp,since)
        if not stamp or parse_iso(stamp)<=sdt:
            continue
        try:
            items,token=await cached_simkl_items(uid,u,token,t,date_from=since,request_cache=request_cache)
            sc,so=await process_status(ch,g,uid,name,member,t,items,profile)
            wc,wo=await (process_movies(ch,g,uid,name,member,items,sdt,profile) if t=="movies" else process_shows(ch,g,uid,name,member,t,items,profile))
            if so and wo:
                await storage.update_last_checked(g,uid,t,to_iso(parse_iso(stamp)))
                posted+=wc
            else:
                cycle_errors.append(f"{t}: partial post failure")
                log.warning("Some %s posts failed for user %s; checkpoint not advanced.",t,uid)
        except Exception as exc:
            cycle_errors.append(f"{t}: {type(exc).__name__}")
            log.exception("Failed processing %s activity for user %s.",t,uid)
        await storage.flush()
    if cycle_errors:
        error="; ".join(cycle_errors)
        await mark_poll_failure(g,uid,error,previous_failures)
    else:
        await storage.update_poll_health(
            g,uid,last_success_at=now_iso(),last_error="",
            consecutive_failures=0,flush=False
        )
        await storage.flush()
    return posted

async def poll_all(g=None):
    started = time.monotonic()

    async with poll_lock:
        targets=await storage.get_poll_targets(g)


        if not targets:
            log.info("Polling cycle: no linked users with configured channels.")
            return 0

        # Keep all guilds for the same Discord user in one worker. This
        # preserves per-user SIMKL request deduplication while allowing
        # different users to be processed concurrently.
        users={}
        for x in targets:
            users.setdefault(x["discord_user_id"],[]).append(x)

        semaphore=asyncio.Semaphore(POLL_CONCURRENCY)

        async def process_user(uid,user_targets):
            async with semaphore:
                user_data=user_targets[0]["user_data"]
                request_cache={}
                posted=0

                for x in user_targets:
                    gid=x["guild_id"]
                    ch=bot.get_channel(int(x["channel_id"]))
                    if ch is None:
                        try:
                            ch=await bot.fetch_channel(int(x["channel_id"]))
                        except Exception as exc:
                            error=f"Discord channel unavailable: {type(exc).__name__}: {exc}"
                            await mark_poll_failure(gid,uid,error,x["guild_user_data"].get("consecutive_failures",0))
                            log.exception("Couldn't access channel %s for guild %s.",x["channel_id"],gid)
                            continue

                    try:
                        posted+=await poll_one(ch,int(gid),uid,user_data,x["guild_user_data"],request_cache)
                    except SimklAuthError as exc:
                        error=f"SIMKL authentication failed: {exc}"
                        await mark_poll_failure(gid,uid,error,x["guild_user_data"].get("consecutive_failures",0))
                        log.warning("Auth failed for %s.",uid)
                    except Exception as exc:
                        error=f"{type(exc).__name__}: {exc}"
                        await mark_poll_failure(gid,uid,error,x["guild_user_data"].get("consecutive_failures",0))
                        log.exception("Polling failed for %s in guild %s.",uid,gid)

                return posted

        results=await asyncio.gather(
            *(process_user(uid,user_targets) for uid,user_targets in users.items())
        )
        posted=sum(results)
        duration=time.monotonic()-started
        log.info(
            "Polling cycle complete: %d user(s), %d target(s), %d posted, %.2fs elapsed, concurrency=%d.",
            len(users),len(targets),posted,duration,POLL_CONCURRENCY
        )
        return posted
STYLE_CHOICES=[app_commands.Choice(name="Rich (large artwork)",value="rich"),app_commands.Choice(name="Minimal (small artwork)",value="minimal"),app_commands.Choice(name="Poster (large poster)",value="poster")]
ARTWORK_CHOICES=[app_commands.Choice(name="Automatic",value="auto"),app_commands.Choice(name="Poster only",value="poster"),app_commands.Choice(name="Backdrop",value="backdrop")]
TEXT_CHOICES=[app_commands.Choice(name="Short",value="short"),app_commands.Choice(name="Detailed",value="detailed")]
NOT_ADMIN_MESSAGE="You need the Manage Server permission to do that."

@bot.tree.command(name="simkl-link",description="Link your SIMKL account in this server.")
async def simkl_link(i):
    g=guild_id(i)
    if not g: await i.response.send_message("This command must be used in a server.",ephemeral=True); return
    uid=str(i.user.id); key=f"{g}:{uid}"
    if key in linking_users: await i.response.send_message("You already have a linking code waiting.",ephemeral=True); return
    linking_users.add(key)
    try:
        await i.response.defer(ephemeral=True); pin=await simkl.start_pin_auth(); code=pin["user_code"]; device=pin["device_code"]; expires=pin.get("expires_in",900); interval=pin.get("interval",5); url=pin.get("verification_uri","https://simkl.com/pin")
        await i.followup.send(f"Go to {url}\nEnter this code: {code}\nThe code expires in about {expires//60} minutes.",ephemeral=True)
        elapsed=0; tokens=None
        while elapsed<expires:
            await asyncio.sleep(interval); elapsed+=interval
            try: tokens=await simkl.poll_pin(device)
            except SimklSlowDown: interval+=5; continue
            except SimklAuthError: break
            except Exception: log.warning("PIN poll failed.",exc_info=True); continue
            if tokens: break
        if not tokens: await i.followup.send("The SIMKL linking code expired or was cancelled. Run /simkl-link again.",ephemeral=True); return
        access=tokens["access_token"]; refresh=tokens.get("refresh_token"); exp=calculate_token_expiry(tokens.get("expires_in")); aid=None
        try:
            settings=await simkl.get_user_settings(access); aid=account_id_from_settings(settings); username=settings.get("user",{}).get("name") or settings.get("account",{}).get("id") or "SIMKL user"
        except Exception: username="SIMKL user"
        await storage.link_user(g,uid,access,refresh,username,now_iso(),exp,aid)
        await i.followup.send(f"Linked as {username} in this server.",ephemeral=True)
        try: await seed_history(g,uid,{"simkl_token":access,"refresh_token":refresh,"token_expires_at":exp},access)
        except Exception: log.warning("Initial history seed failed.",exc_info=True)
    finally: linking_users.discard(key)

@bot.tree.command(name="simkl-unlink",description="Unlink your SIMKL account from this server.")
async def simkl_unlink(i):
    g=guild_id(i)
    if not g: await i.response.send_message("This command must be used in a server.",ephemeral=True); return
    ok=await storage.unlink_user(g,str(i.user.id)); await i.response.send_message("Your SIMKL account has been unlinked from this server." if ok else "You don't have a linked SIMKL account in this server.",ephemeral=True)

@bot.tree.command(name="simkl-style",description="Choose your personal SIMKL activity embed preferences.")
@app_commands.choices(style=STYLE_CHOICES,artwork=ARTWORK_CHOICES,activity_text=TEXT_CHOICES)
async def simkl_style(i,style: app_commands.Choice[str] | None = None,artwork: app_commands.Choice[str] | None = None,activity_text: app_commands.Choice[str] | None = None):
    g=guild_id(i)
    if not g: await i.response.send_message("This command must be used in a server.",ephemeral=True); return
    uid=str(i.user.id)
    if style is None and artwork is None and activity_text is None:
        p=await prefs(g,uid); await i.response.send_message(f"Your effective settings:\n• Style: **{p['style']}**\n• Artwork: **{p['artwork']}**\n• Activity text: **{p['activity_text']}**",ephemeral=True); return
    await storage.set_embed_preferences(uid,style=style.value if style else None,artwork=artwork.value if artwork else None,activity_text=activity_text.value if activity_text else None)
    p=await prefs(g,uid); await i.response.send_message(f"Your personal settings are now **{p['style']} / {p['artwork']} / {p['activity_text']}**.\nThese settings override the server default.",ephemeral=True)

@bot.tree.command(name="simkl-style-server",description="(Admin) Set this server's default SIMKL activity embed style.")
@app_commands.choices(style=STYLE_CHOICES,artwork=ARTWORK_CHOICES,activity_text=TEXT_CHOICES)
async def simkl_style_server(i,style: app_commands.Choice[str] | None = None,artwork: app_commands.Choice[str] | None = None,activity_text: app_commands.Choice[str] | None = None):
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    if style is None and artwork is None and activity_text is None:
        p=await storage.get_server_embed_preferences(g); await i.response.send_message(f"Server default:\n• Style: **{p['style']}**\n• Artwork: **{p['artwork']}**\n• Activity text: **{p['activity_text']}**",ephemeral=True); return
    await storage.set_server_embed_preferences(g,style=style.value if style else None,artwork=artwork.value if artwork else None,activity_text=activity_text.value if activity_text else None)
    p=await storage.get_server_embed_preferences(g); await i.response.send_message(f"Server default updated to **{p['style']} / {p['artwork']} / {p['activity_text']}**.\nUsers with personal settings will continue using their own preferences.",ephemeral=True)

@bot.tree.command(name="simkl-ratings",description="Configure which ratings are shown in activity embeds.")
@app_commands.choices(show_imdb=[app_commands.Choice(name="Show",value="true"),app_commands.Choice(name="Hide",value="false")],show_mal=[app_commands.Choice(name="Show",value="true"),app_commands.Choice(name="Hide",value="false")])
async def simkl_ratings(i,show_imdb: app_commands.Choice[str] | None = None,show_mal: app_commands.Choice[str] | None = None):
    g=guild_id(i)
    if not g:
        await i.response.send_message("This command must be used in a server.",ephemeral=True)
        return
    uid=str(i.user.id)
    if show_imdb is None and show_mal is None:
        p=await prefs(g,uid)
        await i.response.send_message(
            f"IMDb ratings: **{'shown' if p.get('show_imdb', True) else 'hidden'}**\n"
            f"MAL ratings: **{'shown' if p.get('show_mal', True) else 'hidden'}**",
            ephemeral=True,
        )
        return
    await storage.set_embed_preferences(
        uid,
        show_imdb=(show_imdb.value == "true") if show_imdb else None,
        show_mal=(show_mal.value == "true") if show_mal else None,
    )
    p=await prefs(g,uid)
    await i.response.send_message(
        f"Ratings are now configured as IMDb: **{'shown' if p.get('show_imdb', True) else 'hidden'}**, "
        f"MAL: **{'shown' if p.get('show_mal', True) else 'hidden'}**.",
        ephemeral=True,
    )

@bot.tree.command(name="simkl-ratings-server",description="(Admin) Configure this server's default rating visibility.")
@app_commands.choices(show_imdb=[app_commands.Choice(name="Show",value="true"),app_commands.Choice(name="Hide",value="false")],show_mal=[app_commands.Choice(name="Show",value="true"),app_commands.Choice(name="Hide",value="false")])
async def simkl_ratings_server(i,show_imdb: app_commands.Choice[str] | None = None,show_mal: app_commands.Choice[str] | None = None):
    g=guild_id(i)
    if not g or not is_admin(i):
        await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True)
        return
    if show_imdb is None and show_mal is None:
        p=await storage.get_server_embed_preferences(g)
        await i.response.send_message(
            f"Server ratings: IMDb **{'shown' if p.get('show_imdb', True) else 'hidden'}**, "
            f"MAL **{'shown' if p.get('show_mal', True) else 'hidden'}**.",
            ephemeral=True,
        )
        return
    await storage.set_server_embed_preferences(
        g,
        show_imdb=(show_imdb.value == "true") if show_imdb else None,
        show_mal=(show_mal.value == "true") if show_mal else None,
    )
    p=await storage.get_server_embed_preferences(g)
    await i.response.send_message(
        f"Server ratings are now IMDb: **{'shown' if p.get('show_imdb', True) else 'hidden'}**, "
        f"MAL: **{'shown' if p.get('show_mal', True) else 'hidden'}**.",
        ephemeral=True,
    )

@bot.tree.command(name="simkl-setchannel",description="(Admin) Set the channel where this server's watch activity is posted.")
async def simkl_setchannel(i,channel:discord.TextChannel=None):
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    target=channel or i.channel; await storage.set_channel(g,target.id); await i.response.send_message(f"Watch activity for this server will now be posted in {target.mention}.",ephemeral=True)

@bot.tree.command(name="simkl-status",description="(Admin) Show this server's configuration and linked accounts.")
async def simkl_status(i):
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    d=await storage.get_all()
    sg=(d.get("guilds") or {}).get(str(g),{})
    users=sg.get("users") or {}
    allu=d.get("users") or {}
    ch=sg.get("channel_id")
    text=f"<#{ch}>" if ch else "**not set**"
    lines=[]
    now=datetime.now(timezone.utc)
    guild=i.guild
    current_count=0
    stale_count=0
    for uid, gu in users.items():
        try:
            member=guild.get_member(int(uid))
            if member is None:
                member=await guild.fetch_member(int(uid))
        except (discord.NotFound, discord.Forbidden, ValueError):
            member=None
        if member is None:
            stale_count+=1
            continue
        current_count+=1
        u=allu.get(uid) or {}
        username=u.get("simkl_username","unknown")
        expires=u.get("token_expires_at")
        if expires:
            remaining=parse_iso(expires)-now
            if remaining.total_seconds() <= 0:
                token_state="expired"
            elif remaining <= timedelta(days=1):
                token_state=f"expires in {max(int(remaining.total_seconds()//3600),0)}h"
            else:
                token_state=f"expires in {remaining.days}d"
        else:
            token_state="expiry unknown"
        last_poll=gu.get("last_poll_at")
        last_success=gu.get("last_success_at")
        last_error=gu.get("last_error")
        failures=max(int(gu.get("consecutive_failures",0) or 0),0)
        if failures:
            health_state=f"degraded · {failures} consecutive failure(s)"
        elif last_success:
            health_state="healthy"
        else:
            health_state="not checked successfully yet"
        health=f"health: **{health_state}**"
        health += f" · last poll {last_poll}" if last_poll else " · no poll recorded yet"
        health += f" · last success {last_success}" if last_success else " · no successful poll yet"
        if last_error:
            health += f" · last error: {last_error}"
        lines.append(f"• <@{uid}> — SIMKL: **{username}** · token: **{token_state}**\n  {health}")
    linked="\n".join(lines) if lines else "No currently linked accounts."
    tracking_total=len(users)
    stale_note=f" · **{stale_count} stale record(s)**" if stale_count else ""
    await i.response.send_message(
        f"**Posting channel:** {text}\n"
        f"**Poll interval:** every {POLL_INTERVAL_MINUTES} minute(s)\n"
        f"**Tracking records:** {tracking_total} · **Current members:** {current_count}{stale_note}\n\n"
        f"**Linked accounts in this server:**\n{linked}",
        ephemeral=True,
    )

@bot.tree.command(name="simkl-checknow",description="(Admin) Immediately check this server's SIMKL activity.")
async def simkl_checknow(i):
    global last_checknow_at
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    if time.monotonic()-last_checknow_at<CHECKNOW_COOLDOWN_SECONDS:
        await i.response.send_message("Please wait before using /simkl-checknow again.",ephemeral=True); return
    if poll_lock.locked(): await i.response.send_message("A SIMKL activity check is already running.",ephemeral=True); return
    last_checknow_at=time.monotonic()
    await i.response.send_message("Checking this server's SIMKL activity now...",ephemeral=True)
    posted=await poll_all(g)
    await i.followup.send(f"Done. Posted **{posted}** new activity item(s). Check the bot logs if this says 0.",ephemeral=True)

POLL_RETRY_DELAY_SECONDS=60
POLL_MAX_RETRY_DELAY_SECONDS=600

@bot.event
async def on_ready():
    log.info("Logged in as %s.",bot.user)
    for g in bot.guilds:
        await storage.ensure_guild(g.id)
    poll_task = getattr(bot, "_poll_task", None)
    if poll_task is None or poll_task.done():
        bot._poll_task = bot.loop.create_task(polling_loop(), name="simkl-polling")

async def polling_loop():
    await bot.wait_until_ready()
    retry_delay=POLL_RETRY_DELAY_SECONDS
    interval_seconds=POLL_INTERVAL_MINUTES*60
    next_run=time.monotonic()
    while not bot.is_closed():
        try:
            await poll_all()
            retry_delay=POLL_RETRY_DELAY_SECONDS
            next_run+=interval_seconds
            sleep_for=max(0,next_run-time.monotonic())
            if sleep_for:
                await asyncio.sleep(sleep_for)
            else:
                log.warning("Polling cycle exceeded the configured interval; starting the next cycle immediately.")
                next_run=time.monotonic()
        except Exception:
            log.exception("Polling cycle failed; retrying sooner instead of waiting for the full interval.")
            await asyncio.sleep(retry_delay)
            retry_delay=min(retry_delay*2,POLL_MAX_RETRY_DELAY_SECONDS)
            next_run=time.monotonic()
if __name__=="__main__": bot.run(DISCORD_BOT_TOKEN)
