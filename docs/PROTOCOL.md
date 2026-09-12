# Prototype protocol

Version: 1. The exact implemented tool catalog is available through MCP `tools/list`, and the capabilities of the installed Paper plugin through `project_context`.

## Paper connection

The service listens on loopback only, at `127.0.0.1:8765` by default. `GET /health` returns status and version information without private data. `POST /v1/rpc` accepts JSON and an `Authorization: Bearer <token>` header.

Request: `{ "method": "project_context", "params": { "player_id": "UUID", "project_id": "default" }, "requestId": "correlation-id" }`.

Success: `{ "ok": true, "result": { ... } }`. Error: `{ "ok": false, "error": { "code": "...", "message": "..." } }`. An error may come with HTTP 400/403; clients must read the structured body. Tokens are never returned in results.

The administrator key is required for `chat_poll`, `chat_reply`, `recovery_review`, and `recovery_abandon`. The agent key permits world tools within the bound owner's project, but not administrative recovery. The MCP process injects `player_id/project_id` from its configuration; the model is not asked to supply them. The plugin rechecks the owner and their current permissions. An isolated test world can explicitly enable `allow-local-automation` with the `console` principal; administrative recovery operations also pass through this scope check.

## Reading and writing

`region_inspect` requires `min/max` as `{x,y,z}` and `detail: "summary" | "blocks"`. Coordinates are inclusive integers. The prototype limit is 4096 positions. The response contains a palette with counts and, for `blocks`, exact states. Data comes from loaded chunks without implicit world generation.

`build_prepare` accepts `recipe: {version: 1, operations: [...]}`, an optional `dependencies` array, and an optional `part_id` for an exact part mask. Geometry: `box(min,max,block,hollow?)`, `line(from,to,block)`, `cylinder(center,radius,height,block,hollow?)`, `repeat(count,offset,operations)`. This is a JSON description, not executable JavaScript.

Preparation returns `plan_id`, `plan_hash`, `changed_blocks`, `region`, and `expires_at`. The full plan and original blocks stay in the journal. `build_apply` accepts this ID, hash, and an `idempotency_key` that remains constant for that logical call. Repeating the same call returns the same operation. A different plan requires a different key.

`operation_status(operation_id)` returns status, counters, and a bounded sample of conflicts. `operation_cancel` stops subsequent slices. `operation_undo_prepare` creates a reverse plan; it goes through the normal `build_apply` and checks. Losing the response to an apply request does not justify creating a different key and repeating the write: first check `project_context` or repeat the original call with the same key.

`part_define(name,operation_id)` registers only blocks actually written by a completed operation. `part_get(part_id)` returns the name, bounds, count, and protection settings. Bounds are not the mask: `build_prepare(part_id)` checks every block against the exact mask. Extensions are created as separate parts.

Before a write, the actual states of target blocks and declared dependencies are checked; the check runs again after the intent is persisted. A mismatch is never overwritten automatically. Undo also accounts for known subsequent writes by our operations, even when a block's value again matches the earlier result.

The plugin observes uncancelled `BlockPlaceEvent` and `BlockBreakEvent` events in the configured world. Such an event revokes the earlier operation's right to undo that block, including an edit followed by a change back to the original state (ABA). These notifications are held only in the current process's memory. After a restart, and for external paths without an observed event, current-content checks remain in place; a complete history of other plugins' actions is not promised.

A full server-side journal of external changes is not implemented yet. `region_changes` returns `resync_required`; the agent uses fresh, bounded reads. This is an explicit prototype limitation.

## Crash recovery

After a restart, an unfinished operation receives `recovery_required` and prevents new writes from starting. Unfinished slices are not replayed automatically. The administrative RPCs below are not exposed as agent MCP tools and do not roll back the world.

`recovery_review` accepts `operation_id`. Its result uses the Java record's field names: `operationId`, `planId`, `positions`, `matchesBefore`, `matchesAfter`, `foreignStates`, `currentDigest`, `sampledAtMillis`. The reviewed mask combines confirmed writes from earlier slices with potential writes from the unfinished slice; skipped positions that were not written are excluded. The counters describe how current values match `before/after`, while `currentDigest` is the SHA-256 digest of this snapshot. Matching content does not prove who made a change.

`recovery_abandon` accepts `operation_id` and `expected_digest`, taken from the latest review's `currentDigest`. The server rereads the mask and rejects the request if its contents have changed. If they match, it leaves all world blocks in place, changes the operation to `failed`, and persists the decision before returning success. The response has the usual `operation_status` shape.

