"""Deterministic voxel blueprint for the generated Gothic hall reference."""
from collections import Counter, defaultdict
import importlib
import re

ORIGIN = (-50, -60, -40)

class Voxels:
    def __init__(self):
        self.blocks = {}
        self.stage = 'site'
        self.owners = {}

    def set(self, x, y, z, block):
        assert all(isinstance(v, int) for v in (x, y, z)), (x, y, z)
        assert -2 <= x <= 68 and -1 <= y <= 64 and -2 <= z <= 68, (x, y, z)
        if not block.startswith('minecraft:'):
            block = 'minecraft:' + block
        assert re.fullmatch(r'minecraft:[a-z0-9_]+(?:\[[a-z0-9_=,]+\])?', block), block
        if block == 'minecraft:air':
            self.blocks.pop((x, y, z), None)
            self.owners.pop((x, y, z), None)
        else:
            self.blocks[(x, y, z)] = block
            self.owners[(x, y, z)] = self.stage

    def box(self, x1, y1, z1, x2, y2, z2, block):
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        z1, z2 = sorted((z1, z2))
        for y in range(y1, y2 + 1):
            for z in range(z1, z2 + 1):
                for x in range(x1, x2 + 1):
                    self.set(x, y, z, block)

    def clear(self, x1, y1, z1, x2, y2, z2):
        self.box(x1, y1, z1, x2, y2, z2, 'air')

def site(v):
    v.box(1, 0, 1, 63, 0, 62, 'smooth_stone')
    for z in (1, 62):
        v.box(1, 0, z, 63, 0, z, 'polished_andesite')
    for x in (1, 63):
        v.box(x, 0, 1, x, 0, 62, 'polished_andesite')
    # A few continuous paving bands give the terrace scale without noisy texture.
    for x in (5, 33, 60):
        v.box(x, 0, 2, x, 0, 61, 'stone_bricks')
    for z in (4, 59):
        v.box(2, 0, z, 62, 0, z, 'stone_bricks')
    for step in range(1, 7):
        z = step + 1
        v.box(13, 1, z, 25, step, z, 'stone_bricks')
        v.box(14, step, z, 24, step, z,
              'stone_brick_stairs[facing=south,half=bottom,shape=straight,waterlogged=false]')
        for x in (12, 26):
            v.box(x, 1, z, x, step + 1, z, 'polished_andesite')
            v.set(x, step + 2, z, 'stone_brick_slab[type=bottom,waterlogged=false]')
    v.box(13, 1, 8, 25, 6, 9, 'stone_bricks')
    for x in (8, 30, 35, 61):
        for z in (6, 59):
            v.box(x, 1, z, x + 1, 1, z + 1, 'polished_andesite')
            v.box(x, 2, z, x + 1, 3, z + 1, 'stone_bricks')
            v.box(x, 4, z, x + 1, 4, z + 1,
                  'stone_brick_slab[type=bottom,waterlogged=false]')

def connection(v):
    # Two-level enclosed passage between the great hall and companion wing.
    v.stage = 'connecting gallery'
    v.box(31, 0, 34, 40, 6, 42, 'stone_bricks')
    v.box(31, 7, 34, 40, 13, 34, 'stone_bricks')
    v.box(31, 7, 42, 40, 13, 42, 'stone_bricks')
    v.box(31, 13, 33, 40, 13, 43, 'polished_andesite')
    v.box(31, 14, 34, 40, 14, 42, 'deepslate_tiles')
    v.box(31, 15, 36, 40, 15, 40, 'deepslate_tiles')
    v.box(31, 16, 38, 40, 16, 38, 'deepslate_tiles')
    for z, facing, y in [(34, 'south', 14), (35, 'south', 14),
                         (36, 'south', 15), (37, 'south', 15),
                         (39, 'north', 15), (40, 'north', 15),
                         (41, 'north', 14), (42, 'north', 14)]:
        v.box(31, y, z, 40, y, z,
              f'deepslate_tile_stairs[facing={facing},half=bottom,shape=straight,waterlogged=false]')
    v.clear(30, 7, 36, 32, 11, 39)
    v.clear(33, 8, 36, 34, 11, 39)
    v.clear(35, 9, 36, 40, 12, 39)
    v.box(31, 6, 36, 32, 6, 39, 'spruce_planks')
    for x, y in [(33, 6), (34, 7)]:
        v.box(x, y, 36, x, y, 39,
              'spruce_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]')
    v.box(35, 8, 36, 40, 8, 39, 'spruce_planks')

