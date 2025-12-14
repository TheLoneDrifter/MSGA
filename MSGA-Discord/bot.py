import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import random
import string
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import json
import glob

# ==================== CONFIGURATION ====================
load_dotenv()

# Discord Bot Settings
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HYPIXEL_API_KEY = os.getenv("HYPIXEL_API_KEY")
GUILD_ID = os.getenv("GUILD_ID")
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0"))

# Minecraft Plugin Settings
VERIFICATION_FILE_PATH = os.getenv("VERIFICATION_FILE_PATH", "verification_codes.json")
PLUGIN_LOG_PATH = os.getenv("PLUGIN_LOG_PATH", "verification_log.txt")
MINECRAFT_VERIFY_ACCOUNT = os.getenv("MINECRAFT_VERIFY_ACCOUNT", "MSGA-Verify")

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store verification codes in memory and track processed ones
verification_codes = {}
processed_codes = set()
failed_codes = {}

# ==================== HELPER FUNCTIONS ====================
def generate_code() -> str:
    """Generate a random 6-digit verification code"""
    return ''.join(random.choices(string.digits, k=6))

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
                    
                    # Check if it's the correct guild
                    if guild.get("_id") == GUILD_ID:
                        return {"success": True, "guild_name": guild.get("name")}
                    else:
                        return {"success": False, "error": f"Player is in a different guild: {guild.get('name')}"}
                else:
                    return {"success": False, "error": f"Hypixel API error: {resp.status}"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Hypixel API timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

def load_verification_codes():
    """Load verification codes from JSON file"""
    global verification_codes
    
    try:
        # Try multiple possible locations
        possible_paths = [
            VERIFICATION_FILE_PATH,
            f"plugins/VerifyPlugin/{VERIFICATION_FILE_PATH}",
            "verification_codes.json",
            "plugins/verification_codes.json",
            "../verification_codes.json"
        ]
        
        actual_path = None
        for path in possible_paths:
            if os.path.exists(path):
                actual_path = path
                break
        
        if not actual_path:
            print(f"❌ Verification file not found. Tried: {possible_paths}")
            verification_codes = {}
            return verification_codes
        
        with open(actual_path, 'r', encoding='utf-8') as f:
            try:
                content = json.load(f)
                print(f"✅ Loaded {len(content)} verification codes from {actual_path}")
                
                # Convert to our format: code -> (minecraft_username, timestamp, discord_user_id)
                for code, data in content.items():
                    if isinstance(data, dict):
                        minecraft_username = data.get("minecraft_username", "")
                        timestamp = data.get("timestamp", 0)
                        discord_user_id = data.get("discord_user_id", None)
                        
                        verification_codes[code] = {
                            "minecraft_username": minecraft_username,
                            "timestamp": timestamp,
                            "discord_user_id": discord_user_id,
                            "status": "pending",
                            "file_path": actual_path
                        }
                
            except json.JSONDecodeError as e:
                print(f"❌ Error parsing JSON from {actual_path}: {e}")
                verification_codes = {}
                
    except Exception as e:
        print(f"❌ Error loading verification codes: {e}")
        verification_codes = {}
    
    return verification_codes

def save_verification_codes():
    """Save verification codes to JSON file"""
    try:
        if not verification_codes:
            return False
        
        # Use the first file path we found
        file_path = None
        for code_data in verification_codes.values():
            if code_data.get("file_path"):
                file_path = code_data["file_path"]
                break
        
        if not file_path:
            file_path = VERIFICATION_FILE_PATH
        
        # Convert to Minecraft plugin format
        output_data = {}
        for code, data in verification_codes.items():
            if data.get("status") != "removed":  # Don't save removed codes
                output_data[code] = {
                    "minecraft_username": data["minecraft_username"],
                    "timestamp": data["timestamp"]
                }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else '.', exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"✅ Saved {len(output_data)} verification codes to {file_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error saving verification codes: {e}")
        return False

