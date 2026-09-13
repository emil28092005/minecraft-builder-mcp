package io.github.minecraftbuilder.terrainworld;

import com.google.gson.*;
import org.bukkit.*;
import org.bukkit.command.*;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;
import java.nio.file.*;
import java.util.*;

/** Optional bootstrap for a separate, operator-selected world. */
public final class TerrainWorldPlugin extends JavaPlugin {
    private RecipeGenerator generator;
    private World world;
    private Location lobbySpawn;
    private SurfaceMapCapture surfaceMaps;
    private boolean generating;
    private int completed, total, mismatches, minHeight, maxHeight;
    private long columns, wetColumns, started;

    @Override public void onEnable() {
        try {
            saveDefaultConfig();
            if (!getConfig().getBoolean("enabled", false)) return;
            String name = getConfig().getString("world", "shacraft_lobby");
            if (!name.matches("[a-z0-9_]{1,48}")) throw new IllegalArgumentException("Invalid world name");
            // Paper 26.2 stores dimensions beneath the primary save, not server/name.
            World overworld = Objects.requireNonNull(Bukkit.getWorld(NamespacedKey.minecraft("overworld")));
            Path folder = overworld.getWorldPath().resolveSibling(name);
            Path recipeFile = getDataFolder().toPath().resolve(getConfig().getString("recipe", "terrain.json")).normalize();
            if (!recipeFile.startsWith(getDataFolder().toPath())) throw new IllegalArgumentException("Recipe must be inside plugin data folder");
            JsonObject source = JsonParser.parseString(Files.readString(recipeFile)).getAsJsonObject();
            Integer waterLevel = getConfig().isInt("water-level") ? getConfig().getInt("water-level") : null;
            String profile = getConfig().getString("terrain-profile", "recipe-v1");
            generator = new RecipeGenerator(source, waterLevel, profile);
            LobbySpawn spawn = LobbySpawn.fromConfig(getConfig(), () -> generator.height(0, 0) + 1);
            Path manifest = getDataFolder().toPath().resolve(name + ".generation.json");
            String identity = generator.identity();
            if (Files.exists(manifest)) {
                var saved = JsonParser.parseString(Files.readString(manifest)).getAsJsonObject();
                if (!saved.get("identity").getAsString().equals(identity))
                    throw new IllegalStateException("Recipe changed: use a new world name to avoid seams");
            } else {
                if (Files.exists(folder)) throw new IllegalStateException("Refusing to adopt an existing world without its generation manifest");
                JsonObject saved = new JsonObject(); saved.addProperty("identity", identity); saved.add("recipe", source);
                if (waterLevel != null) saved.addProperty("water_level", waterLevel);
                saved.addProperty("terrain_profile", profile);
                Files.writeString(manifest, new GsonBuilder().setPrettyPrinting().create().toJson(saved), StandardOpenOption.CREATE_NEW);
            }
            if (Bukkit.getWorld(name) != null) throw new IllegalStateException("World already loaded by another provider");
            world = new WorldCreator(NamespacedKey.minecraft(name)).seed(source.get("seed").getAsLong())
                .generator(generator).generateStructures(false).createWorld();
            if (world == null) throw new IllegalStateException("World creation failed");
            surfaceMaps = new SurfaceMapCapture(this, world);
            var bounds = generator.recipe.bounds();
            world.getWorldBorder().setCenter((bounds.min().x() + bounds.max().x() + 1) / 2.0,
                (bounds.min().z() + bounds.max().z() + 1) / 2.0);
            int footprint = Math.max(generator.recipe.width(), generator.recipe.length());
            world.getWorldBorder().setSize(Math.max(footprint, getConfig().getInt("border-size", footprint)));
            lobbySpawn = spawn.location(world);
            if (getConfig().contains("spawn")) world.setSpawnLocation(lobbySpawn);
            else world.setSpawnLocation(0, lobbySpawn.getBlockY(), 0);
            getServer().getPluginManager().registerEvents(new LobbyRespawn(world,
                getConfig().contains("spawn") ? lobbySpawn : null), this);
            world.setTime(6000); world.setStorm(false); world.setThundering(false);
            world.setGameRule(GameRule.DO_DAYLIGHT_CYCLE, false);
            world.setGameRule(GameRule.DO_WEATHER_CYCLE, false);
            world.setGameRule(GameRule.DO_MOB_SPAWNING, false);
            Objects.requireNonNull(getCommand("lobby")).setExecutor(this::command);
            if (getConfig().getBoolean("station.enabled", false)) {
                StationLift lift = new StationLift(this, world);
                getServer().getPluginManager().registerEvents(lift, this);
                Objects.requireNonNull(getCommand("station")).setExecutor(lift);
                StationLabels.install(this, world);
            }
            getLogger().info("Terrain world ready: " + name + "; recipe=" + generator.recipe.id());
        } catch (Exception e) {
            getLogger().severe("Terrain world disabled: " + e.getMessage());
            getServer().getPluginManager().disablePlugin(this);
        }
    }

