package io.github.minecraftbuilder.core;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.ArrayDeque;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Bounded optimistic editor for one world. The adapter serializes world-thread calls and allows
 * only one IO task at a time. persistPlan, persistIntent, and flushOperation run on an IO executor.
 * No world writes occur before a durable intent, nor before the post-IO live recheck.
 */
public final class EditEngine {
    private final WorldAccess world;
    private final BlockPolicy policy;
    private final ContextGuard guard;
    private final Journal journal;
    private final Limits limits;
    private final Map<String, Plan> plans = new HashMap<>();
    private final Set<String> durablePlans = new HashSet<>();
    private final Map<String, Operation> operations = new ConcurrentHashMap<>();
    private final Set<String> pendingOperationIds = new LinkedHashSet<>();
    private final Set<String> recoveryOperationIds = new HashSet<>();
    private final Deque<String> recentOperationIds = new ArrayDeque<>();
    private final Map<String, String> idempotency = new HashMap<>();
    private final Map<BlockPos, Writer> lastWriters = new HashMap<>();
    private long revision;
    private boolean recoveryRequired;

    private record Writer(String operationId, long revision) { }
    private static final class Operation {
        final String id;
        final Plan plan;
        final String key;
        OperationStatus state = OperationStatus.QUEUED;
        int cursor, skipped, preflightCursor, finalAuditCursor, nextSequence;
        final List<Receipt> receipts = new ArrayList<>();
        final List<Conflict> conflicts = new ArrayList<>();
        final Map<BlockPos, String> written = new HashMap<>();
        SliceIntent pending;
        boolean intentDurable;
        boolean needsFlush = true;
        long mutationVersion;
        volatile boolean cancelled;
        String message = "Awaiting bounded preflight";
        long abandonedRevision;
        List<BlockPos> abandonedPositions = List.of();
        Operation(String id, Plan plan, String key) { this.id = id; this.plan = plan; this.key = key; }
        OperationSnapshot snapshot() {
            return new OperationSnapshot(id, plan.id(), key, state, cursor, skipped, preflightCursor,
                nextSequence, receipts, pending, conflicts, message, cancelled, abandonedRevision, abandonedPositions);
        }
        OperationView view() {
            return new OperationView(id, plan.id(), plan.projectId(), state, plan.changes().size(), cursor,
                receipts.size(), skipped, preflightCursor, List.copyOf(conflicts), message, needsFlush, cancelled);
        }
    }

    public EditEngine(WorldAccess world, BlockPolicy policy, ContextGuard guard, Journal journal, Limits limits)
        throws IOException {
        this.world = Objects.requireNonNull(world); this.policy = Objects.requireNonNull(policy);
        this.guard = Objects.requireNonNull(guard); this.journal = Objects.requireNonNull(journal);
        this.limits = Objects.requireNonNull(limits);
        for (Plan plan : journal.loadPlans()) {
            validatePlanShape(plan);
            if (plans.put(plan.id(), plan) != null) throw new IOException("Duplicate plan ID");
            durablePlans.add(plan.id());
        }
        // Plan capture time approximates historical creation order; operation IDs break ties stably.
        List<OperationSnapshot> savedOperations = new ArrayList<>(journal.loadOperations());
        savedOperations.sort(Comparator.<OperationSnapshot>comparingLong(saved -> {
            Plan plan = plans.get(saved.planId()); return plan == null ? Long.MIN_VALUE : plan.createdAtMillis();
        }).thenComparing(OperationSnapshot::id));
        for (OperationSnapshot saved : savedOperations) restore(saved);
    }