def build_scene():
    v = Voxels()
    site(v)
    for name, stage in [('main_hall', 'great hall'), ('side_wing', 'side wing'), ('tower', 'bell tower')]:
        v.stage = stage
        importlib.import_module('builds.gothic_hall.' + name).build(v)
    connection(v)
    return v

def boxes(blocks):
    """Merge runs on X, then Z and Y, preserving the exact sparse block mask."""
    rows = defaultdict(list)
    for (x, y, z), block in blocks.items():
        rows[(y, z, block)].append(x)
    runs = []
    for (y, z, block), xs in sorted(rows.items()):
        xs.sort(); start = end = xs[0]
        for x in xs[1:]:
            if x == end + 1:
                end = x
            else:
                runs.append((start, y, z, end, y, z, block)); start = end = x
        runs.append((start, y, z, end, y, z, block))
    merged = []
    groups = defaultdict(list)
    for x1, y1, z1, x2, y2, z2, block in runs:
        groups[(x1, x2, y1, block)].append(z1)
    for (x1, x2, y, block), zs in sorted(groups.items()):
        zs.sort(); start = end = zs[0]
        for z in zs[1:]:
            if z == end + 1: end = z
            else:
                merged.append((x1, y, start, x2, y, end, block)); start = end = z
        merged.append((x1, y, start, x2, y, end, block))
    result = []; groups = defaultdict(list)
    for x1, y1, z1, x2, y2, z2, block in merged:
        groups[(x1, x2, z1, z2, block)].append(y1)
    for (x1, x2, z1, z2, block), ys in sorted(groups.items()):
        ys.sort(); start = end = ys[0]
        for y in ys[1:]:
            if y == end + 1: end = y
            else:
                result.append((x1, start, z1, x2, end, z2, block)); start = end = y
        result.append((x1, start, z1, x2, end, z2, block))
    return result

def manifest(v):
    tiles = defaultdict(dict)
    for p, block in v.blocks.items():
        tiles[(p[1] // 8, p[2] // 16, p[0] // 16)][p] = block
    batches = []
    for key, data in sorted(tiles.items()):
        recipe = []
        for x1, y1, z1, x2, y2, z2, block in boxes(data):
            lo = dict(zip(('x', 'y', 'z'), (x1 + ORIGIN[0], y1 + ORIGIN[1], z1 + ORIGIN[2])))
            hi = dict(zip(('x', 'y', 'z'), (x2 + ORIGIN[0], y2 + ORIGIN[1], z2 + ORIGIN[2])))
            recipe.append({'type': 'box', 'min': lo, 'max': hi, 'block': block})
        positions = list(data)
        minimum = [min(p[i] for p in positions) + ORIGIN[i] for i in range(3)]
        maximum = [max(p[i] for p in positions) + ORIGIN[i] for i in range(3)]
        batches.append({'key': '-'.join(map(str, key)), 'blocks': len(data),
                        'min': dict(zip(('x', 'y', 'z'), minimum)), 'max': dict(zip(('x', 'y', 'z'), maximum)),
                        'recipe': {'version': 1, 'operations': recipe},
                        'stages': dict(Counter(v.owners[p] for p in data))})
    return {'name': 'Gothic hall reference reconstruction', 'origin': ORIGIN,
            'blocks': len(v.blocks), 'stages': dict(Counter(v.owners.values())),
            'palette': dict(Counter(v.blocks.values())), 'batches': batches}
