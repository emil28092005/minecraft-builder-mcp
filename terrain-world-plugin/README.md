# Initial terrain worlds

## Natural Shacraft profile

Configure `terrain-profile: shacraft-natural-v1`, copy `examples/terrain/shacraft-natural-world.json` as the recipe, and select a new world name such as `shacraft_lobby_v2`. The recipe supplies the seed, footprint and palette; its feature list must be empty because the versioned profile defines its own landforms. This is not a new MCP terrain recipe type.

Independent OpenSimplex2S fBm, weighted ridged noise, moderate coordinate warping and authored mountain corridors shape the skyline around soft central hills and connected water courses. There are no rectangular platform features. Before integer flooring, all heights exactly match the approved study's full-field SHA-256. No hydraulic erosion, biome pass or automatic route grading is implied.

Steep columns expose stone/andesite without a dirt layer. Gentle dry columns retain grass and soil; submerged columns have rock beds and continuous source water. Geometry, profile and material version are bound into the immutable generation identity. Live pre-generation checks every column's height, top material and water fill.

FastNoiseLite is vendored under `noise/` from upstream commit `785f37a9ad76e283586a379675085f2063ae03f7`, with a package declaration added. Its MIT notice is present in the source and under `META-INF/LICENSE-FastNoiseLite.txt` in the jar.

## Recipe-based initial worlds

This optional Paper 26.2 plugin creates and reloads a separate world using the existing `TerrainRecipe` height field. It loads before MinecraftBuilderMCP. Installation is inert until `enabled: true` is explicitly set in `plugins/ShacraftTerrain/config.yml`.

Build with `./mvnw package`, install `target/terrain-world-plugin-0.1.0-SNAPSHOT.jar`, and copy a sculpt recipe without preserve masks into the plugin data directory as `terrain.json`:

```yaml
enabled: true
world: shacraft_lobby
recipe: terrain.json
water-level: 48
border-size: 2048
```

The Shacraft example is `../examples/terrain/shacraft-lobby-world.json`: a 768×768 layout translated 64 blocks upward from the original design recipe. Spawn plaza Y=106; station Y=118; airship harbor Y=124. The west lake has a rock bed at Y=38 and water through Y=48. The ravines share that water level. Omit `water-level` for dry terrain.

Generation builds solid foundations down to world bedrock, follows the recipe's soil layers, replaces submerged surface blocks with rock and fills submerged columns with source water. There are no vanilla caves, structures, decorations or mobs. The recipe continues outside the footprint so neighboring chunks do not end at artificial vertical cuts. The optional exploration border can sit beyond the design footprint to keep its visible wall out of construction views; it does not expand the editor's authorized bounds. Day and weather are fixed for construction.

This is **initial world generation**, not an editor apply operation. It has no block-by-block undo journal. Existing chunks are never regenerated. The persisted generation manifest binds the generator version, recipe and water level; changing them under the same world name fails closed. Existing world folders without that manifest are refused. Keep the generator plugin, its configuration and manifest with world backups so future chunks use the same terrain.

Commands:

- `/lobby`: teleport yourself to the central spawn. Requires operator permission.
- `/lobby status`: inspect the current pre-generation pass.
- Server console `lobby <player>`: teleport an online player to the lobby.
- Server console `lobby generate`: asynchronously load/generate the recipe footprint one chunk at a time. Verify every column's visible height, water fill and non-air bed; save `generation-report.json` on completion. Do this before building: later edits legitimately produce mismatches. Repeating the command loads existing chunks, without overwriting them.
- Server console `lobby map <name>`: export an actual top-down surface map of the configured footprint, with no player or camera client. For example, `lobby map layout-before` writes `plugins/ShacraftTerrain/maps/layout-before.json` and `layout-before.png`. Use `lobby status` to see progress. Names use 1–48 lowercase letters, digits, underscores or hyphens; an existing map is never overwritten.

The map exporter reads one existing chunk per tick on the server thread and refuses to generate missing chunks. It changes no blocks. A detached worker renders the PNG and writes the JSON after all columns have been captured. Maps are bounded to 4,194,304 columns. The height and material describe the highest non-air block, including water and survey markers, so bridges and roofs hide the surfaces below. PNGs show actual surface materials with slope shading; colored concrete keeps its unshaded survey color. This is a server-derived orthographic map, not a screenshot or a perspective camera.

The compact JSON format `minecraft-builder-surface-map-v1` includes the world UUID/key, inclusive X/Z bounds, capture timestamps, `palette`, `palette_rgb`, and flat `surface_y` / `material_index` arrays. Index a column with `(z - min_z) * width + (x - min_x)`. North is at the top (negative Z), east at the right (positive X), and each PNG pixel represents one block. These are live, sequential chunk observations rather than an atomic snapshot: pause edits while capturing a before/after verification map. The exporter does not certify a particular build revision.

MinecraftBuilderMCP still supports one active project. Before selecting this world in its config, stop the server and archive the previous project's configuration, metadata and journal together. Use a new project ID and world epoch, a fresh journal directory, and explicit project bounds within the new world. Keep normal per-plan limits and owner authorization. The player-facing `/ai area` command retains its 2-million-block selection limit; an operator can configure the full lobby envelope directly for staged work.

For the local Shacraft session, connect to `127.0.0.1:25575`, then `/lobby`. The old `world` remains loaded; console `execute in minecraft:overworld run tp <player> 0 5 0` can return a player there. The active AI editor remains bound to Shacraft until the old project is restored offline.

Unit checks cover solid foundations, lake source-water continuity, negative chunk coordinates, the complete design's height bounds and invalid initial-world modes. Live generation reports cover real Paper chunks; they are not screenshots or a visual approval of the composition.

The first live Shacraft pass generated/loaded 2304 chunks in 144 seconds and verified all 589,824 columns, including 59,609 water columns, with zero mismatches. See [the saved report](../docs/references/shacraft-lobby-generation-report.json). Terrain reaches Y=203. The local server uses `--heap 4G` and `view-distance=32`; the client also needs an adequate render distance.

Paper 26.2 stores this dimension under `world/dimensions/minecraft/shacraft_lobby`. Back up the complete primary `world` save (including `level.dat`) together with both plugins' data and the generator jar. Copying only a legacy top-level `shacraft_lobby` folder is not a valid backup for this version.

The live natural v2 pass verified all 589,824 columns across 2304 chunks in 275 seconds: zero height/material/water mismatches, 42,399 water columns, highest surface Y=204. See [the report](../docs/references/shacraft-natural-v2-generation-report.json). The separately retained v1 report describes the earlier rectangular layout.
