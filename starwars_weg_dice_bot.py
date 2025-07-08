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

# Load environment variables
load_dotenv()

# Data file for persistent character sheets
DATA_FILE = 'character_sheets.json'
# Load existing character sheets or start fresh
try:
    with open(DATA_FILE, 'r') as f:
        character_sheets = json.load(f)
except FileNotFoundError:
    character_sheets = {}

# Flask health-check server for Render
app = Flask(__name__)
@app.route('/')
def health(): return 'OK', 200

def run_health_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Configure Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# In-memory roll history: user_id -> deque of last 10 rolls
roll_history = {}

# ReUP roll logic
def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0; complication = False; critical_failure = False
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))
    initial = random.randint(1, 6); wild_rolls.append(initial)
    if initial == 1:
        complication = True
        if std_rolls: std_rolls.remove(max(std_rolls))
        new_wild = random.randint(1, 6); wild_rolls.append(new_wild)
        if new_wild == 1:
            critical_failure = True
            return std_rolls, wild_rolls, explosions, complication, critical_failure, modifier
        wild = new_wild
    else:
        wild = initial
    while wild == 6:
        explosions += 1
        wild = random.randint(1, 6)
        wild_rolls.append(wild)
    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return std_rolls, wild_rolls, explosions, complication, critical_failure, total

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# Roll command with character thumbnail lookup
@bot.command(name='roll', help='Roll ReUP D6: !roll <pool> [modifier] [character_name_or_url]')
async def roll(ctx, pool: int, modifier: int = 0, char_or_url: str = None):
    # Determine thumbnail: match registered name or treat as URL
    thumb_url = None
    if char_or_url:
        user_chars = character_sheets.get(str(ctx.author.id), {})
        if char_or_url in user_chars:
            thumb_url = user_chars[char_or_url]
        else:
            thumb_url = char_or_url
    # Perform roll
    std_rolls, wild_rolls, explosions, comp, cf, total = roll_reup(pool, modifier)
    # Store history
    roll_history.setdefault(str(ctx.author.id), deque(maxlen=10)).append((std_rolls, wild_rolls, explosions, comp, cf, total))
    if cf:
        return await ctx.send(f"🚨 {ctx.author.display_name} suffered a Critical Failure on {pool}D6!")
    # Build composite dice image
    images = [Image.open(f"static/d6_std_{p}.png") for p in std_rolls]
    images += [Image.open(f"static/d6_wild_{p}.png") for p in wild_rolls]
    widths, heights = zip(*(img.size for img in images))
    total_w, max_h = sum(widths), max(heights)
    combined = Image.new('RGBA', (total_w, max_h), (0,0,0,0))
    x = 0
    for img in images:
        combined.paste(img, (x, 0)); x += img.width
    combined = combined.resize((int(total_w * 32 / max_h), 32), Image.LANCZOS)
    buf = io.BytesIO(); combined.save(buf, 'PNG'); buf.seek(0)
    # Build embed
    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(modifier) if modifier else ''}",
        color=discord.Color.gold()
    )
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)
    embed.add_field(name='Standard Dice', value=', '.join(map(str, std_rolls)) or 'None', inline=False)
    embed.add_field(name='Wild Die', value=', '.join(map(str, wild_rolls)), inline=False)
    embed.add_field(name='Modifier', value=str(modifier), inline=True)
    embed.add_field(name='Explosions', value=str(explosions), inline=True)
    if comp:
        embed.add_field(name='Complication', value='Yes', inline=True)
    embed.add_field(name='Total', value=str(total), inline=True)
    embed.set_image(url='attachment://dice.png')
    await ctx.send(embed=embed, file=File(buf, filename='dice.png'))

# Character management: name and URL only
@bot.command(name='char', help='Manage chars: add/show/list/remove')
async def char(ctx, action: str = None, name: str = None, url: str = None):
    uid = str(ctx.author.id)
    character_sheets.setdefault(uid, {})
    user_chars = character_sheets[uid]
    # Add: supports multi-word names with quotes
    if action == 'add' and name and url:
        user_chars[name] = url
        with open(DATA_FILE, 'w') as f:
            json.dump(character_sheets, f, indent=2)
        return await ctx.send(f"✅ Character '{name}' registered.")
    # Show
    if action == 'show' and name:
        portrait = user_chars.get(name)
        if not portrait:
            return await ctx.send(f"❌ No character named '{name}'.")
        embed = discord.Embed(title=name, color=discord.Color.blue())
        embed.set_thumbnail(url=portrait)
        return await ctx.send(embed=embed)
    # List
    if action == 'list':
        if not user_chars:
            return await ctx.send("No characters registered.")
        return await ctx.send('📜 ' + ctx.author.display_name + "'s characters:\n" + '\n'.join(user_chars.keys()))
    # Remove
    if action == 'remove' and name:
        if name in user_chars:
            del user_chars[name]
            with open(DATA_FILE, 'w') as f:
                json.dump(character_sheets, f, indent=2)
            return await ctx.send(f"🗑️ Character '{name}' removed.")
        return await ctx.send(f"❌ No character named '{name}'.")
    # Help fallback
    return await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

# History command
@bot.command(name='history', help='Show last 10 rolls')
async def history(ctx):
    h = roll_history.get(str(ctx.author.id), [])
    if not h:
        return await ctx.send("No history.")
    lines = []
    for std, wild, exp, comp, cf, total in h:
        if cf:
            lines.append("🚨 Critical Failure"); continue
        extra = f"Expl:{exp}{', Comp' if comp else ''}"
        lines.append(f"Std:{std} Wild:{wild} → {total} ({extra})")
    await ctx.send("\n".join(lines))

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Missing DISCORD_TOKEN")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable Message Content Intent in Discord Developer Portal
