# world-core

Java 17 world editing core with no Paper/Fabric dependency. It provides immutable plans, bounded preflight and write slices, optimistic conflict checks, confirmed write receipts, checked undo, and durable write-ahead intents. `RecipeCompiler` implements the version 1 `box`, `line`, `cylinder`, and nested `repeat` subset.

## Integration contract

One `EditEngine` belongs to one world and has one active operation at a time. `WorldAccess` must return canonical full state strings; the adapter supplies `BlockPolicy` and a `ContextGuard` that verifies the current project, region, world epoch, permissions, and chunk availability. Both original and desired states must be supported. The adapter must exclude inventories, entities, physics, and compound blocks whose secondary changes cannot be described by a single block write.

World access runs on the server thread. Use one IO executor for durable methods. No IO method holds the engine monitor while writing or syncing files, so status and cancellation remain responsive. The adapter must serialize IO and avoid staging/committing while its IO task is pending.

1. Server thread: `prepare(projectId, epoch, region, desired, dependencies)` captures a bounded snapshot. It does not write the world.
2. IO executor: `persistPlan(plan.id())`.
3. Server thread: `start(plan.id(), idempotencyKey)` creates an operation. Reusing the same key for the same immutable plan returns the original operation ID; another plan is rejected. Keys are scoped to a project.
4. IO executor: `flushOperation(operationId)` before returning a durable operation ID.
5. Server tick: `stageSlice(operationId)`. An empty result can mean preflight/final verification is still in progress. Check `status` and persist it if `needsFlush` is true. Preflight scans the whole request in bounded steps before any world write; changes can still arise after that scan.
6. When a slice is returned, IO executor: `persistIntent(intent)`.
7. Server thread: `commitSlice(intent)`. The engine rechecks the journaled before values, dependencies, context, and block policy after IO. It then writes and reads back at most the configured block limit, checking elapsed time between blocks.
8. IO executor: `flushOperation(operationId)` before another slice. Repeat steps 5–8 until terminal. `APPLIED` follows a bounded final live verification.

If cancellation arrives while a state is being persisted, a newer cancellation flag leaves `needsFlush` true; flush it before another stage. Stop requests retain already confirmed changes. An intent is an internal object capability: the exact instance must pass through persistence and commit, and must never be deserialized from a remote request.

`prepareUndo` only includes confirmed actual writes. Blocks already at the desired state are skipped and never claimed as this operation's work. Undo rejects a changed current state and any known later operation at the same position, even if its current value happens to equal the older result. `receipts` is for adapter bookkeeping, such as named part masks; it is potentially large and should not be returned to the model.

Dependencies are explicitly supplied positions, limited separately from writes. Each slice rechecks all dependencies against their original values, or this operation's confirmed desired values when it has modified those positions. The engine does not infer structural supports from geometry. Final verification and slices are observations across ticks, not an atomic transaction for an entire building.

Use `pendingOperations()` for scheduling and cancellation loops: a maintained index contains only active operations and terminal operations still needing persistence, so each tick does not scan completed history. Use `recentOperations(limit)` (0–100) and `operationCount()` for bounded context; `operations()` is a full-history administrative snapshot. Recent operations are ordered by in-process creation, with persisted plan-capture time used as an approximation after restart. Status views never copy full receipts.

The adapter can call `recordExternal(position)` for observed successful external edits on the server thread. It invalidates known ownership even if a player changes a block away and back to the same state, so undo rejects that known later intervention. Do not call it for the engine's own writes or cancelled player events. Notifications allocate no history for unowned positions and do not write files in events. They are **ephemeral in this prototype**: after restart, unknown external edits retain only the live content-check guarantee. Persisted block-event revisions remain future journal work.

## Prototype journal and recovery

`JsonJournal` uses one checksummed JSON file per plan and operation, flushed file contents, atomic replacement, and directory fsync. This initial implementation deliberately uses atomic JSON snapshots instead of the design document's planned SQLite index and compressed chunk files. The host filesystem must support those durability primitives; there is no silent fallback to a weaker rename. Only one server process may own a journal directory.

