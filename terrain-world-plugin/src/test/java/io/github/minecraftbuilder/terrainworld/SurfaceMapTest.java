package io.github.minecraftbuilder.terrainworld;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import javax.imageio.ImageIO;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class SurfaceMapTest {
    @TempDir Path directory;

    @Test void exportedGridPreservesCoordinatesWaterAndMarkersIndependentOfCaptureOrder() throws Exception {
        SurfaceMap map = new SurfaceMap(-17, -1, -16, 0);
        map.setColumn(-16, 0, 81, "minecraft:magenta_concrete");
        map.setColumn(-17, -1, 48, "minecraft:water");
        map.setColumn(-16, -1, 65, "minecraft:stone");
        map.setColumn(-17, 0, 80, "minecraft:grass_block");
        Instant start = Instant.parse("2026-09-13T00:00:00Z"), end = start.plusSeconds(2);
        map.write(directory, "live-01", "lobby", "minecraft:lobby", "world-uuid", start, end);
        JsonObject json = JsonParser.parseString(Files.readString(directory.resolve("live-01.json"))).getAsJsonObject();
        assertEquals(-17, json.get("min_x").getAsInt());
        assertEquals(2, json.get("width").getAsInt());
        assertEquals(4, json.get("columns").getAsInt());
        assertEquals(48, json.get("min_surface_y").getAsInt());
        assertEquals(81, json.get("max_surface_y").getAsInt());
        assertEquals(start.toString(), json.get("capture_started_at").getAsString());
        assertEquals(end.toString(), json.get("capture_finished_at").getAsString());
        assertFalse(json.get("atomic_snapshot").getAsBoolean());
        assertEquals(List.of("minecraft:barrier"), json.getAsJsonArray("ignored_materials").asList()
            .stream().map(JsonElement::getAsString).toList());
        assertTrue(json.get("surface_policy").getAsString().contains("all air variants"));
        assertEquals(List.of(48, 65, 80, 81), json.getAsJsonArray("surface_y").asList().stream().map(JsonElement::getAsInt).toList());
        JsonArray palette = json.getAsJsonArray("palette"), indices = json.getAsJsonArray("material_index");
        assertEquals("minecraft:water", palette.get(indices.get(0).getAsInt()).getAsString());
        assertEquals("minecraft:magenta_concrete", palette.get(indices.get(3).getAsInt()).getAsString());
        var image = ImageIO.read(directory.resolve("live-01.png").toFile());
        assertEquals(2, image.getWidth()); assertEquals(2, image.getHeight());
        assertEquals(SurfaceMap.color("minecraft:magenta_concrete"), image.getRGB(1, 1) & 0xffffff);
    }

    @Test void incompleteOrDuplicateColumnsCannotProduceMisleadingMaps() {
        SurfaceMap map = new SurfaceMap(0, 0, 1, 0);
        map.setColumn(0, 0, 3, "minecraft:stone");
        assertThrows(IllegalStateException.class, () -> map.setColumn(0, 0, 4, "minecraft:stone"));
        assertThrows(IllegalArgumentException.class, () -> map.setColumn(-1, 0, 4, "minecraft:stone"));
        assertThrows(IllegalStateException.class, map::render);
        assertThrows(IllegalStateException.class, () -> map.write(directory, "incomplete", "w", "w", "w", Instant.now(), Instant.now()));
        assertFalse(Files.exists(directory.resolve("incomplete.json")));
    }

    @Test void filenamesCannotTraverseOrOverwriteExistingArtifacts() throws Exception {
        for (String name : List.of("../bad", "/tmp/map", "UPPER", "", "a.b", "a".repeat(49)))
            assertThrows(IllegalArgumentException.class, () -> SurfaceMap.validateName(name));
        SurfaceMap map = new SurfaceMap(0, 0, 0, 0);
        map.setColumn(0, 0, 1, "minecraft:yellow_concrete");
        Files.writeString(directory.resolve("existing.png"), "keep");
        assertThrows(FileAlreadyExistsException.class, () -> map.write(directory, "existing", "w", "w", "w", Instant.now(), Instant.now()));
        assertEquals("keep", Files.readString(directory.resolve("existing.png")));
        assertFalse(Files.exists(directory.resolve("existing.json")));
    }

    @Test void limitsRejectOverflowAndEveryConcreteColorHasItsOwnPigment() {
        assertThrows(IllegalArgumentException.class, () -> new SurfaceMap(Integer.MIN_VALUE, 0, Integer.MAX_VALUE, 0));
        assertThrows(IllegalArgumentException.class, () -> new SurfaceMap(0, 0, 4096, 4096));
        assertThrows(IllegalArgumentException.class, () -> new SurfaceMap(1, 0, 0, 0));
        Set<Integer> colors = new HashSet<>();
        for (String color : List.of("white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
                "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black"))
            colors.add(SurfaceMap.color("minecraft:" + color + "_concrete"));
        assertEquals(16, colors.size());
        assertNotEquals(SurfaceMap.color("minecraft:water"), SurfaceMap.color("minecraft:grass_block"));
    }
}
