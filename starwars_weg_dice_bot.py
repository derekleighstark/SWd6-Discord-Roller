import os
import random
import io
import json
import base64
import requests
import discord
from discord.ext import commands
from discord import File
import threading
from flask import Flask
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()
discord_token = os.getenv('DISCORD_TOKEN')
if not discord_token:
    raise RuntimeError('DISCORD_TOKEN not set')
github_token = os.getenv('GITHUB_TOKEN')
github_owner = os.getenv('GITHUB_OWNER')
github_repo  = os.getenv('GITHUB_REPO')
if not (github_token and github_owner and github_repo):
    raise RuntimeError('GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO must be set')

# GitHub-backed persistence for !char
FILE_PATH = 'character_sheets.json'
API_URL_BASE = f"https://api.github.com/repos/{github_owner}/{github_repo}/contents/{FILE_PATH}"
HEADERS = {
    'Authorization': f'token {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}

def load_sheets():
    r = requests.get(API_URL_BASE, headers=HEADERS)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    content = data.get('content', '')
    return json.loads(base64.b64decode(content))

def save_sheets(sheets, msg='Update character sheets'):
    r = requests.get(API_URL_BASE, headers=HEADERS)
    sha = r.json().get('sha') if r.status_code == 200 else None
    encoded = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {'message': msg, 'content': encoded}
    if sha:
        payload['sha'] = sha
    put = requests.put(API_URL_BASE, headers=HEADERS, json=payload)
    put.raise_for_status()

# Initialize character sheets
character_sheets = load_sheets()

# Health-check server for uptime
app = Flask(__name__)
@app.route('/')
def health():
    return 'OK', 200

def run_health_server():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ReUP roll logic for Revised & Updated
def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0
    complication = False
    # Roll standard dice (pool - 1)
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))
    # Roll wild die
    w0 = random.randint(1, 6)
    wild_rolls.append(w0)
    if w0 == 1:
        complication = True
        if std_rolls:
            std_rolls.remove(max(std_rolls))
        w1 = random.randint(1, 6)
        wild_rolls.append(w1)
        if w1 == 1:
            total = modifier
            return std_rolls, wild_rolls, 0, True, total
        current = w1
    else:
        current = w0
    # Explosions on wild
    while current == 6:
        explosions += 1
        current = random.randint(1, 6)
        wild_rolls.append(current)
    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return std_rolls, wild_rolls, explosions, complication, total

# Dice roll command with notes and auto-deletion to prevent URL preview
@bot.command(name='roll')
async def roll_command(ctx, pool: int, modifier: int = 0, image_url: str = None, *, notes: str = None):
    # Delete the invoking message to suppress automatic URL unfurling
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass  # bot lacks permission to delete messages

    std, wild, explosions, complication, total = roll_reup(pool, modifier)
    # Build composite image
    images = [Image.open(f"static/d6_std_{d}.png") for d in std] + \
             [Image.open(f"static/d6_wild_{d}.png") for d in wild]
    widths, heights = zip(*(i.size for i in images))
    total_w, max_h = sum(widths), max(heights)
    combined = Image.new('RGBA', (total_w, max_h), (0,0,0,0))
    x = 0
    for img in images:
        combined.paste(img, (x, 0))
        x += img.width
    combined = combined.resize((int(total_w * 32 / max_h), 32), Image.LANCZOS)
    buf = io.BytesIO()
    combined.save(buf, 'PNG')
    buf.seek(0)
    # Build embed
    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(modifier) if modifier else ''}",
        description=notes or discord.Embed.Empty,
        color=discord.Color.gold()
    )
    if image_url:
        embed.set_thumbnail(url=image_url)
    embed.add_field(name='Standard Dice', value=', '.join(map(str, std)) or 'None', inline=False)
    embed.add_field(name='Wild Die',       value=', '.join(map(str, wild)),           inline=False)
    embed.add_field(name='Modifier',       value=str(modifier),                     inline=True)
    embed.add_field(name='Explosions',     value=str(explosions),                   inline=True)
    embed.add_field(name='Complication',   value='Yes' if complication else 'No',    inline=True)
    embed.add_field(name='Total',          value=str(total),                         inline=True)
    embed.set_image(url='attachment://dice.png')
    await ctx.send(embed=embed, file=File(buf, 'dice.png'))

# Character management commands
@bot.group(name='char')
async def char(ctx):
    if not ctx.invoked_subcommand:
        await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

@char.command(name='add')
async def char_add(ctx, name: str, url: str):
    uid = str(ctx.author.id)
    character_sheets.setdefault(uid, {})
    character_sheets[uid][name] = url
    save_sheets(character_sheets, msg=f"Add {name}")
    await ctx.send(f"✅ Character '{name}' added.")

@char.command(name='show')
async def char_show(ctx, name: str):
    uid = str(ctx.author.id)
    url = character_sheets.get(uid, {}).get(name)
    if not url:
        return await ctx.send(f"❌ No character named '{name}'.")
    embed = discord.Embed(title=name, color=discord.Color.blue())
    embed.set_thumbnail(url=url)
    await ctx.send(embed=embed)

@char.command(name='list')
async def char_list(ctx):
    uid = str(ctx.author.id)
    names = character_sheets.get(uid, {}).keys()
    if not names:
        return await ctx.send("No characters registered.")
    char_list_str = "\n".join(names)
    await ctx.send(f"📜 {ctx.author.display_name}'s characters:\n{char_list_str}")

@char.command(name='remove')
async def char_remove(ctx, name: str):
    uid = str(ctx.author.id)
    if name in character_sheets.get(uid, {}):
        character_sheets[uid].pop(name)
        save_sheets(character_sheets, msg=f"Remove {name}")
        await ctx.send(f"🗑️ Character '{name}' removed.")
    else:
        await ctx.send(f"❌ No character named '{name}'.")

if __name__ == '__main__':
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.run(discord_token)

# Enable "Message Content Intent" in Discord Developer Portal
