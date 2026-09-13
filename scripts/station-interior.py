#!/usr/bin/env python3
"""Compile the two furnished Shacraft station floors without world I/O.

The caller owns the exterior, authoritative survey and expected-state writes.
This module owns only the two-block-eroded footprint at block Y 98..123.
All six SMASH panels are decorative, unassigned slots. Functional signs, text
displays and the individual lift transition are deliberately metadata only.
"""

from collections import Counter, deque


AIR = "minecraft:air"
CREAM = "minecraft:smooth_sandstone"
PALE = "minecraft:smooth_quartz"
CUT = "minecraft:cut_sandstone"
GREEN = "minecraft:waxed_oxidized_cut_copper"
GOLD = "minecraft:gold_block"
WOOD = "minecraft:spruce_planks"
DARK = "minecraft:dark_oak_planks"
CHAIN = "minecraft:iron_chain[axis=y,waterlogged=false]"
LANTERN = "minecraft:lantern[hanging=true,waterlogged=false]"
LEAF = "minecraft:spruce_leaves[distance=7,persistent=true,waterlogged=false]"
LOG = "minecraft:spruce_log[axis=y]"


def _slab(material, top=False):
    return f"minecraft:{material}[type={'top' if top else 'bottom'},waterlogged=false]"


def _stair(material, facing, top=False):
    return (f"minecraft:{material}[facing={facing},half={'top' if top else 'bottom'},"
            "shape=straight,waterlogged=false]")


def _rect(box):
    a, b, c, d = map(int, box)
    return {(x, z) for x in range(a, b + 1) for z in range(c, d + 1)}


def _pose(x, y, z, text, facing="south", scale=0.7, **extra):
    return {"position": {"x": x, "y": y, "z": z}, "text": text,
            "facing": facing, "scale": scale, **extra}


