# SIMKLTrackerBot

A self-hosted Discord bot that automatically tracks your **SIMKL** watch activity and posts it to a Discord channel.

SIMKLTrackerBot supports **TV shows, anime, and movies**, with automatic account authentication, activity tracking, artwork, ratings, episode grouping, customizable embeds, and multi-server support.

Everything is self-hosted, and linked SIMKL account data is stored locally on your own server.

<img width="400" height="" alt="simkldiscordbotsample7" src="https://github.com/user-attachments/assets/62b58b48-a792-4b67-99df-6741f9d742b4" />

<img width="400" height="" alt="simkldiscordbotsample8" src="https://github.com/user-attachments/assets/82ffdb47-6a17-4cfb-96bc-a6ae2fa1c929" />

<img width="400" height="" alt="simkldiscordbotsample12" src="https://github.com/user-attachments/assets/c51ab135-a55f-4b6f-b711-01d4b9171095" />

<img width="400" height="" alt="simkldiscordbotsample9" src="https://github.com/user-attachments/assets/e3c04ba3-47b1-4026-987b-87161fc6ac7b" />

---

# Features & Commands

## Features

- 🎬 Tracks **TV shows, anime, and movies** from SIMKL

- ⭐ IMDb ratings for movies and individual TV/anime episodes when available
- 🌸 MyAnimeList ratings for anime movies when available
- 🎨 Multiple embed styles
- ✍️ Short or detailed activity text
- 📺 Groups consecutive episodes into a single Discord message
- 🖼️ TMDB artwork with SIMKL poster fallback
- ⚙️ Per-user and server-wide rating visibility controls
- 🔗 Clickable SIMKL titles
- 🔗 Users link their own SIMKL accounts through Discord
- 🔄 Automatically refreshes SIMKL authentication tokens
- 📊 Uses incremental activity syncing to reduce unnecessary API requests
- ⏱️ Configurable automatic polling
- 🏠 Supports multiple Discord servers
- 💾 Stores data locally in `data/store.json`
- 🐳 Docker support with a pre-built image
- 📊 Personal and server watch statistics
- 🔥 Watch streak tracking
- 🏆 Server watch leaderboards
- 📈 XP levels, ranks, and prestige progression
- 🎯 Daily and weekly watch challenges
- 🛠️ Administrator tools for configuration and manual checks

## Commands

| Command | Permission | What it does |
| --- | --- | --- |
| `/simkl-stats`, `/simkl-profile` | Everyone | Render a fresh profile card with watch, XP, streak, and achievement statistics |
| `/simkl-streak` | Everyone | View your current and longest watch streak |
| `/simkl-leaderboard` | Everyone | View a visual server leaderboard for watches, XP, level, or prestige |
| `/simkl-link` | Everyone | Link your SIMKL account to the bot |
| `/simkl-unlink` | Everyone | Unlink your SIMKL account |
| `/simkl-style` | Everyone | Set your personal embed, artwork, text, and rating preferences |
| `/simkl-setchannel` | Manage Server | Choose where watch activity is posted |
| `/simkl-style-server` | Manage Server | Set the server-wide default embed, text, and rating preferences |
| `/simkl-status` | Manage Server | View the server's configuration, linked users, and polling health |
| `/simkl-timezone` | Manage Server | View or set the server timezone used for dates, statistics, and streaks |
| `/simkl-weekly-recap` | Manage Server | Post a weekly watch recap; use the period option to test it immediately |
| `/simkl-challenges` | Everyone | View current daily and weekly watch challenges |
| `/simkl-prestige` | Everyone | Prestige after reaching Level 100 |
| `/simkl-user-reset` | Everyone | Reset your tracking history for the current server |
| `/simkl-debug` | Manage Server | Privately preview level-up, rank-up, achievement, or prestige notifications without changing progression |
| `/simkl-checknow` | Manage Server | Immediately check SIMKL for new activity |

### Weekly Recaps

Weekly recaps are automatically posted to the configured SIMKL activity channel every **Monday at 09:00** in the server's configured timezone. The automatic recap covers the previous Monday through Sunday.

Administrators can test the feature immediately with:

```text
/simkl-weekly-recap period: Current week
/simkl-weekly-recap period: Previous week
```

The test command posts the recap to the normal activity channel, so it tests the same posting path used by the automatic recap. The recap includes total watches, episode/movie/anime breakdowns, active days, active users, and the top watchers with Discord mentions.

## Progression

Users earn XP automatically from newly detected watch activity. Episodes award **100 XP** and movies award **300 XP**. XP is tracked globally for the Discord user, while watch statistics remain server-local.

