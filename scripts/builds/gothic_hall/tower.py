"""Reference bell tower, in the shared scene's inclusive local coordinates.

The scene supplies set(x, y, z, block), box(x1, y1, z1, x2, y2, z2,
block), and clear(x1, y1, z1, x2, y2, z2). This module has no I/O.
All geometry stays inside x=34..46, y=0..60, z=42..56.
"""


STONE = "minecraft:stone_bricks"
TRIM = "minecraft:polished_andesite"
LIGHT = "minecraft:polished_diorite"
DARK = "minecraft:deepslate_tiles"
GLASS = "minecraft:tinted_glass"
AIR = "minecraft:air"


def _face(face, u, y, depth=0):
    """Positive depth projects outward; -1 is the recessed glazing plane."""
    if face == "north":
        return u, y, 43 - depth
    if face == "south":
        return u, y, 55 + depth
    if face == "west":
        return 35 - depth, y, u
    return 45 + depth, y, u


def _put(v, face, u, y, block, depth=0):
    v.set(*_face(face, u, y, depth), block)


def _ring(v, x1, z1, x2, z2, y, block):
    v.box(x1, y, z1, x2, y, z1, block)
    v.box(x1, y, z2, x2, y, z2, block)
    v.box(x1, y, z1, x1, y, z2, block)
    v.box(x2, y, z1, x2, y, z2, block)


def _lancet(v, face, center, bottom, top, half_width):
    """A pointed opening through a two-block wall, glass one block behind it."""
    for y in range(bottom, top + 1):
        radius = 0 if y >= top - 1 else half_width
        for u in range(center - radius, center + radius + 1):
            _put(v, face, u, y, AIR)
            _put(v, face, u, y, GLASS, -1)
        # The projecting dressings are stone; the glazing never projects.
        for u in {center - radius - 1, center + radius + 1}:
            _put(v, face, u, y, TRIM, 1)
    for u in range(center - half_width - 1, center + half_width + 2):
        _put(v, face, u, bottom - 1, "minecraft:stone_brick_slab[type=top]", 1)
    _put(v, face, center, top + 1, LIGHT, 1)


def _belfry_arch(v, face, center):
    # Seven blocks wide below, narrowing to a high, single-block apex.
    for y in range(32, 41):
        radius = 3 if y <= 37 else 40 - y
        for u in range(center - radius, center + radius + 1):
            for depth in (0, -1):
                _put(v, face, u, y, AIR, depth)
        for u in (center - radius - 1, center + radius + 1):
            _put(v, face, u, y, TRIM, 1)
    _put(v, face, center, 41, LIGHT, 1)
    for u in range(center - 4, center + 5):
        _put(v, face, u, 31, "minecraft:stone_brick_slab[type=top]", 1)


def _stairs(v):
    # Three narrow alternating flights join the interior floors. A landing at
    # each end leaves a three-block-wide central well open through the tower.
    for y_floor, xs, reverse in ((1, (37, 38), False),
                                 (10, (42, 43), True),
                                 (19, (37, 38), False)):
        facing = "north" if reverse else "south"
        state = f"minecraft:stone_brick_stairs[facing={facing},half=bottom,shape=straight]"
        for i in range(9):
            z = 53 - i if reverse else 45 + i
            y = y_floor + i + 1
            for x in xs:
                # Clearance through the destination floor, including headroom.
                v.clear(x, y + 1, z, x, y + 3, z)
                v.set(x, y, z, state)
        # The flight exits sideways onto the destination floor.
    v.clear(39, 29, 53, 41, 32, 53)
    v.set(41, 29, 52, "minecraft:stone_brick_stairs[facing=north]")
    v.set(41, 30, 51, "minecraft:stone_brick_stairs[facing=north]")
    v.clear(41, 30, 52, 41, 33, 52)
    v.clear(41, 31, 51, 41, 33, 51)


def _spire(v):
    # A hollow, steep rectangular hip roof; alternate contractions avoid a
    # stack of disconnected floating rings while giving the spire a fine tip.
    for y in range(45, 57):
        step = y - 45
        rx = 5 - step // 2
        rz = 6 - (step + 1) // 2
        if rx < 0:
            rx = 0
        if rz < 0:
            rz = 0
        x1, x2, z1, z2 = 40 - rx, 40 + rx, 49 - rz, 49 + rz
        v.box(x1, y, z1, x2, y, z2, DARK)
        if rx > 0 and rz > 0:
            v.clear(x1 + 1, y, z1 + 1, x2 - 1, y, z2 - 1)
        # Stair edges soften the one-block roof steps without adding width.
        if rx > 0 and rz > 0:
            for x in range(x1 + 1, x2):
                v.set(x, y, z1, "minecraft:deepslate_tile_stairs[facing=south]")
                v.set(x, y, z2, "minecraft:deepslate_tile_stairs[facing=north]")
            for z in range(z1 + 1, z2):
                v.set(x1, y, z, "minecraft:deepslate_tile_stairs[facing=east]")
                v.set(x2, y, z, "minecraft:deepslate_tile_stairs[facing=west]")
    # The cross is plain masonry, with no unsupported entities or thin blocks.
    v.box(40, 57, 49, 40, 60, 49, TRIM)
    v.box(39, 59, 49, 41, 59, 49, TRIM)