    private void restore(OperationSnapshot saved) throws IOException {
        Plan plan = plans.get(saved.planId());
        if (plan == null) throw new IOException("Operation refers to a missing durable plan");
        if (saved.cursor() < 0 || saved.cursor() > plan.changes().size() || saved.skipped() < 0
            || saved.preflightCursor() < 0 || saved.preflightCursor() > plan.changes().size()
            || saved.receipts().size() + saved.skipped() != saved.cursor() || saved.status() == null)
            throw new IOException("Invalid operation progress");
        Operation op = new Operation(saved.id(), plan, saved.idempotencyKey());
        op.state = saved.status(); op.cursor = saved.cursor(); op.skipped = saved.skipped();
        op.preflightCursor = saved.preflightCursor(); op.nextSequence = saved.nextSequence();
        op.receipts.addAll(saved.receipts()); op.conflicts.addAll(saved.conflicts());
        op.pending = saved.pending(); op.cancelled = saved.cancellationRequested(); op.message = saved.message();
        op.abandonedRevision = saved.abandonedRevision(); op.abandonedPositions = saved.abandonedPositions();
        if (op.abandonedRevision < 0 || op.abandonedPositions.size() > limits.maxChanges()
            || (op.abandonedRevision == 0 && !op.abandonedPositions.isEmpty())
            || (op.abandonedRevision > 0 && (op.pending != null
                || (op.state != OperationStatus.FAILED && op.state != OperationStatus.RECOVERY_REQUIRED))))
            throw new IOException("Invalid abandonment record");
        op.needsFlush = false;
        for (Receipt receipt : saved.receipts()) {
            if (!plan.region().contains(receipt.change().pos()) || receipt.revision() < 1)
                throw new IOException("Invalid write receipt");
            op.written.put(receipt.change().pos(), receipt.change().desired());
            Writer previous = lastWriters.get(receipt.change().pos());
            if (previous == null || previous.revision() < receipt.revision())
                lastWriters.put(receipt.change().pos(), new Writer(op.id, receipt.revision()));
            revision = Math.max(revision, receipt.revision());
        }
        if (op.abandonedRevision > 0) {
            Set<BlockPos> possible = new HashSet<>();
            for (Change change : op.plan.changes()) possible.add(change.pos());
            for (BlockPos position : op.abandonedPositions) {
                if (!possible.contains(position)) throw new IOException("Abandoned position is outside the recorded plan");
                Writer previous = lastWriters.get(position);
                if (previous == null || previous.revision() < op.abandonedRevision)
                    lastWriters.put(position, new Writer("abandoned:" + op.id, op.abandonedRevision));
            }
            revision = Math.max(revision, op.abandonedRevision);
        }
        if (!op.state.terminal() || op.pending != null || op.state == OperationStatus.RECOVERY_REQUIRED) {
            op.state = OperationStatus.RECOVERY_REQUIRED;
            op.message = "Interrupted operation: inspect before/after/current; automatic replay is disabled";
            op.needsFlush = true; recoveryRequired = true; recoveryOperationIds.add(op.id);
        }
        if (operations.put(op.id, op) != null || idempotency.put(key(plan.projectId(), op.key), op.id) != null)
            throw new IOException("Duplicate operation or idempotency key");
        recentOperationIds.addFirst(op.id);
        updatePending(op);
    }

    /** Captures a limited live snapshot; perform on the world thread. No disk writes or world mutations. */
    public synchronized Plan prepare(String projectId, String worldEpoch, Region region,
                                     Map<BlockPos, String> desired, Set<BlockPos> dependencyPositions) {
        requireText(projectId, "projectId"); requireText(worldEpoch, "worldEpoch");
        Objects.requireNonNull(region); Objects.requireNonNull(desired); Objects.requireNonNull(dependencyPositions);
        if (desired.size() > limits.maxChanges()) throw new IllegalArgumentException("Plan exceeds block limit");
        if (dependencyPositions.size() > limits.maxReadDependencies())
            throw new IllegalArgumentException("Read dependencies exceed limit");
        long now = System.currentTimeMillis();
        String id = UUID.randomUUID().toString();
        Plan context = new Plan(id, projectId, worldEpoch, region, List.of(), List.of(), now,
            Math.addExact(now, limits.planTtlMillis()), null);
        guard.check(context);
        // Validate the whole request before any live reads (and before expensive snapshot work).
        for (var entry : desired.entrySet()) { requireInside(region, entry.getKey()); requireSupported(entry.getValue()); }
        for (BlockPos position : dependencyPositions) requireInside(region, position);
        List<Change> changes = new ArrayList<>();
        Map<BlockPos, String> captured = new HashMap<>();
        for (var entry : new TreeMap<>(desired).entrySet()) {
            String before = read(entry.getKey());
            requireSupported(before); captured.put(entry.getKey(), before);
            changes.add(new Change(entry.getKey(), before, entry.getValue()));
        }
        List<Plan.Dependency> dependencies = new ArrayList<>();
        for (BlockPos position : dependencyPositions.stream().sorted().toList()) {
            String before = captured.containsKey(position) ? captured.get(position) : read(position);
            requireSupported(before); dependencies.add(new Plan.Dependency(position, before));
        }
        Plan plan = new Plan(id, projectId, worldEpoch, region, changes, dependencies, now,
            context.expiresAtMillis(), null);
        plans.put(id, plan);
        return plan;
    }

