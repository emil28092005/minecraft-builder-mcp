package io.github.minecraftbuilder.core;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import com.google.gson.JsonParser;
import static org.junit.jupiter.api.Assertions.*;

class JsonJournalTest {
    @TempDir Path temporary;
    @Test void roundTripsDurablePlanAndDetectsContentCorruption() throws Exception {
        JsonJournal journal = new JsonJournal(temporary);
        var engine = EditEngineTest.engine(new EditEngineTest.MemoryWorld(), journal);
        Plan plan = EditEngineTest.prepare(engine, Map.of(EditEngineTest.A, EditEngineTest.STONE));
        assertEquals(plan, new JsonJournal(temporary).loadPlans().get(0));
        Path file = temporary.resolve("plans").resolve(plan.id() + ".json");
        Files.writeString(file, Files.readString(file).replace("minecraft:stone", "minecraft:dirt"));
        assertThrows(IOException.class, () -> new JsonJournal(temporary).loadPlans());
    }
    @Test void strayTemporaryFileDoesNotBecomeACommittedRecord() throws Exception {
        JsonJournal journal = new JsonJournal(temporary);
        Files.writeString(temporary.resolve("operations/.pending-killed.tmp"), "half a record");
        assertTrue(journal.loadOperations().isEmpty());
    }
    @Test void malformedCommittedFileFailsClosed() throws Exception {
        JsonJournal journal = new JsonJournal(temporary);
        Files.writeString(temporary.resolve("operations/bad.json"), "{truncated");
        assertThrows(IOException.class, journal::loadOperations);
    }

    @Test void originalVersionOneOperationWithoutAbandonmentFieldsStillLoads() throws Exception {
        JsonJournal journal = new JsonJournal(temporary);
        var world = new EditEngineTest.MemoryWorld(); var engine = EditEngineTest.engine(world, journal);
        Plan plan = EditEngineTest.prepare(engine, Map.of(EditEngineTest.A, EditEngineTest.STONE));
        String id = EditEngineTest.start(engine, plan);
        Path path = temporary.resolve("operations").resolve(id + ".json");
        var envelope = JsonParser.parseString(Files.readString(path)).getAsJsonObject();
        var payload = JsonParser.parseString(envelope.get("payload").getAsString()).getAsJsonObject();
        payload.remove("abandonedRevision"); payload.remove("abandonedPositions");
        String originalPayload = payload.toString();
        envelope.addProperty("payload", originalPayload);
        envelope.addProperty("sha256", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
            .digest(originalPayload.getBytes(StandardCharsets.UTF_8))));
        Files.writeString(path, envelope.toString());
        var restarted = EditEngineTest.engine(world, new JsonJournal(temporary));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, restarted.status(id).status());
        assertEquals(0, restarted.reviewRecovery(id).positions());
    }
}
