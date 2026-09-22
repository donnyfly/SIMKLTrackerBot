# SIMKL Watch Activity Tracker for Discord

A self-hosted Discord bot that automatically posts your SIMKL watch activity in a clean, modern embed style.

### Example output

<img width="196" height="96" alt="simkldiscordbotsample" src="https://github.com/user-attachments/assets/6acdb1f2-c764-4919-8048-3ea45f96bc5b" />

*(The bot posts messages that look like this — with your Discord name, poster, clickable title, and episode number)*

---

## Features

- Beautiful Discord embeds with poster thumbnails
- Clickable title that links directly to the show/movie on SIMKL
- Supports **TV Shows**, **Anime**, and **Movies**
- Each user links their own SIMKL account with one simple command
- Admin commands to set the channel and force a check
- Runs completely on your own server (no third-party hosting required)
- Lightweight – uses a simple JSON file for storage

---

## What you’ll need

- A computer or VPS that can stay online (Ubuntu recommended)
- A Discord account + a server where you can add bots
- A free [SIMKL](https://simkl.com) account

---

## Quick Setup Guide

### 1. Create the Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**
2. Go to the **Bot** tab → Reset Token → copy the token
3. Under **OAuth2 → URL Generator**:
   - Scopes: `bot` + `applications.commands`
   - Permissions: `Send Messages` + `Read Message History`
4. Copy the generated URL and invite the bot to your server

### 2. Create a SIMKL App

1. Go to [SIMKL Developer Settings](https://simkl.com/settings/developer)
2. Create a new application
3. Redirect URI: `urn:ietf:wg:oauth:2.0:oob`
4. Copy the **Client ID** (you do **not** need the Client Secret)

### 3. Download & Configure the Bot

```bash
git clone https://github.com/donnyfly/simkl-tracker-discord-bot.git
cd simkl-tracker-discord-bot
```
Copy the example environment file:
```bash
cp .env.example .env
nano .env
```
Fill in your values:
```bash
DISCORD_BOT_TOKEN=your_bot_token_here
SIMKL_CLIENT_ID=your_simkl_client_id_here
GUILD_ID=your_server_id_here          # optional but recommended
```

### 4. Install & Run
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```
You should see: `Logged in as SIMKL Tracker#xxxx`

### 5. Set it up in Discord

1. Run `/simkl-setchannel` in the channel where you want activity posted
2. Each person runs `/simkl-link` and follows the PIN instructions

That’s it! The bot will now post new watches automatically.

---

### Keeping it running (Ubuntu)
Create a systemd service so the bot starts automatically after reboot:
```bash
sudo nano /etc/systemd/system/simkl-bot.service
```
Paste (replace `your_username`):
```
[Unit]
Description=SIMKL Discord Watch Activity Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/simkl-tracker-discord-bot
ExecStart=/home/your_username/simkl-tracker-discord-bot/venv/bin/python bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
Then enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable simkl-bot
sudo systemctl start simkl-bot
```
Useful commands:
```bash
sudo systemctl status simkl-bot     # check status
sudo systemctl restart simkl-bot    # restart
journalctl -u simkl-bot -f          # live logs
```
---

## Commands
| Command | Who can use it | What it does |
|---|---|---|
| `/simkl-link` | Anyone | Links your own SIMKL account |
| `/simkl-unlink` | Anyone | Removes your linked account |
| `/simkl-setchannel` | Admins | Sets where activity gets posted |
| `/simkl-status` | Admins | Shows current settings and linked users |
| `/simkl-checknow` | Admins | Forces an immediate check (useful for testing) |

---

## Notes
- The bot only posts activity that happens after a user links their account.
- Posters and links are pulled live from SIMKL.
- All tokens are stored locally in `data/store.json` and never leave your server.

---

## Troubleshooting
- Slash commands don’t appear → Make sure you set `GUILD_ID` in `.env` and restarted the bot.
- Nothing is being posted → Run `/simkl-checknow` and check the logs with `journalctl -u simkl-bot -f`.
- Token invalid → The user should run `/simkl-link` again.
