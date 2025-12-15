package com.msga.verify;

import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.CommandExecutor;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.ChatColor;
import org.bukkit.configuration.file.FileConfiguration;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.World;

import java.io.File;
import java.io.IOException;
import java.nio.file.*;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.logging.Level;
import java.util.regex.Pattern;
import java.text.SimpleDateFormat;
import java.util.Date;

public class VerifyPlugin extends JavaPlugin implements Listener, CommandExecutor {
    
    private FileConfiguration config;
    private File configFile;
    private File logFile;
    
    // Configuration settings
    private String discordBotName = "MSGA-Verify";
    private String successMessage;
    private String errorMessage;
    private String usageMessage;
    private boolean broadcastVerifications = false;
    private boolean requireOnline = false;
    private Path sharedCodesPath;
    private String kickSuccessMessage;
    private String kickErrorMessage;
    
    @Override
    public void onEnable() {
        // Create plugin folder if it doesn't exist
        if (!getDataFolder().exists()) {
            getDataFolder().mkdirs();
        }
        
        // Setup configuration
        setupConfig();
        
        // Register commands
        this.getCommand("verify").setExecutor(this);
        
        // Register events
        getServer().getPluginManager().registerEvents(this, this);
        
        // Create log file
        logFile = new File(getDataFolder(), "verification_log.txt");
        
        // Try to find shared codes file from Discord bot
        findSharedCodesFile();
        
        getLogger().info("VerifyPlugin has been enabled!");
        getLogger().info("Players can use: /verify <6-digit-code>");
        getLogger().info("Discord bot account name: " + discordBotName);
    }
    
    @Override
    public void onDisable() {
        getLogger().info("VerifyPlugin has been disabled!");
    }
    
    private void setupConfig() {
        configFile = new File(getDataFolder(), "config.yml");
        
        if (!configFile.exists()) {
            saveDefaultConfig();
        }
        
        reloadConfig();
        config = getConfig();
        
        // Set default values if not present
        config.addDefault("discord-bot-name", "MSGA-Verify");
        config.addDefault("messages.success", "&a&l✅ Code submitted! The Discord bot will now verify your guild membership.");
        config.addDefault("messages.error", "&c&l❌ Invalid code! Code must be 6 digits.");
        config.addDefault("messages.usage", "&e&lUsage: /verify <6-digit-code>");
        config.addDefault("messages.code-too-short", "&c&l❌ Code too short! Must be 6 digits.");
        config.addDefault("messages.code-too-long", "&c&l❌ Code too long! Must be 6 digits.");
        config.addDefault("messages.code-invalid-chars", "&c&l❌ Code must contain only numbers!");
        config.addDefault("messages.code-not-found", "&c&l❌ Invalid code! Code not found or already used.");
        config.addDefault("broadcast-verifications", false);
        config.addDefault("require-online", false);
        // Default path for Ubuntu root setup
        config.addDefault("shared-codes-path", "/root/verification_codes.json");
        config.addDefault("delete-player-data", true);
        config.addDefault("kick-messages.success", "&a&lSuccessful - Code submitted. Check Discord for verification status.");
        config.addDefault("kick-messages.error", "&c&lUnsuccessful - Invalid verification code");
        config.addDefault("kick-messages.code-too-short", "&c&lUnsuccessful - Code too short");
        config.addDefault("kick-messages.code-too-long", "&c&lUnsuccessful - Code too long");
        config.addDefault("kick-messages.code-invalid-chars", "&c&lUnsuccessful - Code contains invalid characters");
        config.addDefault("kick-messages.code-not-found", "&c&lUnsuccessful - Code not found");
        config.addDefault("kick-messages.save-error", "&c&lUnsuccessful - System error, please contact admin");
        
        config.options().copyDefaults(true);
        saveConfig();
        
        // Load settings
        discordBotName = config.getString("discord-bot-name", "MSGA-Verify");
        successMessage = ChatColor.translateAlternateColorCodes('&', config.getString("messages.success"));
        errorMessage = ChatColor.translateAlternateColorCodes('&', config.getString("messages.error"));
        usageMessage = ChatColor.translateAlternateColorCodes('&', config.getString("messages.usage"));
        broadcastVerifications = config.getBoolean("broadcast-verifications", false);
        requireOnline = config.getBoolean("require-online", false);
        
        // Load kick messages
        kickSuccessMessage = ChatColor.translateAlternateColorCodes('&', config.getString("kick-messages.success", "&a&lSuccessful - Code submitted. Check Discord for verification status."));
        kickErrorMessage = ChatColor.translateAlternateColorCodes('&', config.getString("kick-messages.error", "&c&lUnsuccessful - Invalid verification code"));
        
        String sharedPath = config.getString("shared-codes-path", "/root/verification_codes.json");
        if (!sharedPath.isEmpty()) {
            sharedCodesPath = Paths.get(sharedPath);
            getLogger().info("Using shared codes path: " + sharedCodesPath.toAbsolutePath());
        }
    }
    
