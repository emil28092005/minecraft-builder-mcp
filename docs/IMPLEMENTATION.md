# Implementation status

The first prototype has been built and tested on a real local Paper 26.2 server, including the graphical camera client in Prism and image delivery through MCP. It does not yet cover all of v0.1 in the [design](DESIGN.md): authenticated ACP text replies, MCP reads, and a one-block build/inspect/undo cycle are verified; broader model-driven construction and cancellation tests remain.

## Implemented components

`world-core` contains a Bukkit-independent editor. A declarative recipe becomes an immutable plan with original and desired states, explicit read dependencies, and an expiry time. Validation happens before writing; states are checked again at the point of each write. Disk intents are persisted before the world changes, and results after each slice. File I/O runs off the server thread. Cancellation stops subsequent slices; completed writes remain in history.

`paper-plugin` binds the core to the server thread and checks the owner, world, epoch, region, and protected parts. HTTP is available only on loopback, with separate administrator and agent keys. The plugin registers `/ai`, maintains a small chat queue, sends replies only to the initiator, and controls observer teleportation. The journal and metadata live in the plugin directory; game blocks remain vanilla.

`bridge` exposes 19 MCP tools over stdio, accepts Paper chat events, and launches the pinned `codex-acp`. Conversations are separated by player and project, queues are serialized, and stopping propagates to ACP. The session ID and a compact summary are persisted. The agent receives a separate MCP token; the administrator key stays with the Bridge. Large responses are bounded, and images are delivered as MCP image content. The two material discovery tools return bounded search pages and property domains on demand, without placing the full registry in context.

`camera-mod` contains a local HTTP Worker and Minecraft 26.2 framebuffer capture. The camera waits for spectator mode, the requested position and dimension, neighboring chunk availability, and frame stabilization. HUD/FOV settings are restored after capture or failure. Mixin integration, server-side teleportation, and valid PNGs from several viewpoints have been tested in a real Prism client. The owner and observer used the same UUID.

## Verified checks

