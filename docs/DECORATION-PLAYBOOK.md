# Minecraft decoration playbook

Research reviewed **13 September 2026** for the Shacraft lobby. These notes combine primary Minecraft articles, interviews with builders and official Java release notes with our own measured-building workflow. They record reusable design knowledge; this research stage makes no changes to the world.

Start with this page, then open only the relevant entry in the [14-recipe cookbook](DECORATION-RECIPES.md). The [structured catalog](recipes/decorations.json) is the authoritative source for recipe dimensions, materials, assembly and acceptance checks. Recipes are original design proposals, not copied tutorial schematics, executable `build_prepare` payloads or claims of completed construction.

## Short working memory

1. Give the place a purpose and identify the main arrival, decision point and place to pause.
2. Resolve silhouette, structural rhythm and major material fields before surface details.
3. Assign each material a role. Keep a dominant family, supporting material and selective accent.
4. Make depth with real layers: a recessed window, a projecting sill, a supported eave. Keep the closure behind decorative partial blocks intact.
5. Cluster texture changes where wear, moisture, construction or planting explains them. Preserve calm surfaces between accents.
6. Arrange furniture as useful groups. Keep entrances, lift controls and destination signs visible.
7. Measure the actual ground, floor and route before placing a standard module. Preserve established widths and headroom.
8. Check material availability, exact states, rotation, attachment, substrate and stability after updates.
9. Build one sample, inspect it at player height and from the approach, then repeat with controlled variation.
10. Compare real day/night photographs and inspect concealed sides. A map, plan or successful placement receipt is not a lighting review.
11. Keep unfinished rooms closed. Decoration must not create a passage or a way around an existing enclosure.
12. Save recipe IDs, anchors, rotations, seeds, operation receipts and selected photographs; load only the local context needed for the next edit.

These are project working rules. Numeric dimensions below are starting proposals for this lobby, not universal Minecraft laws.

## What the research changes in our practice

### Shape and depth before micro-detail