    private void findSharedCodesFile() {
        // Try to automatically find the verification_codes.json file
        File serverRoot = new File(".");
        File[] possibleLocations = {
            new File(serverRoot, "verification_codes.json"),
            new File(serverRoot.getParentFile(), "verification_codes.json"),
            new File("/root/verification_codes.json"),  // Explicit path for Ubuntu root
            new File("../verification_codes.json"),  // Parent directory (mcserver's parent)
            new File("../../verification_codes.json"),  // Two levels up
            new File("verification_codes.json")  // Current directory
        };
        
        for (File location : possibleLocations) {
            if (location.exists() && location.isFile()) {
                sharedCodesPath = location.toPath();
                getLogger().info("Found shared codes file at: " + location.getAbsolutePath());
                return;
            }
        }
        
        getLogger().warning("Could not find shared verification_codes.json file!");
        getLogger().warning("Make sure to set 'shared-codes-path' in config.yml");
        getLogger().warning("Expected location: /root/verification_codes.json");
    }
    
    @EventHandler
    public void onPlayerJoin(PlayerJoinEvent event) {
        // Optional: Send reminder about verification
        // Player player = event.getPlayer();
        // player.sendMessage(ChatColor.YELLOW + "Use /verify <code> to submit your verification code from Discord");
    }
    
    @Override
    public boolean onCommand(CommandSender sender, Command cmd, String label, String[] args) {
        if (!(sender instanceof Player)) {
            sender.sendMessage(ChatColor.RED + "This command can only be used by players!");
            return true;
        }
        
        Player player = (Player) sender;
        UUID playerId = player.getUniqueId();
        String playerName = player.getName();
        
        // Check if player provided a code
        if (args.length == 0) {
            player.sendMessage(usageMessage);
            player.sendMessage(ChatColor.GRAY + "Get your code from the Discord bot using /verify command");
            return true;
        }
        
        String code = args[0].trim();
        String kickReason = "";
        boolean shouldKick = true;
        boolean verificationSuccessful = false;
        boolean deletePlayerData = config.getBoolean("delete-player-data", true);
        
        // Validate code format (6 digits)
        if (!isValidCode(code)) {
            if (code.length() < 6) {
                kickReason = ChatColor.translateAlternateColorCodes('&', 
                    config.getString("kick-messages.code-too-short", "&c&lUnsuccessful - Code too short"));
                player.sendMessage(ChatColor.translateAlternateColorCodes('&', 
                    config.getString("messages.code-too-short")));
            } else if (code.length() > 6) {
                kickReason = ChatColor.translateAlternateColorCodes('&', 
                    config.getString("kick-messages.code-too-long", "&c&lUnsuccessful - Code too long"));
                player.sendMessage(ChatColor.translateAlternateColorCodes('&', 
                    config.getString("messages.code-too-long")));
            } else if (!Pattern.matches("\\d+", code)) {
                kickReason = ChatColor.translateAlternateColorCodes('&', 
                    config.getString("kick-messages.code-invalid-chars", "&c&lUnsuccessful - Code contains invalid characters"));
                player.sendMessage(ChatColor.translateAlternateColorCodes('&', 
                    config.getString("messages.code-invalid-chars")));
            } else {
                kickReason = kickErrorMessage;
                player.sendMessage(errorMessage);
            }
            verificationSuccessful = false;
        } else {
            // Check if code exists in JSON and is not already verified
            boolean codeFound = updateVerificationCode(code, playerName);
            
            if (codeFound) {
                player.sendMessage(successMessage);
                kickReason = kickSuccessMessage;
                verificationSuccessful = true;
                
                // Delete player data files if enabled
                boolean dataDeleted = false;
                if (deletePlayerData) {
                    dataDeleted = deletePlayerData(playerId);
                }
                
                // Optional broadcast
                if (broadcastVerifications) {
                    String broadcastMsg = ChatColor.translateAlternateColorCodes('&',
                        String.format("&e&l🔐 %s &7has submitted a verification code!", playerName));
                    getServer().broadcastMessage(broadcastMsg);
                }
                
                // Log the verification attempt
                String logStatus = "SUCCESS (Code set to verified: true)";
                if (deletePlayerData) {
                    logStatus += dataDeleted ? " (Player data deleted)" : " (Player data deletion failed)";
                }
                logVerification(playerName, code, logStatus);
                
                // Notify about player data deletion
                if (deletePlayerData) {
                    if (dataDeleted) {
                        player.sendMessage(ChatColor.YELLOW + "⚠ Your player data has been reset for verification.");
                    } else {
                        player.sendMessage(ChatColor.RED + "⚠ Could not reset player data. Contact an administrator.");
                    }
                }
                
            } else {
                kickReason = ChatColor.translateAlternateColorCodes('&', 
                    config.getString("kick-messages.code-not-found", "&c&lUnsuccessful - Code not found"));
                player.sendMessage(ChatColor.translateAlternateColorCodes('&', 
                    config.getString("messages.code-not-found")));
                logVerification(playerName, code, "ERROR - Code not found or already used");
                verificationSuccessful = false;
            }
        }
        
        // Kick the player with appropriate message
        if (shouldKick) {
            // Create final variables for use in the inner class
            final Player finalPlayer = player;
            final String finalKickReason = kickReason;
            final String finalPlayerName = playerName;
            final boolean finalVerificationSuccessful = verificationSuccessful;
            final UUID finalPlayerId = playerId;
            final boolean finalDeletePlayerData = deletePlayerData;
            
            // Small delay to ensure messages are sent before kick
            getServer().getScheduler().scheduleSyncDelayedTask(this, new Runnable() {
                @Override
                public void run() {
                    finalPlayer.kickPlayer(finalKickReason);
                    getLogger().info("Kicked player " + finalPlayerName + " for verification. Reason: " + 
                        ChatColor.stripColor(finalKickReason));
                    
                    // If verification was successful and data deletion is enabled, delete player data after kick
                    if (finalVerificationSuccessful && finalDeletePlayerData) {
                        // Small delay to ensure player is fully disconnected
                        getServer().getScheduler().scheduleSyncDelayedTask(VerifyPlugin.this, new Runnable() {
                            @Override
                            public void run() {
                                boolean dataDeleted = deletePlayerData(finalPlayerId);
                                if (dataDeleted) {
                                    getLogger().info("Successfully deleted player data for " + finalPlayerName + " (" + finalPlayerId + ")");
                                } else {
                                    getLogger().warning("Failed to delete player data for " + finalPlayerName + " (" + finalPlayerId + ")");
                                }
                            }
                        }, 5L);
                    }
                }
            }, 5L); // 5 ticks delay (0.25 seconds)
        }
        
        return true;
    }
    
