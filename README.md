# SIMKL Activity Tracker for Discord

A self-hosted Discord bot that monitors your SIMKL watch activity and posts new watches to a Discord channel.

The bot supports TV shows, anime, and movies, with automatic SIMKL token refresh, clickable SIMKL titles, configurable embeds, consecutive episode grouping, TMDB artwork, multi-server support, and persistent local storage.

<img width="400" height="" alt="simkldiscordbotsample4" src="https://github.com/user-attachments/assets/7bb75ae5-200e-47e6-822a-f5110152cba2" />
<img width="212" height="" alt="simkldiscordbotsample6" src="https://github.com/user-attachments/assets/1189412b-92f7-4c01-9cac-0a428a27a808" />
<img width="600" height="" alt="simkldiscordbotsample5" src="https://github.com/user-attachments/assets/fd39a2af-26b9-420d-89e5-dea00a04ac0f" />




*Embed styles are selectable via Discord slash commands*


## Features

* 🎬 Tracks TV shows, anime, and movies (watching, planned, dropped, started watching, completed)
* 🔗 Users link their own SIMKL accounts through Discord
* 🔄 Automatically refreshes SIMKL authentication tokens
* ⏱️ Polls SIMKL for new activity at a configurable interval (15 minutes is the recommended production value for this self-hosted setup)
* ⚡ Processes different SIMKL users concurrently with a configurable worker limit
* 📊 Uses incremental syncing and `/sync/activities` to minimize unnecessary API requests
* 📺 Groups consecutive episodes into a single Discord message
* 🖼️ Uses TMDB landscape artwork for episodes, movies, and planned activity, with SIMKL poster fallback
* 🎨 Configurable embed styles: Rich, Minimal, or Poster
* ✍️ Configurable Short or Detailed activity text
* 🔗 Makes titles clickable to their SIMKL pages
* 🏠 Supports multiple Discord servers with per-server channels and defaults
* 💾 Stores bot data locally in a lightweight JSON file
* 🔐 SIMKL account tokens stay on your own server
* 🐳 Docker support with a pre-built image on GitHub Container Registry
* ⚙️ Can also be run directly with Python and systemd
* ⭐ Displays IMDb ratings for movies and TV/anime titles when available
* 🌸 Displays MyAnimeList (MAL) ratings for anime when available
* 🛠️ Includes administrator commands for configuration and manual checks

---

# Requirements

You will need:

* A computer, home server, or VPS that can run the bot continuously
* Python 3.10+ if running without Docker
* A Discord account
* A Discord server where you have permission to add bots
* A SIMKL account
* A Discord Bot Token
* A SIMKL Client ID
* A TMDB API key (for selectable poster/backdrop styles)
* A MDBList API key (for ratings on embeds)

---

# 1. Discord Bot Setup

## Create the Discord Application

1. Open the Discord Developer Portal.
2. Click **New Application**.
3. Give your application a name.
4. Open the **Bot** section.
5. Click **Add Bot**.
6. Copy the bot token.

Keep the bot token private. Do not commit it to GitHub.

## Invite the bot

Go to:

**OAuth2 → URL Generator**

Select:

### Scopes

* `bot`
* `applications.commands`

### Bot Permissions

The bot needs permission to:

* Send Messages
* Read Message History

Generate the invite URL and invite the bot to your Discord server.

> The administrator commands use the **Manage Server** permission.

---

# 2. SIMKL Setup

The bot uses the SIMKL API with **SIMKL AUTH V2**.

1. Log in to your SIMKL account.
2. Open the SIMKL developer settings.
3. Create an application.
4. Copy the application's **Client ID**.

You only need the Client ID. The bot uses SIMKL's device/PIN authentication flow when users link their accounts.

---

# 3. Configuration