Aegos and Shannooty describe working out roofs and the overall silhouette before detailing. Milosz explains using a consistent palette and comparatively simple textures at large scale. For Shacraft, the clock tower should remain the first readable feature; a dormer, finial or cornice is useful only if it strengthens that composition. Review a proposed feature from the main approach before copying it around the roof. [Tranquil Towers](https://www.minecraft.net/en-us/article/tranquil-towers), [The Sky is No Limit](https://www.minecraft.net/en-us/article/sky-no-limit).

The glass-pane article explicitly connects windows with variation in wall depth. Our adaptation uses a recessed **full-glass closure** and a projecting stone surround, since public containment is part of this project. Thin panes can be useful elsewhere, but their appearance does not prove a sealed boundary. Quartz also provides a consistent family for architecture and small furnishings. [Taking Inventory: Glass Pane](https://www.minecraft.net/en-us/article/taking-inventory--glass-pane), [Build With It: Quartz](https://www.minecraft.net/en-us/article/build-with-it--quartz).

### Material variation should explain the surface

Rough diorite and its polished form demonstrate that texture intensity changes the character of a surface; a brighter material is not automatically a quieter one. Mossy cobblestone can suggest age. Our design inference is to place texture by cause: moisture and earth contact at a retaining wall, wear near an approach, clean edges around a maintained station entrance. Use connected patches rather than an independent random material choice for every block. [Build with It: Diorite!](https://www.minecraft.net/en-us/article/build-it--diorite-), [Build With It: Cobblestone!](https://www.minecraft.net/en-us/article/build-with-it--cobblestone-).

A color gradient is optional. If used, it should reinforce a chosen mass or light direction and read at the intended distance. Do not impose an arbitrary weathering percentage or a fixed color-ratio formula on every building. We should compare a small clean sample and a restrained textured sample before committing a facade.

### Interior groups should tell players how to use the room

The builders in *Interior Motives* emphasize purpose and agreement between inside and outside. Jonathan “SnugSites” discusses livable furniture arrangements and the value of two-block partitions when rooms need different finishes on each face. We should build waiting groups, information points and viewing pockets, reserving a clear route between them; an empty section of floor can be necessary circulation. [Interior Motives](https://www.minecraft.net/en-us/article/interior-motives), [Fantastic Furniture](https://www.minecraft.net/en-us/article/fantastic-furniture).

Spruce, plants and lanterns are useful companions to copper and masonry in *Cozy Chambers*. For our station this means warmth at the scale of benches, counters and exhibits, with a limited number of focal groups. A Minecraft article also documents a flowerpot above a decorated pot as a large planter. The original cookbook used a small stone planter; the runtime catalog now makes registered pot block types discoverable, while custom pot decoration and stored-item data remain outside the ordinary state editor. [Cozy Chambers](https://www.minecraft.net/en-us/article/cozy-chambers), [Decorated Pot](https://www.minecraft.net/en-us/article/decorated-pot).

### Decorate the transition between architecture and landscape

The official presentation of BlueNerd's landscaping work connects paths, banks, soil and vegetation. Zaypixel's path examples show how material families and nearby objects communicate different settings. Our application is a clean, formal station axis that gradually gives way to local rock, soil and planted pockets farther out. Curve a route when its destination or terrain calls for it. Do not force a kink every seven blocks: that number belongs to one organic-building tutorial, not the engine or every architectural style. [Landscaping and Terraforming](https://www.minecraft.net/en-us/article/tutorial--tips-for-landscaping-and-terraforming), [Five simple path designs](https://www.minecraft.net/en-us/article/five-simple-path-designs).

Kelpie the Fox's outdoor groups provide useful roles for benches, small structures and hanging lights. The article identifies **Mizuno's 16 Craft** in its reference imagery. Borrow composition and purpose, then judge our result in the actual client textures; matching block names alone cannot reproduce a resource-pack image. [Cottagecore Decor](https://www.minecraft.net/en-us/article/tutorial--cottagecore-decor).

### Lighting requires its own review

Regular lanterns are a useful recurring fixture, but a fixture count does not establish room legibility. Look at the spaces between lights, stair landings, sign faces and exhibit fronts. We already used real station photographs to find dark interiors and refine concealed lighting; see the [completed station record](SHACRAFT-STATION.md). [Taking Inventory: Lantern](https://www.minecraft.net/en-us/article/taking-inventory--lantern).

**Tinted glass is not stained glass:** the Java release notes describe tinted glass as blocking light. Do not use it as a substitute for a transparent lighting lens. The same release notes document waxed copper as preventing oxidation. These facts explain material choices; exact accepted states still come from our current server. [Java Caves & Cliffs Part I](https://www.minecraft.net/en-us/article/caves---cliffs--part-i-out-today-java).

## Shacraft palette and composition

The following assignments are our design direction based on the existing arrival garden and station, rather than claims made by the sources:

- **Large cream masses:** `smooth_sandstone`, with `cut_sandstone` for purposeful masonry bands.
- **Clean prominent edges:** `smooth_quartz` and `quartz_pillar`; use supported sandstone stairs/slabs when a partial shape is needed.
- **Roofs and identity:** the `waxed_oxidized_cut_copper` family. Keep broad roof planes visible.
- **Human-scale warmth:** spruce for benches, counters, ceilings and small structural posts.
- **Selective emphasis:** gold at a major identity or control point, with green backing. Repeated small gold accents must not compete with the main sign.
- **Grounded base:** stone bricks, andesite and restrained moss near actual soil or damp recesses.
- **Planting:** a dominant evergreen mass and small pink/white flower groups, continuing zone 01's established vocabulary.
- **SMASH:** preserve the station frame; use a contained island exhibit and restrained warm accent to distinguish this floor.

Place more detail at an entrance, destination or stopping point. Leave broader quiet surfaces and uninterrupted paving between those locations. This is a distribution choice, not a ban on ornament.

## Recipe index

Each cookbook entry includes dimensions, palette, assembly order, clearance, controlled variants and failure checks:

- Facade: `arched-window-bay`, `cornice-bracket`.
- Roof: `closed-dormer`.
- Interior: `waiting-pocket`, `information-counter`, `smash-exhibit`.
- Routes: `avenue-edge`, `retaining-stair`.
- Lighting: `copper-lantern`, `concealed-light-lens`.
- Planting and landscape: `layered-planter`, `shore-pocket`.
- Small props and surfaces: `luggage-bench`, `masonry-weathering`.

## Current capability boundary

The saved Stage 07 `project_context` lists **100 material IDs**. All base recipe material lists were checked against that historical snapshot. The structured recipes retain that dated capability basis so earlier designs remain reproducible; it is no longer the building allowlist. The runtime implementation in [`BuildingWorld.java`](../paper-plugin/src/main/java/io/github/minecraftbuilder/paper/BuildingWorld.java) now accepts all registered vanilla block types and their valid states. Read the live catalog summary, then discover only the materials needed for the next detail through `material_search` and `material_describe`. [Material workflow](MATERIALS.md).

The original recipe catalog uses flush colored paving instead of carpet, masonry planters instead of pots, full stained glass instead of panes, and wooden block props instead of item entities. These remain deliberate design variants. Registered carpets, trapdoors, flowerpots, decorated pots, banners, candles, wildflowers, leaf litter and firefly bushes can now be selected through the runtime catalog. Block-type availability does not add arbitrary banner patterns, pot decorations, sign text, inventories or text-display creation; the station's existing labels use a separate project-specific plugin. Item-only materials are searchable but cannot be placed by a block recipe.

Java 1.21.5 introduced useful plant density/orientation options; its firefly bush emits only light level 2, so it should be treated as an atmospheric accent rather than primary street illumination. Java 26.2 also adds sulfur and cinnabar material families. Material IDs and exact properties come from the running server's registry, so search before using a version-specific feature. Additional behavior is not a new callable MCP API. [Java 1.21.5 release notes](https://feedback.minecraft.net/hc/en-us/articles/35298208390797-Minecraft-Java-Edition-1-21-5-Spring-to-Life), [Java 26.2 release notes](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-2).

For this runtime, discover the chain ID rather than assuming an older name; the saved station uses `minecraft:iron_chain`. Use `persistent=true` for decorative leaves unless deliberate natural decay is intended, and check distance state on read-back. Flowers need accepted substrates, logs need real support, and stairs/slabs/lanterns need the correct directional and attachment states. Place every half or part of doors, beds and tall plants explicitly. Ordinary building plans can place fluids and waterlogged states, but terrain brushes still reject water in their scan. The existing shore recipe remains a land-side design that preserves water. Fluid flow, random ticks and other later game behavior are not fully reversed by undoing only a plan's direct writes.

## Applying a recipe economically

The Markdown cookbook is for human review; the JSON makes one entry easy to retrieve without reading the entire document. For a local repository agent:

```bash
jq '.recipes[] | {id, category, size}' docs/recipes/decorations.json
jq '.recipes[] | select(.id == "copper-lantern")' docs/recipes/decorations.json
```

Save a placement record with recipe ID, recipe-catalog version and runtime material-catalog version, local origin, rotation, chosen variant, terrain/floor anchor, palette substitutions, variation seed and operation IDs. Use a focused `material_search` page (16 results by default, 32 maximum), then describe only 1–3 selected materials. Reuse their defaults and property domains while the runtime catalog version is unchanged. Inspect the target area and its support/clearance neighborhood, then compile a bounded expected-state patch. Copy each block-entity `snapshot_id` from `region_inspect` into `expected_blocks` to detect data edits without reading inventories or NBT into context. Keep the checked operation receipts and a small set of matching photographs. Large-scale repetition comes after a successful sample.

The shared [MCP/ACP guidance](../bridge/src/building-guidance.ts) includes short material-discovery and decoration summaries. Neither the full recipe catalog nor the material registry is injected into every model turn. The recipe JSON is not a new MCP resource or tool: the in-game ACP agent has no repository filesystem access, so its instructions must not pretend it can retrieve this file. New bridge processes receive the updated summary, and resumed ACP sessions receive changed guidance once through its stored fingerprint. Deployment and validation of the registry expansion are recorded in [MATERIALS.md](MATERIALS.md#validation).

## Acceptance before calling a decoration complete

1. **Fit:** same survey anchors, preserved structure, route width and four-block public headroom where that is the existing Shacraft contract. Four blocks is our design margin, not Minecraft's minimum player height.
2. **Stability:** supports, substrates, leaves, attached pieces and rotated states remain valid after block updates.
3. **Movement:** inspect approaches, corners, stairs and ceilings. A decorative fence or hedge does not replace the checked enclosure. Keep unfinished interiors inaccessible.
4. **Visuals:** matched overview, approach and player-height views; day/night where lighting matters. Check sign visibility, density, material contrast and dark exhibit faces in the actual client.
5. **Evidence:** distinguish proposed design, server-applied blocks, measured geometry and visually inspected results. Record an unavailable camera honestly.
6. **Preservation:** keep the before state, checked edits and useful photographs. A later manual edit is a conflict to resolve, not an invitation to overwrite it.

The 14 catalog entries have been reviewed as design specifications and checked for material-name availability. They have **not** been instantiated or visually approved as a new set of in-world samples.