async def log_verification(event_type: str, discord_user_id: str = None, 
                          minecraft_username: str = None, code: str = None, 
                          details: str = None):
    """Log verification activity"""
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        log_entry = f"[{timestamp}] {event_type}: "
        if discord_user_id:
            log_entry += f"Discord={discord_user_id}, "
        if minecraft_username:
            log_entry += f"MC={minecraft_username}, "
        if code:
            log_entry += f"Code={code}, "
        if details:
            log_entry += f"Details={details}"
        
        print(f"📝 {log_entry}")
        
        # Also write to log file
        try:
            log_file_path = PLUGIN_LOG_PATH
            # Try to find log file in plugin directory
            possible_log_paths = [
                PLUGIN_LOG_PATH,
                f"plugins/VerifyPlugin/{PLUGIN_LOG_PATH}",
                "verification_log.txt",
                "plugins/verification_log.txt"
            ]
            
            actual_log_path = None
            for path in possible_log_paths:
                if os.path.exists(path):
                    actual_log_path = path
                    break
            
            if not actual_log_path:
                # Create in current directory
                actual_log_path = PLUGIN_LOG_PATH
            
            with open(actual_log_path, 'a', encoding='utf-8') as f:
                f.write(log_entry + "\n")
                
        except Exception as e:
            print(f"⚠️ Could not write to log file: {e}")
            
    except Exception as e:
        print(f"❌ Error logging verification: {e}")

async def create_verification_code(discord_user_id: str, minecraft_username: str) -> dict:
    """Create a new verification code"""
    code = generate_code()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    
    try:
        # Store in memory
        verification_codes[code] = {
            "minecraft_username": minecraft_username,
            "timestamp": timestamp,
            "discord_user_id": discord_user_id,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        }
        
        # Save to file
        save_success = save_verification_codes()
        
        if save_success:
            await log_verification("code_generated", discord_user_id, minecraft_username, code, 
                                 f"New verification code generated for {minecraft_username}")
            return {
                "success": True,
                "code": code,
                "message": f"Verification code generated for {minecraft_username}"
            }
        else:
            # Remove from memory if save failed
            verification_codes.pop(code, None)
            return {
                "success": False,
                "error": "Failed to save verification code to file",
                "code": None
            }
        
    except Exception as e:
        print(f"❌ Error creating verification code: {e}")
        return {
            "success": False,
            "error": f"Error creating code: {str(e)}",
            "code": None
        }

def check_pending_verification(discord_user_id: str) -> dict:
    """Check if user has a pending verification"""
    try:
        current_time = datetime.now(timezone.utc)
        
        for code, data in verification_codes.items():
            if (data.get("discord_user_id") == discord_user_id and 
                data.get("status") == "pending"):
                
                # Check expiration
                expires_at_str = data.get("expires_at")
                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                        time_left = expires_at - current_time
                        time_left_minutes = max(0, time_left.total_seconds() / 60)
                    except:
                        time_left_minutes = 0
                else:
                    # Default 30 minutes from creation
                    created_at_str = data.get("created_at")
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                            expires_at = created_at + timedelta(minutes=30)
                            time_left = expires_at - current_time
                            time_left_minutes = max(0, time_left.total_seconds() / 60)
                        except:
                            time_left_minutes = 0
                    else:
                        time_left_minutes = 0
                
                return {
                    "exists": True,
                    "status": "pending",
                    "code": code,
                    "minecraft_username": data["minecraft_username"],
                    "expires_at": expires_at_str,
                    "time_left_minutes": int(time_left_minutes)
                }
        
        return {"exists": False}
    except Exception as e:
        print(f"❌ Error checking pending verification: {e}")
        return {"exists": False}

async def cancel_verification(discord_user_id: str):
    """Cancel a pending verification"""
    try:
        for code, data in list(verification_codes.items()):
            if (data.get("discord_user_id") == discord_user_id and 
                data.get("status") == "pending"):
                
                # Mark as cancelled
                verification_codes[code]["status"] = "cancelled"
                
                # Save changes
                save_verification_codes()
                
                await log_verification("verification_cancelled", discord_user_id, 
                                     data["minecraft_username"], code, 
                                     "User cancelled verification")
                return True
        
        return False
    except Exception as e:
        print(f"❌ Error cancelling verification: {e}")
        return False

