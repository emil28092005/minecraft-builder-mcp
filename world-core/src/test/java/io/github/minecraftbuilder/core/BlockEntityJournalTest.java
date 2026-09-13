package io.github.minecraftbuilder.core;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import static org.junit.jupiter.api.Assertions.*;
import static io.github.minecraftbuilder.core.EditEngineTest.*;

/** Exercises the adapter snapshot contract through the actual durable journal and edit state machine. */
final class BlockEntityJournalTest {
    @TempDir Path directory;
    private static final String CHEST = "minecraft:chest[facing=north]";
    private static final String ROTATED = "minecraft:chest[facing=east]";
    private static final String ITEMS = "|private inventory: diamond sword, signed book, custom plugin data";
    static final class EntityWorld implements WorldAccess {
        final Map<BlockPos,String> values = new HashMap<>();
        int writes;
        public String getBlock(BlockPos p) { return state(captureBlock(p)); }
        public String captureBlock(BlockPos p) { return values.getOrDefault(p, AIR); }
        public String prepareBlock(BlockPos p, String desired, String before) {
            if (desired.contains("|")) return desired;
            if (desired.startsWith("minecraft:chest"))
                return desired + (before.contains("|") ? before.substring(before.indexOf('|')) : "|empty inventory");
            return desired;
        }
        public void setBlock(BlockPos p, String desired) { fail("The editor must restore the complete captured value"); }
        public void setCapturedBlock(BlockPos p, String desired) { values.put(p, desired); writes++; }
        private static String state(String value) { return value.split("\\|", 2)[0]; }
    }
    private EditEngine engine(EntityWorld world, Journal journal) throws Exception {
        return new EditEngine(world, state -> state.startsWith("minecraft:"), plan -> {}, journal, LIMITS);
    }
    @Test void overwriteAndUndoAfterRestartRestoresPrivateDataFromDurableJournal() throws Exception {
        EntityWorld world = new EntityWorld(); world.values.put(A, CHEST + ITEMS);
        var journal = new JsonJournal(directory);
        EditEngine original = engine(world, journal);
        Plan plan = prepare(original, Map.of(A, STONE));
        assertEquals(CHEST + ITEMS, plan.changes().get(0).expected());
        assertEquals(0, world.writes, "prepare must not temporarily place a default block");
        String id = start(original, plan);
        assertEquals(OperationStatus.APPLIED, finish(original, id).status());
        assertEquals(STONE, world.captureBlock(A));

        EditEngine restarted = engine(world, new JsonJournal(directory));
        Plan undo = restarted.prepareUndo(id); restarted.persistPlan(undo.id());
        assertEquals(CHEST + ITEMS, undo.changes().get(0).desired());
        assertEquals(OperationStatus.APPLIED, finish(restarted, start(restarted, undo)).status());
        assertEquals(CHEST + ITEMS, world.captureBlock(A));
    }
    @Test void blockDataChangeRetainsContentsAndUndoDetectsManualInventoryChanges() throws Exception {
        EntityWorld world = new EntityWorld(); world.values.put(A, CHEST + ITEMS);
        EditEngine editor = engine(world, new JsonJournal(directory));
        Plan plan = prepare(editor, Map.of(A, ROTATED));
        assertEquals(ROTATED + ITEMS, plan.changes().get(0).desired());
        String id = start(editor, plan);
        assertEquals(OperationStatus.APPLIED, finish(editor, id).status());
        world.values.put(A, ROTATED + "|player deposited a diamond");
        assertEquals(ROTATED, world.getBlock(A), "visible BlockData did not change");
        assertThrows(IllegalStateException.class, () -> editor.prepareUndo(id));
        assertEquals(1, world.writes);
    }
    @Test void inventoryEditDuringJournalIoStopsBeforeAnyWrite() throws Exception {
        EntityWorld world = new EntityWorld(); world.values.put(A, CHEST + ITEMS);
        EditEngine editor = engine(world, new JsonJournal(directory));
        Plan plan = prepare(editor, Map.of(A, STONE)); String id = start(editor, plan);
        SliceIntent intent = nextIntent(editor, id); editor.persistIntent(intent);
        world.values.put(A, CHEST + "|items moved by a hopper");
        assertEquals(OperationStatus.CONFLICT, editor.commitSlice(intent).status());
        assertEquals(0, world.writes);
    }
    @Test void planBudgetStopsPreparationBeforePersistenceOrWorldMutation() throws Exception {
        EntityWorld world = new EntityWorld();
        String large = CHEST + "|" + "x".repeat(1024 * 1024);
        Map<BlockPos,String> desired = new HashMap<>();
        for (int x = 0; x < 9; x++) { var p = new BlockPos(x, 0, 0); world.values.put(p, large); desired.put(p, STONE); }
        var journal = new MemoryJournal(); EditEngine editor = engine(world, journal);
        var error = assertThrows(IllegalArgumentException.class,
            () -> editor.prepare("project", "epoch", REGION, desired, Set.of()));
        assertTrue(error.getMessage().contains("snapshot_budget_exceeded"));
        assertEquals(0, world.writes); assertTrue(journal.plans.isEmpty());
    }
    @Test void plainLegacyJournalStillAppliesAndUndoesWithSnapshotAwareAdapter() throws Exception {
        EntityWorld world = new EntityWorld();
        EditEngine editor = engine(world, new JsonJournal(directory));
        String id = start(editor, prepare(editor, Map.of(A, STONE)));
        assertEquals(OperationStatus.APPLIED, finish(editor, id).status());
        EditEngine restarted = engine(world, new JsonJournal(directory));
        Plan undo = restarted.prepareUndo(id); restarted.persistPlan(undo.id());
        assertEquals(OperationStatus.APPLIED, finish(restarted, start(restarted, undo)).status());
        assertEquals(AIR, world.captureBlock(A));
    }
}
