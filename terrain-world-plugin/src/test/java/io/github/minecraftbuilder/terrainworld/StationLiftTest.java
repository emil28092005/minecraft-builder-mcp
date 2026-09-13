package io.github.minecraftbuilder.terrainworld;

import org.junit.jupiter.api.Test;
import org.bukkit.Material;
import static org.junit.jupiter.api.Assertions.*;

class StationLiftTest {
    @Test void partialAndProtrudingSupportsCannotBeLandingFloors() {
        assertTrue(StationLift.supportsLanding(Material.WAXED_OXIDIZED_CUT_COPPER));
        assertTrue(StationLift.supportsLanding(Material.SMOOTH_SANDSTONE));
        for (Material block : new Material[]{Material.AIR,Material.SPRUCE_FENCE,Material.STONE_BRICK_WALL,
                Material.SMOOTH_STONE_SLAB,Material.STONE_BRICK_STAIRS,Material.WATER})
            assertFalse(StationLift.supportsLanding(block));
    }
    @Test void onlyCompletedStopsCanBeSelected() {
        assertEquals(99, StationLift.feetY(1));
        assertEquals(113, StationLift.feetY(2));
        for (int floor : new int[]{-1,0,3,4,100})
            assertThrows(IllegalArgumentException.class, () -> StationLift.feetY(floor));
    }

    @Test void decorativeGoldAndOtherHeightsDoNotActAsControls() {
        assertEquals(1, StationLift.selectorFloor(-6,101,-123));
        assertEquals(2, StationLift.selectorFloor(-6,115,-123));
        assertEquals(0, StationLift.selectorFloor(-5,101,-123));
        assertEquals(0, StationLift.selectorFloor(-6,101,-122));
        assertEquals(0, StationLift.selectorFloor(-6,129,-123));
    }

    @Test void controlRequiresPlayerInsideTheMatchingCabin() {
        assertTrue(StationLift.inCabin(-5.5,99,-119.5,1));
        assertTrue(StationLift.inCabin(-5.5,114,-119.5,2));
        assertFalse(StationLift.inCabin(-5.5,99,-119.5,2));
        assertFalse(StationLift.inCabin(-5.5,113,-119.5,1));
        assertFalse(StationLift.inCabin(-5.5,98.9,-119.5,1));
        assertFalse(StationLift.inCabin(-5.5,99,-117,1));
        assertFalse(StationLift.inCabin(-8.1,99,-119.5,1));
    }
}
