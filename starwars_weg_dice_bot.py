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
# Supports only Revised & Updated (ReUP) rules

# Configure intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# History storage: user_id -> deque of last 10 roll dicts
roll_history = {}

# ReUP roll function: pool includes wild die
def roll_reup(pool: int, modifier: int = 0):
    if pool < 1:
        return {"pool": pool, "modifier": modifier, "rolls": [], "total": modifier, "explosions": 0, "complication": False}
    rolls = []
    explosions = 0
    complication = False
    # Standard dice (pool - 1)
    for _ in range(pool - 1):
        r = random.randint(1, 6)
        rolls.append(r)
        while r == 6:
            explosions += 1
            r = random.randint(1, 6)
            rolls.append(r)
    # Wild die
    wild = random.randint(1, 6)
    rolls.append(wild)
    if wild == 1:
        complication = True
    else:
        while wild == 6:
            explosions += 1
            wild = random.randint(1, 6)
            rolls.append(wild)
    total = sum(rolls) + modifier
    return {"pool": pool, "modifier": modifier, "rolls": rolls, "total": total, "explosions": explosions, "complication": complication}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command(name='roll', help='Roll ReUP WEG D6: !roll <pool> [modifier]')
async def roll(ctx, pool: int, modifier: int = 0):
    result = roll_reup(pool, modifier)
    # Store in history
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append(result)

    # Build and send response
    rolls_str = ', '.join(str(r) for r in result['rolls'])
    desc = (
        f"🎲 {ctx.author.display_name} rolled ReUP {result['pool']}D6 {'+'+str(result['modifier']) if result['modifier'] else ''}: {rolls_str}\n"
        f"💥 Explosions: {result['explosions']}\n"
    )
    if result['complication']:
        desc += "⚠️ Complication!\n"
    desc += f"🔀 Total: {result['total']}"
    await ctx.send(desc)

@bot.command(name='history', help='Show your last 10 ReUP rolls')
async def history(ctx):
    user_hist = roll_history.get(ctx.author.id)
    if not user_hist:
        return await ctx.send(f"{ctx.author.display_name}, no roll history.")
    lines = []
    for e in user_hist:
        line = (
            f"{e['pool']}D6{'+'+str(e['modifier']) if e['modifier'] else ''}: {e['rolls']} -> {e['total']}"
        )
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
        # Start health server and run bot
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable 'Message Content Intent' in Discord Developer Portal under Bot settings
