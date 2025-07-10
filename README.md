# Star Wars WEG Dice Roller Bot

A Discord bot that handles **Star Wars D6 “Revised & Expanded”** (ReUP) wild‑die rolls **and** regular polyhedral dice rolls. Built with **Python 3.11**, **discord.py**, and a tiny Flask health‑check server for uptime monitors.

---

## Features

| Command                                         | Purpose                                                                                                    | Example                                                                  |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `!swroll <pool> [modifier] [image_url] [notes]` | Perform a ReUP‐style roll with exploding wild die, complications, and automatic image montage of the dice. | `!swroll 7 +2 https://i.imgur.com/droid.png "Shooting at stormtroopers"` |
| `!swdice <XdY±Z>` (alias `!swd`)                | Classic polyhedral roll (e.g. 3d6, 2d20+4).                                                                | `!swdice 4d8+1`                                                          |

### ReUP Logic Highlights

* Exploding wild‑die on 6 (roll again, infinite).
* Complication trigger on initial wild‑die 1.
* Detects **critical failure** when the first two wild‑die results are `1 → 1`.
* Embed shows: standard dice, wild‑die chain, explosions, complication flag, total, and GM guidance.
* Generates a composite PNG of every die rolled (standard & wild) using images in `static/`.

### Polyhedral Logic Highlights

* Accepts a single arithmetic term `XdY±Z` (e.g. `3d6`, `1d10-2`).
* Rolls each die, sums, applies modifier, and returns an embed with the breakdown.
* Easy to extend to expressions like `2d6+1d4+3` (see the comment in `starwars_weg_dice_bot.py`).

---

## Quick Start

```bash
# Clone & install
$ git clone https://github.com/yourname/starwars-weg-dice-bot.git
$ cd starwars-weg-dice-bot
$ python -m venv venv && source venv/bin/activate
$ pip install -r requirements.txt

# .env file (place in project root)
DISCORD_TOKEN=YOUR_BOT_TOKEN_HERE
PORT=5000               # optional – for health‑check server

# Run locally
$ python starwars_weg_dice_bot.py
```

### Docker

```bash
$ docker build -t weg-dice-bot .
$ docker run -e DISCORD_TOKEN=YOUR_BOT_TOKEN -p 5000:5000 weg-dice-bot
```

---

## File Structure

```
├── starwars_weg_dice_bot.py   # main bot code
├── static/                    # PNG assets for dice faces
│   ├── d6_std_1.png           # 1–6 standard faces
│   └── d6_wild_1.png          # 1–6 wild faces
├── requirements.txt           # python‑package pins
└── README.md                  # you are here
```

---

## Environment Variables

| Variable        | Purpose                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `DISCORD_TOKEN` | **Required.** Bot token from [https://discord.com/developers/applications](https://discord.com/developers/applications). |
| `PORT`          | Port for Flask health endpoint (`/`). Defaults to **5000** – useful for PaaS uptime pings.                               |

---

## Contributing

1. Fork ☄️
2. Create your feature branch (`git checkout -b feat/awesome`)
3. Commit your changes (`git commit -am 'Add awesome feature'`)
4. Push (`git push origin feat/awesome`)
5. Open a Pull Request 🚀

---

## License

MIT. See `LICENSE` for details.

---

> “Never tell me the odds.” — **Han Solo**
