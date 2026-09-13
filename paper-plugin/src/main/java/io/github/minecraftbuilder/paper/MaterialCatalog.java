package io.github.minecraftbuilder.paper;

import org.bukkit.Bukkit;
import org.bukkit.Material;
import org.bukkit.block.TileState;
import org.bukkit.block.data.*;
import org.bukkit.block.data.type.Bed;
import org.bukkit.block.data.type.Door;
import org.bukkit.block.data.type.Leaves;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.function.Function;

/** Runtime registry discovery. Full registries and state permutations never enter an RPC response. */
final class MaterialCatalog {
    static final int DEFAULT_LIMIT = 16, MAX_LIMIT = 32;
    private static final int MAX_QUERY = 96, MAX_ID = 128, MAX_CURSOR = 100;
    private static final int MAX_PROPERTIES = 64, MAX_PROPERTY_VALUES = 256, MAX_DESCRIPTION_CHARS = 16_384;
    private final List<Entry> entries;
    private final Map<String, Entry> byId;
    private final Function<String, StateDescription> describeBlock;
    private final String version;

    record Entry(String id, boolean block, boolean item) {
        Map<String, Object> compact() { return Map.of("id", id, "block", block, "item", item); }
    }
    record StateDescription(String defaultState, Map<String, List<String>> properties, List<String> behavior) {}

    /** Construct on the server thread after Bukkit registries have loaded. */
    MaterialCatalog() {
        this(Bukkit.getMinecraftVersion() + "/" + Bukkit.getBukkitVersion(), runtimeEntries(), MaterialCatalog::runtimeDescription);
    }

    MaterialCatalog(String runtimeVersion, Collection<Entry> source, Function<String, StateDescription> describeBlock) {
        this.entries = source.stream().sorted(Comparator.comparing(Entry::id)).toList();
        Map<String, Entry> index = new HashMap<>();
        StringBuilder fingerprint = new StringBuilder("material-catalog-v1\n").append(runtimeVersion).append('\n');
        for (Entry entry : entries) {
            if (index.put(entry.id(), entry) != null) throw new IllegalArgumentException("Duplicate material ID: " + entry.id());
            fingerprint.append(entry.id()).append(':').append(entry.block()).append(':').append(entry.item()).append('\n');
        }
        this.byId = Map.copyOf(index);
        this.describeBlock = Objects.requireNonNull(describeBlock);
        this.version = digest(fingerprint.toString());
    }

    Map<String, Object> summary() {
        return Map.of("version", version, "materials", entries.size(),
            "blocks", entries.stream().filter(Entry::block).count(),
            "items", entries.stream().filter(Entry::item).count(),
            "search_default_limit", DEFAULT_LIMIT, "search_max_limit", MAX_LIMIT);
    }

    Map<String, Object> search(String query, String kind, Integer requestedLimit, String cursor) {
        query = normalizeQuery(query);
        kind = kind == null ? "block" : kind;
        if (!Set.of("block", "item", "all").contains(kind))
            throw fault("invalid_material_query", "kind must be block, item, or all");
        int limit = requestedLimit == null ? DEFAULT_LIMIT : requestedLimit;
        if (limit < 1 || limit > MAX_LIMIT)
            throw fault("invalid_material_query", "limit must be between 1 and " + MAX_LIMIT);
        String scope = digest(kind + "\n" + query);
        int offset = decodeCursor(cursor, scope);
        String[] tokens = query.isEmpty() ? new String[0] : query.split(" ");
        List<Entry> matching = new ArrayList<>();
        for (Entry entry : entries) {
            if (kind.equals("block") && !entry.block() || kind.equals("item") && !entry.item()) continue;
            if (Arrays.stream(tokens).allMatch(token -> entry.id().contains(token))) matching.add(entry);
        }
        if (offset > matching.size()) throw fault("invalid_cursor", "Cursor exceeds the matching catalog");
        int end = Math.min(matching.size(), offset + limit);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("catalog_version", version);
        result.put("query", query);
        result.put("kind", kind);
        result.put("total", matching.size());
        result.put("results", matching.subList(offset, end).stream().map(Entry::compact).toList());
        if (end < matching.size()) result.put("next_cursor", version + ":" + scope + ":" + end);
        return result;
    }

    Map<String, Object> describe(String id) {
        id = normalizeId(id);
        Entry entry = byId.get(id);
        if (entry == null) throw fault("invalid_material", "Unknown runtime material: " + id);
        Map<String, Object> result = new LinkedHashMap<>(entry.compact());
        result.put("catalog_version", version);
        result.put("placeable", entry.block());
        if (entry.block()) {
            StateDescription state = describeBlock.apply(id);
            if (state.defaultState().length() > 1024)
                throw fault("material_properties_unavailable", "Runtime default block state exceeds the protocol limit");
            result.put("default_state", state.defaultState());
            result.put("properties", state.properties());
            if (!state.behavior().isEmpty()) result.put("behavior", state.behavior());
        }
        return result;
    }

