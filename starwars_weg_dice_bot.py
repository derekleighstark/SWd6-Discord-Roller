```python
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
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_OWNER = os.getenv('GITHUB_OWNER')
GITHUB_REPO = os.getenv('GITHUB_REPO')
if not DISCORD_TOKEN:
    raise RuntimeError('DISCORD_TOKEN not set')
if not (GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO):
    raise RuntimeError('GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO must be set')

# GitHub persistence for !char
FILE_PATH = 'character_sheets.json'
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{FILE_PATH}"
HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def load_sheets():
    resp = requests.get(API_URL, headers=HEADERS)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    data = resp.json()
    content = data.get('content', '')
    return json.loads(base64.b64decode(content))


def save_sheets(sheets, msg='Update sheets'):
    resp = requests.get(API_URL, headers=HEADERS)
    sha = resp.json().get('sha') if resp.status_code == 200 else None
    content = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {'message': msg, 'content': content}
    if sha:
        payload['sha'] = sha
    put = requests.put(API_URL, headers=HEADERS, json=payload)
    put.raise_for_status()

# Load character sheets
tmp_sheets = load_sheets()
character_sheets = {k: v for k, v in tmp_sheets.items()}

# Health-check server
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

def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0
    complication = False
    # Standard dice
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))
    # Wild die
    w0 = random.randint(1, 6)
    wild_rolls.append(w0)
    if w0 == 1:
        complication = True
        if std_rolls:
            std_rolls.remove(max(std_rolls))
        w1 = random.randint(1, 6)
        wild_rolls.append(w1)
        if w1 == 1:
            total = sum(std_rolls) + modifier
            return std_rolls, wild_rolls, explosions, True, total
        current = w1
    else:
        current = w0
    # Explosions from wild
    while current == 6:
        explosions += 1
        current = random.randint(1, 6)
        wild_rolls.append(current)
    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return std_rolls, wild_rolls, explosions, complication, total


def _compose_and_send(ctx, pool, modifier, image_url, notes, std, wild, expl, comp, total):
    # Load images
    imgs = [Image.open(f"static/d6_std_{d}.png") for d in std] + [Image.open(f"static/d6_wild_{d}.png") for d in wild]
    widths, heights = zip(*(i.size for i in imgs))
    total_w, max_h = sum(widths), max(heights)
    combined = Image.new('RGBA', (total_w, max_h), (0, 0, 0, 0))
    x_offset = 0
    for img in imgs:
        combined.paste(img, (x_offset, 0))
        x_offset += img.width
    combined = combined.resize((int(total_w * 32 / max_h), 32), Image.LANCZOS)
    buf = io.BytesIO()
    combined.save(buf, 'PNG')
    buf.seek(0)

    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(modifier) if modifier else ''}",
        description=notes or None,
        color=discord.Color.gold()
    )
    if image_url:
        embed.set_thumbnail(url=image_url)
    embed.add_field(name='Standard Dice', value=', '.join(map(str, std)) or 'None', inline=False)
    embed.add_field(name='Wild Die', value=', '.join(map(str, wild)) or 'None', inline=False)
    embed.add_field(name='Modifier', value=str(modifier), inline=True)
    embed.add_field(name='Explosions', value=str(expl), inline=True)
    embed.add_field(name='Complication', value='Yes' if comp else 'No', inline=True)
    embed.add_field(name='Total', value=str(total), inline=True)
    embed.set_image(url='attachment://dice.png')
    return embed, buf

@bot.command(name='roll')
async def roll_cmd(ctx, *args):
    """Usage: !roll <pool> [modifier] [image_url] [notes]"""
    if not args:
        return await ctx.send("Usage: !roll <pool> [modifier] [image_url] [notes]")
    # suppress URL preview
    try:
        await ctx.message.edit(suppress=True)
    except discord.Forbidden:
        pass
    # Parse arguments
    pool = 0
    try:
        pool = int(args[0])
    except ValueError:
        return await ctx.send("First argument must be pool (int)")
    modifier = 0
    image_url = None
    notes = None
    idx = 1
    if idx < len(args) and args[idx].lstrip('-').isdigit():
        modifier = int(args[idx])
        idx += 1
    if idx < len(args) and args[idx].startswith(('http://','https://')):
        image_url = args[idx]
        idx += 1
    if idx < len(args):
        raw = ' '.join(args[idx:])
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            notes = raw[1:-1]
        else:
            notes = raw
    std, wild, expl, comp, total = roll_reup(pool, modifier)
    embed, buf = _compose_and_send(ctx, pool, modifier, image_url, notes, std, wild, expl, comp, total)
    await ctx.send(embed=embed, file=File(buf, 'dice.png'))

@bot.group(name='char')
async def char(ctx):
    if not ctx.invoked_subcommand:
        await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

@char.command(name='add')
async def char_add(ctx, name: str, url: str):
    uid = str(ctx.author.id)
    character_sheets.setdefault(uid, {})[name] = url
    save_sheets(character_sheets, msg=f"Add {name}")
    await ctx.send(f"✅ Character '{name}' added.")

@char.command(name='show')
async def char_show(ctx, name: str):
    uid = str(ctx.author.id)
    url = character_sheets.get(uid, {}).get(name)
    if not url:
        return await ctx.send(f"❌ No character named '{name}'.")
    embed =.discord.Embed(title=name, color=discord.Color.blue())
    embed.set_thumbnail(url=url)
    await ctx.send(embed=embed)

@char.command(name='list')
async def char_list(ctx):
    uid = str(ctx.author.id)
    names = character_sheets.get(uid, {}).keys()
    if not names:
        return await ctx.send("No characters registered.")
    await ctx.send(f"📜 {ctx.author.display_name}'s characters:\n" + "\n".join(names))

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
    bot.run(DISCORD_TOKEN)
```