The bot uses the following environment variables:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
TMDB_API_KEY=your_tmdb_api_key_here
MDBLIST_API_KEY=your_mdblist_api_key_here
GUILD_ID=
POLL_INTERVAL_MINUTES=15
POLL_CONCURRENCY=5
```

## `DISCORD_BOT_TOKEN`

Your Discord bot token.

## `SIMKL_CLIENT_ID`

Your SIMKL application's Client ID.

## `TMDB_API_KEY`

Your TMDB API key. TMDB is used for episode stills, episode titles, TV/movie backdrops, and anime episode resolution.

## `MDBLIST_API_KEY`

Optional MDBList API key. When configured, the bot can display ratings from MDBList for movies and TV/anime titles. IMDb ratings are shown for movies and TV/anime, while anime can also show its MyAnimeList (MAL) rating when MDBList provides one. MDBList provides a free API tier with 1,000 requests per day. The bot caches ratings in memory for 6 hours to avoid unnecessary requests.

Get an API key from your MDBList account preferences.

## `GUILD_ID`

Optional.

Set this to the ID of your Discord server if you want the bot to sync slash commands directly to that server.

Example:

```env
GUILD_ID=123456789012345678
```

If you leave it empty, the bot will use its normal global command synchronization.

## `POLL_INTERVAL_MINUTES`

Controls how often the bot automatically checks SIMKL for new activity.

The default is:

```env
POLL_INTERVAL_MINUTES=60
```

This means the bot checks SIMKL every **15 minutes** in the recommended production setup when using the example configuration.

If the variable is omitted, the application keeps its legacy 60-minute fallback. Invalid or non-positive values are rejected at startup instead of silently falling back.

You can change this value to suit your needs.

For example, to check every 30 minutes:

```env
POLL_INTERVAL_MINUTES=30
```

Or every 15 minutes:

```env
POLL_INTERVAL_MINUTES=15
```

The value is measured in minutes.

If you remove `POLL_INTERVAL_MINUTES` from your `.env` file, the bot will automatically use the default of **60 minutes**.

5–15 minutes is fine for **PRO/VIP users**; Free users should prefer **30–60 minutes** to stay under the daily quota.

After changing the polling interval, restart the bot for the new value to take effect.


The `/simkl-checknow` command can be used by administrators to manually check for new activity without waiting for the next scheduled poll. A short cooldown prevents repeated manual checks from generating unnecessary API requests.

---

# 4. Docker Compose — Recommended

Docker Compose is the recommended installation method for most users.

## Install Docker

Install Docker using the official Docker documentation.

Make sure Docker Compose is available:

```bash
docker compose version
```

## Create a directory

```bash
mkdir -p ~/simkl-discord-bot
cd ~/simkl-discord-bot
```

## Create the Compose file

Create `docker-compose.yml`:

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

Create the persistent data directory:

```bash
mkdir -p data
```

## Create the environment file

Create `.env`:

```bash
nano .env
```

Add:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
TMDB_API_KEY=your_tmdb_api_key_here
MDBLIST_API_KEY=your_mdblist_api_key_here
GUILD_ID=
POLL_INTERVAL_MINUTES=60
```

Save the file.

## Start the bot

```bash
sudo docker compose up -d
```

Check the container:

```bash
sudo docker compose ps
```

View the logs:

```bash
sudo docker compose logs -f
```

The bot should eventually log in to Discord successfully.

Press `Ctrl+C` to stop following the logs. This does not stop the container.

## Updating the bot

The Docker image is automatically published to GitHub Container Registry whenever a new commit is pushed to the `main` branch.

To update your installation:

```bash
cd ~/simkl-discord-bot
sudo docker compose pull
sudo docker compose up -d
```

Your persistent data remains in:

```text
data/store.json
```

---

# 5. Docker CLI

You can also run the bot without Docker Compose.

Create the persistent data directory:

```bash
mkdir -p ~/simkl-discord-bot/data
```

Create your `.env` file:

```bash
nano ~/simkl-discord-bot/.env
```

Add:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
GUILD_ID=
POLL_INTERVAL_MINUTES=60
```

Run the container:

```bash
sudo docker run -d \
  --name simkltrackerbot \
  --restart unless-stopped \
  --env-file ~/simkl-discord-bot/.env \
  -v ~/simkl-discord-bot/data:/app/data \
  ghcr.io/donnyfly/simkltrackerbot:latest