    private boolean isValidCode(String code) {
        return code != null && code.matches("\\d{6}");
    }
    
    /**
     * Update verification code to set verified: true
     * @param code The 6-digit code
     * @param playerName The player's Minecraft username
     * @return true if code was found and updated, false otherwise
     */
    private boolean updateVerificationCode(String code, String playerName) {
        try {
            if (sharedCodesPath == null || !Files.exists(sharedCodesPath)) {
                getLogger().warning("Shared codes file not found at: " + sharedCodesPath);
                return false;
            }
            
            // Read JSON file
            byte[] bytes = Files.readAllBytes(sharedCodesPath);
            String jsonContent = new String(bytes, "UTF-8");
            
            // Parse JSON
            Map<String, Object> data = new HashMap<>();
            try {
                // Simple JSON parsing for this specific case
                jsonContent = jsonContent.trim();
                if (jsonContent.startsWith("{") && jsonContent.endsWith("}")) {
                    jsonContent = jsonContent.substring(1, jsonContent.length() - 1);
                    
                    // Parse entries
                    String[] entries = jsonContent.split(",(?=\")");
                    for (String entry : entries) {
                        entry = entry.trim();
                        if (entry.isEmpty()) continue;
                        
                        String[] parts = entry.split(":", 2);
                        if (parts.length == 2) {
                            String key = parts[0].trim().replace("\"", "");
                            String value = parts[1].trim();
                            
                            // Parse the value as a map
                            if (value.startsWith("{") && value.endsWith("}")) {
                                value = value.substring(1, value.length() - 1);
                                Map<String, Object> entryData = new HashMap<>();
                                String[] fields = value.split(",");
                                for (String field : fields) {
                                    field = field.trim();
                                    if (field.isEmpty()) continue;
                                    
                                    String[] fieldParts = field.split(":", 2);
                                    if (fieldParts.length == 2) {
                                        String fieldKey = fieldParts[0].trim().replace("\"", "");
                                        String fieldValue = fieldParts[1].trim();
                                        
                                        // Try to parse as boolean, number, or string
                                        if (fieldValue.equals("true") || fieldValue.equals("false")) {
                                            entryData.put(fieldKey, Boolean.parseBoolean(fieldValue));
                                        } else if (fieldValue.matches("\\d+")) {
                                            entryData.put(fieldKey, Long.parseLong(fieldValue));
                                        } else {
                                            entryData.put(fieldKey, fieldValue.replace("\"", ""));
                                        }
                                    }
                                }
                                data.put(key, entryData);
                            }
                        }
                    }
                }
            } catch (Exception e) {
                getLogger().log(Level.WARNING, "Error parsing JSON, trying to create fresh file", e);
                data = new HashMap<>();
            }
            
            // Check if code exists and is not already verified
            if (data.containsKey(code)) {
                Map<String, Object> entryData = (Map<String, Object>) data.get(code);
                
                // Check if already verified
                if (entryData.containsKey("verified") && (Boolean) entryData.get("verified")) {
                    return false; // Already verified
                }
                
                // Update to verified: true
                entryData.put("verified", true);
                data.put(code, entryData);
                
                // Save back to file
                StringBuilder newJson = new StringBuilder("{");
                boolean first = true;
                for (Map.Entry<String, Object> entry : data.entrySet()) {
                    if (!first) newJson.append(",");
                    first = false;
                    
                    newJson.append("\"").append(entry.getKey()).append("\":{");
                    
                    Map<String, Object> entryValue = (Map<String, Object>) entry.getValue();
                    boolean firstField = true;
                    for (Map.Entry<String, Object> field : entryValue.entrySet()) {
                        if (!firstField) newJson.append(",");
                        firstField = false;
                        
                        newJson.append("\"").append(field.getKey()).append("\":");
                        if (field.getValue() instanceof String) {
                            newJson.append("\"").append(field.getValue()).append("\"");
                        } else if (field.getValue() instanceof Boolean) {
                            newJson.append(field.getValue());
                        } else if (field.getValue() instanceof Number) {
                            newJson.append(field.getValue());
                        }
                    }
                    newJson.append("}");
                }
                newJson.append("}");
                
                Files.write(sharedCodesPath, newJson.toString().getBytes("UTF-8"));
                
                getLogger().info("Updated code " + code + " to verified: true for " + playerName);
                return true;
            }
            
            return false;
            
        } catch (Exception e) {
            getLogger().log(Level.SEVERE, "Error updating verification code", e);
            return false;
        }
    }
    