The original full build passed **100 automated tests** — 52 in the core, 17 in the Paper module, 20 in the Bridge, and 11 in the camera module. A later Bridge run passed **40 checks**, including nested cases. Those historical regressions cover streamed text, Code Mode configuration migration, MCP startup failures, and narrowly scoped one-use approvals. Both JARs were built; Java results are in Maven/Gradle XML reports, and the combined log for that run is `.runtime/build-final.log`. Validation of the current registry expansion is recorded separately in [MATERIALS.md](MATERIALS.md#validation).

The registry expansion passed **145 Maven tests and 47 Bridge checks**. Its isolated Paper 26.2 probe described and roundtripped all **1,196 registered block defaults**, including 186 block-entity defaults, and passed **5,392 independent-property variants** through fresh placement, same-material changes and snapshot restoration. Live HTTP tests additionally verified inventory-preserving edits, conflicts on changed block-entity data, new-material schematic rotation and exact chest/sign/pot restoration after a server restart. These results cover the isolated integration server; lobby deployment is tracked in the material validation report.

Automated Java tests cover geometry, limits, idempotency, read dependencies, conflicts, interrupted slices, cancellation, undo, journaling, disk failures, recovery, and individual HTTP/NBT contracts. Bridge tests use real MCP stdio and a mock ACP agent for conversations, permissions, cancellation, and resumption. Camera tests cover HTTP authentication and validation without launching a graphical client.

The following scenarios passed on real Paper in a separately created test world:

- A block changed after plan preparation: the operation ends in a conflict and preserves the other edit.
- An explicit dependency changed: application stops before writing.
- Construction, a retry with the same key, and checked undo; undo is rejected after a later external edit.
- Operation cancellation, protection of a then-unsupported source block under the original palette policy, and rejection outside the allowed area.
- Forced termination of the test's own server process during a 4096-block operation, restart, and `recovery_required` without automatic replay.
- Administrative recovery review: the agent key is denied, a stale digest is rejected, and abandonment preserves current world contents and permits new operations after the decision is written to disk. Part protection does not prevent review, but continues to prohibit writes to the part.
- A hollow cube through real MCP: 26 blocks; `.schem` export, the asset library, undo, import at the same anchor, and another undo restoring 27 blocks of air.
- A missing camera returns an error without substituting an image.
- After installing the mod in Prism, a 575-block tower was built and four real 1280×720 captures were obtained. The last completed the full Camera → Paper → Bridge → MCP ImageContent path. The first request failed when the viewpoint changed; a retry with the client stationary succeeded. [Test report](ONE_CLIENT_TEST.md).
- A reference-based Gothic hall was built, photographed, and polished through checked recipes: 30,125 final blocks and 53 lanterns. Final verification covered 30,843 positions, including 718 removals; grass growth on eight newly planted soil blocks was explicitly recorded. Day, dusk, and interior captures were inspected. At that stage, the narrower Paper policy rejected nonpersistent leaves and waterlogged lantern states; the runtime registry expansion removes that material restriction. [Build report](builds/GOTHIC_HALL.md).

Real `codex-acp` completed `initialize` in a separate profile without login: ACP v1 and session loading support are confirmed. That initial check did not invoke a model or consume model tokens. Dedicated ChatGPT sign-in and real authenticated ACP calls to `project_context` and `region_inspect` have since passed against Paper. A subsequent model turn placed and verified one oak-plank block at (24, -60, -45), then used checked undo and verified air. Place operation: `ae0166c8-6d03-45ab-a80a-48b644819a2b`; undo: `751017ba-8e07-433b-b38d-71dcc8cf2330`. A local proxy restricted writes to the fixture and its recorded undo.

## Significant limitations

**Manual edits.** Comparing expected and current states protects against a different block immediately before writing, including a block entity's extra data. A block-level `region_inspect` returns opaque `snapshot_id` digests for block entities; callers using `expected_blocks` must preserve those digests. Without a caller snapshot, preparation reads the current full state itself. Known player place/break events also invalidate block ownership for undo, even if the player restores the previous material. There is no complete interception of changes from other plugins, commands, physics, or all A→B→A transitions; revisions of known external events are not yet persisted across restarts. This prototype cannot be treated as a universal system for merging arbitrary concurrent edits.

**Crashes.** A JSON journal with fsync replaces the planned SQLite storage. The Minecraft world and our journal do not form a single transaction. An ambiguous operation after a crash blocks new writes. Explicit administrative review and abandonment using a fresh digest are available, without modifying the world and with ambiguous undo disabled. There is no automatic replay/rollback. The full journal is loaded at startup and does not yet support archival.

**Scope and performance.** One owner, project, and world; at most 4096 blocks and 512 explicit dependencies per plan. Writes are limited to 128 blocks with a target budget of up to 5 ms per slice; verification costs and the JVM prevent a hard tick-time guarantee. Full preparation of a bounded plan still runs on the server thread. Long-running load tests on a large server have not been conducted.

**Context.** Project context contains brief metadata, catalog counts/version, up to 20 operations, and up to 64 parts; exact blocks are read separately. Material IDs are discovered with `material_search` (16 results by default, 32 maximum). `material_describe` returns the default and each property's allowed values for one selected material, never every state permutation. Results can be reused while `catalog_version` is unchanged. `region_changes` currently returns `resync_required`. The agent therefore rereads selected areas; the promise of reading only deltas is not implemented yet. ACP conversations support persistence and summaries, but model usage has not been measured here.

**Blocks and schematics.** Ordinary building recipes use the running server's complete registered vanilla block catalog and exact state parser, including waterlogged blocks, fluids, containers, doors and redstone. Item-only catalog entries cannot be placed. Same-material block-state edits preserve existing block-entity data; new block entities use defaults. There is no raw NBT, sign-text, entity or inventory editor. Doors, beds and tall plants require explicit placement of every part; attachment, gravity and support rules still matter. Random ticks, fluid flow and redstone reactions are game behavior, not a fully journaled extension of direct block writes; checked undo does not promise to reverse all their consequences. Terrain recipes and brushes retain their narrower palette and scan policies.

Sponge v2 `.schem` is implemented without a WorldEdit dependency: up to 4096 blocks, up to 64 files and rotations in multiples of 90°. Its palette now uses registered block states and runtime rotation. Entity/block-entity NBT payloads, biomes and conversion between game versions remain unsupported. Export rejects every block entity rather than losing its extra data; import can place a block-entity block type from a state-only palette through the normal default/preservation rules. [Material workflow and precise boundaries](MATERIALS.md).

**Building language.** Box, line, cylinder, and repeat are available. Arches, arbitrary transforms, decorative palettes, JavaScript/Python execution, and automatic reconciliation of recipes with manual edits are not yet available. A registered part contains an exact mask of blocks actually written, not its entire bounding box.

**Camera.** A configured spectator client is required; in the tested scenario this is the same player as the project owner. During capture, that player cannot continue normal building. Game mode and original position are not restored automatically. Frame readiness is heuristic: `serverRevisionVerified: false`. Neighboring chunk availability and stable rendering do not prove receipt of all server updates. Real construction and captures have been tested; third-party shaders, disconnection during capture, and all forms of window freezing have not yet been tested.

**ACP.** Separate HOME/CODEX_HOME directories are used; extra integrations, shell, and forwarding of the administrator token are disabled. This is not OS-level isolation. The pinned adapter maps `read-only` mode to `workspace-write`; temporary paths may remain accessible, and the pinned CLI keeps the `unified_exec` flag enabled when `shell_tool` is disabled. The bundled Code Mode host is enabled for models that require it. Correlated calls to known Minecraft tools receive one-use approval during the active owner request; other permission requests remain rejected. Details and diagnostics are in the [Bridge README](../bridge/README.md).

## Next acceptance stage

1. Extend the verified ACP one-block roundtrip to larger in-game `/ai` builds, real cancellation, and reconnect recovery.
2. Extend the verified single-client Prism scenario: test disconnection/freezing during capture and convenient switching between building and camera use.
3. Extend the demonstrated procedural Gothic-hall workflow to larger authenticated ACP builds, then reassess release readiness, limits, context deltas, and geometry extensions.

## Terrain toolkit

Deterministic terrain recipes now support hills, ridges, plateaus, dry basins/channels and terraces. `terrain_preview` returns a native heightmap and cached recipe ID; `terrain_prepare` creates a checked tile plan for the existing apply/undo pipeline. Offline previews and bounded resumable batches are available through `scripts/terrain.py`. See [Terraforming tools](TERRAFORMING.md) for examples, safety semantics and scale limits.

`terrain_brush_prepare` additionally edits existing terrain relatively: raise/lower, flatten and snapshot-based smoothing, with soft edges, preserved columns, native before/after previews and checked read dependencies. See the relative-brush section of the terraforming guide.