```

Check the container:

```bash
sudo docker ps
```

View logs:

```bash
sudo docker logs -f simkltrackerbot
```

To update the image:

```bash
sudo docker pull ghcr.io/donnyfly/simkltrackerbot:latest
```

Then stop and remove the existing container:

```bash
sudo docker stop simkltrackerbot
sudo docker rm simkltrackerbot
```

Recreate it using the same `docker run` command above.

---

# 6. Windows — Python

If you are running the bot directly on Windows without Docker, you can use Python and a virtual environment.

## Install Python

Install Python for Windows.

After installation, open **PowerShell** and check:

```powershell
python --version
```

You should see a Python version such as:

```text
Python 3.14.x
```

If `python` is not recognized, try:

```powershell
py --version
```

## Install Git

Git is recommended for downloading and updating the repository.

After installing Git, verify it:

```powershell
git --version
```

## Clone the repository

```powershell
git clone https://github.com/donnyfly/SIMKLTrackerBot.git
cd SIMKLTrackerBot
```

## Create a virtual environment

```powershell
python -m venv venv
```

## Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

You should see `(venv)` at the beginning of your PowerShell prompt.

For example:

```text
(venv) PS C:\Users\YourName\SIMKLTrackerBot>
```

### PowerShell execution policy

If PowerShell refuses to run `Activate.ps1`, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate the environment again:

```powershell
.\venv\Scripts\Activate.ps1
```

## Install dependencies

```powershell
python -m pip install -r requirements.txt
```

## Create your environment file

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Open it:

```powershell
notepad .env
```

Set your values:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
GUILD_ID=
POLL_INTERVAL_MINUTES=60
```

Save the file.

You can change `POLL_INTERVAL_MINUTES` if you want the bot to check SIMKL more or less frequently.

## Start the bot

```powershell
python bot.py
```

The bot should log in to Discord and begin polling SIMKL.

### Keeping the bot running on Windows

If you want the bot to automatically start after a reboot, you can configure **Windows Task Scheduler** to launch:

```text
venv\Scripts\python.exe
```

with:

```text
bot.py
```

as the argument.

Set the task's **Start in** directory to the root of the `SIMKLTrackerBot` folder.

---

# 7. Manual Python Installation

If you do not want to use Docker, the bot can be run directly with Python on Linux or macOS.

## Clone the repository

```bash
git clone https://github.com/donnyfly/SIMKLTrackerBot.git
cd SIMKLTrackerBot
```

## Create a virtual environment

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

## Install dependencies

```bash
python -m pip install -r requirements.txt
```

## Create your environment file

```bash
cp .env.example .env
```

Edit it:

```bash
nano .env
```

Set your values:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
GUILD_ID=
POLL_INTERVAL_MINUTES=60
```

## Start the bot

```bash
python bot.py
```

---

# 8. Python + systemd

For a Linux server, systemd can keep the bot running automatically and start it after a reboot.

First, make sure you have completed the manual Python installation above.

Find the full path to Python:

```bash
pwd
```

If your repository is located at:

```text
/home/username/SIMKLTrackerBot
```

then your virtual environment Python will be:

```text
/home/username/SIMKLTrackerBot/venv/bin/python
```

Create a systemd service:

```bash
sudo nano /etc/systemd/system/simkltrackerbot.service
```

Use:

```ini
[Unit]
Description=SIMKL Tracker Discord Bot
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

Replace:

* `username`
* `/home/username/SIMKLTrackerBot`

with your actual username and repository path.

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable the service:

```bash
sudo systemctl enable simkltrackerbot
```

Start it:

```bash
sudo systemctl start simkltrackerbot
```

Check the status:

```bash
sudo systemctl status simkltrackerbot
```

View live logs:

```bash
sudo journalctl -u simkltrackerbot -f
```

---

# 9. Discord Commands

