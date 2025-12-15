import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import json
import os
import random
import string
from datetime import datetime, timezone
from dotenv import load_dotenv

# ==================== CONFIGURATION ====================
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HYPIXEL_API_KEY = os.getenv("HYPIXEL_API_KEY")
HYPIXEL_GUILD_ID = os.getenv("HYPIXEL_GUILD_ID")  # Hypixel guild MongoDB ID (hex string)
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))  # Discord server ID (numeric)
VERIFICATION_FILE_PATH = os.getenv("VERIFICATION_FILE_PATH", "/root/verification_codes.json")

# Discord role IDs for guild ranks
GUILD_ROLE_IDS = {
    "Guild Master": int(os.getenv("GUILD_MASTER_ROLE_ID", "0")),
    "Guild Officer": int(os.getenv("GUILD_OFFICER_ROLE_ID", "0")),
    "Guild Member": int(os.getenv("GUILD_MEMBER_ROLE_ID", "0")),
    "Guild Recruit": int(os.getenv("GUILD_RECRUIT_ROLE_ID", "0"))  # Add if you have a recruit role
}

# Default role if rank is not in mapping (can be changed to Member or None)
DEFAULT_GUILD_ROLE_ID = GUILD_ROLE_IDS["Guild Member"]

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== HELPER FUNCTIONS ====================
def generate_code() -> str:
    """Generate a random 6-digit verification code"""
    return ''.join(random.choices(string.digits, k=6))

def load_verification_codes():
    """Load verification codes from JSON file"""
    try:
        with open(VERIFICATION_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"✅ Loaded {len(data)} verification codes from {VERIFICATION_FILE_PATH}")
            return data
    except FileNotFoundError:
        print(f"❌ Verification file not found at {VERIFICATION_FILE_PATH}")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON: {e}")
        return {}
    except Exception as e:
        print(f"❌ Error loading verification codes: {e}")
        return {}

