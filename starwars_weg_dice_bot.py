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

# Health-check Flask server
app = Flask(__name__)

@app.route('/')
def health():
    return 'OK', 200

def run_health_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Star Wars WEG D6 Dice Roller Bot
# Supports: 1st Edition (1e) and Revised & Updated (reup)

# Configure intents: need message_content for prefix commands
intents = discord.Intents.default()
intents.message_content = True  # enable message content intent
bot = commands.Bot(command_prefix='!', intents=intents)

# History storage: user_id -> deque of last 10 roll dicts
roll_history = {}

# Edition-specific roll functions
def roll_1e(pool: int, modifier: int = 0):
    rolls = [random.randint(1, 6) for _ in range(pool)]
    total = sum(rolls) + modifier
    return {"edition": "1e", "pool": pool, "modifier": modifier, "rolls": rolls, "total": total}


def roll_reup(pool: int, modifier: int = 0):
    if pool < 1:
        return {"edition": "reup", "pool": pool, "modifier": modifier, "rolls": [], "total": modifier, "explosions": 0, "complication": False}
    rolls = []
    explosions = 0
    complication = False
    # Standard dice
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
    return {"edition": "reup", "pool": pool, "modifier": modifier, "rolls": rolls, "total": total, "explosions": explosions, "complication": complication}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command(name='roll', help='Roll WEG D6. Usage: !roll [edition] <pool> [modifier]  (edition: 1e, reup)')
async def roll(ctx, *args):
    edition = 'reup'
    try:
        if len(args) >= 2 and args[0].lower() in ('1e', 'reup'):
            edition = args[0].lower()
            pool = int(args[1])
            modifier = int(args[2]) if len(args) > 2 else 0
        else:
            pool = int(args[0])
            modifier = int(args[1]) if len(args) > 1 else 0
    except (ValueError, IndexError):
        return await ctx.send("Usage: !roll [edition] <pool> [modifier]  (edition: 1e, reup)")

    # Perform the roll
    if edition == '1e':
        result = roll_1e(pool, modifier)
    else:
        result = roll_reup(pool, modifier)

    # Store in history
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append(result)

    # Build and send response
    roll_str = ', '.join(str(r) for r in result['rolls'])
    desc = f"🎲 {ctx.author.display_name} rolled ({result['edition']}) {result['pool']}D6 {'+'+str(result['modifier']) if result['modifier'] else ''}: {roll_str}\n"
    if edition == 'reup':
        desc += f"💥 Explosions: {result.get('explosions',0)}\n"
        if result.get('complication'):
            desc += "⚠️ Complication!\n"
    desc += f"🔀 Total: {result['total']}"
    await ctx.send(desc)

@bot.command(name='history', help='Show your last 10 rolls')
async def history(ctx):
    user_hist = roll_history.get(ctx.author.id)
    if not user_hist:
        return await ctx.send(f"{ctx.author.display_name}, no roll history.")
    lines = []
    for e in user_hist:
        line = f"({e['edition']}) {e['pool']}D6{'+'+str(e['modifier']) if e['modifier'] else ''}: {e['rolls']} -> {e['total']}"
        if e['edition'] == 'reup' and e.get('explosions',0) > 0:
            line += f" (Explosions:{e['explosions']})"
        if e.get('complication'):
            line += " ⚠️"
        lines.append(line)
    await ctx.send(f"{ctx.author.display_name}'s rolls:\n" + "\n".join(lines))

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set.")
        print("Make sure you have a .env file or environment variable DISCORD_TOKEN defined.")
    else:
        # Start health-check server
        threading.Thread(target=run_health_server, daemon=True).start()
        # Run the Discord bot
        bot.run(TOKEN)

# NOTE: Make sure 'Message Content Intent' is enabled in the Discord Developer Portal under Bot → Privileged Gateway Intents
