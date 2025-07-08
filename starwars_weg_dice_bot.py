import os
import random
import io
import json
import base64
import requests
import discord
from discord.ext import commands
from discord import File
from collections import deque, defaultdict
import threading
from flask import Flask
from dotenv import load_dotenv
from PIL import Image
from datetime import datetime, timedelta
import asyncio

# Load environment variables
load_dotenv()

discord_token = os.getenv('DISCORD_TOKEN')
if not discord_token:
    raise RuntimeError('DISCORD_TOKEN not set in environment')

github_token = os.getenv('GITHUB_TOKEN')
github_owner = os.getenv('GITHUB_OWNER')
github_repo  = os.getenv('GITHUB_REPO')
if not (github_token and github_owner and github_repo):
    raise RuntimeError('GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO must be set in environment')

FILE_PATH = 'character_sheets.json'
API_URL_BASE = (
    f"https://api.github.com/repos/{github_owner}/{github_repo}"
    f"/contents/{FILE_PATH}"
)
HEADERS = {
    'Authorization': f'token {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}

# GitHub-backed persistence for character sheets

def load_sheets():
    r = requests.get(API_URL_BASE, headers=HEADERS)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    return json.loads(base64.b64decode(data['content']))


def save_sheets(sheets, msg='Update character sheets'):
    r = requests.get(API_URL_BASE, headers=HEADERS)
    sha = r.json().get('sha') if r.status_code == 200 else None
    content = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {'message': msg, 'content': content, 'sha': sha}
    pr = requests.put(API_URL_BASE, headers=HEADERS, json=payload)
    pr.raise_for_status()

# Initialize persistent stores
character_sheets = load_sheets()
roll_history     = {}                # user_id -> deque of rolls
initiative_order = []                # list of (name, score)
macros           = defaultdict(dict) # user_id -> {name: command}
xp_store         = defaultdict(int)  # user_id -> xp
npc_store        = defaultdict(dict) # user_id -> {name: url}

# Flask health-check server for Render
app = Flask(__name__)
@app.route('/')
def health(): return 'OK', 200

def run_health_server():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Discord bot setup
token = discord_token
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ReUP roll logic
def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0
    complication = False
    critical_failure = False
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))
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
        current = new_wild
    else:
        current = initial
    while current == 6:
        explosions += 1
        current = random.randint(1, 6)
        wild_rolls.append(current)
    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return std_rolls, wild_rolls, explosions, complication, critical_failure, total

# Helper to compose and send roll embed
async def compose_and_send(ctx, pool, modifier, thumb, std, wild, expl, comp, cf, total, prefix):
    images = [Image.open(f"static/d6_std_{p}.png") for p in std] + [Image.open(f"static/d6_wild_{p}.png") for p in wild]
    widths, heights = zip(*(img.size for img in images))
    total_w, max_h = sum(widths), max(heights)
    combined = Image.new('RGBA', (total_w, max_h), (0,0,0,0))
    x_offset = 0
    for img in images:
        combined.paste(img, (x_offset, 0))
        x_offset += img.width
    combined = combined.resize((int(total_w * 32 / max_h), 32), Image.LANCZOS)
    buf = io.BytesIO(); combined.save(buf, 'PNG'); buf.seek(0)

    embed = discord.Embed(title=f"{prefix} {pool}D6 {'+'+str(modifier) if modifier else ''}", color=discord.Color.gold())
    if thumb:
        embed.set_thumbnail(url=thumb)
    embed.add_field(name='Standard Dice', value=', '.join(map(str, std)) or 'None', inline=False)
    embed.add_field(name='Wild Die',       value=', '.join(map(str, wild)),           inline=False)
    embed.add_field(name='Modifier',       value=str(modifier),                     inline=True)
    embed.add_field(name='Explosions',     value=str(expl),                         inline=True)
    if comp:
        embed.add_field(name='Complication', value='Yes',                              inline=True)
    if cf:
        embed.add_field(name='Critical Failure', value='Yes',                         inline=True)
    embed.add_field(name='Total',          value=str(total),                        inline=True)
    embed.set_image(url='attachment://dice.png')

    await ctx.send(embed=embed, file=File(buf, filename='dice.png'))

# Roll command with TN support
@bot.command(help='!roll <pool> [modifier] [tn=<target> or character>]')
async def roll(ctx, pool: int, *args):
    modifier = 0
    target = None
    char_or_url = None
    for arg in args:
        if arg.isdigit():
            modifier = int(arg)
        elif arg.startswith('tn='):
            try: target = int(arg.split('=',1)[1])
            except: pass
        else:
            char_or_url = (char_or_url+' '+arg).strip() if char_or_url else arg
    thumb = None
    if char_or_url:
        uid = str(ctx.author.id)
        thumb = character_sheets.get(uid, {}).get(char_or_url, char_or_url)

    std, wild, expl, comp, cf, total = roll_reup(pool, modifier)
    if target:
        succ = sum(1 for d in std+wild if d>=target)
        return await ctx.send(f"✅ {ctx.author.display_name} got {succ} successes (TN={target})")
    await compose_and_send(ctx, pool, modifier, thumb, std, wild, expl, comp, cf, total, '🎲')