The bot provides the following slash commands.

| Command             | Permission    | Description                              |
| ------------------- | ------------- | ---------------------------------------- |
| `/simkl-link`       | Everyone      | Link your SIMKL account                  |
| `/simkl-unlink`     | Everyone      | Unlink your SIMKL account                |
| `/simkl-setchannel` | Manage Server | Set the channel where activity is posted |
| `/simkl-status`     | Manage Server | View the bot's current status            |
| `/simkl-checknow`   | Manage Server | Manually check SIMKL for new activity    |
| `/simkl-style`      | Everyone      | Set your personal embed preferences     |
| `/simkl-style-server` | Manage Server | Set the server-wide embed defaults    |

## `/simkl-link`

Each Discord user links their own SIMKL account.

The bot uses SIMKL's AUTH V2 device/PIN flow.

Once linked, the bot tracks new activity for that user.

The bot does not intentionally dump a user's entire existing SIMKL watch history into Discord when they first link their account.

## `/simkl-unlink`

Removes the user's SIMKL account connection from the bot.

## `/simkl-setchannel`

Sets the Discord channel where SIMKL activity should be posted.

Requires the **Manage Server** permission.

## `/simkl-status`

Displays the bot's current configuration and tracking status.

Requires the **Manage Server** permission.

## `/simkl-checknow`

Immediately checks SIMKL for new activity instead of waiting for the next scheduled poll.

Requires the **Manage Server** permission.

---

# 10. Embed Styles and Activity Types

Embed appearance is split into three independent settings:

* **Style**
  * **Rich** — large landscape artwork
  * **Minimal** — small artwork thumbnail
  * **Poster** — large portrait poster
* **Artwork**
  * **Automatic** — use the best available artwork for the activity
  * **Poster only** — prefer poster artwork
* **Activity text**
  * **Short** — compact activity messages
  * **Detailed** — more descriptive activity messages

Use `/simkl-style` to set a personal preference. Personal preferences override the server default for that user.

Server administrators can use `/simkl-style-server` to change the default for everyone who has not set a personal preference.

The bot can report these activity types:

* **started watching**
* **planned to watch**
* **completed**
* **dropped**
* **watched**
* **rewatched**

When `MDBLIST_API_KEY` is configured, movies and TV/anime titles show their IMDb rating when MDBList has one available. Single anime episodes can also show a MyAnimeList (MAL) rating when MDBList provides one.

Ratings are displayed below the episode title for single-episode activity. Episode ranges do not display ratings because they represent multiple episodes.

For a single episode, the bot uses the episode's TMDB still when available. Movies and planned TV/anime activity use landscape TMDB artwork. If TMDB artwork cannot be found, the bot falls back to the SIMKL poster where available.

---

# 11. Multi-server Support

A single bot instance can now be used in multiple Discord servers.

Configuration is separated into:

* **Global:** Discord bot token, SIMKL Client ID, and TMDB API key.
* **Per server:** activity channel and server-wide embed defaults.
* **Per user:** SIMKL authentication and personal embed preferences.
* **Per server + user:** tracking history, announced activity, watch timestamps, and polling checkpoints.

Users link their SIMKL account separately in each server with `/simkl-link`. Unlinking with `/simkl-unlink` only removes the connection from the current server.

When a user is linked to a new server, the bot seeds that server's existing watch history so old activity is not posted as new activity.

---

# 12. Episode Grouping

When multiple consecutive episodes are watched, the bot groups them together.

For example:

```text
S02E08
S02E09
S02E10
S02E11
```

can be posted as a single activity message rather than four separate messages.

Non-consecutive episodes remain separate.

For example:

```text
S02E08
S02E09
S02E12
```

will be grouped into two activity messages:

```text
S02E08–S02E09
S02E12
```

Each individual episode is still tracked internally.

---

# 13. Polling

The bot checks SIMKL for new activity every **60 minutes by default**.

The polling interval can be changed using the `POLL_INTERVAL_MINUTES` environment variable in your `.env` file.