Progression has 100 levels per prestige, with ranks ranging from **Newcomer** to **Screen Immortal**. Reaching Level 100 unlocks `/simkl-prestige`, which resets the current level progression while preserving lifetime XP, achievements, and watch statistics.

The bot also generates three daily and three weekly watch challenges. Completing a challenge grants bonus XP. Challenge progress is based on watch activity detected by the bot and is tracked separately from the server watch statistics.

Use `/simkl-profile` or `/simkl-stats` to see current XP, level, rank, prestige, lifetime XP, and the XP breakdown. `/simkl-leaderboard category: XP / progression` replaces the old XP leaderboard; `/simkl-challenges` and `/simkl-prestige` remain available. Each prestige gets a distinct color and a rotating insignia. The prestige command posts the animation after a successful reset.

Use `/simkl-debug feature: Level up` to preview the next level, `feature: Rank up` to preview the next rank (or choose a rank boundary with `level`), `feature: Achievement unlocked` with `achievement` to preview any achievement, and `feature: Prestige unlocked` with an optional `prestige` number. Only the admin sees these previews. They use the live notification layout and animated GIF, but do not unlock anything or change XP.

## Watch statistics

The bot keeps per-server watch statistics locally in `data/store.json`. Statistics are updated when activity is successfully processed and are seeded from existing watch history when a user first links their SIMKL account.

Available commands:

- `/simkl-profile` or `/simkl-stats` — Render the same profile PNG on each request. It includes level, rank, current and lifetime XP, XP breakdown, prestige, episode and movie counts, anime counts, streaks, achievements, recent and top titles, active days, last 30 days, and top genres when genre metadata is available. You can optionally select another member.
- `/simkl-streak` — View current and longest watch streaks.
- `/simkl-leaderboard` — View the top 10 users by total watches, episodes, movies, anime, XP progression, level, or prestige. Each row shows prestige, level, current XP, and total watches.

Profiles and leaderboards render from the latest locally recorded polling data; opening them does not make a new SIMKL API request. Historical title records lack genre metadata, so top genres appear as "No genre data yet" until SIMKL supplies genre tags for subsequently recorded watches.

### Embed customization

Activity messages can be customized using `/simkl-style`.

**Style**
- **Rich** — large landscape artwork
- **Minimal** — compact thumbnail

**Artwork**
- **Automatic** — chooses the most appropriate available artwork
- **Poster only** — uses poster artwork
- **Backdrop** — uses landscape backdrop artwork; when TMDB has a title logo, it is shown as a small thumbnail in the embed's corner

**Activity text**
- **Short** — compact activity messages
- **Detailed** — more information about the activity

Personal preferences override the server's defaults.

Administrators can use `/simkl-style-server` to configure the server-wide defaults.

---

# Installation

Docker Compose is the **recommended installation method**.

The bot can also be run directly with Python on Windows, Linux, or macOS.

## Docker Compose — Recommended

### Requirements

- A computer, home server, or VPS that can run Docker
- A Discord account
- A Discord server where you can add bots
- A SIMKL account
- Discord Bot Token
- SIMKL Client ID
- TMDB API key
- MDBList API key if you want ratings

### 1. Create the Discord bot

Open the Discord Developer Portal and create a new application.

Go to **Bot → Add Bot** and copy the bot token.

Then go to:

**OAuth2 → URL Generator**

Select these scopes:

- `bot`
- `applications.commands`

The bot needs permission to:

- Send Messages
- Read Message History

Use the generated URL to invite the bot to your Discord server.

Keep your bot token private.

### 2. Create a SIMKL application

Log in to SIMKL and create an application in the developer settings.

Copy the application's **Client ID**.

Users will link their own SIMKL accounts later using `/simkl-link`.

### 3. Get API keys

SIMKLTrackerBot uses:

- **TMDB** for artwork and episode information
- **MDBList** for movie/show IMDb and MyAnimeList ratings
- **IMDb's public ratings dataset** for individual episode IMDb ratings

The MDBList API key is optional. It is used for movie/show IMDb ratings and anime movie MyAnimeList ratings. Individual episode IMDb ratings use IMDb's public ratings dataset and do not require an MDBList API key.

### 4. Install Docker

Install Docker and make sure Docker Compose is available:

```bash
docker compose version
```

### 5. Create the bot directory

```bash
mkdir -p ~/simkl-discord-bot
cd ~/simkl-discord-bot
```

### 6. Create `docker-compose.yml`

```yaml
services:
  simkltrackerbot:
    image: ghcr.io/donnyfly/simkltrackerbot:latest
    container_name: simkltrackerbot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data
```

### 7. Create `.env`

```bash
nano .env
```

