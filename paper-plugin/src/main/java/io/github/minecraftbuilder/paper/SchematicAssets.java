package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.BlockPos;
import java.io.*;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/**
 * Strict, dependency-free subset of Sponge Schematic v2 (gzip, big-endian NBT, palette varints).
 * Spec: https://github.com/SpongePowered/Schematic-Specification/blob/master/versions/schematic-2.md
 * IO methods run off the world thread. Snapshot input must already exclude all unsupported world data.
 * This codec deliberately rejects entities, block entities, biomes, unknown top-level tags and versions.
 * No DataFixer conversion is attempted: returned states must be canonicalized/validated by the server.
 */
public final class SchematicAssets {
    public static final int MAX_BLOCKS = 4096, MAX_ASSETS = 64;
    private static final int MAX_COMPRESSED = 1_048_576, MAX_NBT = 4_194_304;
    private static final Set<String> ROOT_FIELDS = Set.of("Version", "DataVersion", "Width", "Height", "Length",
        "Offset", "PaletteMax", "Palette", "BlockData", "BlockEntities", "Entities", "Metadata");
    private final Path root;
    private final StateTransformer states;

    @FunctionalInterface
    public interface StateTransformer { String transform(String state, int degrees) throws IOException; }

    public record Asset(String assetId, String name, int width, int height, int length, int blockCount,
                        int dataVersion, BlockPos offset, String sha256, long bytes) { }
    private record Decoded(String name, int width, int height, int length, int dataVersion,
                           BlockPos offset, List<String> blocks) { }
    private record Tag(int type, Object value) { }
    private record TagList(int elementType, List<Tag> values) { }

    public SchematicAssets(Path root) throws IOException { this(root, SchematicAssets::rotateState); }

    public SchematicAssets(Path root, StateTransformer states) throws IOException {
        Objects.requireNonNull(states);
        this.states = (state,degrees) -> states.transform(rotateState(state,0),degrees);
        this.root = root.toAbsolutePath().normalize();
        rejectSymlinkParents();
        Files.createDirectories(this.root);
        if (!Files.isDirectory(this.root, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Asset root must be a directory");
    }

    /** Export all cells of a dense box. origin is the clipboard anchor, not necessarily the minimum. */
    public synchronized Asset exportSnapshot(String name, Map<BlockPos, String> blocks, BlockPos origin, int dataVersion) throws IOException {
        requireName(name);
        Objects.requireNonNull(blocks); Objects.requireNonNull(origin);
        if (blocks.isEmpty() || blocks.size() > MAX_BLOCKS) throw new IOException("Snapshot must contain 1..4096 blocks");
        if (dataVersion < 0) throw new IOException("Invalid Minecraft DataVersion");
        rejectSymlinkParents();
        if (assetPaths().size() >= MAX_ASSETS) throw new IOException("Asset library is full (64 files maximum)");
        int minX = Integer.MAX_VALUE, minY = Integer.MAX_VALUE, minZ = Integer.MAX_VALUE;
        int maxX = Integer.MIN_VALUE, maxY = Integer.MIN_VALUE, maxZ = Integer.MIN_VALUE;
        for (BlockPos at : blocks.keySet()) {
            if (at == null) throw new IOException("Null snapshot position");
            minX = Math.min(minX, at.x()); minY = Math.min(minY, at.y()); minZ = Math.min(minZ, at.z());
            maxX = Math.max(maxX, at.x()); maxY = Math.max(maxY, at.y()); maxZ = Math.max(maxZ, at.z());
        }
        int width = extent(minX, maxX), height = extent(minY, maxY), length = extent(minZ, maxZ);
        int volume = volume(width, height, length);
        if (blocks.size() != volume) throw new IOException("Snapshot must include every bounding-box cell, including air");
        BlockPos offset;
        try { offset = new BlockPos(Math.subtractExact(minX, origin.x()), Math.subtractExact(minY, origin.y()), Math.subtractExact(minZ, origin.z())); }
        catch (ArithmeticException e) { throw new IOException("Clipboard offset overflows integer coordinates", e); }
        LinkedHashMap<String, Integer> palette = new LinkedHashMap<>();
        ByteArrayOutputStream data = new ByteArrayOutputStream();
        for (int y = 0; y < height; y++) for (int z = 0; z < length; z++) for (int x = 0; x < width; x++) {
            String state = states.transform(blocks.get(new BlockPos(minX + x, minY + y, minZ + z)), 0);
            int index = palette.computeIfAbsent(state, ignored -> palette.size());
            writeVarInt(data, index);
        }
        byte[] encoded = encode(name, dataVersion, width, height, length, offset, palette, data.toByteArray());
        if (encoded.length > MAX_COMPRESSED) throw new IOException("Compressed asset exceeds 1 MiB");
        String id = UUID.randomUUID().toString();
        Path destination = path(id), temporary = Files.createTempFile(root, ".asset-", ".tmp");
        try {
            Files.write(temporary, encoded, StandardOpenOption.TRUNCATE_EXISTING);
            try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) { channel.force(true); }
            Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE);
            try (FileChannel directory = FileChannel.open(root, StandardOpenOption.READ)) { directory.force(true); }
        } finally { Files.deleteIfExists(temporary); }
        return metadata(id, decode(encoded), encoded);
    }