    /** IO executor only. A plan cannot start until this succeeds. */
    public void persistPlan(String planId) throws IOException {
        Plan plan;
        synchronized (this) { plan = plan(planId); }
        journal.savePlan(plan);
        synchronized (this) { durablePlans.add(planId); }
    }

    /** Creates a memory operation. Persist it with flushOperation before returning a durable operation ID. */
    public synchronized OperationView start(String planId, String idempotencyKey) {
        Plan plan = plan(planId);
        requireText(idempotencyKey, "idempotencyKey");
        String existingId = idempotency.get(key(plan.projectId(), idempotencyKey));
        if (existingId != null) {
            Operation existing = operation(existingId);
            if (!existing.plan.id().equals(planId)) throw new IllegalArgumentException("Idempotency key belongs to another plan");
            return existing.view();
        }
        if (recoveryRequired) throw new IllegalStateException("recovery_required: unresolved journal prevents new writes");
        if (!durablePlans.contains(planId)) throw new IllegalStateException("Plan is not durable; persistPlan first");
        if (System.currentTimeMillis() > plan.expiresAtMillis()) throw new IllegalStateException("Plan expired; prepare again");
        guard.check(plan);
        if (!pendingOperationIds.isEmpty())
            throw new IllegalStateException("busy: one active or unflushed operation is allowed per world engine");
        Operation op = new Operation(UUID.randomUUID().toString(), plan, idempotencyKey);
        if (plan.changes().isEmpty()) { op.state = OperationStatus.APPLIED; op.message = "No changes"; }
        operations.put(op.id, op); idempotency.put(key(plan.projectId(), idempotencyKey), op.id);
        recentOperationIds.addFirst(op.id); updatePending(op);
        return op.view();
    }

    /**
     * Bounded world-thread preflight, then stage a slice. Empty means poll again if status is active.
     * If status.needsFlush, flush off-thread before polling again. No world writes occur here.
     */
    public synchronized Optional<SliceIntent> stageSlice(String operationId) {
        Operation op = operation(operationId);
        if (op.state.terminal()) return Optional.empty();
        if (op.needsFlush) throw new IllegalStateException("flushOperation must complete before the next slice");
        if (op.pending != null) throw new IllegalStateException("A slice is already staged");
        try { return stageInternal(op); }
        catch (RuntimeException e) {
            finish(op, OperationStatus.FAILED, "Cannot inspect world: " + e.getMessage());
            return Optional.empty();
        } finally { op.mutationVersion++; }
    }