For example:

```env
POLL_INTERVAL_MINUTES=120
```

will make the bot check every 2 hours.

If `POLL_INTERVAL_MINUTES` is not set, the bot defaults to:

```text
60 minutes
```

After changing the value in `.env`, restart the bot for the new interval to take effect.

### API usage

The bot is designed to minimize unnecessary SIMKL API requests.

During a normal polling cycle, it first checks SIMKL's `/sync/activities` endpoint. If SIMKL reports that a media type has changed since the bot's last check, the bot then requests the relevant updated watch data using an incremental `date_from` value.

The bot does **not** repeatedly download the user's entire watch history during every polling cycle.

During a polling cycle, different SIMKL users are processed concurrently up to `POLL_CONCURRENCY`. Servers linked to the same user are kept in the same worker so shared SIMKL request caching remains effective and each server's tracking state stays isolated.

The scheduler also accounts for the time spent processing a polling cycle. It targets the configured interval between cycle starts instead of adding the full interval after every completed cycle. If a cycle takes longer than the configured interval, the next cycle starts as soon as the current one finishes rather than allowing delay to grow indefinitely.

The current JSON storage backend is intentionally designed for a single bot process. It should not be shared by multiple bot processes or instances. A future distributed deployment should move persistent state to a shared database before running multiple workers against the same data.

Because SIMKL API requests are subject to account/app limits, shorter polling intervals will result in more API requests. A longer interval is recommended if you do not need near-real-time activity updates.

The `/simkl-checknow` command can be used by administrators to manually check for new activity without waiting for the next scheduled poll. Manual checks have a short cooldown to prevent accidental repeated requests.

### Token refresh

SIMKL authentication tokens are refreshed automatically when necessary. The bot also tracks token expiry information and can proactively refresh a token when it is approaching expiration.

This allows linked users to remain authenticated without having to repeatedly link their SIMKL account.

---

# 14. Persistent Data

The bot stores persistent information in:

```text
data/store.json
```

This includes information such as:

* Linked Discord/SIMKL accounts
* SIMKL access and refresh tokens
* Discord channel configuration
* Polling state
* Previously announced activity

When using Docker, make sure the `data` directory is mounted:

```yaml
volumes:
  - ./data:/app/data
```

Do not remove `data/store.json` unless you intentionally want to reset the bot's stored data.

## Backing up your data

For Docker:

```bash
cp data/store.json data/store.json.backup
```

Or copy the entire data directory:

```bash
cp -r data data-backup
```

Keep backups somewhere secure because the data contains authentication information.

---

# 15. Reliability and Recovery

The bot is designed to recover from temporary SIMKL, Discord, metadata, and storage-related problems without requiring a manual restart.

### Polling health

Each server/user tracking record keeps:

* Last poll time
* Last successful poll time
* Last error
* Consecutive failure count

`/simkl-status` shows the current health state for members in the server. Tracking records for members who leave are retained so their history and checkpoints can resume if they rejoin; they are shown separately as stale records instead of being treated as currently linked accounts.

### Failed Discord posts

A Discord message is only treated as successfully announced after Discord accepts the send. Failed sends do not advance the relevant SIMKL checkpoint.

Successful episode/movie announcements are persisted immediately. This reduces the chance that a restart after a successful send will produce a duplicate announcement.

For status/watchlist activity, successfully posted status changes are also persisted independently. If one item fails while another succeeds, the successful item is not repeatedly announced while the failed item remains eligible for retry.

The bot does not blindly retry failed Discord sends because Discord may have accepted a message even if the client receives an error. Retrying such a request could create duplicate messages. Normal Discord rate-limit handling is left to `discord.py`.

### Checkpoint safety

A media-type checkpoint advances only when all required processing for that media type succeeds. If a post fails, the checkpoint remains behind and the bot will retry the activity during a later poll.

Already successful announcements are recorded separately, so retrying a checkpoint does not normally duplicate them.

### Configuration validation

