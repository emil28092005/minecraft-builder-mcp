"""The smaller, two-storey gabled companion to the main Gothic hall.

Coordinates are inclusive and local to the complete composition.  ``build``
only writes through the supplied voxel API; it does not contact Minecraft.
"""

STONE = "minecraft:stone_bricks"
TRIM = "minecraft:polished_andesite"
LIGHT = "minecraft:polished_diorite"
GLASS = "minecraft:tinted_glass"
WOOD = "minecraft:spruce_planks"
BEAM = "minecraft:stripped_spruce_log[axis=y]"
ROOF = "minecraft:deepslate_tiles"
AIR = "minecraft:air"


def _stair(material, facing, half="bottom"):
    return (
        f"minecraft:{material}[facing={facing},half={half},"
        "shape=straight,waterlogged=false]"
    )


def _wall_block(x, y, z):
    """Sparse, deterministic masonry variation, without a checkerboard."""
    n = (x * 31 + y * 17 + z * 47 + x * z * 3) % 53
    if n < 3:
        return "minecraft:cracked_stone_bricks"
    if n < 8:
        return "minecraft:andesite"
    return STONE


def _lancet(v, left, right, bottom, top, wall, outside, north=False):
    """A stone pointed surround, open reveal, and recessed dark glass."""
    center = (left + right) / 2

    def point(u, y, depth, block):
        if north:
            v.set(u, y, depth, block)
        else:
            v.set(depth, y, u, block)

    for u in range(left - 1, right + 2):
        cap = top + 1 - int(abs(u - center))
        for y in range(bottom - 1, cap + 1):
            point(u, y, outside, LIGHT if y == cap else TRIM)
    for u in range(left, right + 1):
        cap = top - int(abs(u - center))
        for y in range(bottom, cap + 1):
            point(u, y, outside, AIR)
            point(u, y, wall, GLASS)
    # The sill projects one block; the glass stays in the wall behind it.
    for u in range(left - 1, right + 2):
        point(u, bottom - 1, outside, LIGHT)


def _buttress(v, west, z):
    """Three diminishing stages, with projecting pale weathering caps."""
    outer, inner = (36, 38) if west else (57, 59)
    v.box(outer, 0, z - 1, inner, 1, z + 1, TRIM)
    a, b = (37, 38) if west else (57, 58)
    v.box(a, 2, z - 1, b, 6, z + 1, STONE)
    v.box(outer, 7, z - 1, inner, 7, z + 1, LIGHT)
    v.box(a, 8, z, b, 14, z, STONE)
    v.box(a, 15, z - 1, b, 15, z + 1, TRIM)
    v.box(a, 16, z, b, 18, z, STONE)
    v.box(a, 19, z, b, 19, z, LIGHT)


def _entrance(v):
    # Two nested pointed archivolts give the entrance visible depth.
    for z, left, right, peak, block in (
        (14, 44, 51, 8, TRIM),
        (15, 45, 50, 7, LIGHT),
    ):
        for x in range(left, right + 1):
            cap = peak - int(abs(x - 47.5))
            v.box(x, 1, z, x, cap, z, block)
    for x in range(46, 50):
        cap = 6 - int(abs(x - 47.5))
        v.clear(x, 1, 14, x, cap, 17)
    # Timber inner jambs suggest the tall wooden doorway, leaving it usable.
    v.box(45, 1, 16, 45, 4, 16, BEAM)
    v.box(50, 1, 16, 50, 4, 16, BEAM)
    v.box(44, 0, 13, 51, 0, 16, TRIM)
    v.box(46, 0, 14, 49, 0, 17, "minecraft:smooth_stone")


