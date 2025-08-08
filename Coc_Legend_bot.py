import discord
from discord.ext import commands, tasks
import aiohttp
import json
import os
import asyncio
import csv
import io
import logging
from datetime import datetime, timezone, timedelta
import pytz
from urllib.parse import quote

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIG ===
TOKEN = ""
CHANNEL_ID = 1363201757211001083
API = "https://api.clashk.ing"
COC_API = "https://api.clashofclans.com/v1/players/"
COC_BEARER = ""
COC_HEADERS = {
    "Authorization": f"Bearer {COC_BEARER}",
    "Accept": "application/json"
}
HEADERS = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
DATA_FILE = "players.json"
SEASONAL_FILE = "seasonal.json"
IST = pytz.timezone("Asia/Kolkata")

# Global session for connection pooling
session = None

# === DATA UTILS ===
def load_players():
    return json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}

def save_players(data):
    json.dump(data, open(DATA_FILE, "w"), indent=2)

def load_seasonal():
    return json.load(open(SEASONAL_FILE)) if os.path.exists(SEASONAL_FILE) else {}

def save_seasonal(data):
    json.dump(data, open(SEASONAL_FILE, "w"), indent=2)

def load_prev_trophies(path="previous.json"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

def save_prev_trophies(prev_data, path="previous.json"):
    with open(path, "w") as f:
        json.dump(prev_data, f, indent=2)

players = load_players()

# === BOT SETUP ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="-", intents=intents)

# === ENHANCED SESSION MANAGEMENT ===
async def get_session():
    """Get or create global aiohttp session with improved settings"""
    global session
    if session is None or session.closed:
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            use_dns_cache=True,
            keepalive_timeout=60,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_read=10
        )
        
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={'Connection': 'keep-alive'}
        )
    return session

async def fetch_api(endpoint, params=None, retries=3):
    """Enhanced API fetch function with better error handling"""
    for attempt in range(retries):
        try:
            api_session = await get_session()
            url = API + endpoint
            
            async with api_session.get(url, headers=HEADERS, params=params) as res:
                if res.status == 200:
                    return await res.json()
                else:
                    logger.warning(f"API call failed: {endpoint}, status: {res.status}, attempt: {attempt + 1}")
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionResetError) as e:
            logger.error(f"API fetch error for {endpoint}, attempt {attempt + 1}: {e}")
            if attempt < retries - 1:
                # Close and recreate session on connection errors
                if session and not session.closed:
                    await session.close()
                session = None
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            logger.error(f"Unexpected API fetch error for {endpoint}: {e}")
            break
    
    return None

async def fetch_coc(tag):
    """Fetch player data from Clash of Clans API"""
    try:
        coc_session = await get_session()
        url = f"{COC_API}%23{tag}"
        headers = COC_HEADERS
        
        async with coc_session.get(url, headers=headers) as res:
            if res.status == 200:
                return await res.json()
            else:
                logger.warning(f"COC API call failed: {tag}, status: {res.status}")
                return None
    except Exception as e:
        logger.error(f"COC API fetch error for {tag}: {e}")
        return None

def get_current_clash_day():
    now = datetime.now(IST)
    reset = now.replace(hour=10, minute=30, second=0, microsecond=0)
    if now < reset:
        clash_day = (now - timedelta(days=1)).date().isoformat()
    else:
        clash_day = now.date().isoformat()
    return clash_day

def is_season_reset_time():
    """Check if it's last Monday 10:30 AM IST"""
    now = datetime.now(IST)
    return (
        now.weekday() == 0 and  # Monday
        (now + timedelta(days=7)).month != now.month and  # Last Monday
        now.hour == 10 and now.minute == 30  # Exactly 10:30 AM
    )

def transfer_daily_to_seasonal():
    """Transfer daily data from players.json to seasonal.json at 10:30 AM"""
    clash_day = get_current_clash_day()
    seasonal_data = load_seasonal()
    
    for name, info in players.items():
        tag = info['tag']
        legend_log = info.get("legend_log", {})
        
        if clash_day in legend_log:
            day_data = legend_log[clash_day]
            
            # Initialize player in seasonal if not exists
            if tag not in seasonal_data:
                seasonal_data[tag] = {}
            
            # Store the day's data
            seasonal_data[tag][clash_day] = {
                "offense": day_data.get("attack", []),
                "defense": day_data.get("defense", []),
                "start_trophies": day_data.get("start_trophies")
            }
    
    save_seasonal(seasonal_data)
    
    # Clear daily data from players.json
    for name, info in players.items():
        info["legend_log"] = {}
        info["legend"] = {"attack": 0, "defense": 0}
    
    save_players(players)
    logger.info(f"Daily data transferred to seasonal.json for {clash_day}")

# === STARTUP ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    seasonal_reset.start()
    monitor.start()
    daily_transfer.start()

# === DAILY DATA TRANSFER TASK ===
@tasks.loop(minutes=1)
async def daily_transfer():
    """Transfer data at 10:30 AM IST daily"""
    now = datetime.now(IST)
    if now.hour == 10 and now.minute == 30:
        transfer_daily_to_seasonal()

# === SEASONAL RESET TASK ===
@tasks.loop(minutes=3)
async def seasonal_reset():
    now = datetime.now(IST)
    seasonal_path = SEASONAL_FILE
    flag_file = "seasonal_reset.flag"

    if is_season_reset_time():
        # Prevent multiple resets in the same minute
        if not os.path.exists(flag_file):
            with open(seasonal_path, "w") as f:
                json.dump({}, f, indent=2)
            with open(flag_file, "w") as f:
                f.write("reset done")

            print("🧹 seasonal.json cleared on last Monday at 10:30 AM IST")

            # Optional: Notify a channel
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                await channel.send("🧹 `seasonal.json` cleared! A new season begins.")
    else:
        # Remove the flag if it's not the reset time anymore
        if os.path.exists(flag_file):
            os.remove(flag_file)