class _Interior:
    def __init__(self, footprint, layout):
        self.footprint = {(int(x), int(z)) for x, z in footprint}
        self.inside = {(x, z) for x, z in self.footprint
                       if all((x + dx, z + dz) in self.footprint
                              for dx in range(-2, 3) for dz in range(-2, 3))}
        if not self.inside:
            raise ValueError("The station needs an interior after its two-block setback")
        self.layout = layout
        self.states = {}
        self.groups = {}
        self.features = []
        self.texts = []
        self.targets = {99: [], 113: []}
        self.selections = []
        self.lift = {}
        self.floor_walk = {}

    def put(self, x, y, z, state, group):
        p = (int(x), int(y), int(z))
        if (p[0], p[2]) not in self.inside or not 98 <= p[1] <= 123:
            raise ValueError(f"Interior write outside the owned volume: {p} ({group})")
        self.states[p] = state
        self.groups[p] = group

    def box(self, bounds, lo, hi, state, group, clipped=False):
        for x, z in sorted(_rect(bounds)):
            if clipped and (x, z) not in self.inside:
                continue
            for y in range(lo, hi + 1):
                self.put(x, y, z, state, group)

    def target(self, feet, x, z, name):
        self.targets[feet].append({"name": name, "x": x, "y": feet, "z": z})

    def record(self, kind, bounds, feet, **extra):
        self.features.append({"kind": kind, "bounds_xz": list(bounds),
                              "walk_y": feet, **extra})

    def shell(self):
        for x, z in sorted(self.inside):
            for y in range(98, 124):
                if y in (98, 112):
                    state, group = CREAM, "interior:continuous-floor"
                elif y == 111:
                    state, group = "minecraft:stone_bricks", "interior:solid-intermediate-deck"
                else:
                    state, group = AIR, "interior:owned-room-air"
                self.put(x, y, z, state, group)

    def floors(self, feet):
        floor = feet - 1
        group = f"interior:{feet}:floor-inlay"
        # Large calm limestone panels, outlined by the architectural column grid.
        for x, z in sorted(self.inside):
            if x in (-51, -46, -21, -16, 15, 20) or z in (-129, -124, -106, -101):
                self.put(x, floor, z, PALE, group)
            if x in (-50, -17, 19) and -135 <= z <= -93:
                self.put(x, floor, z, CUT, group)
        for x in (-11, -10, -2, -1):
            for z in range(-115, -84):
                if (x, z) in self.inside:
                    self.put(x, floor, z, GREEN if x in (-10, -2) else PALE, group)
        for z in (-111, -103, -95, -87):
            for x in (-10, -2):
                if (x, z) in self.inside:
                    self.put(x, floor, z, GOLD, group)
        centres = [(-59, -117), (25, -117), (-34, -103), (5, -99)]
        if feet == 99:
            centres += [(-33, -117), (-31, -135), (5, -135)]
        for cx, cz in centres:
            for dx in range(-5, 6):
                for dz in range(-5, 6):
                    if (cx + dx, cz + dz) not in self.inside:
                        continue
                    r = abs(dx) + abs(dz)
                    if r == 5:
                        state = GREEN
                    elif r == 4:
                        state = PALE
                    elif r <= 2 and (dx == 0 or dz == 0):
                        state = GOLD if r == 0 else CUT
                    else:
                        continue
                    self.put(cx + dx, floor, cz + dz, state, group)
        if feet == 113:
            # A terracotta runner belongs to SMASH, while the centre axis stays pale.
            for x, z in sorted(_rect([-46, 11, -134, -130])):
                self.put(x, floor, z, "minecraft:orange_terracotta", group)
            for x in range(-46, 12):
                for z in (-135, -129):
                    self.put(x, floor, z, PALE if x % 10 else GOLD, group)
            for x, z in sorted(_rect([22, 29, -124, -112])):
                edge = x in (22, 29) or z in (-124, -112)
                self.put(x, floor, z, GREEN if edge else "minecraft:orange_terracotta", group)

    def arcade(self, feet, ceiling):
        group = f"interior:{feet}:arcade"
        panel_y = ceiling - 1
        # A solid coffer ceiling closes the upper floor below the inaccessible attic.
        for x, z in sorted(self.inside):
            self.put(x, panel_y, z, WOOD, group)
            if z in (-139, -128, -125, -105, -102, -91) or x in (-50, -47, -20, -17, 16, 19):
                self.put(x, panel_y, z, DARK, group)
            if z in (-128, -125, -105, -102):
                self.put(x, panel_y - 1, z, CREAM, group)
        for bounds in self.layout["aligned_columns"]:
            a, b, c, d = bounds
            self.box(bounds, feet, feet, CUT, group)
            self.box(bounds, feet + 1, feet + 1, PALE, group)
            self.box(bounds, feet + 2, ceiling - 4,
                     "minecraft:quartz_pillar[axis=y]", group)
            self.box(bounds, ceiling - 3, ceiling - 1, CREAM, group)
            self.box([a - 1, b + 1, c - 1, d + 1], ceiling - 3, ceiling - 3,
                     _slab("smooth_sandstone_slab", top=True), group, clipped=True)
            self.box([a - 1, b + 1, c - 1, d + 1], ceiling - 2, ceiling - 2,
                     CREAM, group, clipped=True)
            self.record("aligned-column", bounds, feet)
        # High corbels make the two column rows read as a shallow cream arcade.
        for bounds in self.layout["aligned_columns"]:
            a, b, c, d = bounds
            for x, facing in ((a - 2, "east"), (b + 2, "west")):
                for z in (c, d):
                    if (x, z) in self.inside:
                        self.put(x, ceiling - 3, z,
                                 _stair("smooth_sandstone_stairs", facing, top=True), group)

    def chandelier(self, x, z, feet, ceiling):
        group = f"interior:{feet}:chandelier"
        collar = ceiling - 4
        for y in range(collar + 1, ceiling):
            self.put(x, y, z, CHAIN, group)
        self.put(x, collar, z, GOLD, group)
        for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self.put(x + dx, collar, z + dz, GREEN, group)
            self.put(x + dx, collar - 1, z + dz, LANTERN, group)
        self.record("four-lantern-chandelier", [x - 1, x + 1, z - 1, z + 1],
                    feet, lowest_block_y=collar - 1)

    def bench(self, bounds, feet, facing="south", name="bench"):
        a, b, c, d = bounds
        if b - a < 3 or d - c != 1:
            raise ValueError("Station benches use a long, two-block-deep rectangle")
        group = f"interior:{feet}:bench"
        back_z, seat_z = (c, d) if facing == "south" else (d, c)
        stair_facing = "north" if facing == "south" else "south"
        for x in range(a, b + 1):
            if x in (a, b):
                for z in (c, d):
                    self.put(x, feet, z, CUT, group)
                    self.put(x, feet + 1, z, _slab("smooth_sandstone_slab"), group)
            else:
                self.put(x, feet, seat_z, _stair("spruce_stairs", stair_facing), group)
                self.put(x, feet, back_z, WOOD, group)
                self.put(x, feet + 1, back_z, _slab("spruce_slab"), group)
        front = d + 1 if facing == "south" else c - 1
        for x in range(a + 1, b):
            self.target(feet, x, front, f"{name}-access-{x}")
        self.record("spruce-bench", bounds, feet, facing=facing)

    def planter(self, x, z, feet, name="topiary"):
        group = f"interior:{feet}:planter"
        bounds = [x - 1, x + 1, z - 1, z + 1]
        self.box(bounds, feet, feet, CUT, group)
        self.put(x, feet, z, "minecraft:dirt", group)
        self.put(x, feet + 1, z, LOG, group)
        self.put(x, feet + 2, z, LOG, group)
        for dx, dz in ((-1, 0), (0, -1), (0, 0), (0, 1), (1, 0)):
            self.put(x + dx, feet + 3, z + dz, LEAF, group)
        self.put(x, feet + 4, z, LEAF, group)
        self.record(name, bounds, feet)

    def lift_cabin(self, feet, ceiling):
        group = f"interior:{feet}:lift"
        housing = self.layout["lift"]["housing"]
        cabin = self.layout["lift"]["clear_cabin"]
        inner = _rect(cabin)
        a, b, c, d = housing
        for x, z in sorted(_rect(housing)):
            if (x, z) in inner:
                self.put(x, feet - 1, z, "minecraft:polished_andesite", group)
                continue
            for y in range(feet, ceiling):
                state = GREEN
                if x in (a, b) and z in (c, d):
                    state = CUT if y in (feet, feet + 5) else CREAM
                if y == feet + 5 and z == d:
                    state = GOLD
                self.put(x, y, z, state, group)
        # The unused volume above each cabin is solid, never an open shaft.
        self.box(cabin, feet + 7, ceiling - 1, WOOD, group)
        self.box(cabin, feet, feet + 6, AIR, group)
        self.box([-8, -4, -117, -116], feet, feet + 4, AIR, group)
        self.box([-8, -4, -117, -116], feet + 5, feet + 5, GOLD, group)
        for x in (-8, -4):
            for z in range(-122, -117):
                self.put(x, feet - 1, z, GREEN, group)
        self.put(-6, feet + 6, -120, CHAIN, group)
        self.put(-6, feet + 5, -120, LANTERN, group)
        selector = (-6, feet + 2, -123)
        self.put(*selector, GOLD, group)
        number = 1 if feet == 99 else 2
        self.lift[str(number)] = {
            "housing_bounds_xz": housing, "clear_cabin_bounds_xz": cabin,
            "walk_y": feet, "door_bounds_xz": [-8, -4, -117, -116],
            "door_clear_height": 5, "selector_block": list(selector),
            "destination": {"x": -5.5, "y": 113 if feet == 99 else 99,
                            "z": -119.5, "yaw": 0, "pitch": 0},
            "landing_block": [-6, feet, -120], "floor_is_solid": True,
        }
        self.texts.append(_pose(-5.5, feet + 6.2, -114.93,
                               "1  ВЕСТИБЮЛЬ" if number == 1 else "2  SMASH",
                               scale=0.9, id=f"lift-{number}-front"))
        self.texts.append(_pose(-5.5, feet + 3.3, -121.92,
                               "Вверх · SMASH" if number == 1 else "Вниз · Вестибюль",
                               scale=0.45, id=f"lift-{number}-selector"))
        self.target(feet, -6, -120, f"lift-{number}-landing")
        self.target(feet, -6, -114, f"lift-{number}-approach")
        self.record("enclosed-lift-cabin", housing, feet, floor_number=number)

    def gallery_panel(self, x, z, feet, title, subtitle, facing="east"):
        group = f"interior:{feet}:gallery-panel"
        # East-facing panels stand along the western wall, clear of the arcade.
        for dz in range(-2, 3):
            for dy in range(0, 6):
                state = CUT if abs(dz) == 2 or dy in (0, 5) else DARK
                self.put(x, feet + dy, z + dz, state, group)
        for dz in (-2, 2):
            self.put(x, feet + 2, z + dz, GOLD, group)
        self.texts.append(_pose(x + 1.04, feet + 3.9, z + 0.5,
                               title + "\n" + subtitle, facing=facing, scale=0.52,
                               id=f"gallery-{feet}-{x}-{z}"))
        self.target(feet, x + 3, z, title)
        self.record("rules-panel" if feet == 113 else "station-gallery-panel",
                    [x, x, z - 2, z + 2], feet)

    def diorama(self):
        feet = 113
        a, b, c, d = self.layout["smash_display"]
        group = "interior:113:contained-island-diorama"
        self.box([a, b, c, d], feet, feet, "minecraft:black_concrete", group)
        for x, z in sorted(_rect([a, b, c, d])):
            if x in (a, b) or z in (c, d):
                self.put(x, feet, z, CUT, group)
                for y in (feet + 1, feet + 2):
                    self.put(x, y, z, "minecraft:glass", group)
                self.put(x, feet + 3, z, _slab("smooth_sandstone_slab"), group)
        # Miniatures hover above an opaque, intact display base, inside a glass case.
        for ix, (cx, cz, radius) in enumerate(((-38, -115, 2), (-29, -115, 2), (-34, -120, 2))):
            self.put(cx, 114, cz, "minecraft:deepslate[axis=y]", group)
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    dist = abs(dx) + abs(dz)
                    if dist <= 2:
                        self.put(cx + dx, 115, cz + dz, "minecraft:stone", group)
                    if dist <= 3:
                        self.put(cx + dx, 116, cz + dz, "minecraft:moss_block", group)
            self.put(cx, 117, cz, LOG, group)
            self.put(cx, 118, cz, LOG, group)
            for dx, dz in ((-1, 0), (0, -1), (0, 0), (0, 1), (1, 0)):
                self.put(cx + dx, 119, cz + dz, LEAF, group)
            self.put(cx, 120, cz, LEAF, group)
            self.put(cx + (1 if ix != 1 else -1), 117, cz + 1,
                     "minecraft:red_concrete" if ix == 1 else "minecraft:light_blue_concrete", group)
        self.texts.append(_pose((a + b) / 2 + 0.5, 115, d + 1.05,
                               "SMASH  ·  УДЕРЖИСЬ НА ОСТРОВЕ", scale=0.6,
                               id="smash-diorama-caption"))
        self.target(feet, -33, d + 2, "diorama-south-view")
        self.target(feet, a - 2, -117, "diorama-west-view")
        self.target(feet, b + 2, -117, "diorama-east-view")
        self.record("closed-display-only-diorama", [a, b, c, d], feet,
                    enclosed=True, arena=False, floor_intact=True, top_y=120)

    def selection_bays(self):
        feet = 113
        group = "interior:113:smash-selection-bays"
        # Solid infill behind the recessed panels prevents unfinished rear rooms.
        for x, z in sorted(self.inside):
            if -47 <= x <= 13 and z <= -140:
                for y in range(feet, 124):
                    self.put(x, y, z, CREAM, group)
        for index, bounds in enumerate(self.layout["smash_selection_bays"], 1):
            a, b, c, d = bounds
            mid = (a + b) // 2
            for x in range(a, b + 1):
                for y in range(feet, feet + 8):
                    self.put(x, y, c, DARK, group)
            for x in (a, b):
                for z in range(c + 1, d + 1):
                    for y in range(feet, feet + 7):
                        self.put(x, y, z, CUT if y == feet else CREAM, group)
            self.box([a, b, c + 1, d], feet + 7, feet + 7, CREAM, group)
            self.box([a + 1, b - 1, c + 1, c + 1], feet + 1, feet + 6, GOLD, group)
            # Five-wide miniature reliefs are explicitly generic, unassigned previews.
            for dx in range(-2, 3):
                for dy in range(4):
                    material = "light_blue_concrete"
                    summit = 1 + ((dx + index) % 3 == 0)
                    if dy < summit:
                        material = "stone" if dy == 0 else "moss_block"
                    if dy == 3 and dx == (index % 3) - 1:
                        material = "white_concrete"
                    self.put(mid + dx, feet + 2 + dy, c + 2,
                             "minecraft:" + material, group)
            for x in range(mid - 1, mid + 2):
                self.put(x, feet, d, CUT, group)
                self.put(x, feet + 1, d, WOOD, group)
            self.put(mid, feet + 6, c + 2, LANTERN, group)
            self.put(mid, feet + 7, c + 2, GREEN, group)
            sign = [mid, feet + 1, d + 1]
            support = [mid, feet + 1, d]
            self.selections.append({
                "slot": f"{index:02d}", "bounds_xz": bounds,
                "assigned": False, "destination": None,
                "relief_is_decorative": True,
                "sign_block": sign, "sign_support_block": support,
                "sign_facing": "south", "sign_lines": [f"АРЕНА {index:02d}", "Не назначено", "", ""],
                "standing_block": [mid, feet, d + 2],
                "label_pose": _pose(mid + 0.5, feet + 6.6, d + 1.05,
                                    f"{index:02d}", scale=0.55),
            })
            self.target(feet, mid, d + 2, f"arena-{index:02d}-sign")
            self.record("unassigned-arena-selection-bay", bounds, feet, slot=index)
        self.box([-35, 1, -139, -138], 121, 123, DARK, group)
        self.texts.append(_pose(-16.5, 122.2, -136.94, "S M A S H", scale=2.2,
                               id="smash-header"))

    def furniture(self, feet):
        for i, bounds in enumerate(self.layout["wing_benches"]):
            self.bench(bounds, feet, "south", f"wing-bench-{i + 1}")
        for x, z in ((-56, -131), (-56, -106), (21, -131), (21, -106)):
            self.planter(x, z, feet)
        # The north and south galleries are furnished public rooms, without doors
        # suggesting additional unfinished wings or upper-floor circulation.
        for i, (bounds, facing) in enumerate((([-22, -15, -94, -93], "north"),
                                               ([0, 7, -94, -93], "north"))):
            self.bench(bounds, feet, facing, f"south-gallery-bench-{i + 1}")
        for x, z in ((-30, -94), (12, -94)):
            if _rect([x - 1, x + 1, z - 1, z + 1]) <= self.inside:
                self.planter(x, z, feet)
        if feet == 99:
            for i, bounds in enumerate(([-44, -37, -137, -136], [-26, -19, -137, -136],
                                        [1, 8, -137, -136])):
                self.bench(bounds, feet, "south", f"north-gallery-bench-{i + 1}")
            for x in (-31, 11):
                self.planter(x, -137, feet)
            self.gallery_panel(-72, -116, feet, "SHACRAFT", "Площадь прибытия")
            self.texts.append(_pose(-5.5, 108, -114.93,
                                   "SHACRAFT", scale=0.9,
                                   id="vestibule-heading"))
        else:
            for z, title, subtitle in ((-122, "УРОН", "Больше урона — сильнее отбрасывание"),
                                        (-115, "ОТБРАСЫВАНИЕ", "Удержись на острове"),
                                        (-108, "ДВОЙНОЙ ПРЫЖОК", "Вернись на площадку")):
                self.gallery_panel(-72, z, feet, title, subtitle)
            self.texts.append(_pose(26, 118.5, -105.9, "ЗОНА ОЖИДАНИЯ", scale=0.7,
                                   id="smash-waiting-heading"))

    def leaf_distances(self):
        leaves = {p for p, s in self.states.items() if s.startswith("minecraft:spruce_leaves[")}
        distance = {}
        queue = deque()
        for p, s in self.states.items():
            if s.startswith("minecraft:spruce_log["):
                queue.append((p, 0))
        while queue:
            (x, y, z), d = queue.popleft()
            if d >= 6:
                continue
            for p in ((x - 1, y, z), (x + 1, y, z), (x, y - 1, z),
                      (x, y + 1, z), (x, y, z - 1), (x, y, z + 1)):
                if p in leaves and d + 1 < distance.get(p, 7):
                    distance[p] = d + 1
                    queue.append((p, d + 1))
        for p in leaves:
            self.states[p] = (f"minecraft:spruce_leaves[distance={distance.get(p, 7)},"
                              "persistent=true,waterlogged=false]")

    def navigation(self):
        details = {}
        for feet, seed in ((99, (-6, -86)), (113, (-6, -120))):
            clear = {(x, z) for x, z in self.inside
                     if all(self.states[(x, y, z)] == AIR for y in range(feet, feet + 4))}
            if seed not in clear:
                raise ValueError(f"Interior navigation start is obstructed at {feet}: {seed}")
            reached = {seed}
            queue = deque([seed])
            while queue:
                x, z = queue.popleft()
                for p in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
                    if p in clear and p not in reached:
                        reached.add(p)
                        queue.append(p)
            for target in self.targets[feet]:
                if (target["x"], target["z"]) not in reached:
                    raise ValueError(f"Unreachable interior target: {target}")
            # Close genuine inaccessible air pockets; never leave a half-built room.
            sealed = clear - reached
            for x, z in sorted(sealed):
                for y in range(feet, 111 if feet == 99 else 124):
                    self.put(x, y, z, CREAM, f"interior:{feet}:sealed-service-infill")
            reserved = [self.layout["reserved_clear_aisles"]["entry"]]
            if feet == 113:
                reserved.append(self.layout["reserved_clear_aisles"]["bay_front"])
            for bounds in reserved:
                required = _rect(bounds) & self.inside
                blocked = required - reached
                if blocked:
                    raise ValueError(f"Reserved circulation is blocked at Y{feet}: {sorted(blocked)[:5]}")
            self.floor_walk[feet] = [{"x": x, "y": feet, "z": z}
                                     for x, z in sorted(reached)]
            details[str(feet)] = {"walk_columns": len(reached),
                                 "minimum_verified_headroom": 4,
                                 "named_targets": self.targets[feet],
                                 "sealed_inaccessible_columns": len(sealed),
                                 "all_named_targets_reachable": True,
                                 "reserved_aisles_clear": True}
        return details


