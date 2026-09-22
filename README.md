# SIMKL Watch Activity Tracker for Discord

Posts messages like:

> **Username** watched **S01E03 - "The Rogue Prince"** of **House of the Dragon**

> **Username** watched the movie **Dune: Part Two**

Each person links their own SIMKL account with one command. The bot then checks
SIMKL every few minutes and posts anything new to a channel you choose.

No coding knowledge needed — just follow the steps below in order.

---

## What you'll need

- A computer (Windows, Mac, or Linux) or a VPS that can stay on while the bot runs
- A Discord account where you can create a bot application
- A free SIMKL account

---

## Step 1 — Install Python

1. Go to https://www.python.org/downloads/ and download **Python 3.11 or newer**.
2. Run the installer.
   - **Windows:** on the first screen, check the box **"Add python.exe to PATH"** before clicking Install.
   - **Mac:** just run the installer normally.
3. To check it worked, open a terminal (Command Prompt/PowerShell on Windows, Terminal on Mac) and type:
   ```
   python --version
   ```
   You should see something like `Python 3.11.x`. (On Mac, you may need to type `python3` instead of `python`.)

---

## Step 2 — Create the Discord bot

1. Go to https://discord.com/developers/applications and click **New Application**. Name it anything (e.g. "SIMKL Tracker").
2. In the left sidebar, click **Bot**.
   - Click **Reset Token** (or **View Token**) and copy the token somewhere safe. You'll paste it into this project in Step 4. **Never share this token with anyone.**
3. Still on the Bot page, scroll down and make sure **Public Bot** is OFF (unless you want other servers to add it too).
4. In the left sidebar, click **OAuth2 → URL Generator**.
   - Under **Scopes**, check `bot` and `applications.commands`.
   - Under **Bot Permissions**, check `Send Messages` and `Read Message History`.
   - Copy the generated URL at the bottom, paste it into your browser, and invite the bot to your server.

---

## Step 3 — Create a SIMKL app (for the API connection)

1. Log in at https://simkl.com and go to https://simkl.com/settings/developer
2. Click to create a new app.
   - **Redirect URI:** you can put `urn:ietf:wg:oauth:2.0:oob` — it isn't actually used by this bot.
3. Copy the **Client ID** shown for your app. You'll paste it into this project in Step 4.
   - You do **not** need the Client Secret for this bot.

---

## Step 4 — Configure the bot

1. Download the project files (the ones shared in this chat) into a folder on your computer, e.g. `simkl-discord-bot`.
2. Inside that folder, make a copy of `.env.example` and rename the copy to `.env`.
3. Open `.env` in any text editor and fill in:
   ```
   DISCORD_BOT_TOKEN=paste your bot token here
   SIMKL_CLIENT_ID=paste your SIMKL client ID here
   GUILD_ID=your Discord server's ID (optional but recommended while testing)
   ```
   To get your server's ID: in Discord, go to **User Settings → Advanced → Enable Developer Mode**, then right-click your server's icon and choose **Copy Server ID**.

---

## Step 5 — Install dependencies and run the bot

Open a terminal, navigate into the project folder, then run:

```
pip install -r requirements.txt
python bot.py
```

(On Mac/Linux you may need `pip3` and `python3` instead.)

If everything is set up correctly, you'll see a line like `Logged in as SIMKL Tracker#1234`.
**Leave this terminal window open** — the bot only runs while this is running. To stop it, press `Ctrl+C`.

> **Keeping it running long-term:** for a first test, running it in a terminal is fine.
> To keep it running permanently on a Windows/Mac computer, just leave the terminal open (or the
> computer awake). On a VPS, look into `tmux`, `screen`, or a `systemd` service so it keeps running
> after you disconnect.

---

## Step 6 — Set it up in Discord

In your server, run these slash commands:

1. **`/simkl-setchannel`** — run this in the channel where you want watch activity posted.
   (Requires the "Manage Server" permission.)
2. Each person who wants their activity tracked runs **`/simkl-link`**.
   - The bot will reply privately with a short code and a link (simkl.com/pin).
   - Go to that link, log into SIMKL if needed, and enter the code.
   - The bot will DM you a confirmation once it's linked. This usually takes a few seconds.

That's it — the bot checks for new activity every 5 minutes by default and posts it to your chosen channel.

---

## Commands reference

| Command | Who can use it | What it does |
|---|---|---|
| `/simkl-link` | Anyone | Links your own SIMKL account |
| `/simkl-unlink` | Anyone | Removes your linked account |
| `/simkl-setchannel` | Admins | Sets where activity gets posted |
| `/simkl-status` | Admins | Shows current settings and linked users |
| `/simkl-checknow` | Admins | Forces an immediate check (useful for testing) |

---

## Adjusting the check frequency

By default the bot checks every 5 minutes. To change it, open `data/store.json` after running
the bot at least once, and change `"poll_interval_minutes"`. Restart the bot afterward.

---

## Troubleshooting

- **Slash commands don't show up in Discord:** if you didn't set `GUILD_ID` in `.env`, Discord can
  take up to an hour to show new global commands. Setting `GUILD_ID` makes them appear instantly.
- **"Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID"**: double check your `.env` file is named exactly
  `.env` (not `.env.txt`) and both values are filled in.
- **A linked user's activity stops posting:** their SIMKL authorization may have been revoked. Ask
  them to run `/simkl-link` again.
- **Nothing posts even though someone watched something:** run `/simkl-checknow` to force an
  immediate check rather than waiting for the next automatic cycle.

---

## How it works (optional reading)

- Each linked user's SIMKL access token is stored locally in `data/store.json` — never sent anywhere
  except to SIMKL's own API.
- Every poll cycle, the bot asks SIMKL for each user's shows/movies/anime updated since the last
  check, compares watched timestamps, and posts anything new — then remembers what it already
  announced so nothing gets posted twice.
- No central database or hosting service is required; it's a single always-running Python process.
