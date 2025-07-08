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

# Load environment variables from .env if present
load_dotenv()

# Data file for persistent character sheets
data_file = 'character_sheets.json'
# Load existing character sheets or start fresh
try:
    with open(data_file, 'r') as f:
        raw = json.load(f)
        # Convert keys back to int and values to tuple
        character_sheets = {int(k): tuple(v) for k, v in raw.items()}
except FileNotFoundError:
    character_sheets = {}

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

# In-memory storage
roll_history = {}          # user_id -> deque of last 10 roll tuples

# ReUP roll function
...  # [unchanged roll_reup code here]

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

# roll command unchanged
...  # [unchanged roll command code here]

@bot.command(name='char', help='Save or view your character sheet: !char [portrait_url] <sheet_text>')
async def char(ctx, portrait_url: str = None, *, sheet_text: str = None):
    if portrait_url and sheet_text:
        # Save character sheet in memory
        character_sheets[ctx.author.id] = (sheet_text, portrait_url)
        # Persist to disk
        to_save = {str(k): list(v) for k, v in character_sheets.items()}
        with open(data_file, 'w') as f:
            json.dump(to_save, f, indent=2)
        await ctx.send(f"✅ {ctx.author.display_name}'s character sheet saved.")
    else:
        # Retrieve and display
        data = character_sheets.get(ctx.author.id)
        if not data:
            return await ctx.send("You have no character sheet saved. Use `!char <portrait_url> <sheet_text>` to add one.")
        sheet, url = data
        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Character Sheet",
            description=sheet,
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=url)
        await ctx.send(embed=embed)

# history command unchanged
...  # [unchanged history command code here]

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN env var not set.")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        bot.run(TOKEN)

# NOTE: Enable Message Content Intent in Developer Portal
