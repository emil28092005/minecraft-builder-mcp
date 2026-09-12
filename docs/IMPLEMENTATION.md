# Implementation status

The first prototype has been built and tested on a real local Paper 26.2 server, including the graphical camera client in Prism and image delivery through MCP. It does not yet cover all of v0.1 in the [design](DESIGN.md): the first authenticated Codex turn over ACP remains untested.

## Implemented components

`world-core` contains a Bukkit-independent editor. A declarative recipe becomes an immutable plan with original and desired states, explicit read dependencies, and an expiry time. Validation happens before writing; states are checked again at the point of each write. Disk intents are persisted before the world changes, and results after each slice. File I/O runs off the server thread. Cancellation stops subsequent slices; completed writes remain in history.

`paper-plugin` binds the core to the server thread and checks the owner, world, epoch, region, and protected parts. HTTP is available only on loopback, with separate administrator and agent keys. The plugin registers `/ai`, maintains a small chat queue, sends replies only to the initiator, and controls observer teleportation. The journal and metadata live in the plugin directory; game blocks remain vanilla.

`bridge` exposes 14 MCP tools over stdio, accepts Paper chat events, and launches the pinned `codex-acp`. Conversations are separated by player and project, queues are serialized, and stopping propagates to ACP. The session ID and a compact summary are persisted. The agent receives a separate MCP token; the administrator key stays with the Bridge. Large responses are bounded, and images are delivered as MCP image content.

`camera-mod` contains a local HTTP Worker and Minecraft 26.2 framebuffer capture. The camera waits for spectator mode, the requested position and dimension, neighboring chunk availability, and frame stabilization. HUD/FOV settings are restored after capture or failure. Mixin integration, server-side teleportation, and valid PNGs from several viewpoints have been tested in a real Prism client. The owner and observer used the same UUID.

## Verified checks

Current build: **100 automated tests passing** — 52 in the core, 17 in the Paper module, 20 in the Bridge, and 11 in the camera module. Both JARs have been built; Java results are in Maven/Gradle XML reports, and the combined log for this run is `.runtime/build-final.log`.

Automated Java tests cover geometry, limits, idempotency, read dependencies, conflicts, interrupted slices, cancellation, undo, journaling, disk failures, recovery, and individual HTTP/NBT contracts. Bridge tests use real MCP stdio and a mock ACP agent for conversations, permissions, cancellation, and resumption. Camera tests cover HTTP authentication and validation without launching a graphical client.

The following scenarios passed on real Paper in a separately created test world:

- A block changed after plan preparation: the operation ends in a conflict and preserves the other edit.
- An explicit dependency changed: application stops before writing.
- Construction, a retry with the same key, and checked undo; undo is rejected after a later external edit.
- Operation cancellation, protection of an unsupported source block, and rejection outside the allowed area.
- Forced termination of the test's own server process during a 4096-block operation, restart, and `recovery_required` without automatic replay.
- Administrative recovery review: the agent key is denied, a stale digest is rejected, and abandonment preserves current world contents and permits new operations after the decision is written to disk. Part protection does not prevent review, but continues to prohibit writes to the part.
- A hollow cube through real MCP: 26 blocks; `.schem` export, the asset library, undo, import at the same anchor, and another undo restoring 27 blocks of air.
- A missing camera returns an error without substituting an image.
- After installing the mod in Prism, a 575-block tower was built and four real 1280×720 captures were obtained. The last completed the full Camera → Paper → Bridge → MCP ImageContent path. The first request failed when the viewpoint changed; a retry with the client stationary succeeded. [Test report](ONE_CLIENT_TEST.md).
- A reference-based Gothic hall was built, photographed, and polished through checked recipes: 30,125 final blocks and 53 lanterns. Final verification covered 30,843 positions, including 718 removals; grass growth on eight newly planted soil blocks was explicitly recorded. Day, dusk, and interior captures were inspected. Nonpersistent leaves and waterlogged lantern states were rejected by the updated live Paper policy. [Build report](builds/GOTHIC_HALL.md).

