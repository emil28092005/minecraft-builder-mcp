package io.github.minecraftbuilder.terrainworld;

import org.bukkit.*;
import org.bukkit.plugin.java.JavaPlugin;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Instant;
import java.util.function.IntFunction;

/** One existing chunk per server tick, followed by detached asynchronous rendering. */
final class SurfaceMapCapture {
    private final JavaPlugin plugin;
    private final World world;
    private boolean active;
    private int completed, total, chunksWide;
    private String name = "none", state = "idle";
    private SurfaceMap map;
    private Instant startedAt;

    SurfaceMapCapture(JavaPlugin plugin, World world) { this.plugin = plugin; this.world = world; }
    boolean active() { return active; }
    String status() { return "map=" + name + "; map_state=" + state + "; map_chunks=" + completed + "/" + total; }
    private Path directory() { return plugin.getDataFolder().toPath().resolve("maps"); }

    record Column(int y, Material material) {}

    /** Barriers contain players, but must not hide the visible world in a surface map. */
    static Column visibleColumn(int minY, int highestY, IntFunction<Material> materialAt) {
        for (int y = Math.max(minY, highestY); y >= minY; y--) {
            Material material = materialAt.apply(y);
            if (material != Material.AIR && material != Material.CAVE_AIR
                && material != Material.VOID_AIR && material != Material.BARRIER) return new Column(y, material);
            if (y == minY) break;
        }
        // A void column has no visible surface; retain a bounded, explicit air sentinel.
        return new Column(minY, Material.AIR);
    }

    private Column visibleColumn(int x, int z) {
        return visibleColumn(world.getMinHeight(), world.getHighestBlockYAt(x, z, HeightMap.WORLD_SURFACE),
            y -> world.getBlockAt(x, y, z).getType());
    }

    void start(String name, int minX, int minZ, int maxX, int maxZ) throws IOException {
        if (active) throw new IllegalStateException("Map capture already active");
        SurfaceMap.requireUnusedName(directory(), name);
        map = new SurfaceMap(minX, minZ, maxX, maxZ);
        this.name = name; completed = 0;
        chunksWide = Math.floorDiv(maxX, 16) - Math.floorDiv(minX, 16) + 1;
        total = chunksWide * (Math.floorDiv(maxZ, 16) - Math.floorDiv(minZ, 16) + 1);
        startedAt = Instant.now(); active = true; state = "reading";
        plugin.getLogger().info("Surface map " + name + " started: " + total + " existing chunks; no terrain generation or block changes");
        next();
    }

    private void next() {
        if (!active || !plugin.isEnabled()) return;
        if (completed == total) { write(); return; }
        int cx = Math.floorDiv(map.minX, 16) + completed % chunksWide;
        int cz = Math.floorDiv(map.minZ, 16) + completed / chunksWide;
        if (!world.isChunkGenerated(cx, cz)) { fail("Chunk " + cx + "," + cz + " has not been generated"); return; }
        // generate=false: exporting a map must not extend the world.
        world.getChunkAtAsync(cx, cz, false).whenComplete((chunk, error) -> {
            if (!plugin.isEnabled()) return;
            Bukkit.getScheduler().runTask(plugin, () -> {
                if (error != null) { fail(error.getMessage()); return; }
                if (chunk == null) { fail("Existing chunk unavailable: " + cx + "," + cz); return; }
                boolean ticket = false;
                try {
                    ticket = chunk.addPluginChunkTicket(plugin);
                    for (int z = Math.max(map.minZ, cz * 16); z <= Math.min(map.maxZ, cz * 16 + 15); z++)
                        for (int x = Math.max(map.minX, cx * 16); x <= Math.min(map.maxX, cx * 16 + 15); x++) {
                            Column column = visibleColumn(x, z);
                            map.setColumn(x, z, column.y(), column.material().getKey().toString());
                        }
                    completed++;
                    if (completed % 512 == 0) plugin.getLogger().info("Surface map " + name + ": " + completed + "/" + total + " chunks");
                } catch (Exception e) { fail(e.getMessage()); return; }
                finally { if (ticket) chunk.removePluginChunkTicket(plugin); }
                // Zero-delay tasks can run again in the same scheduler heartbeat
                // when the chunk future is already complete. Require a later tick.
                Bukkit.getScheduler().runTaskLater(plugin, this::next, 1L);
            });
        });
    }

    private void write() {
        state = "writing";
        Instant finishedAt = Instant.now();
        String worldName = world.getName(), worldKey = world.getKey().toString(), worldUuid = world.getUID().toString();
        // This worker only sees the completed primitive grid, strings and output directory.
        SurfaceMap capturedMap = map;
        Path destination = directory();
        String capturedName = name;
        Instant capturedStart = startedAt;
        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                capturedMap.write(destination, capturedName, worldName, worldKey, worldUuid, capturedStart, finishedAt);
                if (!plugin.isEnabled()) return;
                Bukkit.getScheduler().runTask(plugin, () -> {
                    active = false; state = "complete"; map = null;
                    plugin.getLogger().info("Surface map complete: maps/" + capturedName + ".json and .png; "
                        + capturedMap.columns() + " observed columns; north up; chunk-sequential capture");
                });
            } catch (Exception e) {
                if (plugin.isEnabled()) Bukkit.getScheduler().runTask(plugin, () -> fail(e.getMessage()));
            }
        });
    }

    private void fail(String reason) {
        active = false; state = "failed"; map = null;
        plugin.getLogger().severe("Surface map " + name + " stopped: " + reason);
    }
}