# === MONITOR TASK ===
@tasks.loop(minutes=1)
async def monitor():
    try:
        channel = bot.get_channel(CHANNEL_ID)
        now = datetime.now(IST)
        clash_day = get_current_clash_day()

        # Load previous trophies from separate file
        prev_data = load_prev_trophies()

        for name, info in players.items():
            tag = info['tag']
            coc_data = await fetch_coc(tag)
            if not coc_data:
                print(f"[{name}] No coc data.")
                continue

            trophies = coc_data.get("trophies")
            if trophies is None:
                print(f"[{name}] No trophy data.")
                continue

            prev_trophies = prev_data.get(name)
            if prev_trophies is None:
                prev_data[name] = trophies
                save_prev_trophies(prev_data)
                continue  # First run, skip to avoid fake delta

            delta = trophies - prev_trophies
            print(f"[{name}] Current: {trophies}, Previous: {prev_trophies}, Delta: {delta}")

            if delta == 0:
                continue  # No change

            change_type = "attack" if delta > 0 else "defense"
            abs_delta = abs(delta)

            # === Update players.json ===
            legend_log = info.setdefault("legend_log", {})
            day_log = legend_log.setdefault(clash_day, {"attack": [], "defense": []})

            # Split large offense gains like +80, +120 into [40, 40]
            if change_type == "attack" and abs_delta in [80, 120, 160, 200, 240, 280, 320]:
                chunks = [40] * (abs_delta // 40)
                day_log[change_type].extend(chunks)
            else:
                day_log[change_type].append(abs_delta)

            info["legend"] = {
                "attack": sum(day_log["attack"]),
                "defense": sum(day_log["defense"])
            }

            save_players(players)

            # === Update seasonal.json ===
            seasonal_data = load_seasonal()
            seasonal_data.setdefault(tag, {})
            daily_data = seasonal_data[tag].setdefault(clash_day, {
                "offense": [],
                "defense": []
            })

            daily_data["offense"] = day_log["attack"]
            daily_data["defense"] = day_log["defense"]

            # Only set start_trophies once after 10:30 AM
            reset_time = now.replace(hour=10, minute=30, second=0, microsecond=0)
            if now > reset_time and "start_trophies" not in daily_data:
                daily_data["start_trophies"] = prev_trophies
                print(f"[{name}] ✅ start_trophies set to {prev_trophies} at {now.strftime('%H:%M')}")

            save_seasonal(seasonal_data)

            # === Update prev_trophies
            prev_data[name] = trophies
            save_prev_trophies(prev_data)

            # === Send Discord Embed
            embed = discord.Embed(
                title=f"📈 Legend Update: {name}",
                color=0x00ffcc,
                timestamp=datetime.now(timezone.utc)
            )

            if delta > 0:
                embed.add_field(name="⚔️ Offense Trophy Gain", value=f"`+{delta}`")
            else:
                embed.add_field(name="🛡️ Defense Trophy Loss", value=f"`-{abs_delta}`")

            embed.set_footer(text="Legend League Tracker")
            await channel.send(embed=embed)

    except Exception as e:
        print(f"[monitor] ❌ Error: {e}")

# === SEARCH COMMAND ===
@bot.command(name="search")
async def search_player(ctx, *, query: str = None):
    """Search for players globally using ClashKing API"""
    if not query:
        await ctx.send("⚠️ Please provide a player name or tag. Example: `-search AJAY` or `-search #9VVPVCRPR`")
        return
    
    query = query.strip()
    
    # Check if it's a tag
    if query.startswith("#"):
        tag = query[1:].upper()
        await handle_tag_search(ctx, tag)
    else:
        # Check if player exists in our database first
        local_player = None
        local_name = None
        for name, info in players.items():
            if name.lower() == query.lower():
                local_player = info
                local_name = name
                break
        
        if local_player:
            # Show stats for tracked player with option for historical data
            await show_tracked_player_stats(ctx, local_name, local_player)
        else:
            # Search globally by name
            await handle_name_search(ctx, query)

async def handle_tag_search(ctx, tag):
    """Handle direct tag search using real-time API"""
    try:
        # Use real-time API for current data
        realtime_data = await fetch_api(f"/player/to-do", {"player_tags": f"#{tag}"})
        
        if not realtime_data or not realtime_data.get("items"):
            await ctx.send("❌ No player data found for this tag.")
            return
        
        player_data = realtime_data["items"][0]  # First (and only) result
        
        # Build and send embed with real-time data
        embed = await build_realtime_search_embed(player_data)
        view = SearchView(ctx.author, tag, player_data.get("player_tag", f"#{tag}").replace("#", ""))
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        logger.error(f"Tag search error: {e}")
        await ctx.send("❌ Failed to fetch player data.")

async def handle_name_search(ctx, name):
    """Handle name search - show list of players"""
    try:
        search_data = await fetch_api(f"/player/search/{name}")
        
        if not search_data or "items" not in search_data:
            await ctx.send("❌ No players found with that name.")
            return
        
        items = search_data["items"]
        if not items:
            await ctx.send("📭 No players found with that name.")
            return
        
        if len(items) == 1:
            # Only one result, directly show stats using real-time API
            tag = items[0]["tag"].replace("#", "")
            await handle_tag_search(ctx, tag)
        else:
            # Multiple results, show selection
            embed = build_name_search_embed(items, name)
            view = NameSearchView(ctx.author, items, name)
            await ctx.send(embed=embed, view=view)
            
    except Exception as e:
        logger.error(f"Name search error: {e}")
        await ctx.send("❌ Failed to search for players.")

async def show_tracked_player_stats(ctx, name, player_info):
    """Show stats for tracked player with historical option"""
    tag = player_info["tag"]
    
    # Get data concurrently
    coc_data, realtime_data = await asyncio.gather(
        fetch_coc(tag),
        fetch_api(f"/player/to-do", {"player_tags": f"#{tag}"}),
        return_exceptions=True
    )
    
    if not coc_data or isinstance(coc_data, Exception):
        await ctx.send("❌ Player data not available.")
        return
    
    # Extract real-time data if available
    realtime_player = None
    if realtime_data and realtime_data.get("items"):
        realtime_player = realtime_data["items"][0]
    
    # Build tracked player embed
    embed = await build_tracked_player_embed(coc_data, realtime_player, tag, name)
    view = TrackedPlayerView(ctx.author, tag, name)
    
    await ctx.send(embed=embed, view=view)

async def build_realtime_search_embed(player_data):
    """Build stats embed for searched player using real-time API data"""
    player_tag = player_data.get("player_tag", "Unknown")
    name = "Unknown"
    tag = player_tag.replace("#", "") if player_tag != "Unknown" else ""
    
    # Get today's date in IST
    today_ist = datetime.now(IST)
    today_str = today_ist.date().isoformat()
    
    # Get legend data from the nested structure
    legends_data = player_data.get("legends", {})
    today_attacks = legends_data.get("attacks", [])
    today_defenses = legends_data.get("defenses", [])
    new_attacks = legends_data.get("new_attacks", [])
    new_defenses = legends_data.get("new_defenses", [])
    
    # Calculate totals
    today_offense_total = sum(today_attacks) if today_attacks else 0
    today_defense_total = sum(today_defenses) if today_defenses else 0
    today_net = today_offense_total - today_defense_total
    
    # Get current trophies from last attack or defense
    current_trophies = 0
    if new_attacks:
        current_trophies = new_attacks[-1].get("trophies", 0)
    elif new_defenses:
        current_trophies = new_defenses[-1].get("trophies", 0)
    
    # Calculate start trophies from first attack
    start_trophies = current_trophies - today_net if today_net != 0 else current_trophies
    if new_attacks:
        first_attack = new_attacks[0]
        start_trophies = first_attack.get("trophies", 0) - first_attack.get("change", 0)
    
    # Try to get player name from COC API
    try:
        coc_data = await fetch_coc(tag)
        if coc_data:
            name = coc_data.get("name", "Unknown")
            townhall = coc_data.get("townHallLevel", "?")
        else:
            townhall = "?"
    except:
        townhall = "?"

    embed = discord.Embed(
        title=f"🔍 Search Results — {name}",
        description=f"🏰 TH{townhall} | Today: {today_str}",
        color=0x00ffcc
    )
    
    # Today's performance with start trophy
    embed.add_field(name="🏁 Start Trophies", value=f"`{start_trophies:,}`", inline=True)
    embed.add_field(name="🏆 Current Trophies", value=f"`{current_trophies:,}`", inline=True)
    embed.add_field(name="📊 Net Today", value=f"`{today_net:+}`", inline=True)
    
    # Today's offense details
    if today_attacks:
        offense_str = ", ".join(f"+{v}" for v in today_attacks)
        offense_display = f"{offense_str}\n**Total**: +{today_offense_total} ({len(today_attacks)} hits)"
    else:
        offense_display = "None"
    
    embed.add_field(name="⚔️ Today's Attacks", value=offense_display, inline=False)
    
    # Today's defense details  
    if today_defenses:
        defense_str = ", ".join(f"-{v}" for v in today_defenses)
        defense_display = f"{defense_str}\n**Total**: -{today_defense_total} ({len(today_defenses)} hits)"
    else:
        defense_display = "None"
    
    embed.add_field(name="🛡️ Today's Defenses", value=defense_display, inline=False)
    
    # Hero Equipment Display
    if new_attacks:
        latest_attack = new_attacks[-1]
        hero_gear = latest_attack.get("hero_gear", [])
        
        if hero_gear:
            equipment_display = format_hero_equipment(hero_gear)
            embed.add_field(name="⚔️ Hero Equipment", value=equipment_display, inline=False)
    
    # Player link
    profile_link = f"https://link.clashofclans.com/en/?action=OpenPlayerProfile&tag=%23{tag}"
    embed.add_field(name="🔗 Player Link", value=f"[Open in Clash of Clans]({profile_link})", inline=False)
    
    embed.set_footer(text=f"Tag: #{tag}")
    embed.timestamp = datetime.now()
    
    return embed

def format_hero_equipment(hero_gear):
    """Format hero equipment display with names and hero titles"""
    if not hero_gear:
        return "No equipment data"
    
    # Group equipment by hero (assuming 2 per hero)
    heroes = ["Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince"]
    hero_equipment = {}
    
    # Assign equipment to heroes (2 per hero)
    for i in range(0, len(hero_gear), 2):
        if i // 2 < len(heroes):
            hero_name = heroes[i // 2]
            equipment_pair = hero_gear[i:i+2]
            hero_equipment[hero_name] = equipment_pair
    
    # Format display with hero names and equipment names
    display_lines = []
    for hero, equipment in hero_equipment.items():
        if equipment:
            hero_icons = {
                "Barbarian King": "👑", 
                "Archer Queen": "🏹", 
                "Grand Warden": "🧙", 
                "Royal Champion": "⚔️", 
                "Minion Prince": "👾"
            }
            hero_icon = hero_icons.get(hero, "⚔️")
            display_lines.append(f"**{hero_icon} {hero}:**")
            
            # Equipment names with levels
            equip_strs = []
            for equip in equipment:
                name = equip.get("name", "Unknown")
                level = equip.get("level", 0)
                equip_strs.append(f"• {name} (Lv.{level})")
            
            display_lines.extend(equip_strs)
            display_lines.append("")  # Empty line between heroes
    
    return "\n".join(display_lines).strip() if display_lines else "No equipment data"

async def build_tracked_player_embed(coc_data, realtime_player, tag, name):
    """Build embed for tracked player combining local and real-time data"""
    current_trophies = coc_data.get("trophies", "N/A")
    
    embed = discord.Embed(title=f"🏰 {name} (Tracked)", color=0x00ff00)
    
    # Get today's local data
    today_str = get_current_clash_day()
    legend_log = players.get(name, {}).get("legend_log", {}).get(today_str, {})
    
    attack_list = legend_log.get("attack", [])
    defense_list = legend_log.get("defense", [])
    attack_total = sum(attack_list)
    defense_total = sum(defense_list)
    trophy_net = attack_total - defense_total
    
    # Get start trophies from seasonal data
    seasonal_data = load_seasonal()
    today_data = seasonal_data.get(tag, {}).get(today_str, {})
    start_trophies = today_data.get("start_trophies", "—")
    
    embed.add_field(name="🏆 Current Trophies", value=f"`{current_trophies}`", inline=True)
    embed.add_field(name="🏁 Start Trophies", value=f"`{start_trophies}`", inline=True)
    embed.add_field(name="📊 Net Today", value=f"`{trophy_net:+}`", inline=True)
    
    # Today's performance from local data
    if attack_list:
        atk_str = ", ".join(f"+{v}" for v in attack_list)
        atk_display = f"{atk_str}\n**Total**: +{attack_total} ({len(attack_list)} hits)"
    else:
        atk_display = "None"
        
    if defense_list:
        def_str = ", ".join(f"-{v}" for v in defense_list)
        def_display = f"{def_str}\n**Total**: -{defense_total} ({len(defense_list)} hits)"
    else:
        def_display = "None"
    
    embed.add_field(name="⚔️ Today's Attacks (Local)", value=atk_display, inline=False)
    embed.add_field(name="🛡️ Today's Defenses (Local)", value=def_display, inline=False)
    
    # Real-time comparison (if available)
    if realtime_player:
        legends_data = realtime_player.get("legends", {})
        rt_attacks = legends_data.get("attacks", [])
        rt_defenses = legends_data.get("defenses", [])
        new_attacks = legends_data.get("new_attacks", [])
        
        rt_offense_total = sum(rt_attacks) if rt_attacks else 0
        rt_defense_total = sum(rt_defenses) if rt_defenses else 0
        
        if rt_offense_total > 0 or rt_defense_total > 0:
            embed.add_field(
                name="📡 Real-time Comparison",
                value=f"⚔️ `+{rt_offense_total}` ({len(rt_attacks)} hits) | 🛡️ `-{rt_defense_total}` ({len(rt_defenses)} hits)",
                inline=False
            )
        
        # Hero Equipment Display from real-time data
        if new_attacks:
            latest_attack = new_attacks[-1]
            hero_gear = latest_attack.get("hero_gear", [])
            
            if hero_gear:
                equipment_display = format_hero_equipment(hero_gear)
                embed.add_field(name="⚔️ Hero Equipment", value=equipment_display, inline=False)
    
    profile_link = f"https://link.clashofclans.com/en/?action=OpenPlayerProfile&tag=%23{tag}"
    embed.add_field(name="🔗 Player Link", value=f"[Open in Clash of Clans]({profile_link})", inline=False)
    
    embed.set_footer(text=f"Tag: #{tag}")
    embed.timestamp = datetime.now()
    
    return embed

def build_name_search_embed(items, search_name):
    """Build embed for name search results"""
    embed = discord.Embed(
        title=f"🔍 Search Results for '{search_name}'",
        description=f"Found {len(items)} players. Select one to view stats:",
        color=0x3498db
    )
    
    for i, player in enumerate(items[:15], 1):  # Limit to 15 results
        name = player.get("name", "Unknown")
        tag = player.get("tag", "")
        trophies = player.get("trophies", 0)
        th = player.get("th", "?")
        clan_name = player.get("clan_name", "No Clan")
        
        embed.add_field(
            name=f"{i}. {name}",
            value=(
                f"🏷️ `{tag}`\n"
                f"🏆 `{trophies:,}` | 🏰 TH{th}\n"
                f"🏘️ `{clan_name}`"
            ),
            inline=True
        )
    
    return embed

# === VIEW CLASSES ===
class SearchView(discord.ui.View):
    """View for search command results"""
    
    def __init__(self, author, tag, player_name):
        super().__init__(timeout=300)
        self.author = author
        self.tag = tag
        self.player_name = player_name
    
    @discord.ui.button(label="📜 Historical Data", style=discord.ButtonStyle.secondary)
    async def show_historical(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        view = HistoricalView(self.author, self.tag, self.player_name)
        embed = discord.Embed(
            title=f"📅 Historical Data — {self.player_name}",
            description="Select a month to view detailed legend statistics:",
            color=0x9B59B6
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
    
    @discord.ui.button(label="📊 Export Data", style=discord.ButtonStyle.green)
    async def export_data(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        await export_player_data(interaction, self.tag, self.player_name)

class TrackedPlayerView(discord.ui.View):
    """View for tracked player with historical option"""
    
    def __init__(self, author, tag, player_name):
        super().__init__(timeout=300)
        self.author = author
        self.tag = tag
        self.player_name = player_name
    
    @discord.ui.button(label="📜 ClashKing History", style=discord.ButtonStyle.secondary)
    async def show_historical(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        view = HistoricalView(self.author, self.tag, self.player_name)
        embed = discord.Embed(
            title=f"📅 Historical Data — {self.player_name}",
            description="Select a month to view detailed legend statistics:",
            color=0x9B59B6
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
    
    @discord.ui.button(label="📊 Export Data", style=discord.ButtonStyle.green)
    async def export_data(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        await export_player_data(interaction, self.tag, self.player_name)

class NameSearchView(discord.ui.View):
    """View for name search results selection"""
    
    def __init__(self, author, items, search_name):
        super().__init__(timeout=300)
        self.author = author
        self.items = items[:15]  # Limit to 15
        self.search_name = search_name
        self.add_selection_dropdown()
    
    def add_selection_dropdown(self):
        options = []
        for i, player in enumerate(self.items, 1):
            name = player.get("name", "Unknown")
            tag = player.get("tag", "")
            trophies = player.get("trophies", 0)
            
            options.append(discord.SelectOption(
                label=f"{i}. {name}",
                description=f"{tag} | {trophies:,} trophies",
                value=str(i-1)
            ))
        
        select = PlayerSelect(options, self.author, self.items)
        self.add_item(select)

class PlayerSelect(discord.ui.Select):
    """Dropdown for player selection"""
    
    def __init__(self, options, author, items):
        super().__init__(placeholder="Choose a player...", options=options)
        self.author = author
        self.items = items
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        selected_index = int(self.values[0])
        selected_player = self.items[selected_index]
        tag = selected_player["tag"].replace("#", "")
        
        await interaction.response.defer()
        
        # Use real-time API for selected player
        realtime_data = await fetch_api(f"/player/to-do", {"player_tags": f"#{tag}"})
        
        if not realtime_data or not realtime_data.get("items"):
            await interaction.followup.send("❌ No real-time data found for this player.")
            return
        
        player_data = realtime_data["items"][0]
        
        # Build and send embed
        embed = await build_realtime_search_embed(player_data)
        view = SearchView(self.author, tag, player_data.get("player_tag", f"#{tag}").replace("#", ""))
        
        await interaction.followup.send(embed=embed, view=view)

class HistoricalView(discord.ui.View):
    """View for historical month selection with unique custom_ids"""
    
    def __init__(self, author, tag, player_name):
        super().__init__(timeout=300)
        self.author = author
        self.tag = tag
        self.player_name = player_name
        self.current_month = datetime.now(IST)
        self.interaction_count = 0
        self.add_month_buttons()
    
    def add_month_buttons(self):
        # Add month navigation buttons with UNIQUE custom_ids
        months = []
        for i in range(6):  # Last 6 months
            month_date = self.current_month - timedelta(days=30*i)
            months.append(month_date)
        
        # Store months for callback reference
        self.months_data = {}
        
        for i, month_date in enumerate(months):
            month_str = month_date.strftime("%Y-%m")  # This gives "2025-07", "2025-06", etc.
            month_name_str = month_date.strftime("%B %Y")
            
            # Create unique custom_id using index
            unique_id = f"month_btn_{i}_{int(datetime.now().timestamp())}_{self.interaction_count}"
            
            # Store the month string for this button
            self.months_data[unique_id] = month_str
            
            button = discord.ui.Button(
                label=month_name_str,
                style=discord.ButtonStyle.primary if i == 0 else discord.ButtonStyle.secondary,
                custom_id=unique_id
            )
            button.callback = self.month_callback
            self.add_item(button)
    
    async def month_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        self.interaction_count += 1
        
        # Get the month string from stored data
        custom_id = interaction.data["custom_id"]
        month_str = self.months_data.get(custom_id)
        
        if not month_str:
            await interaction.response.send_message("❌ Invalid button data.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Fetch historical data using YYYY-MM format
        legend_data = await fetch_api(f"/player/%23{self.tag}/legends", {"season": month_str})
        
        if not legend_data:
            await interaction.followup.send(f"❌ No data found for {month_str}.")
            return
        
        # Build historical embed
        embed = await build_historical_embed(legend_data, month_str)
        view = DailyView(self.author, self.tag, self.player_name, month_str, legend_data)
        
        await interaction.followup.send(embed=embed, view=view)

class DailyView(discord.ui.View):
    """Updated view for daily navigation within a month with unique button IDs"""
    
    def __init__(self, author, tag, player_name, month_str, legend_data):
        super().__init__(timeout=300)
        self.author = author
        self.tag = tag
        self.player_name = player_name
        self.month_str = month_str
        self.legend_data = legend_data
        self.dates = sorted(legend_data.get("legends", {}).keys())
        self.current_index = 0
        self.interaction_count = 0
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        
        # Create unique timestamps for each button
        timestamp = int(datetime.now().timestamp())
        
        # Previous day button with unique custom_id
        prev_btn = discord.ui.Button(
            label="◀️ Previous", 
            style=discord.ButtonStyle.secondary,
            custom_id=f"prev_day_{self.tag}_{timestamp}_{self.interaction_count}"
        )
        prev_btn.disabled = self.current_index == 0
        prev_btn.callback = self.previous_day
        self.add_item(prev_btn)
        
        # Next day button with unique custom_id
        next_btn = discord.ui.Button(
            label="Next ▶️", 
            style=discord.ButtonStyle.secondary,
            custom_id=f"next_day_{self.tag}_{timestamp}_{self.interaction_count + 1}"
        )
        next_btn.disabled = self.current_index >= len(self.dates) - 1
        next_btn.callback = self.next_day
        self.add_item(next_btn)
        
        # Back to month view with unique custom_id
        back_btn = discord.ui.Button(
            label="📅 Month View", 
            style=discord.ButtonStyle.primary,
            custom_id=f"back_month_{self.tag}_{timestamp}_{self.interaction_count + 2}"
        )
        back_btn.callback = self.back_to_month
        self.add_item(back_btn)
    
    async def previous_day(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        try:
            self.current_index = max(0, self.current_index - 1)
            self.interaction_count += 1
            self.update_buttons()
            
            embed = self.build_daily_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error(f"Previous day error: {e}")
            await interaction.response.send_message("❌ Error loading previous day.", ephemeral=True)
    
    async def next_day(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        try:
            self.current_index = min(len(self.dates) - 1, self.current_index + 1)
            self.interaction_count += 1
            self.update_buttons()
            
            embed = self.build_daily_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error(f"Next day error: {e}")
            await interaction.response.send_message("❌ Error loading next day.", ephemeral=True)
    
    async def back_to_month(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return
        
        try:
            embed = await build_historical_embed(self.legend_data, self.month_str)
            # Create new DailyView to reset button states
            view = DailyView(self.author, self.tag, self.player_name, self.month_str, self.legend_data)
            
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Back to month error: {e}")
            await interaction.response.send_message("❌ Error loading month view.", ephemeral=True)
    
    def build_daily_embed(self):
        """Build embed for specific day - show complete attack/defense lists"""
        if not self.dates:
            return discord.Embed(title="No Data", description="No daily data available", color=0xff0000)
        
        current_date = self.dates[self.current_index]
        day_data = self.legend_data["legends"][current_date]
        
        attacks = day_data.get("attacks", [])
        defenses = day_data.get("defenses", [])
        new_attacks = day_data.get("new_attacks", [])
        new_defenses = day_data.get("new_defenses", [])
        
        total_offense = sum(attacks)
        total_defense = sum(defenses)
        net_gain = total_offense - total_defense
        
        embed = discord.Embed(
            title=f"📅 Daily Stats — {self.player_name}",
            description=f"Date: {current_date} ({self.current_index + 1}/{len(self.dates)})",
            color=0x00ffcc
        )
        
        # Get initial trophy (lowest trophy from attacks)
        initial_trophy = None
        if new_attacks:
            trophy_values = []
            for attack in new_attacks:
                current_trophy = attack.get("trophies", 0)
                change = attack.get("change", 0)
                initial = current_trophy - change
                trophy_values.append(initial)
            if trophy_values:
                initial_trophy = min(trophy_values)
        
        if initial_trophy:
            embed.add_field(name="🏁 Initial Trophies", value=f"`{initial_trophy:,}`", inline=True)
        
        embed.add_field(name="⚔️ Total Offense", value=f"`+{total_offense}`", inline=True)
        embed.add_field(name="🛡️ Total Defense", value=f"`-{total_defense}`", inline=True)
        embed.add_field(name="📊 Net Gain", value=f"`{net_gain:+}`", inline=True)
        embed.add_field(name="🎯 Attacks Made", value=f"`{len(attacks)}`", inline=True)
        embed.add_field(name="🛡️ Defenses Hit", value=f"`{len(defenses)}`", inline=True)
        
        # Attack details with timing - SHOW ALL ATTACKS
        if new_attacks:
            attack_details = []
            for attack in new_attacks:
                timestamp = attack.get("time", 0)
                change = attack.get("change", 0)
                trophies = attack.get("trophies", 0)
                time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M")
                attack_details.append(f"`{time_str}` +{change} → {trophies:,}")
            
            # Split into multiple fields if too long
            if len(attack_details) > 10:
                embed.add_field(
                    name="⚔️ Attack Timeline (1-10)",
                    value="\n".join(attack_details[:10]),
                    inline=False
                )
                if len(attack_details) > 10:
                    embed.add_field(
                        name="⚔️ Attack Timeline (11+)",
                        value="\n".join(attack_details[10:]),
                        inline=False
                    )
            else:
                embed.add_field(
                    name="⚔️ Attack Timeline",
                    value="\n".join(attack_details),
                    inline=False
                )
        
        # Defense details with timing - SHOW ALL DEFENSES
        if new_defenses:
            defense_details = []
            for defense in new_defenses:
                timestamp = defense.get("time", 0)
                change = defense.get("change", 0)
                trophies = defense.get("trophies", 0)
                time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M")
                defense_details.append(f"`{time_str}` -{change} → {trophies:,}")
            
            # Split into multiple fields if too long
            if len(defense_details) > 10:
                embed.add_field(
                    name="🛡️ Defense Timeline (1-10)",
                    value="\n".join(defense_details[:10]),
                    inline=False
                )
                if len(defense_details) > 10:
                    embed.add_field(
                        name="🛡️ Defense Timeline (11+)",
                        value="\n".join(defense_details[10:]),
                        inline=False
                    )
            else:
                embed.add_field(
                    name="🛡️ Defense Timeline",
                    value="\n".join(defense_details),
                    inline=False
                )
        
        embed.set_footer(text=f"Tag: #{self.tag}")
        embed.timestamp = datetime.now()
        
        return embed

async def build_historical_embed(legend_data, month_str):
    """Build embed for historical month view"""
    name = legend_data.get("name", "Unknown")
    tag = legend_data.get("tag", "").replace("#", "")
    
    # Parse month name
    try:
        month_date = datetime.strptime(month_str, "%Y-%m")
        month_display = month_date.strftime("%B %Y")
    except:
        month_display = month_str
    
    legends = legend_data.get("legends", {})
    
    embed = discord.Embed(
        title=f"📅 {month_display} — {name}",
        description=f"Monthly legend league performance",
        color=0x9B59B6
    )
    
    total_offense = total_defense = total_days = 0
    daily_summaries = []
    
    for date in sorted(legends.keys()):
        day_data = legends[date]
        attacks = day_data.get("attacks", [])
        defenses = day_data.get("defenses", [])
        
        day_offense = sum(attacks)
        day_defense = sum(defenses)
        day_net = day_offense - day_defense
        
        total_offense += day_offense
        total_defense += day_defense
        total_days += 1
        
        # Get initial trophy
        initial_trophy = "—"
        new_attacks = day_data.get("new_attacks", [])
        if new_attacks:
            trophy_values = []
            for attack in new_attacks:
                current_trophy = attack.get("trophies", 0)
                change = attack.get("change", 0)
                initial = current_trophy - change
                trophy_values.append(initial)
            if trophy_values:
                initial_trophy = f"{min(trophy_values):,}"
        
        daily_summaries.append({
            "date": date,
            "initial": initial_trophy,
            "offense": day_offense,
            "defense": day_defense,
            "net": day_net,
            "attacks": len(attacks),
            "defenses": len(defenses)
        })
    
    # Show summary
    net_total = total_offense - total_defense
    avg_offense = total_offense / max(total_days, 1)
    avg_defense = total_defense / max(total_days, 1)
    
    embed.add_field(
        name="📊 Monthly Summary",
        value=(
            f"📅 **Active Days**: `{total_days}`\n"
            f"⚔️ **Total Offense**: `+{total_offense}`\n"
            f"🛡️ **Total Defense**: `-{total_defense}`\n"
            f"📈 **Net Gain**: `{net_total:+}`\n"
            f"📊 **Daily Avg**: `+{avg_offense:.1f}` / `-{avg_defense:.1f}`"
        ),
        inline=False
    )
    
    # Show recent days (last 10)
    recent_days = daily_summaries[-10:]
    if recent_days:
        day_lines = []
        for day in recent_days:
            day_lines.append(
                f"**{day['date']}**: 🏁`{day['initial']}` ⚔️`+{day['offense']}({day['attacks']})` "
                f"🛡️`-{day['defense']}({day['defenses']})` 📊`{day['net']:+}`"
            )
        
        embed.add_field(
            name="📋 Recent Days",
            value="\n".join(day_lines),
            inline=False
        )
    
    embed.set_footer(text=f"Tag: #{tag} | Use buttons to navigate daily details")
    embed.timestamp = datetime.now()
    
    return embed

async def export_player_data(interaction, tag, player_name):
    """Export player data to CSV"""
    try:
        await interaction.response.defer()
        
        # Get last 3 months of data
        months_data = []
        current_date = datetime.now(IST)
        
        for i in range(3):
            month_date = current_date - timedelta(days=30*i)
            month_str = month_date.strftime("%Y-%m")
            
            legend_data = await fetch_api(f"/player/%23{tag}/legends", {"season": month_str})
            if legend_data and "legends" in legend_data:
                months_data.append((month_str, legend_data["legends"]))
        
        if not months_data:
            await interaction.followup.send("❌ No data available for export.")
            return
        
        # Create CSV data
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        
        # Write header
        writer.writerow([
            "Date", "Month", "Initial_Trophies", "Attacks_Made", "Total_Offense", 
            "Defenses_Hit", "Total_Defense", "Net_Gain", "Attack_Details", "Defense_Details"
        ])
        
        # Write data
        for month_str, legends in months_data:
            for date, day_data in sorted(legends.items()):
                attacks = day_data.get("attacks", [])
                defenses = day_data.get("defenses", [])
                new_attacks = day_data.get("new_attacks", [])
                
                # Calculate initial trophy
                initial_trophy = ""
                if new_attacks:
                    trophy_values = []
                    for attack in new_attacks:
                        current_trophy = attack.get("trophies", 0)
                        change = attack.get("change", 0)
                        initial = current_trophy - change
                        trophy_values.append(initial)
                    if trophy_values:
                        initial_trophy = min(trophy_values)
                
                attack_details = ", ".join(map(str, attacks))
                defense_details = ", ".join(map(str, defenses))
                
                writer.writerow([
                    date, month_str, initial_trophy, len(attacks), sum(attacks),
                    len(defenses), sum(defenses), sum(attacks) - sum(defenses),
                    attack_details, defense_details
                ])
        
        # Create file
        csv_buffer.seek(0)
        file_content = csv_buffer.getvalue().encode('utf-8')
        
        file = discord.File(
            io.BytesIO(file_content),
            filename=f"{player_name}_legend_data.csv"
        )
        
        await interaction.followup.send(
            f"📊 **Export Complete!**\nLegend data for **{player_name}** (Last 3 months)",
            file=file
        )
        
    except Exception as e:
        logger.error(f"Export error: {e}")
        await interaction.followup.send("❌ Failed to export data.")

# === OTHER COMMANDS ===
@bot.command(name="stats")
async def stats(ctx, identifier: str = None):
    if not identifier:
        await ctx.send("⚠️ Please provide a player name or tag. Example: `-stats Ajay` or `-stats #TAG`")
        return

    identifier = identifier.strip()
    tag = None
    player_key = None

    for name, info in players.items():
        if name.lower() == identifier.lower():
            tag = info["tag"]
            player_key = name
            break

    if not tag:
        if identifier.startswith("#"):
            tag = identifier[1:]
        else:
            await ctx.send("⚠️ Player name not found in tracked list. Use `-list` to see names.")
            return

    coc_data = await fetch_coc(tag)
    if not coc_data:
        await ctx.send("❌ Player not found or no data available.")
        return

    name = coc_data.get("name", tag)
    current_trophies = coc_data.get("trophies", "N/A")
    clan = coc_data.get("clan", {})
    clan_name = clan.get("name")
    clan_tag = clan.get("tag")

    today_str = get_current_clash_day()
    legend_log = players.get(player_key, {}).get("legend_log", {}).get(today_str, {})
    attack_list = legend_log.get("attack", [])
    defense_list = legend_log.get("defense", [])

    attack_total = sum(attack_list)
    defense_total = sum(defense_list)
    trophy_net = attack_total - defense_total

    # Fetch Initial Trophies
    seasonal_data = load_seasonal()
    start_trophies = "—"
    player_seasonal = seasonal_data.get(tag, {})
    today_data = player_seasonal.get(today_str, {})
    start_trophies = today_data.get("start_trophies", "—")

    # Hero gear fetch
    hero_gear_raw = []
    try:
        gear_data = await fetch_api(f"/player/to-do", {"player_tags": f"%23{tag}"})
        if gear_data and gear_data.get("items"):
            legends_data = gear_data["items"][0].get("legends", {})
            new_attacks = legends_data.get("new_attacks", [])
            if new_attacks:
                hero_gear_raw = new_attacks[-1].get("hero_gear", [])
    except:
        pass

    # Hero levels from coc_data
    hero_levels = {h['name']: h['level'] for h in coc_data.get("heroes", [])}

    heroes = {
        "👑 Barbarian King": [],
        "👸 Archer Queen": [],
        "🧚 Grand Warden": [],
        "🎯 Royal Champion": [],
        "👹 Minion Prince": []
    }
    hero_order = list(heroes.keys())
    hero_names = ["Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince"]

    for i in range(0, len(hero_gear_raw), 2):
        hero_icon = hero_order[i // 2] if i // 2 < len(hero_order) else None
        hero_name = hero_names[i // 2] if i // 2 < len(hero_names) else None
        if hero_icon and hero_name:
            level = hero_levels.get(hero_name)
            hero_title = f"{hero_icon} (Lv. {level})" if level else hero_icon
            gears = []
            for gear in hero_gear_raw[i:i+2]:
                gname = gear["name"]
                glevel = gear["level"]
                gears.append(f"{gname} (Lv. {glevel})")
            heroes[hero_title] = gears

    atk_hit_str = " ".join(f"+{v}" for v in attack_list) if attack_list else "None"
    def_hit_str = " ".join(f"-{v}" for v in defense_list) if defense_list else "None"

    # Embed
    embed = discord.Embed(title=f"🏰 {name}", color=0x00ffcc)
    embed.add_field(name="🏆 Current Trophies", value=f"`{current_trophies}`", inline=True)
    embed.add_field(name="🟢 Initial Trophies", value=f"`{start_trophies}`", inline=True)
    embed.add_field(name="📊 Net Today", value=f"`{trophy_net}`", inline=True)

    embed.add_field(name="⚔️ Attacks", value=f"{atk_hit_str} ({len(attack_list)} hits)\n**Total**: +{attack_total}", inline=False)
    embed.add_field(name="🛡️ Defenses", value=f"{def_hit_str} ({len(defense_list)} hits)\n**Total**: -{defense_total}", inline=False)

    for hero_title, gear_list in heroes.items():
        if gear_list:
            embed.add_field(name=hero_title, value="\n".join(gear_list), inline=False)

    if not any(heroes.values()):
        embed.add_field(name="🧰 Hero Gear", value="⚠️ No gear data found.", inline=False)

    if clan_name and clan_tag:
        full_clan_tag = clan_tag if clan_tag.startswith("#") else f"#{clan_tag}"
        clan_url = f"https://link.clashofclans.com/en/?action=OpenClanProfile&tag={quote(full_clan_tag)}"
        embed.add_field(name="🏅 Clan", value=f"[{clan_name}]({clan_url})", inline=True)

    # 🔗 Player Link field instead of in title
    profile_link = f"https://link.clashofclans.com/en/?action=OpenPlayerProfile&tag=%23{tag}"
    embed.add_field(name="🔗 Player Link", value=f"[Open in Clash of Clans]({profile_link})", inline=True)

    # 🌍 Global Rank (via ClashKing API)
    try:
        encoded_tag = quote(f"#{tag}")
        global_rank_data = await fetch_api(f"/ranking/legends/{encoded_tag}")
        if global_rank_data and "rank" in global_rank_data:
            rank = global_rank_data["rank"]
            embed.add_field(name="🌍 Global Ranking", value=f"`#{rank:,}`", inline=True)
        else:
            embed.add_field(name="🌍 Global Ranking", value="`#NA`", inline=True)
    except:
        embed.add_field(name="🌍 Global Ranking", value="`#NA`", inline=True)

    embed.set_footer(text=f"Tag: #{tag}")
    embed.timestamp = datetime.now()

    # === Button for Logs ===
    view = discord.ui.View()

    async def show_logs_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("⚠️ Only the command user can use this button.", ephemeral=True)
            return

        seasonal_data = load_seasonal()
        player_logs = seasonal_data.get(tag, {})
        if not player_logs:
            await interaction.response.send_message("📦 No seasonal log available for this player.", ephemeral=True)
            return

        embed_logs = discord.Embed(title=f"📜 Daily Logs — {name}", color=0x00ffcc)
        atk_total_all = def_total_all = days = 0

        for date in sorted(player_logs.keys()):
            log = player_logs[date]
            offense = log.get("offense", [])
            defense = log.get("defense", [])
            start_trophies = log.get("start_trophies", None)

            atk_total = sum(offense)
            def_total = sum(defense)
            net = atk_total - def_total
            atk_hits = len(offense)
            def_hits = len(defense)

            log_line = (
                f"🏁 `{start_trophies or '—'}` | "
                f"⚔️ `+{atk_total}` ({atk_hits}) | "
                f"🛡️ `-{def_total}` ({def_hits}) | "
                f"📊 `Net: {net:+}`"
            )

            embed_logs.add_field(name=f"🗓️ {date}", value=log_line, inline=False)
            atk_total_all += atk_total
            def_total_all += def_total
            days += 1

        avg_atk = round(atk_total_all / days, 1) if days else 0
        avg_def = round(def_total_all / days, 1) if days else 0
        embed_logs.set_footer(text=f"📆 Total Days: {days} | Avg Offense: +{avg_atk} | Avg Defense: -{avg_def}")

        await interaction.response.send_message(embed=embed_logs, ephemeral=False)

    button = discord.ui.Button(label="📜 Previous Logs", style=discord.ButtonStyle.secondary)
    button.callback = show_logs_callback
    view.add_item(button)

    await ctx.send(embed=embed, view=view)

@bot.command(name="localrank")
async def localrank(ctx, country: str = None, limit: int = 10):
    if not country:
        return await ctx.send("⚠️ Please provide a country name. Example: `-localrank India 10`")
    if limit > 200:
        return await ctx.send("⚠️ Max limit is 200.")

    headers = {
        "Authorization": f"Bearer {COC_BEARER}",
        "Accept": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        # Fetch all locations
        async with session.get("https://api.clashofclans.com/v1/locations", headers=headers) as loc_res:
            if loc_res.status != 200:
                return await ctx.send("❌ Failed to fetch location list.")
            data = await loc_res.json()
            locations = data.get("items", [])

        location_id = None
        for loc in locations:
            if loc["name"].lower() == country.lower() and loc.get("isCountry", False):
                location_id = loc["id"]
                break

        if not location_id:
            return await ctx.send("❌ Country not found. Please check the spelling.")

        # Fetch local rankings
        async with session.get(
            f"https://api.clashofclans.com/v1/locations/{location_id}/rankings/players?limit={limit}",
            headers=headers
        ) as rank_res:
            if rank_res.status != 200:
                return await ctx.send("❌ Failed to fetch local ranking.")
            rank_data = await rank_res.json()
            rankings = rank_data.get("items", [])

    if not rankings:
        return await ctx.send("⚠️ No players found.")

    embed = discord.Embed(title=f"🏅 Local Rankings — {country.title()}", description=f"Top {limit} players", color=0x00BFFF)
    for player in rankings:
        embed.add_field(
            name=f"{player.get('rank', '?')}. {player.get('name', 'Unknown')} [{player.get('tag', '')}]",
            value=f"🏆 `{player.get('trophies', '?')}` | 🎖️ Exp: `{player.get('expLevel', '?')}`\n🏰 Clan: `{player.get('clan', {}).get('name','No Clan')}`",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name="eos")
async def eos(ctx, player_name: str = None, count: int = 5):
    if not player_name:
        await ctx.send("⚠️ Please provide a player name. Example: `-eos Ajay 5`")
        return

    # Case-insensitive player match
    player = next((info for name, info in players.items() if name.lower() == player_name.lower()), None)

    if not player:
        await ctx.send("⚠️ Player not found. Use -list to see all tracked players.")
        return

    tag = player["tag"].replace("#", "").upper()
    data = await fetch_api(f"/player/{tag}/legend_rankings", {"limit": count})

    if not data:
        await ctx.send("❌ Failed to fetch end-of-season data.")
        return

    embed = discord.Embed(
        title=f"📅 End of Season Stats — {player_name.title()}",
        description=f"Showing last `{count}` seasons",
        color=0x1E90FF
    )

    for season in data[:count]:
        season_name = season.get("season", "Unknown")
        trophies = season.get("trophies", 0)
        rank = season.get("rank", "N/A")
        attack_wins = season.get("attackWins", 0)
        defense_wins = season.get("defenseWins", 0)
        clan = season.get("clan", {}).get("name", "No Clan")

        value = (
            f"🏆 **Trophies**: `{trophies}`\n"
            f"🎖️ **Rank**: `{rank}`\n"
            f"⚔️ **Attacks**: `{attack_wins}` | 🛡️ **Defenses**: `{defense_wins}`\n"
            f"🏰 **Clan**: `{clan}`"
        )

        embed.add_field(name=f"📆 {season_name}", value=value, inline=False)

    embed.set_footer(text=f"Tag: #{tag}")

    await ctx.send(embed=embed)

@bot.command(name="cutoff")
async def cutoff(ctx):
    try:
        data = await fetch_api("/legends/trophy-buckets")
        if not data:
            await ctx.send("⚠️ Failed to fetch trophy cutoff data.")
            return
        
        data = data.get("items", [])
    except Exception:
        await ctx.send("⚠️ Failed to fetch trophy cutoff data.")
        return

    if not data:
        await ctx.send("⚠️ No cutoff data available.")
        return

    embed = discord.Embed(
        title="📉 Legend League Trophy Cutoffs",
        description="Number of players in each trophy bucket.",
        color=discord.Color.purple()
    )

    emoji_scale = [
        "🥇", "🥈", "🥉", "🏅", "🎖️", "🔰", "💠", "⭐", "🌟", "🔥", "⚡", "💎", "🚀"
    ]

    for i, entry in enumerate(sorted(data, key=lambda x: x["_id"])):
        trophy = entry["_id"]
        count = entry["count"]
        emoji = emoji_scale[i] if i < len(emoji_scale) else "🏷️"
        embed.add_field(
            name=f"{emoji} {trophy}+ Trophies",
            value=f"👥 **{count:,}** players",
            inline=False
        )

    embed.set_footer(text="📊 Source: ClashKing — Trophy Distribution")
    await ctx.send(embed=embed)

@bot.command(name="addplayer")
async def add_player(ctx, name: str, tag: str):
    tag = tag.strip("#").upper()
    players[name] = {
        "tag": tag,
        "legend": {"attack": 0, "defense": 0},
        "last_reset_date": ""
    }
    save_players(players)
    await ctx.send(f"✅ Added **{name}** with tag `#{tag}`")

@bot.command(name="removeplayer")
async def remove_player(ctx, name: str):
    if name in players:
        del players[name]
        save_players(players)
        await ctx.send(f"🗑️ Removed player **{name}**")
    else:
        await ctx.send(f"⚠️ Player **{name}** not found.")

@bot.command(name="list")
async def list_players(ctx):
    if not players:
        await ctx.send("📭 No players are currently being tracked.")
        return
    embed = discord.Embed(title="📋 Tracked Players", color=0x3498db)
    for name, info in players.items():
        embed.add_field(name=name, value=f"`#{info['tag']}`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="leaderboard")
async def leaderboard(ctx):
    scores = []
    skipped = []

    clash_day = get_current_clash_day()

    for name, info in players.items():
        tag = info.get("tag")
        profile = await fetch_coc(tag)

        if not tag or not profile:
            skipped.append(name)
            continue

        legend_log = info.get("legend_log", {}).get(clash_day, {"attack": [], "defense": []})

        attack_list = legend_log.get("attack", [])
        defense_list = legend_log.get("defense", [])

        attack_total = sum(attack_list)
        defense_total = sum(defense_list)
        attack_hits = len(attack_list)
        defense_hits = len(defense_list)

        net = attack_total - defense_total

        scores.append({
            "name": name,
            "trophies": profile.get("trophies", 0),
            "net": net,
            "attacks": attack_total,
            "defenses": defense_total,
            "atk_hits": attack_hits,
            "def_hits": defense_hits
        })

    if not scores:
        await ctx.send("⚠️ No leaderboard data available.")
        return

    scores.sort(key=lambda x: x["trophies"], reverse=True)

    leaderboard_embed = discord.Embed(title="🏆 Legend Leaderboard (Today)", color=0xFFD700)

    for i, entry in enumerate(scores, 1):
        leaderboard_embed.add_field(
            name=f"{i}. {entry['name']} — {entry['trophies']} 🏆",
            value=(
                f"⚔️ {entry['attacks']} (+{entry['atk_hits']} hits)\n"
                f"🛡️ {entry['defenses']} (-{entry['def_hits']} hits)\n"
                f"📊 Net: `{entry['net']:+}`"
            ),
            inline=False
        )

    await ctx.send(embed=leaderboard_embed)

    # === GLOBAL STATS ===
    global_data = await fetch_api("/global/counts")

    def fmt(val):
        try:
            return f"`{int(val):,}`"
        except:
            return "`N/A`"

    if global_data:
        global_embed = discord.Embed(title="🌍 Global Clash Stats", color=0x1ABC9C)
        global_embed.add_field(name="👥 Players", value=fmt(global_data.get("player_count")), inline=True)
        global_embed.add_field(name="🏰 Clans", value=fmt(global_data.get("clan_count")), inline=True)
        global_embed.add_field(name="🏆 Legend Players", value=fmt(global_data.get("players_in_legends")), inline=True)
        global_embed.add_field(name="⚔️ Players in War", value=fmt(global_data.get("players_in_war")), inline=True)
        global_embed.add_field(name="🎯 Clans in War", value=fmt(global_data.get("clans_in_war")), inline=True)
        global_embed.add_field(name="📦 Wars Stored", value=fmt(global_data.get("wars_stored")), inline=True)
        global_embed.add_field(name="🔁 Join/Leaves", value=fmt(global_data.get("total_join_leaves")), inline=False)
        await ctx.send(embed=global_embed)
    else:
        await ctx.send("⚠️ Failed to fetch global stats.")

@bot.command(name="patterns")
async def attack_patterns(ctx, player_name: str = None):
    if not player_name:
        await ctx.send("⚠️ Please provide a player name. Example: `-patterns ajay`")
        return

    # Find player in tracked list (case insensitive)
    player_data = None
    actual_name = None
    for name, info in players.items():
        if name.lower() == player_name.lower():
            player_data = info
            actual_name = name
            break

    if not player_data:
        await ctx.send("⚠️ Player not found in tracked list. Use `-list` to see all tracked players.")
        return

    tag = player_data["tag"]
    
    # Load seasonal data for pattern analysis
    seasonal_data = load_seasonal()
    player_seasonal = seasonal_data.get(tag, {})
    
    if not player_seasonal:
        await ctx.send("📭 No seasonal data found for this player.")
        return

    # Get all available days and sort them
    all_days = sorted(player_seasonal.keys())
    
    if not all_days:
        await ctx.send("📭 Insufficient data for pattern analysis.")
        return

    # Initialize pattern tracking variables
    daily_activity = {"Monday": 0, "Tuesday": 0, "Wednesday": 0, "Thursday": 0, "Friday": 0, "Saturday": 0, "Sunday": 0}
    total_attacks = 0
    total_defenses = 0
    total_offense = 0
    total_defense_loss = 0
    best_day_performance = {"day": "", "net": -999, "offense": 0, "defense": 0}
    worst_day_performance = {"day": "", "net": 999, "offense": 0, "defense": 0}
    
    # Analyze each day's data
    daily_stats = []
    active_days = 0
    
    for day in all_days:
        day_data = player_seasonal.get(day, {})
        offense = day_data.get("offense", [])
        defense = day_data.get("defense", [])
        start_trophies = day_data.get("start_trophies", 0)
        
        day_attacks = len(offense)
        day_defenses = len(defense)
        day_offense_total = sum(offense)
        day_defense_total = sum(defense)
        day_net = day_offense_total - day_defense_total
        
        # Only count days with activity
        if day_attacks > 0 or day_defenses > 0:
            active_days += 1
            
        total_attacks += day_attacks
        total_defenses += day_defenses
        total_offense += day_offense_total
        total_defense_loss += day_defense_total
        
        # Track best/worst days
        if day_net > best_day_performance["net"]:
            best_day_performance = {
                "day": day, 
                "net": day_net, 
                "offense": day_offense_total, 
                "defense": day_defense_total
            }
        if day_net < worst_day_performance["net"]:
            worst_day_performance = {
                "day": day, 
                "net": day_net, 
                "offense": day_offense_total, 
                "defense": day_defense_total
            }
        
        # Get day of week
        try:
            date_obj = datetime.strptime(day, "%Y-%m-%d")
            day_name = date_obj.strftime("%A")
            daily_activity[day_name] += day_attacks
        except:
            pass
        
        daily_stats.append({
            "day": day,
            "attacks": day_attacks,
            "defenses": day_defenses,
            "offense": day_offense_total,
            "defense": day_defense_total,
            "net": day_net,
            "start_trophies": start_trophies
        })

    if total_attacks == 0 and total_defenses == 0:
        await ctx.send("📭 No activity data found for pattern analysis.")
        return

    # Calculate statistics
    avg_attacks_per_day = round(total_attacks / max(active_days, 1), 1)
    avg_defenses_per_day = round(total_defenses / max(active_days, 1), 1)
    avg_offense_per_day = round(total_offense / max(active_days, 1), 1)
    avg_defense_per_day = round(total_defense_loss / max(active_days, 1), 1)
    
    # Find most active day of week
    most_active_day = max(daily_activity.items(), key=lambda x: x[1])
    least_active_day = min(daily_activity.items(), key=lambda x: x[1])
    
    # Calculate attack efficiency (average trophies per attack)
    attack_efficiency = round(total_offense / max(total_attacks, 1), 1)
    defense_efficiency = round(total_defense_loss / max(total_defenses, 1), 1)
    
    # Find streaks and patterns
    attack_days = sum(1 for stat in daily_stats if stat["attacks"] > 0)
    defense_days = sum(1 for stat in daily_stats if stat["defenses"] > 0)
    inactive_days = sum(1 for stat in daily_stats if stat["attacks"] == 0 and stat["defenses"] == 0)
    
    # Create comprehensive embed
    embed = discord.Embed(
        title=f"📊 Attack Patterns Analysis — {actual_name.title()}",
        description=f"Analysis based on {len(all_days)} days of data ({active_days} active days)",
        color=0x9B59B6
    )

    # Basic activity stats
    embed.add_field(
        name="📈 Activity Overview",
        value=(
            f"⚔️ **Avg Attacks/Day**: `{avg_attacks_per_day}`\n"
            f"🛡️ **Avg Defenses/Day**: `{avg_defenses_per_day}`\n"
            f"📊 **Total Sessions**: `{total_attacks + total_defenses}`\n"
            f"💤 **Inactive Days**: `{inactive_days}`"
        ),
        inline=False
    )

    # Performance metrics
    embed.add_field(
        name="🎯 Performance Metrics",
        value=(
            f"⚔️ **Attack Efficiency**: `{attack_efficiency} per hit`\n"
            f"🛡️ **Avg Defense Loss**: `{defense_efficiency} per hit`\n"
            f"📈 **Total Offense**: `+{total_offense}`\n"
            f"📉 **Total Defense**: `-{total_defense_loss}`"
        ),
        inline=False
    )

    # Day of week patterns
    embed.add_field(
        name="📅 Weekly Attack Pattern",
        value=(
            f"🔥 **Most Active**: `{most_active_day[0]}` ({most_active_day[1]} attacks)\n"
            f"😴 **Least Active**: `{least_active_day[0]}` ({least_active_day[1]} attacks)"
        ),
        inline=False
    )

    # Best and worst days
    embed.add_field(
        name="🏆 Best Day Performance",
        value=(
            f"📅 **Date**: `{best_day_performance['day']}`\n"
            f"📊 **Net**: `{best_day_performance['net']:+}`\n"
            f"⚔️ **Offense**: `+{best_day_performance['offense']}`\n"
            f"🛡️ **Defense**: `-{best_day_performance['defense']}`"
        ),
        inline=True
    )

    embed.add_field(
        name="📉 Worst Day Performance", 
        value=(
            f"📅 **Date**: `{worst_day_performance['day']}`\n"
            f"📊 **Net**: `{worst_day_performance['net']:+}`\n"
            f"⚔️ **Offense**: `+{worst_day_performance['offense']}`\n"
            f"🛡️ **Defense**: `-{worst_day_performance['defense']}`"
        ),
        inline=True
    )

    embed.set_footer(text=f"Tag: #{tag} | {len(all_days)} days analyzed")
    embed.timestamp = datetime.now()

    await ctx.send(embed=embed)

@bot.command(name="helpme", aliases=["commands", "cmds"])
async def custom_help(ctx):
    embed = discord.Embed(
        title="📖 Help Menu",
        description="Here are all the commands you can use:",
        color=0x00BFFF
    )

    # === Player Commands ===
    embed.add_field(
        name="➕ `-addplayer <name> <tag>`",
        value="Add a new player to tracking.\n**Example**: `-addplayer Ajay #P8V8YRG99`",
        inline=False
    )

    embed.add_field(
        name="➖ `-removeplayer <name>`",
        value="Remove a tracked player by name.\n**Example**: `-removeplayer Ajay`",
        inline=False
    )

    embed.add_field(
        name="📋 `-list`",
        value="Show all tracked players and their tags.",
        inline=False
    )

    # === Stats and Leaderboards ===
    embed.add_field(
        name="📊 `-stats <name or tag>`",
        value="Show today's Legend League stats with gear info.\n**Example**: `-stats Ajay`",
        inline=False
    )

    embed.add_field(
        name="🔍 `-search <name or tag>`",
        value="Search for any player globally with real-time data.\n**Example**: `-search Ajay` or `-search #TAG`",
        inline=False
    )

    embed.add_field(
        name="🏆 `-leaderboard`",
        value="Show current tracked players ranked by trophies.",
        inline=False
    )

    embed.add_field(
        name="📊 `-patterns <name>`",
        value="Analyze attack patterns and performance trends.\n**Example**: `-patterns Ajay`",
        inline=False
    )

    embed.add_field(
        name="📅 `-eos <name> <count>`",
        value="Check End of Season legend rankings.\n**Example**: `-eos Ajay 5`",
        inline=False
    )

    embed.add_field(
        name="🌍 `-localrank <country> <limit>`",
        value="Get top players from a specific country.\n**Example**: `-localrank India 10`",
        inline=False
    )

    embed.add_field(
        name="🔻 `-cutoff`",
        value="Check global legend league trophy cutoff buckets.",
        inline=False
    )

    embed.add_field(
        name="❓ `-helpme` or `-commands` or `-cmds`",
        value="Display this help menu.",
        inline=False
    )

    embed.set_footer(text="Use commands with prefix '-' (dash). Need help? Ask the WatchDog bot creator 🐾")
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3305/3305803.png")
    await ctx.send(embed=embed)

# === ERROR HANDLER FOR UNKNOWN COMMANDS ===
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("⚠️ Unknown command! Use `-helpme` to see all available commands.")
    else:
        logger.error(f"Command error: {error}")
        await ctx.send("❌ An error occurred while processing the command.")

# === RUN ===
bot.run(TOKEN)