import os
import random
import io
import discord
from discord.ext import commands
from discord import File
from collections import deque
import threading
from flask import Flask
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()

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

# In-memory history storage: user_id -> deque of last 10 roll dicts
roll_history = {}

# ReUP roll function
def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0
    complication = False
    critical_failure = False

    # Standard dice (pool - 1)
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))

    # Wild die
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

    # Explosions on wild
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

@bot.command(name='roll', help='Roll ReUP WEG D6: !roll <pool> [modifier]')
async def roll(ctx, pool: int, modifier: int = 0):
    std_rolls, wild_rolls, explosions, complication, critical_failure, total = roll_reup(pool, modifier)

    # Update history
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append((std_rolls, wild_rolls, explosions, complication, critical_failure, total))

    # Handle critical failure
    if critical_failure:
        await ctx.send(f"🚨 {ctx.author.display_name} Critical Failure on {pool}D6!")
        return

    # Composite image
    images = []
    for pip in std_rolls:
        images.append(Image.open(f"static/d6_std_{pip}.png"))
    for _ in wild_rolls:
        images.append(Image.open("static/d6_wild.png"))

    # Concatenate horizontally
    widths, heights = zip(*(img.size for img in images))
    total_w = sum(widths)
    max_h = max(heights)
    combined = Image.new('RGBA', (total_w, max_h), (0,0,0,0))
    x = 0
    for img in images:
        combined.paste(img, (x, 0))
        x += img.width

    # Resize for inline display (height 64px)
    scale = 64 / max_h
    combined = combined.resize((int(total_w * scale), 64), Image.ANTIALIAS)

    # Save to buffer
    buf = io.BytesIO()
    combined.save(buf, format='PNG')
    buf.seek(0)

    # Build embed
    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled ReUP {pool}D6 {'+'+str(modifier) if modifier else ''}",
        color=discord.Color.gold()
    )
    embed.set_image(url="attachment://dice.png")
    embed.add_field(name='Explosions', value=str(explosions), inline=True)
    if complication:
        embed.add_field(name='Complication', value='Yes', inline=True)
    embed.add_field(name='Total', value=str(total), inline=True)

    # Send embed with image
    await ctx.send(embed=embed, file=File(buf, filename='dice.png'))

@bot.command(name='history', help='Show your last 10 ReUP rolls')
async def history(ctx):
    user_hist = roll_history.get(ctx.author.id)
    if not user_hist:
        await ctx.send(f"{ctx.author.display_name}, no roll history.")
        return
    lines = []
    for std_rolls, wild_rolls, explosions, complication, cf, total in user_hist:
        if cf:
            lines.append(f"🚨 Critical Failure")
            continue
        lines.append(f"Std:{std_rolls} Wild:{wild_rolls} → {total} (Expl:{explosions}{', Comp' if complication else ''})")
    await ctx.send("\n".join(lines))

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN env var not set.")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable Message Content Intent in Developer Portal