Abandoning uncertain history permanently disables undo for that operation and preserves the invalidation of earlier undo ownership for blocks in the affected mask. New writes are permitted only after the decisions for all unfinished operations have been durably saved. A failure before persistence leaves recovery required; a lost response requires checking `operation_status`, not assuming that a rollback occurred. A stale or incorrect digest is returned as an `invalid_request` RPC error with a reason.

The `applied` status confirms the write and verification result observed by the running server. Chunk files and the journal do not form a shared transaction; automatic verification that all previously completed operations survived a crash is not implemented yet.

## Local schematics

The implemented RPC names are `asset_list`, `schematic_export`, and `schematic_import_prepare`. There are no separate `schematic_list` or immediate `schematic_import` routes. Check `project_context` for these capabilities.

`asset_list` accepts an optional `query` for case-insensitive name search and returns `{ "assets": [...] }`. Each entry contains `assetId`, `name`, `width`, `height`, `length`, `blockCount`, `dataVersion`, `offset`, `sha256`, and `bytes`. The catalog holds up to 64 files; every file is validated when read, so a corrupt schematic may cause the entire list request to fail.

`schematic_export` accepts `name`, inclusive `min/max`, and an optional `origin`. The name contains 1–64 printable characters. `origin` defines the schematic's anchor point and defaults to `min`. The server reads a dense rectangular region, including air, within the current project area and the `max_plan_blocks` limit (at most 4096). Unsupported blocks and entities other than players cause rejection; players are not written to the schematic. The result is one object with the same metadata fields as `asset_list`. The file remains in the `schematics` subdirectory of the plugin's data directory; the RPC returns neither its contents nor an arbitrary path.

`schematic_import_prepare` accepts `asset_id`, `target: {x,y,z}`, and an optional `rotation: 0 | 90 | 180 | 270` (default 0). Rotation is clockwise when viewed from above, around the `target` anchor; the saved `offset` is taken into account. Supported stair directions and log/pillar axes are also transformed. The result is the usual `plan_id/plan_hash/changed_blocks/region/expires_at`; writing requires a separate `build_apply`. Air in the schematic is part of the plan and can remove existing supported blocks. The area, original contents, surroundings, block policy, and conflicts are checked through the normal preparation and application path.

A limited subset of Sponge Schematic v2 is supported: gzip and NBT with a palette of vanilla building block states. Limits are 4096 positions, a 1 MiB compressed file, and 4 MiB of decompressed NBT. Entities, block entities, biomes, unknown top-level fields, required mods, and other format versions are rejected. A `DataVersion` newer than the current server is not accepted; there is no DataFixer conversion. Full compatibility with every WorldEdit schematic is not claimed.

An external `.schem` can be placed in the local schematic directory in advance with a name matching `[A-Za-z0-9][A-Za-z0-9_-]{0,63}.schem`; its filename stem then serves as `asset_id`. Arbitrary paths, network URLs, and symbolic links are not accepted. The prototype does not support file uploads through RPC.

## Chat

`chat_poll` accepts a `client_id` that remains stable throughout the Bridge process's lifetime. The response is `messages` with `id`, `playerId`, `projectId`, `text`, `type`, and position and targeted-block information when available. `type` is either `prompt` or `cancel`. The administrator key is required.

`chat_reply` accepts `id`, `playerId`, `text`, `done`, and an optional `error`. The response is routed only to the initiator of the original request. When the Bridge process changes, unfinished requests are not replayed automatically: the plugin stops changes and asks the user to inspect the world. `/ai stop` pauses new writes regardless of whether the ACP turn has finished.

## Camera

`camera_capture` accepts `camera_id` or `pose: {x,y,z,yaw,pitch,fov?,width?,height?}`. The position refers to the observer's feet; the Worker returns eye coordinates separately. `after_operation_id` checks that the server operation has completed, but does not guarantee that the client has received all of its packets.

Paper serializes requests, moves the configured spectator observer, and sends a request to the local Camera Worker at `127.0.0.1:8766` with a separate key. A pending response contains `captureId`; poll by calling `camera_capture` with `capture_id`. A completed result contains `imageBase64` and `mimeType`, which the Bridge converts into MCP image content rather than a textual base64 string.

Captures include a heuristic assessment of chunk/frame readiness. `serverRevisionVerified: false` remains in place until strict client acknowledgement is implemented. A missing camera, a timeout, or failure to obtain a fresh frame never counts as visual success.

Worker details: [camera-mod/README.md](../camera-mod/README.md). Threading and journal: [world-core/README.md](../world-core/README.md). ACP and isolation: [bridge/README.md](../bridge/README.md).
