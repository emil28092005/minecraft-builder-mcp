package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.BlockPos;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import static org.junit.jupiter.api.Assertions.*;

class SchematicAssetsTest {
    @TempDir Path root;
    private static final BlockPos ZERO = new BlockPos(0, 0, 0);
    private static final String STONE = "minecraft:stone";
    private static final String STAIRS = "minecraft:oak_stairs[facing=north,half=bottom,shape=inner_left,waterlogged=false]";

    @Test void roundTripKeepsEveryDenseCellAndOriginOffset() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        Map<BlockPos, String> blocks = new LinkedHashMap<>();
        blocks.put(new BlockPos(-2, 70, 4), STONE);
        blocks.put(new BlockPos(-1, 70, 4), "minecraft:air");
        blocks.put(new BlockPos(-2, 71, 4), "minecraft:oak_log[axis=x]");
        blocks.put(new BlockPos(-1, 71, 4), STAIRS);
        BlockPos anchor = new BlockPos(-1, 69, 3);
        var asset = assets.exportSnapshot("Башня", blocks, anchor, 5000);
        assertEquals(new BlockPos(-1, 1, 1), asset.offset());
        assertEquals(4, asset.blockCount());
        assertEquals(5000, asset.dataVersion());
        assertEquals(64, asset.sha256().length());
        assertEquals(blocks, assets.read(asset.assetId(), anchor, 0));
        assertEquals(List.of(asset), assets.list());
        try (DataInputStream nbt = new DataInputStream(new GZIPInputStream(Files.newInputStream(root.resolve(asset.assetId() + ".schem"))))) {
            assertEquals(10, nbt.readUnsignedByte());
            assertEquals("Schematic", nbt.readUTF());
            assertEquals(3, nbt.readUnsignedByte()); assertEquals("Version", nbt.readUTF()); assertEquals(2, nbt.readInt());
        }
    }

    @Test void rotationMovesOffsetAndTransformsStairsLogsSlabsWithoutMirroring() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        Map<BlockPos, String> blocks = Map.of(new BlockPos(1, 0, 0), STAIRS, new BlockPos(2, 0, 0), "minecraft:oak_log[axis=x]",
            new BlockPos(3, 0, 0), "minecraft:oak_slab[type=top,waterlogged=false]");
        var asset = assets.exportSnapshot("Rotation", blocks, ZERO, 5000);
        Map<BlockPos, String> rotated = assets.read(asset.assetId(), new BlockPos(10, 64, 20), 90);
        assertEquals("minecraft:oak_stairs[facing=east,half=bottom,shape=inner_left,waterlogged=false]", rotated.get(new BlockPos(10, 64, 21)));
        assertEquals("minecraft:oak_log[axis=z]", rotated.get(new BlockPos(10, 64, 22)));
        assertEquals("minecraft:oak_slab[type=top,waterlogged=false]", rotated.get(new BlockPos(10, 64, 23)));
        assertEquals("minecraft:oak_log[axis=x]", assets.read(asset.assetId(), ZERO, 180).get(new BlockPos(-2, 0, 0)));
        assertEquals("minecraft:oak_stairs[facing=west,half=bottom,shape=inner_left,waterlogged=false]", assets.read(asset.assetId(), ZERO, 270).get(new BlockPos(0, 0, -1)));
    }

    @Test void independentlyWrittenFixtureUsesXThenZThenYVarintOrder() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        Files.write(root.resolve("external.schem"), fixture(2, 1, 2, List.of(STONE, "minecraft:air"), new byte[]{0, 1, 1, 0}, out -> {}));
        assertEquals(Map.of(ZERO, STONE, new BlockPos(1, 0, 0), "minecraft:air", new BlockPos(0, 0, 1), "minecraft:air", new BlockPos(1, 0, 1), STONE), assets.read("external", ZERO, 0));
    }

    @Test void paletteIndicesAbove127RoundTripAsMultibyteVarints() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        List<String> palette = new ArrayList<>();
        for (String block : List.of("oak_stairs", "spruce_stairs", "cobblestone_stairs", "stone_brick_stairs"))
            for (String facing : List.of("north", "east", "south", "west"))
                for (String half : List.of("bottom", "top"))
                    for (String shape : List.of("straight", "inner_left", "inner_right", "outer_left", "outer_right"))
                        palette.add("minecraft:" + block + "[facing=" + facing + ",half=" + half + ",shape=" + shape + ",waterlogged=false]");
        ByteArrayOutputStream indices = new ByteArrayOutputStream();
        Map<BlockPos, String> expected = new LinkedHashMap<>();
        for (int i = 0; i < palette.size(); i++) {
            if (i < 128) indices.write(i); else { indices.write((i & 127) | 128); indices.write(i >>> 7); }
            expected.put(new BlockPos(i, 0, 0), palette.get(i));
        }
        Files.write(root.resolve("varints.schem"), fixture(palette.size(), 1, 1, palette, indices.toByteArray(), out -> {}));
        assertEquals(expected, assets.read("varints", ZERO, 0));
        var exported = assets.exportSnapshot("Large palette", expected, ZERO, 5000);
        assertEquals(expected, assets.read(exported.assetId(), ZERO, 0));
    }

    @Test void rejectsSparseSnapshotUnsupportedBlocksAndUnrepresentableOrigin() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        assertThrows(IOException.class, () -> assets.exportSnapshot("Gap", Map.of(ZERO, STONE, new BlockPos(2, 0, 0), STONE), ZERO, 5000));
        assertThrows(IOException.class, () -> assets.exportSnapshot("Chest", Map.of(ZERO, "minecraft:chest"), ZERO, 5000));
        assertThrows(IOException.class, () -> assets.exportSnapshot("Offset", Map.of(new BlockPos(Integer.MIN_VALUE, 0, 0), STONE), new BlockPos(Integer.MAX_VALUE, 0, 0), 5000));
        assertEquals(0, assets.list().size());
    }

    @Test void rejectsEntitiesAndBlockEntitiesRatherThanDroppingThem() throws Exception {
        for (String field : List.of("Entities", "BlockEntities")) {
            Files.write(root.resolve("entity.schem"), fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> {
                tag(out, 9, field); out.writeByte(10); out.writeInt(1); tag(out, 8, "Id"); out.writeUTF("minecraft:pig"); out.writeByte(0);
            }));
            IOException error = assertThrows(IOException.class, () -> new SchematicAssets(root).read("entity", ZERO, 0));
            assertTrue(error.getMessage().contains("unsupported"));
        }
    }

    @Test void rejectsBiomeAndUnknownTopLevelData() throws Exception {
        Files.write(root.resolve("biome.schem"), fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> { tag(out, 7, "BiomeData"); out.writeInt(1); out.writeByte(0); }));
        assertThrows(IOException.class, () -> new SchematicAssets(root).read("biome", ZERO, 0));
    }

    @Test void rejectsBadPaletteMissingExtraAndMalformedVarints() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        for (byte[] data : List.of(new byte[]{2}, new byte[0], new byte[]{0, 0}, new byte[]{(byte) 128}, new byte[]{(byte) 128, 0}, new byte[]{(byte) 255, (byte) 255, (byte) 255, (byte) 255, 127})) {
            Files.write(root.resolve("bad.schem"), fixture(1, 1, 1, List.of(STONE), data, out -> {}));
            assertThrows(IOException.class, () -> assets.read("bad", ZERO, 0));
        }
    }

    @Test void rejectsDuplicateTagsUnsupportedVersionAndHugeVolume() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        Files.write(root.resolve("duplicate.schem"), fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> { tag(out, 3, "Version"); out.writeInt(3); }));
        assertThrows(IOException.class, () -> assets.read("duplicate", ZERO, 0));
        Files.write(root.resolve("large.schem"), fixture(4097, 1, 1, List.of(STONE), new byte[]{0}, out -> {}));
        assertThrows(IOException.class, () -> assets.read("large", ZERO, 0));
        byte[] future = fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> {});
        byte[] raw = new GZIPInputStream(new ByteArrayInputStream(future)).readAllBytes();
        // Locate integer following the independent fixture's Version field and replace 2 with 3.
        try (ByteArrayInputStream bytes = new ByteArrayInputStream(raw); DataInputStream in = new DataInputStream(bytes)) {
            in.readByte(); in.readUTF(); in.readByte(); in.readUTF(); int at = raw.length - bytes.available(); raw[at + 3] = 3;
        }
        Files.write(root.resolve("future.schem"), gzip(raw));
        assertThrows(IOException.class, () -> assets.read("future", ZERO, 0));
    }

    @Test void rejectsGzipBombTruncationExcessiveDepthAndHostileArrayLength() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        Files.write(root.resolve("bomb.schem"), gzip(new byte[4_194_305]));
        assertThrows(IOException.class, () -> assets.read("bomb", ZERO, 0));
        Files.write(root.resolve("short.schem"), new byte[]{31, (byte) 139});
        assertThrows(IOException.class, () -> assets.read("short", ZERO, 0));
        Files.write(root.resolve("array.schem"), fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> { tag(out, 11, "Offset"); out.writeInt(Integer.MAX_VALUE); }));
        assertThrows(IOException.class, () -> assets.read("array", ZERO, 0));
        Files.write(root.resolve("deep.schem"), fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> {
            tag(out, 10, "Metadata"); for (int i = 0; i < 30; i++) tag(out, 10, "deep"); for (int i = 0; i < 31; i++) out.writeByte(0);
        }));
        assertThrows(IOException.class, () -> assets.read("deep", ZERO, 0));
    }

    @Test void rejectsPathsSymlinksAndCoordinateOverflow() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        assertThrows(IOException.class, () -> assets.read("../outside", ZERO, 0));
        Path external = Files.createTempFile("mcb-schematic-test-", ".schem");
        try {
            Files.write(external, fixture(1, 1, 1, List.of(STONE), new byte[]{0}, out -> {}));
            Files.createSymbolicLink(root.resolve("linked.schem"), external);
            assertThrows(IOException.class, () -> assets.read("linked", ZERO, 0));
            Files.delete(root.resolve("linked.schem"));
        } finally { Files.deleteIfExists(external); }
        var asset = assets.exportSnapshot("Offset", Map.of(new BlockPos(1, 0, 0), STONE), ZERO, 5000);
        assertThrows(IOException.class, () -> assets.read(asset.assetId(), new BlockPos(Integer.MAX_VALUE, 0, 0), 0));
        assertThrows(IOException.class, () -> assets.read(asset.assetId(), ZERO, 45));
    }

    @Test void rejectsUnspecifiedRotationalPropertiesAndUnsupportedStates() throws Exception {
        assertThrows(IOException.class, () -> SchematicAssets.rotateState("minecraft:oak_stairs", 90));
        assertThrows(IOException.class, () -> SchematicAssets.rotateState("minecraft:oak_log", 90));
        assertThrows(IOException.class, () -> SchematicAssets.rotateState("minecraft:oak_log[axis=x,axis=z]", 0));
        assertThrows(IOException.class, () -> SchematicAssets.rotateState("minecraft:oak_stairs[facing=up]", 0));
        assertThrows(IOException.class, () -> SchematicAssets.rotateState("minecraft:oak_slab[type=top,waterlogged=true]", 0));
        assertThrows(IOException.class, () -> SchematicAssets.rotateState("minecraft:stone[rotation=4]", 90));
    }

    @Test void metadataAndPlacementRejectFutureDataVersionOnTheActualRead() throws Exception {
        SchematicAssets assets = new SchematicAssets(root);
        var asset = assets.exportSnapshot("Versioned", Map.of(ZERO, STONE), ZERO, 5000);
        assertEquals(asset, assets.metadata(asset.assetId()));
        assertThrows(IOException.class, () -> assets.read(asset.assetId(), ZERO, 0, 4999));
        assertEquals(Map.of(ZERO, STONE), assets.read(asset.assetId(), ZERO, 0, 5000));
        assertEquals(Map.of(ZERO, STONE), assets.read(asset.assetId(), ZERO, 0, 5001));
    }

    private interface Extra { void write(DataOutputStream out) throws IOException; }
    /** Independent spec fixture writer, intentionally does not call codec encode. */
    private static byte[] fixture(int width, int height, int length, List<String> palette, byte[] data, Extra extra) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(bytes)) {
            tag(out, 10, "Schematic"); tag(out, 3, "Version"); out.writeInt(2); tag(out, 3, "DataVersion"); out.writeInt(5000);
            tag(out, 2, "Width"); out.writeShort(width); tag(out, 2, "Height"); out.writeShort(height); tag(out, 2, "Length"); out.writeShort(length);
            tag(out, 3, "PaletteMax"); out.writeInt(palette.size()); tag(out, 10, "Palette");
            for (int i = 0; i < palette.size(); i++) { tag(out, 3, palette.get(i)); out.writeInt(i); }
            out.writeByte(0); tag(out, 7, "BlockData"); out.writeInt(data.length); out.write(data); extra.write(out); out.writeByte(0);
        }
        return gzip(bytes.toByteArray());
    }
    private static void tag(DataOutputStream out, int type, String name) throws IOException { out.writeByte(type); out.writeUTF(name); }
    private static byte[] gzip(byte[] bytes) throws IOException {
        ByteArrayOutputStream compressed = new ByteArrayOutputStream();
        try (GZIPOutputStream gzip = new GZIPOutputStream(compressed)) { gzip.write(bytes); }
        return compressed.toByteArray();
    }
}