async def check_submitted_codes():
    """Check for codes submitted by Minecraft players"""
    try:
        # Reload codes from file
        load_verification_codes()
        
        current_time = datetime.now(timezone.utc)
        
        # Find codes that are pending and have been in the file for a while
        # (indicating they were submitted in Minecraft)
        for code, data in list(verification_codes.items()):
            if data.get("status") == "pending":
                # Check if code is recent (submitted in last 5 minutes)
                timestamp = data.get("timestamp", 0)
                code_age = current_time.timestamp() - timestamp
                
                # If code was created more than 2 minutes ago but less than 35 minutes ago,
                # it was likely submitted in Minecraft
                if 120 < code_age < 2100:  # 2 minutes to 35 minutes
                    discord_user_id = data.get("discord_user_id")
                    minecraft_username = data.get("minecraft_username")
                    
                    if discord_user_id and minecraft_username:
                        # Mark as submitted
                        verification_codes[code]["status"] = "submitted"
                        await log_verification("code_submitted", discord_user_id, 
                                             minecraft_username, code, 
                                             "Code submitted in Minecraft")
                        
                        # Process the verification
                        await process_verification(discord_user_id, minecraft_username, code)
        
        # Clean up old processed codes
        cleanup_old_codes()
                
    except Exception as e:
        print(f"❌ Error checking submitted codes: {e}")

def cleanup_old_codes():
    """Remove old processed codes from memory"""
    try:
        current_time = datetime.now(timezone.utc)
        codes_to_remove = []
        
        for code, data in list(verification_codes.items()):
            status = data.get("status")
            timestamp = data.get("timestamp", 0)
            code_age = current_time.timestamp() - timestamp
            
            # Remove codes that are:
            # 1. Processed (verified/failed) and older than 1 hour
            # 2. Expired pending codes older than 2 hours
            # 3. Cancelled codes older than 1 hour
            
            if status in ["verified", "failed", "expired", "cancelled"] and code_age > 3600:
                codes_to_remove.append(code)
            elif status == "pending" and code_age > 7200:  # 2 hours
                codes_to_remove.append(code)
        
        # Remove old codes
        for code in codes_to_remove:
            verification_codes.pop(code, None)
        
        if codes_to_remove:
            print(f"🧹 Cleaned up {len(codes_to_remove)} old codes")
            
    except Exception as e:
        print(f"❌ Error cleaning up old codes: {e}")

async def process_verification(discord_user_id: str, minecraft_username: str, code: str):
    """Process a submitted verification"""
    try:
        # Mark as processing
        if code in verification_codes:
            verification_codes[code]["status"] = "processing"
        
        # Get Minecraft UUID
        uuid_result = await get_minecraft_uuid(minecraft_username)
        if not uuid_result["success"]:
            error_msg = f"Minecraft account not found: {uuid_result['error']}"
            await log_verification("verification_failed", discord_user_id, minecraft_username, code, error_msg)
            
            if code in verification_codes:
                verification_codes[code]["status"] = "failed"
                verification_codes[code]["details"] = error_msg
            
            save_verification_codes()
            return
        
        uuid = uuid_result["uuid"]
        correct_name = uuid_result["name"]
        
        # Check guild membership
        guild_result = await check_guild_membership(uuid)
        if not guild_result["success"]:
            error_msg = guild_result["error"]
            await log_verification("guild_check_failed", discord_user_id, correct_name, code, error_msg)
            
            if code in verification_codes:
                verification_codes[code]["status"] = "failed"
                verification_codes[code]["details"] = error_msg
            
            save_verification_codes()
            return
        
        # Verification successful - assign role
        for guild in bot.guilds:
            member = guild.get_member(int(discord_user_id))
            if member:
                role = guild.get_role(VERIFIED_ROLE_ID)
                if role:
                    try:
                        # Check if member already has the role
                        if role not in member.roles:
                            await member.add_roles(role)
                        
                        # Update verification status
                        verified_at = datetime.now(timezone.utc).isoformat()
                        
                        if code in verification_codes:
                            verification_codes[code].update({
                                "status": "verified",
                                "verified_at": verified_at,
                                "details": f"Guild: {guild_result['guild_name']}",
                                "minecraft_uuid": uuid,
                                "corrected_name": correct_name
                            })
                        
                        # Save changes
                        save_verification_codes()
                        
                        await log_verification("verification_success", discord_user_id, correct_name, code, 
                                             f"Assigned role {role.name} - Guild: {guild_result['guild_name']}")
                        
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
                        except discord.Forbidden:
                            # Can't send DM, that's okay
                            pass
                        
                        # Optional: Announce in a channel
                        announcement_channel = discord.utils.get(guild.text_channels, name="verifications")
                        if not announcement_channel:
                            # Try to find any appropriate channel
                            for channel in guild.text_channels:
                                if "verify" in channel.name.lower() or "general" in channel.name.lower():
                                    announcement_channel = channel
                                    break
                        
                        if announcement_channel:
                            announce_embed = discord.Embed(
                                title="🎉 New Member Verified!",
                                description=f"{member.mention} has been verified as **{correct_name}**",
                                color=discord.Color.green()
                            )
                            announce_embed.add_field(
                                name="Guild",
                                value=guild_result['guild_name'],
                                inline=True
                            )
                            announce_embed.set_footer(text=f"Verification code: {code}")
                            await announcement_channel.send(embed=announce_embed)
                        
                    except discord.Forbidden:
                        error_msg = "Bot missing permissions to add role"
                        await log_verification("role_assignment_failed", discord_user_id, correct_name, code, error_msg)
                        if code in verification_codes:
                            verification_codes[code]["status"] = "failed"
                            verification_codes[code]["details"] = error_msg
                        save_verification_codes()
                    except Exception as e:
                        error_msg = str(e)
                        await log_verification("verification_error", discord_user_id, correct_name, code, error_msg)
                        if code in verification_codes:
                            verification_codes[code]["status"] = "failed"
                            verification_codes[code]["details"] = error_msg
                        save_verification_codes()
                else:
                    error_msg = f"Verified role not found (ID: {VERIFIED_ROLE_ID})"
                    await log_verification("role_not_found", discord_user_id, correct_name, code, error_msg)
                    if code in verification_codes:
                        verification_codes[code]["status"] = "failed"
                        verification_codes[code]["details"] = error_msg
                    save_verification_codes()
        
    except Exception as e:
        error_msg = f"Error processing verification: {str(e)}"
        await log_verification("verification_error", discord_user_id, minecraft_username, code, error_msg)
        if code in verification_codes:
            verification_codes[code]["status"] = "failed"
            verification_codes[code]["details"] = error_msg
        save_verification_codes()

