#!/usr/bin/env python3
"""Compile a continuous, checked arrival-square balustrade; never edit the world.

The existing polygon is followed exactly. Cardinal elbows close diagonal gaps;
garden-side elbows move outward and receive observed, grounded stone footings.
Every road clear cell, planted block and existing light remains protected.
"""
import argparse
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / '.runtime/balustrade-stage04'
AIR = 'minecraft:air'
N = {'east': (1, 0), 'north': (0, -1), 'south': (0, 1), 'west': (-1, 0)}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


survey = module('balustrade_survey', ROOT / 'scripts/foundation-survey.py')
geometry = module('balustrade_geometry', ROOT / 'scripts/foundation-study/geometry.py')


def compile_plan(before):
    design = json.loads((ROOT / '.runtime/plaza-stage03/design-final.json').read_text())
    geo = json.loads((ROOT / '.runtime/foundations-stage02/foundations-final.geometry.json').read_text())
    cells = {(c['x'], c['z']): c for c in geo['cells']}
    roads = {tuple(p) for r in geo['routes'] for p in r['clear_cells']}
    outer = geometry.polygon_cells(design['outer_hex'])
    edge = {p for p in outer if any((p[0]+dx, p[1]+dz) not in outer for dx, dz in N.values())}
    gardens = set()
    for bed in design['beds']:
        gardens |= geometry.polygon_cells(bed['outline'])
        gardens |= {tuple(p) for p in bed.get('additional_planting_columns', [])}
    ordered = sorted(edge, key=lambda p: math.atan2(p[1]-9, p[0]))
    chain, elbows = [], []
    for a, b in zip(ordered, ordered[1:]+ordered[:1]):
        chain.append(a)
        dx, dz = b[0]-a[0], b[1]-a[1]
        if max(abs(dx), abs(dz)) > 1:
            raise ValueError('Boundary order contains a nonadjacent jump')
        if dx and dz:
            candidates = [(a[0], b[1]), (b[0], a[1])]
            def score(p):
                state = before.state(p[0], 96, p[1])
                return (p in edge or p in chain, p in gardens or state != AIR, p not in outer, p)
            # An opening remains open even when its diagonal connector lies in it.
            p = min(candidates, key=score)
            chain.append(p)
            elbows.append(p)
    if len(set(chain)) != len(chain):
        raise ValueError('Cardinal perimeter is not a simple cycle')
    selected = {p for p in chain if p not in roads}
    for p in selected:
        state = before.state(p[0], 96, p[1])
        if state != AIR and not ('stone_brick_wall[' in state or
                (p in edge and state == 'minecraft:smooth_sandstone_slab[type=bottom,waterlogged=false]')):
            raise ValueError(f'Protected decoration intersects fence at {p}: {state}')
        if before.state(p[0], 97, p[1]) != AIR:
            raise ValueError(f'Protected decoration intersects handrail at {p}')
    # Rotate at an opening, then split into uninterrupted fence runs.
    cut = next(i for i, p in enumerate(chain) if p not in selected)
    linear = chain[cut:]+chain[:cut]
    runs, run = [], []
    for p in linear:
        if p in selected:
            run.append(p)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    piers = set()
    for run in runs:
        segments = max(1, round((len(run)-1)/8))
        piers |= {run[round(i*(len(run)-1)/segments)] for i in range(segments+1)}
        piers |= {tuple(p) for p in design['outer_hex'] if tuple(p) in run}
    desired, groups, footing_columns, replaced_rims = {}, {}, [], []
    def put(x, y, z, state, group):
        if (x, z) in roads:
            raise ValueError(f'Protected road cell at {(x, z)}')
        before.state(x, y, z)
        desired[x, y, z] = 'minecraft:'+state
        groups[x, y, z] = group
    for x, z in sorted(selected):
        if (x, z) not in outer:
            # Stop at an observed full support; never assume air or bury plants.
            y = 95
            while before.state(x, y, z) == AIR:
                y -= 1
            support = before.state(x, y, z).split('[')[0].removeprefix('minecraft:')
            if support not in survey.FULL or y > 95:
                raise ValueError(f'No simple observed footing at {(x, y, z)}')
            if y < 95:
                footing_columns.append({'x': x, 'z': z, 'support_y': y})
                if support == 'grass_block':
                    put(x, y, z, 'dirt', 'stable-buried-footing-soil')
                for yy in range(y+1, 96):
                    put(x, yy, z, 'cut_sandstone' if yy == 95 else 'stone_bricks', 'grounded-elbow-footing')
        if before.state(x, 96, z).startswith('minecraft:smooth_sandstone_slab'):
            replaced_rims.append([x, z])
        if (x, z) in piers:
            state = 'cut_sandstone'
        else:
            connected = {}
            for name, (dx, dz) in N.items():
                neighbor = before.state(x+dx, 96, z+dz).split('[')[0].removeprefix('minecraft:')
                connected[name] = (x+dx, z+dz) in selected or neighbor.endswith('_wall') or neighbor in survey.FULL
            straight = (connected['east'] and connected['west'] and not connected['north'] and not connected['south']) or (connected['north'] and connected['south'] and not connected['east'] and not connected['west'])
            props = {name: 'tall' if value else 'none' for name, value in connected.items()}
            props |= {'up': 'false' if straight else 'true', 'waterlogged': 'false'}
            state = 'stone_brick_wall['+','.join(f'{k}={v}' for k, v in sorted(props.items()))+']'
        put(x, 96, z, state, 'sandstone-piers' if (x, z) in piers else 'connected-stone-balusters')
        put(x, 97, z, 'smooth_sandstone_slab[type=bottom,waterlogged=false]', 'continuous-cream-handrail')
    # Old uncapped road rails need reciprocal arms where the new fence joins them.
    adjacent = {(x+dx, z+dz) for x, z in selected for dx, dz in N.values()} - selected
    neighboring_rails = {p for p in adjacent if before.state(p[0], 96, p[1]).startswith('minecraft:stone_brick_wall[')}
    for x, z in sorted(neighboring_rails):
        if before.state(x, 97, z) != AIR:
            raise ValueError('Neighboring rail has an unsupported cap configuration')
        links = {}
        for name, (dx, dz) in N.items():
            p = x+dx, 96, z+dz
            neighbor = desired.get(p, before.state(*p)).split('[')[0].removeprefix('minecraft:')
            links[name] = neighbor.endswith('_wall') or neighbor in survey.FULL
        straight = (links['east'] and links['west'] and not links['north'] and not links['south']) or (links['north'] and links['south'] and not links['east'] and not links['west'])
        props = {name: 'low' if linked else 'none' for name, linked in links.items()}
        props |= {'up': 'false' if straight else 'true', 'waterlogged': 'false'}
        put(x, 96, z, 'stone_brick_wall['+','.join(f'{k}={v}' for k, v in sorted(props.items()))+']', 'reciprocal-road-rail-joins')
    blocks = [dict(zip(('x', 'y', 'z'), p)) | {'block': state, 'expected': before.state(*p), 'group': groups[p]}
              for p, state in sorted(desired.items()) if state != before.state(*p)]
    meta = {'version': 1, 'scope': before.scope, 'floor_y': 95, 'handrail_top_y': 97.5,
            'fence_columns': sorted(selected), 'pier_columns': sorted(piers), 'path_runs': runs,
            'elbow_columns': sorted(set(elbows) & selected), 'footing_columns': footing_columns,
            'neighboring_rail_columns': sorted(neighboring_rails),
            'replaced_planter_rims': replaced_rims, 'protected_road_columns': sorted(roads),
            'by_group': dict(Counter(b['group'] for b in blocks)), 'changed_blocks': len(blocks)}
    # Reuse the independent garden and inherited-route auditor with the new obstacle mask.
    garden_meta = json.loads((ROOT / '.runtime/plaza-stage03/plaza-polished.metadata.json').read_text())
    garden_meta['unwalkable_columns'] = sorted({tuple(p) for p in garden_meta['unwalkable_columns']} | selected)
    walk = json.loads((ROOT / '.runtime/plaza-stage03/plaza-polished.walk.json').read_text())
    walk['points'] = [p for p in walk['points'] if (p['x'], p['z']) not in selected]
    garden_meta['walk_samples'] = len(walk['points'])
    return {'version': 1, 'scope': before.scope, 'blocks': blocks}, meta, garden_meta, walk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, default=STAGE / 'before-full.json.gz')
    parser.add_argument('--output', type=Path, default=STAGE / 'balustrade.json')
    args = parser.parse_args()
    before = survey.load_snapshot(args.before)
    plan, meta, garden_meta, walk = compile_plan(before)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for suffix, document in (('.json', plan), ('.metadata.json', meta), ('.garden-metadata.json', garden_meta), ('.walk.json', walk)):
        args.output.with_suffix(suffix).write_text(json.dumps(document, separators=(',', ':'))+'\n')
    print(json.dumps({k: meta[k] for k in ('changed_blocks', 'by_group', 'replaced_planter_rims')}
                     | {'fence_columns': len(meta['fence_columns']), 'piers': len(meta['pier_columns']),
                        'runs': [len(r) for r in meta['path_runs']], 'footings': len(meta['footing_columns'])}))


if __name__ == '__main__':
    main()