    /** Imported files may be provisioned locally as [A-Za-z0-9][A-Za-z0-9_-]{0,63}.schem. */
    public synchronized List<Asset> list() throws IOException {
        List<Asset> result = new ArrayList<>();
        for (Path file : assetPaths()) {
            String id = file.getFileName().toString().replaceFirst("\\.schem$", "");
            byte[] bytes = load(id);
            result.add(metadata(id, decode(bytes), bytes));
        }
        return List.copyOf(result);
    }

    /** Bounded strict inspection of one asset without exposing a filesystem path. */
    public synchronized Asset metadata(String assetId) throws IOException {
        byte[] bytes = load(assetId);
        return metadata(assetId, decode(bytes), bytes);
    }

    /** rotation90 is degrees: 0/90/180/270 clockwise viewed from above. Rotate about target anchor. */
    public synchronized Map<BlockPos, String> read(String assetId, BlockPos target, int rotation90) throws IOException {
        return read(assetId, target, rotation90, Integer.MAX_VALUE);
    }

    /** Checks the same decoded input used for placement, even if a file changed after metadata(). */
    public synchronized Map<BlockPos, String> read(String assetId, BlockPos target, int rotation90, int maxDataVersion) throws IOException {
        if (!Set.of(0, 90, 180, 270).contains(rotation90)) throw new IOException("Rotation must be 0, 90, 180 or 270 degrees");
        if (maxDataVersion < 0) throw new IOException("Invalid target Minecraft DataVersion");
        Objects.requireNonNull(target);
        Decoded value = decode(load(assetId));
        if (value.dataVersion > maxDataVersion) throw new IOException("Schematic DataVersion is newer than the target server");
        Map<BlockPos, String> result = new LinkedHashMap<>();
        try {
            int index = 0;
            for (int y = 0; y < value.height; y++) for (int z = 0; z < value.length; z++) for (int x = 0; x < value.width; x++) {
                int dx = Math.addExact(x, value.offset.x()), dy = Math.addExact(y, value.offset.y()), dz = Math.addExact(z, value.offset.z());
                for (int turn = 0; turn < rotation90 / 90; turn++) { int oldX = dx; dx = Math.negateExact(dz); dz = oldX; }
                BlockPos at = target.add(new BlockPos(dx, dy, dz));
                result.put(at, states.transform(value.blocks.get(index++), rotation90));
            }
        } catch (ArithmeticException e) { throw new IOException("Placement overflows integer coordinates", e); }
        return Collections.unmodifiableMap(result);
    }