    private boolean command(CommandSender sender, Command command, String label, String[] args) {
        if (world == null) { sender.sendMessage("Terrain world unavailable"); return true; }
        if (args.length == 1 && args[0].equals("status")) {
            sender.sendMessage("Shacraft: " + completed + "/" + total + " chunks; active=" + generating + "; mismatched columns=" + mismatches + "; " + surfaceMaps.status());
        } else if (args.length == 2 && args[0].equals("map")) {
            if (!(sender instanceof ConsoleCommandSender)) { sender.sendMessage("Surface map export is a server-console command"); return true; }
            if (generating) { sender.sendMessage("Wait for terrain generation before capturing a map"); return true; }
            try {
                var b = generator.recipe.bounds();
                surfaceMaps.start(args[1], b.min().x(), b.min().z(), b.max().x(), b.max().z());
                sender.sendMessage("Surface map started; inspect lobby status. Output: plugins/ShacraftTerrain/maps/" + args[1] + ".{json,png}");
            } catch (Exception e) { sender.sendMessage("Cannot capture map: " + e.getMessage()); }
        } else if (args.length == 1 && args[0].equals("generate") && sender instanceof ConsoleCommandSender) {
            if (generating) { sender.sendMessage("Generation already active"); return true; }
            if (surfaceMaps.active()) { sender.sendMessage("Wait for the active surface map capture"); return true; }
            completed = 0; columns = 0; wetColumns = 0; mismatches = 0;
            minHeight = Integer.MAX_VALUE; maxHeight = Integer.MIN_VALUE;
            var b = generator.recipe.bounds();
            total = (Math.floorDiv(b.max().x(), 16) - Math.floorDiv(b.min().x(), 16) + 1)
                * (Math.floorDiv(b.max().z(), 16) - Math.floorDiv(b.min().z(), 16) + 1);
            started = System.currentTimeMillis(); generating = true; next();
        } else {
            Player player = sender instanceof Player p ? p : args.length == 1 ? Bukkit.getPlayerExact(args[0]) : null;
            if (player == null) { sender.sendMessage("/lobby [status] or console: lobby <player> | generate | map <name>"); return true; }
            player.teleportAsync(lobbySpawn.clone());
        }
        return true;
    }

    private void next() {
        if (!isEnabled() || !generating) return;
        if (completed == total) {
            generating = false; world.save();
            var report = Map.of("world", world.getName(), "recipe_id", generator.recipe.id(), "chunks", total,
                "verified_columns", columns, "water_columns", wetColumns, "mismatches", mismatches, "min_surface_y", minHeight,
                "max_surface_y", maxHeight, "elapsed_ms", System.currentTimeMillis() - started);
            try { Files.writeString(getDataFolder().toPath().resolve("generation-report.json"), new GsonBuilder().setPrettyPrinting().create().toJson(report)); }
            catch (Exception e) { getLogger().severe("Cannot save generation report: " + e.getMessage()); }
            getLogger().info("Terrain generation complete: " + report); return;
        }
        var b = generator.recipe.bounds();
        int nx = Math.floorDiv(b.max().x(), 16) - Math.floorDiv(b.min().x(), 16) + 1;
        int cx = Math.floorDiv(b.min().x(), 16) + completed % nx;
        int cz = Math.floorDiv(b.min().z(), 16) + completed / nx;
        world.getChunkAtAsync(cx, cz, true).whenComplete((chunk, error) -> {
            if (!isEnabled()) return;
            Bukkit.getScheduler().runTask(this, () -> {
                if (error != null) { generating = false; getLogger().severe("Generation stopped: " + error.getMessage()); return; }
                for (int x = 0; x < 16; x++) for (int z = 0; z < 16; z++) {
                    int wx = cx * 16 + x, wz = cz * 16 + z;
                    if (wx < b.min().x() || wx > b.max().x() || wz < b.min().z() || wz > b.max().z()) continue;
                    int expected = generator.visibleHeight(wx, wz);
                    int actual = world.getHighestBlockYAt(wx, wz, HeightMap.WORLD_SURFACE);
                    int ground = generator.height(wx, wz);
                    boolean wet = expected > ground;
                    boolean mismatch = actual != expected || world.getBlockAt(wx, ground, wz).getType() != generator.surfaceMaterial(wx,wz);
                    if (wet) {
                        wetColumns++;
                        for (int y = ground + 1; y <= expected; y++)
                            if (world.getBlockAt(wx, y, wz).getType() != Material.WATER) { mismatch = true; break; }
                        if (world.getBlockAt(wx, ground, wz).getType().isAir()) mismatch = true;
                    }
                    if (mismatch) mismatches++;
                    minHeight = Math.min(minHeight, actual); maxHeight = Math.max(maxHeight, actual); columns++;
                }
                completed++;
                if (completed % 128 == 0) getLogger().info("Terrain progress " + completed + "/" + total);
                Bukkit.getScheduler().runTaskLater(this, this::next, 1L);
            });
        });
    }
}
