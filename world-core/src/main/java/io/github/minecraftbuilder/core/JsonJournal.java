package io.github.minecraftbuilder.core;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

/** Atomic, checksummed JSON snapshots. Requires a filesystem supporting atomic rename and directory fsync. */
public final class JsonJournal implements Journal {
    private static final long MAX_RECORD_BYTES = 128L * 1024 * 1024;
    private final Gson gson = new Gson();
    private final Path plans;
    private final Path operations;
    private record Envelope(int format, String kind, String id, String payload, String sha256) { }

    public JsonJournal(Path root) throws IOException {
        Path absolute = root.toAbsolutePath();
        Files.createDirectories(absolute);
        plans = absolute.resolve("plans"); operations = absolute.resolve("operations");
        Files.createDirectories(plans); Files.createDirectories(operations);
        syncDirectory(absolute);
        if (absolute.getParent() != null) syncDirectory(absolute.getParent());
    }
    @Override public synchronized void savePlan(Plan plan) throws IOException { save(plans, "plan", plan.id(), plan); }
    @Override public synchronized void saveOperation(OperationSnapshot operation) throws IOException {
        save(operations, "operation", operation.id(), operation);
    }
    @Override public synchronized List<Plan> loadPlans() throws IOException { return load(plans, "plan", Plan.class); }
    @Override public synchronized List<OperationSnapshot> loadOperations() throws IOException {
        return load(operations, "operation", OperationSnapshot.class);
    }
    private void save(Path directory, String kind, String id, Object value) throws IOException {
        requireId(id);
        String payload = gson.toJson(value);
        byte[] bytes = gson.toJson(new Envelope(1, kind, id, payload, checksum(payload))).getBytes(StandardCharsets.UTF_8);
        if (bytes.length > MAX_RECORD_BYTES) throw new IOException("Journal record exceeds size limit");
        Path temporary = Files.createTempFile(directory, ".pending-", ".tmp");
        try {
            try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
                ByteBuffer buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) channel.write(buffer);
                channel.force(true);
            }
            Files.move(temporary, directory.resolve(id + ".json"), StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING);
            syncDirectory(directory);
        } finally { Files.deleteIfExists(temporary); }
    }
    private <T> List<T> load(Path directory, String kind, Class<T> type) throws IOException {
        List<T> result = new ArrayList<>();
        try (var files = Files.list(directory)) {
            for (Path file : files.filter(p -> p.getFileName().toString().endsWith(".json")).sorted().toList()) {
                if (!Files.isRegularFile(file) || Files.size(file) > MAX_RECORD_BYTES)
                    throw new IOException("Invalid journal record: " + file.getFileName());
                try {
                    Envelope envelope = gson.fromJson(Files.readString(file), Envelope.class);
                    if (envelope == null || envelope.format != 1 || !kind.equals(envelope.kind)
                        || !file.getFileName().toString().equals(envelope.id + ".json")
                        || envelope.payload == null || !checksum(envelope.payload).equals(envelope.sha256))
                        throw new IOException("Corrupt or unsupported journal: " + file.getFileName());
                    requireId(envelope.id);
                    T value = gson.fromJson(envelope.payload, type);
                    String recordId = value instanceof Plan p ? p.id() : ((OperationSnapshot) value).id();
                    if (!envelope.id.equals(recordId)) throw new IOException("Mismatched journal identity");
                    result.add(value);
                } catch (JsonParseException | IllegalArgumentException | NullPointerException e) {
                    throw new IOException("Cannot parse journal: " + file.getFileName(), e);
                }
            }
        }
        return List.copyOf(result);
    }
    private static void requireId(String id) throws IOException {
        try { if (!UUID.fromString(id).toString().equals(id)) throw new IllegalArgumentException(); }
        catch (IllegalArgumentException | NullPointerException e) { throw new IOException("Invalid journal ID", e); }
    }
    private static String checksum(String payload) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(payload.getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    private static void syncDirectory(Path directory) throws IOException {
        try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) { channel.force(true); }
    }
}
