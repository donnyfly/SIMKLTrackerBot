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

load_dotenv()
DISCORD_BOT_TOKEN=os.getenv("DISCORD_BOT_TOKEN"); SIMKL_CLIENT_ID=os.getenv("SIMKL_CLIENT_ID"); TMDB_API_KEY=os.getenv("TMDB_API_KEY"); MDBLIST_API_KEY=os.getenv("MDBLIST_API_KEY"); GUILD_ID=os.getenv("GUILD_ID")
try: POLL_INTERVAL_MINUTES=max(int(os.getenv("POLL_INTERVAL_MINUTES","60")),1)
except ValueError: POLL_INTERVAL_MINUTES=60
if not DISCORD_BOT_TOKEN or not SIMKL_CLIENT_ID: raise SystemExit("Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID.")
if not TMDB_API_KEY: raise SystemExit("Missing TMDB_API_KEY.")

MEDIA_TYPES=("shows","anime","movies"); ACTIVITY_KEYS={"shows":"tv_shows","anime":"anime","movies":"movies"}
WATCHLIST_STATUSES=("watching","plantowatch","completed","dropped")
STATUS_TEXT={"watching":"started watching","plantowatch":"planned to watch","completed":"completed","dropped":"dropped"}
MEDIA_STYLES={"shows":(0x3498DB,"📺 TV"),"anime":(0xE91E63,"🌸 Anime"),"movies":(0xF1C40F,"🎬 Movie")}
HISTORY_FETCH_TIMEOUT_SECONDS=120; CHECKNOW_COOLDOWN_SECONDS=30
poll_lock=asyncio.Lock(); last_checknow_at=0.0; linking_users=set(); profile_lookup_attempted=set()
logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s"); log=logging.getLogger("simkl-bot")
simkl=SimklClient(SIMKL_CLIENT_ID); tmdb=TmdbClient(TMDB_API_KEY); mdblist=MdbListClient(MDBLIST_API_KEY) if MDBLIST_API_KEY else None

class SimklBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default()); self.tree=app_commands.CommandTree(self)
    async def setup_hook(self):
        if GUILD_ID:
            g=discord.Object(id=int(GUILD_ID)); self.tree.copy_global_to(guild=g); await self.tree.sync(guild=g); log.info("Slash commands synced to development guild %s.",GUILD_ID)
        else:
            await self.tree.sync(); log.info("Slash commands synced globally.")
    async def close(self):
        for client in (simkl,tmdb,mdblist):
            try: await client.close()
            except Exception: pass
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
    if not r: return None,e.get("episode_title")
    still=await tmdb.get_episode_still(r["series_id"],r["season_number"],r["episode_number"])
    return still,e.get("episode_title") or (r.get("episode") or {}).get("name")

async def prefs(g,u): return await storage.get_embed_preferences(g,u)
async def get_imdb_rating(media_type, tmdb_id):
    if mdblist is None or tmdb_id is None:
        return None
    try:
        return await mdblist.get_imdb_rating(media_type, tmdb_id)
    except Exception:
        log.warning("MDBList rating lookup failed for %s %s.", media_type, tmdb_id, exc_info=True)
        return None

def build_embed(t,desc,ts,name,member,image,profile,title=None,title_url=None,poster=None,preferences=None):
    color,label=MEDIA_STYLES[t]; p={"style":"rich","artwork":"auto","activity_text":"short"}; p.update(preferences or {})
    e=discord.Embed(title=title,url=title_url,description=desc,color=color,timestamp=ts)
    e.set_author(name=f"{name}'s Activity",url=profile,icon_url=member.display_avatar.url if member else None)
    selected=poster if p["artwork"]=="poster" or p["style"]=="poster" else image
    selected=selected or poster or image
    if selected:
        if p["style"]=="minimal": e.set_thumbnail(url=selected)
        else: e.set_image(url=selected)
    e.set_footer(text=f"{label} · SIMKL"); return e
async def send_embed(ch,e,what):
    try: await ch.send(embed=e); return True
    except Exception: log.exception("Failed to send %s embed.",what); return False

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

