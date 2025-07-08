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

# GitHub-backed persistence for character sheets
def load_sheets():
    r = requests.get(API_URL_BASE, headers=HEADERS)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    return json.loads(base64.b64decode(data['content']))

def save_sheets(sheets, msg='Update sheets'):
    r = requests.get(API_URL_BASE, headers=HEADERS)
    sha = r.json().get('sha') if r.status_code==200 else None
    content = base64.b64encode(json.dumps(sheets,indent=2).encode()).decode()
    payload = {'message':msg,'content':content,'sha':sha}
    pr = requests.put(API_URL_BASE, headers=HEADERS, json=payload)
    pr.raise_for_status()

character_sheets = load_sheets()

# In-memory stores
roll_history = {}                       # user_id -> deque of rolls
initiative_order = []                  # list of (name, score)
macros = defaultdict(dict)             # user_id -> {name: command}
xp_store = defaultdict(int)           # user_id -> xp
npc_store = defaultdict(dict)          # user_id -> {name: url}

# Flask health-check
app = Flask(__name__)
@app.route('/')
def health(): return 'OK',200

def run_health_server():
    port = int(os.getenv('PORT',5000))
    app.run('0.0.0.0',port)

# Discord bot setup
token = token
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ReUP roll logic
def roll_reup(pool:int, modifier:int=0):
    std, wild = [], []
    exp, comp, cf = 0, False, False
    for _ in range(max(0,pool-1)): std.append(random.randint(1,6))
    init = random.randint(1,6); wild.append(init)
    if init==1:
        comp=True; std and std.remove(max(std))
        nw=random.randint(1,6); wild.append(nw)
        if nw==1: cf=True; return std,wild,exp,comp,cf,modifier
        cur=nw
    else: cur=init
    while cur==6:
        exp+=1; cur=random.randint(1,6); wild.append(cur)
    total=sum(std)+sum(wild)+modifier
    return std,wild,exp,comp,cf,total

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Generic roll wrapper
def compose_and_send(ctx,pool,modifier,thumb,std_rolls,wild_rolls,exp,comp,cf,total,title_prefix):
    # image
    imgs=[Image.open(f"static/d6_std_{p}.png") for p in std_rolls]
    imgs+=[Image.open(f"static/d6_wild_{p}.png") for p in wild_rolls]
    w,h=zip(*(i.size for i in imgs));tw,mh=sum(w),max(h)
    combo=Image.new('RGBA',(tw,mh),(0,0,0,0));x=0
    for i in imgs: combo.paste(i,(x,0));x+=i.width
    combo=combo.resize((int(tw*32/mh),32),Image.LANCZOS)
    buf=io.BytesIO(); combo.save(buf,'PNG'); buf.seek(0)
    # embed
    em=discord.Embed(title=f"{title_prefix} {pool}D6 {'+'+str(modifier) if modifier else ''}",color=discord.Color.gold())
    if thumb: em.set_thumbnail(url=thumb)
    em.add_field('Standard Dice',', '.join(map(str,std_rolls)) or 'None',False)
    em.add_field('Wild Die',', '.join(map(str,wild_rolls)),False)
    em.add_field('Modifier',str(modifier),True)
    em.add_field('Explosions',str(exp),True)
    comp and em.add_field('Complication','Yes',True)
    cf and em.add_field('Critical Failure','Yes',True)
    em.add_field('Total',str(total),True)
    em.set_image(url='attachment://dice.png')
    await ctx.send(embed=em,file=File(buf,'dice.png'))

# Dice roll commands
@bot.command(help='ReUP d6 roll or success check')
async def roll(ctx,pool:int, *args):
    # parse modifier/tn and thumb
    modifier=0; tn=None; thumb=None; name_or_url=None
    for a in args:
        if a.isdigit(): modifier=int(a)
        elif a.startswith('tn='):
            tn=int(a.split('=')[1])
        else: name_or_url=(name_or_url+' '+a if name_or_url else a)
    # determine thumb
    if name_or_url:
        uid=str(ctx.author.id)
        thumb=character_sheets.get(uid,{}).get(name_or_url,name_or_url)
    std,wild,exp,comp,cf,total=roll_reup(pool,modifier)
    # success mode
    if tn:
        succ=sum(1 for d in std+wild if d>=tn)
        return await ctx.send(f"✅ {ctx.author.display_name} got {succ} successes (TN={tn})")
    # normal
    await compose_and_send(ctx,pool,modifier,thumb,std,wild,exp,comp,cf,total,'🎲')

