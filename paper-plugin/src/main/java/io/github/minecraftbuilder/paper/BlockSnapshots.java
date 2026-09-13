package io.github.minecraftbuilder.paper;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.Objects;

/** Private journal representation. MCP responses expose only block data and an opaque digest. */
final class BlockSnapshots {
    private static final String PREFIX = "\u0000mcb-block-v1:";
    static final int MAX_SNAPSHOT_BYTES = 1024 * 1024;
    record Value(String state, String nbt) { }
    static boolean captured(String value) { return value != null && value.startsWith(PREFIX); }
    static String encode(String state, String nbt) {
        Objects.requireNonNull(state); Objects.requireNonNull(nbt);
        if (state.isBlank() || state.length() > 1024 || state.indexOf('\n') >= 0 || state.indexOf('\u0000') >= 0)
            throw new IllegalArgumentException("Invalid captured block data");
        String result = PREFIX + state + "\n" + nbt;
        requireBounded(result);
        return result;
    }
    static Value decode(String value) {
        Objects.requireNonNull(value);
        if (!captured(value)) return new Value(value, null);
        requireBounded(value);
        int split = value.indexOf('\n', PREFIX.length());
        if (split <= PREFIX.length() || split - PREFIX.length() > 1024 || split == value.length() - 1)
            throw new IllegalArgumentException("Invalid stored block snapshot");
        return new Value(value.substring(PREFIX.length(), split), value.substring(split + 1));
    }
    static String state(String value) { return decode(value).state(); }
    static String snapshotId(String value) {
        if (!captured(value)) return null;
        decode(value);
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    static Map<String, String> publicView(String value) {
        String id = snapshotId(value);
        return id == null ? Map.of("state", state(value)) : Map.of("state", state(value), "snapshot_id", id);
    }
    private static void requireBounded(String value) {
        if (value.length() > MAX_SNAPSHOT_BYTES || value.getBytes(StandardCharsets.UTF_8).length > MAX_SNAPSHOT_BYTES)
            throw new IllegalArgumentException("snapshot_budget_exceeded: block entity exceeds the 1 MiB snapshot limit");
    }
    private BlockSnapshots() { }
}