Plans and idempotency records survive restart. Any queued/applying operation, unfinished intent, or previous uncertain result becomes `RECOVERY_REQUIRED` on load and blocks all new writes in that engine. No intent is replayed automatically. `inspectRecovery(id, offset, limit)` reads a bounded page of uncertain before/after/current states; matching after is evidence of content, not proof of authorship. Malformed or corrupt committed records fail startup. Uncommitted temporary files are ignored.

Recovery never resumes, overwrites, or deletes journal history automatically. An explicit administrator can call `reviewRecovery(id)` to inspect counts and a SHA-256 digest of current contents across the union of earlier confirmed receipts and the pending uncertain write mask. `abandonRecovery(id, expectedDigest)` rereads that same mask and refuses a stale digest. It leaves all world blocks untouched, marks the operation `FAILED`, permanently disables undo for that abandoned operation, and invalidates previous ownership on the affected positions. The invalidation revision is persisted and survives restart. This action abandons uncertain history; it is not a rollback or proof that previous writes happened.

The adapter must expose review and abandonment exclusively through an explicit administrative interface, outside agent MCP tools. Call `flushOperation` after abandonment; the global recovery latch clears only after that exact state is durably saved and every other unresolved operation has also been handled. A crash before that flush retains recovery on restart. A failed flush retains the affected mask for another review. A newer cancellation or recovery decision cannot be acknowledged by an older in-flight flush. Recovery review reads at most the configured plan limit synchronously, so the Paper prototype's 4096-block cap also bounds this administrative operation.

Recovery uses `ContextGuard.checkRecovery(plan)`. The adapter should retain caller authorization, project/world/epoch identity and region/dependency bounds, while excluding restrictions that apply only to block writes, such as paused writing or protected parts. This lets an administrator abandon uncertain history without reopening protected world editing. The interface default delegates to `check(plan)`, so existing adapters retain their complete guard until they explicitly implement this separation.

A terminal operation reports states observed at runtime; Minecraft's chunk saving is not transactional with this journal, so those observations do not prove disk persistence of the world after a crash. Undo and subsequent plans always reread live state. Fully automatic reconciliation and restart auditing of completed chunk writes remain future work.

JSON snapshots rewrite the accumulated receipt list after each slice. This prioritizes inspectability and correctness for the initial small-plan prototype; it is not the final storage design or a claim of 100,000-block throughput. Prepare is synchronous and bounded by `maxChanges`; the Paper prototype should cap it conservatively until chunked snapshot preparation exists. The nanosecond budget is a soft limit checked between blocks, not a preemptive deadline for a slow server API call or dependency precheck.

## Geometry contract

The compiler accepts `{ "version": 1, "operations": [...] }`. Coordinates are integer world coordinates. Later operations overwrite earlier positions in the result; the compiler itself never reads or writes the world.

- `box`: inclusive `min`/`max`, `block`, optional `hollow`. Hollow keeps all six boundary faces.
- `line`: `from`/`to`, `block`. Both endpoints are included; interpolation makes a deterministic 26-connected voxel line.
- `cylinder`: bottom `center`, integer nonnegative `radius`, positive `height`, `block`, optional `hollow`. Hollow retains the side wall and has open top/bottom.
- `repeat`: `count` (1–1024), integer `offset`, nested `operations`. Iteration zero uses zero offset.

The compiler enforces unique block count, scan budget, nesting depth 8, expanded operation count 4096, checked coordinate arithmetic, and strict fields. Overlapping repeated shapes still consume scan budget. Arbitrary scripts, expressions, transforms, palettes, `.schem`, arch generation, and replacement masks are not implemented here yet.

## Verification

Run `mvn -f world-core/pom.xml test` from the repository root. Tests cover mutation during journal IO and between slices, read dependencies, partial cancellation, ownership of skipped blocks, changed permissions/policies, idempotency through a real filesystem restart, undo conflicts and later writers, disk failures, corruption, setter exceptions after mutation, nested world callbacks, final verification, geometry limits, and a stalled journal that must not block status or cancellation.

Memory-world tests prove the core's state machine and journal boundaries. They do not prove Minecraft threading, chunk persistence, physics behavior, or server performance; those require the real Paper integration tests.
