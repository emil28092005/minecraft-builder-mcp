package io.github.minecraftbuilder.core;

import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class RecipeCompilerTest {
    private static Map<BlockPos, String> compile(String operations, int limit) {
        return RecipeCompiler.compile(JsonParser.parseString("{\"version\":1,\"operations\":" + operations + "}").getAsJsonObject(), limit);
    }
    @Test void hollowBoxHasFacesAndNoInterior() {
        var blocks = compile("""
            [{"type":"box","min":{"x":0,"y":0,"z":0},"max":{"x":2,"y":2,"z":2},"block":"minecraft:stone","hollow":true}]
            """, 100);
        assertEquals(26, blocks.size()); assertFalse(blocks.containsKey(new BlockPos(1, 1, 1)));
    }
    @Test void repeatUsesOffsetsAndLaterOperationsWinDeterministically() {
        String json = """
            [{"type":"repeat","count":3,"offset":{"x":2,"y":0,"z":0},"operations":[
              {"type":"line","from":{"x":0,"y":0,"z":0},"to":{"x":1,"y":0,"z":0},"block":"minecraft:stone"}
            ]},{"type":"box","min":{"x":2,"y":0,"z":0},"max":{"x":2,"y":0,"z":0},"block":"minecraft:gold_block"}]
            """;
        var blocks = compile(json, 20); assertEquals(6, blocks.size());
        assertEquals("minecraft:gold_block", blocks.get(new BlockPos(2, 0, 0))); assertEquals(blocks, compile(json, 20));
    }
    @Test void descendingDiagonalIncludesExactEndpoints() {
        var blocks = compile("""
            [{"type":"line","from":{"x":3,"y":3,"z":3},"to":{"x":-2,"y":-2,"z":-2},"block":"minecraft:stone"}]
            """, 10);
        assertEquals(6, blocks.size()); assertTrue(blocks.containsKey(new BlockPos(-2, -2, -2)));
        assertTrue(blocks.containsKey(new BlockPos(3, 3, 3)));
    }
    @Test void cylinderUsesBottomCenterAndOpenShell() {
        var solid = compile("""
            [{"type":"cylinder","center":{"x":0,"y":3,"z":0},"radius":1,"height":2,"block":"minecraft:stone"}]
            """, 20);
        assertEquals(10, solid.size()); assertTrue(solid.containsKey(new BlockPos(0, 4, 0)));
        var hollow = compile("""
            [{"type":"cylinder","center":{"x":0,"y":3,"z":0},"radius":1,"height":2,"block":"minecraft:stone","hollow":true}]
            """, 20);
        assertEquals(8, hollow.size()); assertFalse(hollow.containsKey(new BlockPos(0, 3, 0)));
    }
    @Test void boundsAndScanBudgetRejectHugeOrOverlappingRecipes() {
        assertThrows(IllegalArgumentException.class, () -> compile("""
            [{"type":"box","min":{"x":0,"y":0,"z":0},"max":{"x":1000,"y":1000,"z":1000},"block":"minecraft:stone"}]
            """, 100));
        assertThrows(IllegalArgumentException.class, () -> compile("""
            [{"type":"repeat","count":100,"offset":{"x":0,"y":0,"z":0},"operations":[
            {"type":"box","min":{"x":0,"y":0,"z":0},"max":{"x":0,"y":0,"z":0},"block":"minecraft:stone"}]}]
            """, 1));
        assertThrows(IllegalArgumentException.class, () -> compile("""
            [{"type":"line","from":{"x":0,"y":0,"z":0},"to":{"x":2,"y":0,"z":0},"block":"minecraft:stone"}]
            """, 2));
    }
    @Test void rejectsFractionalCoordinatesUnknownFieldsAndCoordinateOverflow() {
        assertThrows(IllegalArgumentException.class, () -> compile("""
            [{"type":"line","from":{"x":0.5,"y":0,"z":0},"to":{"x":1,"y":0,"z":0},"block":"minecraft:stone"}]
            """, 20));
        assertThrows(IllegalArgumentException.class, () -> compile("""
            [{"type":"repeat","count":1,"offset":{"x":0,"y":0,"z":0},"operations":[],"script":"shell"}]
            """, 20));
        assertThrows(ArithmeticException.class, () -> compile("""
            [{"type":"repeat","count":2,"offset":{"x":1,"y":0,"z":0},"operations":[
            {"type":"box","min":{"x":2147483647,"y":0,"z":0},"max":{"x":2147483647,"y":0,"z":0},"block":"minecraft:stone"}]}]
            """, 20));
    }
}
