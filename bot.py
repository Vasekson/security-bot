import discord
from discord.ext import commands
from discord import app_commands
import re
import json
import os
from datetime import datetime, timedelta

# ================== NASTAVENÍ ==================

GUILD_ID = 1462556019959005360  # <-- TVÉ ID SERVERU (už opraveno)
LOG_CHANNEL_NAME = "log"

# anti-raid
MAX_JOINS = 5
JOIN_TIME = 10  # sekund

# anti-flood
FLOOD_MESSAGES = 5
FLOOD_TIME = 6  # sekund

# anti-alt
MIN_ACCOUNT_AGE_DAYS = 7

BAD_WORDS = ["scam", "free nitro", "crypto"]
LINK_REGEX = re.compile(r"https?://")

# ==============================================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

join_tracker = {}
message_tracker = {}
warnings = {}

raid_active = False
raid_until = None

# ================== WARN STORAGE ==================

def load_warnings():
    global warnings
    try:
        with open("warnings.json", "r") as f:
            warnings = json.load(f)
    except FileNotFoundError:
        warnings = {}

def save_warnings():
    with open("warnings.json", "w") as f:
        json.dump(warnings, f)

# ================== READY ==================

@bot.event
async def on_ready():
    load_warnings()

    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        print("✅ Slash příkazy syncnuty pro server")
    except Exception as e:
        print(f"⚠️ Slash sync selhal (bot běží dál): {e}")

    print(f"🤖 Bot přihlášen jako {bot.user}")

# ================== ANTI-ALT + ANTI-RAID ==================

@bot.event
async def on_member_join(member):
    global raid_active, raid_until

    now = datetime.utcnow()
    guild = member.guild
    log = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    # anti-alt
    age = (now - member.created_at).days
    if age < MIN_ACCOUNT_AGE_DAYS:
        await member.kick(reason="Anti-alt: nový účet")
        if log:
            await log.send(f"🧪 **ANTI-ALT** – {member} kicknut (účet {age} dní)")
        return

    # anti-raid
    join_tracker.setdefault(guild.id, [])
    join_tracker[guild.id] = [
        t for t in join_tracker[guild.id]
        if now - t < timedelta(seconds=JOIN_TIME)
    ]
    join_tracker[guild.id].append(now)

    if len(join_tracker[guild.id]) >= MAX_JOINS and not raid_active:
        raid_active = True
        raid_until = now + timedelta(minutes=5)

        for channel in guild.text_channels:
            await channel.set_permissions(guild.default_role, send_messages=False)

        if log:
            await log.send("🚨 **ANTI-RAID – chat uzamčen na 5 minut**")

    if raid_active and now > raid_until:
        raid_active = False
        for channel in guild.text_channels:
            await channel.set_permissions(guild.default_role, send_messages=True)
        if log:
            await log.send("✅ **ANTI-RAID UKONČEN – chat odemčen**")

# ================== ANTI-SPAM ==================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    now = datetime.utcnow()
    uid = str(message.author.id)
    guild = message.guild
    log = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    # anti-flood
    message_tracker.setdefault(uid, [])
    message_tracker[uid] = [
        t for t in message_tracker[uid]
        if now - t < timedelta(seconds=FLOOD_TIME)
    ]
    message_tracker[uid].append(now)

    if len(message_tracker[uid]) >= FLOOD_MESSAGES:
        await message.delete()
        await warn_user(message.author, guild, "Flood spam")
        if log:
            await log.send(f"⚡ **ANTI-FLOOD** – {message.author}")
        return

    content = message.content.lower()

    if any(word in content for word in BAD_WORDS):
        await message.delete()
        await warn_user(message.author, guild, "Zakázané slovo")
        return

    if LINK_REGEX.search(content):
        await message.delete()
        await warn_user(message.author, guild, "Zakázaný odkaz")
        return

    await bot.process_commands(message)

# ================== WARN / MUTE / BAN ==================

async def warn_user(member, guild, reason):
    uid = str(member.id)
    warnings.setdefault(uid, 0)
    warnings[uid] += 1
    save_warnings()

    log = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    if warnings[uid] == 2:
        mute = discord.utils.get(guild.roles, name="Muted")
        if mute:
            await member.add_roles(mute)
            if log:
                await log.send(f"🔇 {member} mute (2 warny)")

    if warnings[uid] >= 3:
        await member.ban(reason="3 warny")
        if log:
            await log.send(f"⛔ {member} BAN (3 warny)")

# ================== SLASH PŘÍKAZY ==================

@tree.command(
    name="warn",
    description="Varuje uživatele",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Bez důvodu"):
    await warn_user(member, interaction.guild, reason)
    await interaction.response.send_message(f"⚠️ {member.mention} varován: {reason}")

@tree.command(
    name="warnings",
    description="Zobrazí počet warnů",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    count = warnings.get(str(member.id), 0)
    await interaction.response.send_message(f"📊 {member.mention} má **{count}** warnů")

@tree.command(
    name="ban",
    description="Zabanuje uživatele",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Bez důvodu"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"⛔ {member.mention} byl zabanován: {reason}")

@tree.command(
    name="lock",
    description="Uzamkne chat",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(manage_channels=True)
async def lock_cmd(interaction: discord.Interaction):
    for channel in interaction.guild.text_channels:
        await channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔐 Chat uzamčen")

@tree.command(
    name="unlock",
    description="Odemkne chat",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock_cmd(interaction: discord.Interaction):
    for channel in interaction.guild.text_channels:
        await channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Chat odemčen")

# ================== START ==================

TOKEN = os.getenv("TOKEN")
bot.run(TOKEN)
