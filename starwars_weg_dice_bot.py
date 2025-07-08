import os
import random
import discord
from discord.ext import commands
from collections import deque

# Star Wars WEG D6 Dice Roller Bot
# Supports: 1st Edition (1e) and Revised & Updated (reup)
# Features:
# - 1e: pool of D6, sum only
# - reup: pool-1 standard D6 + 1 wild die (explode on 6, 1 = complication)
# - Modifiers, roll history (last 10 per user)
# - Unified !roll command

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

# History: user_id -> deque of last 10 roll dicts
roll_history = {}

# Edition-specific roll functions
def roll_1e(pool: int, modifier: int = 0):
    rolls = [random.randint(1, 6) for _ in range(pool)]
    total = sum(rolls) + modifier
    return {"edition": "1e", "pool": pool, "modifier": modifier, "rolls": rolls, "total": total}


def roll_reup(pool: int, modifier: int = 0):
    # reup behavior: pool includes wild die
    if pool < 1:
        return {"edition": "reup", "pool": pool, "modifier": modifier, "rolls": [], "total": modifier, "explosions": 0, "complication": False}
    rolls = []
    explosions = 0
    complication = False
    # standard dice
    for _ in range(pool - 1):
        r = random.randint(1, 6)
        rolls.append(r)
        while r == 6:
            explosions += 1
            r = random.randint(1, 6)
            rolls.append(r)
    # wild die
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
    # Parse args: optional edition
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

    # Perform roll
    if edition == '1e':
        result = roll_1e(pool, modifier)
    else:
        result = roll_reup(pool, modifier)

    # Record history
    user_hist = roll_history.setdefault(ctx.author.id, deque(maxlen=10))
    user_hist.append(result)

    # Build response
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
    TOKEN = os.getenv('655f674042c8295dd8b33b779bb73ab27bbe1c41a5b6cd17d5a7d1681d16bfe0')
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set.")
    else:
        bot.run(TOKEN)