def save_verification_codes(data):
    """Save verification codes to JSON file"""
    try:
        with open(VERIFICATION_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Saved {len(data)} verification codes to {VERIFICATION_FILE_PATH}")
        return True
    except Exception as e:
        print(f"❌ Error saving verification codes: {e}")
        return False

async def get_minecraft_uuid(username: str) -> dict:
    """Get Minecraft UUID from username using Mojang API"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"https://api.mojang.com/users/profiles/minecraft/{username}",
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"success": True, "uuid": data["id"], "name": data["name"]}
                elif resp.status == 404:
                    return {"success": False, "error": "Minecraft account not found"}
                else:
                    return {"success": False, "error": f"Mojang API error: {resp.status}"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Mojang API timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

async def check_guild_membership(uuid: str) -> dict:
    """Check if a player is in the specified Hypixel guild and get their rank"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"https://api.hypixel.net/guild",
                params={"key": HYPIXEL_API_KEY, "player": uuid},
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if not data.get("success"):
                        return {"success": False, "error": "Hypixel API request failed"}
                    
                    guild = data.get("guild")
                    if guild is None:
                        return {"success": False, "error": "Player is not in any guild"}
                    
                    # Check if it's the correct guild
                    if guild.get("_id") == HYPIXEL_GUILD_ID:
                        # Get the player's guild rank
                        members = guild.get("members", [])
                        player_rank = "Guild Member"  # Default rank
                        
                        # Find the player in members list
                        for member in members:
                            if member.get("uuid") == uuid:
                                # Get the rank name
                                rank = member.get("rank")
                                if rank == "Guild Master":
                                    player_rank = "Guild Master"
                                elif rank == "Officer":
                                    player_rank = "Guild Officer"
                                elif rank == "Member":
                                    player_rank = "Guild Member"
                                elif rank == "Recruit":
                                    player_rank = "Guild Recruit"
                                else:
                                    # For custom ranks, check if it's an officer rank
                                    # Hypixel API returns ranks in order of priority
                                    ranks = guild.get("ranks", [])
                                    for r in ranks:
                                        if r.get("name") == rank:
                                            # Check if rank has officer permissions (priority >= 3)
                                            if r.get("priority", 0) >= 3:
                                                player_rank = "Guild Officer"
                                            break
                                
                                # Get join date if available
                                join_date = member.get("joined", 0)
                                if join_date:
                                    join_date = datetime.fromtimestamp(join_date/1000).strftime('%Y-%m-%d')
                                
                                return {
                                    "success": True, 
                                    "guild_name": guild.get("name"),
                                    "guild_rank": player_rank,
                                    "join_date": join_date,
                                    "raw_rank": rank
                                }
                        
                        return {
                            "success": True, 
                            "guild_name": guild.get("name"),
                            "guild_rank": player_rank,
                            "join_date": None,
                            "raw_rank": "Member"
                        }
                    else:
                        return {"success": False, "error": f"Player is in a different guild: {guild.get('name')}"}
                else:
                    return {"success": False, "error": f"Hypixel API error: {resp.status}"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Hypixel API timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

async def get_discord_role_for_guild_rank(guild_rank: str):
    """Get the Discord role ID for a given Hypixel guild rank"""
    return GUILD_ROLE_IDS.get(guild_rank, DEFAULT_GUILD_ROLE_ID)

async def assign_guild_rank_role(member, guild_rank: str, discord_guild):
    """Assign the appropriate Discord role based on Hypixel guild rank"""
    role_id = await get_discord_role_for_guild_rank(guild_rank)
    
    if not role_id:
        print(f"⚠️ No role ID found for guild rank: {guild_rank}")
        return None
    
    role = discord_guild.get_role(role_id)
    if not role:
        print(f"❌ Discord role not found for ID: {role_id} (Rank: {guild_rank})")
        return None
    
    # Remove any existing guild rank roles first
    existing_guild_roles = []
    for role_id in GUILD_ROLE_IDS.values():
        if role_id:
            existing_role = discord_guild.get_role(role_id)
            if existing_role and existing_role in member.roles:
                existing_guild_roles.append(existing_role)
    
    if existing_guild_roles:
        try:
            await member.remove_roles(*existing_guild_roles)
            print(f"↪️ Removed existing guild roles from {member.name}")
        except discord.Forbidden:
            print(f"❌ Missing permissions to remove roles from {member.name}")
        except Exception as e:
            print(f"⚠️ Error removing roles: {e}")
    
    # Add the new guild rank role
    try:
        await member.add_roles(role)
        print(f"✅ Assigned {role.name} role to {member.name} (Hypixel Rank: {guild_rank})")
        return role
    except discord.Forbidden:
        print(f"❌ Missing permissions to add role {role.name} to {member.name}")
        return None
    except Exception as e:
        print(f"❌ Error assigning role: {e}")
        return None

async def process_verified_codes():
    """Process codes that have been set to verified: true by Minecraft plugin"""
    try:
        data = load_verification_codes()
        processed_any = False
        
        for code, entry in data.items():
            # Check if code is verified by Minecraft plugin but not processed yet
            if entry.get("verified", False) and not entry.get("processed", False):
                minecraft_username = entry.get("minecraft_username")
                discord_user_id = entry.get("discord_user_id")
                
                if not discord_user_id:
                    print(f"⚠️ Code {code} has no discord_user_id, skipping")
                    continue
                
                print(f"🔄 Processing verified code {code} for {minecraft_username}")
                
                # Get Minecraft UUID
                uuid_result = await get_minecraft_uuid(minecraft_username)
                if not uuid_result["success"]:
                    print(f"❌ Failed to get UUID for {minecraft_username}: {uuid_result['error']}")
                    # Mark as processed anyway to avoid retrying
                    data[code]["processed"] = True
                    data[code]["error"] = uuid_result["error"]
                    save_verification_codes(data)
                    continue
                
                uuid = uuid_result["uuid"]
                correct_name = uuid_result["name"]
                
                # Check guild membership and get rank
                guild_result = await check_guild_membership(uuid)
                
                # Mark as processed
                data[code]["processed"] = True
                
                if not guild_result["success"]:
                    # Not in the guild
                    print(f"❌ Guild check failed for {correct_name}: {guild_result['error']}")
                    data[code]["guild_verified"] = False
                    data[code]["error"] = guild_result["error"]
                    
                    # Try to send DM to user
                    try:
                        discord_guild = bot.get_guild(DISCORD_GUILD_ID)
                        if discord_guild:
                            member = discord_guild.get_member(int(discord_user_id))
                            if member:
                                embed = discord.Embed(
                                    title="❌ Verification Failed",
                                    description=f"Your Minecraft account **{correct_name}** could not be verified.",
                                    color=discord.Color.red()
                                )
                                embed.add_field(
                                    name="Reason",
                                    value=guild_result['error'],
                                    inline=False
                                )
                                embed.add_field(
                                    name="What to do",
                                    value="1. Make sure you're in the correct Hypixel guild\n2. Try the verification process again",
                                    inline=False
                                )
                                await member.send(embed=embed)
                    except Exception as e:
                        print(f"⚠️ Could not send DM: {e}")
                    
                else:
                    # Player is in the guild - assign appropriate role based on rank
                    data[code]["guild_verified"] = True
                    data[code]["verified_at"] = datetime.now(timezone.utc).isoformat()
                    data[code]["guild_name"] = guild_result.get("guild_name")
                    data[code]["guild_rank"] = guild_result.get("guild_rank")
                    data[code]["raw_rank"] = guild_result.get("raw_rank")
                    data[code]["join_date"] = guild_result.get("join_date")
                    
                    # Get Discord guild and assign role
                    discord_guild = bot.get_guild(DISCORD_GUILD_ID)
                    if not discord_guild:
                        print(f"❌ Discord guild not found (ID: {DISCORD_GUILD_ID})")
                        data[code]["error"] = "Discord guild not found"
                        save_verification_codes(data)
                        continue
                    
                    member = discord_guild.get_member(int(discord_user_id))
                    if not member:
                        print(f"❌ Discord member not found (ID: {discord_user_id})")
                        data[code]["error"] = "Discord member not found in server"
                        save_verification_codes(data)
                        continue
                    
                    # Assign guild rank role
                    assigned_role = await assign_guild_rank_role(
                        member, 
                        guild_result.get("guild_rank"), 
                        discord_guild
                    )
                    
                    if not assigned_role:
                        error_msg = "Failed to assign guild rank role"
                        print(f"❌ {error_msg}")
                        data[code]["error"] = error_msg
                        save_verification_codes(data)
                        continue
                    
                    print(f"✅ Successfully assigned {assigned_role.name} role to {member.name} for Minecraft account {correct_name}")
                    
                    # Send success DM
                    try:
                        embed = discord.Embed(
                            title="✅ Verification Complete!",
                            description=f"Your Minecraft account **{correct_name}** has been verified!",
                            color=discord.Color.green()
                        )
                        embed.add_field(
                            name="Guild",
                            value=f"**{guild_result['guild_name']}**",
                            inline=True
                        )
                        embed.add_field(
                            name="Guild Rank",
                            value=f"**{guild_result['guild_rank']}**",
                            inline=True
                        )
                        embed.add_field(
                            name="Discord Role",
                            value=assigned_role.mention,
                            inline=False
                        )
                        if guild_result.get("join_date"):
                            embed.add_field(
                                name="Guild Join Date",
                                value=guild_result["join_date"],
                                inline=True
                            )
                        embed.set_footer(text=f"Verification code: {code}")
                        await member.send(embed=embed)
                    except Exception as e:
                        print(f"⚠️ Could not send success DM: {e}")
                
                save_verification_codes(data)
                processed_any = True
        
        return processed_any
        
    except Exception as e:
        print(f"❌ Error processing verified codes: {e}")
        return False

# ==================== BOT EVENTS ====================
@bot.event
async def on_ready():
    print(f"✅ Discord Bot logged in as {bot.user}")
    print(f"📊 Connected to {len(bot.guilds)} guild(s)")
    
    # Get the Discord guild
    discord_guild = bot.get_guild(DISCORD_GUILD_ID)
    if discord_guild:
        print(f"🎯 Target Discord Guild: {discord_guild.name} (ID: {discord_guild.id})")
        
        # Check guild rank roles
        print("🛡️ Guild Rank Roles:")
        for rank_name, role_id in GUILD_ROLE_IDS.items():
            if role_id:
                role = discord_guild.get_role(role_id)
                if role:
                    print(f"  ✅ {rank_name}: {role.name} (ID: {role.id})")
                else:
                    print(f"  ❌ {rank_name} role NOT found (ID: {role_id})")
    else:
        print(f"❌ Discord guild NOT found (ID: {DISCORD_GUILD_ID})")
    
    print(f"🤖 Bot is ready for verification!")
    print(f"📁 Verification file: {VERIFICATION_FILE_PATH}")
    print(f"🎮 Hypixel Guild ID: {HYPIXEL_GUILD_ID}")
    
    # Load existing verification codes
    data = load_verification_codes()
    
    # Count statuses
    pending = sum(1 for e in data.values() if not e.get("verified", False))
    verified = sum(1 for e in data.values() if e.get("verified", False))
    processed = sum(1 for e in data.values() if e.get("processed", False))
    
    print(f"📊 Loaded {len(data)} codes: {pending} pending, {verified} verified, {processed} processed")
    
    # Start background task
    bot.loop.create_task(check_verified_periodically())
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

async def check_verified_periodically():
    """Periodically check for codes set to verified: true by Minecraft"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await process_verified_codes()
        except Exception as e:
            print(f"❌ Error in verification check: {e}")
        await asyncio.sleep(5)  # Check every 5 seconds

# ==================== SLASH COMMANDS ====================
@bot.tree.command(name="verify", description="Start verification process with your Minecraft username")
@app_commands.describe(minecraft_username="Your Minecraft username")
async def verify_command(interaction: discord.Interaction, minecraft_username: str):
    """Start verification process - generates code and saves with verified: false"""
    
    await interaction.response.defer(ephemeral=True)
    
    # Clean username
    minecraft_username = minecraft_username.strip()
    
    # Load existing data
    data = load_verification_codes()
    
    # Check if user already has an active verification (not processed)
    user_id = str(interaction.user.id)
    for code, entry in data.items():
        if entry.get("discord_user_id") == user_id and not entry.get("processed", False):
            if entry.get("verified", False):
                status = "Submitted in Minecraft - waiting for processing"
            else:
                status = "Pending - not submitted in Minecraft yet"
            
            embed = discord.Embed(
                title="⚠️ Active Verification Found",
                description=f"You already have an active verification!",
                color=discord.Color.orange()
            )
            embed.add_field(name="Minecraft Account", value=entry.get("minecraft_username"), inline=False)
            embed.add_field(name="Verification Code", value=f"`{code}`", inline=False)
            embed.add_field(name="Status", value=status, inline=False)
            embed.add_field(
                name="Instructions",
                value=f"Join the Minecraft server and type:\n```/verify {code}```",
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
    
    # Generate new code
    code = generate_code()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    
    # Save to JSON with verified: false
    data[code] = {
        "minecraft_username": minecraft_username,
        "timestamp": timestamp,
        "verified": False,  # Minecraft plugin will set this to true
        "discord_user_id": user_id,
        "processed": False,  # Bot will set this to true after processing
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    save_verification_codes(data)
    
    # Send instructions to user
    embed = discord.Embed(
        title="🔐 Verification Started",
        description=f"To verify your Minecraft account **{minecraft_username}**, please follow these steps:",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📝 **Your Verification Code:**",
        value=f"```{code}```",
        inline=False
    )
    embed.add_field(
        name="📍 **Step 1: Join Minecraft Server**",
        value="Join our Minecraft server",
        inline=False
    )
    embed.add_field(
        name="📍 **Step 2: Submit Code**",
        value=f"Once in the server, type:\n```/verify {code}```",
        inline=False
    )
    embed.add_field(
        name="📍 **Step 3: Get Your Guild Rank Role**",
        value="The bot will check your Hypixel guild rank and assign the appropriate Discord role:\n"
              f"• **Guild Officer** → <@&{GUILD_ROLE_IDS['Guild Officer']}>\n"
              f"• **Guild Member** → <@&{GUILD_ROLE_IDS['Guild Member']}>",
        inline=False
    )
    embed.add_field(
        name="ℹ️ **Note:**",
        value="After submitting the code, you will be kicked from the server. This is normal!",
        inline=False
    )
    embed.add_field(
        name="⏱️ **Code expires in 30 minutes**",
        value="If you don't submit the code within 30 minutes, you'll need to start over",
        inline=False
    )
    
    await interaction.followup.send(embed=embed, ephemeral=True)
    print(f"📝 Generated code {code} for {minecraft_username} (Discord: {interaction.user.name})")

@bot.tree.command(name="status", description="Check your verification status")
async def status_command(interaction: discord.Interaction):
    """Check verification status"""
    await interaction.response.defer(ephemeral=True)
    
    user_id = str(interaction.user.id)
    data = load_verification_codes()
    
    # Find user's codes
    user_codes = []
    for code, entry in data.items():
        if entry.get("discord_user_id") == user_id:
            user_codes.append((code, entry))
    
    if not user_codes:
        # Check if user already has a guild rank role
        discord_guild = bot.get_guild(DISCORD_GUILD_ID)
        if discord_guild:
            member = discord_guild.get_member(interaction.user.id)
            if member:
                # Check for any guild rank role
                has_guild_role = False
                current_role = None
                for role_id in GUILD_ROLE_IDS.values():
                    if role_id:
                        role = discord_guild.get_role(role_id)
                        if role and role in member.roles:
                            has_guild_role = True
                            current_role = role
                            break
                
                if has_guild_role and current_role:
                    embed = discord.Embed(
                        title="✅ Already Verified",
                        description=f"You already have the {current_role.mention} role!",
                        color=discord.Color.green()
                    )
                    # Try to find the user's verification entry
                    for code, entry in data.items():
                        if entry.get("discord_user_id") == user_id and entry.get("guild_verified"):
                            if entry.get("guild_rank"):
                                embed.add_field(
                                    name="Hypixel Guild Rank",
                                    value=entry.get("guild_rank"),
                                    inline=True
                                )
                            if entry.get("guild_name"):
                                embed.add_field(
                                    name="Guild",
                                    value=entry.get("guild_name"),
                                    inline=True
                                )
                            break
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
        
        embed = discord.Embed(
            title="❌ No Active Verification",
            description="You don't have an active verification.\nUse `/verify <minecraft_username>` to start.",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Show most recent code
    code, entry = user_codes[-1]  # Most recent
    minecraft_username = entry.get("minecraft_username")
    verified = entry.get("verified", False)
    processed = entry.get("processed", False)
    guild_verified = entry.get("guild_verified", None)
    
    if not verified:
        # Code not submitted in Minecraft yet
        embed = discord.Embed(
            title="⏳ Waiting for Minecraft Submission",
            description=f"Your verification for **{minecraft_username}** is pending.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Verification Code", value=f"`{code}`", inline=False)
        embed.add_field(
            name="Instructions",
            value=f"Join the Minecraft server and type:\n```/verify {code}```",
            inline=False
        )
    elif verified and not processed:
        # Submitted in Minecraft, waiting for bot to process
        embed = discord.Embed(
            title="🔄 Processing Verification",
            description=f"Code submitted for **{minecraft_username}**!",
            color=discord.Color.blue()
        )
        embed.add_field(name="Status", value="Checking guild membership and rank...", inline=False)
        embed.add_field(name="Code", value=f"`{code}`", inline=False)
    elif processed:
        if guild_verified:
            # Successfully verified
            embed = discord.Embed(
                title="✅ Verification Complete!",
                description=f"Your Minecraft account **{minecraft_username}** has been verified!",
                color=discord.Color.green()
            )
            if entry.get("guild_name"):
                embed.add_field(name="Guild", value=entry.get("guild_name"), inline=True)
            if entry.get("guild_rank"):
                embed.add_field(name="Guild Rank", value=entry.get("guild_rank"), inline=True)
            if entry.get("join_date"):
                embed.add_field(name="Joined Guild", value=entry.get("join_date"), inline=True)
        else:
            # Guild verification failed
            embed = discord.Embed(
                title="❌ Guild Verification Failed",
                description=f"Your Minecraft account **{minecraft_username}** is not in the required guild.",
                color=discord.Color.red()
            )
            if entry.get("error"):
                embed.add_field(name="Reason", value=entry.get("error"), inline=False)
            embed.add_field(
                name="What to do",
                value="1. Make sure you're in the correct Hypixel guild\n2. Use `/verify <minecraft_username>` to try again",
                inline=False
            )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="myrank", description="Check your current guild rank and role")
async def myrank_command(interaction: discord.Interaction):
    """Check user's current guild rank and assigned role"""
    await interaction.response.defer(ephemeral=True)
    
    discord_guild = bot.get_guild(DISCORD_GUILD_ID)
    if not discord_guild:
        await interaction.followup.send("❌ Could not find the Discord server.", ephemeral=True)
        return
    
    member = discord_guild.get_member(interaction.user.id)
    if not member:
        await interaction.followup.send("❌ Could not find your member information.", ephemeral=True)
        return
    
    # Check which guild rank role the user has
    user_guild_roles = []
    for rank_name, role_id in GUILD_ROLE_IDS.items():
        if role_id:
            role = discord_guild.get_role(role_id)
            if role and role in member.roles:
                user_guild_roles.append((rank_name, role))
    
    if not user_guild_roles:
        embed = discord.Embed(
            title="❌ No Guild Role Assigned",
            description="You don't have any guild rank roles assigned.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="How to get a role",
            value="Use `/verify <minecraft_username>` to start the verification process.",
            inline=False
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # User has at least one guild role (should only have one)
    rank_name, role = user_guild_roles[0]
    
    # Look up verification data for this user
    data = load_verification_codes()
    user_verifications = []
    
    for code, entry in data.items():
        if entry.get("discord_user_id") == str(interaction.user.id) and entry.get("guild_verified"):
            user_verifications.append(entry)
    
    embed = discord.Embed(
        title="🎮 Your Guild Information",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="Current Discord Role",
        value=f"{role.mention} ({rank_name})",
        inline=False
    )
    
    if user_verifications:
        latest = user_verifications[-1]  # Most recent verification
        if latest.get("guild_name"):
            embed.add_field(
                name="Hypixel Guild",
                value=latest.get("guild_name"),
                inline=True
            )
        if latest.get("guild_rank"):
            embed.add_field(
                name="Hypixel Rank",
                value=latest.get("guild_rank"),
                inline=True
            )
        if latest.get("join_date"):
            embed.add_field(
                name="Joined Guild",
                value=latest.get("join_date"),
                inline=True
            )
        if latest.get("minecraft_username"):
            embed.add_field(
                name="Minecraft Account",
                value=latest.get("minecraft_username"),
                inline=False
            )
    else:
        embed.add_field(
            name="⚠️ Note",
            value="No recent verification data found. Your role was assigned manually or in a previous session.",
            inline=False
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="list_codes", description="List all verification codes (Admin only)")
@app_commands.default_permissions(administrator=True)
async def list_codes_command(interaction: discord.Interaction):
    """List all verification codes"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        data = load_verification_codes()
        
        if not data:
            await interaction.followup.send("No verification codes found.", ephemeral=True)
            return
        
        # Create embeds for different statuses
        pending_codes = []
        submitted_codes = []
        processed_codes = []
        failed_codes = []
        
        for code, entry in data.items():
            minecraft_username = entry.get("minecraft_username", "Unknown")
            verified = entry.get("verified", False)
            processed_status = entry.get("processed", False)
            guild_verified = entry.get("guild_verified", None)
            discord_user_id = entry.get("discord_user_id", "None")
            guild_rank = entry.get("guild_rank", "Unknown")
            
            # Try to get Discord username
            discord_name = "Unknown"
            try:
                discord_guild = bot.get_guild(DISCORD_GUILD_ID)
                if discord_guild:
                    member = discord_guild.get_member(int(discord_user_id)) if discord_user_id.isdigit() else None
                    if member:
                        discord_name = member.name
            except:
                pass
            
            entry_info = f"**{code}**: {minecraft_username}\n"
            entry_info += f"Discord: {discord_name} ({discord_user_id})\n"
            
            if guild_verified and guild_rank:
                entry_info += f"Rank: {guild_rank}\n"
            
            if not verified:
                pending_codes.append(entry_info)
            elif verified and not processed_status:
                submitted_codes.append(entry_info)
            elif processed_status and guild_verified:
                processed_codes.append(entry_info)
            elif processed_status and not guild_verified:
                failed_codes.append(entry_info)
        
        embeds = []
        
        if pending_codes:
            embed = discord.Embed(
                title="📝 Pending Codes (not submitted in Minecraft)",
                description="\n".join(pending_codes[:8]),  # Limit to 8
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Total: {len(pending_codes)}")
            embeds.append(embed)
        
        if submitted_codes:
            embed = discord.Embed(
                title="🔄 Submitted Codes (waiting for processing)",
                description="\n".join(submitted_codes[:8]),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Total: {len(submitted_codes)}")
            embeds.append(embed)
        
        if processed_codes:
            embed = discord.Embed(
                title="✅ Verified Codes",
                description="\n".join(processed_codes[:8]),
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Total: {len(processed_codes)}")
            embeds.append(embed)
        
        if failed_codes:
            embed = discord.Embed(
                title="❌ Failed Verifications",
                description="\n".join(failed_codes[:8]),
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Total: {len(failed_codes)}")
            embeds.append(embed)
        
        # Send embeds
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="cleanup", description="Clean up old verification codes (Admin only)")
@app_commands.default_permissions(administrator=True)
async def cleanup_command(interaction: discord.Interaction):
    """Remove old verification codes"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        data = load_verification_codes()
        old_count = len(data)
        
        # Remove codes older than 24 hours
        current_time = datetime.now(timezone.utc).timestamp()
        codes_to_remove = []
        
        for code, entry in data.items():
            timestamp = entry.get("timestamp", 0)
            if current_time - timestamp > 86400:  # 24 hours
                codes_to_remove.append(code)
        
        for code in codes_to_remove:
            data.pop(code, None)
        
        if codes_to_remove:
            save_verification_codes(data)
        
        embed = discord.Embed(
            title="🧹 Cleanup Complete",
            description=f"Removed {len(codes_to_remove)} old verification codes.",
            color=discord.Color.green()
        )
        embed.add_field(name="Before", value=old_count, inline=True)
        embed.add_field(name="After", value=len(data), inline=True)
        embed.add_field(name="Removed", value=len(codes_to_remove), inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="forcerole", description="Force assign a guild role to a user (Admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    member="The Discord member",
    rank="The guild rank to assign"
)
@app_commands.choices(rank=[
    app_commands.Choice(name="Guild Master", value="Guild Master"),
    app_commands.Choice(name="Guild Officer", value="Guild Officer"),
    app_commands.Choice(name="Guild Member", value="Guild Member"),
    app_commands.Choice(name="Guild Recruit", value="Guild Recruit")
])
async def forcerole_command(interaction: discord.Interaction, member: discord.Member, rank: str):
    """Force assign a guild rank role to a user"""
    await interaction.response.defer(ephemeral=True)
    
    discord_guild = bot.get_guild(DISCORD_GUILD_ID)
    if not discord_guild:
        await interaction.followup.send("❌ Could not find the Discord server.", ephemeral=True)
        return
    
    assigned_role = await assign_guild_rank_role(member, rank, discord_guild)
    
    if assigned_role:
        embed = discord.Embed(
            title="✅ Role Assigned",
            description=f"Successfully assigned {assigned_role.mention} to {member.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Guild Rank", value=rank, inline=True)
    else:
        embed = discord.Embed(
            title="❌ Failed to Assign Role",
            description=f"Could not assign role to {member.mention}",
            color=discord.Color.red()
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ==================== MAIN ENTRY POINT ====================
if __name__ == "__main__":
    print("🚀 Starting Discord Verification Bot...")
    print("=" * 50)
    print(f"📁 Verification file: {VERIFICATION_FILE_PATH}")
    print(f"🎮 Hypixel Guild ID: {HYPIXEL_GUILD_ID}")
    print(f"💬 Discord Guild ID: {DISCORD_GUILD_ID}")
    print("🛡️ Guild Rank Roles:")
    for rank_name, role_id in GUILD_ROLE_IDS.items():
        if role_id:
            print(f"  • {rank_name}: {role_id}")
    
    # Check if verification file exists
    if os.path.exists(VERIFICATION_FILE_PATH):
        print("✅ Verification file found")
    else:
        print("⚠️ Verification file not found. It will be created when first code is generated.")
    
    print("=" * 50)
    print("🤖 Starting bot...")
    
    bot.run(DISCORD_TOKEN)