async def seed_history(g,uid,u,token):
    last=await storage.get_last_checked(g,uid); keys=[]; statuses={}; watches={}
    for t in MEDIA_TYPES:
        since=parse_iso(last.get(t,EPOCH_ISO)); items,token=await call_refresh(uid,u,token,simkl.get_all_items,t,timeout=HISTORY_FETCH_TIMEOUT_SECONDS)
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
                image,ep_title=await episode_media(t,grp[0])
            except Exception:
                log.warning("TMDB episode lookup failed for %s.", title, exc_info=True)
                image,ep_title=None,grp[0].get("episode_title")
            label=format_episode_range(sn,grp[0]["episode_number"],grp[-1]["episode_number"]); verb=kind
            rating = await get_imdb_rating("tv", grp[0].get("tmdb_id")) if len(grp) == 1 else None
            rating_text = f" · ⭐ IMDb {rating:.1f}/10" if rating is not None else ""
            desc=f"{verb} **{label}**{rating_text}"
            if p["activity_text"]=="detailed": desc=f"{verb} **{label}** of **{title}**{rating_text}"
            if len(grp)==1 and ep_title: desc+=f"\n*{ep_title}*"
            e=build_embed(t,desc,max(x["watched_dt"] for x in grp),name,member,image or fallback,profile,title,url,fallback,p)
            if not await send_embed(ch,e,"episode"): ok=False; continue
            await storage.add_announced(g,uid,[x["key"] for x in grp]); pending.update({x["key"]:x["watched_raw"] for x in grp}); count+=len(grp)
    if pending: await storage.update_activity_state(g,uid,watch_times=pending)
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
        rating = await get_imdb_rating("movie", ids.get("tmdb"))
        rating_text = f" · ⭐ IMDb {rating:.1f}/10" if rating is not None else ""
        verb="rewatched" if rw else "watched a movie"; desc=f"{verb}{rating_text}" if p["activity_text"]!="detailed" else f"{verb} **{title}**{rating_text}"
        e=build_embed("movies",desc,dt,name,member,image or poster,profile,title,simkl_title_url("movies",sid,ids.get("slug")),poster,p)
        if not await send_embed(ch,e,"movie"): ok=False; continue
        await storage.add_announced(g,uid,[k]); pending[k]=wr; count+=1
    if pending: await storage.update_activity_state(g,uid,watch_times=pending)
    return count,ok

async def process_status(ch,g,uid,name,member,t,items,profile):
    state=await storage.get_activity_state(g,uid); statuses=state["statuses"]; baseline=not state["statuses_seeded"]; p=await prefs(g,uid); pending={}; count=0; ok=True
    for x in items or []:
        m=(x.get("movie") if t=="movies" else x.get("show")) or {}; ids=m.get("ids") or {}; sid=ids.get("simkl"); status=x.get("status")
        if sid is None or status not in WATCHLIST_STATUSES: continue
        key=f"{t}:{sid}"; pending[key]=status
        if baseline or statuses.get(key)==status: continue
        title=m.get("title") or "Untitled"; poster=simkl_poster_url(m.get("poster")); image=None
        if ids.get("tmdb") is not None:
            try:
                image=await (tmdb.get_movie_backdrop(ids["tmdb"]) if t=="movies" else tmdb.get_tv_backdrop(ids["tmdb"]))
            except Exception:
                log.warning("TMDB status artwork lookup failed for %s.", title, exc_info=True)
        rating = await get_imdb_rating("movie" if t=="movies" else "tv", ids.get("tmdb"))
        rating_text = f" · ⭐ IMDb {rating:.1f}/10" if rating is not None else ""
        desc=f"{STATUS_TEXT[status]}{rating_text}" if p["activity_text"]!="detailed" else f"{STATUS_TEXT[status]} **{title}**{rating_text}"
        e=build_embed(t,desc,datetime.now(timezone.utc),name,member,image or poster,profile,title,simkl_title_url(t,sid,ids.get("slug")),poster,p)
        if not await send_embed(ch,e,status): ok=False; continue
        count+=1
    if pending and ok: await storage.update_activity_state(g,uid,statuses=pending,statuses_seeded=True)
    return count,ok

async def poll_one(ch,g,uid,u,gu):
    token=await valid_token(uid,u)
    member,name=await resolve_member(g,uid)
    if not member:
        log.warning("User %s is no longer a member of guild %s; skipping.",uid,g)
        return 0
    try:
        activities,token=await call_refresh(uid,u,token,simkl.get_activities)
    except Exception:
        log.exception("Failed to get SIMKL activity timestamps for user %s.",uid)
        return 0
    if not gu.get("history_seeded"):
        try:
            token=await seed_history(g,uid,u,token)
            gu["history_seeded"]=True
        except Exception:
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
    for t in MEDIA_TYPES:
        since=last.get(t,EPOCH_ISO)
        sdt=parse_iso(since)
        a=activities.get(ACTIVITY_KEYS[t]) or {}
        stamp=a.get("all")
        log.info("Check %s/%s: SIMKL %s activity=%r checkpoint=%s",g,uid,t,stamp,since)
        if not stamp or parse_iso(stamp)<=sdt:
            continue
        try:
            items,token=await call_refresh(uid,u,token,simkl.get_all_items,t,date_from=since)
            sc,so=await process_status(ch,g,uid,name,member,t,items,profile)
            wc,wo=await (process_movies(ch,g,uid,name,member,items,sdt,profile) if t=="movies" else process_shows(ch,g,uid,name,member,t,items,profile))
            if so and wo:
                await storage.update_last_checked(g,uid,t,to_iso(parse_iso(stamp)))
                posted+=wc
            else:
                log.warning("Some %s posts failed for user %s; checkpoint not advanced.",t,uid)
        except Exception:
            log.exception("Failed processing %s activity for user %s.",t,uid)
        await storage.flush()
    return posted

