# Runtime materials

Ordinary building recipes accept every vanilla block type and valid block state registered by the running Minecraft server. The old fixed building palette has been removed. The same catalog also discovers items, but an item without a block form cannot be placed by `build_prepare`.

This does not require loading the registry into the agent's context. `project_context.material_catalog` returns only the catalog version, counts and search limits. The block and item counts overlap: a material can have both forms. `material_search` retrieves a small page of candidate IDs; `material_describe` retrieves details for one selected material.

## Discover a detail, then build it

1. Read `project_context` for the authorized area, limits and material-catalog version. Inspect the local construction area.
2. Search a relevant family, for example `material_search({"query":"spruce trapdoor"})`. Search is case-insensitive and every whitespace-separated token must occur in the material ID.
3. Describe the chosen ID with `material_describe({"id":"minecraft:spruce_trapdoor"})`. Use the returned `default_state` and allowed property values to select its facing, half, open and waterlogged state.
4. Compile bounded geometry with that state. Keep attachments, supports, surrounding clearance and every required half or part explicit.
5. Prepare, inspect the returned plan summary, apply with a stable idempotency key, and poll `operation_status`. Read back the relevant states and inspect an actual camera image when available.

Search for 1–3 details at a time. Reuse already described defaults and property values while `catalog_version` is unchanged; repeat discovery after a version change or an unknown-state error. An unchanged catalog does not make a previous world snapshot current.

`material_search` accepts a query of at most 96 printable characters, `kind: "block" | "item" | "all"` (default `block`), `limit: 1..32` (default 16), and an optional cursor of at most 100 characters. A response contains `catalog_version`, normalized `query`, `kind`, `total`, a bounded `results` array of `{id, block, item}`, and an optional `next_cursor`. Cursors belong to the catalog version and query/kind; start a new search if either changes. An empty query still returns only one page.

`material_describe` accepts one exact `minecraft:` ID of at most 128 characters. A block entry returns `default_state`, `properties` mapping each property name to its allowed values, and optional compact `behavior` hints. These are individual property domains, not every Cartesian state combination. An item-only result returns `placeable: false` and no block state. Unknown materials and unavailable runtime property introspection fail explicitly.

No tool descriptions contain the complete registry. No call needs to describe all materials in advance. State strings are bounded to 1024 characters; ordinary MCP text results retain the 64 KiB response limit. The guidance shared by MCP and ACP explicitly requests focused searches and reuse of results. The full recipe cookbook is also kept outside the default prompt.

## Block states and extra data

A recipe state has the form `minecraft:block[property=value,...]`. The server validates IDs, property names and values and canonicalizes the result. Omitted properties use the server defaults. Fluids, waterlogged blocks, nonpersistent leaves, carpets, doors, redstone and block-entity block types are accepted when present in the runtime registry.

Block-entity data is separate from the state string. A chest's orientation is a state; its inventory is extra data. A sign's block type and rotation are states; its text is extra data. New block entities use their default data. A same-material state edit preserves existing extra data. Replacing a block entity with another material uses the normal checked snapshot and undo path; the original data stays in the server-side history, not in the agent prompt.

With `region_inspect(detail: "blocks")`, a block entity includes an opaque `snapshot_id` alongside `pos` and `state`. When supplying `expected_blocks`, include every desired position exactly once and copy each returned digest unchanged. A digest is mandatory for an existing block entity, even if it is empty or has default data. The server rejects omitted required digests and stale states/data before preparation. The digest is a lowercase 64-character SHA-256 value; it does not reveal inventory or NBT contents. If no `expected_blocks` array is supplied, preparation captures the current full state itself.

```json
{
  "pos": {"x": 0, "y": 64, "z": 0},
  "state": "minecraft:chest[facing=north,type=single,waterlogged=false]",
  "snapshot_id": "<copy the exact 64-character digest from region_inspect>"
}
```

The digest above is a placeholder, not a valid request. Copy the complete inspected entry instead of inventing or regenerating its digest. A conflict is evidence of a changed world and requires a localized decision; do not read a new snapshot merely to force the old design through.

There is no arbitrary NBT, item-inventory, entity, sign-text, banner-pattern or decorated-pot-data editor. Discovering an item does not create an item stack or an item entity. Existing project-specific text displays and game-selection logic remain separate from these generic building tools.

## Placement behavior

Support for a block state does not construct its neighbors. Explicitly place both door halves, both bed parts, every tall-plant half and all other pieces required by a design. Give attached blocks valid support, supply valid flower substrates and check directional states. Decorative leaves should normally use `persistent=true`; accepting natural decay states does not make them suitable for a permanent facade.

Fluid flow, gravity, random ticks, plant growth, oxidation and redstone reactions are Minecraft simulation behavior. The operation journal and checked undo cover direct recorded writes and their checked snapshots, not every later simulation consequence. Use a bounded prototype with the required containment and support, then inspect after game updates before repeating a motif. A prepared plan alone is not evidence that a decorative assembly remains stable.

Terrain generation and relative brushes have separate policies. Their existing limited terrain palettes remain; brushes still reject fluids and structures in the scan window. Placing water through ordinary checked geometry does not add a fluid-aware terrain brush or hydraulic erosion API.

## Schematics and preservation

The Sponge v2 codec accepts registered block states and uses the runtime's block-state rotation behavior. Limits remain 4096 positions per asset, 64 local files, 1 MiB compressed input, 4 MiB decompressed NBT and rotations of 0/90/180/270 degrees.

