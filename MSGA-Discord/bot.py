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
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0"))
VERIFICATION_FILE_PATH = os.getenv("VERIFICATION_FILE_PATH", "/root/verification_codes.json")

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
    """Check if a player is in the specified Hypixel guild"""
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
                    
                    # Check if it's the correct guild - HYPIXEL_GUILD_ID is a hex string (MongoDB ObjectId)
                    if guild.get("_id") == HYPIXEL_GUILD_ID:
                        return {"success": True, "guild_name": guild.get("name")}
                    else:
                        return {"success": False, "error": f"Player is in a different guild: {guild.get('name')}"}
                else:
                    return {"success": False, "error": f"Hypixel API error: {resp.status}"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Hypixel API timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
                
                # Check guild membership
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
                    # Player is in the guild - assign verified role
                    data[code]["guild_verified"] = True
                    data[code]["verified_at"] = datetime.now(timezone.utc).isoformat()
                    data[code]["guild_name"] = guild_result.get("guild_name")
                    
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
                    
                    role = discord_guild.get_role(VERIFIED_ROLE_ID)
                    if not role:
                        print(f"❌ Verified role not found (ID: {VERIFIED_ROLE_ID})")
                        data[code]["error"] = "Verified role not found"
                        save_verification_codes(data)
                        continue
                    
                    try:
                        if role not in member.roles:
                            await member.add_roles(role)
                            print(f"✅ Successfully assigned verified role to {member.name} for Minecraft account {correct_name}")
                        else:
                            print(f"ℹ️ {member.name} already has the verified role")
                        
                        # Send success DM
                        try:
                            embed = discord.Embed(
                                title="✅ Verification Complete!",
                                description=f"Your Minecraft account **{correct_name}** has been verified!",
                                color=discord.Color.green()
                            )
                            embed.add_field(
                                name="Guild Membership",
                                value=f"You are a member of **{guild_result['guild_name']}**",
                                inline=False
                            )
                            embed.add_field(
                                name="Role Granted",
                                value=f"You have been granted the {role.mention} role",
                                inline=False
                            )
                            embed.set_footer(text=f"Verification code: {code}")
                            await member.send(embed=embed)
                        except Exception as e:
                            print(f"⚠️ Could not send success DM: {e}")
                        
                    except discord.Forbidden:
                        error_msg = "Bot missing permissions to add role"
                        print(f"❌ {error_msg}")
                        data[code]["error"] = error_msg
                    except Exception as e:
                        error_msg = f"Error assigning role: {str(e)}"
                        print(f"❌ {error_msg}")
                        data[code]["error"] = error_msg
                
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
        
        # Check verified role
        role = discord_guild.get_role(VERIFIED_ROLE_ID)
        if role:
            print(f"🛡️ Verified role found: {role.name}")
        else:
            print(f"❌ Verified role NOT found (ID: {VERIFIED_ROLE_ID})")
    else:
        print(f"❌ Discord guild NOT found (ID: {DISCORD_GUILD_ID})")
    
    print(f"🤖 Bot is ready for verification!")
    print(f"📁 Verification file: {VERIFICATION_FILE_PATH}")
    print(f"🎮 Hypixel Guild ID: {HYPIXEL_GUILD_ID}")
    print(f"🛡️ Verified Role ID: {VERIFIED_ROLE_ID}")
    
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
        name="📍 **Step 3: Wait for Verification**",
        value="The bot will automatically check if you're in the guild and assign the verified role",
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
        # Check if user already has verified role
        discord_guild = bot.get_guild(DISCORD_GUILD_ID)
        if discord_guild:
            member = discord_guild.get_member(interaction.user.id)
            if member:
                role = discord_guild.get_role(VERIFIED_ROLE_ID)
                if role and role in member.roles:
                    embed = discord.Embed(
                        title="✅ Already Verified",
                        description="You have already been verified and have the verified role!",
                        color=discord.Color.green()
                    )
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
        embed.add_field(name="Status", value="Checking guild membership...", inline=False)
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
                embed.add_field(name="Guild", value=entry.get("guild_name"), inline=False)
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
            processed = entry.get("processed", False)
            guild_verified = entry.get("guild_verified", None)
            discord_user_id = entry.get("discord_user_id", "None")
            
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
            
            entry_info = f"**{code}**: {minecraft_username}\nDiscord: {discord_name} ({discord_user_id})"
            
            if not verified:
                pending_codes.append(entry_info)
            elif verified and not processed:
                submitted_codes.append(entry_info)
            elif processed and guild_verified:
                processed_codes.append(entry_info)
            elif processed and not guild_verified:
                failed_codes.append(entry_info)
        
        embeds = []
        
        if pending_codes:
            embed = discord.Embed(
                title="📝 Pending Codes (not submitted in Minecraft)",
                description="\n".join(pending_codes[:10]),  # Limit to 10
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Total: {len(pending_codes)}")
            embeds.append(embed)
        
        if submitted_codes:
            embed = discord.Embed(
                title="🔄 Submitted Codes (waiting for processing)",
                description="\n".join(submitted_codes[:10]),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Total: {len(submitted_codes)}")
            embeds.append(embed)
        
        if processed_codes:
            embed = discord.Embed(
                title="✅ Verified Codes",
                description="\n".join(processed_codes[:10]),
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Total: {len(processed_codes)}")
            embeds.append(embed)
        
        if failed_codes:
            embed = discord.Embed(
                title="❌ Failed Verifications",
                description="\n".join(failed_codes[:10]),
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

# ==================== MAIN ENTRY POINT ====================
if __name__ == "__main__":
    print("🚀 Starting Discord Verification Bot...")
    print("=" * 50)
    print(f"📁 Verification file: {VERIFICATION_FILE_PATH}")
    print(f"🎮 Hypixel Guild ID: {HYPIXEL_GUILD_ID}")
    print(f"💬 Discord Guild ID: {DISCORD_GUILD_ID}")
    print(f"🛡️ Verified Role ID: {VERIFIED_ROLE_ID}")
    
    # Check if verification file exists
    if os.path.exists(VERIFICATION_FILE_PATH):
        print("✅ Verification file found")
    else:
        print("⚠️ Verification file not found. It will be created when first code is generated.")
    
    print("=" * 50)
    print("🤖 Starting bot...")
    
    bot.run(DISCORD_TOKEN)