@bot.command(help='Private roll (DM)')
async def privateroll(ctx,pool:int,modifier:int=0,name_or_url:str=None):
    std,wild,exp,comp,cf,total=roll_reup(pool,modifier)
    dm=await ctx.author.create_dm()
    await compose_and_send(dm,pool,modifier,name_or_url,std,wild,exp,comp,cf,total,'🔒 Private Roll')

@bot.command(help='Damage roll: !damage <pool> <soak>')
async def damage(ctx,pool:int,soak:int):
    std=[random.randint(1,6) for _ in range(pool)]
    total=sum(std)-soak
    await ctx.send(f"💥 Damage Roll: Dice {std} - Soak {soak} = {total}")

# Initiative tracker
@bot.group(help='Manage initiative: add, list, next')
async def init(ctx): pass
@init.command(name='add')
async def init_add(ctx,name:str,score:int):
    initiative_order.append((name,score))
    initiative_order.sort(key=lambda x:-x[1])
    await ctx.send(f"⚔️ Added {name} at {score}")
@init.command(name='list')
async def init_list(ctx):
    lines=[f"{n}: {s}" for n,s in initiative_order]
    await ctx.send("🗡️ Initiative Order:\n"+"\n".join(lines))
@init.command(name='next')
async def init_next(ctx):
    if initiative_order:
        n,s=initiative_order.pop(0)
        await ctx.send(f"➡️ Next: {n} ({s})")
    else: await ctx.send("No more initiative entries.")

# Reminders via automations tool stub (requires automations.create)
@bot.command(help='Schedule a reminder: !remind <minutes> <message>')
async def remind(ctx,minutes:int,*,msg:str):
    from automations import create
    create({"prompt": f"Tell me to {msg}","dtstart_offset_json": "{\"minutes\": %d}"%minutes})
    await ctx.send(f"⏰ Reminder set in {minutes} minutes: {msg}")

# Macro system
@bot.group(help='Define and run macros')
async def macro(ctx): pass
@macro.command(name='add')
async def macro_add(ctx,name:str,*,command:str):
    macros[str(ctx.author.id)][name]=command
    await ctx.send(f"🔖 Macro '{name}' saved.")
@macro.command(name='run')
async def macro_run(ctx,name:str):
    cmd=macros[str(ctx.author.id)].get(name)
    if not cmd: return await ctx.send("Macro not found.")
    await ctx.invoke(*cmd.split())

# XP tracking
@bot.group(help='Track XP: add, show')
async def xp(ctx): pass
@xp.command(name='add')
async def xp_add(ctx,amount:int):
    xp_store[str(ctx.author.id)]+=amount
    await ctx.send(f"🌟 Added {amount} XP. Total: {xp_store[str(ctx.author.id)]}")
@xp.command(name='show')
async def xp_show(ctx):
    await ctx.send(f"🎖️ XP: {xp_store[str(ctx.author.id)]}")

# NPC management (name & URL)
@bot.group(help='Manage NPCs: add, show, list, remove')
async def npc(ctx): pass
@npc.command(name='add')
async def npc_add(ctx,name:str,url:str):
    npc_store[str(ctx.author.id)][name]=url
    await ctx.send(f"🤖 NPC '{name}' added.")
@npc.command(name='show')
async def npc_show(ctx,name:str):
    url=npc_store[str(ctx.author.id)].get(name)
    if not url: return await ctx.send("NPC not found.")
    e=discord.Embed(title=name); e.set_thumbnail(url=url)
    await ctx.send(embed=e)
@npc.command(name='list')
async def npc_list(ctx):
    keys=npc_store[str(ctx.author.id)].keys()
    await ctx.send("NPCs:\n"+"\n".join(keys) if keys else "No NPCs.")
@npc.command(name='remove')
async def npc_remove(ctx,name:str):
    if name in npc_store[str(ctx.author.id)]: npc_store[str(ctx.author.id)].pop(name)
    await ctx.send(f"🗑️ NPC '{name}' removed.")

# History command
@bot.command(help='Show last 10 rolls')
async def history(ctx):
    h=roll_history.get(str(ctx.author.id),[])
    if not h: return await ctx.send("No history.")
    lines=[]
    for s,w,e,c,cf,t in h:
        if cf: lines.append("🚨 CF"); continue
        lines.append(f"Std:{s} Wild:{w} →{t} (Expl:{e}{',Comp' if c else ''})")
    await ctx.send("\n".join(lines))

if __name__=='__main__':
    if not token or not GITHUB_TOKEN:
        print("Missing DISCORD_TOKEN or GITHUB_TOKEN")
    else:
        threading.Thread(target=run_health_server,daemon=True).start()
        bot.run(token)

# NOTE: Message Content Intent must be enabled