    private Optional<SliceIntent> stageInternal(Operation op) {
        if (!checkContext(op) || !checkDependencies(op)) return Optional.empty();
        long started = System.nanoTime();
        if (op.preflightCursor < op.plan.changes().size()) {
            int checked = 0;
            while (op.preflightCursor < op.plan.changes().size() && checked < limits.maxBlocksPerSlice()) {
                Change change = op.plan.changes().get(op.preflightCursor);
                if (!checkChange(op, change, true)) return Optional.empty();
                op.preflightCursor++; checked++;
                if (System.nanoTime() - started >= limits.sliceNanos()) break;
            }
            op.message = "Preflight " + op.preflightCursor + "/" + op.plan.changes().size();
            return Optional.empty();
        }
        if (op.cursor == op.plan.changes().size()) {
            int checked = 0;
            while (op.finalAuditCursor < op.plan.changes().size() && checked < limits.maxBlocksPerSlice()) {
                Change change = op.plan.changes().get(op.finalAuditCursor);
                String current = read(change.pos());
                if (!current.equals(change.desired())) {
                    conflict(op, change, current, "Final verification differs from desired state");
                    return Optional.empty();
                }
                op.finalAuditCursor++; checked++;
                if (System.nanoTime() - started >= limits.sliceNanos()) break;
            }
            if (op.finalAuditCursor == op.plan.changes().size())
                finish(op, OperationStatus.APPLIED, "All requested states verified; snapshot is not an atomic world transaction");
            return Optional.empty();
        }
        List<Change> slice = new ArrayList<>();
        for (int index = op.cursor; index < op.plan.changes().size() && slice.size() < limits.maxBlocksPerSlice(); index++) {
            Change change = op.plan.changes().get(index);
            if (!checkChange(op, change, true)) return Optional.empty();
            // The journal records the actual state observed now, including no-op desired states.
            slice.add(new Change(change.pos(), read(change.pos()), change.desired()));
            if (System.nanoTime() - started >= limits.sliceNanos()) break;
        }
        op.pending = new SliceIntent(op.id, op.nextSequence++, slice);
        op.state = OperationStatus.APPLYING; op.message = "Intent staged; no blocks written";
        op.intentDurable = false;
        return Optional.of(op.pending);
    }

    /** IO executor only. Failure stops the engine; a partially successful fsync cannot be guessed. */
    public void persistIntent(SliceIntent intent) throws IOException {
        Operation op;
        OperationSnapshot snapshot;
        synchronized (this) {
            op = requireIntent(intent);
            if (op.intentDurable) return;
            snapshot = op.snapshot();
        }
        try {
            journal.saveOperation(snapshot);
            synchronized (this) {
                if (op.pending != intent) throw new IllegalStateException("Slice changed during persistence");
                op.intentDurable = true;
            }
        } catch (IOException e) {
            synchronized (this) { recovery(op, "Cannot persist write intent: " + e.getMessage()); }
            throw e;
        }
    }

    /** World thread only: revalidate after IO, write a bounded slice, verify actual writes. */
    public synchronized OperationView commitSlice(SliceIntent intent) {
        Operation op = requireIntent(intent);
        if (!op.intentDurable) throw new IllegalStateException("Intent is not durable");
        if (op.state.terminal()) return op.view();
        try { return commitInternal(op, intent); }
        catch (RuntimeException e) {
            recovery(op, "Slice verification failed; retained intent requires reconciliation: " + e.getMessage());
            return op.view();
        } finally { op.mutationVersion++; }
    }

    private OperationView commitInternal(Operation op, SliceIntent intent) {
        if (!checkContext(op) || !checkDependencies(op)) { discardIntent(op); return op.view(); }
        for (Change change : intent.changes()) {
            // Strict equality to the journaled before value closes the IO race, including no-op entries.
            String current = read(change.pos());
            if (!checkUndoWriter(op, change, current)) { discardIntent(op); return op.view(); }
            if (!current.equals(change.expected()) || !policy.supports(current) || !policy.supports(change.desired())) {
                conflict(op, change, current, "Changed while intent was persisted"); discardIntent(op); return op.view();
            }
        }
        long started = System.nanoTime();
        for (Change change : intent.changes()) {
            if (op.cancelled) { finish(op, OperationStatus.CANCELLED, "Stopped between blocks; completed writes remain"); break; }
            String current = read(change.pos());
            if (!checkUndoWriter(op, change, current)) break;
            if (!current.equals(change.expected())) {
                conflict(op, change, current, "Changed during slice (possible nested world callback)"); break;
            }
            if (current.equals(change.desired())) { op.skipped++; op.cursor++; }
            else {
                try {
                    world.setBlock(change.pos(), change.desired());
                    String actual = read(change.pos());
                    if (!actual.equals(change.desired())) {
                        recovery(op, "Write result is uncertain at " + change.pos()); break;
                    }
                    recordWrite(op, change);
                } catch (RuntimeException e) {
                    // A setter can fail after mutation. Observe and retain a confirmed receipt when possible.
                    try {
                        String actual = read(change.pos());
                        if (actual.equals(change.desired())) recordWrite(op, change);
                        else if (!actual.equals(change.expected())) { recovery(op, "Setter failed with an unexpected world state"); break; }
                        finish(op, OperationStatus.FAILED, "World write failed: " + e.getMessage());
                    } catch (RuntimeException readFailure) { recovery(op, "World write and verification failed"); }
                    break;
                }
            }
            if (System.nanoTime() - started >= limits.sliceNanos()) break;
        }
        if (op.state != OperationStatus.RECOVERY_REQUIRED) discardIntent(op);
        op.needsFlush = true;
        if (!op.state.terminal()) op.message = "Slice written; awaiting durable receipt";
        return op.view();
    }

