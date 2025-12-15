import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

# ==================== CONFIGURATION ====================
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HYPIXEL_API_KEY = os.getenv("HYPIXEL_API_KEY")
GUILD_ID = os.getenv("GUILD_ID")
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0"))
VERIFICATION_FILE_PATH = os.getenv("VERIFICATION_FILE_PATH", "/root/verification_codes.json")

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store active verifications
active_verifications = {}

# ==================== HELPER FUNCTIONS ====================
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

def update_verification_status(code: str, verified: bool = False, discord_user_id: str = None):
    """Update the verification status in the JSON file"""
    try:
        # Load current data
        with open(VERIFICATION_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Update the specific code entry
        if code in data:
            data[code]["verified"] = verified
            if discord_user_id:
                data[code]["discord_user_id"] = discord_user_id
            
            # Save back to file
            with open(VERIFICATION_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            status = "verified: true" if verified else "verified: false"
            print(f"✅ Updated code {code} status: {status}")
            return True
        else:
            print(f"❌ Code {code} not found in verification file")
            return False
            
    except Exception as e:
        print(f"❌ Error updating verification status: {e}")
        return False

async def process_verification(code: str, discord_user_id: str, interaction: discord.Interaction = None):
    """Process a verification code - check guild and assign role if in guild"""
    try:
        # Load the verification codes
        data = load_verification_codes()
        
        if code not in data:
            if interaction:
                await interaction.followup.send(f"❌ Verification code `{code}` not found. Make sure you entered it correctly in Minecraft.", ephemeral=True)
            return False
        
        entry = data[code]
        minecraft_username = entry.get("minecraft_username")
        
        # Get Minecraft UUID
        uuid_result = await get_minecraft_uuid(minecraft_username)
        if not uuid_result["success"]:
            if interaction:
                await interaction.followup.send(f"❌ Error: {uuid_result['error']}", ephemeral=True)
            return False
        
        uuid = uuid_result["uuid"]
        correct_name = uuid_result["name"]
        
        # Check guild membership
        guild_result = await check_guild_membership(uuid)
        
        # Update verification status to false (processed)
        update_verification_status(code, False, discord_user_id)
        
        if not guild_result["success"]:
            # Not in the guild
            if interaction:
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
                    value="1. Make sure you're in the correct Hypixel guild\n2. Make sure your Minecraft username is correct\n3. Try the verification process again",
                    inline=False
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            
            print(f"❌ Guild verification failed for {correct_name}: {guild_result['error']}")
            return False
        
        # Player is in the guild - assign verified role
        guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID else None
        if guild:
            member = guild.get_member(int(discord_user_id))
            if member:
                role = guild.get_role(VERIFIED_ROLE_ID)
                if role:
                    try:
                        if role not in member.roles:
                            await member.add_roles(role)
                        
                        # Send success message
                        if interaction:
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
                            await interaction.followup.send(embed=embed, ephemeral=True)
                        
                        print(f"✅ Successfully verified {correct_name} (Discord: {member.name}) in guild {guild_result['guild_name']}")
                        return True
                        
                    except discord.Forbidden:
                        error_msg = "Bot missing permissions to add role"
                        if interaction:
                            await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                        print(f"❌ {error_msg}")
                        return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error processing verification: {e}")
        if interaction:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
        return False

async def check_pending_verifications():
    """Check for pending verifications (verified: true) and process them"""
    try:
        data = load_verification_codes()
        
        for code, entry in data.items():
            # Check if verified is true (submitted by Minecraft plugin)
            if entry.get("verified", False):
                minecraft_username = entry.get("minecraft_username")
                discord_user_id = entry.get("discord_user_id")
                
                if not discord_user_id:
                    print(f"⚠️ Code {code} has no discord_user_id, skipping")
                    continue
                
                print(f"🔄 Processing pending verification for code {code} (Minecraft: {minecraft_username})")
                
                # Process verification without interaction
                await process_verification(code, discord_user_id)
                
    except Exception as e:
        print(f"❌ Error checking pending verifications: {e}")

# ==================== BOT EVENTS ====================
@bot.event
async def on_ready():
    print(f"✅ Discord Bot logged in as {bot.user}")
    print(f"📊 Connected to {len(bot.guilds)} guild(s)")
    print(f"🤖 Bot is ready for verification!")
    print(f"📁 Verification file: {VERIFICATION_FILE_PATH}")
    
    # Load existing verification codes
    data = load_verification_codes()
    
    # Count verified vs unverified
    verified_count = sum(1 for entry in data.values() if entry.get("verified", False))
    unverified_count = len(data) - verified_count
    print(f"📊 Loaded {len(data)} verification entries ({verified_count} pending, {unverified_count} processed)")
    
    # Start background task
    bot.loop.create_task(check_pending_periodically())
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

async def check_pending_periodically():
    """Periodically check for pending verifications (verified: true)"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_pending_verifications()
        except Exception as e:
            print(f"❌ Error in pending verification check: {e}")
        await asyncio.sleep(10)  # Check every 10 seconds

# ==================== SLASH COMMANDS ====================
@bot.tree.command(name="verify", description="Start verification process with your Minecraft username")
@app_commands.describe(minecraft_username="Your Minecraft username")
async def verify_command(interaction: discord.Interaction, minecraft_username: str):
    """Start verification process by providing Minecraft username"""
    
    await interaction.response.defer(ephemeral=True)
    
    # Clean username
    minecraft_username = minecraft_username.strip()
    
    # Store user's Minecraft username with a placeholder code
    # The actual code will be generated by the Minecraft plugin
    user_id = str(interaction.user.id)
    active_verifications[user_id] = {
        "minecraft_username": minecraft_username,
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    
    embed = discord.Embed(
        title="🔐 Verification Instructions",
        description=f"To verify your Minecraft account **{minecraft_username}**, please follow these steps:",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📝 **Step 1: Join Minecraft Server**",
        value="Join our Minecraft server",
        inline=False
    )
    embed.add_field(
        name="📝 **Step 2: Get Your Code**",
        value="Once in the server, you will receive a 6-digit verification code automatically",
        inline=False
    )
    embed.add_field(
        name="📝 **Step 3: Submit Code**",
        value="Type `/verify <code>` in Minecraft chat (replace `<code>` with your actual code)",
        inline=False
    )
    embed.add_field(
        name="📝 **Step 4: Complete Verification**",
        value="After submitting the code in Minecraft, come back here and use `/submit_code <code>` to finish the process",
        inline=False
    )
    embed.add_field(
        name="ℹ️ **Note**",
        value="After submitting the code in Minecraft, you will be kicked from the server. This is normal!",
        inline=False
    )
    embed.set_footer(text="You can use /status to check your verification progress")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="submit_code", description="Submit your verification code after entering it in Minecraft")
@app_commands.describe(code="The 6-digit verification code you received in Minecraft")
async def submit_code_command(interaction: discord.Interaction, code: str):
    """Submit verification code after entering it in Minecraft"""
    
    await interaction.response.defer(ephemeral=True)
    
    user_id = str(interaction.user.id)
    
    # Check if user started verification
    if user_id not in active_verifications:
        embed = discord.Embed(
            title="❌ No Active Verification",
            description="You haven't started a verification yet. Use `/verify <minecraft_username>` first.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Clean code
    code = code.strip()
    
    # Process the verification
    success = await process_verification(code, user_id, interaction)
    
    if success:
        # Remove from active verifications
        active_verifications.pop(user_id, None)

@bot.tree.command(name="status", description="Check your verification status")
async def status_command(interaction: discord.Interaction):
    """Check verification status"""
    await interaction.response.defer(ephemeral=True)
    
    user_id = str(interaction.user.id)
    
    # Check if user has an active verification
    if user_id in active_verifications:
        user_data = active_verifications[user_id]
        minecraft_username = user_data["minecraft_username"]
        
        embed = discord.Embed(
            title="⏳ Verification Pending",
            description=f"Your verification for **{minecraft_username}** is pending.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Status",
            value="Waiting for you to submit the code in Minecraft",
            inline=False
        )
        embed.add_field(
            name="Instructions",
            value="1. Join the Minecraft server\n2. You will receive a code\n3. Type `/verify <code>` in Minecraft\n4. Come back here and use `/submit_code <code>`",
            inline=False
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Check if user is already verified (has the role)
    guild = interaction.guild
    member = guild.get_member(interaction.user.id)
    
    if member:
        role = guild.get_role(VERIFIED_ROLE_ID)
        if role and role in member.roles:
            embed = discord.Embed(
                title="✅ Already Verified",
                description="You have already been verified and have the verified role!",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
    
    # User has no active verification and is not verified
    embed = discord.Embed(
        title="❌ No Active Verification",
        description="You don't have an active verification.\nUse `/verify <minecraft_username>` to start.",
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="force_verify", description="Manually verify a code (Admin only)")
@app_commands.describe(code="The 6-digit verification code")
@app_commands.default_permissions(administrator=True)
async def force_verify_command(interaction: discord.Interaction, code: str):
    """Manually verify a code"""
    await interaction.response.defer(ephemeral=True)
    
    success = await process_verification(code, str(interaction.user.id), interaction)
    
    if not success:
        await interaction.followup.send(f"❌ Failed to verify code `{code}`", ephemeral=True)

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
        
        # Create embeds (split into multiple if too many)
        pending_codes = []
        processed_codes = []
        
        for code, entry in data.items():
            minecraft_username = entry.get("minecraft_username", "Unknown")
            verified = entry.get("verified", False)
            timestamp = entry.get("timestamp", 0)
            discord_user_id = entry.get("discord_user_id", "None")
            
            # Convert timestamp to readable time
            if timestamp:
                dt = datetime.fromtimestamp(timestamp, timezone.utc)
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_str = "Unknown"
            
            entry_info = f"**{code}**: {minecraft_username} ({time_str})\nDiscord ID: {discord_user_id}"
            
            if verified:
                pending_codes.append(entry_info)
            else:
                processed_codes.append(entry_info)
        
        # Create embeds
        embeds = []
        
        if pending_codes:
            embed = discord.Embed(
                title="📝 Pending Verifications (verified: true)",
                description="\n".join(pending_codes) if pending_codes else "None",
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Total: {len(pending_codes)}")
            embeds.append(embed)
        
        if processed_codes:
            embed = discord.Embed(
                title="✅ Processed Codes (verified: false)",
                description="\n".join(processed_codes[:25]),  # Limit to 25 entries
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Total: {len(processed_codes)}")
            embeds.append(embed)
        
        # Send embeds
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ==================== MAIN ENTRY POINT ====================
if __name__ == "__main__":
    print("🚀 Starting Discord Verification Bot...")
    print("=" * 50)
    print(f"📁 Verification file: {VERIFICATION_FILE_PATH}")
    
    # Check if verification file exists
    if os.path.exists(VERIFICATION_FILE_PATH):
        print("✅ Verification file found")
    else:
        print("⚠️ Verification file not found. It will be created by the Minecraft plugin.")
    
    print("=" * 50)
    print("🤖 Starting bot...")
    
    bot.run(DISCORD_TOKEN)