def build(v):
    """Add a hollow Gothic bell tower and its pointed roof to a scene."""
    # Foundation and shell: two-block walls give the apertures real reveals.
    v.box(35, 0, 43, 45, 43, 55, STONE)
    v.clear(37, 2, 45, 43, 42, 53)
    _ring(v, 34, 42, 46, 56, 0, "minecraft:deepslate_bricks")
    _ring(v, 34, 42, 46, 56, 1, TRIM)
    _ring(v, 34, 42, 46, 56, 3, "minecraft:stone_brick_slab[type=bottom]")

    # Dressed corners and stepped buttress feet, all within the tower envelope.
    corners = ((34, 42, 35, 43), (45, 42, 46, 43),
               (34, 55, 35, 56), (45, 55, 46, 56))
    for x1, z1, x2, z2 in corners:
        v.box(x1, 1, z1, x2, 5, z2, TRIM)
        v.box(x1, 6, z1, x2, 29, z2, STONE)
        for y in (6, 15, 28):
            v.box(x1, y, z1, x2, y, z2, TRIM)
    for x, z in ((35, 43), (45, 43), (35, 55), (45, 55)):
        v.box(x, 4, z, x, 43, z, TRIM)

    # Strong horizontal courses separate the shaft from the open belfry.
    for y in (15, 16, 29, 30, 42, 43):
        _ring(v, 34, 42, 46, 56, y, TRIM if y % 2 else STONE)
    for y in (10, 19, 28, 30):
        v.box(37, y, 45, 43, y, 53, "minecraft:oak_planks")
        if y != 30:
            v.clear(39, y, 47, 41, y, 51)
    v.box(35, 44, 43, 45, 44, 55, STONE)
    _ring(v, 34, 42, 46, 56, 44, "minecraft:stone_brick_slab[type=bottom]")

    # Paired narrow lower lights and broader, pointed upper lancets.
    for face, centers in (("north", (38, 42)), ("south", (38, 42)),
                          ("west", (47, 51)), ("east", (47, 51))):
        for center in centers:
            _lancet(v, face, center, 6, 12, 0)
            _lancet(v, face, center, 19, 26, 1)
        _belfry_arch(v, face, 40 if face in ("north", "south") else 49)

    # An actual walk-in doorway toward the wing; no decorative solid door.
    v.clear(39, 2, 42, 41, 5, 44)
    v.clear(40, 6, 42, 40, 6, 44)
    for x in (38, 42):
        v.box(x, 2, 42, x, 5, 42, TRIM)
    v.set(39, 6, 42, TRIM)
    v.set(41, 6, 42, TRIM)
    v.set(40, 7, 42, LIGHT)
    _stairs(v)

    # A block-built ochre bell echoes the reference using allowlisted sandstone.
    # Its open mouth and central clapper remain visible through all four arches.
    v.box(35, 41, 49, 45, 41, 49, "minecraft:spruce_log[axis=x]")
    v.box(40, 38, 49, 40, 40, 49, "minecraft:dark_oak_log[axis=y]")
    v.box(40, 36, 49, 40, 37, 49, "minecraft:cut_sandstone")
    for x, z in ((39, 49), (40, 48), (40, 49), (40, 50), (41, 49)):
        v.set(x, 35, z, "minecraft:cut_sandstone")
    _ring(v, 39, 48, 41, 50, 34, "minecraft:cut_sandstone")
    v.set(40, 34, 49, "minecraft:dark_oak_log[axis=y]")
    v.set(40, 33, 49, TRIM)

    # A row of small corbels under the cornice is readable from a distance.
    for face, us in (("north", (37, 39, 41, 43)), ("south", (37, 39, 41, 43)),
                     ("west", (45, 47, 49, 51, 53)), ("east", (45, 47, 49, 51, 53))):
        for u in us:
            _put(v, face, u, 41, f"minecraft:stone_brick_stairs[facing={face},half=top]", 1)
    _spire(v)

    # Four light corner pinnacles frame the darker central spire.
    for x, z in ((35, 43), (45, 43), (35, 55), (45, 55)):
        v.box(x, 44, z, x, 49, z, TRIM)
        for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            v.set(x + dx, 46, z + dz, "minecraft:stone_brick_slab[type=top]")
        v.set(x, 50, z, "minecraft:stone_brick_slab[type=bottom]")