Add:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
TMDB_API_KEY=your_tmdb_api_key_here
MDBLIST_API_KEY=your_mdblist_api_key_here
POLL_INTERVAL_MINUTES=60
POLL_CONCURRENCY=5
```

The default polling interval is **60 minutes**, matching SIMKL's recommended polling interval.

You can change it for your own installation if desired.

### 8. Start the bot

```bash
sudo docker compose up -d
```

Check that it is running:

```bash
sudo docker compose ps
```

View the logs:

```bash
sudo docker compose logs -f
```

Once the bot is online, use `/simkl-link` in your Discord server to connect a SIMKL account.

Press `Ctrl+C` to stop viewing the logs. The bot will continue running.

---

## Docker CLI

Docker Compose is recommended, but you can also run the container directly.

Create the required directories:

```bash
mkdir -p ~/simkl-discord-bot/data
```

Create the environment file:

```bash
nano ~/simkl-discord-bot/.env
```

Use the same environment variables shown in the Docker Compose installation.

Run:

```bash
sudo docker run -d \
  --name simkltrackerbot \
  --restart unless-stopped \
  --env-file ~/simkl-discord-bot/.env \
  -v ~/simkl-discord-bot/data:/app/data \
  ghcr.io/donnyfly/simkltrackerbot:latest
```

View the logs:

```bash
sudo docker logs -f simkltrackerbot
```

---

## Windows — Python

Docker is recommended on Windows, but you can also run the bot directly with Python.

### Requirements

- Python 3.10 or newer
- Git

Check Python:

```powershell
python --version
```

Check Git:

```powershell
git --version
```

### Clone the repository

```powershell
git clone https://github.com/donnyfly/SIMKLTrackerBot.git
cd SIMKLTrackerBot
```

### Create a virtual environment

```powershell
python -m venv venv
```

Activate it:

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate again:

```powershell
.\venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### Create `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in your API keys and bot token.

### Start the bot

```powershell
python bot.py
```

For automatic startup after a reboot, Windows Task Scheduler can be used to launch the bot.

---

## Linux / macOS — Python

Docker is recommended, but you can run the bot directly with Python.

### Requirements

- Python 3.10 or newer
- Git

### Clone the repository

```bash
git clone https://github.com/donnyfly/SIMKLTrackerBot.git
cd SIMKLTrackerBot
```

### Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install dependencies

```bash
python -m pip install -r requirements.txt
```

### Create `.env`

```bash
cp .env.example .env
nano .env
```

Fill in your API keys and bot token.

### Start the bot

```bash
python bot.py
```

### Linux servers

For a Linux server where the bot should automatically start after reboot, you can run it using **systemd**.

Create:

```bash
sudo nano /etc/systemd/system/simkltrackerbot.service
```

Example:

```ini
[Unit]
Description=SIMKLTrackerBot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=username
WorkingDirectory=/home/username/SIMKLTrackerBot
ExecStart=/home/username/SIMKLTrackerBot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `username` and the paths with your actual account and installation directory.

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now simkltrackerbot
```

Check the service:

```bash
sudo systemctl status simkltrackerbot
```

View logs:

```bash
sudo journalctl -u simkltrackerbot -f
```

---

# Configuration

The main configuration is stored in `.env`.

