package io.github.minecraftbuilder.terrainworld;

import org.bukkit.configuration.MemoryConfiguration;
import org.junit.jupiter.api.Test;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class LobbySpawnTest {
    @Test void absentSectionKeepsOriginalRecipeFallback() {
        assertEquals(new LobbySpawn(.5, 89, .5, 180, 0),
            LobbySpawn.fromConfig(new MemoryConfiguration(), () -> 89));
    }

    @Test void explicitPlazaCoordinatesDoNotConsultGeneratedTerrainOrRoof() {
        MemoryConfiguration config = configured();
        config.set("spawn.yaw", 137.5);
        config.set("spawn.pitch", -12.5);
        assertEquals(new LobbySpawn(.5, 96, 43.5, 137.5f, -12.5f),
            LobbySpawn.fromConfig(config, () -> { throw new AssertionError("Fallback must not be read"); }));
        config.set("spawn.yaw", null);
        config.set("spawn.pitch", null);
        assertEquals(new LobbySpawn(.5, 96, 43.5, 180, 0), LobbySpawn.fromConfig(config, () -> 200));
    }

    @Test void incompleteNonNumericAndNonFiniteSettingsFailInsteadOfFallingBack() {
        MemoryConfiguration config = configured();
        config.set("spawn.z", null);
        assertThrows(IllegalArgumentException.class, () -> LobbySpawn.fromConfig(config, () -> 89));
        for (Object value : new Object[]{"96", Double.NaN, Double.POSITIVE_INFINITY}) {
            MemoryConfiguration invalid = configured(); invalid.set("spawn.y", value);
            assertThrows(IllegalArgumentException.class, () -> LobbySpawn.fromConfig(invalid, () -> 89));
        }
        config.set("spawn", "invalid");
        assertThrows(IllegalArgumentException.class, () -> LobbySpawn.fromConfig(config, () -> 89));
    }

    @Test void worldAndViewLimitsAreChecked() {
        assertThrows(IllegalArgumentException.class, () -> new LobbySpawn(30_000_000, 96, 0, 180, 0));
        assertThrows(IllegalArgumentException.class, () -> new LobbySpawn(0, 96, 0, Float.POSITIVE_INFINITY, 0));
        assertThrows(IllegalArgumentException.class, () -> new LobbySpawn(0, 96, 0, 180, 91));
        assertThrows(IllegalArgumentException.class, () -> new LobbySpawn(0, -65, 0, 180, 0).requireHeight(-64, 320));
        assertThrows(IllegalArgumentException.class, () -> new LobbySpawn(0, 320, 0, 180, 0).requireHeight(-64, 320));
        assertDoesNotThrow(() -> new LobbySpawn(0, 96, 0, 180, 0).requireHeight(-64, 320));
    }

    private static MemoryConfiguration configured() {
        MemoryConfiguration config = new MemoryConfiguration();
        config.createSection("spawn", Map.of("x", .5, "y", 96, "z", 43.5, "yaw", 180, "pitch", 0));
        return config;
    }
}
