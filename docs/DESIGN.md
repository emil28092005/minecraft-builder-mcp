# minecraft-builder-mcp — design document

Document version: 0.1 · Date: September 12, 2026

Status: target design. The first prototype has been created; its actual capabilities, tests, and deviations from this document are listed in [IMPLEMENTATION.md](IMPLEMENTATION.md). The sections below also describe requirements that have not yet been implemented.

## 1. Purpose

Create a building environment for Minecraft Java Edition in which a person and an AI agent collaboratively design, build, and edit maps. The user talks to Codex through in-game chat or an external client. The agent receives structured information about the world, applies bulk changes through MCP, inspects real captures, and corrects the result.

The main scenario is: “Build a tower here” → site inspection → construction → captures → proportion adjustments. The user can build manually in parallel and then ask: “Keep my windows, add two floors, and redo the roof.”

The result consists of ordinary vanilla blocks. The map must remain usable after our components are removed. History, recipes, and part names are stored separately from game blocks.

## 2. Decisions and working assumptions

The discussion establishes these requirements: Paper as a building environment with future minigame use; Codex through the existing `codex-acp`; Minecraft MCP for world interaction; virtual cameras; bulk operations; named parts; preservation of manual edits; economical context use; undo; and transferring builds.

This document adopts the following design decisions, which may be changed before implementation:

- The first version targets one owner and a small group of trusted builders, one Paper server, and one active write operation per building area.
- The server plugin is the only component of our system that modifies the world directly.
- Cameras are served by a separate Minecraft client with a Fabric mod. Ordinary players do not need a client mod for chat.
- The Bridge is written in TypeScript; the Paper plugin and Fabric mod in Java. Exact tool versions are pinned after compatibility checks.
- The first version's building language is a restricted declarative description of geometry and repetition. Arbitrary Python/JavaScript is not executed inside the server.
- Captures, conflicts, and history do not have their own model within MCP. An image-capable agent interprets them.
- A user's building command authorizes ordinary changes within the selected area; approval is not required for every batch of blocks. Actual conflicts and actions outside the granted scope are handled separately.

## 3. Why both client and server components are needed

A client mod can control the camera, capture an image, read chunks sent to the client, and send commands the player is allowed to use. This is sufficient for a prototype that builds through server commands. However, such a client is not the authoritative source of world state and cannot provide coordinated block validation and writing on the server.

