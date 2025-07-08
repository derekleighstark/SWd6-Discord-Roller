import os
import random
import io
import json
import discord
from discord.ext import commands
from discord import File
from collections import deque
import threading
from flask import Flask
from dotenv import load_dotenv
from PIL import Image

# Load environment variables from .env if present
load_dotenv()

# Data file for persistent character sheets
data_file = 'character_sheets.json'
# Load existing character sheets or start fresh
try:
    with open(data_file, 'r') as f:
        raw = json.load(f)
        character_sheets = {int(k): tuple(v) for k, v in raw.items()}
except FileNotFoundError:
    character_sheets = {}

# Health-check Flask server for Render
app = Flask(__name__)

@app.route('/')
def health():
    return 'OK', 200

def run_health_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Star Wars WEG D6 Dice Roller Bot
# Supports only Revised & Updated (ReUP) rules with proper Wild Die mechanics

# Configure Discord intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# In-memory storage
roll_history = {}          # user_id -> deque of last 10 rolls
# roll_reup function unchanged

def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0
    complication = False
    critical_failure = False
    # standard dice
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))
    # wild die initial
    initial = random.randint(1, 6)
    wild_rolls.append(initial)
    if initial == 1:
        complication = True
        if std_rolls:
            std_rolls.remove(max(std_rolls))
        new_wild = random.randint(1, 6)
        wild_rolls.append(new_wild)
        if new_wild == 1:
            critical_failure = True
            return std_rolls, wild_rolls, explosions, complication, critical_failure, modifier
        wild = new_wild
    else:
        wild = initial
    # wild explosions only
    while wild == 6:
        explosions += 1
        wild = random.randint(1, 6)
        wild_rolls.append(wild)
    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return std_rolls, wild_rolls, explosions, complication, critical_failure, total

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command(name='roll', help='Roll ReUP WEG D6: !roll <pool> [modifier] [character_image_url]')
async def roll(ctx, pool: int, modifier: int = 0, character_image_url: str = None):
    std_rolls, wild_rolls, explosions, complication, critical_failure, total = roll_reup(pool, modifier)
    # store history
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append((std_rolls, wild_rolls, explosions, complication, critical_failure, total))
    # critical fail
    if critical_failure:
        return await ctx.send(f"🚨 {ctx.author.display_name} suffered a Critical Failure on {pool}D6!")
    # build composite image
    images = [Image.open(f"static/d6_std_{pip}.png") for pip in std_rolls]
    images += [Image.open("static/d6_wild.png") for _ in wild_rolls]
    widths, heights = zip(*(img.size for img in images))
    total_w, max_h = sum(widths), max(heights)
    combined = Image.new('RGBA', (total_w, max_h), (0,0,0,0))
    x = 0
    for img in images:
        combined.paste(img, (x, 0))
        x += img.width
    # resize height 32px
    scale = 32 / max_h
    combined = combined.resize((int(total_w * scale), 32), Image.ANTIALIAS)
    buf = io.BytesIO()
    combined.save(buf, format='PNG')
    buf.seek(0)
    # build embed
    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled ReUP {pool}D6 {'+'+str(modifier) if modifier else ''}",
        color=discord.Color.gold()
    )
    if character_image_url:
        embed.set_thumbnail(url=character_image_url)
    # text details inside embed
    embed.add_field(name='Standard Dice', value=', '.join(map(str,std_rolls)) or 'None', inline=False)
    embed.add_field(name='Wild Die', value=', '.join(map(str,wild_rolls)), inline=False)
    embed.add_field(name='Modifier', value=str(modifier), inline=True)
    embed.add_field(name='Explosions', value=str(explosions), inline=True)
    if complication:
        embed.add_field(name='Complication', value='Yes', inline=True)
    embed.add_field(name='Total', value=str(total), inline=True)
    embed.set_image(url="attachment://dice.png")
    await ctx.send(embed=embed, file=File(buf, filename='dice.png'))

@bot.command(name='char', help='Save or view your character sheet: !char [portrait_url] <sheet_text>')
async def char(ctx, portrait_url: str = None, *, sheet_text: str = None):
    if portrait_url and sheet_text:
        character_sheets[ctx.author.id] = (sheet_text, portrait_url)
        to_save = {str(k): list(v) for k, v in character_sheets.items()}
        with open(data_file, 'w') as f:
            json.dump(to_save, f, indent=2)
        return await ctx.send(f"✅ {ctx.author.display_name}'s character sheet saved.")
    data = character_sheets.get(ctx.author.id)
    if not data:
        return await ctx.send("No sheet saved. Use `!char <url> <sheet>`.")
    sheet, url = data
    embed = discord.Embed(title=f"{ctx.author.display_name}'s Character Sheet", description=sheet, color=discord.Color.blue())
    embed.set_thumbnail(url=url)
    await ctx.send(embed=embed)

@bot.command(name='history', help='Show your last 10 ReUP rolls')
async def history(ctx):
    user_hist = roll_history.get(ctx.author.id)
    if not user_hist:
        return await ctx.send(f"{ctx.author.display_name}, no roll history.")
    lines = []
    for std_rolls, wild_rolls, explosions, complication, cf, total in user_hist:
        if cf:
            lines.append("🚨 Critical Failure")
            continue
        extras = f"Expl:{explosions}{', Complication' if complication else ''}"
        lines.append(f"Std:{std_rolls} Wild:{wild_rolls} → {total} ({extras})")
    await ctx.send("\n".join(lines))

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN env var not set.")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable Message Content Intent in Discord Developer Portal