    /** IO executor only; the next slice is forbidden until receipts/status have been flushed. */
    public void flushOperation(String operationId) throws IOException {
        Operation op;
        OperationSnapshot snapshot;
        long snapshotVersion;
        synchronized (this) {
            op = operation(operationId);
            if (op.pending != null && !op.state.terminal())
                throw new IllegalStateException("Use persistIntent for a staged slice");
            snapshot = op.snapshot();
            snapshotVersion = op.mutationVersion;
        }
        try {
            journal.saveOperation(snapshot);
            synchronized (this) {
                // Never publish an older flush as the durable acknowledgement of newer state.
                // Normally only cancellation may interleave; explicit recovery also advances this version.
                op.needsFlush = op.mutationVersion != snapshotVersion || op.cancelled != snapshot.cancellationRequested();
                updatePending(op);
                if (op.abandonedRevision > 0 && op.state == OperationStatus.FAILED && !op.needsFlush) {
                    recoveryOperationIds.remove(op.id);
                    recoveryRequired = !recoveryOperationIds.isEmpty();
                }
            }
        } catch (IOException e) {
            synchronized (this) { recovery(op, "Cannot persist operation state: " + e.getMessage()); }
            throw e;
        }
    }

    /** Cancellation does not roll back confirmed blocks. The next stage/commit observes this flag. */
    public OperationView cancel(String operationId) {
        Operation op = operation(operationId);
        boolean wasCancelled = op.cancelled;
        op.cancelled = true;
        synchronized (this) { if (!wasCancelled) op.mutationVersion++; return op.view(); }
    }

    public synchronized OperationView status(String operationId) { return operation(operationId).view(); }
    /** Internal adapter use only: potentially large; do not send the full receipt list to the model. */
    public synchronized List<Receipt> receipts(String operationId) { return List.copyOf(operation(operationId).receipts); }
    public synchronized List<OperationView> operations() {
        return operations.values().stream().map(Operation::view).sorted(java.util.Comparator.comparing(OperationView::id)).toList();
    }
    /** Scheduler index: only active operations or terminal states still requiring a durable flush. */
    public synchronized List<OperationView> pendingOperations() {
        return pendingOperationIds.stream().map(id -> operation(id).view()).toList();
    }
    /** Bounded context snapshot; most recently created operations first, no receipt copies. */
    public synchronized List<OperationView> recentOperations(int limit) {
        if (limit < 0 || limit > 100) throw new IllegalArgumentException("Recent operation limit must be 0..100");
        List<OperationView> result = new ArrayList<>(Math.min(limit, recentOperationIds.size()));
        for (String id : recentOperationIds) {
            if (result.size() == limit) break;
            result.add(operation(id).view());
        }
        return List.copyOf(result);
    }
    public int operationCount() { return operations.size(); }

