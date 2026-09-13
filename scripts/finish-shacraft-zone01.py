#!/usr/bin/env python3
"""Compile small arrival details and a separately reversible invisible enclosure.

Reads observed states only; apply the two recipes through scripts/layout.py.
The normal-player boundary has a full floor, side membrane and transparent roof.
Existing full stone cells can form the membrane; partial collision shapes cannot.
"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / '.runtime/zone01-stage05'
AIR = 'minecraft:air'
BARRIER = 'minecraft:barrier[waterlogged=false]'
N = ((1, 0), (-1, 0), (0, 1), (0, -1))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


survey = module('zone01_survey', ROOT / 'scripts/foundation-survey.py')
geometry = module('zone01_geometry', ROOT / 'scripts/foundation-study/geometry.py')
FULL = survey.FULL | {'waxed_oxidized_cut_copper', 'barrier'}


def full(state):
    return state.split('[')[0].removeprefix('minecraft:') in FULL


def compile_plans(before):
    design = json.loads((ROOT / '.runtime/plaza-stage03/design-final.json').read_text())
    geo = json.loads((ROOT / '.runtime/foundations-stage02/foundations-final.geometry.json').read_text())
    rails = json.loads((ROOT / '.runtime/balustrade-stage04/balustrade-final.metadata.json').read_text())
    outer = geometry.polygon_cells(design['outer_hex'])
    roads = {tuple(p) for r in geo['routes'] for p in r['clear_cells']}
    details, groups = {}, {}

    def decorate(x, y, z, state, group):
        at = x, y, z
        old = before.state(*at)
        if y >= 96 and (old != AIR or (x, z) in roads):
            raise ValueError(f'Furniture touches existing decoration or an approach at {at}')
        if y == 95 and not full(old):
            raise ValueError(f'Inlay would change a stair or unsupported floor at {at}')
        details[at] = 'minecraft:'+state
        groups[at] = group

    urns = [(-10, 35), (10, 35)]
    for cx, cz in urns:
        decorate(cx, 96, cz, 'cut_sandstone', 'urn-pedestals')
        for dx, dz in N:
            decorate(cx+dx, 96, cz+dz, 'smooth_sandstone_slab[type=bottom,waterlogged=false]', 'urn-plinths')
        for dx in range(-1, 2):
            for dz in range(-1, 2):
                if dx == dz == 0:
                    bowl = 'dirt'
                elif dx and dz:
                    bowl = 'cut_sandstone'
                else:
                    facing = 'east' if dx == 1 else 'west' if dx == -1 else 'south' if dz == 1 else 'north'
                    bowl = f'smooth_sandstone_stairs[facing={facing},half=bottom,shape=straight,waterlogged=false]'
                decorate(cx+dx, 97, cz+dz, bowl, 'urn-bowls')
        decorate(cx, 98, cz, 'white_tulip', 'urn-flowers')
    # A low freestanding enamel nameboard; its text display is a separate receipt.
    decorate(-8, 96, 43, 'cut_sandstone', 'welcome-pedestal')
    for x in range(-9, -6):
        decorate(x, 97, 43, 'green_concrete', 'welcome-nameboard')
        decorate(x, 98, 43, 'waxed_oxidized_cut_copper_slab[type=bottom,waterlogged=false]', 'welcome-coping')
    thresholds = {
        'north': [(x, z) for x in range(-4, 5) for z in (-31, -30)],
        'south': [(x, z) for x in range(-4, 5) for z in (50, 51)],
        'east': [(x, z) for x in (38, 39) for z in range(13, 20)],
        'west': [(x, z) for x in (-40, -39) for z in range(16, 21)],
        'northwest': [(x, z) for x in range(-36, -31) for z in range(-16, -9)
                      if (x, z) in roads and x-z in (-21, -20)],
    }
    for name, columns in thresholds.items():
        for x, z in columns:
            decorate(x, 95, z, 'smooth_stone', 'flush-threshold-'+name)
        # Restrained green/brass corner accents stay at the exact paving height.
        for x, z in (min(columns), max(columns)):
            decorate(x, 95, z, 'waxed_oxidized_cut_copper', 'threshold-copper-insets')

    # Solid joint piers stop a partial-shaped road rail from carrying a folded
    # membrane through a whole garden-side balustrade and its connected plants.
    for x, z in ((-42, 22), (41, 11), (42, 20)):
        at = x, 96, z
        if not before.state(*at).startswith('minecraft:stone_brick_wall['):
            raise ValueError(f'Joint pier baseline changed at {at}')
        details[at], groups[at] = 'minecraft:cut_sandstone', 'finished-road-joint-piers'

    # Allow the complete plaza, its balustrade and short level approach aprons.
    near = {(x+dx, z+dz) for x, z in outer for dx in range(-2, 3) for dz in range(-2, 3)}
    interior = outer | {tuple(p) for p in rails['fence_columns']}
    interior |= {(c['x'], c['z']) for c in geo['cells'] if c['kind'] == 'full' and c['block_y'] == 95
                 and (c['x'], c['z']) in near}
    # Fold the six-face membrane inward around partial collision shapes instead
    # of replacing visible rails, stair treads, plants or fixture overhangs.
    n6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
    original_volume = {(x, y, z) for x, z in interior for y in range(96, 116)}
    volume = set(original_volume)
    cache = {}
    def observed(p):
        if p not in cache:
            cache[p] = details.get(p, before.state(*p))
        return cache[p]
    for _ in range(128):
        membrane = {(x+dx, y+dy, z+dz) for x, y, z in volume for dx, dy, dz in n6} - volume
        partial = {p for p in membrane if observed(p) != AIR and not full(observed(p))}
        if not partial:
            break
        remove = {(x+dx, y+dy, z+dz) for x, y, z in partial for dx, dy, dz in n6} & volume
        if not remove:
            raise ValueError('Partial-shape boundary cannot be sealed without editing decoration')
        volume -= remove
    else:
        raise ValueError('Boundary folding did not converge')
    if (0, 96, 43) not in volume:
        raise ValueError('Spawn is outside the finished enclosure')
    shell = {(x, z) for x, y, z in membrane if 96 <= y < 116}
    floor = {p for p in membrane if p[1] == 95}
    roof = {p for p in membrane if p[1] == 116}
    walls = membrane - floor - roof
    barriers, barrier_groups = {}, {}
    for group, positions in [('invisible-side-wall', walls), ('invisible-floor-gap', floor), ('invisible-roof', roof)]:
        for at in sorted(positions):
            state = details.get(at, before.state(*at))
            if full(state):
                continue
            if state != AIR:
                raise ValueError(f'Enclosure would erase a visible/partial block at {at}: {state}')
            barriers[at], barrier_groups[at] = BARRIER, group
    if details.keys() & barriers.keys():
        raise ValueError('Decoration and containment recipes overlap')
    def recipe(states, labels):
        return {'version': 1, 'scope': before.scope, 'blocks': [dict(zip(('x', 'y', 'z'), p)) |
            {'block': state, 'expected': before.state(*p), 'group': labels[p]}
            for p, state in sorted(states.items()) if state != before.state(*p)]}
    finish, envelope = recipe(details, groups), recipe(barriers, barrier_groups)
    combined = {'version': 1, 'scope': before.scope, 'blocks': finish['blocks']+envelope['blocks']}
    metadata = {'version': 1, 'scope': before.scope, 'interior_columns': sorted(interior),
                'shell_columns': sorted(shell), 'floor_y': 95, 'roof_y': 116,
                'source': {'x': .5, 'y': 96, 'z': 43.5},
                'interior_excluded_voxels': sorted(original_volume-volume),
                'decoration': {'urn_centers': urns, 'welcome_plinth': [-8, 43], 'thresholds': thresholds},
                'barrier_groups': dict(Counter(b['group'] for b in envelope['blocks'])),
                'detail_groups': dict(Counter(b['group'] for b in finish['blocks'])),
                'scope_note': 'Static collision enclosure for normal players; spectator and operator teleport/break commands bypass it.'}
    return finish, envelope, combined, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, default=STAGE / 'before.json.gz')
    parser.add_argument('--output-dir', type=Path, default=STAGE)
    args = parser.parse_args()
    result = compile_plans(survey.load_snapshot(args.before))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in zip(('finishing.json', 'barriers.json', 'combined.json', 'zone-boundary.metadata.json'), result):
        (args.output_dir/name).write_text(json.dumps(value, separators=(',', ':'))+'\n')
    print(json.dumps({'details': len(result[0]['blocks']), 'barriers': len(result[1]['blocks']),
                      'interior_columns': len(result[3]['interior_columns']), 'shell_columns': len(result[3]['shell_columns']),
                      'groups': result[3]['barrier_groups']}))


if __name__ == '__main__':
    main()
