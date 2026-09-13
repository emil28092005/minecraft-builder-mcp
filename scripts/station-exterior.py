#!/usr/bin/env python3
"""Deterministic, detached exterior for the approved two-floor Shacraft station.

The caller supplies the exact station foundation cells and combines this shell with
the interior before taking expected-state snapshots. This module never reads or
writes a Minecraft world. Coordinates and block states are explicit and stable.
"""

from collections import Counter, defaultdict
from math import ceil, hypot


AIR = "minecraft:air"
STONE = "minecraft:stone_bricks"
DARK = "minecraft:polished_deepslate"
CREAM = "minecraft:smooth_sandstone"
ASHLAR = "minecraft:cut_sandstone"
PALE = "minecraft:smooth_quartz"
PILLAR = "minecraft:quartz_pillar[axis=y]"
GREEN = "minecraft:waxed_oxidized_cut_copper"
DEEP_GREEN = "minecraft:green_concrete"
GOLD = "minecraft:gold_block"
WOOD = "minecraft:spruce_planks"
GLASS = "minecraft:brown_stained_glass"
CLEAR_GLASS = "minecraft:glass"
LAMP = "minecraft:lantern[hanging=true,waterlogged=false]"
CHAIN = "minecraft:iron_chain[axis=y,waterlogged=false]"
GLOW = "minecraft:glowstone"
CARDINALS = ((0, -1, "north"), (1, 0, "east"), (0, 1, "south"), (-1, 0, "west"))


def _dilate(cells, radius):
    return {(x + dx, z + dz) for x, z in cells
            for dx in range(-radius, radius + 1) for dz in range(-radius, radius + 1)}


def _erode(cells, radius):
    return {(x, z) for x, z in cells if all((x + dx, z + dz) in cells
            for dx in range(-radius, radius + 1) for dz in range(-radius, radius + 1))}


def _runs(values):
    result = []
    for value in sorted(values):
        if result and value == result[-1][-1] + 1:
            result[-1].append(value)
        else:
            result.append([value])
    return result


