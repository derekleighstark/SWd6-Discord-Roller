# Starwars WEG D6 Dice Bot

A Discord bot for rolling dice using the **Star Wars West End Games D6** (Revised & Updated) system and managing character portrait URLs. It supports:

* **ReUP dice rolling** with wild die mechanics, explosions, and complications
* **Optional modifier** and **notes** on each roll
* **Image thumbnails** for character portraits or inline images
* **Suppressed URL previews** to avoid double-posting
* **Persistent character storage** via GitHub (using a JSON file in your repo)
* **Health‐check endpoint** to keep the free‐tier service alive

---

## Features & Commands

### 🎲 Dice Rolls (`!roll`)

Roll a ReUP D6 pool with optional modifier, thumbnail, and notes:

```
!roll <pool> [modifier] [image_url] [notes...]
```

* **pool**: Number of dice to roll (e.g. `5`)
* **modifier**: (optional) Integer to add to the final total
* **image\_url**: (optional) URL to a portrait or icon to embed
* **notes**: (optional) Quoted or unquoted text describing the action

**Example:**

```
!roll 4 2 https://i.imgur.com/Chopper.png "Chopper uses electroshock prod"
```

Embed fields:

* **Standard Dice**: Individual non‐wild rolls
* **Wild Die**: Your single wild die (with explosions)
* **Modifier**: Applied modifier
* **Explosions**: Count of extra wild die rolls from 6s
* **Complication**: Yes/No if a wild‐die 1 occurred
* **Total**: Sum of all dice + modifier

### 🗂️ Character Management (`!char`)

Persist and retrieve character portrait URLs (stored in GitHub `character_sheets.json`):

* `!char add "Name" URL`
  Register a character with a portrait URL
* `!char show "Name"`
  Display the character’s thumbnail
* `!char list`
  List all registered characters
* `!char remove "Name"`
  Remove a character

### 🔄 Health‐Check

A Flask endpoint at `/` returns `OK` to keep your service awake on free hosting platforms like Render.

---

## Setup & Deployment

1. **Clone this repo** and add your static assets:

   * `static/d6_std_1.png` … `static/d6_std_6.png`
   * `static/d6_wild_1.png` … `static/d6_wild_6.png`

2. **Create environment variables** (e.g. in Render dashboard or `.env`):

   ```bash
   DISCORD_TOKEN=your_bot_token
   GITHUB_TOKEN=your_personal_access_token
   GITHUB_OWNER=your_github_username
   GITHUB_REPO=your_repo_name
   ```

   * **GITHUB\_TOKEN** needs `repo` scope to read/write the JSON

3. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

4. **Deploy** (e.g. push to GitHub & Render will auto‐deploy). Ensure `Message Content Intent` is enabled in the Discord Developer Portal.

5. **Keep alive**: Use an uptime monitor (UptimeRobot, GitHub Actions) to ping the health‐check endpoint every 10–15 minutes.

---

## Contributing

Pull requests, issues, and feature suggestions are welcome! Please ensure:

* New dice mechanics adhere to West End Games ReUP rules
* Character data stays in the GitHub JSON file

---

© 2025 Starwars WEG Dice Bot
