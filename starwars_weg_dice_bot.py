import os
import base64
import json
import threading
import io
import requests
from dotenv import load_dotenv
from flask import Flask
import discord
from discord.ext import commands
from PIL import Image

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER  = os.getenv("GITHUB_OWNER")
GITHUB_REPO   = os.getenv("GITHUB_REPO")

if not all([DISCORD_TOKEN, GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO]):
    print("Error: Missing one of DISCORD_TOKEN, GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO")
    exit(1)

# GitHub-backed persistence for character sheets
API_URL_BASE = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
    "/contents/character_sheets.json"
)
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json"
}

def load_sheets():
    resp = requests.get(API_URL_BASE, headers=HEADERS)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"])
    return json.loads(content)

def save_sheets(sheets):
    resp = requests.get(API_URL_BASE, headers=HEADERS)
    if resp.status_code not in (200, 404):
        resp.raise_for_status()
    sha = resp.json().get("sha") if resp.status_code == 200 else None
    encoded = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {"message": "Update character sheets", "content": encoded}
    if sha:
        payload["sha"] = sha
    put = requests.put(API_URL_BASE, headers=HEADERS, json=payload)
    put.raise_for_status()

character_sheets = load_sheets()

# ReUP dice-rolling logic (official: no reroll on 1)
def roll_reup(pool, modifier):
    import random

    # Standard dice: pool-1
    std_dice = [random.randint(1, 6) for _ in range(max(pool - 1, 0))]

    # Roll the Wild Die exactly once
    wild = random.randint(1, 6)
    wild_rolls = [wild]
    explosions = 0

    # Explode on 6
    while wild == 6:
        explosions += 1
        wild = random.randint(1, 6)
        wild_rolls.append(wild)

    # Complication if initial wild was 1
    complication = (wild_rolls[0] == 1)

    total = sum(std_dice) + sum(wild_rolls) + modifier
    return std_dice, wild_rolls, modifier, explosions, complication, total

# Health-check server for uptime
app = Flask(__name__)

@app.route("/")
def health():
    return "OK", 200

def run_health_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Roll command
@bot.command(name="swroll")
async def roll_cmd(ctx, *args):
    # Suppress URL preview
    try:
        await ctx.message.edit(suppress=True)
    except discord.Forbidden:
        pass

    if not args:
        await ctx.send("Usage: !swroll <pool> [modifier] [image_url] [notes]")
        return

    # Parse pool
    try:
        pool = int(args[0])
    except ValueError:
        await ctx.send("❌ Pool must be an integer.")
        return

    modifier = 0
    idx = 1

    # Optional modifier
    if idx < len(args):
        try:
            modifier = int(args[idx])
            idx += 1
        except ValueError:
            modifier = 0

    # Optional image URL
    url = None
    if idx < len(args) and args[idx].startswith(("http://", "https://")):
        url = args[idx]
        idx += 1

    # Optional notes
    notes = None
    if idx < len(args):
        notes = " ".join(args[idx:])
        if (notes.startswith('"') and notes.endswith('"')) or (notes.startswith("'") and notes.endswith("'")):
            notes = notes[1:-1]

    # Perform the roll
    std_dice, wild_rolls, modifier, explosions, complication, total = roll_reup(pool, modifier)

    # Determine display_wild (same as wild_rolls here)
    display_wild = wild_rolls

    # Detect true Critical Failure (1→1 on wild)
    critical_failure = False
    if complication and len(wild_rolls) >= 2 and wild_rolls[1] == 1:
        critical_failure = True

    # Build embed header
    if critical_failure:
        embed = discord.Embed(title="🚨 Critical Failure on ReUP Roll!", color=0xFF0000)
    else:
        embed = discord.Embed(title=f"🎲 {ctx.author.display_name} rolled {pool}D6", color=0xFFD700)

    # Attach notes & thumbnail
    if notes:
        embed.description = notes
    if url:
        embed.set_thumbnail(url=url)

    # Add fields
    embed.add_field(name="Standard Dice",  value=", ".join(map(str, std_dice)) or "None", inline=True)
    embed.add_field(name="Wild Die",       value=", ".join(map(str, display_wild)), inline=True)
    embed.add_field(name="Modifier",       value=str(modifier),                          inline=True)
    embed.add_field(name="Explosions",     value=str(explosions),                        inline=True)
    embed.add_field(name="Complication",   value="Yes" if complication else "No",        inline=True)
    embed.add_field(name="Total",          value=str(total),                             inline=False)

    # GM option reminder if complication
    if complication:
        embed.add_field(
            name="GM Option",
            value=(
                "Wild d6=1 → GM may:\n"
                "1) add normally\n"
                "2) subtract this & highest die\n"
                "3) add normally & introduce complication"
            ),
            inline=False
        )

    # Composite dice image
    images = []
    for pip in std_dice:
        images.append(Image.open(f"static/d6_std_{pip}.png"))
    for pip in display_wild:
        images.append(Image.open(f"static/d6_wild_{pip}.png"))

    widths, heights = zip(*(im.size for im in images)) if images else ([0], [0])
    total_w = sum(widths)
    combined = Image.new("RGBA", (total_w, heights[0] if heights else 32))
    x_offset = 0
    for im in images:
        combined.paste(im, (x_offset, 0))
        x_offset += im.width

    # Resize to 64px height
    target_h = 64
    scale = (target_h / heights[0]) if heights and heights[0] else 1
    combined = combined.resize((int(total_w * scale), target_h), Image.LANCZOS)

    # Send as attachment
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    buf.seek(0)
    file = discord.File(buf, filename="dice.png")
    embed.set_image(url="attachment://dice.png")

    await ctx.send(embed=embed, file=file)

# Character management commands
@bot.group(name="char", invoke_without_command=True)
async def char_group(ctx):
    await ctx.send("Use `!char add <Name> <URL>`, `!char show <Name>`, `!char list`, or `!char remove <Name>`")

@char_group.command(name="add")
async def char_add(ctx, name: str, url: str):
    uid = str(ctx.author.id)
    character_sheets.setdefault(uid, {})[name] = url
    save_sheets(character_sheets)
    await ctx.send(f"✅ Added character **{name}**.")

@char_group.command(name="show")
async def char_show(ctx, name: str):
    uid = str(ctx.author.id)
    url = character_sheets.get(uid, {}).get(name)
    if not url:
        await ctx.send(f"No such character **{name}**.")
        return
    embed = discord.Embed(title=name, color=0x00FF00)
    embed.set_thumbnail(url=url)
    await ctx.send(embed=embed)

@char_group.command(name="list")
async def char_list(ctx):
    uid = str(ctx.author.id)
    names = list(character_sheets.get(uid, {}).keys())
    if not names:
        await ctx.send("No characters registered.")
        return
    await ctx.send(f"📜 {ctx.author.display_name}'s characters:\n" + "\n".join(names))

@char_group.command(name="remove")
async def char_remove(ctx, name: str):
    uid = str(ctx.author.id)
    if name in character_sheets.get(uid, {}):
        del character_sheets[uid][name]
        save_sheets(character_sheets)
        await ctx.send(f"🗑️ Removed character **{name}**.")
    else:
        await ctx.send(f"No such character **{name}**.")

# Run health server & bot
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.run(DISCORD_TOKEN)