    private int decodeCursor(String cursor, String scope) {
        if (cursor == null || cursor.isEmpty()) return 0;
        if (cursor.length() > MAX_CURSOR || !cursor.matches("[0-9a-f]{24}:[0-9a-f]{24}:[0-9]{1,9}"))
            throw fault("invalid_cursor", "Malformed material catalog cursor");
        String[] parts = cursor.split(":");
        if (!parts[0].equals(version)) throw fault("stale_cursor", "Material catalog changed; restart the search");
        if (!parts[1].equals(scope)) throw fault("invalid_cursor", "Cursor belongs to another query or kind");
        return Integer.parseInt(parts[2]);
    }

    private static String normalizeQuery(String query) {
        if (query == null) return "";
        if (query.length() > MAX_QUERY || query.chars().anyMatch(Character::isISOControl))
            throw fault("invalid_material_query", "query must contain at most 96 printable characters");
        return query.strip().toLowerCase(Locale.ROOT).replaceAll("\\s+", " ");
    }

    private static String normalizeId(String id) {
        if (id == null || id.length() > MAX_ID || !id.matches("(?:minecraft:)?[a-z0-9_./-]+"))
            throw fault("invalid_material", "Expected one exact Minecraft material ID without properties or NBT");
        return id.contains(":") ? id : "minecraft:" + id;
    }

    private static List<Entry> runtimeEntries() {
        List<Entry> entries = new ArrayList<>();
        for (Material material : Material.values()) {
            if (material.isLegacy()) continue;
            boolean block = material.isBlock(), item = material.isItem();
            if (!block && !item) continue;
            if (block) {
                // A registry mismatch must fail visibly, never silently shrink the advertised catalog.
                try { Bukkit.createBlockData(material); }
                catch (RuntimeException error) {
                    throw new IllegalStateException("Cannot read runtime block registry entry " + material.getKey(), error);
                }
            }
            entries.add(new Entry(material.getKey().toString(), block, item));
        }
        return entries;
    }

    private static StateDescription runtimeDescription(String id) {
        BlockData data = Bukkit.createBlockData(id);
        try {
            // Paper's public API exposes only createBlockDataStates(), which materializes all
            // combinations. Read the existing StateHolder's property domains instead. These
            // public mapped methods are verified against the pinned Paper 26.2 runtime.
            Object state = data.getClass().getMethod("getState").invoke(data);
            List<String> behavior = new ArrayList<>();
            if (data.getMaterial().hasGravity()) behavior.add("gravity");
            if (data.getMaterial() == Material.WATER || data.getMaterial() == Material.LAVA) behavior.add("fluid");
            if (data instanceof Waterlogged) behavior.add("waterloggable");
            if (data instanceof Door || data instanceof Bed) behavior.add("multi_block");
            if (data instanceof Bisected) behavior.add("half_property");
            if (data instanceof FaceAttachable || data instanceof Attachable) behavior.add("attachment_sensitive");
            if (data instanceof Leaves) behavior.add("leaf_decay");
            if (data.createBlockState() instanceof TileState) behavior.add("block_entity");
            return new StateDescription(data.getAsString(), readProperties(state), List.copyOf(behavior));
        } catch (ReflectiveOperationException | LinkageError error) {
            throw fault("material_properties_unavailable", "Runtime property introspection is unavailable for " + id);
        }
    }

    /** Domain-only adapter, kept separate so tests can cover all value types without a running server. */
    static Map<String, List<String>> readProperties(Object state) throws ReflectiveOperationException {
        Object value = state.getClass().getMethod("getProperties").invoke(state);
        if (!(value instanceof Collection<?> properties) || properties.size() > MAX_PROPERTIES)
            throw fault("material_properties_unavailable", "Runtime property count exceeds the response limit");
        Map<String, List<String>> result = new TreeMap<>();
        int characters = 0;
        for (Object property : properties) {
            String name = (String) property.getClass().getMethod("getName").invoke(property);
            Object possible = property.getClass().getMethod("getPossibleValues").invoke(property);
            if (!(possible instanceof Collection<?> values) || values.isEmpty() || values.size() > MAX_PROPERTY_VALUES)
                throw fault("material_properties_unavailable", "Runtime property domain exceeds the response limit");
            var serializeValue = property.getClass().getMethod("getName", Comparable.class);
            List<String> serialized = new ArrayList<>();
            characters += name.length();
            for (Object candidate : values) {
                String text = (String) serializeValue.invoke(property, candidate);
                characters += text.length();
                if (characters > MAX_DESCRIPTION_CHARS)
                    throw fault("material_properties_unavailable", "Runtime property description exceeds the response limit");
                serialized.add(text);
            }
            if (result.put(name, List.copyOf(serialized)) != null)
                throw fault("material_properties_unavailable", "Runtime returned duplicate property names");
        }
        return Collections.unmodifiableMap(result);
    }

    private static String digest(String input) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(input.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes, 0, 12);
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    private static RpcServer.Fault fault(String code, String message) { return new RpcServer.Fault(code, message); }
}
