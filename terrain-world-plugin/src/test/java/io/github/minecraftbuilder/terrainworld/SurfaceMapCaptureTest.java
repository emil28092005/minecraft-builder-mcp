package io.github.minecraftbuilder.terrainworld;

import org.bukkit.Material;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class SurfaceMapCaptureTest {
    @Test void roofAndAirGapsDoNotHideGardenOrWater() {
        for (Material visible : List.of(Material.SPRUCE_LEAVES, Material.WATER, Material.STONE_SLAB)) {
            List<Integer> reads = new ArrayList<>();
            var column = SurfaceMapCapture.visibleColumn(-64, 122, y -> {
                reads.add(y);
                return switch (y) {
                    case 122, 121 -> Material.BARRIER;
                    case 120 -> Material.AIR;
                    case 119 -> Material.CAVE_AIR;
                    case 118 -> Material.VOID_AIR;
                    case 117 -> visible;
                    default -> throw new AssertionError("Read beneath first visible block");
                };
            });
            assertEquals(117, column.y());
            assertEquals(visible, column.material());
            assertEquals(List.of(122, 121, 120, 119, 118, 117), reads);
        }
    }

    @Test void emptyColumnHasAirSentinelAndNeverReadsBelowWorld() {
        List<Integer> reads = new ArrayList<>();
        var column = SurfaceMapCapture.visibleColumn(-64, -62, y -> {
            assertTrue(y >= -64);
            reads.add(y);
            return y == -63 ? Material.BARRIER : Material.AIR;
        });
        assertEquals(new SurfaceMapCapture.Column(-64, Material.AIR), column);
        assertEquals(List.of(-62, -63, -64), reads);
        assertEquals(new SurfaceMapCapture.Column(-64, Material.BEDROCK),
            SurfaceMapCapture.visibleColumn(-64, -65, y -> {
                assertEquals(-64, y);
                return Material.BEDROCK;
            }));
    }
}