def build(v):
    """Build within x=36..59, y=0..28, z=13..43."""
    # Hollow masonry shell, an accessible ground floor and an upper floor.
    v.box(38, 0, 16, 57, 0, 41, TRIM)
    v.clear(39, 1, 17, 56, 27, 40)
    for y in range(1, 18):
        for x in range(38, 58):
            for z in (16, 41):
                v.set(x, y, z, _wall_block(x, y, z))
        for z in range(17, 41):
            for x in (38, 57):
                v.set(x, y, z, _wall_block(x, y, z))
    v.box(39, 0, 17, 56, 0, 40, WOOD)
    v.box(39, 8, 17, 56, 8, 40, WOOD)

    # Floor bands and the projecting eaves visually join the two storeys.
    for y, block in ((0, TRIM), (7, TRIM), (8, LIGHT), (16, TRIM)):
        v.box(37, y, 15, 58, y, 15, block)
        v.box(37, y, 42, 58, y, 42, block)
        v.box(58, y, 16, 58, y, 41, block)
        for z in range(16, 42):
            # The main composition will connect the gallery through here.
            if not (7 <= y <= 11 and 36 <= z <= 39):
                v.set(37, y, z, block)

    for z in (17, 25, 33, 41):
        _buttress(v, True, z)
        _buttress(v, False, z)
    for x in (38, 57):
        v.box(x - 1, 0, 14, x + 1, 1, 16, TRIM)
        v.box(x, 2, 14, x, 16, 16, STONE)
        v.box(x - 1, 17, 14, x + 1, 17, 16, LIGHT)
        v.box(x, 18, 15, x, 20, 15, STONE)
        v.set(x, 21, 15, LIGHT)

    # A paired rhythm of small lower and tall upper side windows.
    for z in (21, 29, 37):
        for wall, outside in ((38, 37), (57, 58)):
            if wall == 38 and z == 37:
                continue  # Keep the gallery doorway and its approach clear.
            _lancet(v, z - 1, z + 1, 2, 6, wall, outside)
            _lancet(v, z - 1, z + 1, 10, 15, wall, outside)
    for left, right in ((41, 42), (53, 54)):
        _lancet(v, left, right, 2, 6, 16, 15, north=True)
    for left, right in ((42, 45), (50, 53)):
        _lancet(v, left, right, 10, 15, 16, 15, north=True)
    _entrance(v)

    # Timber supports remain against the edges, leaving the rooms traversable.
    for x in (40, 55):
        for z in (18, 39):
            v.box(x, 1, z, x, 7, z, BEAM)
    for z in (23, 31, 39):
        v.box(39, 7, z, 56, 7, z, "minecraft:stripped_spruce_log[axis=x]")
    v.clear(53, 8, 28, 55, 11, 35)
    for step in range(8):
        y, z = step + 1, 28 + step
        if y > 1:
            v.box(53, 1, z, 55, y - 1, z, WOOD)
        v.box(53, y, z, 55, y, z, _stair("spruce_stairs", "south"))
        v.clear(53, y + 1, z, 55, y + 2, z)
    v.box(52, 9, 28, 52, 9, 35, "minecraft:spruce_slab[type=bottom,waterlogged=false]")

    # A steep roof, dark in the middle and bounded by pale stepped gables.
    for x in range(37, 59):
        rise = min(x - 37, 58 - x)
        y = 17 + rise
        facing = "east" if x <= 47 else "west"
        if 38 <= x <= 57 and y >= 18:
            for z in (16, 41):
                v.box(x, 18, z, x, y, z, STONE)
        v.box(x, y, 15, x, y, 42, _stair("deepslate_tile_stairs", facing))
        for z in (14, 43):
            v.set(x, y, z, _stair("stone_brick_stairs", facing))
            if y > 17:
                v.set(x, y - 1, z, TRIM)
    v.box(47, 28, 15, 48, 28, 42, ROOF)
    for z in (14, 43):
        v.box(47, 27, z, 48, 28, z, LIGHT)
    _lancet(v, 46, 49, 19, 24, 16, 15, north=True)
    for x in (47, 48):
        v.box(x, 26, 15, x, 28, 15, TRIM)

    # Wooden cornice brackets are visible under the long roof slopes.
    for z in (19, 23, 27, 31, 35, 39):
        for x, facing in ((37, "east"), (58, "west")):
            v.set(x, 16, z, _stair("spruce_stairs", facing, half="top"))
