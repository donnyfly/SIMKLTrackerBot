"""Achievement definitions for SIMKLTrackerBot.

Achievements are data-driven so unlock logic can be implemented separately
from the definitions and presented consistently in Discord.
"""

ACHIEVEMENTS = {
    "first_watch": {
        "name": "First Watch",
        "emoji": "🎬",
        "description": "Record your first watch.",
        "category": "total",
        "threshold": 1,
    },
    "episode_10": {
        "name": "Binge Starter",
        "emoji": "📺",
        "description": "Watch 10 episodes.",
        "category": "episodes",
        "threshold": 10,
    },
    "episode_100": {
        "name": "Century Club",
        "emoji": "💯",
        "description": "Watch 100 episodes.",
        "category": "episodes",
        "threshold": 100,
    },
    "episode_500": {
        "name": "Episode Legend",
        "emoji": "👑",
        "description": "Watch 500 episodes.",
        "category": "episodes",
        "threshold": 500,
    },
    "movie_10": {
        "name": "Movie Night",
        "emoji": "🍿",
        "description": "Watch 10 movies.",
        "category": "movies",
        "threshold": 10,
    },
    "movie_25": {
        "name": "Movie Buff",
        "emoji": "🎞️",
        "description": "Watch 25 movies.",
        "category": "movies",
        "threshold": 25,
    },
    "anime_episode_100": {
        "name": "Anime Addict",
        "emoji": "🌸",
        "description": "Watch 100 anime episodes.",
        "category": "anime_episodes",
        "threshold": 100,
    },
    "anime_episode_500": {
        "name": "Anime Veteran",
        "emoji": "🌟",
        "description": "Watch 500 anime episodes.",
        "category": "anime_episodes",
        "threshold": 500,
    },
    "watch_100": {
        "name": "Dedicated Watcher",
        "emoji": "🏆",
        "description": "Watch 100 total items.",
        "category": "total",
        "threshold": 100,
    },
    "watch_500": {
        "name": "Legendary",
        "emoji": "👑",
        "description": "Watch 500 total items.",
        "category": "total",
        "threshold": 500,
    },
}


def get_achievement(achievement_id):
    return ACHIEVEMENTS.get(achievement_id)


def all_achievements():
    return list(ACHIEVEMENTS.items())