def _line(x0, y0, x1, y1):
    """Inclusive integer line for legible clock hands and roof trim."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = 1 if x0 < x1 else -1, 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        yield x0, y0
        if (x0, y0) == (x1, y1):
            return
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


def compile_exterior(footprint: set[tuple[int, int]], layout: dict):
    """Return (block states, ownership groups, metadata), with no external effects.

    Structural floors are exactly the supplied footprint. Interior ornament may
    replace their finish, but must retain the two complete separating decks.
    All exterior windows are full glass blocks, including their inner wall layer.
    Only the south entrance removes wall blocks below the sealed roof space.
    """
    footprint = {(int(x), int(z)) for x, z in footprint}
    if not footprint:
        raise ValueError("Station foundation must not be empty")
    if any(not (-74 <= x <= 40 and -145 <= z <= -83) for x, z in footprint):
        raise ValueError("Foundation exceeds the approved station envelope")
    if layout.get("perimeter_wall_thickness", 2) != 2:
        raise ValueError("The approved shell requires two-block perimeter walls")
    inner = _erode(footprint, 2)
    walls = footprint - inner
    boundary = footprint - _erode(footprint, 1)
    shadow = _dilate(footprint, 2)
    maximum_shadow = _dilate(footprint, 3)
    states, groups = {}, {}

    def put(x, y, z, state, group):
        x, y, z = int(x), int(y), int(z)
        if not (-78 <= x <= 44 and -149 <= z <= -80 and 98 <= y <= 160):
            raise ValueError(f"Exterior escaped approved coordinate bounds: {(x, y, z)}")
        if (x, z) not in maximum_shadow:
            raise ValueError(f"Exterior overhang exceeds three blocks: {(x, y, z)}")
        if y == 98 and (x, z) not in footprint:
            raise ValueError(f"Ground floor escaped foundation: {(x, y, z)}")
        states[x, y, z] = state
        groups[x, y, z] = group

    def box(x0, x1, y0, y1, z0, z1, state, group, mask=None):
        for z in range(z0, z1 + 1):
            for x in range(x0, x1 + 1):
                if mask is not None and (x, z) not in mask:
                    continue
                for y in range(y0, y1 + 1):
                    put(x, y, z, state, group)

    def stair(material, facing, half="bottom"):
        return f"minecraft:{material}[facing={facing},half={half},shape=straight,waterlogged=false]"

    # The upper cabin will be stationary; neither deck contains a lift-shaft hole.
    for x, z in sorted(footprint):
        for y, state, group in ((98, CREAM, "floor.ground"),
                                (111, WOOD, "floor.intermediate.structure"),
                                (112, CREAM, "floor.upper"),
                                (124, WOOD, "ceiling.upper.structure"),
                                (125, CREAM, "ceiling.upper.seal")):
            put(x, y, z, state, group)
    for x, z in sorted(walls):
        for y in range(99, 125):
            state = ASHLAR
            if y == 99:
                state = DARK
            elif y == 100:
                state = STONE
            elif y in (101, 109, 113, 122, 123):
                state = CREAM
            elif y in (110, 111):
                state = STONE
            elif y in (112, 124):
                state = PALE
            put(x, y, z, state, "wall.masonry")

    # Identify straight stretches from the exact contour, including its eastern recess.
    faces = []
    for nx, nz, facing in CARDINALS:
        planes = defaultdict(list)
        for x, z in boundary:
            if (x + nx, z + nz) not in footprint:
                planes[z if nz else x].append(x if nz else z)
        for plane, positions in sorted(planes.items()):
            for run in _runs(positions):
                if len(run) >= 7:
                    faces.append((nx, nz, facing, plane, run[0], run[-1]))

    def face_position(nx, nz, plane, tangent, depth=0):
        # Positive depth is toward the inside; negative depth is a relief projection.
        return (tangent - nx * depth, plane - nz * depth) if nz else (plane - nx * depth, tangent - nz * depth)

    windows, pilasters, facade_lamps = [], [], []
    for nx, nz, facing, plane, lo, hi in faces:
        phase = -6 if nz else -119
        centers = [c for c in range(lo + 3, hi - 2) if (c - phase) % 10 == 0]
        if not centers and hi - lo >= 8:
            centers = [(lo + hi) // 2]
        for center in centers:
            for base, top in ((102, 108), (115, 122)):
                # A five-wide pointed arch, enclosed by cream voussoirs and piers.
                for tangent in range(center - 3, center + 4):
                    delta = abs(tangent - center)
                    for y in range(base - 1, top + 2):
                        cap = top - max(0, delta - 1)
                        opening = delta <= 2 and base <= y <= cap
                        state = GLASS if opening else CREAM
                        if opening and tangent == center and y < top - 1:
                            state = WOOD
                        if opening and y == base + 3:
                            state = WOOD
                        if delta == 3 and y <= top - 1:
                            state = PILLAR
                        for depth in (0, 1):
                            x, z = face_position(nx, nz, plane, tangent, depth)
                            if (x, z) in walls:
                                put(x, y, z, state, "window.frame" if state != GLASS else "window.glass")
                # Bottom sill projects by one block but never opens the shell.
                for tangent in range(center - 3, center + 4):
                    x, z = face_position(nx, nz, plane, tangent, -1)
                    if (x, z) in maximum_shadow:
                        put(x, base - 1, z, CREAM, "window.sill")
                windows.append({"normal": facing, "plane": plane, "center": center,
                                "base_y": base, "apex_y": top, "glass_layers": 2})
        # Vertical bays use quiet, regular dressed-stone pilasters, not material noise.
        pier_centers = sorted({lo, hi, *[c + 5 for c in centers if c + 5 <= hi]})
        for center in pier_centers:
            x, z = face_position(nx, nz, plane, center)
            for depth in (0, 1):
                px, pz = face_position(nx, nz, plane, center, depth)
                if (px, pz) not in walls:
                    continue
                for y in range(101, 124):
                    put(px, y, pz, PILLAR if y not in (110, 111, 112) else PALE, "wall.pilaster")
            pilasters.append([x, z])
            if center not in (lo, hi) and hi - lo >= 15:
                px, pz = face_position(nx, nz, plane, center, -1)
                # Eave-mounted lighting: clear below, and supported immediately above.
                put(px, 124, pz, CREAM, "lamp.bracket")
                put(px, 123, pz, CHAIN, "lamp.chain")
                put(px, 122, pz, LAMP, "lamp.lantern")
                facade_lamps.append([px, 122, pz])

    # Continuous layered cornices connect every projection of the exact footprint.
    first_relief = _dilate(footprint, 1) - inner
    second_relief = shadow - _erode(footprint, 1)
    for x, z in sorted(first_relief):
        put(x, 110, z, CREAM, "cornice.floor.lower")
        put(x, 112, z, PALE, "cornice.floor.upper")
        put(x, 124, z, CREAM, "cornice.eave.lower")
    for x, z in sorted(second_relief):
        put(x, 125, z, CREAM, "cornice.eave.upper")

    # Union of three pitched masses: a broad central hall and two hipped end wings.
    # Every roof column is closed, without making the inaccessible attic solid fill.
    def roof_height(x, z):
        candidates = []
        if -53 <= x <= 18 and -147 <= z <= -95:
            candidates.append(140 - ceil(abs(z + 121) * 14 / 26))
        if -76 <= x <= -50 and -141 <= z <= -96:
            candidates.append(126 + max(0, min(13 - abs(x + 63), z + 141, -96 - z)))
        if 14 <= x <= 42 and -141 <= z <= -96:
            candidates.append(126 + max(0, min(14 - abs(x - 28), z + 141, -96 - z)))
        if -27 <= x <= 15 and -100 <= z <= -81:
            candidates.append(126 + max(0, min(10 - abs(z + 91), x + 27, 15 - x)))
        return max([126, *candidates])

    roof_heights = {p: min(140, roof_height(*p)) for p in shadow}
    shadow_boundary = shadow - _erode(shadow, 1)
    for x, z in sorted(shadow):
        top = roof_heights[x, z]
        # Close all verge/gable faces down to the continuous eave line.
        if (x, z) in shadow_boundary:
            for y in range(126, top):
                put(x, y, z, ASHLAR if y < top - 1 else GREEN, "roof.gable")
        put(x, top - 1, z, GREEN, "roof.underlay")
        uphill = [(roof_heights.get((x + dx, z + dz), top - 1), facing)
                  for dx, dz, facing in CARDINALS]
        high, facing = max(uphill, key=lambda item: item[0])
        state = stair("waxed_oxidized_cut_copper_stairs", facing) if high > top else GREEN
        if (x + 6) % 12 == 0 and top < 139:
            state = GREEN
        put(x, top, z, state, "roof.copper")
        if top == 140:
            put(x, 140, z, GREEN, "roof.ridge")

    # Four pavilion lantern roofs lend a clear rhythm to the ends of the facade.
    pavilions = [(-66, -131, 7), (-66, -106, 7), (32, -131, 7), (28, -106, 6)]
    for cx, cz, radius in pavilions:
        pavilion = {(x, z) for x in range(cx - radius, cx + radius + 1)
                    for z in range(cz - radius, cz + radius + 1) if (x, z) in shadow}
        for x, z in sorted(pavilion):
            ring = max(abs(x - cx), abs(z - cz))
            top = 137 - ring
            # The cap only raises the parent roof; it never cuts an accidental opening.
            if top <= roof_heights[x, z]:
                continue
            for y in range(roof_heights[x, z], top):
                put(x, y, z, GREEN if y >= top - 1 else CREAM, "pavilion.roof.support")
            facing = "east" if x < cx else "west" if x > cx else "south" if z < cz else "north"
            put(x, top, z, stair("waxed_oxidized_cut_copper_stairs", facing) if ring else GREEN, "pavilion.roof.copper")
        for y, state in ((138, GREEN), (139, GOLD), (140, CHAIN)):
            put(cx, y, cz, state, "pavilion.finial")

    # Shacraft-green hanging stone panels, with a small gold S motif on the end bays.
    # These are block reliefs, not entities or inventory-backed banner blocks.
    shield_centers = [(-65, -97, 1), (28, -97, 1), (-65, -140, -1), (31, -140, -1)]
    glyph = ("111", "100", "111", "001", "111")
    for cx, plane, normal in shield_centers:
        for y in range(110, 123):
            half = 2 if y >= 112 else y - 109
            for dx in range(-half, half + 1):
                put(cx + dx, y, plane, GOLD if abs(dx) == half else DEEP_GREEN, "ornament.green.shield")
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    put(cx + col - 1, 120 - row, plane + normal, GOLD, "ornament.gold.s")
        for dx in range(-3, 4):
            put(cx + dx, 123, plane, CREAM, "ornament.shield.cap")

    # The projecting entrance arch remains seven blocks clear at useful head height.
    axis = int(layout.get("entrance_axis_x", -6))
    entrance = layout.get("entrance_opening_x", [-9, -3])
    for x in range(axis - 6, axis + 7):
        dx = abs(x - axis)
        for z in (-85, -84):
            if (x, z) not in footprint:
                continue
            for y in range(99, 111):
                if dx in (4, 5):
                    put(x, y, z, PILLAR if y > 100 else DARK, "entrance.pier")
                elif y >= 109 - min(dx, 4):
                    put(x, y, z, CREAM, "entrance.arch")
    entrance_air = []
    for x in range(int(entrance[0]), int(entrance[1]) + 1):
        top = 109 - abs(x - axis)
        for z in (-85, -84, -83):
            for y in range(99, top + 1):
                put(x, y, z, AIR, "entrance.clear")
                entrance_air.append([x, y, z])
    for px in (axis - 6, axis + 6):
        put(px, 108, -83, CREAM, "entrance.lamp.bracket")
        put(px, 108, -82, CREAM, "entrance.lamp.bracket")
        put(px, 107, -82, CHAIN, "entrance.lamp.chain")
        put(px, 106, -82, LAMP, "entrance.lamp")
    # A high, glazed lancet over the portal echoes the long window below the reference clock.
    for x in range(axis - 3, axis + 4):
        for y in range(115, 124):
            cap = 123 - abs(x - axis)
            state = GLASS if y <= cap else CREAM
            if x == axis or y == 118:
                state = WOOD if y <= cap else CREAM
            for z in (-85, -84):
                if (x, z) in walls:
                    put(x, y, z, state, "entrance.upper.lancet")

    # Sealed clock tower: solid underside already exists at Y124/125, no future-floor doorway.
    tx0, tx1, tz0, tz1 = axis - 9, axis + 9, -102, -84
    # Carry the tower's front corner piers down through both public-storey facades.
    for x in (tx0, tx0 + 1, tx1 - 1, tx1):
        for z in (tz1, tz1 - 1):
            for y in range(101, 125):
                put(x, y, z, PALE if y in (110, 111, 112, 124) else PILLAR, "tower.facade.pier")
    tower = {(x, z) for x in range(tx0, tx1 + 1) for z in range(tz0, tz1 + 1)}
    tower_inner = _erode(tower, 2)
    tower_wall = tower - tower_inner
    for x, z in sorted(tower):
        put(x, 126, z, CREAM, "tower.base.seal")
    for x, z in sorted(tower_wall):
        corner = (x <= tx0 + 1 or x >= tx1 - 1) and (z <= tz0 + 1 or z >= tz1 - 1)
        for y in range(127, 148):
            state = PILLAR if corner else ASHLAR
            if y in (128, 130, 147):
                state = PALE
            put(x, y, z, state, "tower.masonry")
    # Clock disks have a stone backing, recessed cream face and four gold bezels.
    clock_faces = [("south", axis, -82), ("north", axis, -104),
                   ("west", -16, -93), ("east", 4, -93)]
    hour_marks = {(0, 6), (0, -6), (6, 0), (-6, 0), (4, 4), (-4, 4), (4, -4), (-4, -4)}
    hands = set(_line(0, 0, -3, 4)) | set(_line(0, 0, 3, 3))
    for facing, center, plane in clock_faces:
        nx, nz = {"south": (0, 1), "north": (0, -1), "west": (-1, 0), "east": (1, 0)}[facing]
        for u in range(-8, 9):
            for v in range(-8, 9):
                radius = hypot(u, v)
                if radius > 8.3:
                    continue
                x, z = (center + u, plane) if nz else (center, plane + u)
                # All ornament is supported by one continuous backing layer.
                put(x - nx, 139 + v, z - nz, CREAM, "clock.backing")
                state = CREAM
                if radius > 7.4:
                    state = PALE
                elif radius > 6.5:
                    state = GOLD
                elif (u, v) in hour_marks:
                    state = DEEP_GREEN
                elif (u, v) in hands:
                    state = DARK
                if (u, v) == (0, 0):
                    state = GOLD
                put(x, 139 + v, z, state, "clock.face." + facing)
    # Broad cream cap, steep patinated copper crown and a restrained gold finial.
    tower_cap = _dilate(tower, 1)
    for x, z in sorted(tower_cap):
        put(x, 148, z, PALE, "tower.cornice")
    for x, z in sorted(tower):
        radius = max(abs(x - axis), abs(z + 93))
        top = 149 + max(0, 7 - radius)
        for y in range(149, top):
            put(x, y, z, GREEN, "tower.roof.underlay")
        facing = "east" if x < axis else "west" if x > axis else "south" if z < -93 else "north"
        put(x, top, z, stair("waxed_oxidized_cut_copper_stairs", facing) if radius else GREEN, "tower.roof.copper")
    for x, z in ((tx0, tz0), (tx1, tz0), (tx0, tz1), (tx1, tz1)):
        put(x, 150, z, GREEN, "tower.corner.finial")
        put(x, 151, z, GOLD, "tower.corner.finial")
        put(x, 152, z, CHAIN, "tower.corner.finial")
    for y, state in ((157, GOLD), (158, CHAIN)):
        put(axis, y, -93, state, "tower.central.finial")
    for x, z in ((tx0 - 1, tz1), (tx1 + 1, tz1), (tx0 - 1, tz0), (tx1 + 1, tz0)):
        put(x, 148, z, PALE, "tower.lamp.bracket")
        put(x, 147, z, CHAIN, "tower.lamp.chain")
        put(x, 146, z, LAMP, "tower.lamp")

    # Deterministic checks describe the shell; the root performs full merged navigation QA.
    entrance_columns = {(x, z) for x in range(entrance[0], entrance[1] + 1) for z in (-85, -84, -83)}
    assert all(states.get((x, y, z)) == AIR for x, z in entrance_columns for y in range(99, 103))
    assert all((x, z) in footprint for (x, y, z) in states if y == 98)
    assert all(states[x, 112, z] != AIR and states[x, 125, z] != AIR for x, z in footprint)
    assert {p for p, state in states.items() if state == AIR} == {tuple(p) for p in entrance_air}
    solid = {p for p, state in states.items() if state != AIR}
    remaining = set(solid)
    queue = [remaining.pop()]
    while queue:
        x, y, z = queue.pop()
        for p in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                  (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
            if p in remaining:
                remaining.remove(p)
                queue.append(p)
    assert not remaining, "Exterior contains detached floating ornament"
    metadata = {
        "generator": "station-exterior-v1", "world_writes": 0,
        "foundation_columns": len(footprint), "two_block_wall_columns": len(walls),
        "bounds": {"min": [min(p[i] for p in states) for i in range(3)],
                   "max": [max(p[i] for p in states) for i in range(3)]},
        "floor_block_y": [98, 112], "walk_y": [99, 113],
        "solid_intermediate_deck": [111, 112], "sealed_roof_ceiling": [124, 125],
        "main_roof_eaves_y": 126, "main_roof_ridge_y": 140, "clocktower_peak_y": 158,
        "entrance_clear_x": list(entrance), "entrance_clear_z": [-85, -84, -83],
        "entrance_minimum_clear_height": 8, "windows": windows, "pilasters": pilasters,
        "facade_lamps": facade_lamps, "pavilions": [list(p) for p in pavilions],
        "clock_faces": [{"facing": f, "center_or_x": c, "plane_or_z": p,
                          "center_y": 139, "radius": 8} for f, c, p in clock_faces],
        "materials": sorted({state.split("[")[0] for state in states.values()}),
        "states_by_group": dict(sorted(Counter(groups.values()).items())),
        "blocks": len(states), "entrance_air_blocks": len(entrance_air),
        "checks": {"ground_floor_on_exact_footprint": True, "two_solid_separating_decks": True,
                   "only_main_entrance_is_open": True, "roof_and_tower_have_no_doorway": True,
                   "maximum_overhang_blocks": 3, "all_windows_full_block_glass": True,
                   "all_solid_states_share_one_cardinally_connected_component": True},
    }
    return states, groups, metadata
