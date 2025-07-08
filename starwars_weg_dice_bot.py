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

# GitHub JSON persistence
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
    content = r.json()['content']
    return json.loads(base64.b64decode(content))

def save_sheets(sheets, msg='Update sheets'):
    r = requests.get(API_URL_BASE, headers=HEADERS)
    sha = r.json().get('sha') if r.status_code == 200 else None
    encoded = base64.b64encode(json.dumps(sheets, indent=2).encode()).decode()
    payload = {'message': msg, 'content': encoded}
    if sha:
        payload['sha'] = sha
    put = requests.put(API_URL_BASE, headers=HEADERS, json=payload)
    put.raise_for_status()

# Persistent and in-memory stores
character_sheets = load_sheets()
roll_history     = {}                # user_id -> deque of rolls
initiative_order = []                # list of (name, score)
macros           = defaultdict(dict) # user_id -> {name: command}
xp_store         = defaultdict(int) # user_id -> xp
npc_store        = defaultdict(dict)# user_id -> {name: url}

# Flask health-check
app = Flask(__name__)
@app.route('/')
def health():
    return 'OK', 200

def run_health_server():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Discord setup
token = discord_token
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Roll logic
def roll_reup(pool: int, modifier: int = 0):
    std, wild = [], []
    exp = 0; comp = False; cf = False
    for _ in range(max(0, pool-1)): std.append(random.randint(1,6))
    init = random.randint(1,6); wild.append(init)
    if init==1:
        comp=True
        if std: std.remove(max(std))
        nw = random.randint(1,6); wild.append(nw)
        if nw==1: cf=True; return std, wild, exp, comp, cf, modifier
        cur = nw
    else:
        cur = init
    while cur==6:
        exp+=1; cur=random.randint(1,6); wild.append(cur)
    total = sum(std)+sum(wild)+modifier
    return std, wild, exp, comp, cf, total

async def compose_and_send(ctx, pool, mod, thumb, std, wild, exp, comp, cf, total):
    imgs = [Image.open(f"static/d6_std_{d}.png") for d in std] + [Image.open(f"static/d6_wild_{d}.png") for d in wild]
    w,h = zip(*(i.size for i in imgs)); tw, mh = sum(w), max(h)
    combo = Image.new('RGBA',(tw,mh),(0,0,0,0)); x=0
    for i in imgs: combo.paste(i,(x,0)); x+=i.width
    combo = combo.resize((int(tw*32/mh),32),Image.LANCZOS)
    buf=io.BytesIO(); combo.save(buf,'PNG'); buf.seek(0)
    em = discord.Embed(title=f"🎲 {ctx.author.display_name} rolled {pool}D6 {'+'+str(mod) if mod else ''}", color=discord.Color.gold())
    if thumb: em.set_thumbnail(url=thumb)
    em.add_field('Standard Dice',', '.join(map(str,std)) or 'None',False)
    em.add_field('Wild Die',', '.join(map(str,wild)),False)
    em.add_field('Modifier',str(mod),True)
    em.add_field('Explosions',str(exp),True)
    if comp: em.add_field('Complication','Yes',True)
    if cf: em.add_field('Crit Fail','Yes',True)
    em.add_field('Total',str(total),True)
    em.set_image(url='attachment://dice.png')
    await ctx.send(embed=em, file=File(buf, 'dice.png'))

@bot.command(help='!roll <pool> [mod] [tn=<target> or char>])')
async def roll(ctx, pool: int, *args):
    mod=0; tn=None; name=None
    for a in args:
        if a.isdigit(): mod=int(a)
        elif a.startswith('tn='):
            try: tn=int(a.split('=',1)[1])
            except: pass
        else:
            name=(name+' '+a).strip() if name else a
    thumb=None
    if name:
        uid=str(ctx.author.id)
        thumb=character_sheets.get(uid,{}).get(name,name)
    std,wild,exp,comp,cf,total=roll_reup(pool,mod)
    if tn:
        succ=sum(1 for d in std+wild if d>=tn)
        return await ctx.send(f"✅ {ctx.author.display_name} got {succ} successes (TN={tn})")
    await compose_and_send(ctx,pool,mod,thumb,std,wild,exp,comp,cf,total)

@bot.command(help='!privateroll <pool> [mod] [char]')
async def privateroll(ctx,pool:int,*a):
    m=int(a[0]) if a and a[0].isdigit() else 0
    std,wild,exp,comp,cf,total=roll_reup(pool,m)
    dm=await ctx.author.create_dm()
    await compose_and_send(dm,pool,m,None,std,wild,exp,comp,cf,total)

@bot.command(help='!damage <pool> <soak>')
async def damage(ctx,pool:int,soak:int):
    r=[random.randint(1,6) for _ in range(pool)]
    await ctx.send(f"💥 Damage: {r} - {soak} = {sum(r)-soak}")

@bot.group(help='Initiative: add/list/next')
async def init(ctx):
    if not ctx.invoked_subcommand:
        await ctx.send("Usage: !init add <name> <score> | list | next")

@init.command()async def add(ctx,name:str,score:int):
    initiative_order.append((name,score))
    initiative_order.sort(key=lambda x:-x[1])
    await ctx.send(f"Added {name} @ {score}")

@init.command()async def list(ctx):
    if not initiative_order:return await ctx.send("None.")
    await ctx.send("Order:\n"+'\n'.join(f"{n}: {s}" for n,s in initiative_order))

@init.command()async def next(ctx):
    if not initiative_order:return await ctx.send("None.")
    n,s=initiative_order.pop(0)
    await ctx.send(f"Next: {n} ({s})")

@bot.group(help='!char add/show/list/remove')
async def char(ctx):
    if not ctx.invoked_subcommand:
        await ctx.send("Usage: !char add \"Name\" URL | show \"Name\" | list | remove \"Name\"")

@char.command()async def add(ctx,name:str,url:str):
    uid=str(ctx.author.id)
    character_sheets.setdefault(uid,{})[name]=url
    save_sheets(character_sheets,msg=f"Add {name}")
    await ctx.send(f"Registered '{name}'")

@char.command()async def show(ctx,name:str):
    uid=str(ctx.author.id)
    u=character_sheets.get(uid,{}).get(name)
    if not u:return await ctx.send(f"No '{name}'")
    e=discord.Embed(title=name,color=0x0000ff);e.set_thumbnail(url=u)
    await ctx.send(embed=e)

@char.command()
async def list(ctx):
    uid=str(ctx.author.id)
    names=character_sheets.get(uid,{}).keys()
    if not names:return await ctx.send("No chars.")
    cs="\n".join(names)
    await ctx.send(f"📜 {ctx.author.display_name}'s characters:\n{cs}")

@char.command()async def remove(ctx,name:str):
    uid=str(ctx.author.id)
    if name in character_sheets.get(uid,{}):
        character_sheets[uid].pop(name)
        save_sheets(character_sheets,msg=f"Remove {name}")
        await ctx.send(f"Removed '{name}'")
    else:
        await ctx.send(f"No '{name}'")

@bot.command(help='!history')
async def history(ctx):
    h=roll_history.get(str(ctx.author.id),[])
    if not h:return await ctx.send("No history.")
    lines=[]
    for s,w,e,c,cf,t in h:
        if cf:lines.append("🚨 CF");continue
        lines.append(f"Std:{s} Wild:{w} →{t} (Expl:{e}{',Comp' if c else ''})")
    await ctx.send("\n".join(lines))

if __name__=='__main__':
    threading.Thread(target=run_health_server,daemon=True).start()
    bot.run(token)

# NOTE: Enable Message Content Intent in Dev Portal