    /**
     * Record an observed external edit on the server thread, even when its value later returns to the
     * same state (ABA). This invalidates only known ownership; it does not make journal IO in an event.
     * The notification is ephemeral and must not be emitted for this engine's own writes.
     */
    public synchronized void recordExternal(BlockPos position) {
        Objects.requireNonNull(position);
        // Unknown/unowned world positions need no history allocation.
        if (!lastWriters.containsKey(position)) return;
        revision = Math.incrementExact(revision);
        lastWriters.put(position, new Writer("external", revision));
    }
    public synchronized Plan plan(String planId) {
        Plan result = plans.get(planId);
        if (result == null) throw new IllegalArgumentException("Unknown plan");
        return result;
    }

    /** Prepare the inverse of confirmed writes; known later writers or changed values reject the whole undo. */
    public synchronized Plan prepareUndo(String operationId) {
        Operation source = operation(operationId);
        if (!source.state.terminal() || source.state == OperationStatus.RECOVERY_REQUIRED || source.needsFlush
            || source.abandonedRevision > 0)
            throw new IllegalStateException("Undo requires a terminal, durable, reconciled operation");
        guard.check(source.plan);
        Map<BlockPos, String> desired = new LinkedHashMap<>();
        for (Receipt receipt : source.receipts) {
            Change change = receipt.change();
            Writer writer = lastWriters.get(change.pos());
            if (writer == null || !writer.operationId().equals(source.id))
                throw new IllegalStateException("Undo conflict: known later operation at " + change.pos());
            String actual = read(change.pos());
            if (!actual.equals(change.desired())) throw new IllegalStateException("Undo conflict: external change at " + change.pos());
            desired.put(change.pos(), change.expected());
        }
        Plan base = prepare(source.plan.projectId(), source.plan.worldEpoch(), source.plan.region(), desired, Set.of());
        Plan undo = new Plan(base.id(), base.projectId(), base.worldEpoch(), base.region(), base.changes(),
            base.dependencies(), base.createdAtMillis(), base.expiresAtMillis(), source.id);
        plans.put(undo.id(), undo);
        return undo;
    }

    /** Read-only bounded inspection of uncertain intent entries; recovery never auto-replays them. */
    public synchronized List<Conflict> inspectRecovery(String operationId, int offset, int limit) {
        Operation op = operation(operationId);
        if (op.state != OperationStatus.RECOVERY_REQUIRED) throw new IllegalStateException("Operation does not require recovery");
        guard.checkRecovery(op.plan);
        if (offset < 0 || limit < 1 || limit > limits.maxBlocksPerSlice()) throw new IllegalArgumentException("Invalid recovery page");
        List<Change> candidates = recoveryChanges(op);
        List<Conflict> result = new ArrayList<>();
        for (int i = offset; i < candidates.size() && result.size() < limit; i++) {
            Change change = candidates.get(i);
            String actual = read(change.pos());
            String reason = actual.equals(change.expected()) ? "matches_before" : actual.equals(change.desired()) ? "matches_after" : "foreign_state";
            result.add(new Conflict(change.pos(), change.expected(), actual, change.desired(), reason));
        }
        return List.copyOf(result);
    }

    /**
     * Server thread, explicit administrator use only. Reads at most maxChanges affected positions.
     * The adapter should expose this outside model-accessible tools. No ownership is inferred.
     */
    public synchronized RecoveryReview reviewRecovery(String operationId) {
        Operation op = operation(operationId);
        if (op.state != OperationStatus.RECOVERY_REQUIRED) throw new IllegalStateException("Operation does not require recovery");
        guard.checkRecovery(op.plan);
        return recoveryReview(op);
    }

