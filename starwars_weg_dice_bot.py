import os
import random
import io
import json
import base64
import requests
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

token = os.getenv('DISCORD_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_OWNER = 'YourGitHubUsername'
GITHUB_REPO = 'YourRepoName'
FILE_PATH = 'character_sheets.json'
API_URL_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{FILE_PATH}"
HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Functions to load/save sheets via GitHub API

def load_sheets():
    resp = requests.get(API_URL_BASE, headers=HEADERS)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data['content'])
    return json.loads(content)


def save_sheets(sheets, commit_message='Update character sheets'):
    # fetch current sha
    resp = requests.get(API_URL_BASE, headers=HEADERS)
    if resp.status_code not in (200, 404):
        resp.raise_for_status()
    sha = resp.json().get('sha') if resp.status_code == 200 else None
    encoded = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {
        'message': commit_message,
        'content': encoded,
        'sha': sha
    }
    put = requests.put(API_URL_BASE, headers=HEADERS, json=payload)
    put.raise_for_status()
    return put.json()

# Initialize character sheets from GitHub
character_sheets = load_sheets()

# Health-check server for Render
app = Flask(__name__)
@app.route('/')
def health(): return 'OK', 200

def run_health_server():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Configure Discord bot
token = token
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# In-memory roll history
roll_history = {}

# ReUP roll logic
def roll_reup(pool: int, modifier: int = 0):
    std, wild = [], []
    exp = 0; comp = False; cf = False
    for _ in range(max(0, pool-1)): std.append(random.randint(1,6))
    init = random.randint(1,6); wild.append(init)
    if init == 1:
        comp = True
        if std: std.remove(max(std))
        nw = random.randint(1,6); wild.append(nw)
        if nw == 1:
            cf = True
            return std, wild, exp, comp, cf, modifier
        cur = nw
    else:
        cur = init
    while cur == 6:
        exp += 1
        cur = random.randint(1,6)
        wild.append(cur)
    total = sum(std) + sum(wild) + modifier
    return std, wild, exp, comp, cf, total

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# Roll command
@bot.command(name='roll', help='!roll <pool> [modifier or char] [char or url]')
async def roll(ctx, pool: int, *args):
    modifier = 0
    char_or_url = None
    if args:
        if args[0].isdigit():
            modifier = int(args[0])
            if len(args) > 1:
                char_or_url = ' '.join(args[1:])
        else:
            char_or_url = ' '.join(args)
    thumb = None
    if char_or_url:
        user = str(ctx.author.id)
        thumb = character_sheets.get(user, {}).get(char_or_url, char_or_url)
    std_rolls, wild_rolls, explosions, comp, cf, total = roll_reup(pool, modifier)
    roll_history.setdefault(str(ctx.author.id), deque(maxlen=10)).append((std_rolls, wild_rolls, explosions, comp, cf, total))
    if cf:
        return await ctx.send(f"🚨 {ctx.author.display_name} Critical Failure on {pool}D6!")
    imgs = [Image.open(f"static/d6_std_{p}.png") for p in std_rolls] + [Image.open(f"static/d6_wild_{p}.png") for p in wild_rolls]
    w,h = zip(*(i.size for i in imgs)); tw, mh = sum(w), max(h)
    combo = Image.new('RGBA',(tw,mh),(0,0,0,0)); x=0
    for i in imgs: combo.paste(i,(x,0)); x+=i.width
    combo = combo.resize((int(tw*32/mh),32), Image.LANCZOS)
    buf = io.BytesIO(); combo.save(buf,'PNG'); buf.seek(0)
    em = discord.Embed(title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(modifier) if modifier else ''}", color=discord.Color.gold())
    if thumb: em.set_thumbnail(url=thumb)
    em.add_field(name='Standard Dice', value=', '.join(map(str,std_rolls)) or 'None', inline=False)
    em.add_field(name='Wild Die', value=', '.join(map(str,wild_rolls)), inline=False)
    em.add_field(name='Modifier', value=str(modifier), inline=True)
    em.add_field(name='Explosions', value=str(explosions), inline=True)
    if comp: em.add_field(name='Complication', value='Yes', inline=True)
    em.add_field(name='Total', value=str(total), inline=True)
    em.set_image(url='attachment://dice.png')
    await ctx.send(embed=em, file=File(buf, filename='dice.png'))

# Character management
@bot.command(name='char', help='!char add "Name" URL | show "Name" | list | remove "Name"')
async def char(ctx, action: str = None, name: str = None, url: str = None):
    uid = str(ctx.author.id)
    if uid not in character_sheets: character_sheets[uid] = {}
    ucs = character_sheets[uid]
    if action == 'add' and name and url:
        ucs[name] = url
        save_sheets(character_sheets, commit_message=f"Add {name} by {ctx.author.id}")
        return await ctx.send(f"✅ '{name}' registered.")
    if action == 'show' and name:
        p = ucs.get(name)
        if not p: return await ctx.send(f"❌ '{name}' not found.")
        e = discord.Embed(title=name, color=discord.Color.blue()); e.set_thumbnail(url=p)
        return await ctx.send(embed=e)
    if action == 'list':
        if not ucs: return await ctx.send("No characters.")
        return await ctx.send('📜 ' + ctx.author.display_name + "'s chars:\n" + '\n'.join(ucs.keys()))
    if action == 'remove' and name:
        if name in ucs:
            ucs.pop(name)
            save_sheets(character_sheets, commit_message=f"Remove {name} by {ctx.author.id}")
            return await ctx.send(f"🗑️ '{name}' removed.")
        return await ctx.send(f"❌ '{name}' not found.")
    return await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

# History command
@bot.command(name='history', help='Show last 10 rolls')
async def history(ctx):
    h = roll_history.get(str(ctx.author.id), [])
    if not h: return await ctx.send("No history.")
    lines = []
    for s, w, e, c, cf, t in h:
        if cf: lines.append("🚨 Critical Failure"); continue
        extra = f"Expl:{e}{', Comp' if c else ''}"
        lines.append(f"Std:{s} Wild:{w} → {t} ({extra})")
    await ctx.send("\n".join(lines))

if __name__ == '__main__':
    if not token or not GITHUB_TOKEN: print("Missing DISCORD_TOKEN or GITHUB_TOKEN")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(token)

# NOTE: Enable Message Content Intent in Dev Portal
