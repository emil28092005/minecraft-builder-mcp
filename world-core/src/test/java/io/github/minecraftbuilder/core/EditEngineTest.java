package io.github.minecraftbuilder.core;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.io.IOException;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;

class EditEngineTest {
    static final String AIR = "minecraft:air", STONE = "minecraft:stone", GOLD = "minecraft:gold_block";
    static final BlockPos A = new BlockPos(0, 0, 0), B = new BlockPos(1, 0, 0), C = new BlockPos(2, 0, 0);
    static final Region REGION = new Region("world", new BlockPos(-20, -20, -20), new BlockPos(20, 20, 20));
    static final Limits LIMITS = new Limits(4096, 16, 1, 1_000_000_000, 600_000, 4);
    @TempDir Path temporary;

    static class MemoryWorld implements WorldAccess {
        final Map<BlockPos, String> blocks = new HashMap<>(); int writes;
        Runnable afterWrite;
        @Override public String getBlock(BlockPos position) { return blocks.getOrDefault(position, AIR); }
        @Override public void setBlock(BlockPos position, String state) {
            blocks.put(position, state); writes++;
            if (afterWrite != null) afterWrite.run();
        }
    }
    static class MemoryJournal implements Journal {
        final Map<String, Plan> plans = new HashMap<>();
        final Map<String, OperationSnapshot> operations = new HashMap<>();
        boolean fail;
        @Override public void savePlan(Plan plan) throws IOException { check(); plans.put(plan.id(), plan); }
        @Override public void saveOperation(OperationSnapshot op) throws IOException { check(); operations.put(op.id(), op); }
        @Override public List<Plan> loadPlans() { return List.copyOf(plans.values()); }
        @Override public List<OperationSnapshot> loadOperations() { return List.copyOf(operations.values()); }
        void check() throws IOException { if (fail) throw new IOException("Injected disk failure"); }
    }
    static EditEngine engine(MemoryWorld world, Journal journal) throws IOException {
        return new EditEngine(world, state -> Set.of(AIR, STONE, GOLD).contains(state), plan -> {}, journal, LIMITS);
    }
    static Plan prepare(EditEngine engine, Map<BlockPos, String> desired) throws IOException {
        Plan plan = engine.prepare("project", "epoch", REGION, desired, Set.of());
        engine.persistPlan(plan.id()); return plan;
    }
    static String start(EditEngine engine, Plan plan) throws IOException {
        String id = engine.start(plan.id(), "request-" + plan.id()).id(); engine.flushOperation(id); return id;
    }
    static SliceIntent nextIntent(EditEngine engine, String id) throws IOException {
        for (int i = 0; i < 100; i++) {
            var intent = engine.stageSlice(id);
            if (intent.isPresent()) return intent.get();
            OperationView view = engine.status(id);
            if (view.needsFlush()) engine.flushOperation(id);
            if (view.status().terminal()) throw new AssertionError("Terminal before intent: " + view);
        }
        throw new AssertionError("No intent");
    }
    static void slice(EditEngine engine, String id) throws IOException {
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent); engine.commitSlice(intent); engine.flushOperation(id);
    }
    static OperationView finish(EditEngine engine, String id) throws IOException {
        for (int i = 0; i < 1000; i++) {
            OperationView view = engine.status(id);
            if (view.needsFlush()) engine.flushOperation(id);
            if (view.status().terminal()) return engine.status(id);
            var intent = engine.stageSlice(id);
            if (intent.isPresent()) { engine.persistIntent(intent.get()); engine.commitSlice(intent.get()); }
        }
        throw new AssertionError("Operation failed to terminate");
    }

    @Test void manualChangeAnywhereBeforeApplyStopsEntirePlan() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        Plan plan = prepare(engine, Map.of(A, STONE, B, STONE, C, STONE));
        world.blocks.put(C, GOLD); String id = start(engine, plan);
        assertEquals(OperationStatus.CONFLICT, finish(engine, id).status());
        assertEquals(0, world.writes); assertEquals(GOLD, world.getBlock(C));
    }
    @Test void ioRaceStopsBeforeAnySliceWrites() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent);
        world.blocks.put(A, GOLD); OperationView result = engine.commitSlice(intent);
        assertEquals(OperationStatus.CONFLICT, result.status()); assertEquals(0, world.writes);
    }
    @Test void noWriteBeforeDurableIntentAndNoNextSliceBeforeDurableReceipt() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        SliceIntent intent = nextIntent(engine, id);
        assertThrows(IllegalStateException.class, () -> engine.commitSlice(intent)); assertEquals(0, world.writes);
        engine.persistIntent(intent); engine.commitSlice(intent);
        assertThrows(IllegalStateException.class, () -> engine.stageSlice(id));
        assertEquals(1, world.writes);
    }
    @Test void editBetweenSlicesKeepsConfirmedPartialResult() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE, C, STONE)));
        slice(engine, id); world.blocks.put(B, GOLD);
        OperationView result = finish(engine, id);
        assertEquals(OperationStatus.CONFLICT, result.status()); assertEquals(1, result.written());
        assertEquals(STONE, world.getBlock(A)); assertEquals(GOLD, world.getBlock(B)); assertEquals(AIR, world.getBlock(C));
    }
    @Test void externalChangeToDesiredIsSkippedAndNotOwnedByUndo() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        Plan plan = prepare(engine, Map.of(A, STONE, B, STONE)); world.blocks.put(A, STONE);
        String id = start(engine, plan); OperationView result = finish(engine, id);
        assertEquals(OperationStatus.APPLIED, result.status()); assertEquals(1, result.written()); assertEquals(1, result.skipped());
        Plan undo = engine.prepareUndo(id); engine.persistPlan(undo.id()); finish(engine, start(engine, undo));
        assertEquals(STONE, world.getBlock(A)); assertEquals(AIR, world.getBlock(B));
    }
    @Test void readDependencyChangeBetweenSlicesStopsFutureWrites() throws Exception {
        MemoryWorld world = new MemoryWorld(); world.blocks.put(C, STONE);
        EditEngine engine = engine(world, new MemoryJournal());
        Plan plan = engine.prepare("project", "epoch", REGION, Map.of(A, STONE, B, STONE), Set.of(C)); engine.persistPlan(plan.id());
        String id = start(engine, plan); slice(engine, id); world.blocks.put(C, AIR);
        OperationView result = finish(engine, id);
        assertEquals(OperationStatus.CONFLICT, result.status()); assertEquals(1, result.written());
        assertEquals(AIR, world.getBlock(B)); assertEquals(C, result.conflicts().get(0).pos());
    }
    @Test void dependencyWrittenByThisOperationUsesConfirmedDesiredValue() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        Plan plan = engine.prepare("project", "epoch", REGION, Map.of(A, STONE, B, STONE), Set.of(A)); engine.persistPlan(plan.id());
        assertEquals(OperationStatus.APPLIED, finish(engine, start(engine, plan)).status());
    }
    @Test void cancellationAfterOneSliceCanBeUndoneWithoutTouchingRemainingBlocks() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        slice(engine, id); engine.cancel(id);
        assertEquals(OperationStatus.CANCELLED, finish(engine, id).status());
        Plan undo = engine.prepareUndo(id); engine.persistPlan(undo.id()); finish(engine, start(engine, undo));
        assertEquals(AIR, world.getBlock(A)); assertEquals(AIR, world.getBlock(B)); assertEquals(2, world.writes);
    }
    @Test void cancellationWhileIntentIsPersistedWritesNothing() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent); engine.cancel(id);
        assertEquals(OperationStatus.CANCELLED, engine.commitSlice(intent).status()); assertEquals(0, world.writes);
    }
    @Test void repeatedApplyUsesSameOperationAcrossRestartAndRejectsDifferentPlan() throws Exception {
        MemoryWorld world = new MemoryWorld(); JsonJournal journal = new JsonJournal(temporary);
        EditEngine engine = engine(world, journal); Plan plan = prepare(engine, Map.of(A, STONE));
        String id = start(engine, plan); finish(engine, id);
        assertEquals(id, engine.start(plan.id(), "request-" + plan.id()).id()); assertEquals(1, world.writes);
        EditEngine restarted = engine(world, new JsonJournal(temporary));
        assertEquals(id, restarted.start(plan.id(), "request-" + plan.id()).id()); assertEquals(1, world.writes);
        Plan other = prepare(restarted, Map.of(B, STONE));
        assertThrows(IllegalArgumentException.class, () -> restarted.start(other.id(), "request-" + plan.id()));
    }
    @Test void undoRejectsExternalEditBeforePreparationOrAfterPreparation() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE))); finish(engine, id);
        world.blocks.put(A, GOLD); assertThrows(IllegalStateException.class, () -> engine.prepareUndo(id));
        world.blocks.put(A, STONE); Plan undo = engine.prepareUndo(id); engine.persistPlan(undo.id());
        world.blocks.put(A, GOLD);
        assertEquals(OperationStatus.CONFLICT, finish(engine, start(engine, undo)).status()); assertEquals(GOLD, world.getBlock(A));
    }
    @Test void undoRejectsKnownLaterWriterEvenWhenCurrentValueMatchesOriginalAfter() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String first = start(engine, prepare(engine, Map.of(A, STONE))); finish(engine, first);
        finish(engine, start(engine, prepare(engine, Map.of(A, GOLD))));
        finish(engine, start(engine, prepare(engine, Map.of(A, STONE))));
        assertThrows(IllegalStateException.class, () -> engine.prepareUndo(first));
    }
    @Test void unsupportedSourceOrDestinationAndOutOfBoundsAreRejectedBeforeWriting() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        assertThrows(IllegalArgumentException.class, () -> prepare(engine, Map.of(A, "minecraft:chest")));
        world.blocks.put(A, "minecraft:chest");
        assertThrows(IllegalArgumentException.class, () -> prepare(engine, Map.of(A, AIR)));
        assertThrows(IllegalArgumentException.class, () -> prepare(engine, Map.of(new BlockPos(21, 0, 0), STONE)));
        assertThrows(IllegalArgumentException.class, () -> engine.prepare("project", "epoch", REGION, Map.of(B, STONE), Set.of(new BlockPos(0, 21, 0))));
        assertEquals(0, world.writes);
    }
    @Test void permissionRevokedDuringIntentIoStopsSlice() throws Exception {
        MemoryWorld world = new MemoryWorld(); AtomicBoolean allowed = new AtomicBoolean(true);
        EditEngine engine = new EditEngine(world, state -> true, plan -> {
            if (!allowed.get()) throw new IllegalStateException("access revoked");
        }, new MemoryJournal(), LIMITS);
        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent); allowed.set(false);
        assertEquals(OperationStatus.FAILED, engine.commitSlice(intent).status()); assertEquals(0, world.writes);
    }
    @Test void failedIntentPersistenceNeverWritesAndBlocksFurtherOperations() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine engine = engine(world, journal);
        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(engine, id); journal.fail = true;
        assertThrows(IOException.class, () -> engine.persistIntent(intent));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, engine.status(id).status()); assertEquals(0, world.writes);
        journal.fail = false; Plan other = prepare(engine, Map.of(B, STONE));
        assertThrows(IllegalStateException.class, () -> engine.start(other.id(), "other"));
    }
    @Test void failedReceiptPersistenceRestartsAsUncertainWithoutReplay() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine engine = engine(world, journal);
        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent); engine.commitSlice(intent);
        journal.fail = true; assertThrows(IOException.class, () -> engine.flushOperation(id)); journal.fail = false;
        EditEngine restarted = engine(world, journal);
        assertEquals(OperationStatus.RECOVERY_REQUIRED, restarted.status(id).status()); assertEquals(1, world.writes);
        assertEquals("matches_after", restarted.inspectRecovery(id, 0, 1).get(0).reason());
        assertTrue(restarted.stageSlice(id).isEmpty()); assertEquals(1, world.writes);
    }
    @Test void crashBeforeWriteRecognizesBeforeAndForeignStatesWithoutChangingEither() throws Exception {
        MemoryWorld world = new MemoryWorld(); JsonJournal journal = new JsonJournal(temporary); EditEngine engine = engine(world, journal);
        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent);
        EditEngine restarted = engine(world, new JsonJournal(temporary));
        assertEquals("matches_before", restarted.inspectRecovery(id, 0, 1).get(0).reason());
        world.blocks.put(A, GOLD); assertEquals("foreign_state", restarted.inspectRecovery(id, 0, 1).get(0).reason());
        assertEquals(0, world.writes);
    }
    @Test void worldSetterThrowAfterMutationPreservesConfirmedReceiptForUndo() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        world.afterWrite = () -> { throw new IllegalStateException("post-write callback failed"); };
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        OperationView result = finish(engine, id);
        assertEquals(OperationStatus.FAILED, result.status()); assertEquals(1, result.written());
        world.afterWrite = null; Plan undo = engine.prepareUndo(id); engine.persistPlan(undo.id()); finish(engine, start(engine, undo));
        assertEquals(AIR, world.getBlock(A));
    }
    @Test void nestedWorldCallbackCannotOverwriteLaterPositionInSameSlice() throws Exception {
        MemoryWorld world = new MemoryWorld();
        EditEngine engine = new EditEngine(world, state -> true, plan -> {}, new MemoryJournal(),
            new Limits(10, 10, 10, 1_000_000_000, 600_000, 4));
        world.afterWrite = () -> world.blocks.put(B, GOLD);
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        OperationView result = finish(engine, id);
        assertEquals(OperationStatus.CONFLICT, result.status()); assertEquals(1, result.written()); assertEquals(GOLD, world.getBlock(B));
    }
    @Test void finalAuditDetectsChangeToAlreadyWrittenBlock() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        slice(engine, id); slice(engine, id); world.blocks.put(A, GOLD);
        assertEquals(OperationStatus.CONFLICT, finish(engine, id).status()); assertEquals(GOLD, world.getBlock(A));
    }
    @Test void returnedPlansAndIntentsAreImmutable() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        Map<BlockPos, String> desired = new LinkedHashMap<>(Map.of(A, STONE)); Plan plan = prepare(engine, desired);
        desired.put(B, GOLD); assertEquals(1, plan.changes().size());
        assertThrows(UnsupportedOperationException.class, () -> plan.changes().clear());
        SliceIntent intent = nextIntent(engine, start(engine, plan));
        assertThrows(UnsupportedOperationException.class, () -> intent.changes().clear());
        SliceIntent copy = new SliceIntent(intent.operationId(), intent.sequence(), intent.changes());
        assertThrows(IllegalArgumentException.class, () -> engine.persistIntent(copy));
    }

    @Test void stalledJournalDoesNotBlockStatusOrCancelAndDoesNotLoseCancellation() throws Exception {
        CountDownLatch saving = new CountDownLatch(1), release = new CountDownLatch(1);
        MemoryJournal journal = new MemoryJournal() {
            @Override public void saveOperation(OperationSnapshot op) throws IOException {
                saving.countDown();
                try { if (!release.await(5, TimeUnit.SECONDS)) throw new IOException("Test journal timeout"); }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException(e); }
                super.saveOperation(op);
            }
        };
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, journal);
        Plan plan = prepare(engine, Map.of(A, STONE)); String id = engine.start(plan.id(), "request").id();
        CompletableFuture<Void> flushing = CompletableFuture.runAsync(() -> {
            try { engine.flushOperation(id); } catch (IOException e) { throw new RuntimeException(e); }
        });
        assertTrue(saving.await(2, TimeUnit.SECONDS));
        try {
            var cancellation = CompletableFuture.supplyAsync(() -> { engine.status(id); return engine.cancel(id); });
            assertTrue(cancellation.get(1, TimeUnit.SECONDS).cancellationRequested());
        } finally { release.countDown(); }
        flushing.get(2, TimeUnit.SECONDS);
        assertTrue(engine.status(id).needsFlush());
        engine.flushOperation(id);
        assertEquals(OperationStatus.CANCELLED, finish(engine, id).status()); assertEquals(0, world.writes);
    }

    @Test void storedPlanIsRecheckedAgainstChangedBlockPolicy() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal();
        Plan plan = prepare(engine(world, journal), Map.of(A, STONE));
        EditEngine restricted = new EditEngine(world, state -> AIR.equals(state), ignored -> {}, journal, LIMITS);
        assertEquals(OperationStatus.CONFLICT, finish(restricted, start(restricted, plan)).status());
        assertEquals(0, world.writes);
    }

    @Test void pendingIndexRetainsDirtyTerminalStateUntilFlushAndExcludesFinishedHistory() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        Plan first = prepare(engine, Map.of());
        String firstId = engine.start(first.id(), "empty").id();
        assertEquals(OperationStatus.APPLIED, engine.status(firstId).status());
        assertEquals(List.of(firstId), engine.pendingOperations().stream().map(OperationView::id).toList());
        engine.flushOperation(firstId); assertTrue(engine.pendingOperations().isEmpty());

        String id = start(engine, prepare(engine, Map.of(A, STONE)));
        assertEquals(List.of(id), engine.pendingOperations().stream().map(OperationView::id).toList());
        engine.cancel(id); engine.stageSlice(id);
        assertEquals(OperationStatus.CANCELLED, engine.pendingOperations().get(0).status());
        engine.flushOperation(id); assertTrue(engine.pendingOperations().isEmpty());
        assertEquals(2, engine.operationCount());
    }

    @Test void recentContextAndSchedulerRemainBoundedWithLargeCompletedHistory() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        List<String> ids = new java.util.ArrayList<>();
        for (int i = 0; i < 150; i++) ids.add(start(engine, prepare(engine, Map.of())));
        assertEquals(150, engine.operationCount()); assertTrue(engine.pendingOperations().isEmpty());
        assertEquals(7, engine.recentOperations(7).size());
        assertEquals(ids.get(149), engine.recentOperations(7).get(0).id());
        assertEquals(ids.get(143), engine.recentOperations(7).get(6).id());
        assertTrue(engine.recentOperations(0).isEmpty());
        assertThrows(IllegalArgumentException.class, () -> engine.recentOperations(101));
    }

    @Test void restartedIndexesIncludeUnflushedRecoveryWithoutAllTerminalHistory() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal();
        EditEngine engine = engine(world, journal);
        start(engine, prepare(engine, Map.of()));
        String active = start(engine, prepare(engine, Map.of(A, STONE)));
        EditEngine restarted = engine(world, journal);
        assertEquals(2, restarted.operationCount()); assertEquals(2, restarted.recentOperations(10).size());
        assertEquals(List.of(active), restarted.pendingOperations().stream().map(OperationView::id).toList());
        assertEquals(OperationStatus.RECOVERY_REQUIRED, restarted.pendingOperations().get(0).status());
        restarted.flushOperation(active); assertTrue(restarted.pendingOperations().isEmpty());
        Plan other = prepare(restarted, Map.of(B, STONE));
        assertThrows(IllegalStateException.class, () -> restarted.start(other.id(), "still-blocked"));
    }

    @Test void observedExternalAbaRejectsUndoEvenWhenStateReturnsToDesired() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String source = start(engine, prepare(engine, Map.of(A, STONE))); finish(engine, source);
        world.blocks.put(A, AIR); engine.recordExternal(A);
        world.blocks.put(A, STONE); engine.recordExternal(A);
        assertThrows(IllegalStateException.class, () -> engine.prepareUndo(source));
        assertEquals(1, world.writes); assertEquals(STONE, world.getBlock(A));
    }

    @Test void observedExternalAbaDuringUndoIntentPersistenceIsRecheckedAtCommit() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String source = start(engine, prepare(engine, Map.of(A, STONE))); finish(engine, source);
        Plan undo = engine.prepareUndo(source); engine.persistPlan(undo.id());
        String inverse = start(engine, undo); SliceIntent intent = nextIntent(engine, inverse); engine.persistIntent(intent);
        world.blocks.put(A, AIR); engine.recordExternal(A); world.blocks.put(A, STONE); engine.recordExternal(A);
        assertEquals(OperationStatus.CONFLICT, engine.commitSlice(intent).status());
        assertEquals(1, world.writes); assertEquals(STONE, world.getBlock(A));
    }

    @Test void externalNotificationForUnownedPositionDoesNotAffectUnrelatedUndo() throws Exception {
        MemoryWorld world = new MemoryWorld(); EditEngine engine = engine(world, new MemoryJournal());
        String source = start(engine, prepare(engine, Map.of(A, STONE))); finish(engine, source);
        engine.recordExternal(B);
        Plan undo = engine.prepareUndo(source); engine.persistPlan(undo.id());
        assertEquals(OperationStatus.APPLIED, finish(engine, start(engine, undo)).status());
        assertEquals(AIR, world.getBlock(A));
    }

    @Test void recoveryInspectsEarlierConfirmedSlicesAndUncertainCurrentSliceTogether() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine engine = engine(world, journal);
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        slice(engine, id);
        SliceIntent second = nextIntent(engine, id); engine.persistIntent(second);
        EditEngine restarted = engine(world, journal);
        assertEquals(A, restarted.inspectRecovery(id, 0, 1).get(0).pos());
        assertEquals("matches_after", restarted.inspectRecovery(id, 0, 1).get(0).reason());
        assertEquals(B, restarted.inspectRecovery(id, 1, 1).get(0).pos());
        assertEquals("matches_before", restarted.inspectRecovery(id, 1, 1).get(0).reason());
        assertEquals(1, world.writes);
    }

    @Test void crashInsideSliceRecognizesMixedWorldStatesWithoutAssumingAllWritesHappened() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal();
        EditEngine engine = new EditEngine(world, state -> true, ignored -> {}, journal,
            new Limits(10, 10, 10, 1_000_000_000, 600_000, 4));
        String id = start(engine, prepare(engine, Map.of(A, STONE, B, STONE)));
        SliceIntent intent = nextIntent(engine, id); engine.persistIntent(intent);
        // Model process death after one write but before any in-memory/durable receipt can be trusted.
        world.setBlock(A, STONE);
        EditEngine restarted = engine(world, journal);
        assertEquals(OperationStatus.RECOVERY_REQUIRED, restarted.status(id).status());
        assertEquals("matches_after", restarted.inspectRecovery(id, 0, 1).get(0).reason());
        assertEquals("matches_before", restarted.inspectRecovery(id, 1, 1).get(0).reason());
        assertEquals(0, restarted.status(id).written()); assertEquals(1, world.writes);
    }

    @Test void controlCharactersCannotCrossIdempotencyProjectScope() throws Exception {
        EditEngine engine = engine(new MemoryWorld(), new MemoryJournal());
        assertThrows(IllegalArgumentException.class,
            () -> engine.prepare("project\u0000key", "epoch", REGION, Map.of(), Set.of()));
        Plan plan = prepare(engine, Map.of());
        assertThrows(IllegalArgumentException.class, () -> engine.start(plan.id(), "key\u0000suffix"));
    }

    @Test void recoveryAbandonRequiresUnchangedReviewedMaskAndDoesNotWriteWorld() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE, B, STONE)));
        slice(initial, id); SliceIntent second = nextIntent(initial, id); initial.persistIntent(second);
        EditEngine recovered = engine(world, journal);
        RecoveryReview review = recovered.reviewRecovery(id);
        assertEquals(2, review.positions()); assertEquals(1, review.matchesBefore()); assertEquals(1, review.matchesAfter());
        assertEquals(review.currentDigest(), recovered.reviewRecovery(id).currentDigest());
        world.blocks.put(B, "minecraft:chest");
        assertThrows(IllegalStateException.class, () -> recovered.abandonRecovery(id, review.currentDigest()));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, recovered.status(id).status());
        RecoveryReview changed = recovered.reviewRecovery(id); assertEquals(1, changed.foreignStates());
        OperationView abandoned = recovered.abandonRecovery(id, changed.currentDigest());
        assertEquals(OperationStatus.FAILED, abandoned.status()); assertTrue(abandoned.needsFlush());
        assertEquals(1, world.writes); assertEquals("minecraft:chest", world.getBlock(B));
        Plan next = prepare(recovered, Map.of(C, STONE));
        assertThrows(IllegalStateException.class, () -> recovered.start(next.id(), "before-abandonment-flush"));
        recovered.flushOperation(id);
        assertThrows(IllegalStateException.class, () -> recovered.prepareUndo(id));
        assertEquals(OperationStatus.APPLIED, finish(recovered, start(recovered, next)).status());
        assertEquals("minecraft:chest", world.getBlock(B));
    }

    @Test void crashBeforeAbandonmentFlushRetainsRecoveryLatchAndOriginalMask() throws Exception {
        MemoryWorld world = new MemoryWorld(); JsonJournal journal = new JsonJournal(temporary); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE)));
        SliceIntent intent = nextIntent(initial, id); initial.persistIntent(intent);
        EditEngine recovered = engine(world, new JsonJournal(temporary));
        recovered.abandonRecovery(id, recovered.reviewRecovery(id).currentDigest());
        EditEngine crashedAgain = engine(world, new JsonJournal(temporary));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, crashedAgain.status(id).status());
        assertEquals(1, crashedAgain.reviewRecovery(id).positions());
        Plan next = prepare(crashedAgain, Map.of(B, STONE));
        assertThrows(IllegalStateException.class, () -> crashedAgain.start(next.id(), "still-unresolved"));
        assertEquals(0, world.writes);
    }

    @Test void failedAbandonmentFlushKeepsMaskForAnotherExplicitReview() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE, B, STONE)));
        slice(initial, id); SliceIntent second = nextIntent(initial, id); initial.persistIntent(second);
        EditEngine recovered = engine(world, journal);
        recovered.abandonRecovery(id, recovered.reviewRecovery(id).currentDigest());
        journal.fail = true; assertThrows(IOException.class, () -> recovered.flushOperation(id));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, recovered.status(id).status());
        assertEquals(2, recovered.reviewRecovery(id).positions());
        journal.fail = false;
        // Even a persisted recovery marker carrying prior abandonment metadata must remain blocked.
        recovered.flushOperation(id);
        EditEngine restarted = engine(world, journal);
        assertEquals(OperationStatus.RECOVERY_REQUIRED, restarted.status(id).status());
        assertEquals(2, restarted.reviewRecovery(id).positions());
        restarted.abandonRecovery(id, restarted.reviewRecovery(id).currentDigest()); restarted.flushOperation(id);
        assertEquals(OperationStatus.APPLIED, finish(restarted, start(restarted, prepare(restarted, Map.of(C, STONE)))).status());
    }

    @Test void durableAbandonmentInvalidatesEarlierOwnershipAcrossRestartButAllowsNewHistory() throws Exception {
        MemoryWorld world = new MemoryWorld(); JsonJournal journal = new JsonJournal(temporary); EditEngine initial = engine(world, journal);
        String first = start(initial, prepare(initial, Map.of(A, STONE))); finish(initial, first);
        String interrupted = start(initial, prepare(initial, Map.of(A, GOLD)));
        SliceIntent intent = nextIntent(initial, interrupted); initial.persistIntent(intent);
        EditEngine recovered = engine(world, new JsonJournal(temporary));
        recovered.abandonRecovery(interrupted, recovered.reviewRecovery(interrupted).currentDigest()); recovered.flushOperation(interrupted);
        assertThrows(IllegalStateException.class, () -> recovered.prepareUndo(first));
        EditEngine restarted = engine(world, new JsonJournal(temporary));
        assertEquals(OperationStatus.FAILED, restarted.status(interrupted).status());
        assertTrue(restarted.pendingOperations().isEmpty());
        assertThrows(IllegalStateException.class, () -> restarted.prepareUndo(first));
        assertThrows(IllegalStateException.class, () -> restarted.prepareUndo(interrupted));
        String latest = start(restarted, prepare(restarted, Map.of(A, GOLD))); finish(restarted, latest);
        EditEngine lastRestart = engine(world, new JsonJournal(temporary));
        Plan undoLatest = lastRestart.prepareUndo(latest); lastRestart.persistPlan(undoLatest.id());
        assertEquals(OperationStatus.APPLIED, finish(lastRestart, start(lastRestart, undoLatest)).status());
        assertEquals(STONE, world.getBlock(A));
    }

    @Test void digestCannotAbandonAnotherOperationWithSameBlockContents() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal firstJournal = new MemoryJournal(), secondJournal = new MemoryJournal();
        EditEngine first = engine(world, firstJournal), second = engine(world, secondJournal);
        String firstId = start(first, prepare(first, Map.of(A, STONE)));
        String secondId = start(second, prepare(second, Map.of(A, STONE)));
        first.persistIntent(nextIntent(first, firstId)); second.persistIntent(nextIntent(second, secondId));
        EditEngine recoveredFirst = engine(world, firstJournal), recoveredSecond = engine(world, secondJournal);
        String firstDigest = recoveredFirst.reviewRecovery(firstId).currentDigest();
        assertThrows(IllegalStateException.class, () -> recoveredSecond.abandonRecovery(secondId, firstDigest));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, recoveredSecond.status(secondId).status());
        assertEquals(0, world.writes);
    }

    @Test void queuedOperationWithNoIntentCanBeExplicitlyAbandonedWithoutInventingWrites() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE)));
        EditEngine recovered = engine(world, journal);
        RecoveryReview review = recovered.reviewRecovery(id); assertEquals(0, review.positions());
        recovered.abandonRecovery(id, review.currentDigest()); recovered.flushOperation(id);
        assertEquals(0, world.writes);
        assertEquals(OperationStatus.APPLIED, finish(recovered, start(recovered, prepare(recovered, Map.of(B, STONE)))).status());
    }

    @Test void oldRecoveryFlushCannotAcknowledgeNewerAbandonment() throws Exception {
        AtomicBoolean block = new AtomicBoolean(false);
        CountDownLatch saving = new CountDownLatch(1), release = new CountDownLatch(1);
        MemoryJournal journal = new MemoryJournal() {
            @Override public void saveOperation(OperationSnapshot op) throws IOException {
                if (block.get()) {
                    saving.countDown();
                    try { if (!release.await(5, TimeUnit.SECONDS)) throw new IOException("Test journal timeout"); }
                    catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException(e); }
                }
                super.saveOperation(op);
            }
        };
        MemoryWorld world = new MemoryWorld(); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE)));
        initial.persistIntent(nextIntent(initial, id));
        EditEngine recovered = engine(world, journal); block.set(true);
        CompletableFuture<Void> oldFlush = CompletableFuture.runAsync(() -> {
            try { recovered.flushOperation(id); } catch (IOException e) { throw new RuntimeException(e); }
        });
        assertTrue(saving.await(2, TimeUnit.SECONDS));
        try { recovered.abandonRecovery(id, recovered.reviewRecovery(id).currentDigest()); }
        finally { release.countDown(); }
        oldFlush.get(2, TimeUnit.SECONDS); block.set(false);
        assertTrue(recovered.status(id).needsFlush());
        Plan next = prepare(recovered, Map.of(B, STONE));
        assertThrows(IllegalStateException.class, () -> recovered.start(next.id(), "stale-flush"));
        recovered.flushOperation(id);
        assertEquals(OperationStatus.APPLIED, finish(recovered, start(recovered, next)).status());
    }

    @Test void EveryUnresolvedOperationMustBeDurablyAbandonedBeforeNewWrites() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal firstJournal = new MemoryJournal(), secondJournal = new MemoryJournal();
        EditEngine first = engine(world, firstJournal), second = engine(world, secondJournal);
        String firstId = start(first, prepare(first, Map.of(A, STONE)));
        String secondId = start(second, prepare(second, Map.of(B, STONE)));
        first.persistIntent(nextIntent(first, firstId)); second.persistIntent(nextIntent(second, secondId));
        firstJournal.plans.putAll(secondJournal.plans); firstJournal.operations.putAll(secondJournal.operations);
        EditEngine recovered = engine(world, firstJournal);
        recovered.abandonRecovery(firstId, recovered.reviewRecovery(firstId).currentDigest()); recovered.flushOperation(firstId);
        Plan next = prepare(recovered, Map.of(C, STONE));
        assertThrows(IllegalStateException.class, () -> recovered.start(next.id(), "other-unresolved"));
        recovered.abandonRecovery(secondId, recovered.reviewRecovery(secondId).currentDigest()); recovered.flushOperation(secondId);
        assertEquals(OperationStatus.APPLIED, finish(recovered, start(recovered, next)).status());
    }

    @Test void recoveryCanAbandonWithWritesPausedWhileStillEnforcingContextRights() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE)));
        initial.persistIntent(nextIntent(initial, id));
        AtomicBoolean contextAuthorized = new AtomicBoolean(true);
        ContextGuard guard = new ContextGuard() {
            private void context(Plan plan) {
                if (!contextAuthorized.get() || !plan.projectId().equals("project") || !plan.worldEpoch().equals("epoch")
                    || !plan.region().equals(REGION)) throw new SecurityException("Context or owner no longer authorized");
            }
            @Override public void check(Plan plan) {
                context(plan); throw new IllegalStateException("Writes paused or part protected");
            }
            @Override public void checkRecovery(Plan plan) { context(plan); }
        };
        EditEngine recovered = new EditEngine(world, state -> true, guard, journal, LIMITS);
        RecoveryReview review = recovered.reviewRecovery(id);
        assertEquals(1, recovered.inspectRecovery(id, 0, 1).size());
        contextAuthorized.set(false);
        assertThrows(SecurityException.class, () -> recovered.reviewRecovery(id));
        assertThrows(SecurityException.class, () -> recovered.inspectRecovery(id, 0, 1));
        assertThrows(SecurityException.class, () -> recovered.abandonRecovery(id, review.currentDigest()));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, recovered.status(id).status());
        contextAuthorized.set(true);
        recovered.abandonRecovery(id, review.currentDigest()); recovered.flushOperation(id);
        assertEquals(OperationStatus.FAILED, recovered.status(id).status()); assertEquals(0, world.writes);
        assertThrows(IllegalStateException.class, () -> prepare(recovered, Map.of(B, STONE)));
    }

    @Test void recoveryGuardDefaultNeverSilentlyBypassesExistingAuthorization() throws Exception {
        MemoryWorld world = new MemoryWorld(); MemoryJournal journal = new MemoryJournal(); EditEngine initial = engine(world, journal);
        String id = start(initial, prepare(initial, Map.of(A, STONE)));
        initial.persistIntent(nextIntent(initial, id));
        EditEngine restricted = new EditEngine(world, state -> true,
            plan -> { throw new SecurityException("World epoch changed"); }, journal, LIMITS);
        assertThrows(SecurityException.class, () -> restricted.reviewRecovery(id));
        assertThrows(SecurityException.class, () -> restricted.inspectRecovery(id, 0, 1));
        assertEquals(OperationStatus.RECOVERY_REQUIRED, restricted.status(id).status());
        assertEquals(0, world.writes);
    }
}
