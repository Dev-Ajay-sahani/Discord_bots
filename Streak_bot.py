import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import json
import asyncio
import os
import pytz

# Set these manually
DISCORD_TOKEN = ""
CHANNEL_ID = 1379153204838928404  # Replace with your channel ID
ROLE_ID = 1379157676667179179     # Replace with your role ID

IST = pytz.timezone("Asia/Kolkata")
DATA_FILE = "streaks.json"

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_streak(user_id: str) -> int:
    data = load_data()
    return data.get(user_id, {}).get("streak", 0)

def increment_streak(user_id: str) -> bool:
    now = datetime.now(IST)
    today_9pm = now.replace(hour=21, minute=0, second=0, microsecond=0)
    window_start = today_9pm - timedelta(days=1) if now < today_9pm else today_9pm

    data = load_data()
    user_data = data.get(user_id, {})
    last_updated_str = user_data.get("last_updated")

    if last_updated_str:
        last_updated = datetime.fromisoformat(last_updated_str).astimezone(IST)
        if last_updated >= window_start:
            return False

    data[user_id] = {
        "streak": user_data.get("streak", 0) + 1,
        "last_updated": now.isoformat()
    }
    save_data(data)
    return True

def reset_streak(user_id: str):
    data = load_data()
    data[user_id] = {
        "streak": 0,
        "last_updated": datetime.now(IST).isoformat()
    }
    save_data(data)

def get_streak_stamp(user_id):
    data = load_data()
    user_data = data.get(user_id)
    if not user_data:
        return "❌❌❌❌❌❌❌"

    last_updated = datetime.fromisoformat(user_data["last_updated"]).astimezone(IST)
    streak = user_data["streak"]
    now = datetime.now(IST)

    stamps = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        cutoff = day.replace(hour=21, minute=0, second=0, microsecond=0)
        if last_updated.date() == cutoff.date() and streak > 0:
            stamps.append("✅")
        elif i < streak:
            stamps.append("✅")
        else:
            stamps.append("❌")
    return "".join(stamps)

RANKS = [
    (1095, "🕊️💎 Eternal Transcendent"),
    (1090, "🌌 Boundless Starborn"),
    (1075, "🪬 Seraph of the Void"),
    (1060, "🫧 Crystalline Dreamer"),
    (1045, "🌌 Paradox Ascender"),
    (1030, "🌄 Zenith Treader"),
    (1015, "🛐 Halo-Touched"),
    (1000, "📜 Mythwalker"),
    (985,  "🎴 Illusion Weaver"),
    (970,  "⚙️ Clockwork Sentinel"),
    (955,  "🌀 Nexus Guardian"),
    (940,  "🩶 Saint of Shadows"),
    (925,  "🌟 Light Unending"),
    (910,  "🕊️ Dawn of Silence"),
    (895,  "🔔 Echo of Time"),
    (880,  "🌐 Code of Creation"),
    (865,  "🔗 Dimensional Anchor"),
    (850,  "📿 Reincarnated Sage"),
    (835,  "💫 Fatebinder"),
    (820,  "🌪️ Whisper of Storms"),
    (805,  "🌿 Gaia’s Herald"),
    (790,  "🦋 Phantom Chrysalis"),
    (775,  "🧿 Soul Architect"),
    (760,  "🩸 Lifeblood Eternum"),
    (745,  "⛓️ Chainbreaker"),
    (730,  "👑 Legacy Incarnate"), 
    (715,  "🌌 Halo of Origins"),
    (700,  "🎭 Faceless Immortal"),
    (685,  "🪐 Orbital Paladin"),
    (670,  "🌈 Spectrum Wielder"),
    (655,  "🧿 Seer of Aeons"),
    (640,  "🔥 Ember of Eons"),
    (625,  "🐲 Eternity’s Scale"),
    (610,  "🦅 Celestial Hawk"),
    (595,  "🌊 Tidal Ascendant"),
    (580,  "⚡ Tempest Channeler"),
    (565,  "🧊 Frost Monarch"),
    (550,  "🌫️ Mistborn Prophet"),
    (535,  "☀️ Dawnbringer"),
    (520,  "🌙 Moonlit Sentinel"),
    (505,  "🌌 Void Navigator"),
    (490,  "🔮 Dreamwalker"),
    (475,  "🪷 Boundless Nirvana"),
    (460,  "🐉 Primal Origin"),
    (445,  "🧿 Karma Weaver"),
    (430,  "🎇 Reality Rewriter"),
    (415,  "🪦 Deathless Wanderer"),
    (400,  "🌋 Volcanic Heart"),
    (385,  "🪞 Reflection Beyond Time"),
    (370,  "💿 Arcane Codebearer"),
    (355,  "🧠 Ultra Instinct Mind"),
    (340,  "🛸 Galactic Nomad"),
    (325,  "⚛️ Quantum Sovereign"),
    (310,  "🕰️ Timeless Observer"),
    (295,  "🦴 Warden of Realms"),
    (280,  "👁️ All-Seeing Oracle"),
    (265,  "🩻 Ethereal Phantom"),
    (250,  "🧬 Reality Binder"),
    (235,  "🪐 Stellar Overlord"),
    (220,  "🌀 Cosmic Architect"),
    (205,  "🌠 Eternal Flamebearer"),
    (190,  "🌌 Celestial Paragon"),
    (175,  "💫 Infinity Wielder"),
    (160,  "🕳️ Dimensional Conqueror"),
    (145,  "🪽 Spirit of the Beyond"),
    (130,  "🌟 Ascendant Eternity"),
    (115,  "🧿 Omniversal Being"),
    (100, "💠 The Absolute One"),
    (95, "🕊️ True Sovereign"),
    (90, "⚡ Slayer of Gods"),
    (85, "🌌 World Shatterer"),
    (80, "🔱 Ascended Reaper"),
    (70, "👑 Shadow Monarch"),
    (60, "🩸 Monarch’s Vessel"),
    (50, "🕶️ Shadow Commander"),
    (40, "🌑 Shadow Wielder"),
    (30, "💥 S-Rank Breaker"),
    (20, "🏆 A-Rank Champion"),
    (15, "🏹 B-Rank Sentinel"),
    (10, "🛡️ C-Rank Slayer"),
    (5, "⚔️ D-Rank Reaper"),
    (1, "🐣 E-Rank Seeker")
]
def get_rank_title(streak):
    for threshold, title in RANKS:
        if streak >= threshold:
            return title
    return "Unranked"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user.name}')
    reminder_check.start()