Example:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
TMDB_API_KEY=your_tmdb_api_key_here
MDBLIST_API_KEY=your_mdblist_api_key_here
POLL_INTERVAL_MINUTES=60
POLL_CONCURRENCY=5
```

## Required settings

### `DISCORD_BOT_TOKEN`

Your Discord bot token.

### `SIMKL_CLIENT_ID`

Your SIMKL application's Client ID.

### `TMDB_API_KEY`

Used for artwork and episode information.

### `MDBLIST_API_KEY`

Optional. Used for IMDb and MyAnimeList ratings.

## Optional settings

### `POLL_INTERVAL_MINUTES`

Controls how often the bot checks SIMKL for new activity.

The default is:

```env
POLL_INTERVAL_MINUTES=60
```

This matches SIMKL's recommended polling interval.

You can choose a different interval for your own installation, for example:

```env
POLL_INTERVAL_MINUTES=15
```

Shorter intervals result in more frequent API requests.

Restart the bot after changing the setting.

### `SIMKL_DEFAULT_TIMEZONE`

Sets the default IANA timezone used for watch statistics and streaks.

The default is:

```env
SIMKL_DEFAULT_TIMEZONE=Asia/Singapore
```

Server administrators can override this per Discord server with:

```text
/simkl-timezone timezone: Asia/Singapore
```

Use `/simkl-timezone` without a value to view the current setting. Use `/simkl-timezone timezone: reset` to return to the environment/default timezone.

Timezone changes affect how **new watch activity** is assigned to calendar dates. Existing date-only statistics cannot be perfectly converted after the fact because the original timestamp for every historical event is not retained.

### `POLL_CONCURRENCY`

Controls how many different SIMKL users can be processed at the same time.

The default is:

```env
POLL_CONCURRENCY=5
```

The default value is suitable for most installations.

---

# How It Works

## Linking a SIMKL account

Each Discord user links their own SIMKL account using:

```text
/simkl-link
```

The bot uses SIMKL's authentication flow and stores the resulting account credentials locally.

Users do not need to give their SIMKL password to the bot.

When a user first links their account, existing watch history is synchronized so old activity is not posted as new activity.

## Activity tracking

The bot periodically checks SIMKL for changes.

It uses incremental syncing to avoid repeatedly downloading the user's entire watch history.

New activity can include:

- Watched
- Rewatched
- Started watching
- Completed
- Planned
- Dropped

## Episode grouping

Consecutive episodes are grouped together.

For example:

```text
S02E08
S02E09
S02E10
```

can be posted as one activity instead of three separate messages.

Non-consecutive episodes remain separate.

## Multiple Discord servers

One bot instance can be used across multiple Discord servers.

Server-specific settings such as:

- Activity channel
- Server embed defaults

are kept separate.

Users can use the same SIMKL account across servers without creating a separate SIMKL account.

## Ratings

Ratings are provided by two sources:

- **Movies** — IMDb ratings from MDBList
- **Individual TV/anime episodes** — IMDb ratings from IMDb's public ratings dataset
- **Anime movies** — IMDb and MyAnimeList ratings from MDBList

Individual/ranged episode activity is handled differently: a single episode can display its IMDb rating when available, while grouped/ranged episodes do not display an episode rating.

Ratings depend on the relevant source having the information available. The IMDb episode dataset is refreshed automatically and stored locally in `data/imdb_ratings.db`.

## Artwork

The bot uses TMDB artwork where available.

Episodes can use episode stills, while movies and other activity can use landscape or poster artwork depending on the selected settings.

If suitable TMDB artwork is unavailable, the bot can fall back to SIMKL artwork.

---

# Updating & Backups

## Docker Compose

Pull the latest image:

```bash
cd ~/simkl-discord-bot
sudo docker compose pull
sudo docker compose up -d
```

Your persistent data remains in:

```text
data/store.json
data/imdb_ratings.db
```

`data/imdb_ratings.db` is automatically rebuilt from IMDb's public ratings dataset when it is missing or older than 24 hours. The downloaded dataset is temporary and is removed after the database is built.

## Docker CLI

Pull the latest image:

```bash
sudo docker pull ghcr.io/donnyfly/simkltrackerbot:latest
```

Then recreate the container using the same `docker run` command from the installation section.

## Python

Update the repository:

```bash
git pull
```

Update dependencies:

```bash
python -m pip install -r requirements.txt
```

Restart the bot.

If using systemd:

```bash
sudo systemctl restart simkltrackerbot
```

## Backing up your data

The bot's persistent data is stored in:

```text
data/store.json
data/imdb_ratings.db
```

Back up `data/store.json` because it contains authentication information. The IMDb database can be regenerated automatically, so it does not need to be backed up.

For a simple backup:

```bash
cp data/store.json data/store.json.backup
```

---

# Troubleshooting

## Bot does not start

Check the logs.

### Docker Compose

```bash
sudo docker compose logs -f
```

### Docker

```bash
sudo docker logs -f simkltrackerbot
```

### Python

```bash
python bot.py
```

### systemd

```bash
sudo journalctl -u simkltrackerbot -f
```

## Slash commands are not appearing

Make sure the bot was invited with:

- `bot`
- `applications.commands`

Slash commands are synchronized globally, so newly added or changed commands may take some time to appear. Make sure the bot was invited with the `applications.commands` scope.

## Bot is online but does not post activity

Check that:

1. The user has linked their SIMKL account with `/simkl-link`.
2. A posting channel has been configured with `/simkl-setchannel`.
3. The bot has permission to send messages in that channel.
4. There is new SIMKL activity to report.
5. The bot is running normally.

Administrators can also use:

```text
/simkl-checknow
```

to manually trigger an activity check.

## Docker container keeps restarting

Check the last 100 log lines:

```bash
sudo docker compose logs --tail=100
```

Then check:

```bash
sudo docker compose ps
```

Configuration errors are reported when the bot starts.

---

# Security

Never commit or share:

- `.env`
- Discord bot tokens
- SIMKL authentication tokens
- `data/store.json`

Keep your bot's credentials private.

If your Discord bot token is accidentally exposed, regenerate it immediately through the Discord Developer Portal.

---

# License

This project is licensed under the MIT License.