# Private roll
@bot.command(help='!privateroll <pool> [modifier] [character]')
async def privateroll(ctx, pool: int, *args):
    mod = int(args[0]) if args and args[0].isdigit() else 0
    std, wild, expl, comp, cf, total = roll_reup(pool, mod)
    dm = await ctx.author.create_dm()
    await compose_and_send(dm, pool, mod, None, std, wild, expl, comp, cf, total, '🔒 Private Roll')

# Damage roll
@bot.command(help='!damage <pool> <soak>')
async def damage(ctx, pool: int, soak: int):
    rolls = [random.randint(1,6) for _ in range(pool)]
    dmg = sum(rolls)-soak
    await ctx.send(f"💥 Damage Roll: {rolls} - Soak {soak} = {dmg}")

# Initiative tracker\@bot.group(help='Initiative: add, list, next')
async def init(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send("Usage: !init add <name> <score> | list | next")

@init.command(name='add')
async def init_add(ctx, name: str, score: int):
    initiative_order.append((name, score))
    initiative_order.sort(key=lambda x:-x[1])
    await ctx.send(f"⚔️ Added {name} at {score}")

@init.command(name='list')
async def init_list(ctx):
    if not initiative_order:
        return await ctx.send("No initiative entries.")
    order = '\n'.join(f"{n}: {s}" for n,s in initiative_order)
    await ctx.send("🗡️ Initiative Order:\n"+order)

@init.command(name='next')
async def init_next(ctx):
    if not initiative_order:
        return await ctx.send("No more initiative entries.")
    name, score = initiative_order.pop(0)
    await ctx.send(f"➡️ Next: {name} ({score})")

# Reminders (requires automations tool)
@bot.command(help='!remind <minutes> <message>')
async def remind(ctx, minutes: int, *, msg: str):
    from automations import create
    create({"prompt":f"Tell me to {msg}","dtstart_offset_json":json.dumps({'minutes':minutes})})
    await ctx.send(f"⏰ Reminder set in {minutes} minutes: {msg}")

# Macros
@bot.group(help='Macros: add, run, list, remove')
async def macro(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send("Usage: !macro add <name> <command> | run <name> | list | remove <name>")

@macro.command(name='add')
async def macro_add(ctx, name: str, *, command: str):
    macros[str(ctx.author.id)][name] = command
    await ctx.send(f"🔖 Macro '{name}' saved.")

@macro.command(name='run')
async def macro_run(ctx, name: str):
    cmd=macros[str(ctx.author.id)].get(name)
    if not cmd: return await ctx.send("Macro not found.")
    parts=cmd.split()
    await ctx.invoke(bot.get_command(parts[0]), *parts[1:])

@macro.command(name='list')
async def macro_list(ctx):
    m=macros[str(ctx.author.id)]
    if not m: return await ctx.send("No macros defined.")
    await ctx.send("Macros:\n"+'\n'.join(m.keys()))

@macro.command(name='remove')
async def macro_remove(ctx, name: str):
    if name in macros[str(ctx.author.id)]: macros[str(ctx.author.id)].pop(name); await ctx.send(f"🗑️ Macro '{name}' removed.")
    else: await ctx.send("Macro not found.")

# Character management
@bot.group(help='Characters: add, show, list, remove')
async def char(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

@char.command(name='add')
async def char_add(ctx, name: str, url: str):
    uid=str(ctx.author.id)
    character_sheets.setdefault(uid,{})
    character_sheets[uid][name]=url
    save_sheets(character_sheets,msg=f"Add {name} by {ctx.author.id}")
    await ctx.send(f"✅ Character '{name}' registered.")

@char.command(name='show')
async def char_show(ctx, name: str):
    uid=str(ctx.author.id)
    url=character_sheets.get(uid,{}).get(name)
    if not url: return await ctx.send(f"❌ No character named '{name}'.")
    e=discord.Embed(title=name,color=discord.Color.blue());e.set_thumbnail(url=url)
    await ctx.send(embed=e)

@char.command(name='list')
async def char_list(ctx):
    uid = str(ctx.author.id)
    names = character_sheets.get(uid, {}).keys()
    if not names:
        await ctx.send("No characters registered.")
        return
    char_list_str = '
'.join(names)
    await ctx.send(f"📜 {ctx.author.display_name}'s characters:
{char_list_str}")