A server component is needed for authoritative region reads, permission checks, state comparisons immediately before writing, journaling, and applying changes under load limits. It cannot render the game view itself. Client and server execution are separate in Minecraft; rendering is performed by the client. [Fabric side separation](https://wiki.fabricmc.net/tutorial%3Aside).

The target installation can run entirely on one computer: Paper, Bridge, Codex, and the camera client. A dedicated machine or rented hosting is not required. A separate observer needs its own permitted game session; we cannot assume that one account can keep both the player and camera connected to the same server simultaneously. If a second session is unavailable, camera mode in the user's client with temporary view switching is possible; this is a separate interface tradeoff.

Single-player includes an integrated server. A Fabric module for its server side can be added later while retaining the MCP contracts. This removes the separate Paper process but requires another world adapter. A mod running only on the logical client side is insufficient for the full guarantees.

## 4. Platform and compatibility

The candidate for the first prototype is Minecraft/Paper 26.2 with Java 25. On the document date, the download page offers Paper 26.2, and the documentation specifies Java 25 for the 26.1+ branches. This confirms platform availability, not compatibility of all our dependencies. [Paper downloads](https://papermc.io/downloads/paper), [Java requirements](https://docs.papermc.io/paper/getting-started/).

Before implementing the main functionality, exact versions of Paper, WorldEdit, Fabric Loader/API, Codex, `codex-acp`, the MCP/ACP SDKs, and Node.js must be pinned. Dependencies must not update automatically on every launch. Build versions and hashes will be recorded in a future compatibility file.

WorldEdit is used for selections and the `.schem` format; using it as the write mechanism is evaluated separately. Its `EditSession` supports batching and history, but this does not replace our conflict checks, persistent journal, or execution-time control. Buffering must not defer actual writes beyond the validated server step. [WorldEdit Edit Sessions](https://worldedit.enginehub.org/en/latest/api/concepts/edit-sessions/).

The initial guaranteed set consists of vanilla building blocks without inventories or custom NBT, including tested log, stair, and slab states. Air is allowed as the result of deletion. Doors and other multipart structures are added only after indivisible change groups are implemented. Gravity-affected blocks, fluids, redstone, entities, and block entities are outside the initial editing and undo guarantees.

The restriction also applies to existing content: an operation must not silently overwrite a chest or another unsupported block. Preflight validation detects this before application and returns a clear reason.

## 5. First-version scope

v0.1 includes:

- Chat commands, a separate project session, a stream of short progress messages, and stopping.
- A designated building area and local world inspection.
- Compact shape descriptions, repetition, palettes, and a reproducible `seed`.
- A prepared plan, change counts, and application in slices.
- Named parts with exact sets of blocks belonging to them.
- Checks for changes since reading, stopping on conflict, and checked undo.
- A persistent operation journal and detection of unfinished writes after restart.
- One serving camera, several saved viewpoints, and image delivery through MCP.
- `.schem` import and export within the supported data set.

Outside v0.1: a public service for arbitrary players, multiple agents writing simultaneously in one area, Folia, complete minigames, arbitrary server-console access, third-party 3D generation services, automatic mesh voxelization, general-purpose physics simulation, arbitrary scripts with OS access, and intelligent transfer of any manual edit when geometry changes.

The system helps build minigame maps but does not implement the minigames' rules. Automatic aesthetic assessment is not a quality guarantee.

## 6. Components and connections

Request path: in-game chat → Paper plugin → Bridge as ACP client → `codex-acp` → Codex. Change path: Codex → Minecraft MCP in the Bridge → Paper plugin → world. Image path: Codex → Minecraft MCP → Camera Worker → Fabric client → image.

### Paper plugin

Responsible for commands, player identities, regions, permissions, block-state snapshots, plan validation, application scheduling, and persistent history. The plugin enforces limits independently of any promises made by the agent or Bridge.

### Bridge

Launches the pinned `codex-acp` version, implements the ACP client, and exposes Minecraft MCP tools. Maintains the project's connection to its conversation, formats messages for in-game chat, and limits the amount of data sent to the model. It does not become an alternative source of truth about blocks.

`codex-acp` already translates ACP into Codex App Server operations and supports images and MCP server connections. The project therefore does not implement a separate Codex ACP adapter. The capabilities of the particular pinned version are checked during connection setup. [codex-acp repository](https://github.com/agentclientprotocol/codex-acp).

### Camera Worker

Manages the capture queue and the connected Fabric client. Stores viewpoints, checks scene loading, and returns images with metadata. Camera failure does not destroy history or prevent block reads; the task explicitly receives a “not visually verified” status.

### Storage

The plugin stores metadata and indexes in SQLite, and large snapshots and changes in compressed files with checksums. It is the only writer to its database. The Bridge separately stores ACP sessions and compact summaries; the Camera Worker stores images. There is no shared database directly modified by both Java and Node.js.

Local connections bind to loopback by default and are protected by separate component secrets. Remote installations are expected to use an SSH tunnel or a verified secure connection; the world-editing interface does not need public access.

## 7. Sessions and the in-game interface

Main commands proposed for v0.1:

- `/ai <text>` — message the agent in the active project.
- `/ai project create <name>` and `/ai project use <name>` — create and select a project.
- `/ai area set` — commit the selected region after checking its size and permissions.
- `/ai status` — show the current request, operation, and camera status.
- `/ai stop` — stop the agent turn and request cancellation of the active world change.
- `/ai undo <operation>` — prepare and apply checked undo for the user's own operation.
- `/ai camera save <name>` — save the position and view direction.
- `/ai protect <part>` — protect a part from agent changes.

Ordinary public chat is not sent to the model in full. `/ai` messages and explicit mentions are forwarded only after sender validation. Replies are visible to the initiator by default; a shared building channel can be added through configuration.

Each project has a request queue. v0.1 allows one active agent turn per project; new messages are queued, and changing the task during execution requires coordinated interruption. The player UUID, world UUID, and project ID come from the server. The model cannot replace them through prompt text.

The Bridge stores the ACP session ID, but the project does not depend on that conversation remaining available forever. If resumption is impossible, a new session receives the project summary, current operation, and data references. Automatic attachment to the current Codex desktop conversation is not assumed. The lifecycle is checked against [ACP Session Setup](https://agentclientprotocol.com/protocol/v1/session-setup) and [ACP Prompt Turn](https://agentclientprotocol.com/protocol/v1/prompt-turn).

Chat displays stages and results, not every block placement. Message length and frequency are limited. A conflict message shows the user the building part, location, and consequences of their choice; technical identifiers are available in the details.

## 8. Data model

**Project:** stable ID, owner, members, world UUID, world epoch, permitted regions, block policy, quality settings, and a brief design summary. The epoch changes when a world is restored or replaced so that old plans cannot be applied to a different copy.

**Region:** dimension, inclusive integer `min/max` bounds, and read/write limits. Block coordinates are integers; camera coordinates are floating-point values. World height and border come from the server. Local recipe coordinates have an explicit anchor and transformation into world coordinates.

**Part:** ID, name, parent, tags, exact block mask, bounding volume, anchor, revision, protection mode, and recipe reference. The bounding box is used for lookup and does not imply ownership of everything inside it. In v0.1, editable child masks do not overlap; the parent is their union.

**Recipe:** language version, generator version, parameters, palette, seed, subparts, and transforms. Identical inputs and versions must produce the same plan. Rotations transform both coordinates and directional block states. Unsupported transforms are rejected.

**Snapshot:** ID, world and epoch, mask, canonical block states, section revisions, and hashes. A snapshot assembled over several ticks is not declared globally atomic: sections that change during collection are reread, or the snapshot is marked unstable.

**Plan:** immutable ID and content hash, initiator, region, base snapshot, dependency read set, write set with `expected/desired`, groups of related blocks, expiry, and statistics. The read set includes supports and clear passages when the decision depends on them. The plan is stored on the server; the model receives a summary.

**Operation:** ID, idempotency key, plan ID, status, slice numbers, count of confirmed writes, conflicts, author, timestamps, and a link to the undo operation. Exact original and resulting contents are stored in the persistent journal.

**Camera:** name, world, position, yaw/pitch, FOV, resolution, and display profile. **Capture:** image ID, camera ID, time, associated operation, loading information, and freshness status. A capture corresponds to an observation time; it is not an atomic image of the entire server state.

## 9. Building language and workflow

In v0.1, the agent submits a JSON program: parameters, a palette, and a sequence of `box`, `line`, `cylinder`, `arch`, `repeat`, `transform`, `replace`, and `paste` operations. These are proposed primitives, not existing tools. `replace` requires a region mask and a filter on source states.

Repetitions have a bounded count; only specified numeric expressions and parameter references are allowed. There is no `eval`, infinite looping, module loading, networking, or file paths. The interpreter has limits on depth, operations, memory, time, and the resulting block count. Future support for arbitrary code requires a separate process with OS-enforced isolation, not merely banning a few strings in a script.

Workflow:

1. The agent discovers server capabilities, the active project, the region, and viewpoints.
2. It requests a terrain summary and existing parts; if needed, local blocks and a capture.
3. It creates a recipe or a targeted edit to a specific part.
4. The plugin snapshots dependencies, computes a plan, and checks limits without writing to the world.
5. The agent receives volume, materials, intersections, and warnings about unverified properties.
6. A permitted plan is applied in slices. An ordinary authorized build does not require repeated approval.
7. After application, structural checks and captures from selected viewpoints are performed.
8. A correction creates a new operation. The number of autonomous retries is limited; if there is no improvement, the agent reports what it could not resolve.

The recipe is not the sole source of current geometry. After a manual change, the agent must use the actual world state. v0.1 must not simply regenerate an entire part over its current contents.

Build quality is guided by a brief project intent: purpose, scale relative to the player, silhouette, palette, primary materials, entrances, interior spaces, and reference viewpoints. For a large task, the agent first plans the major volumes, then builds the structure, then adds details. These stages remain separate operations so that unsuccessful detailing does not destroy a successful silhouette. An empty interior is acceptable only when it matches the brief.

Structural validation in v0.1 confirms declared dimensions, bounds, block states, and actual plan completion. Semantic properties such as navigability, arena balance, and facade aesthetics are assessed separately and are not presented as results of simple block comparison.

## 10. Manual edits and conflicts

Server code performs the comparison. The model does not receive the full block list to compute the difference itself.

An ordinary write uses base state `B`, current state `C`, and desired state `D`:

- `C = B`: writing `D` is allowed if dependencies are unchanged and permissions are satisfied.
- `C = D`: the block already matches the result; no write is needed, and it is not recorded in the new history as our work.
- Otherwise: a conflict. The state is not overwritten automatically.

In v0.1, detecting a manual divergence inside a part being rebuilt stops automatic regeneration of that part. The agent may prepare a local plan that explicitly preserves current geometry, or build a different, unaffected part.

A three-way merge is proposed for v0.2: compare the previous generated result `G0`, the current world `C`, and the new result `G1`. If `G1 = G0`, preserve the manual edit; if `C = G0`, the new geometry may be accepted; if `C = G1`, no write is needed; other overlaps require a decision. This is a coordinate-based merge, not an understanding of what a window or staircase means.

Example: a manually added window in an unchanged wall is preserved when upper floors are added. If a new floor shifts the entire wall, the system does not automatically know where to move the window. In v0.1, such rebuilding stops and a new local plan is proposed. Automatic transfer of edits in recipe coordinates belongs to the next version.

If a conflict is found in advance, the plan does not begin writing. If a conflict arises during execution, the operation stops before the next affected group and returns a partial result. It does not silently continue building the remaining fragments, since this could leave the structure geometrically incorrect.

Resolution options are: preserve the current world and replan; exclude a protected part; or, following an explicit owner decision, replace a specific conflicting fragment. A new decision creates a new plan from fresh state. The agent's tools do not offer a global “ignore all conflicts” mode.

Player events, natural-change events, and WorldEdit integration speed up revision updates. However, third-party plugins are not all required to emit the same events. Hashes and revisions therefore serve as optimizations, while live block checks immediately before writing remain mandatory. An unknown source is described as an “external change,” not attributed to a player.

Server validation protects current content. If an uncontrolled plugin changes a block and changes it back between checks, content comparison alone cannot reconstruct that history. A complete authorship history of every possible world change is not promised.

## 11. Application, stopping, and recovery

Operation states: `prepared` → `queued` → `applying` → `applied`. Other terminal branches: `conflict`, `cancelled`, `failed`, `recovery_required`. Every state includes the count of actually confirmed blocks: even `cancelled` can mean a partially modified world. Visual validation has a separate `pending/passed/needs_changes/unavailable` status; a capture does not determine whether writing has finished.

Geometry preparation, compression, file operations, networking, and model requests run outside the game thread. Live world reads and writes use supported server APIs on the server thread. This follows the restrictions of the [Paper Scheduler](https://docs.papermc.io/paper/dev/scheduler/).

Slice algorithm:

1. Form a bounded group of changes and dependencies on its surroundings. A plugin-wide dispatcher serializes overlapping operations by world UUID and region, including across different projects. A lock on a single project is not sufficient protection.
2. On the server thread, read the actual initial state and prepare an intent record with `before/after`, a group ID, and a checksum.
3. Save the intent to the persistent journal off the server thread and wait for persistence acknowledgement. The world does not change before this.
4. Return to the server thread; recheck permissions, epoch, limits, expected states, and dependencies. If anything changed, stop before writing this group.
5. In the same server step, without yielding control, apply a permitted small group, verify the result, and record blocks actually changed. Intent records with skipped or error outcomes are also persisted.
6. Commit group completion before continuing to the next group. Update the operation summary and invalidate affected caches.

A plan must declare dependencies. If a part depends on blocks processed earlier, subsequent checks account for the operation's own confirmed values. A change to an important support after it was processed pauses subsequent dependent steps. Full consistency of the entire building across many ticks is not guaranteed without locking out all external writers; a final check is required after writing.

An ordinary manual edit cannot interleave between validation and writing within one server slice. Even a slice, however, is not a Minecraft ACID transaction: an exception, nested events, or physics may cause partial changes. The executor records the actual result, and the operation stops. Multipart objects use small indivisible logical groups and separate validation rules. Support for these groups does not imply atomicity if the process crashes.

`/ai stop` has two independent effects: ACP cancellation of the model turn and a server-side operation cancellation flag. Stopping the model alone does not cancel an already running write. The plugin checks the flag before each slice; completed changes remain in history. Losing the Bridge prevents new slices after a short connection timeout; a completed slice is not replayed blindly.

All mutating requests have an idempotency key bound to the project and content hash. A retry with the same key and plan returns the existing operation; the same key with different content is rejected. Retrying after a network timeout starts with an operation-status request.

After a crash, the plugin detects unfinished groups and enters `recovery_required`. World-file persistence and journal persistence do not form a single shared transaction. Startup therefore compares the live world with `before/after`: the old value, the new value, or an unrelated state. Neither unknown states nor ambiguous history are overwritten automatically. Resumption or undo is constructed as a new validated plan; writing blocks based solely on the journal's last status is prohibited.

Undo creates a reverse operation only for blocks we actually wrote. It restores `before` if the current state matches the confirmed `after` and there is no known later write by another action. A known subsequent change produces a conflict even if its final value happens to match. Unknown external actions remain subject to the content-check limitation in section 10.

Secondary effects — flowing water, falling sand, inventory changes, plant growth, and redstone updates — cannot be restored with a simple reverse block list. v0.1 excludes these scenarios from the guaranteed building area. The journal does not replace a world backup. Full simulation of side effects requires a separate design.

Validation considers supported surroundings, not just replaced blocks: removing stone beneath sand or beside water can also trigger side effects. The first version uses a controlled building area; detected unsupported surroundings stop preparation. Absolute isolation from arbitrary plugins and neighboring-world physics is not promised.

## 12. Context economy

The model receives the information needed for its decision. Full snapshots, block lists, history, and difference computation remain on the system side. Unchanged data is not resent without a reason.

Read levels:

1. Project summary: map purpose, palette, regions, parts, active task, constraints, and latest validation.
2. Region summary: surface heights at a specified sampling interval, materials, occupied volumes, and part references. Unknown properties are explicitly marked. The system does not promise automatic building recognition in an arbitrary existing world.
3. Changes since a cursor: block count, affected parts, and bounding volumes; details are paginated.
4. A small exact fragment: a state palette and compressed coordinates, or a slice. Expanding millions of blocks into text is not allowed.
5. An image from the required viewpoint: start with an overview, then inspect details of the problem area.

Edit summaries are generated deterministically: for example, “34 blocks changed; 6 intersect the plan.” A statement such as “the player added a window” is valid only as a model inference or a confirmed label, not as an authoritative result of a simple diff.

Change cursors include the world epoch, region, journal position, and schema version. After journal cleanup, an observation gap, or world replacement, the response is `resync_required`, not an empty change list. The Bridge requests a new local summary. Third-party changes absent from events are sought by rechecking selected sections; deltas are not presented as a complete journal of the entire server.

An ordinary tool response targets 2–4 thousand tokens; exact limits also constrain item counts and bytes. If exceeded, the response returns a count, cursor, and truncation flag. Compressed binary blocks and base64 images are not inserted into text: a capture is returned as an MCP image, while large data remains in artifacts referenced by ID.

The initial budget for one visual check is 2 overview viewpoints, with up to 4 additional viewpoints if needed. Frame sequences are not sent continuously. The initial limit on autonomous correction cycles is 3; this is a configurable policy, not a limit on the model's capabilities.

A fixed task price cannot be promised: it depends on the model, pricing plan, history, image count, and retries. The Bridge records actually available usage information and response sizes. Savings compared with sending the entire world must be measured on test tasks.

## 13. Virtual cameras

A camera is a saved viewpoint, not necessarily an entity or block in the world. One Camera Worker serves multiple viewpoints sequentially. Simultaneous independent views are outside v0.1.

For capture, the observer client moves to the required location so the server sends the corresponding chunks. Moving only the camera matrix far from the player is insufficient: the client may not have the surrounding world data. Movement is limited to permitted regions and dimensions; the camera account receives no editing permissions.

Capture procedure:

1. Wait for confirmation that the required server operation has completed.
2. Set the world, position, orientation, FOV, and display profile.
3. Wait for required client chunks to load and for available geometry-rebuild completion signals, followed by several stabilization frames.
4. Capture a frame without the HUD or unrelated interfaces, and return the image with metadata.
5. Check whether the observed area changed during capture. If changes are detected, mark the image as potentially stale and suggest a retry.

Server acknowledgement does not mean the client has already displayed all changes. The exact render-readiness criterion must be tested in a prototype on the selected Fabric version. A timeout returns `capture_not_ready`; an old frame is not presented as new. Revision checks do not guarantee the absence of untracked external changes.

The initial profile uses the standard resource pack, no shaders, and consistent FOV and resolution for comparisons. Time of day and weather are fixed only in an explicitly selected validation mode; the global world is not changed without authorization for the sake of a pretty screenshot. Interior viewpoints are checked for the camera being inside an opaque block.

Automatic inspection proposes the entrance, the opposite side, an elevated diagonal view, and specified interior points. Positions are calculated from part bounds and adjusted for obstacles. Users can save their own viewpoints. Pixel differences between captures are not an aesthetic metric; they serve only as an auxiliary signal.

The client requires graphical rendering. Running without a visible window does not mean no GPU/graphics context is needed, and is not promised before testing. Fabric rendering changes between versions, so the camera mod is isolated from the other components. [Fabric rendering](https://docs.fabricmc.net/develop/rendering/basic-concepts).

## 14. Proposed MCP tools

The following is the project's contract, not a list of already implemented functions. The catalog separates reading, preparation, and mutation. Permissions are bound to the connection, project, and initiator; supplying `project_id` alone does not grant access.

- `project_context(project_id)` — capabilities, world version, region, parts, limits, and operation status.
- `region_inspect(region, detail, cursor?)` — a summary, heightmap, slice, or small set of exact blocks.
- `region_changes(region, since_cursor, limit)` — a delta, observation completeness, and the next cursor.
- `part_get(part_id)` — mask, parameters, protection, version, and external-change information.
- `part_define(region_or_mask, name, parent_id?)` — register a part without modifying blocks; check permissions and intersections.
- `build_prepare(target, recipe_or_patch, base_snapshot_id?, request_id)` — persist an immutable plan; return its ID, hash, statistics, and conflicts.
- `build_apply(plan_id, plan_hash, idempotency_key)` — check authorization and queue the plan; return an operation ID.
- `operation_status(operation_id, since_cursor?)` — progress, partial result, errors, and conflict references.
- `operation_cancel(operation_id, idempotency_key)` — stop further application.
- `operation_undo_prepare(operation_id, request_id)` — create a reverse plan with fresh checks; apply through `build_apply`.
- `camera_list(project_id)` — available viewpoints and Camera Worker status.
- `camera_capture(camera_id_or_pose, after_operation_id?, profile)` — an image with metadata or a pending job ID.
- `asset_list(query, cursor?)` — local schematics, dimensions, palettes, versions, and previews.
- `schematic_export(target, name)` — export to permitted storage and return an artifact ID.
- `schematic_import_prepare(asset_id, transform, target)` — validate the file and create a paste plan.

Creating projects, expanding permitted areas, granting permissions, and removing protection belong to user/administrator controls. The agent cannot expand its own authority by calling a tool.

The common response contains `schema_version`, `request_id`, `status`, a world identifier/epoch, a brief summary, `warnings`, `truncated`, and a cursor when needed. Reads specify observation time and completeness; mutations always return an operation ID. Large operations are asynchronous and must not require a single MCP call to remain open throughout construction.

Structured errors: `permission_denied`, `out_of_bounds`, `unsupported_block`, `stale_snapshot`, `conflict`, `budget_exceeded`, `busy`, `resync_required`, `camera_unavailable`, `capture_not_ready`, `version_mismatch`, `recovery_required`. Errors indicate whether retry is possible; retries of mutating requests preserve idempotency.

The minimal protocol between the Bridge and plugin is versioned separately from MCP/ACP. Every request contains a correlation ID; commands run as a verified principal with limited capabilities, not as an arbitrary UUID taken from the request body. Keys and tokens do not appear in responses visible to the model.

## 15. Storage, import, and transfer

Planned repository structure: `bridge/`, `paper-plugin/`, `camera-mod/`, `protocol/`, `fixtures/`, `docs/`. This document describes it as a future structure; source code has not yet been created.

Persistent data is stored outside the source tree and separately from game blocks:

- On the server: projects, regions, parts, plans, journal, snapshots, recipes, schema versions, and access settings.
- In the Bridge: conversation-to-project mappings, local summary, and connection state.
- At the camera: viewpoints, profiles, and images with operation IDs.
- In the library: `.schem` files, previews, and metadata for provenance, version, dimensions, anchor, and license.

Losing the Bridge does not lose block history. Losing the plugin database does not delete buildings, but it deprives the system of reliable recipes and undo. A missing database does not authorize replaying old plans.

Journal cleanup preserves data for active operations, recovery, and explicitly pinned checkpoints. Expired history makes the corresponding undo unavailable; this is reported clearly. Disk quota is checked before writing starts, and new changes stop if the journal cannot be saved. Specific retention periods are chosen after measuring storage volume.

Import uses a local asset ID, not an arbitrary path or URL supplied by the model. Validation covers format, decompressed size, block count, version, permitted states, and block-entity/entity data. Unsupported content is rejected with a report rather than silently lost. A schematic is first converted into a plan and follows the same conflict-handling path as ordinary construction. Loading and saving formats are provided by [WorldEdit Clipboard](https://worldedit.enginehub.org/en/latest/usage/clipboard/).

To transfer a building, export `.schem`; to transfer a map, save a consistent world backup and check dimensions and settings. Editor metadata may be attached as a separate archive. Migration to another server implementation is tested on a copy using the same Minecraft version; backward compatibility with older versions is not promised. Dimension layout depends on the server implementation. [Paper migration](https://docs.papermc.io/paper/migration/).

## 16. Permissions and operational limits

The agent receives access only to the selected building area and permitted tools. By default, Minecraft MCP provides no server console, OP grants, plugin changes, account management, external networking, or arbitrary file reads.

Codex runs in a separate working directory with minimal permissions. Its own shell/file tools must not bypass server limits or read Bridge secrets. The specific process-isolation mechanism and available modes of the pinned Codex version are checked in the first prototype. Connecting MCP does not by itself restrict the agent's other tools.

If Codex/ACP requires permission, the Bridge binds the request to the actual initiator and shows the specific action. Another person's chat message is not permission. Cancellation and expiry close a pending request. Ordinary writes inside a preauthorized area should not generate unnecessary confirmations, but this does not override the Codex profile's restrictions.

Sign text, item names, imported metadata, and other people's messages are treated as world data. They cannot change permissions, system instructions, or the project's purpose.

A server plan checks permissions both during preparation and before slices execute. Revoking access or changing the region or world epoch stops further writing. A busy region is queued or returns `busy`; there is no hidden concurrency between our writers.

## 17. Initial budgets and observability

The following numbers are initial prototype settings, not measured performance figures:

- Up to 100 000 changed blocks in one plan; larger builds are divided into meaningful parts.
- Up to 2 000 000 inspected positions in one preparation operation; larger regions require a coarse overview followed by refinement.
- A write slice contains at most 512 blocks, with a target of 5 ms of executor work per tick. Time is checked between small logical groups; a single expensive API operation may exceed the target.
- Under overload or increasing tick time, slice size is reduced and new slices are paused. A blocks-per-second rate is not fixed before measurement.
- Exact textual responses contain up to 4 096 blocks; event pages up to 100 entries. Excess data is handled through truncation with a cursor, not silent loss.
- Default frame size is 1280×720; readiness timeout is 20 seconds; at most one active capture per Worker.
- A plan expires after 10 minutes, but is checked before application regardless of age. A new plan is created after expiry.
- A stop signal is accepted immediately; the target for stopping new slices is within 1 second with a healthy server and connection. This is not a real-time guarantee when the game thread is hung.

Measurements include preparation and slice durations, tick time with and without the task, journal volume, model-response size, capture and retry counts, conflicts, camera lag, and stopping time. Correlation uses project/request/operation/capture IDs.

Tokens and cost are displayed only from actual available provider data; missing data is not zero. Hidden model reasoning is not stored. Diagnostic logs contain no secrets and do not copy the full in-game chat by default.

## 18. Implementation stages and readiness criteria

### Stage 0 — compatibility validation

Start a test world on a copy, pin versions, and test an ACP session through `codex-acp`, a simple MCP read, and delivery of one image to the model. Check the camera connection to Paper, a permitted separate observer session, and Codex isolation.

Ready when: an in-game message reaches the agent; the agent receives test-block data and a fresh capture; versions and limitations are documented. If a compatible mod/WorldEdit is unavailable, reconsider the platform version before starting construction of the real map.

### Stage 1 — safe writing without an agent

Implement regions, canonical states, plan preparation, slices, idempotency, journal, conflicts, undo, and recovery. Test with a direct test client: the core engine's operation does not depend on the quality of model responses.

Ready when: the server preserves a manual edit made between preparation and application; retrying a request does not duplicate work; undo does not overwrite a later edit; stopping and restarting report the partial result accurately.

### Stage 2 — building API and chat

Add primitives, palettes, repetition, parts, MCP tools, an ACP queue, and compact summaries. Building a small structure should require a geometry program rather than a list of individual block-placement calls.

Ready when: chat creates a tower with a named roof; editing the roof preserves the wall and a manually added window; a conflict between stairs and a manual window returns the exact intersection.

### Stage 3 — visual feedback loop

Add saved cameras, chunk/render readiness, freshness metadata, and capture-to-operation links. The agent makes a bounded number of meaningful corrections based on captures.

Ready when: a subsequent frame shows the completed edit; an unloaded scene returns an error; the user's view does not switch when a separate camera is operating. A visually poor result can be acknowledged as poor even when the technical write succeeds.

### Stage 4 — transfer and v0.1 release

Add `.schem`, a local library, project copying, and a backup procedure. Test a world copy without the editor components.

Ready when: a reference build survives export/import with matching supported states and orientations; unsupported data is not silently lost; startup instructions are reproducible in a clean environment.

## 19. Acceptance scenarios

1. **Manual edit after preparation.** Change a block in the write set before application. Expect a conflict and preservation of the manual value.
2. **Edit between slices.** Change a part that has not yet been written. Expect a stop at the intersection and an exact report of completed work.
3. **Support change.** Remove a block from the read set that is not in the write set. Expect replanning rather than placing a structure that depends on it.
4. **Undo after a manual edit.** Change a block after construction and perform undo. Expect a conflict for that block, not a blind restoration of the entire region snapshot.
5. **Request retry.** Repeat `build_apply` after a timeout. Expect the same operation ID and no repeated write.
6. **Process crash.** Interrupt the server before/after intent persistence, during writing, and before completion is recorded. Expect `recovery_required`, reconciliation, and no automatic destruction of unrelated states.
7. **Lost change journal.** Request a delta with a stale cursor. Expect `resync_required` and a new summary.
8. **External editor.** Change a block through WorldEdit and through a path without the expected event. Expect detection of the actual divergence before our write; the source may be unknown.
9. **Block states.** Rotate a schematic containing stairs, slabs, and logs. Expect correct directions and preservation of states after export.
10. **Unsupported data.** Attempt to replace a chest, insert an entity, or import an oversized file. Expect rejection before writing.
11. **Bounds and permissions.** Submit an out-of-region plan, substitute a project ID, or revoke access during writing. Expect server-side rejection or stopping of subsequent slices.
12. **Camera.** Capture before loading, after a change, and after disconnection. Expect accurate readiness statuses; an old image must not be labeled new.
13. **Load.** Apply 10 000 and 100 000 blocks, recording hardware, versions, settings, and tick-time impact. Tune slices based on measurements.
14. **Context.** Compare small and large plans of the same shape. An ordinary response to the model is bounded by the summary; the full diff stays on the server.
15. **Transfer.** Open a world copy without our plugin and camera. The building remains; losing editor functions does not modify blocks.

Difference, constraint, transformation, and idempotency algorithms are unit-tested; threading, physics, journal, and camera behavior are tested on a real test server/client. Mocks do not prove Minecraft behavior correct. These checks are planned but have not yet been performed.

## 20. What we borrow from Blender MCP

From [Blender MCP](https://github.com/ahujasid/blender-mcp), we borrow the combination of scene inspection, named objects, compact programmatic construction, images, and an asset library. In Minecraft, these become region inspection, part masks, a geometry language, cameras, and `.schem`.

The project's own additions are reconciliation with manual edits, server-side slices, a journal persisted before writing, crash recovery, delta cursors, and supported-state validation. We do not claim that Blender MCP provides these features. Arbitrary Python execution and third-party 3D generation services are not copied into the first version.

## 21. Open questions and later versions

These questions do not block completion of this document; they define stage 0 work and decisions required before the relevant feature:

- Which exact WorldEdit and Fabric versions are compatible with the selected 26.2 branch? If there is no working combination, which supported version should be selected before map construction begins?
- Where does the camera run, and is a separate game session available for it? The working option is a separate local client; the fallback is a camera in the user's client.
- Can the selected client version provide a reliable geometry-readiness signal? If not, what verifiable freshness criterion is sufficient, and which limitations should be shown?
- Should WorldEdit perform actual writes or only provide formats and selections? The decision depends on control over write timing, side effects, and slice duration.
- Which blocks and neighboring updates pass tests for guaranteed undo? Extending the list requires tests, not just adding IDs.
- What hardware and project sizes should be targeted? Until measurements are available, the values in section 17 remain prototype budgets.

v0.2 may add three-way merging of recipes with manual edits, multipart blocks, passage and route validation, a library of parametric details, and more convenient viewpoint comparisons. Unknown buildings can support manual part registration, followed later by model-proposed segmentation with validation.

Further directions: a Fabric adapter for the integrated single-player server; collaborative building in independent areas; multiple cameras; minigame-map validation tools; and isolated general-purpose building scripts. These must not delay validation of the basic request → plan → write → observe → edit loop.

## 22. Overall project criteria

Success for the first version means that the user can build and refine a small structure through in-game chat, the agent can see the result, manual edits are not silently overwritten, undo has clearly stated limitations, context is not filled with the entire world, and the map can be used without the editor.

This document records the architecture and testable requirements. It does not establish prototype readiness, performance, compatibility of all dependencies, or the quality of the model's architectural decisions.