    /**
     * Explicitly abandon uncertain history, leaving every world block untouched. The current-state
     * digest must match a fresh review. Flush off-thread before any new editing can be enabled.
     */
    public synchronized OperationView abandonRecovery(String operationId, String expectedDigest) {
        Operation op = operation(operationId);
        if (op.state != OperationStatus.RECOVERY_REQUIRED) throw new IllegalStateException("Operation does not require recovery");
        if (expectedDigest == null || !expectedDigest.matches("[0-9a-f]{64}"))
            throw new IllegalArgumentException("A SHA-256 digest from reviewRecovery is required");
        guard.checkRecovery(op.plan);
        RecoveryReview current = recoveryReview(op);
        if (!MessageDigest.isEqual(current.currentDigest().getBytes(StandardCharsets.US_ASCII),
                                  expectedDigest.getBytes(StandardCharsets.US_ASCII)))
            throw new IllegalStateException("Recovery mask changed since review; inspect and review again");
        List<BlockPos> abandoned = recoveryChanges(op).stream().map(Change::pos).toList();
        revision = Math.incrementExact(revision);
        op.abandonedRevision = revision; op.abandonedPositions = abandoned;
        for (BlockPos position : abandoned)
            lastWriters.put(position, new Writer("abandoned:" + op.id, revision));
        discardIntent(op);
        finish(op, OperationStatus.FAILED, "Administrator abandoned uncertain history; world unchanged; this operation cannot be undone");
        // Deliberately keep the recovery latch until the exact abandonment state has been persisted.
        recoveryOperationIds.add(op.id); recoveryRequired = true;
        return op.view();
    }

    private RecoveryReview recoveryReview(Operation op) {
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
        digestString(digest, "minecraft-builder-mcp-recovery-v1"); digestString(digest, op.id);
        digestString(digest, op.plan.id()); digestString(digest, op.plan.region().worldId());
        digestString(digest, op.plan.worldEpoch());
        int before = 0, after = 0, foreign = 0;
        List<Change> changes = recoveryChanges(op);
        for (Change change : changes) {
            digest.update(ByteBuffer.allocate(12).putInt(change.pos().x()).putInt(change.pos().y()).putInt(change.pos().z()).array());
            String actual = read(change.pos());
            digestString(digest, change.expected()); digestString(digest, change.desired()); digestString(digest, actual);
            if (actual.equals(change.expected())) before++;
            else if (actual.equals(change.desired())) after++;
            else foreign++;
        }
        return new RecoveryReview(op.id, op.plan.id(), changes.size(), before, after, foreign,
            HexFormat.of().formatHex(digest.digest()), System.currentTimeMillis());
    }

    private static void digestString(MessageDigest digest, String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        digest.update(ByteBuffer.allocate(4).putInt(bytes.length).array()); digest.update(bytes);
    }

    private List<Change> recoveryChanges(Operation op) {
        Map<BlockPos, Change> candidates = new TreeMap<>();
        for (Receipt receipt : op.receipts) candidates.put(receipt.change().pos(), receipt.change());
        if (op.pending != null) for (Change change : op.pending.changes()) {
            // A journaled no-op was never owned and does not need write reconciliation.
            if (!change.expected().equals(change.desired())) candidates.put(change.pos(), change);
        }
        if (!op.abandonedPositions.isEmpty()) {
            Set<BlockPos> abandoned = new HashSet<>(op.abandonedPositions);
            for (Change change : op.plan.changes())
                if (abandoned.contains(change.pos())) candidates.putIfAbsent(change.pos(), change);
        }
        return List.copyOf(candidates.values());
    }

