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
# Load existing character sheets or start fresh:
# user_id -> { character_name: { 'portrait': url, 'fields': { key: value, ... } } }
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

# ReUP roll logic (unchanged)
def roll_reup(pool: int, modifier: int = 0):
    std_rolls, wild_rolls = [], []
    explosions = 0; complication = False; critical_failure = False
    for _ in range(max(0, pool - 1)): std_rolls.append(random.randint(1, 6))
    initial = random.randint(1, 6); wild_rolls.append(initial)
    if initial == 1:
        complication = True
        if std_rolls: std_rolls.remove(max(std_rolls))
        new_wild = random.randint(1, 6); wild_rolls.append(new_wild)
        if new_wild == 1: critical_failure = True; return std_rolls, wild_rolls, explosions, complication, critical_failure, modifier
        wild = new_wild
    else: wild = initial
    while wild == 6:
        explosions += 1; wild = random.randint(1, 6); wild_rolls.append(wild)
    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return std_rolls, wild_rolls, explosions, complication, critical_failure, total

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# Roll command
@bot.command(name='roll', help='Roll ReUP D6: !roll <pool> [modifier] [thumb_url]')
async def roll(ctx, pool: int, modifier: int = 0, thumb_url: str = None):
    std_rolls, wild_rolls, explosions, comp, cf, total = roll_reup(pool, modifier)
    roll_history.setdefault(str(ctx.author.id), deque(maxlen=10)).append((std_rolls, wild_rolls, explosions, comp, cf, total))
    if cf:
        return await ctx.send(f"🚨 {ctx.author.display_name} Critical Failure on {pool}D6!")
    # Composite dice image
    imgs = [Image.open(f"static/d6_std_{p}.png") for p in std_rolls]
    imgs += [Image.open(f"static/d6_wild_{p}.png") for p in wild_rolls]
    w, h = zip(*(img.size for img in imgs)); total_w, max_h = sum(w), max(h)
    combo = Image.new('RGBA', (total_w, max_h), (0,0,0,0))
    x=0
    for img in imgs: combo.paste(img, (x,0)); x+=img.width
    scale = 32/max_h; combo = combo.resize((int(total_w*scale),32), Image.LANCZOS)
    buf = io.BytesIO(); combo.save(buf,'PNG'); buf.seek(0)
    # Build embed
    embed = discord.Embed(title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(modifier) if modifier else ''}", color=discord.Color.gold())
    if thumb_url: embed.set_thumbnail(url=thumb_url)
    embed.add_field(name='Standard Dice', value=', '.join(map(str,std_rolls)) or 'None', inline=False)
    embed.add_field(name='Wild Die', value=', '.join(map(str,wild_rolls)), inline=False)
    embed.add_field(name='Modifier', value=str(modifier), inline=True)
    embed.add_field(name='Explosions', value=str(explosions), inline=True)
    if comp: embed.add_field(name='Complication', value='Yes', inline=True)
    embed.add_field(name='Total', value=str(total), inline=True)
    embed.set_image(url='attachment://dice.png')
    await ctx.send(embed=embed, file=File(buf, filename='dice.png'))

# Character management: multiple characters per user
@bot.command(name='char', help='Manage chars: add/show/list/remove')
async def char(ctx, action: str=None, *args):
    uid = str(ctx.author.id)
    if uid not in character_sheets: character_sheets[uid]={}
    user_chars = character_sheets[uid]
    if action=='add' and len(args)>=3:
        name=args[0]; url=args[1]; sheet_raw=' '.join(args[2:])
        # parse sheet by semicolon-separated key:value pairs
        fields={}
        for part in sheet_raw.split(';'):
            if ':' in part:
                k,v=part.split(':',1); fields[k.strip()]=v.strip()
        user_chars[name]={'portrait':url,'fields':fields}
        with open(DATA_FILE,'w') as f: json.dump(character_sheets,f,indent=2)
        return await ctx.send(f"✅ '{name}' added.")
    if action=='show' and len(args)==1:
        name=args[0]
        char=user_chars.get(name)
        if not char: return await ctx.send(f"❌ '{name}' not found.")
        embed=discord.Embed(title=name, color=discord.Color.blue())
        embed.set_thumbnail(url=char['portrait'])
        for k,v in char['fields'].items(): embed.add_field(name=k, value=v, inline=False)
        return await ctx.send(embed=embed)
    if action=='list':
        if not user_chars: return await ctx.send("No characters.")
        return await ctx.send('📜 ' + ctx.author.display_name + "'s characters:\n"+ '\n'.join(user_chars.keys()))
    if action=='remove' and len(args)==1:
        name=args[0]
        if name in user_chars:
            del user_chars[name]
            with open(DATA_FILE,'w') as f: json.dump(character_sheets,f,indent=2)
            return await ctx.send(f"🗑️ '{name}' removed.")
        return await ctx.send(f"❌ '{name}' not found.")
    # help
    return await ctx.send("Usage: !char add <name> <portrait_url> <key:val;...> | show <name> | list | remove <name>")

# History command
@bot.command(name='history', help='Show last 10 rolls')
async def history(ctx):
    h=roll_history.get(str(ctx.author.id),[])
    if not h: return await ctx.send("No history.")
    lines=[]
    for std,wild,exp,comp,cf,total in h:
        if cf: lines.append("🚨 Critical Failure"); continue
        extra=f"Expl:{exp}{', Comp' if comp else ''}"
        lines.append(f"Std:{std} Wild:{wild} → {total} ({extra})")
    await ctx.send("\n".join(lines))

if __name__=='__main__':
    TOKEN=os.getenv('DISCORD_TOKEN')
    if not TOKEN: print("Missing DISCORD_TOKEN")
    else:
        threading.Thread(target=run_health_server,daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable Message Content Intent in Discord Developer Portal
