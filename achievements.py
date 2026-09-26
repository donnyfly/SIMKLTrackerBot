"""Achievement definitions for SIMKLTrackerBot.

Achievements are intentionally challenging so higher tiers feel meaningful
rather than being awarded for routine activity.
"""

ACHIEVEMENTS = {
    "first_watch": {
        "name": "First Watch",
        "emoji": "🎬",
        "description": "Record your first watch.",
        "category": "total",
        "threshold": 1,
        "xp": 100,
    },
    "episodes_50": {
        "name": "Seasoned Watcher",
        "emoji": "📺",
        "description": "Watch 50 episodes.",
        "category": "episodes",
        "threshold": 50,
        "xp": 250,
    },
    "episodes_250": {
        "name": "Binge Master",
        "emoji": "📚",
        "description": "Watch 250 episodes.",
        "category": "episodes",
        "threshold": 250,
        "xp": 500,
    },
    "episodes_1000": {
        "name": "Episode Veteran",
        "emoji": "🏅",
        "description": "Watch 1,000 episodes.",
        "category": "episodes",
        "threshold": 1000,
        "xp": 1000,
    },
    "episodes_2500": {
        "name": "Episode Legend",
        "emoji": "👑",
        "description": "Watch 2,500 episodes.",
        "category": "episodes",
        "threshold": 2500,
        "xp": 2000,
    },
    "movies_25": {
        "name": "Movie Regular",
        "emoji": "🍿",
        "description": "Watch 25 movies.",
        "category": "movies",
        "threshold": 25,
        "xp": 250,
    },
    "movies_100": {
        "name": "Movie Buff",
        "emoji": "🎞️",
        "description": "Watch 100 movies.",
        "category": "movies",
        "threshold": 100,
        "xp": 500,
    },
    "movies_250": {
        "name": "Cinephile",
        "emoji": "🎥",
        "description": "Watch 250 movies.",
        "category": "movies",
        "threshold": 250,
        "xp": 1000,
    },
    "anime_250": {
        "name": "Anime Devotee",
        "emoji": "🌸",
        "description": "Watch 250 anime episodes.",
        "category": "anime_episodes",
        "threshold": 250,
        "xp": 500,
    },
    "anime_1000": {
        "name": "Anime Veteran",
        "emoji": "🌟",
        "description": "Watch 1,000 anime episodes.",
        "category": "anime_episodes",
        "threshold": 1000,
        "xp": 1000,
    },
    "anime_2500": {
        "name": "Anime Legend",
        "emoji": "💮",
        "description": "Watch 2,500 anime episodes.",
        "category": "anime_episodes",
        "threshold": 2500,
        "xp": 2000,
    },
    "total_250": {
        "name": "Dedicated Watcher",
        "emoji": "🏆",
        "description": "Watch 250 total items.",
        "category": "total",
        "threshold": 250,
        "xp": 250,
    },
    "total_1000": {
        "name": "Committed Watcher",
        "emoji": "💎",
        "description": "Watch 1,000 total items.",
        "category": "total",
        "threshold": 1000,
        "xp": 750,
    },
    "total_2500": {
        "name": "Elite Watcher",
        "emoji": "🥇",
        "description": "Watch 2,500 total items.",
        "category": "total",
        "threshold": 2500,
        "xp": 1500,
    },
    "total_5000": {
        "name": "Legendary",
        "emoji": "👑",
        "description": "Watch 5,000 total items.",
        "category": "total",
        "threshold": 5000,
        "xp": 3000,
    },
    "streak_30": {
        "name": "Monthly Dedication",
        "emoji": "🔥",
        "description": "Maintain a 30-day watch streak.",
        "category": "streak",
        "threshold": 30,
        "xp": 500,
    },
    "streak_100": {
        "name": "Unstoppable",
        "emoji": "⚡",
        "description": "Maintain a 100-day watch streak.",
        "category": "streak",
        "threshold": 100,
        "xp": 1500,
    },
    "streak_365": {
        "name": "Year-Round Watcher",
        "emoji": "🌠",
        "description": "Maintain a 365-day watch streak.",
        "category": "streak",
        "threshold": 365,
        "xp": 3000,
    },
}


def get_achievement(achievement_id):
    return ACHIEVEMENTS.get(achievement_id)


def all_achievements():
    return list(ACHIEVEMENTS.items())
