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

import java.io.File;
import java.io.IOException;
import java.io.FileWriter;
import java.io.FileReader;
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
    private File codesFile;
    private File logFile;
    
    // Cache for pending verifications
    private Map<UUID, String> pendingVerifications = new HashMap<UUID, String>();
    
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
        
        // Create necessary files
        codesFile = new File(getDataFolder(), "verification_codes.json");
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
        config.addDefault("messages.success", "&a&l✅ Verification code sent! Check Discord for confirmation.");
        config.addDefault("messages.error", "&c&l❌ Invalid code! Code must be 6 digits.");
        config.addDefault("messages.usage", "&e&lUsage: /verify <6-digit-code>");
        config.addDefault("messages.code-too-short", "&c&l❌ Code too short! Must be 6 digits.");
        config.addDefault("messages.code-too-long", "&c&l❌ Code too long! Must be 6 digits.");
        config.addDefault("messages.code-invalid-chars", "&c&l❌ Code must contain only numbers!");
        config.addDefault("broadcast-verifications", false);
        config.addDefault("require-online", false);
        config.addDefault("shared-codes-path", "");
        config.addDefault("kick-messages.success", "&a&lSuccessful - Verified");
        config.addDefault("kick-messages.error", "&c&lUnsuccessful - Invalid verification code");
        config.addDefault("kick-messages.code-too-short", "&c&lUnsuccessful - Code too short");
        config.addDefault("kick-messages.code-too-long", "&c&lUnsuccessful - Code too long");
        config.addDefault("kick-messages.code-invalid-chars", "&c&lUnsuccessful - Code contains invalid characters");
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
        kickSuccessMessage = ChatColor.translateAlternateColorCodes('&', config.getString("kick-messages.success", "&a&lSuccessful - Verified"));
        kickErrorMessage = ChatColor.translateAlternateColorCodes('&', config.getString("kick-messages.error", "&c&lUnsuccessful - Invalid verification code"));
        
        String sharedPath = config.getString("shared-codes-path", "");
        if (!sharedPath.isEmpty()) {
            sharedCodesPath = Paths.get(sharedPath);
        }
    }
    
    private void findSharedCodesFile() {
        // Try to automatically find the verification_codes.json file
        File serverRoot = new File(".");
        File[] possibleLocations = {
            new File(serverRoot, "verification_codes.json"),
            new File(serverRoot.getParentFile(), "verification_codes.json"),
            new File("plugins/DiscordBot/verification_codes.json"),
            new File("plugins/verification_codes.json")
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
    }
    
    @EventHandler
    public void onPlayerJoin(PlayerJoinEvent event) {
        Player player = event.getPlayer();
        UUID playerId = player.getUniqueId();
        
        // Check if player has a pending verification
        if (pendingVerifications.containsKey(playerId)) {
            String code = pendingVerifications.get(playerId);
            player.sendMessage(ChatColor.YELLOW + "⚠ You have a pending verification with code: " + 
                             ChatColor.GREEN + code);
            player.sendMessage(ChatColor.YELLOW + "Type " + ChatColor.GREEN + "/verify " + code + 
                             ChatColor.YELLOW + " to complete verification.");
        }
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
            // Store in pending cache
            pendingVerifications.put(playerId, code);
            
            // Save the code to the shared JSON file
            boolean success = saveVerificationCode(code, playerName);
            
            if (success) {
                player.sendMessage(successMessage);
                kickReason = kickSuccessMessage;
                verificationSuccessful = true;
                
                // Optional broadcast
                if (broadcastVerifications) {
                    String broadcastMsg = ChatColor.translateAlternateColorCodes('&',
                        String.format("&e&l🔐 %s &7has submitted a verification code!", playerName));
                    getServer().broadcastMessage(broadcastMsg);
                }
                
                // Log the verification attempt
                logVerification(playerName, code, "SUCCESS");
                
                // Send instruction about next steps
                player.sendMessage(ChatColor.GRAY + "The Discord bot will now verify your guild membership...");
                player.sendMessage(ChatColor.GRAY + "Check Discord for confirmation!");
                
            } else {
                kickReason = ChatColor.translateAlternateColorCodes('&', 
                    config.getString("kick-messages.save-error", "&c&lUnsuccessful - System error, please contact admin"));
                player.sendMessage(ChatColor.RED + "❌ Error saving verification code! Please contact an admin.");
                logVerification(playerName, code, "ERROR - Failed to save");
                verificationSuccessful = false;
            }
        }
        
        // Kick the player with appropriate message
        if (shouldKick) {
            // Small delay to ensure messages are sent before kick
            getServer().getScheduler().scheduleSyncDelayedTask(this, new Runnable() {
                @Override
                public void run() {
                    player.kickPlayer(kickReason);
                    getLogger().info("Kicked player " + playerName + " for verification. Reason: " + 
                        ChatColor.stripColor(kickReason));
                }
            }, 5L); // 5 ticks delay (0.25 seconds)
        }
        
        return true;
    }
    
    private boolean isValidCode(String code) {
        return code != null && code.matches("\\d{6}");
    }
    
    private boolean saveVerificationCode(String code, String playerName) {
        try {
            // First try to use the shared path if configured
            if (sharedCodesPath != null && Files.exists(sharedCodesPath)) {
                return saveToSharedJsonFile(code, playerName);
            }
            
            // Otherwise save to local JSON file
            return saveToLocalJsonFile(code, playerName);
            
        } catch (Exception e) {
            getLogger().log(Level.SEVERE, "Error saving verification code", e);
            return false;
        }
    }
    
    private boolean saveToSharedJsonFile(String code, String playerName) {
        try {
            // Read existing JSON content
            String jsonContent = "";
            if (Files.exists(sharedCodesPath)) {
                byte[] bytes = Files.readAllBytes(sharedCodesPath);
                jsonContent = new String(bytes, "UTF-8");
            }
            
            // Parse JSON
            long timestamp = System.currentTimeMillis() / 1000L;
            
            String newEntry = String.format(
                "\"%s\": {\"minecraft_username\": \"%s\", \"timestamp\": %d}",
                code, playerName, timestamp
            );
            
            // Remove trailing } if exists
            jsonContent = jsonContent.trim();
            if (jsonContent.startsWith("{") && jsonContent.endsWith("}")) {
                jsonContent = jsonContent.substring(1, jsonContent.length() - 1);
            }
            
            // Add comma if not empty
            if (!jsonContent.isEmpty() && !jsonContent.endsWith(",")) {
                jsonContent += ",";
            }
            
            // Construct new JSON
            String newJson = "{" + jsonContent + newEntry + "}";
            
            // Write back to file
            Files.write(sharedCodesPath, newJson.getBytes("UTF-8"));
            
            getLogger().info("Saved verification code " + code + " for " + playerName + " to shared file");
            return true;
            
        } catch (Exception e) {
            getLogger().log(Level.SEVERE, "Error saving to shared JSON file", e);
            return false;
        }
    }
    
    private boolean saveToLocalJsonFile(String code, String playerName) {
        try {
            // Create codes file if it doesn't exist
            if (!codesFile.exists()) {
                codesFile.createNewFile();
                FileWriter writer = new FileWriter(codesFile);
                try {
                    writer.write("{}");
                } finally {
                    writer.close();
                }
            }
            
            // Read existing JSON
            String jsonContent;
            FileReader reader = new FileReader(codesFile);
            try {
                StringBuilder content = new StringBuilder();
                int character;
                while ((character = reader.read()) != -1) {
                    content.append((char) character);
                }
                jsonContent = content.toString();
            } finally {
                reader.close();
            }
            
            // Simple JSON manipulation
            long timestamp = System.currentTimeMillis() / 1000L;
            
            String newEntry = String.format(
                "\"%s\": {\"minecraft_username\": \"%s\", \"timestamp\": %d}",
                code, playerName, timestamp
            );
            
            // Remove trailing } if exists
            jsonContent = jsonContent.trim();
            if (jsonContent.startsWith("{") && jsonContent.endsWith("}")) {
                jsonContent = jsonContent.substring(1, jsonContent.length() - 1);
            }
            
            // Add comma if not empty
            if (!jsonContent.isEmpty() && !jsonContent.endsWith(",")) {
                jsonContent += ",";
            }
            
            // Construct new JSON
            String newJson = "{" + jsonContent + newEntry + "}";
            
            // Write back to file
            FileWriter writer = new FileWriter(codesFile);
            try {
                writer.write(newJson);
            } finally {
                writer.close();
            }
            
            getLogger().info("Saved verification code " + code + " for " + playerName + " to local file");
            return true;
            
        } catch (Exception e) {
            getLogger().log(Level.SEVERE, "Error saving verification code", e);
            return false;
        }
    }
    
    private void logVerification(String playerName, String code, String status) {
        try {
            String timestamp = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format(new Date());
            String logEntry = String.format("[%s] %s: Player=%s, Code=%s\n", 
                timestamp, status, playerName, code);
            
            // Write to log file
            FileWriter writer = new FileWriter(logFile, true);
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