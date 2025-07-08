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

# ReUP roll function implementing Wild Die rules
def roll_reup(pool: int, modifier: int = 0):
    result = {
        'pool': pool,
        'modifier': modifier,
        'rolls': [],
        'explosions': 0,
        'complication': False,
        'critical_failure': False,
        'total': modifier
    }
    if pool < 1:
        return result

    # 1. Roll (pool - 1) standard dice with exploding sixes
    std_rolls = []
    for _ in range(pool - 1):
        r = random.randint(1, 6)
        std_rolls.append(r)
        while r == 6:
            result['explosions'] += 1
            r = random.randint(1, 6)
            std_rolls.append(r)

    # 2. Roll Wild Die
    wild = random.randint(1, 6)

    # 3. If Wild = 1: complication, remove highest std die, re-roll wild
    if wild == 1:
        result['complication'] = True
        if std_rolls:
            # remove exactly one highest die
            std_rolls.remove(max(std_rolls))
        # re-roll wild die once
        wild = random.randint(1, 6)
        if wild == 1:
            # critical failure
            result['critical_failure'] = True
            result['rolls'] = std_rolls.copy()
            result['total'] = modifier
            return result

    # 4. Add remaining standard rolls and the (re-)rolled wild
    rolls = std_rolls.copy()
    rolls.append(wild)

    # 5. Handle wild explosions
    temp = wild
    while temp == 6:
        result['explosions'] += 1
        temp = random.randint(1, 6)
        rolls.append(temp)

    # 6. Sum up total
    result['rolls'] = rolls
    result['total'] = sum(rolls) + modifier
    return result

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

    # Critical failure short-circuit
    if res['critical_failure']:
        await ctx.send(f"🚨 {ctx.author.display_name} suffered a critical failure on ReUP {res['pool']}D6!")
        return

    # Build and send response
    rolls_str = ', '.join(str(r) for r in res['rolls'])
    desc = (
        f"🎲 {ctx.author.display_name} rolled ReUP {res['pool']}D6 {'+'+str(res['modifier']) if res['modifier'] else ''}: {rolls_str}\n"
        f"💥 Explosions: {res['explosions']}\n"
    )
    if res['complication']:
        desc += "⚠️ Complication! (Wild Die initial=1)\n"
    desc += f"🔀 Total: {res['total']}"
    await ctx.send(desc)

@bot.command(name='history', help='Show your last 10 ReUP rolls')
async def history(ctx):
    user_hist = roll_history.get(ctx.author.id)
    if not user_hist:
        await ctx.send(f"{ctx.author.display_name}, no roll history.")
        return
    lines = []
    for e in user_hist:
        if e['critical_failure']:
            lines.append(f"🚨 {e['pool']}D6: Critical Failure")
            continue
        line = f"{e['pool']}D6{'+'+str(e['modifier']) if e['modifier'] else ''}: {e['rolls']} -> {e['total']}"
        if e['explosions'] > 0:
            line += f" (Explosions:{e['explosions']})"
        if e['complication']:
            line += " ⚠️"
        lines.append(line)
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
