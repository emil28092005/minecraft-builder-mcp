package io.github.minecraftbuilder.terrainworld;

import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.configuration.ConfigurationSection;
import java.util.function.IntSupplier;

/** Explicit player feet position; never derived from a roof or containment heightmap. */
record LobbySpawn(double x, double y, double z, float yaw, float pitch) {
    LobbySpawn {
        if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)
            || !Float.isFinite(yaw) || !Float.isFinite(pitch))
            throw new IllegalArgumentException("Spawn coordinates and angles must be finite");
        if (Math.abs(x) >= 30_000_000 || Math.abs(z) >= 30_000_000)
            throw new IllegalArgumentException("Spawn coordinates must be inside Minecraft's world limits");
        if (pitch < -90 || pitch > 90) throw new IllegalArgumentException("Spawn pitch must be between -90 and 90");
    }

    static LobbySpawn fromConfig(ConfigurationSection config, IntSupplier fallbackY) {
        if (!config.contains("spawn")) return new LobbySpawn(.5, fallbackY.getAsInt(), .5, 180, 0);
        ConfigurationSection spawn = config.getConfigurationSection("spawn");
        if (spawn == null) throw new IllegalArgumentException("Spawn must be a section with numeric x, y and z");
        return new LobbySpawn(number(spawn, "x"), number(spawn, "y"), number(spawn, "z"),
            (float) (spawn.contains("yaw") ? number(spawn, "yaw") : 180),
            (float) (spawn.contains("pitch") ? number(spawn, "pitch") : 0));
    }

    private static double number(ConfigurationSection section, String key) {
        if (!(section.get(key) instanceof Number value))
            throw new IllegalArgumentException("Spawn " + key + " must be numeric");
        return value.doubleValue();
    }

    void requireHeight(int minY, int maxY) {
        if (y < minY || y >= maxY) throw new IllegalArgumentException("Spawn Y must be inside world height bounds");
    }

    Location location(World world) {
        requireHeight(world.getMinHeight(), world.getMaxHeight());
        return new Location(world, x, y, z, yaw, pitch);
    }
}