# ==================== BOT EVENTS ====================
@bot.event
async def on_ready():
    print(f"✅ Discord Bot logged in as {bot.user}")
    print(f"📊 Connected to {len(bot.guilds)} guild(s)")
    print(f"🤖 Bot is ready for verification!")
    print(f"📁 Looking for verification file: {VERIFICATION_FILE_PATH}")
    
    # Load existing verification codes
    load_verification_codes()
    print(f"📊 Loaded {len(verification_codes)} existing verification codes")
    
    # Start background tasks
    bot.loop.create_task(check_verifications_periodically())
    bot.loop.create_task(cleanup_expired_periodically())
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

async def check_verifications_periodically():
    """Periodically check for submitted verifications"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_submitted_codes()
        except Exception as e:
            print(f"❌ Error in verification check: {e}")
        await asyncio.sleep(5)  # Check every 5 seconds

async def cleanup_expired_periodically():
    """Periodically clean up expired verifications"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            current_time = datetime.now(timezone.utc)
            expired_count = 0
            
            for code, data in list(verification_codes.items()):
                if data.get("status") == "pending":
                    expires_at_str = data.get("expires_at")
                    if expires_at_str:
                        try:
                            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                            if current_time > expires_at:
                                verification_codes[code]["status"] = "expired"
                                expired_count += 1
                                
                                # Log expiration
                                discord_user_id = data.get("discord_user_id")
                                minecraft_username = data.get("minecraft_username")
                                await log_verification("verification_expired", discord_user_id, 
                                                     minecraft_username, code, "Code expired (30 minutes)")
                        except:
                            pass
            
            if expired_count > 0:
                save_verification_codes()
                print(f"🧹 Marked {expired_count} verifications as expired")
                
        except Exception as e:
            print(f"❌ Error cleaning up expired verifications: {e}")
        await asyncio.sleep(60)  # Clean up every minute