async def poll_all(g=None):
    targets=await storage.get_poll_targets(g)
    posted=0
    for x in targets:
        ch=bot.get_channel(int(x["channel_id"]))
        if ch is None:
            try: ch=await bot.fetch_channel(int(x["channel_id"]))
            except Exception: continue
        try: posted+=await poll_one(ch,int(x["guild_id"]),x["discord_user_id"],x["user_data"],x["guild_user_data"])
        except SimklAuthError: log.warning("Auth failed for %s.",x["discord_user_id"])
        except Exception: log.exception("Polling failed for %s.",x["discord_user_id"])
    return posted

STYLE_CHOICES=[app_commands.Choice(name="Rich (large artwork)",value="rich"),app_commands.Choice(name="Minimal (small artwork)",value="minimal"),app_commands.Choice(name="Poster (large poster)",value="poster")]
ARTWORK_CHOICES=[app_commands.Choice(name="Automatic",value="auto"),app_commands.Choice(name="Poster only",value="poster")]
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

@bot.tree.command(name="simkl-setchannel",description="(Admin) Set the channel where this server's watch activity is posted.")
async def simkl_setchannel(i,channel:discord.TextChannel=None):
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    target=channel or i.channel; await storage.set_channel(g,target.id); await i.response.send_message(f"Watch activity for this server will now be posted in {target.mention}.",ephemeral=True)

@bot.tree.command(name="simkl-status",description="(Admin) Show this server's configuration and linked accounts.")
async def simkl_status(i):
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    d=await storage.get_all(); sg=(d.get("guilds") or {}).get(str(g),{}); users=sg.get("users") or {}; allu=d.get("users") or {}; ch=sg.get("channel_id"); text=f"<#{ch}>" if ch else "**not set**"
    linked="\n".join(f"• <@{uid}> — SIMKL: **{(allu.get(uid) or {}).get('simkl_username','unknown')}**" for uid in users) if users else "No linked accounts."
    await i.response.send_message(f"**Posting channel:** {text}\n**Poll interval:** every {POLL_INTERVAL_MINUTES} minute(s)\n\n**Linked accounts in this server:**\n{linked}",ephemeral=True)

@bot.tree.command(name="simkl-checknow",description="(Admin) Immediately check this server's SIMKL activity.")
async def simkl_checknow(i):
    global last_checknow_at
    g=guild_id(i)
    if not g or not is_admin(i): await i.response.send_message(NOT_ADMIN_MESSAGE,ephemeral=True); return
    if time.monotonic()-last_checknow_at<CHECKNOW_COOLDOWN_SECONDS:
        await i.response.send_message("Please wait before using /simkl-checknow again.",ephemeral=True); return
    if poll_lock.locked(): await i.response.send_message("A SIMKL activity check is already running.",ephemeral=True); return
    await poll_lock.acquire(); last_checknow_at=time.monotonic()
    try:
        await i.response.send_message("Checking this server's SIMKL activity now...",ephemeral=True)
        posted=await poll_all(g)
    finally:
        poll_lock.release()
    await i.followup.send(f"Done. Posted **{posted}** new activity item(s). Check the bot logs if this says 0.",ephemeral=True)

poll_task_started=False
@bot.event
async def on_ready():
    global poll_task_started
    log.info("Logged in as %s.",bot.user)
    for g in bot.guilds:
        await storage.ensure_guild(g.id)
    if not poll_task_started:
        poll_task_started=True; bot.loop.create_task(polling_loop())

async def polling_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try: await poll_all()
        except Exception: log.exception("Polling cycle failed.")
        await asyncio.sleep(POLL_INTERVAL_MINUTES*60)

if __name__=="__main__": bot.run(DISCORD_BOT_TOKEN)
