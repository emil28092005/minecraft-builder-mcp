package io.github.minecraftbuilder.paper;

import org.bukkit.Material;
import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.Waterlogged;
import org.bukkit.block.data.type.Leaves;
import org.junit.jupiter.api.Test;
import java.lang.reflect.Proxy;
import static org.junit.jupiter.api.Assertions.*;

/** Parsed BlockData stubs test policy; the live registry integration test validates item rejection. */
final class BuildingWorldPolicyTest {
    private static BlockData state(Material material, Class<? extends BlockData> type,
                                   boolean waterlogged, boolean persistent) {
        return (BlockData) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type},
            (proxy, method, arguments) -> switch (method.getName()) {
                case "getMaterial" -> material;
                case "isWaterlogged" -> waterlogged;
                case "isPersistent" -> persistent;
                default -> throw new UnsupportedOperationException(method.getName());
            });
    }
    @Test void leafAndWaterloggedStatesAreNoLongerArtificiallyRestricted() {
        for (Material material : new Material[]{Material.SPRUCE_LEAVES, Material.OAK_LEAVES})
            for (boolean wet : new boolean[]{false,true})
                for (boolean persistent : new boolean[]{false,true})
                    assertTrue(BuildingWorld.supportsData(state(material, Leaves.class, wet, persistent)));
        for (Material material : new Material[]{Material.SPRUCE_FENCE, Material.CUT_SANDSTONE_SLAB,
                Material.BARRIER, Material.CHEST})
            assertTrue(BuildingWorld.supportsData(state(material, Waterlogged.class, true, true)));
    }
    @Test void fluidsGrowthAdministrativeAndBlockEntityTypesAreAccepted() {
        for (Material material : new Material[]{Material.WATER, Material.LAVA, Material.OAK_SAPLING,
                Material.PEONY, Material.CUT_COPPER, Material.STRUCTURE_VOID, Material.LIGHT,
                Material.STRUCTURE_BLOCK, Material.JIGSAW, Material.COMMAND_BLOCK,
                Material.CHAIN_COMMAND_BLOCK, Material.REPEATING_COMMAND_BLOCK, Material.TNT,
                Material.CHEST, Material.OAK_SIGN, Material.DECORATED_POT, Material.BEEHIVE,
                Material.TRIAL_SPAWNER, Material.VAULT})
            assertTrue(BuildingWorld.supportsData(state(material, BlockData.class, false, true)), material.name());
    }
    @Test void missingAndLegacyDataDoNotBypassTheParserPolicy() {
        assertFalse(BuildingWorld.supportsData(null));
        assertFalse(BuildingWorld.supportsData(state(null, BlockData.class, false, true)));
        assertFalse(BuildingWorld.supportsData(state(Material.LEGACY_STONE, BlockData.class, false, true)));
    }
}
