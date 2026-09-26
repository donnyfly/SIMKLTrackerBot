import asyncio
from datetime import date
from io import BytesIO
import tempfile

from PIL import Image

import storage as storage_module
from level_visuals import prestige_style, render_prestige_gif
from profile_visuals import profile_snapshot, render_profile_png, render_leaderboard_png
from progression import xp_for_level


def test_profile_recomputes_watch_and_genre_totals_each_view():
    stats={
        "episodes_watched":5,"movies_watched":1,
        "anime_episodes_watched":2,"anime_movies_watched":0,
        "watch_dates":{"2026-09-26":{"total":6}},
        "titles":{"one":{"title":"Example","count":5,"last_watched":"2026-09-26T03:00:00Z","genres":["Drama"]}},
    }
    progression={"xp":xp_for_level(10),"prestige":1,"lifetime_xp":100000,"xp_events":[],"challenge_completions":{}}
    first=profile_snapshot(stats,progression,{},1,3,today=date(2026,9,26))
    assert (first["level"],first["total"],first["top_genres"]) == (10,6,[("Drama",5)])
    first_image=render_profile_png("Viewer",first)
    assert Image.open(first_image).size==(1080,1065)
    stats["episodes_watched"]+=1
    stats["titles"]["one"]["count"]+=1
    second=profile_snapshot(stats,progression,{"first_watch":{}},1,3,today=date(2026,9,26))
    assert second["total"]==7
    assert second["achievements"]==1
    assert second["top_genres"]==[("Drama",6)]
    assert first_image.getvalue()!=render_profile_png("Viewer",second).getvalue()


def test_empty_genre_state_and_leaderboard_card():
    stats={"episodes_watched":1,"movies_watched":0,"titles":{},"watch_dates":{}}
    snapshot=profile_snapshot(stats,{"xp":0}, {},0,0,today=date(2026,9,26))
    assert snapshot["top_genres"]==[]
    board=render_leaderboard_png("Server","XP progression",[
        {"name":"Viewer","prestige":1,"level":9,"xp":500,"total":5},
    ])
    assert Image.open(board).size==(1080,845)


def test_prestige_emblems_and_accents_vary():
    styles=[prestige_style(n) for n in range(1,13)]
    assert len(set(color for color,_ in styles))==12
    assert len(set(icon for _,icon in styles))==6
    for number in (1,2,3,6):
        gif=Image.open(render_prestige_gif(number))
        assert gif.size==(720,280)
        assert gif.n_frames>1


def test_prestige_update_is_atomic():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            previous=storage_module.DATA_PATH
            storage_module.DATA_PATH=f"{directory}/store.json"
            try:
                store=storage_module.Storage()
                await store.link_user("123","42","token",None,"viewer","2026-09-26T00:00:00Z")
                await store.award_watch_xp("42","seed","episode","Example","2026-09-26T00:00:00Z",xp_for_level(100))
                assert sorted(await asyncio.gather(store.prestige_user("42"),store.prestige_user("42")))==[False,True]
                state=await store.get_progression("42")
                assert state["prestige"]==1 and state["xp"]==0
            finally:
                storage_module.DATA_PATH=previous
    asyncio.run(scenario())
