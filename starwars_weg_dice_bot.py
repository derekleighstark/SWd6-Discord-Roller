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
GITHUB_REPO  = os.getenv('GITHUB_REPO')
if not DISCORD_TOKEN:
    raise RuntimeError('DISCORD_TOKEN not set')
if not (GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO):
    raise RuntimeError('GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO must be set')

# GitHub persistence for !char
FILE_PATH = 'character_sheets.json'
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{FILE_PATH}"
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

def load_sheets():
    resp = requests.get(API_URL, headers=HEADERS)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    data = resp.json()
    return json.loads(base64.b64decode(data.get('content', '')))


def save_sheets(sheets, msg='Update sheets'):
    resp = requests.get(API_URL, headers=HEADERS)
    sha = resp.json().get('sha') if resp.status_code == 200 else None
    content = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {'message': msg, 'content': content}
    if sha:
        payload['sha'] = sha
    put = requests.put(API_URL, headers=HEADERS, json=payload)
    put.raise_for_status()

# Load sheets
character_sheets = load_sheets()

# Health-check server
app = Flask(__name__)
@app.route('/')
def health():
    return 'OK', 200

def run_health_server():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Discord setup
token = DISCORD_TOKEN
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ReUP roll logic
def roll_reup(pool: int, modifier: int = 0):
    std, wild = [], []
    explosions = 0
    complication = False
    for _ in range(max(0, pool - 1)):
        std.append(random.randint(1, 6))
    w0 = random.randint(1, 6)
    wild.append(w0)
    if w0 == 1:
        complication = True
        if std:
            std.remove(max(std))
        w1 = random.randint(1, 6)
        wild.append(w1)
        if w1 == 1:
            return std, wild, 0, True, modifier
        current = w1
    else:
        current = w0
    while current == 6:
        explosions += 1
        current = random.randint(1, 6)
        wild.append(current)
    total = sum(std) + sum(wild) + modifier
    return std, wild, explosions, complication, total

# Roll command parsing all args to avoid converter errors
@bot.command(name='roll')
async def roll(ctx, *args):
    # Usage: !roll <pool> [modifier] [image_url] [notes...]
    if not args:
        return await ctx.send("Usage: !roll <pool> [modifier] [image_url] [notes]")
    # pool
    try:
        pool = int(args[0])
    except ValueError:
        return await ctx.send("First argument must be pool size (int)")
    modifier = 0
    image_url = None
    notes = None
    idx = 1
    # modifier
    if idx < len(args) and args[idx].lstrip('-').isdigit():
        modifier = int(args[idx]); idx += 1
    # image_url
    if idx < len(args) and args[idx].startswith(('http://','https://')):
        image_url = args[idx]; idx += 1
    # notes
    if idx < len(args):
        raw = ' '.join(args[idx:])
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            notes = raw[1:-1]
        else:
            notes = raw
    # roll
    std, wild, expl, comp, total = roll_reup(pool, modifier)
    # compose image
    imgs = [Image.open(f"static/d6_std_{d}.png") for d in std] + [Image.open(f"static/d6_wild_{d}.png") for d in wild]
    w,h = zip(*(i.size for i in imgs)); tw,mh = sum(w), max(h)
    combo = Image.new('RGBA',(tw,mh),(0,0,0,0)); x=0
    for i in imgs: combo.paste(i,(x,0)); x+=i.width
    combo = combo.resize((int(tw*32/mh),32),Image.LANCZOS)
    buf=io.BytesIO(); combo.save(buf,'PNG'); buf.seek(0)
    # embed
    em = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(modifier) if modifier else ''}",
        description=notes or discord.Embed.Empty,
        color=discord.Color.gold()
    )
    if image_url: em.set_thumbnail(url=image_url)
    em.add_field('Standard Dice',', '.join(map(str,std)) or 'None',False)
    em.add_field('Wild Die',', '.join(map(str,wild)),False)
    em.add_field('Modifier',str(modifier),True)
    em.add_field('Explosions',str(expl),True)
    em.add_field('Complication','Yes' if comp else 'No',True)
    em.add_field('Total',str(total),True)
    em.set_image(url='attachment://dice.png')
    await ctx.send(embed=em, file=File(buf,'dice.png'))

# Character management
@bot.group(name='char')
async def char(ctx):
    if not ctx.invoked_subcommand:
        await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

@char.command(name='add')
async def char_add(ctx, name: str, url: str):
    uid = str(ctx.author.id)
    character_sheets.setdefault(uid,{})[name]=url
    save_sheets(character_sheets,msg=f"Add {name}")
    await ctx.send(f"✅ Character '{name}' added.")

@char.command(name='show')
async def char_show(ctx, name: str):
    uid = str(ctx.author.id)
    url = character_sheets.get(uid,{}).get(name)
    if not url: return await ctx.send(f"❌ No '{name}'")
    e=discord.Embed(title=name,color=discord.Color.blue()); e.set_thumbnail(url=url)
    await ctx.send(embed=e)

@char.command(name='list')
async def char_list(ctx):
    uid = str(ctx.author.id)
    names = character_sheets.get(uid,{}).keys()
    if not names: return await ctx.send("No characters.")
    await ctx.send(f"📜 {ctx.author.display_name}'s characters:\n" + "\n".join(names))

@char.command(name='remove')
async def char_remove(ctx, name: str):
    uid = str(ctx.author.id)
    if name in character_sheets.get(uid,{}):
        character_sheets[uid].pop(name)
        save_sheets(character_sheets,msg=f"Remove {name}")
        await ctx.send(f"🗑️ Character '{name}' removed.")
    else:
        await ctx.send(f"❌ No '{name}'")

if __name__=='__main__':
    threading.Thread(target=run_health_server,daemon=True).start()
    bot.run(token)

# Enable Message Content Intent
