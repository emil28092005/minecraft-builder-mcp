# Shacraft clock station: vestibule and SMASH

Design v1, 13 September 2026. **Proposal only; no world edits were made.**

This design fits the saved, existing zone 02 foundation in `shacraft_lobby_v2`. The current station has a deck and setting-out bands, not a completed above-ground building. Its fixed overall envelope is 115 by 63 blocks; the occupied footprint is irregular. The final stage 02 geometry contains 5,764 station columns, including the east-edge recess. The earlier ideal outline contained 5,823 columns and is not the exact placement authority.

## Drawings

- [Coordinate plans and section](00-coordinate-plan.png) · [printable PDF](00-coordinate-plan.pdf)
- [First-floor vestibule](01-vestibule.png)
- [Second-floor SMASH hall](02-smash-floor.png)
- [Clock station cutaway](03-cutaway.png)
- [Exact coordinate specification and checks](layout.json)
- [Full image prompts](prompts.json)

The three perspective images were generated with the **built-in image_gen tool**. They establish architectural character and atmosphere. The coordinate plan and JSON govern dimensions and placement: generated ornament, block counts, lettering, map thumbnails and roof shapes are illustrative. In particular, the invented slogans in the SMASH image are not approved Shacraft copy. The technical plan was drawn deterministically with Pillow from the saved foundation cells.

## Spatial arrangement

The south entrance keeps the existing approach axis at X=-6. The exterior staircase is 21 blocks clear; the entrance and principal approach aisle are seven blocks clear. A green copper and warm brass-colored lift surround is visible from the doorway, with a small directory beside it. Benches and planting occupy the side galleries. Column positions align vertically; pale stone arches and spruce ceiling panels continue the original clock-station reference.

The first-floor paving remains at block Y98, with feet at Y99. The two-block intermediate deck occupies Y111 and Y112; SMASH is walked at Y113. This gives 12 blocks of structural clear height below the intermediate deck and 11 above it, before the next ceiling begins at Y124. Hanging lamps and decorative beams may reduce local headroom; keep at least four clear blocks over public circulation. The proposed main roof has eaves at Y126 and ridge at Y140; the clock-tower peak is Y158. These are proposed heights, not measurements of an existing shell.

The lift housing occupies X=-10..-2, Z=-124..-116 on both floors. Two-block walls leave a 5 by 5 clear cabin, with a five-block opening facing south. The suggested eventual behavior is a personal floor selection and transition between enclosed stationary cabins, preventing one player's selection from moving everyone else. Lift controls, animation and world transfers are not implemented by this design. Future floors can reuse the shaft alignment, but their height, roof integration and circulation need a further design pass.

## SMASH floor

The user confirmed the Shotbow-style mode: accumulating damage increases knockback, players double-jump and attempt to knock opponents off the arena. See [Shotbow's getting-started guide](https://wiki.shotbow.net/SMASH_Getting_Started).

Six seven-by-five selection alcoves line the north wall, with three blocks between adjacent alcoves and a seven-block clear aisle in front. Each contains an arena illustration and an ordinary sign at reachable height. Slots 01–06 are **unassigned placeholders**: arena names, destinations and live status are not invented here. Later, each sign can connect to its arena world or queue.

A 19 by 15 decorative island diorama occupies the western part of the main hall. Its small islands and static figures explain knockback visually. The display sits above a solid floor, behind a stone-and-glass enclosure. It is scenery, not a playable arena or a hole through the building. The west gallery explains damage, knockback and double jumping; the east gallery provides waiting space. Burnt-orange and dark-red accents distinguish SMASH while retaining Shacraft's green copper, cream stone, spruce and warm lighting.

## Evidence and limits

`draw-plan.py` checks all specified columns, benches, the lift housing, display and selection bays against a two-block setback inside the saved foundation. It checks for furnishing overlaps and keeps the seven-block entrance aisle and bay-front aisle clear. These are design checks, not a collision test of a constructed building.

Sources are `.runtime/foundations-stage02/foundations-final.geometry.json` and the saved `zone01-complete.json` surface export; its capture time is recorded in `layout.json`. That export is not an atomic or fresh live scan. It shows only deck, parapet and lamp heights in this footprint. Before building, inspect current voxels again, preserve manual changes, save a backup and implement with conflict-aware batches. Zone 01's existing containment remains in place until a separate, checked opening of the station route.

For a design rebuild in the main repository, run `python3 docs/references/zone02-interior-v1/draw-plan.py` with Pillow available and the source geometry/export retained. Roof overhangs, arches, window bays and decorative block palettes remain to be detailed during the building pass within the selected region. No additional minigame rooms or playable arenas are included in this stage.