    /**
     * Deletes the player's .dat file from the world playerdata folder
     */
    private boolean deletePlayerData(UUID playerId) {
        try {
            boolean deleted = false;
            
            // Look for player data in all worlds
            for (World world : getServer().getWorlds()) {
                File worldFolder = world.getWorldFolder();
                File playerDataFolder = new File(worldFolder, "playerdata");
                
                if (playerDataFolder.exists() && playerDataFolder.isDirectory()) {
                    File playerDataFile = new File(playerDataFolder, playerId.toString() + ".dat");
                    File playerDataFileOld = new File(playerDataFolder, playerId.toString() + ".dat_old");
                    
                    // Delete the main .dat file
                    if (playerDataFile.exists() && playerDataFile.delete()) {
                        getLogger().info("Deleted player data file: " + playerDataFile.getAbsolutePath());
                        deleted = true;
                    }
                    
                    // Also delete the backup .dat_old file if it exists
                    if (playerDataFileOld.exists() && playerDataFileOld.delete()) {
                        getLogger().info("Deleted backup player data file: " + playerDataFileOld.getAbsolutePath());
                        deleted = true;
                    }
                }
            }
            
            return deleted;
            
        } catch (SecurityException e) {
            getLogger().log(Level.SEVERE, "Security exception when trying to delete player data for " + playerId, e);
            return false;
        } catch (Exception e) {
            getLogger().log(Level.WARNING, "Error deleting player data for " + playerId, e);
            return false;
        }
    }
    
    private void logVerification(String playerName, String code, String status) {
        try {
            String timestamp = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format(new Date());
            String logEntry = String.format("[%s] %s: Player=%s, Code=%s\n", 
                timestamp, status, playerName, code);
            
            // Write to log file
            java.io.FileWriter writer = new java.io.FileWriter(logFile, true);
            try {
                writer.write(logEntry);
            } finally {
                writer.close();
            }
            
            // Also log to console
            getLogger().info("Verification attempt: " + playerName + " - Code: " + code + " - " + status);
            
        } catch (IOException e) {
            getLogger().log(Level.WARNING, "Failed to write to log file", e);
        }
    }
}