Real `codex-acp` completed `initialize` in a separate profile without login: ACP v1 and session loading support are confirmed. This does not yet test a model turn or tool calls after authentication. The tests did not invoke a model or consume model tokens.

## Significant limitations

**Manual edits.** Comparing expected and current states protects against a different block immediately before writing. Known player place/break events also invalidate block ownership for undo, even if the player restores the previous material. There is no complete interception of changes from other plugins, commands, physics, or all A→B→A transitions; revisions of known external events are not yet persisted across restarts. This prototype cannot be treated as a universal system for merging arbitrary concurrent edits.

**Crashes.** A JSON journal with fsync replaces the planned SQLite storage. The Minecraft world and our journal do not form a single transaction. An ambiguous operation after a crash blocks new writes. Explicit administrative review and abandonment using a fresh digest are available, without modifying the world and with ambiguous undo disabled. There is no automatic replay/rollback. The full journal is loaded at startup and does not yet support archival.

**Scope and performance.** One owner, project, and world; at most 4096 blocks and 512 explicit dependencies per plan. Writes are limited to 128 blocks with a target budget of up to 5 ms per slice; verification costs and the JVM prevent a hard tick-time guarantee. Full preparation of a bounded plan still runs on the server thread. Long-running load tests on a large server have not been conducted.

**Context.** Project context contains brief metadata, up to 20 operations, and up to 64 parts; exact blocks are read separately. `region_changes` currently returns `resync_required`. The agent therefore rereads selected areas; the promise of reading only deltas is not implemented yet. ACP conversations support persistence and summaries, but model usage has not been measured here.

**Blocks and schematics.** A limited set of 71 vanilla materials is allowed, including selected stairs and slabs, lanterns, iron chains (`iron_chain` in Minecraft 26.2), iron bars, stone brick walls, oak leaves, moss, gray and brown glass, glowstone, and gold blocks; `project_context` returns the exact list. Leaves are allowed only with `persistent=true` so that they do not decay without a tree. Waterlogged blocks, containers, doors, redstone, and other complex blocks are unsupported. Checks of surrounding blocks intentionally restrict use near unsupported environments. Sponge v2 `.schem` is implemented without a WorldEdit dependency: up to 4096 blocks, up to 64 files, rotations in multiples of 90°, no entities, block entities, or biomes, and no conversion between game versions. Its strict codec currently supports the original 61-material palette; the ten new decorative materials are available through normal building operations. Unsupported content is rejected rather than removed during export.

**Building language.** Box, line, cylinder, and repeat are available. Arches, arbitrary transforms, decorative palettes, JavaScript/Python execution, and automatic reconciliation of recipes with manual edits are not yet available. A registered part contains an exact mask of blocks actually written, not its entire bounding box.

**Camera.** A configured spectator client is required; in the tested scenario this is the same player as the project owner. During capture, that player cannot continue normal building. Game mode and original position are not restored automatically. Frame readiness is heuristic: `serverRevisionVerified: false`. Neighboring chunk availability and stable rendering do not prove receipt of all server updates. Real construction and captures have been tested; third-party shaders, disconnection during capture, and all forms of window freezing have not yet been tested.

**ACP.** Separate HOME/CODEX_HOME directories are used; extra integrations, shell, and forwarding of the administrator token are disabled. This is not OS-level isolation. The pinned adapter maps `read-only` mode to `workspace-write`; temporary paths may remain accessible, and the pinned CLI keeps the `unified_exec` flag enabled when `shell_tool` is disabled. Additional permission requests are currently rejected. Permissions for the dynamically supplied Minecraft MCP need testing in the first real turn. Details and diagnostics are in the [Bridge README](../bridge/README.md).

## Next acceptance stage

1. The user logs in to the dedicated Codex profile, connects to Paper, and binds the owner. Test a small build requested through in-game `/ai`, response streaming, MCP use, and cancellation.
2. Extend the verified single-client Prism scenario: test disconnection/freezing during capture and convenient switching between building and camera use.
3. Extend the demonstrated build → inspect → correct cycle to an authenticated ACP model turn, then reassess release readiness, limits, context deltas, and geometry extensions.