Entity and block-entity NBT payloads are rejected on import. A state-only palette can name a block-entity block type; it follows ordinary new-default or same-material-preservation rules when prepared. Export refuses every block entity, including empty ones, rather than silently discarding its extra data. Biomes, unknown top-level fields, required mods and game-version conversion remain unsupported. A `.schem` therefore does not replace a complete world checkpoint.

Keep the recipe, inspected snapshots, operation receipts and useful photographs with an appropriate world backup. The historical Stage 07 snapshot contained 100 material IDs; the decoration recipe catalog preserves that dated capability basis for reproducibility. It does not limit the current server registry or need to be expanded into thousands of entries.

## Validation

The registry expansion passed validation against a separate Paper 26.2 build 123 integration server on 2026-09-13. Its catalog version is `00474abd322518089309784c`: **1,691 materials, 1,196 block types and 1,537 item types**. Block/item counts overlap. These are observations from that runtime, not fixed protocol constants.

Completed checks:

- Real MCP stdio advertised 19 tools and delivered catalog discovery responses. The catalog summary was 130 bytes of compact JSON; the measured full `project_context`, including recent operation history, was 3,375 bytes. A focused three-result copper-trapdoor search was 374 bytes and one candle description was 324 bytes. A default 16-result HTTP search page was 1,256 bytes. These are response byte measurements, not model token counts or a model-usage benchmark.
- The runtime property probe described all 1,196 block types successfully. The largest description was 682 bytes, with at most seven properties on one block and at most 27 values in a property domain. No Cartesian state list was returned.
- The final registry probe placed and read back all 1,196 default block states, including 186 block-entity defaults, with zero failures. It also passed 5,392 deduplicated cases that vary individual properties: every case passed fresh placement, a same-material state edit, and restoration of the original snapshot. The temporary fixture anchor was restored.
- Eleven live HTTP scenarios passed: pagination and bounds, property domains, item-only distinction, new block/fluid apply and undo, paired door halves, private block-entity digests, same-material chest rotation with inventory preservation, stale inventory conflicts before preparation and during application, replacement without inventory drops, a waterlogged cherry-trapdoor schematic rotated 90 degrees, and refusal to export block entities.
- A further check after a real Paper restart used checked undo to restore exact chest, sign and decorated-pot snapshot digests. The chest retained its seven diamonds and the sign retained the known fixture text `MCP snapshot test`.
- The full Maven suite passed 145 tests and the Bridge suite passed 47 checks, including nested cases. Bridge coverage includes bounded discovery transport, state/NBT limits, block-entity snapshot digests, scoped tool approvals and one-time delivery of changed instructions to resumed sessions. After the final narrow structure-block mode fix, the Paper/core package and its tests passed again.

The probe covers every registered default state and individual-property variants, not the Cartesian product of all properties or long-running redstone/fluid behavior. The live HTTP scenarios separately verify the operation journal, stale-data conflicts and restoration after restart.

**Lobby deployment:** the updated plugin is running in `shacraft-lobby-v2`. A fresh backup was made while the server was stopped. After restart, the project, world ID and epoch, selected region, operation count and part count matched the previous context; recent operations remained applied. Real MCP stdio advertised all 19 tools and successfully returned the new catalog, search and descriptor. The chat Bridge was restarted with its existing state directory, and its ChatGPT login remained available. These deployment checks were read-only and did not modify the lobby's construction.

The [verification receipt](references/material-registry-verification.json) preserves the registry counts, test coverage, response sizes and deployed plugin digest without private credentials or block-entity contents. On the lobby, the full `project_context` measured 4,840 bytes with its history; its catalog summary remained 130 bytes. Context size still depends on the requested world information, rather than just the catalog.

Local evidence lives in `.runtime/material-test-server/live-receipt.json`, `.runtime/material-test-server/mcp-receipt.json` and `.runtime/material-test-server/plugins/MaterialRegistryProbe/report.json`. These test-runtime paths are not distributed assets or links to files in Git.

## Repeating the live fixture

The separate [registry probe](../scripts/material-registry-probe/README.md) retains the source and builder for the exhaustive default-state and individual-property checks. Its helper plugin is opt-in and belongs only in the disposable test server; it is not part of the production plugin.

[`scripts/test-materials-live.py`](../scripts/test-materials-live.py) is an opt-in integration fixture, separate from ordinary automated tests. It changes and restores bounded test blocks, uses known chest/sign data, and exercises a real server restart. It does not create or launch a server.

Provision a separate Paper test server in `.runtime/material-test-server` with project `material-integration`, a region whose maximum X is 511, local automation enabled for the `console` principal, HTTP on `127.0.0.1:18765`, and RCON on `127.0.0.1:25586`. The operator supplies that server's private agent and RCON credentials in its local `test-access.json`; keep the file outside Git. The fixture checks the project and region before mutation and is intentionally not configurable to point at the lobby.

With that isolated server running, invoke from the repository root:

```bash
python3 scripts/test-materials-live.py before-restart
```

After the phase finishes and writes `live-receipt.json`, cleanly stop and restart **that same isolated test server**, preserving its world, plugin data and journal. Then run:

```bash
python3 scripts/test-materials-live.py after-restart
```

The second phase consumes the saved operation receipt and checks restoration after restart; running it twice is not a fresh test. The fixture leaves known test fixtures and an exported schematic in the isolated world/library. It must not be run against a shared lobby or treated as a read-only health check.