    private void recordWrite(Operation op, Change change) {
        long next = Math.incrementExact(revision); revision = next;
        op.receipts.add(new Receipt(change, next)); op.written.put(change.pos(), change.desired());
        lastWriters.put(change.pos(), new Writer(op.id, next)); op.cursor++;
    }
    private boolean checkContext(Operation op) {
        if (op.cancelled) { finish(op, OperationStatus.CANCELLED, "Cancelled; confirmed writes remain available for undo"); return false; }
        if (System.currentTimeMillis() > op.plan.expiresAtMillis()) {
            finish(op, OperationStatus.FAILED, "Plan expired; prepare from fresh state"); return false;
        }
        try { guard.check(op.plan); }
        catch (RuntimeException e) { finish(op, OperationStatus.FAILED, "Context no longer valid: " + e.getMessage()); return false; }
        return true;
    }
    private boolean checkDependencies(Operation op) {
        for (Plan.Dependency dependency : op.plan.dependencies()) {
            String expected = op.written.getOrDefault(dependency.pos(), dependency.expected());
            String actual = read(dependency.pos());
            if (!expected.equals(actual)) {
                conflict(op, new Change(dependency.pos(), expected, expected), actual, "Read dependency changed"); return false;
            }
        }
        return true;
    }
    private boolean checkChange(Operation op, Change change, boolean allowDesired) {
        String actual = read(change.pos());
        if (!policy.supports(actual) || !policy.supports(change.desired()) || !policy.supports(change.expected())) {
            conflict(op, change, actual, "Current or planned block state is unsupported by the current policy"); return false;
        }
        if (!checkUndoWriter(op, change, actual)) return false;
        if (!actual.equals(change.expected()) && !(allowDesired && actual.equals(change.desired()))) {
            conflict(op, change, actual, "Write set changed since preparation"); return false;
        }
        return true;
    }
    private boolean checkUndoWriter(Operation op, Change change, String actual) {
        if (op.plan.undoOf() != null) {
            Writer writer = lastWriters.get(change.pos());
            if (writer == null || !writer.operationId().equals(op.plan.undoOf())) {
                conflict(op, change, actual, "Known later operation prevents undo"); return false;
            }
        }
        return true;
    }
    private void conflict(Operation op, Change change, String actual, String reason) {
        if (op.conflicts.size() < limits.maxConflictDetails())
            op.conflicts.add(new Conflict(change.pos(), change.expected(), actual, change.desired(), reason));
        finish(op, OperationStatus.CONFLICT, reason);
    }
    private void finish(Operation op, OperationStatus state, String message) {
        op.state = state; op.message = message; op.needsFlush = true;
        op.mutationVersion++;
        updatePending(op);
    }
    private void recovery(Operation op, String reason) {
        recoveryRequired = true; recoveryOperationIds.add(op.id); finish(op, OperationStatus.RECOVERY_REQUIRED, reason);
    }
    private void discardIntent(Operation op) { op.pending = null; op.intentDurable = false; op.needsFlush = true; }
    private void updatePending(Operation op) {
        if (!op.state.terminal() || op.needsFlush) pendingOperationIds.add(op.id);
        else pendingOperationIds.remove(op.id);
    }
    private Operation requireIntent(SliceIntent intent) {
        Objects.requireNonNull(intent);
        Operation op = operation(intent.operationId());
        if (op.pending != intent) throw new IllegalArgumentException("Stale or foreign slice intent");
        return op;
    }
    private Operation operation(String id) {
        Operation op = operations.get(id);
        if (op == null) throw new IllegalArgumentException("Unknown operation");
        return op;
    }
    private String read(BlockPos pos) { return Objects.requireNonNull(world.getBlock(pos), "World returned null state"); }
    private void requireSupported(String state) {
        if (state == null || !policy.supports(state)) throw new IllegalArgumentException("Unsupported block state: " + state);
    }
    private static void requireInside(Region region, BlockPos pos) {
        if (pos == null || !region.contains(pos)) throw new IllegalArgumentException("Position outside authorized region: " + pos);
    }
    private static void requireText(String value, String name) {
        if (value == null || value.isBlank() || value.length() > 256 || value.chars().anyMatch(c -> c < 32))
            throw new IllegalArgumentException("Invalid " + name);
    }
    private static String key(String projectId, String idempotencyKey) { return projectId + "\u0000" + idempotencyKey; }
    private void validatePlanShape(Plan plan) throws IOException {
        if (plan.changes().size() > limits.maxChanges() || plan.dependencies().size() > limits.maxReadDependencies())
            throw new IOException("Stored plan exceeds configured limits");
        Set<BlockPos> positions = new HashSet<>();
        for (Change change : plan.changes()) {
            if (!plan.region().contains(change.pos()) || !positions.add(change.pos()))
                throw new IOException("Stored plan contains invalid/duplicate positions");
        }
        for (Plan.Dependency dependency : plan.dependencies())
            if (!plan.region().contains(dependency.pos())) throw new IOException("Stored dependency is outside region");
    }
}