`POLL_INTERVAL_MINUTES` and `POLL_CONCURRENCY` must be positive integers. Invalid values now stop the bot with a clear startup error rather than silently changing the requested configuration.

An invalid `GUILD_ID` is also rejected at startup.

### Recovery behavior

Temporary polling failures are recorded persistently and retried on the next scheduled poll. The scheduler's existing retry/backoff path remains in place for unexpected cycle-level failures, while individual user/server failures are isolated so one broken target does not stop the rest of the polling cycle.

### Testing

The project includes automated storage-health regression tests and runs them through GitHub Actions on pushes and pull requests.

---

# 16. Security

Never share or commit:

* `.env`
* Your Discord bot token
* SIMKL authentication tokens
* `data/store.json`

The repository includes `.gitignore` rules intended to prevent sensitive local files from being committed.

If you accidentally expose your Discord bot token, regenerate it through the Discord Developer Portal immediately.

---

# 16. Troubleshooting

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

### systemd

```bash
sudo journalctl -u simkltrackerbot -f
```

### Manual Python

Run:

```bash
python bot.py
```

and inspect the error shown in the terminal.

---

## `Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID`

Check your `.env` file:

```bash
cat .env
```

Make sure both variables are present:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
```

Do not share the contents of `.env` publicly.

---

## Slash commands are not appearing

If you set `GUILD_ID`, make sure it contains the correct Discord server ID.

Example:

```env
GUILD_ID=123456789012345678
```

Then restart the bot.

For Docker Compose:

```bash
sudo docker compose restart
```

---

## Bot is online but does not post activity

Check that:

1. The user has linked their SIMKL account with `/simkl-link`.
2. The bot has permission to send messages in the configured channel.
3. The correct channel was configured with `/simkl-setchannel`.
4. The watched activity is new activity after the account was linked.
5. The bot is running and polling normally.

You can also manually trigger a check:

```text
/simkl-checknow
```

---

## Docker container keeps restarting

Check the logs:

```bash
sudo docker compose logs --tail=100
```

Also check:

```bash
sudo docker compose ps
```

---

# 17. Updating from GitHub

## Docker Compose

The Docker image is published automatically to GitHub Container Registry when changes are pushed to `main`.

Update with:

```bash
cd ~/simkl-discord-bot
sudo docker compose pull
sudo docker compose up -d
```

Your persistent data in `data/store.json` is preserved.

## Docker CLI

Pull the latest image:

```bash
sudo docker pull ghcr.io/donnyfly/simkltrackerbot:latest
```

Then stop and remove the existing container:

```bash
sudo docker stop simkltrackerbot
sudo docker rm simkltrackerbot
```

Recreate it using the same `docker run` command from the Docker CLI installation section.

## Manual Python — Linux/macOS

Pull the latest code:

```bash
git pull
```

Activate the virtual environment:

```bash
source venv/bin/activate
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

## Windows

Pull the latest code:

```powershell
git pull
```

Activate the virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
```

Update dependencies:

```powershell
python -m pip install -r requirements.txt
```

Restart the bot:

```powershell
python bot.py
```

---

# 18. Development

Clone the repository:

```bash
git clone https://github.com/donnyfly/SIMKLTrackerBot.git
cd SIMKLTrackerBot
```

Create a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Create `.env` from `.env.example` and configure your credentials.

Run:

```bash
python bot.py
```

---

# 19. Docker Image

The project publishes a Docker image to GitHub Container Registry:

```text
ghcr.io/donnyfly/simkltrackerbot:latest
```

The `main` branch is automatically built and published using GitHub Actions.

The image can therefore be updated without building the application locally.

---

# 20. Repository Structure

```text
SIMKLTrackerBot/
├── .github/
│   └── workflows/
│       └── docker.yml
├── data/
│   └── .gitkeep
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
├── bot.py
├── docker-compose.yml
├── mdblist_client.py
├── requirements.txt
├── simkl_client.py
└── storage.py
```

`data/store.json` is generated locally when the bot runs and should not be committed to GitHub.

---

# License [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