    private static Asset metadata(String id, Decoded data, byte[] bytes) {
        try {
            return new Asset(id, data.name, data.width, data.height, data.length, data.blocks.size(), data.dataVersion,
                data.offset, HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)), bytes.length);
        } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); }
    }
    private Path path(String id) throws IOException {
        if (id == null || !id.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,63}")) throw new IOException("Invalid asset ID; paths are not accepted");
        return root.resolve(id + ".schem");
    }
    private void rejectSymlinkParents() throws IOException {
        for (Path at = root; at != null; at = at.getParent())
            if (Files.isSymbolicLink(at)) throw new IOException("Symlinks are not allowed in asset directory path");
    }
    private List<Path> assetPaths() throws IOException {
        rejectSymlinkParents();
        List<Path> files = new ArrayList<>();
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(root, "*.schem")) {
            for (Path file : stream) {
                String name = file.getFileName().toString();
                path(name.substring(0, name.length() - 6));
                if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Asset must be a regular non-symlink file");
                if (files.size() >= MAX_ASSETS) throw new IOException("Asset library exceeds 64 files");
                files.add(file);
            }
        }
        files.sort(Comparator.comparing(file -> file.getFileName().toString()));
        return files;
    }
    private byte[] load(String id) throws IOException {
        rejectSymlinkParents();
        Path file = path(id);
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Asset not found or is not a regular file");
        try (InputStream in = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = in.readNBytes(MAX_COMPRESSED + 1);
            if (bytes.length > MAX_COMPRESSED) throw new IOException("Compressed asset exceeds 1 MiB");
            return bytes;
        }
    }
    private static int extent(int min, int max) throws IOException {
        long value = (long) max - min + 1;
        if (value < 1 || value > MAX_BLOCKS) throw new IOException("Schematic dimension exceeds limits");
        return (int) value;
    }
    private static int volume(int width, int height, int length) throws IOException {
        long volume = (long) width * height * length;
        if (width < 1 || height < 1 || length < 1 || volume > MAX_BLOCKS) throw new IOException("Schematic volume must be 1..4096");
        return (int) volume;
    }
    private static void requireName(String name) throws IOException {
        if (name == null || name.isBlank() || name.length() > 64 || name.chars().anyMatch(Character::isISOControl))
            throw new IOException("Asset name must contain 1..64 printable characters");
    }

    /** Offline syntax codec; runtime integration injects registry validation and native rotation. */
    static String rotateState(String state, int degrees) throws IOException {
        if (state == null || state.length() > 1024 || !state.matches("minecraft:[a-z0-9_]+(?:\\[[a-z0-9_=,]+\\])?"))
            throw new IOException("Invalid vanilla block state");
        int bracket = state.indexOf('[');
        String id = state.substring(10, bracket < 0 ? state.length() : bracket);
        TreeMap<String, String> properties = new TreeMap<>();
        if (bracket >= 0) for (String property : state.substring(bracket + 1, state.length() - 1).split(",")) {
            String[] pair = property.split("=", -1);
            if (pair.length != 2 || properties.put(pair[0], pair[1]) != null) throw new IOException("Invalid or duplicate block property");
        }
        if (!Set.of(0,90,180,270).contains(degrees)) throw new IOException("Invalid rotation");
        if (degrees == 0) return "minecraft:" + id + (properties.isEmpty() ? "" : "[" + String.join(",", properties.entrySet().stream().map(e -> e.getKey() + "=" + e.getValue()).toList()) + "]");
        Set<String> allowed = Set.of("facing","axis","half","shape","type","waterlogged","snowy");
        if (!allowed.containsAll(properties.keySet())) throw new IOException("Runtime block rotation required for these properties");
        if(properties.containsKey("shape") && !Set.of("straight","inner_left","inner_right","outer_left","outer_right").contains(properties.get("shape")))
            throw new IOException("Runtime block rotation required for this shape");
        if (degrees != 0 && id.endsWith("_stairs") && !properties.containsKey("facing"))
            throw new IOException("Rotation requires explicit stairs facing");
        if (degrees != 0 && (id.endsWith("_log") || id.equals("quartz_pillar") || id.equals("deepslate")) && !properties.containsKey("axis"))
            throw new IOException("Rotation requires explicit block axis");
        if (properties.containsKey("facing") && !Set.of("up","down").contains(properties.get("facing"))) {
            List<String> faces = List.of("north", "east", "south", "west");
            if (!faces.contains(properties.get("facing"))) throw new IOException("Invalid facing");
            properties.put("facing", faces.get((faces.indexOf(properties.get("facing")) + degrees / 90) % 4));
        }
        if (degrees % 180 != 0 && properties.containsKey("axis") && !properties.get("axis").equals("y"))
            properties.put("axis", properties.get("axis").equals("x") ? "z" : "x");
        return "minecraft:" + id + (properties.isEmpty() ? "" : "[" + String.join(",", properties.entrySet().stream().map(e -> e.getKey() + "=" + e.getValue()).toList()) + "]");
    }

    private static byte[] encode(String name, int version, int width, int height, int length, BlockPos offset,
                                 LinkedHashMap<String, Integer> palette, byte[] blockData) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(new GZIPOutputStream(bytes))) {
            header(out, 10, "Schematic");
            header(out, 3, "Version"); out.writeInt(2);
            header(out, 3, "DataVersion"); out.writeInt(version);
            header(out, 2, "Width"); out.writeShort(width);
            header(out, 2, "Height"); out.writeShort(height);
            header(out, 2, "Length"); out.writeShort(length);
            header(out, 11, "Offset"); out.writeInt(3); out.writeInt(offset.x()); out.writeInt(offset.y()); out.writeInt(offset.z());
            header(out, 3, "PaletteMax"); out.writeInt(palette.size());
            header(out, 10, "Palette");
            for (var entry : palette.entrySet()) { header(out, 3, entry.getKey()); out.writeInt(entry.getValue()); }
            out.writeByte(0);
            header(out, 7, "BlockData"); out.writeInt(blockData.length); out.write(blockData);
            header(out, 9, "BlockEntities"); out.writeByte(10); out.writeInt(0);
            header(out, 9, "Entities"); out.writeByte(10); out.writeInt(0);
            header(out, 10, "Metadata"); header(out, 8, "Name"); out.writeUTF(name);
            header(out, 8, "Author"); out.writeUTF("minecraft-builder-mcp");
            header(out, 4, "Date"); out.writeLong(System.currentTimeMillis());
            out.writeByte(0); out.writeByte(0);
        }
        return bytes.toByteArray();
    }
    private static void header(DataOutputStream out, int type, String name) throws IOException { out.writeByte(type); out.writeUTF(name); }
    private static void writeVarInt(OutputStream out, int value) throws IOException {
        do { int next = value & 127; value >>>= 7; out.write(next | (value != 0 ? 128 : 0)); } while (value != 0);
    }
    private Decoded decode(byte[] compressed) throws IOException {
        byte[] raw;
        try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(compressed))) {
            raw = gzip.readNBytes(MAX_NBT + 1);
            if (raw.length > MAX_NBT) throw new IOException("Inflated schematic exceeds 4 MiB");
        }
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(raw))) {
            if (in.readUnsignedByte() != 10) throw new IOException("Schematic root must be TAG_Compound");
            String rootName = boundedUtf(in);
            if (!rootName.isEmpty() && !rootName.equals("Schematic")) throw new IOException("Unexpected schematic root name");
            Map<String, Tag> tags = compound(in, 0, new int[]{0});
            if (in.read() != -1) throw new IOException("Trailing NBT data is not accepted");
            if (!ROOT_FIELDS.containsAll(tags.keySet())) throw new IOException("Unsupported schematic fields (biomes/custom data are not imported)");
            if (integer(tags, "Version") != 2) throw new IOException("Only Sponge schematic version 2 is supported");
            int dataVersion = integer(tags, "DataVersion");
            if (dataVersion < 0) throw new IOException("Invalid Minecraft DataVersion");
            int width = Short.toUnsignedInt((Short) required(tags, "Width", 2).value);
            int height = Short.toUnsignedInt((Short) required(tags, "Height", 2).value);
            int length = Short.toUnsignedInt((Short) required(tags, "Length", 2).value);
            int volume = volume(width, height, length);
            BlockPos offset = new BlockPos(0, 0, 0);
            if (tags.containsKey("Offset")) {
                int[] values = (int[]) required(tags, "Offset", 11).value;
                if (values.length != 3) throw new IOException("Offset must have exactly 3 integers");
                offset = new BlockPos(values[0], values[1], values[2]);
            }
            for (String name : List.of("Entities", "BlockEntities")) if (tags.containsKey(name)) {
                TagList list = (TagList) required(tags, name, 9).value;
                if (!list.values.isEmpty()) throw new IOException(name + " are unsupported; import rejected without dropping data");
                if (list.elementType != 0 && list.elementType != 10) throw new IOException("Invalid " + name + " list type");
            }
            Map<String, Tag> paletteTags = map(required(tags, "Palette", 10));
            if (paletteTags.isEmpty() || paletteTags.size() > MAX_BLOCKS) throw new IOException("Invalid palette size");
            int paletteMax = tags.containsKey("PaletteMax") ? integer(tags, "PaletteMax") : MAX_BLOCKS;
            if (paletteMax < 1 || paletteMax > MAX_BLOCKS) throw new IOException("Invalid PaletteMax");
            Map<Integer, String> palette = new HashMap<>();
            for (var entry : paletteTags.entrySet()) {
                if (entry.getValue().type != 3) throw new IOException("Palette indices must be integers");
                int id = (Integer) entry.getValue().value;
                String state = states.transform(entry.getKey(), 0);
                if (id < 0 || id >= paletteMax || palette.put(id, state) != null) throw new IOException("Invalid or duplicate palette index");
            }
            byte[] blockData = (byte[]) required(tags, "BlockData", 7).value;
            ByteArrayInputStream data = new ByteArrayInputStream(blockData);
            List<String> blocks = new ArrayList<>(volume);
            for (int i = 0; i < volume; i++) {
                int id = readVarInt(data);
                String state = palette.get(id);
                if (state == null) throw new IOException("BlockData refers to missing palette index");
                blocks.add(state);
            }
            if (data.read() != -1) throw new IOException("BlockData has extra entries");
            String name = "Imported schematic";
            if (tags.containsKey("Metadata")) {
                Map<String, Tag> metadata = map(required(tags, "Metadata", 10));
                if (metadata.containsKey("RequiredMods")) {
                    TagList mods = (TagList) required(metadata, "RequiredMods", 9).value;
                    if (!mods.values.isEmpty()) throw new IOException("Schematics requiring mods are unsupported");
                }
                if (metadata.containsKey("Name")) { name = (String) required(metadata, "Name", 8).value; requireName(name); }
            }
            return new Decoded(name, width, height, length, dataVersion, offset, List.copyOf(blocks));
        } catch (IllegalArgumentException | ClassCastException e) { throw new IOException("Malformed schematic", e); }
    }
    private static int readVarInt(InputStream in) throws IOException {
        int value = 0;
        for (int index = 0; index < 5; index++) {
            int next = in.read();
            if (next < 0) throw new EOFException("Truncated block-data varint");
            if (index == 4 && (next & 0xf0) != 0) throw new IOException("Block-data varint exceeds positive int");
            value |= (next & 127) << (index * 7);
            if ((next & 128) == 0) {
                if (value < 0 || index > 0 && (next & 127) == 0) throw new IOException("Negative or noncanonical block-data varint");
                return value;
            }
        }
        throw new IOException("Block-data varint is too long");
    }
    private static Tag required(Map<String, Tag> tags, String key, int type) throws IOException {
        Tag value = tags.get(key);
        if (value == null || value.type != type) throw new IOException("Missing or mistyped schematic field: " + key);
        return value;
    }
    private static int integer(Map<String, Tag> tags, String key) throws IOException { return (Integer) required(tags, key, 3).value; }
    @SuppressWarnings("unchecked") private static Map<String, Tag> map(Tag tag) { return (Map<String, Tag>) tag.value; }
    private static String boundedUtf(DataInputStream in) throws IOException {
        int length = in.readUnsignedShort();
        if (length > 4096) throw new IOException("NBT string exceeds 4096 bytes");
        byte[] bytes = in.readNBytes(length);
        if (bytes.length != length) throw new EOFException("Truncated NBT string");
        // NBT Java strings use DataInput modified UTF-8, including supplementary characters.
        ByteArrayOutputStream framed = new ByteArrayOutputStream(length + 2);
        DataOutputStream out = new DataOutputStream(framed); out.writeShort(length); out.write(bytes);
        return new DataInputStream(new ByteArrayInputStream(framed.toByteArray())).readUTF();
    }
    private static Map<String, Tag> compound(DataInputStream in, int depth, int[] nodes) throws IOException {
        if (depth > 16) throw new IOException("NBT nesting exceeds 16 levels");
        Map<String, Tag> result = new LinkedHashMap<>();
        while (true) {
            int type = in.readUnsignedByte();
            if (type == 0) return result;
            String name = boundedUtf(in);
            if (result.containsKey(name)) throw new IOException("Duplicate NBT tag name");
            result.put(name, payload(in, type, depth + 1, nodes));
        }
    }
    private static int count(DataInputStream in, int itemBytes) throws IOException {
        int count = in.readInt();
        if (count < 0 || count > MAX_NBT / itemBytes || (long) count * itemBytes > in.available())
            throw new IOException("NBT array/list size exceeds remaining bounded input");
        return count;
    }
    private static Tag payload(DataInputStream in, int type, int depth, int[] nodes) throws IOException {
        if (depth > 16 || ++nodes[0] > 20_000) throw new IOException("NBT structure exceeds depth/node budget");
        Object value = switch (type) {
            case 1 -> in.readByte(); case 2 -> in.readShort(); case 3 -> in.readInt(); case 4 -> in.readLong();
            case 5 -> in.readFloat(); case 6 -> in.readDouble();
            case 7 -> { int size = count(in, 1); byte[] bytes = in.readNBytes(size); if (bytes.length != size) throw new EOFException(); yield bytes; }
            case 8 -> boundedUtf(in);
            case 9 -> {
                int elementType = in.readUnsignedByte(), size = count(in, 1);
                if (elementType < 0 || elementType > 12 || (elementType == 0 && size != 0)) throw new IOException("Invalid NBT list type");
                if (size > 20_000) throw new IOException("NBT list exceeds node budget");
                List<Tag> values = new ArrayList<>(size);
                for (int i = 0; i < size; i++) values.add(payload(in, elementType, depth + 1, nodes));
                yield new TagList(elementType, List.copyOf(values));
            }
            case 10 -> compound(in, depth, nodes);
            case 11 -> { int size = count(in, 4); int[] values = new int[size]; for (int i = 0; i < size; i++) values[i] = in.readInt(); yield values; }
            case 12 -> { int size = count(in, 8); long[] values = new long[size]; for (int i = 0; i < size; i++) values[i] = in.readLong(); yield values; }
            default -> throw new IOException("Unknown NBT tag type");
        };
        return new Tag(type, value);
    }
}
