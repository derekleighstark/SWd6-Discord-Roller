import os
import random
import discord
from discord.ext import commands
from collections import deque
import threading
from flask import Flask
from dotenv import load_dotenv

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

# Configure intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# History storage: user_id -> deque of last 10 roll dicts
roll_history = {}

# ReUP roll function with separate standard and wild dice
def roll_reup(pool: int, modifier: int = 0):
    # initialize
    std_rolls = []
    wild_rolls = []
    explosions = 0
    complication = False
    critical_failure = False

    # Standard dice (pool - 1), no explosions
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))

    # Wild Die initial roll
    wild = random.randint(1, 6)
    # Check complication
    if wild == 1:
        complication = True
        # remove highest standard die if exists
        if std_rolls:
            std_rolls.remove(max(std_rolls))
        # re-roll wild once
        wild = random.randint(1, 6)
        if wild == 1:
            # critical failure: no further rolls
            critical_failure = True
            return {
                'pool': pool,
                'modifier': modifier,
                'std_rolls': std_rolls,
                'wild_rolls': [],
                'explosions': 0,
                'complication': True,
                'critical_failure': True,
                'total': modifier
            }
    # record wild
    wild_rolls.append(wild)
    # Wild Die explosions
    while wild == 6:
        explosions += 1
        wild = random.randint(1, 6)
        wild_rolls.append(wild)

    total = sum(std_rolls) + sum(wild_rolls) + modifier
    return {
        'pool': pool,
        'modifier': modifier,
        'std_rolls': std_rolls,
        'wild_rolls': wild_rolls,
        'explosions': explosions,
        'complication': complication,
        'critical_failure': False,
        'total': total
    }

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command(name='roll', help='Roll ReUP WEG D6: !roll <pool> [modifier]')
async def roll(ctx, pool: int, modifier: int = 0):
    res = roll_reup(pool, modifier)
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append(res)

    # Build embed for results
    if res['critical_failure']:
        embed = discord.Embed(
            title=f"🚨 {ctx.author.display_name}'s Critical Failure!",
            description=f"ReUP {res['pool']}D6",
            color=discord.Color.dark_red()
        )
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled ReUP {res['pool']}D6",
        color=discord.Color.gold()
    )
    # Standard dice field
    std_val = ', '.join(str(d) for d in res['std_rolls']) or 'None'
    embed.add_field(name='Standard Dice', value=std_val, inline=False)
    # Wild dice field, colored via embed color highlight
    wild_val = ', '.join(str(d) for d in res['wild_rolls'])
    embed.add_field(name='Wild Die', value=wild_val, inline=False)

    # Explosions and complications
    embed.add_field(name='Explosions', value=str(res['explosions']), inline=True)
    if res['complication']:
        embed.add_field(name='Complication', value='Yes', inline=True)

    # Total
    embed.add_field(name='Modifier', value=str(res['modifier']), inline=True)
    embed.add_field(name='Total', value=str(res['total']), inline=True)

    await ctx.send(embed=embed)

@bot.command(name='history', help='Show your last 10 ReUP rolls')
async def history(ctx):
    user_hist = roll_history.get(ctx.author.id)
    if not user_hist:
        return await ctx.send(f"{ctx.author.display_name}, no roll history.")
    lines = []
    for e in user_hist:
        if e['critical_failure']:
            lines.append(f"🚨 {e['pool']}D6: Critical Failure")
            continue
        std = f"Std: [{', '.join(map(str,e['std_rolls']))}]"
        wild = f"Wild: [{', '.join(map(str,e['wild_rolls']))}]"
        extras = f"Expl:{e['explosions']}"
        if e['complication']:
            extras += ", Complication"
        lines.append(f"{std} {wild} → Total {e['total']} ({extras})")
    await ctx.send(f"{ctx.author.display_name}'s ReUP rolls:\n" + "\n".join(lines))

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set.")
        print("Ensure you have a .env file with DISCORD_TOKEN or set it in environment variables.")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable 'Message Content Intent' in Discord Developer Portal under Bot settings