# ==================== SLASH COMMANDS ====================
@bot.tree.command(name="verify", description="Start verification process with your Minecraft username")
@app_commands.describe(minecraft_username="Your Minecraft username")
async def verify_command(interaction: discord.Interaction, minecraft_username: str):
    """Start verification process by generating a code"""
    
    await interaction.response.defer(ephemeral=True)
    
    # Clean username
    minecraft_username = minecraft_username.strip()
    
    # Check for existing pending verification
    pending = check_pending_verification(str(interaction.user.id))
    
    if pending["exists"]:
        minutes_left = pending["time_left_minutes"]
        embed = discord.Embed(
            title="⚠️ Verification Pending",
            description=f"You already have a pending verification!\n\n**Minecraft Account:** {pending['minecraft_username']}\n\nIn Minecraft, type:\n```/verify {pending['code']}```",
            color=discord.Color.orange()
        )
        if minutes_left > 0:
            embed.add_field(
                name="⏱️ Expires in",
                value=f"{minutes_left} minutes",
                inline=False
            )
        else:
            embed.add_field(
                name="⚠️ Status",
                value="Expired - generating new code",
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        # If expired, still allow creating new one
        if minutes_left <= 0:
            await create_new_verification(interaction, minecraft_username)
        return
    
    # Create new verification
    await create_new_verification(interaction, minecraft_username)

async def create_new_verification(interaction: discord.Interaction, minecraft_username: str):
    """Helper to create new verification"""
    result = await create_verification_code(str(interaction.user.id), minecraft_username)
    
    if not result["success"]:
        embed = discord.Embed(
            title="❌ Error",
            description=result["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    code = result["code"]
    
    embed = discord.Embed(
        title="🔐 Verification Started",
        description=f"To verify your Minecraft account **{minecraft_username}**, please join our server and run:",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📝 **In Minecraft, type:**",
        value=f"```/verify {code}```",
        inline=False
    )
    embed.add_field(
        name="📍 **Instructions:**",
        value="1. Join the server\n2. Wait until you're in the lobby\n3. Run the command above\n4. You will be automatically kicked\n5. Wait for verification to complete on Discord",
        inline=False
    )
    embed.add_field(
        name="⏱️ **Code expires in 30 minutes**",
        value="If the code expires, use `/verify` again to get a new one",
        inline=False
    )
    embed.add_field(
        name="ℹ️ **Note:**",
        value="You will be kicked from the server after submitting the code. This is normal!",
        inline=False
    )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="verification_status", description="Check your current verification status")
async def verification_status(interaction: discord.Interaction):
    """Check verification status"""
    await interaction.response.defer(ephemeral=True)
    
    pending = check_pending_verification(str(interaction.user.id))
    
    if pending["exists"]:
        minutes_left = pending["time_left_minutes"]
        status_color = discord.Color.orange() if pending["status"] == "pending" else discord.Color.blue()
        
        embed = discord.Embed(
            title=f"⏳ Verification {pending['status'].upper()}",
            description=f"**Minecraft Account:** {pending['minecraft_username']}",
            color=status_color
        )
        embed.add_field(name="Verification Code", value=f"`{pending['code']}`", inline=False)
        
        if minutes_left > 0:
            embed.add_field(name="⏱️ Time Remaining", value=f"{minutes_left} minutes", inline=False)
        else:
            embed.add_field(name="⚠️ Status", value="Expired", inline=False)
        
        if pending["status"] == "pending":
            embed.add_field(
                name="📝 Instructions",
                value=f"In Minecraft, type:\n```/verify {pending['code']}```",
                inline=False
            )
        elif pending["status"] == "submitted":
            embed.add_field(
                name="🔄 Status",
                value="Code submitted! Processing verification...",
                inline=False
            )
        elif pending["status"] == "processing":
            embed.add_field(
                name="⚙️ Status",
                value="Verification in progress...",
                inline=False
            )
        elif pending["status"] == "verified":
            embed.add_field(
                name="✅ Status",
                value="Verification complete! You should have the verified role.",
                inline=False
            )
    else:
        # Check if user has verified role
        member = interaction.guild.get_member(interaction.user.id)
        if member:
            role = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if role and role in member.roles:
                embed = discord.Embed(
                    title="✅ Already Verified",
                    description=f"You have the verified role!",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="Role",
                    value=role.mention,
                    inline=False
                )
            else:
                embed = discord.Embed(
                    title="❌ No Active Verification",
                    description="You don't have any active verifications.\nUse `/verify <minecraft_username>` to start.",
                    color=discord.Color.blue()
                )
        else:
            embed = discord.Embed(
                title="❌ No Active Verification",
                description="You don't have any active verifications.\nUse `/verify <minecraft_username>` to start.",
                color=discord.Color.blue()
            )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="cancel_verification", description="Cancel your pending verification")
async def cancel_verification_command(interaction: discord.Interaction):
    """Cancel pending verification"""
    await interaction.response.defer(ephemeral=True)
    
    success = await cancel_verification(str(interaction.user.id))
    
    if success:
        embed = discord.Embed(
            title="✅ Verification Cancelled",
            description="Your pending verification has been cancelled.",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="❌ No Pending Verification",
            description="You don't have any pending verifications to cancel.",
            color=discord.Color.blue()
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="verification_stats", description="Show verification statistics (Admin only)")
@app_commands.default_permissions(administrator=True)
async def verification_stats(interaction: discord.Interaction):
    """Show verification statistics"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Count different statuses
        status_counts = {
            "pending": 0,
            "submitted": 0,
            "processing": 0,
            "verified": 0,
            "failed": 0,
            "expired": 0,
            "cancelled": 0
        }
        
        for code, data in verification_codes.items():
            status = data.get("status", "unknown")
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts["failed"] += 1  # Default to failed for unknown
        
        total = sum(status_counts.values())
        
        embed = discord.Embed(
            title="📊 Verification Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(name="Total Verifications", value=total, inline=True)
        embed.add_field(name="Successful", value=status_counts["verified"], inline=True)
        embed.add_field(name="Pending", value=status_counts["pending"], inline=True)
        embed.add_field(name="Processing", value=status_counts["processing"], inline=True)
        embed.add_field(name="Submitted", value=status_counts["submitted"], inline=True)
        embed.add_field(name="Failed/Expired", value=status_counts["failed"] + status_counts["expired"] + status_counts["cancelled"], inline=True)
        
        # Get recent successful verifications
        recent_verified = []
        for code, data in verification_codes.items():
            if data.get("status") == "verified":
                verified_at = data.get("verified_at", "")
                if verified_at:
                    try:
                        time = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
                        time_str = time.strftime('%H:%M')
                    except:
                        time_str = "Unknown"
                else:
                    time_str = "Unknown"
                
                recent_verified.append({
                    "username": data.get("minecraft_username", "Unknown"),
                    "time": time_str,
                    "code": code
                })
        
        # Sort by time (most recent first)
        recent_verified.sort(key=lambda x: x.get("time", ""), reverse=True)
        
        if recent_verified:
            recent_list = []
            for v in recent_verified[:5]:  # Last 5
                recent_list.append(f"**{v['username']}** - {v['time']}")
            
            embed.add_field(
                name="Recent Verifications",
                value="\n".join(recent_list) if recent_list else "None",
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error fetching statistics: {str(e)}", ephemeral=True)

@bot.tree.command(name="reload_codes", description="Reload verification codes from file (Admin only)")
@app_commands.default_permissions(administrator=True)
async def reload_codes_command(interaction: discord.Interaction):
    """Reload verification codes from file"""
    await interaction.response.defer(ephemeral=True)
    
    old_count = len(verification_codes)
    load_verification_codes()
    new_count = len(verification_codes)
    
    embed = discord.Embed(
        title="🔄 Codes Reloaded",
        description=f"Reloaded verification codes from file.",
        color=discord.Color.green()
    )
    embed.add_field(name="Previous Count", value=old_count, inline=True)
    embed.add_field(name="New Count", value=new_count, inline=True)
    embed.add_field(name="Difference", value=f"+{new_count - old_count}" if new_count > old_count else f"{new_count - old_count}", inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ==================== MAIN ENTRY POINT ====================
if __name__ == "__main__":
    print("🚀 Starting Discord Verification Bot...")
    print("=" * 50)
    print("📁 Looking for verification files...")
    
    # Try to find verification files
    possible_files = [
        "verification_codes.json",
        "plugins/verification_codes.json",
        "plugins/VerifyPlugin/verification_codes.json",
        "../verification_codes.json"
    ]
    
    found_files = []
    for file_path in possible_files:
        if os.path.exists(file_path):
            found_files.append(file_path)
            print(f"✅ Found: {file_path}")
    
    if not found_files:
        print("⚠️ No verification files found. Bot will create new ones.")
    else:
        print(f"📊 Found {len(found_files)} verification file(s)")
    
    print("=" * 50)
    print("🤖 Starting bot...")
    
    bot.run(DISCORD_TOKEN)