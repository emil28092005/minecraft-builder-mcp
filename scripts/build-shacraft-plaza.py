#!/usr/bin/env python3
"""Compile a reference-led arrival garden against observed, protected voxel states.

No world writes. Apply the resulting checked recipe with scripts/layout.py.
The brand bitmap is sampled into block coordinates, not used as a rendered fake.
"""
import argparse
from collections import Counter, deque
import hashlib
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N2 = ((1, 0), (-1, 0), (0, 1), (0, -1))
N3 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
AIR = 'minecraft:air'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


geometry = module('plaza_geometry', ROOT / 'scripts/foundation-study/geometry.py')
survey = module('plaza_survey', ROOT / 'scripts/foundation-survey.py')
assets = module('plaza_assets', ROOT / 'scripts/plaza-assets.py')


def distances(mask):
    result = {p: 0 for p in mask if any((p[0]+dx, p[1]+dz) not in mask for dx, dz in N2)}
    pending = deque(result)
    while pending:
        x, z = pending.popleft()
        for dx, dz in N2:
            p = x+dx, z+dz
            if p in mask and p not in result:
                result[p] = result[x, z]+1
                pending.append(p)
    return result


def brand_cells(path, width=25, height=35):
    from PIL import Image
    source = Image.open(path).convert('RGBA')
    # Select the green artwork, excluding transparency and the pale antialias fringe.
    mask = Image.new('L', source.size)
    pixels = source.get_flattened_data() if hasattr(source, 'get_flattened_data') else source.getdata()
    mask.putdata([255 if a > 100 and g > r*1.15 and g > b*1.15 else 0 for r, g, b, a in pixels])
    box = mask.getbbox()
    if not box:
        raise ValueError('Brand image contains no green artwork')
    cells = mask.crop(box).resize((width, height), Image.Resampling.BOX)
    return {(x-width//2, z+9-height//2) for z in range(height) for x in range(width)
            if cells.getpixel((x, z)) >= 115}


def compile_plan(design, before, previous, logo):
    base_geometry = json.loads((ROOT / '.runtime/foundations-stage02/foundations-final.geometry.json').read_text())
    cells = {(c['x'], c['z']): c for c in base_geometry['cells']}
    outer = geometry.polygon_cells(design['outer_hex'])
    floor = {p for p in outer if cells[p]['kind'] == 'full' and cells[p]['block_y'] == 95}
    edge = distances(outer)
    protected = {tuple(p) for route in base_geometry['routes'] for p in route['clear_cells']}
    desired, groups = {}, {}

    def put(x, y, z, state, group):
        if not state.startswith('minecraft:'):
            state = 'minecraft:'+state
        before.state(x, y, z)  # Require observed support and air, including canopy overhangs.
        desired[x, y, z], groups[x, y, z] = state, group

    def current(x, y, z):
        return desired.get((x, y, z), before.state(x, y, z))

    # Retire only still-matching zone01 survey marks, including its exterior
    # stakes and number. Other districts and changed human blocks are preserved.
    marker_groups = {'arrival-hex', 'spawn-medallion', 'spawn-monogram', 'label-01', 'wayfinding-01'}
    markers = json.loads((ROOT/'.runtime/layout-study/markers-final.json').read_text())
    for b in markers['blocks']:
        if b.get('group') not in marker_groups:
            continue
        p = b['x'], b['y'], b['z']
        try:
            observed = before.state(*p)
        except (KeyError, ValueError):
            continue
        if observed == b['block']:
            put(*p, b['expected'], 'retire-zone01-survey')

    # Preserve stair treads, the foundation footprint, and all neighboring districts.
    for x, z in sorted(floor):
        material = 'smooth_sandstone'
        if edge[x, z] == 0:
            material = 'cut_sandstone'
        elif edge[x, z] == 1:
            material = 'smooth_stone'
        put(x, 95, z, material, 'cream-paving')

    for radius, material in ((22, 'polished_andesite'), (24, 'smooth_stone'), (28, 'cut_sandstone')):
        poly = [(round(radius*math.sin(i*math.pi/3)), 9-round(radius*math.cos(i*math.pi/3))) for i in range(6)]
        ring = geometry.polygon_cells(poly)
        for x, z in ring:
            if any((x+dx, z+dz) not in ring for dx, dz in N2):
                put(x, 95, z, material, 'hexagonal-paving-bands')
    logo_mask = brand_cells(logo)
    for x, z in logo_mask:
        if (x, z) not in floor:
            raise ValueError('Logo exceeds the paving')
        put(x, 95, z, 'green_concrete', 'original-brand-inlay')

    # Replace the former bulky survey-stage light piers. Their perimeter rails remain.
    old_plan = json.loads((ROOT / '.runtime/foundations-stage02/foundations-final.json').read_text())
    old_lamps = [(b['x'], b['z']) for b in old_plan['blocks'] if b.get('group') == 'lamps'
                 and ((b['x'], b['z']) in outer or (b['x'], b['z']) == (-5, 56))]
    for x, z in old_lamps:
        for y in range(96, 100):
            put(x, y, z, 'air', 'replace-old-lamp-piers')
        props = {}
        for name, (dx, dz) in {'east': (1, 0), 'north': (0, -1), 'south': (0, 1), 'west': (-1, 0)}.items():
            neighbor = before.state(x+dx, 96, z+dz)
            props[name] = 'low' if any(n in neighbor for n in ('stone_brick_wall', 'chiseled_stone_bricks')) else 'none'
        put(x, 96, z, 'stone_brick_wall['+','.join(f'{k}={v}' for k, v in sorted(props.items() | {'up': 'true', 'waterlogged': 'false'}.items()))+']', 'restored-perimeter-rail')

    beds, beds_union, bench_aprons, fixture_records = [], set(), set(), []
    flower_types = ('pink_tulip', 'white_tulip', 'oxeye_daisy', 'allium', 'azure_bluet')
    for index, bed in enumerate(design['beds']):
        mask = geometry.polygon_cells(bed['outline'])
        mask |= {tuple(p) for p in bed.get('additional_planting_columns', [])}
        if not mask <= floor or mask & protected:
            raise ValueError('Garden intersects a protected road or non-flat foundation')
        beds.append(mask)
        beds_union |= mask
        inset = distances(mask)
        for x, z in sorted(mask):
            put(x, 94, z, 'dirt', 'garden-soil')
            put(x, 95, z, 'grass_block[snowy=false]', 'garden-soil')
            if inset[x, z] == 0:
                put(x, 95, z, 'smooth_sandstone', 'planter-rim')
                put(x, 96, z, 'smooth_sandstone_slab[type=bottom,waterlogged=false]', 'planter-rim')
            else:
                # Drifts follow small clusters, rather than an alternating plant checkerboard.
                patch = (x//3+2*(z//3)+index) % 7
                if inset[x, z] == 1 and patch in (0, 1, 5):
                    put(x, 96, z, 'oak_leaves[distance=7,persistent=true,waterlogged=false]', 'low-evergreen-hedge')
                elif (x*17+z*31) % 5 != 0:
                    flower = flower_types[patch % len(flower_types)]
                    put(x, 96, z, flower, 'flower-drifts')

        tree = bed['tree']
        put(tree['x'], 95, tree['z'], 'dirt', 'stable-tree-soil')
        height = max(11, min(15, tree['height_above_floor']))
        for (dx, y, dz), state in assets.conifer(height, seed=1337+index*71).items():
            if 'leaves' in state and y < 4:
                continue
            put(tree['x']+dx, 96+y, tree['z']+dz, state, 'custom-conifers')
        fixture_records.append({'type': 'conifer', 'x': tree['x'], 'z': tree['z'], 'height': height})
        t = bed['small_topiary']
        put(t['x'], 95, t['z'], 'dirt', 'stable-tree-soil')
        for y in range(4):
            put(t['x'], 96+y, t['z'], 'spruce_log[axis=y]', 'small-topiary')
        for y, radius in ((2, 1), (3, 1), (4, 0)):
            for dx in range(-radius, radius+1):
                for dz in range(-radius, radius+1):
                    if dx*dx+dz*dz <= 2 and (dx or dz or y == 4):
                        put(t['x']+dx, 96+y, t['z']+dz, 'spruce_leaves[distance=7,persistent=true,waterlogged=false]', 'small-topiary')
        fixture_records.append({'type': 'topiary', 'x': t['x'], 'z': t['z'], 'height': 5})

    facing_vectors = {'north': (0, -1), 'east': (1, 0), 'south': (0, 1), 'west': (-1, 0)}
    opposite = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
    for bed, mask in zip(design['beds'], beds):
        b = bed['bench']
        cx, cz = b['center']
        facing = opposite[b['back_faces']]
        dx, dz = facing_vectors[facing]
        # Open a level, three-block seat approach through the planter rim.
        for offset in (-1, 0, 1):
            for step in range(1, 8):
                x, z = cx+dx*step-dz*offset, cz+dz*step+dx*offset
                if (x, z) not in floor:
                    raise ValueError('Bench approach exceeds the plaza')
                for y in (96, 97):
                    if '_log[' in current(x, y, z):
                        raise ValueError('Bench approach intersects a tree')
                    put(x, y, z, 'air', 'bench-access')
                put(x, 95, z, 'smooth_sandstone', 'bench-access')
                bench_aprons.add((x, z))
                if (x, z) not in mask:
                    break
        for (ox, y, oz), state in assets.bench(b['length'], facing).items():
            x, z = cx+ox, cz+oz
            if (x, z) not in floor or (x, z) in protected:
                raise ValueError('Bench exceeds its clear garden bay')
            for yy in (96, 97):
                if '_log[' in current(x, yy, z):
                    raise ValueError('Bench intersects a tree root')
                put(x, yy, z, 'air', 'bench-access')
            put(x, 95, z, 'smooth_sandstone', 'bench-foundation')
            put(x, 96+y, z, state, 'garden-benches')
        fixture_records.append({'type': 'bench', 'x': cx, 'z': cz, 'facing': facing, 'seats': 3})

    lamps = [(v['x'], v['z']) for v in design['lighting']['lamps']]
    for x, z in lamps:
        c = cells.get((x, z), {})
        if (x, z) in protected or c.get('kind') != 'full' or c.get('block_y') != 95:
            raise ValueError('Lamp base intrudes into an approach')
        put(x, 95, z, 'chiseled_stone_bricks', 'lamp-footing')
        for (dx, y, dz), state in assets.lamp(6).items():
            put(x+dx, 96+y, z+dz, state, 'copper-garden-lamps')
        fixture_records.append({'type': 'lamp', 'x': x, 'z': z, 'lantern_y': 100})

    # Leaves use their stable distance to the composed logs, including touching hedges.
    leaf_positions = {p for p, state in desired.items() if '_leaves[' in state}
    logs = {p for p, state in desired.items() if '_log[' in state}
    leaf_dist, pending = {}, deque()
    for x, y, z in logs:
        for dx, dy, dz in N3:
            p = x+dx, y+dy, z+dz
            if p in leaf_positions:
                leaf_dist[p] = 1
                pending.append(p)
    while pending:
        x, y, z = pending.popleft()
        if leaf_dist[x, y, z] >= 6:
            continue
        for dx, dy, dz in N3:
            p = x+dx, y+dy, z+dz
            if p in leaf_positions and p not in leaf_dist:
                leaf_dist[p] = leaf_dist[x, y, z]+1
                pending.append(p)
    for p in leaf_positions:
        material = desired[p].split('[', 1)[0]
        desired[p] = f'{material}[distance={leaf_dist.get(p, 7)},persistent=true,waterlogged=false]'

    # Every floor column with a low obstacle is excluded from the walking network.
    blocked = set()
    for x, z in floor:
        if current(x, 96, z) != AIR or current(x, 97, z) != AIR:
            blocked.add((x, z))
    blocked |= beds_union - bench_aprons
    if blocked & protected:
        raise ValueError(f'Decoration obstructs protected road cells: {sorted(blocked & protected)[:8]}')
    for x, z in blocked:
        if abs(x) <= 6 and (x, z) not in beds_union:
            # Existing outer balustrades are handled by the previous navigation mask.
            if any(groups.get((x, y, z), '') not in ('restored-perimeter-rail', '') for y in (96, 97)):
                raise ValueError('Central sightline/walking axis was obstructed')

    blocks = []
    for p, state in sorted(desired.items()):
        observed = before.state(*p)
        try:
            prior = previous.state(*p)
        except (KeyError, ValueError):
            if p[1] <= 114:
                raise
            prior = AIR
        if observed != prior:
            raise ValueError(f'Unexpected manual edit preserved at {p}')
        if state != observed:
            blocks.append(dict(zip(('x', 'y', 'z'), p)) | {'block': state, 'expected': observed, 'group': groups[p]})
    walk = [{'x': x, 'z': z, 'standing_y': 96} for x, z in sorted(floor-blocked)]
    meta = {'scope': before.scope, 'district': '01', 'changed_blocks': len(blocks), 'planters': len(beds),
            'planter_columns': len(beds_union), 'trees': 6, 'topiary': 6, 'benches': 6, 'new_lamps': len(lamps),
            'old_lamps_replaced': len(old_lamps), 'logo_blocks': len(logo_mask), 'walk_samples': len(walk),
            'unwalkable_columns': sorted(blocked), 'bench_access_columns': sorted(bench_aprons),
            'fixtures': fixture_records, 'by_material': dict(Counter(b['block'] for b in blocks)),
            'by_group': dict(Counter(b['group'] for b in blocks)), 'source': 'Observed after-foundation baseline; approved reference sheets 03 and 11'}
    return {'version': 1, 'scope': before.scope, 'blocks': blocks}, meta, {'scope': before.scope, 'points': walk}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, default=ROOT/'.runtime/plaza-stage03/design-final.json')
    parser.add_argument('--before', type=Path, default=ROOT/'.runtime/plaza-stage03/before.json.gz')
    parser.add_argument('--output', type=Path, default=ROOT/'.runtime/plaza-stage03/plaza.json')
    parser.add_argument('--logo', type=Path, default=Path('/home/emil/Desktop/Shacraft-Lobby-References/brand/logo-180.png'))
    args = parser.parse_args()
    before = survey.load_snapshot(args.before)
    previous = survey.load_snapshot(ROOT/'.runtime/foundations-stage02/after.json.gz')
    design = json.loads(args.design.read_text())
    plan, meta, walk = compile_plan(design, before, previous, args.logo)
    meta['source_logo_sha256'] = hashlib.sha256(args.logo.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(plan, separators=(',', ':'))+'\n')
    args.output.with_suffix('.metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
    args.output.with_suffix('.walk.json').write_text(json.dumps(walk, separators=(',', ':'))+'\n')
    print(json.dumps({k: v for k, v in meta.items() if k not in ('unwalkable_columns', 'bench_access_columns', 'fixtures', 'by_material')}))


if __name__ == '__main__':
    main()