def compile_interior(footprint, layout):
    """Return canonical voxel states, per-voxel groups, and JSON-safe metadata.

    ``footprint`` contains the actual surveyed foundation's (x, z) columns.
    Geometry is deterministic and absolute, as specified by the approved layout.
    The returned air states are intentional room clearance; callers must apply
    the normal expected-state and protected-volume checks before any live write.
    """
    b = _Interior(footprint, layout)
    floors = [(int(f["walk_y"]), int(f["ceiling_underside_y"])) for f in layout["floors"]]
    if floors != [(99, 111), (113, 124)]:
        raise ValueError("This approved interior is defined only for walk Y99 and Y113")
    b.shell()
    for feet, ceiling in floors:
        b.floors(feet)
        b.arcade(feet, ceiling)
        b.furniture(feet)
        lights = [(-58, -116), (25, -116), (5, -107), (-32, -101)]
        if feet == 99:
            lights += [(-33, -116), (-30, -132)]
        for x, z in lights:
            b.chandelier(x, z, feet, ceiling)
        b.lift_cabin(feet, ceiling)
    b.diorama()
    b.selection_bays()
    b.leaf_distances()
    navigation = b.navigation()
    palette = sorted({s.partition("[")[0] for s in b.states.values()})
    metadata = {
        "schema_version": 1,
        "name": "Shacraft station furnished vestibule and SMASH gallery",
        "status": "compiled candidate; requires caller survey, collision and live verification",
        "owned_y": [98, 123], "perimeter_setback_blocks": 2,
        "foundation_columns": len(b.footprint), "interior_columns": len(b.inside),
        "state_count": len(b.states), "non_air_count": sum(s != AIR for s in b.states.values()),
        "group_counts": dict(sorted(Counter(b.groups.values()).items())),
        "palette": palette, "features": b.features, "lift": b.lift,
        "selection_bays": b.selections, "text_displays": b.texts,
        "walk_points": b.floor_walk[99] + b.floor_walk[113],
        "walk_points_by_floor": {str(k): v for k, v in b.floor_walk.items()},
        "navigation": navigation,
        "design_invariants": {
            "only_two_furnished_floors": True, "upper_floor_has_no_holes": True,
            "lift_has_no_open_shaft": True, "no_attic_or_clocktower_access": True,
            "diorama_is_closed_and_display_only": True, "arena_slots_are_unassigned": True,
            "functional_text_signs_and_lift_are_caller_owned": True,
        },
    }
    return b.states, b.groups, metadata
