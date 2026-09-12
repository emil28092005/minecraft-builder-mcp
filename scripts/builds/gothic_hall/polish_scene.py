"""Reference-driven finishing layer; the original scene and its ledgers stay immutable."""
from .scene import build_scene as original_scene
from .polish_architecture import build as architecture

STONE = 'minecraft:stone_bricks'
TRIM = 'minecraft:polished_andesite'
LEAVES = 'minecraft:oak_leaves[distance=7,persistent=true,waterlogged=false]'
CHAIN = 'minecraft:iron_chain[axis=y,waterlogged=false]'
SLAB = 'minecraft:stone_brick_slab[type=bottom,waterlogged=false]'


def stair(facing, half='top'):
    return f'minecraft:stone_brick_stairs[facing={facing},half={half},shape=straight,waterlogged=false]'


def bars(north=False, east=False, south=False, west=False):
    return ('minecraft:iron_bars[' + ','.join(f'{key}={str(value).lower()}' for key, value in
            [('north', north), ('east', east), ('south', south), ('west', west)]) + ',waterlogged=false]')


def finished_scene():
    v = original_scene()
    for x in (6, 32):
        for z in (14, 22, 30, 38, 46, 54):
            v.set(x, 30, z, STONE)
    for x in (7, 31):
        v.set(x, 34, 12, STONE)
    for z in range(36, 40):
        v.set(35, 8, z, stair('east', 'bottom'))
    return v


def lamp(v, x, y, z, hanging=True):
    v.set(x, y, z, f'minecraft:lantern[hanging={str(hanging).lower()},waterlogged=false]')


def lighting(v):
    v.stage = 'lanterns and interior lighting'
    # Portal fixtures attach to the existing masonry jambs.
    for x in (13, 25):
        v.set(x, 14, 9, stair('south'))
        v.set(x, 13, 9, CHAIN)
        lamp(v, x, 12, 9)
    for x, facing, bays in ((4, 'east', (14, 22, 30, 38, 46, 54)),
                            (34, 'west', (14, 22, 30))):
        for z in bays:
            v.set(x, 16, z, stair(facing))
            v.set(x, 15, z, CHAIN)
            lamp(v, x, 14, z)
    for x in (43, 52):
        v.set(x, 8, 14, stair('south'))
        v.set(x, 7, 14, CHAIN)
        lamp(v, x, 6, 14)
    for z in (21, 29, 37):
        v.set(59, 14, z, TRIM)
        v.set(60, 14, z, stair('west'))
        v.set(60, 13, z, CHAIN)
        lamp(v, 60, 12, z)
    # Existing low piers become courtyard lamps, with a full supporting cap.
    for x in (8, 30, 35, 61):
        for z in (6, 59):
            v.set(x, 4, z, TRIM)
            lamp(v, x, 5, z, False)
    # Three chandeliers hang in the clear nave, below the preserved timber ties.
    for z in (22, 38, 46):
        v.box(19, 19, z, 19, 27, z, CHAIN)
        for dx in range(-2, 3):
            v.set(19 + dx, 18, z, bars(dx == 0, dx < 2, dx == 0, dx > -2))
        for dz in (-2, -1, 1, 2):
            v.set(19, 18, z + dz, bars(dz > -2, False, dz < 2, False))
        for x, zz in ((17, z), (21, z), (19, z - 2), (19, z + 2)):
            lamp(v, x, 17, zz)
    for x, facing in ((13, 'west'), (25, 'east')):
        for z in (22, 38, 46):
            v.set(x, 12, z, stair(facing))
            v.set(x, 11, z, CHAIN)
            lamp(v, x, 10, z)
    # Wing ground floor: lights hang from the existing floor beams.
    for x in (43, 50):
        for z in (23, 31):
            v.set(x, 6, z, CHAIN)
            lamp(v, x, 5, z)
    for z in (23, 35):
        v.box(38, 17, z, 57, 17, z, 'minecraft:spruce_log[axis=x]')
        v.box(47, 14, z, 47, 16, z, CHAIN)
        lamp(v, 47, 13, z)
    # Tower landings and the block-built bell receive a restrained warm light.
    for y in (7, 16, 25):
        v.box(40, y + 1, 46, 40, y + 2, 46, CHAIN)
        lamp(v, 40, y, 46)
    for x in (37, 43):
        v.box(x, 39, 49, x, 40, 49, CHAIN)
        lamp(v, x, 38, 49)


def landscape(v):
    v.stage = 'planted stone terrace'

    def bed(x1, z1, x2, z2, high=3):
        # Soil replaces only the known terrace surface, with a low dressed rim.
        for x in range(x1, x2 + 1):
            for z in range(z1, z2 + 1):
                edge = x in (x1, x2) or z in (z1, z2)
                if edge:
                    if (x, 1, z) not in v.blocks:
                        v.set(x, 1, z, SLAB)
                else:
                    v.set(x, 0, z, 'minecraft:dirt')
                    height = high - int((x * 7 + z * 11) % 5 == 0)
                    for y in range(1, height + 1):
                        if (x, y, z) not in v.blocks:
                            v.set(x, y, z, LEAVES)

    for z in (18, 26, 34, 42, 50):
        bed(1, z - 2, 5, z + 2, 2)
    for z in (21, 29, 37):
        bed(60, z - 2, 64, z + 2, 2)
    bed(5, 9, 12, 11, 2)
    bed(26, 9, 32, 11, 2)
    bed(39, 11, 43, 13, 2)
    bed(52, 11, 56, 13, 2)
    bed(9, 59, 28, 61, 2)
    bed(48, 45, 59, 47, 2)

    def narrow_tree(x, z, height):
        # Persistent leaves cannot decay; every addition respects existing masonry.
        if (x, 0, z) not in v.blocks or v.blocks[(x, 0, z)].split('[')[0] in (
                'minecraft:smooth_stone', 'minecraft:polished_andesite', 'minecraft:stone_bricks'):
            v.set(x, 0, z, 'minecraft:moss_block')
        for y in range(1, height - 1):
            if (x, y, z) not in v.blocks or v.blocks[(x, y, z)] == LEAVES:
                v.set(x, y, z, 'minecraft:spruce_log[axis=y]')
        for y in range(2, height + 1):
            radius = 2 if y <= height - 4 else 1 if y <= height - 1 else 0
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if abs(dx) + abs(dz) > radius + 1:
                        continue
                    p = x + dx, y, z + dz
                    if p not in v.blocks or v.blocks[p] == LEAVES:
                        v.set(*p, LEAVES)
    for x, z, h in ((10, 9, 8), (28, 9, 8), (62, 16, 7), (62, 44, 7),
                     (6, 60, 8), (32, 60, 7)):
        narrow_tree(x, z, h)
    # Slight wear follows the edges, leaving the main approach calm and readable.
    for (x, y, z), block in list(v.blocks.items()):
        if y == 0 and block == 'minecraft:smooth_stone' and (x < 6 or x > 59 or z > 57):
            if (x * 31 + z * 17) % 29 == 0:
                v.set(x, y, z, 'minecraft:andesite')
        if y in (1, 2, 3) and block == STONE and (x < 8 or x > 56) and (x * 13 + y * 7 + z * 19) % 31 == 0:
            v.set(x, y, z, 'minecraft:mossy_stone_bricks')


def build_scene():
    v = finished_scene()
    architecture(v)
    lighting(v)
    landscape(v)
    return v
