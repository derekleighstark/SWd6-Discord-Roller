import os
import threading
import io
import random
import re  # NEW: regex for !swdice parsing
from dotenv import load_dotenv
from flask import Flask
import discord
from discord.ext import commands
from PIL import Image

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    print("Error: Missing DISCORD_TOKEN")
    exit(1)

# ────────────────────────────────────────────────────────────────
# ReUP dice‑rolling logic (official: no reroll on 1)
# ────────────────────────────────────────────────────────────────

def roll_reup(pool: int, modifier: int):
    """Return detailed results for a ReUP roll."""
    std_dice = [random.randint(1, 6) for _ in range(max(pool - 1, 0))]

    wild = random.randint(1, 6)
    wild_rolls = [wild]
    explosions = 0

    # Explode on 6
    while wild == 6:
        explosions += 1
        wild = random.randint(1, 6)
        wild_rolls.append(wild)

    complication = (wild_rolls[0] == 1)
    total = sum(std_dice) + sum(wild_rolls) + modifier

    return std_dice, wild_rolls, modifier, explosions, complication, total


# ────────────────────────────────────────────────────────────────
# Health‑check server for uptime‑services like Replit / Fly.io
# ────────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/")
def health():
    return "OK", 200


def run_health_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# ────────────────────────────────────────────────────────────────
# Discord bot setup
# ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ────────────────────────────────────────────────────────────────
# !swroll – ReUP Wild‑Die mechanic
# ────────────────────────────────────────────────────────────────
@bot.command(name="swroll")
async def roll_cmd(ctx, *args):
    # Suppress URL preview from the original message
    try:
        await ctx.message.edit(suppress=True)
    except discord.Forbidden:
        pass

    if not args:
        await ctx.send("Usage: !swroll <pool> [modifier] [image_url] [notes]")
        return

    try:
        pool = int(args[0])
    except ValueError:
        await ctx.send("❌ Pool must be an integer.")
        return

    modifier = 0
    idx = 1

    # Optional modifier
    if idx < len(args):
        try:
            modifier = int(args[idx])
            idx += 1
        except ValueError:
            modifier = 0

    # Optional image URL
    url = None
    if idx < len(args) and args[idx].startswith(("http://", "https://")):
        url = args[idx]
        idx += 1

    # Optional notes
    notes = None
    if idx < len(args):
        notes = " ".join(args[idx:])
        if (notes.startswith('"') and notes.endswith('"')) or \
           (notes.startswith("'") and notes.endswith("'")):
            notes = notes[1:-1]

    # Perform the roll
    std_dice, wild_rolls, modifier, explosions, complication, total = roll_reup(pool, modifier)

    # Detect true Critical Failure (1→1 on wild)
    critical_failure = False
    if complication and len(wild_rolls) >= 2 and wild_rolls[1] == 1:
        critical_failure = True

    # Build embed header
    if critical_failure:
        embed = discord.Embed(title="🚨 Critical Failure on ReUP Roll!", color=0xFF0000)
    else:
        embed = discord.Embed(title=f"🎲 {ctx.author.display_name} rolled {pool}D6", color=0xFFD700)

    # Attach notes & thumbnail
    if notes:
        embed.description = notes
    if url:
        embed.set_thumbnail(url=url)

    # Add fields
    embed.add_field(name="Standard Dice", value=", ".join(map(str, std_dice)) or "None", inline=True)
    embed.add_field(name="Wild Die",      value=", ".join(map(str, wild_rolls)),       inline=True)
    embed.add_field(name="Modifier",      value=str(modifier),                          inline=True)
    embed.add_field(name="Explosions",    value=str(explosions),                        inline=True)
    embed.add_field(name="Complication",  value="Yes" if complication else "No",        inline=True)
    embed.add_field(name="Total",         value=str(total),                             inline=False)

    # GM option reminder if complication
    if complication:
        embed.add_field(
            name="GM Option",
            value=(
                "Wild d6=1 → GM may:\n"
                "1) add normally\n"
                "2) subtract this & highest die\n"
                "3) add normally & introduce complication"
            ),
            inline=False
        )

    # Composite dice image for flair ---------------------------
    images = []
    for pip in std_dice:
        images.append(Image.open(f"static/d6_std_{pip}.png"))
    for pip in wild_rolls:
        images.append(Image.open(f"static/d6_wild_{pip}.png"))

    if images:
        widths, heights = zip(*(im.size for im in images))
        total_w = sum(widths)
        combined = Image.new("RGBA", (total_w, heights[0]))
        x_offset = 0
        for im in images:
            combined.paste(im, (x_offset, 0))
            x_offset += im.width

        # Resize to 64 px height
        target_h = 64
        scale = target_h / heights[0]
        combined = combined.resize((int(total_w * scale), target_h), Image.LANCZOS)

        buf = io.BytesIO()
        combined.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="dice.png")
        embed.set_image(url="attachment://dice.png")
        await ctx.send(embed=embed, file=file)
    else:
        await ctx.send(embed=embed)


# ────────────────────────────────────────────────────────────────
# !swdice – generic polyhedral roller (XdY ± Z)
# ────────────────────────────────────────────────────────────────
@bot.command(name="swdice", aliases=["swd"])
async def dice_cmd(ctx, *, expr: str | None = None):
    """Roll standard polyhedral dice. Examples:
    !swdice 3d6
    !swdice 2d20+4
    !swdice 1d10-1"""

    try:
        await ctx.message.edit(suppress=True)
    except discord.Forbidden:
        pass

    if not expr:
        await ctx.send("Usage: `!swdice XdY+Z` – e.g. `!swdice 4d8+2`")
        return

    match = re.fullmatch(r"\s*(\d+)[dD](\d+)\s*([+\-]\s*\d+)?\s*", expr)
    if not match:
        await ctx.send("❌ I couldn’t read that. Try something like `3d6+1`.")
        return

    qty   = int(match.group(1))
    sides = int(match.group(2))
    mod   = int(match.group(3).replace(" ", "")) if match.group(3) else 0

    if qty <= 0 or sides <= 0:
        await ctx.send("❌ Dice quantity and sides must both be positive numbers.")
        return

    rolls = [random.randint(1, sides) for _ in range(qty)]
    total = sum(rolls) + mod

    embed = discord.Embed(
        title=f"🎲 {ctx.author.display_name} rolled {qty}d{sides}",
        color=0x3498DB if mod == 0 else 0x9B59B6
    )
    embed.add_field(name="Rolls",    value=", ".join(map(str, rolls)), inline=False)
    embed.add_field(name="Modifier", value=str(mod),                  inline=True)
    embed.add_field(name="Total",    value=str(total),                inline=True)

    await ctx.send(embed=embed)


# ────────────────────────────────────────────────────────────────
# Main entry
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.run(DISCORD_TOKEN)