@bot.command()
async def streakon(ctx):
    user_id = str(ctx.author.id)
    
    if increment_streak(user_id):
        await asyncio.sleep(1)
        new_streak = get_streak(user_id)
        rank = get_rank_title(new_streak)
        stamp = get_streak_stamp(user_id)

        celebration = ""
        # ✅ FIX: check the *new* streak for milestone, not yesterday
        if new_streak in [7, 21, 30,40, 45,55, 69, 75, 90, 100,150,200,250,300,350,400,450,500,550,600,650,700,750,800,850,900,1000,1100,1200,1300,1400,1500,1600,1700,1800,1900,2000,2100,2200,2300,2400,2500,2600,2700,2800,2900,3000]:
            celebration = f"🎉 **Milestone achieved: {new_streak} days!** 🎉\n"

        await ctx.send(
            f"✅ {ctx.author.mention} Streak updated!\n🔥 Current streak: **{new_streak} days**\n"
            f"🏅 Rank: {rank}\n🗓️ History: {stamp}\n{celebration}"
        )
    else:
        await ctx.send(f"⚠️ {ctx.author.mention} You’ve already checked in today. Try again after 9 PM!")

@bot.command()
async def streakbroken(ctx):
    reset_streak(str(ctx.author.id))
    await ctx.send(f"❌ {ctx.author.mention} Your streak has been reset to 0. Let's restart 🔁")

@bot.command()
async def nightfall(ctx):
    streak = get_streak(str(ctx.author.id))
    await ctx.send(
        f"🌙 {ctx.author.mention} It is fine, don't feel guilty. It is a natural process. No loss.\n🔥 Your streak remains: **{streak} days**"
    )

@bot.command()
async def leaderboard(ctx):
    data = load_data()
    sorted_data = sorted(data.items(), key=lambda x: x[1].get("streak", 0), reverse=True)
    message = "**🏆 NoFap Leaderboard 🏆**\n\n"

    for i, (user_id, info) in enumerate(sorted_data[:10], start=1):
        try:
            user_obj = await bot.fetch_user(int(user_id))
            username = user_obj.name
        except:
            username = f"User ID {user_id}"
        rank = get_rank_title(info["streak"])
        stamp = get_streak_stamp(user_id)
        message += f"**#{i}** - {username} — **{info['streak']}** days | {rank} | {stamp}\n"

    await ctx.send(message)

@bot.event
async def on_message(message):
    if message.author.id == bot.user.id:
        return

    SAPPHIRE_ID = 678344927997853742
    if message.author.id == SAPPHIRE_ID and message.mentions:
        mentioned_user = message.mentions[0]
        user_id = str(mentioned_user.id)
        content = message.content.lower()

        if "!streakon" in content:
            if increment_streak(user_id):
                streak = get_streak(user_id)
                await message.channel.send(f"✅ {mentioned_user.mention} Streak updated! Current streak: **{streak} days** 💪")
            else:
                now = datetime.now(IST)
                today_9pm = now.replace(hour=21, minute=0, second=0, microsecond=0)
                next_checkin = today_9pm if now < today_9pm else today_9pm + timedelta(days=1)
                diff = next_checkin - now
                hours, remainder = divmod(diff.seconds, 3600)
                minutes = remainder // 60
                await message.channel.send(f"⚠️ {mentioned_user.mention} Already checked in today. Your next Check in **{hours}h {minutes}m** ")

        elif "!streakbroken" in content or "!justdone" in content:
            reset_streak(user_id)
            await message.channel.send(f"❌ {mentioned_user.mention} Your streak has been reset to 0. Let's restart 🔁")

        elif "!nightfall" in content:
            streak = get_streak(user_id)
            await message.channel.send(
                f"🌙 {mentioned_user.mention} It is fine, don't feel guilty. It is a natural process. No loss.\n🔥 Your streak remains: **{streak} days**"
            )

        elif "!leaderboard" in content:
            data = load_data()
            sorted_data = sorted(data.items(), key=lambda x: x[1].get("streak", 0), reverse=True)
            msg = "**🏆 NoFap Leaderboard 🏆**\n\n"
            for i, (uid, info) in enumerate(sorted_data[:10], start=1):
                try:
                    user_obj = await bot.fetch_user(int(uid))
                    name = user_obj.name
                except:
                    name = f"User ID {uid}"
                rank = get_rank_title(info["streak"])
                stamp = get_streak_stamp(uid)
                msg += f"**#{i}** - {name} — **{info['streak']}** days | {rank} | {stamp}\n"
            await message.channel.send(msg)

    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def reminder_check():
    now = datetime.now(IST)
    if now.hour == 21 and now.minute == 0:
        channel = bot.get_channel(CHANNEL_ID)
        guild = discord.utils.get(bot.guilds)
        if guild:
            role = discord.utils.get(guild.roles, id=ROLE_ID)
            if channel and role:
                await channel.send(f"🔔 {role.mention} ⬇️ **Choose Option Below**⬇️ **Daily Check in**")

bot.run(DISCORD_TOKEN)


