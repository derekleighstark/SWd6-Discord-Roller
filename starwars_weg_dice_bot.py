import os
import random
import discord
from discord.ext import commands
from discord import File
from collections import deque
import threading
from flask import Flask
from dotenv import load_dotenv

# Load environment variables from .env if present
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

# Configure Discord intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# In-memory history storage: user_id -> deque of last 10 roll dicts
roll_history = {}

# ReUP roll function with separate standard and wild dice
def roll_reup(pool: int, modifier: int = 0):
    # initialize
    std_rolls = []
    wild_rolls = []
    explosions = 0
    complication = False
    critical_failure = False

    # Roll standard dice (pool - 1), no explosions
    for _ in range(max(0, pool - 1)):
        std_rolls.append(random.randint(1, 6))

    # Roll initial Wild Die
    initial_wild = random.randint(1, 6)
    wild_rolls.append(initial_wild)

    # Check for complication on initial Wild
    if initial_wild == 1:
        complication = True
        # remove one highest standard die
        if std_rolls:
            std_rolls.remove(max(std_rolls))
        # re-roll wild once
        new_wild = random.randint(1, 6)
        wild_rolls.append(new_wild)
        if new_wild == 1:
            # critical failure: no further resolution
            critical_failure = True
            return {
                'pool': pool,
                'modifier': modifier,
                'std_rolls': std_rolls,
                'wild_rolls': wild_rolls,
                'explosions': 0,
                'complication': True,
                'critical_failure': True,
                'total': modifier
            }
        wild = new_wild
    else:
        wild = initial_wild

    # Handle explosion chain on wild die
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
        'critical_failure': critical_failure,
        'total': total
    }

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command(name='roll', help='Roll ReUP WEG D6: !roll <pool> [modifier]')
async def roll(ctx, pool: int, modifier: int = 0):
    res = roll_reup(pool, modifier)

    # Store in history
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append(res)

    # Critical failure response
    if res['critical_failure']:
        return await ctx.send(f"🚨 {ctx.author.display_name} suffered a Critical Failure on ReUP {res['pool']}D6!")

    # Build header and footer text
    header = f"🎲 {ctx.author.display_name} rolled ReUP {res['pool']}D6 {'+'+str(modifier) if modifier else ''}\n"
    footer = f"🔀 Total: {res['total']}"

    # Prepare attachments list
    files = []
    # Attach standard dice images
    for idx, pip in enumerate(res['std_rolls']):
        path = f"static/d6_std_{pip}.png"
        files.append(File(path, filename=f"std{idx}_{pip}.png"))
    # Attach wild die images
    for idx, pip in enumerate(res['wild_rolls']):
        path = "static/d6_wild.png"
        files.append(File(path, filename=f"wild{idx}_{pip}.png"))

    # Send message with attachments inline
    await ctx.send(header + footer, files=files)

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
        extras = f"Explosions: {e['explosions']}"
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
        # Start health-check server and run bot
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable 'Message Content Intent' in Discord Developer Portal under Bot settings
