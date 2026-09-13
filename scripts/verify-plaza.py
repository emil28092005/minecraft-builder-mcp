#!/usr/bin/env python3
"""Read-only candidate/live QA for the composed Shacraft arrival gardens.

Candidate mode overlays desired states on the observed baseline. Live mode uses
an observed after snapshot and compares every planned state exactly. The checks
cover this toolkit's static single flowers, persistent leaves, rooted log trees,
supported lanterns and supplied walking surfaces, not arbitrary Minecraft physics.
"""
import argparse
from collections import Counter, deque
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


survey = module('plaza_qa_survey', ROOT / 'scripts/foundation-survey.py')
navigation = module('plaza_qa_navigation', ROOT / 'scripts/foundation-study/verify_geometry.py')
FLOWERS = {'allium', 'oxeye_daisy', 'azure_bluet', 'pink_tulip', 'white_tulip'}
SOIL = {'dirt', 'grass_block'}
STATIC_CUBES = survey.FULL | {'waxed_oxidized_cut_copper'}
N3 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def parse(state):
    name, _, raw = state.removeprefix('minecraft:').partition('[')
    props = dict(part.split('=', 1) for part in raw.rstrip(']').split(',') if '=' in part)
    return name, props


class Reader:
    def __init__(self, snapshot, overlay=None):
        self.snapshot, self.scope = snapshot, snapshot.scope
        self.overlay, self.cache = overlay or {}, {}

    def state(self, x, y, z):
        key = (x, y, z)
        if key not in self.cache:
            self.cache[key] = self.overlay[key] if key in self.overlay else self.snapshot.state(x, y, z)
        return self.cache[key]


def supported_center(state, face):
    """Conservative face support for full cubes and simple dry shapes used here."""
    name, props = parse(state)
    if props.get('waterlogged') == 'true':
        return False
    if name in STATIC_CUBES:
        return True
    if name.endswith('_slab'):
        return props.get('type') == 'double' or props.get('type') == ('bottom' if face == 'down' else 'top')
    if name.endswith('_stairs'):
        return props.get('half') == ('bottom' if face == 'down' else 'top')
    if name == 'iron_chain':
        return props.get('axis') == 'y'
    if name in ('spruce_fence', 'iron_bars'):
        return True
    if name == 'stone_brick_wall':
        return props.get('up') == 'true'
    return False


def leaf_distance(reader, start):
    """Shortest face-connected path from a leaf to a log, capped at seven.

    Read actual adjacent states, including unchanged leaves/logs, rather than
    trusting the compiler's desired-only propagation or saved distance values.
    """
    pending, seen = deque([(start, 0)]), {start}
    while pending:
        (x, y, z), distance = pending.popleft()
        if distance >= 6:
            continue
        for dx, dy, dz in N3:
            neighbor = x + dx, y + dy, z + dz
            name, _ = parse(reader.state(*neighbor))
            if name.endswith('_log'):
                return distance + 1
            if name.endswith('_leaves') and neighbor not in seen:
                seen.add(neighbor)
                pending.append((neighbor, distance + 1))
    return 7


def check_fixtures(reader, desired, metadata):
    failures, counts = [], Counter()
    for at, planned in desired.items():
        name, _ = parse(planned)
        if name not in FLOWERS and name != 'lantern' and not name.endswith('_leaves'):
            continue
        x, y, z = at
        state = reader.state(*at)
        actual_name, props = parse(state)
        if actual_name != name:
            failures.append({'at': list(at), 'reason': 'fixture_material_differs', 'planned': planned, 'actual': state})
            continue
        if name in FLOWERS:
            counts['flowers'] += 1
            below = reader.state(x, y - 1, z)
            if parse(below)[0] not in SOIL:
                failures.append({'at': list(at), 'reason': 'flower_without_valid_soil', 'below': below})
        elif name == 'lantern':
            counts['lanterns'] += 1
            hanging = props.get('hanging') == 'true'
            support = reader.state(x, y + (1 if hanging else -1), z)
            if props.get('waterlogged') != 'false' or not supported_center(support, 'down' if hanging else 'up'):
                failures.append({'at': list(at), 'reason': 'lantern_without_dry_center_support', 'support': support})
        else:
            counts['leaves'] += 1
            expected_distance = leaf_distance(reader, at)
            if (props.get('persistent') != 'true' or props.get('waterlogged') != 'false'
                    or props.get('distance') != str(expected_distance)):
                failures.append({'at': list(at), 'reason': 'unstable_or_wrong_leaf_state',
                                 'actual': state, 'expected_distance': expected_distance})
    roots = set()
    for fixture in metadata['fixtures']:
        if fixture['type'] not in ('conifer', 'topiary'):
            continue
        counts['rooted_trees'] += 1
        x, z = fixture['x'], fixture['z']
        root = (x, 96, z)
        roots.add(root)
        root_name, root_props = parse(reader.state(*root))
        below = reader.state(x, 95, z)
        if not root_name.endswith('_log') or root_props.get('axis') != 'y' or parse(below)[0] not in SOIL:
            failures.append({'at': list(root), 'reason': 'tree_root_without_vertical_log_and_soil', 'below': below})
        elif parse(below)[0] == 'grass_block':
            failures.append({'at': [x, 95, z], 'reason': 'grass_under_opaque_trunk_will_decay_to_dirt'})
        trunk = sorted(p[1] for p, state in desired.items() if p[0] == x and p[2] == z and parse(state)[0].endswith('_log'))
        if not trunk or trunk != list(range(96, max(trunk) + 1)):
            failures.append({'at': list(root), 'reason': 'discontinuous_planned_trunk', 'log_y': trunk})
        else:
            for y in trunk:
                material, props = parse(reader.state(x, y, z))
                if not material.endswith('_log') or props.get('axis') != 'y':
                    failures.append({'at': [x, y, z], 'reason': 'trunk_gap_or_wrong_axis'})
    log_positions = {p for p, s in desired.items() if parse(s)[0].endswith('_log')}
    pending, connected = deque(roots & log_positions), roots & log_positions
    while pending:
        x, y, z = pending.popleft()
        for dx, dy, dz in N3:
            p = x + dx, y + dy, z + dz
            if p in log_positions and p not in connected:
                pending.append(p)
                connected.add(p)
    if log_positions - connected:
        failures.append({'reason': 'logs_disconnected_from_declared_tree_roots', 'positions': [list(p) for p in sorted(log_positions - connected)[:20]]})
    counts['root_connected_logs'] = len(connected)
    return {'passed': not failures, 'checked': dict(counts), 'failures': failures}


def audit(before, layout, metadata, walk, base_navigation, after=None):
    scope = survey.scope_of(layout['scope'])
    if any(value != scope for value in (before.scope, metadata['scope'], walk['scope'])) or (after and after.scope != scope):
        raise ValueError('Project/world/epoch differs between QA inputs')
    desired, mismatches = {}, []
    for block in layout['blocks']:
        pos = survey.point(block)
        at = tuple(pos[a] for a in ('x', 'y', 'z'))
        if at in desired:
            raise ValueError('Duplicate desired coordinate')
        if before.state(*at) != block['expected']:
            raise ValueError(f'Plan expected state differs from baseline at {at}')
        desired[at] = block['block']
        if after and after.state(*at) != block['block']:
            mismatches.append({'at': list(at), 'expected': block['block'], 'actual': after.state(*at)})
    reader = Reader(after or before, None if after else desired)
    fixtures = check_fixtures(reader, desired, metadata)
    walking = survey.verify_walkable(reader, walk['points'])
    nav = json.loads(json.dumps(base_navigation))
    blocked = {tuple(p) for p in metadata['unwalkable_columns']}
    if any((p['x'], p['z']) in blocked for p in walk['points']):
        raise ValueError('Walking samples include declared unwalkable ground')
    excluded = 0
    for cell in nav['cells']:
        if cell['clear'] and (cell['x'], cell['z']) in blocked:
            cell['clear'] = False
            excluded += 1
    navigation_result = navigation.audit(nav)
    navigation_result['decorated_ground_columns_excluded'] = excluded
    nav_cells = navigation.normalize_cells(nav)
    graph = navigation.surface_graph(nav_cells)
    reached = navigation.reachable(graph, (0, 9))
    bench_access = []
    vectors = {'north': (0, -1), 'south': (0, 1), 'west': (-1, 0), 'east': (1, 0)}
    for fixture in metadata['fixtures']:
        if fixture['type'] != 'bench':
            continue
        dx, dz = vectors[fixture['facing']]
        for offset in (-1, 0, 1):
            point = fixture['x'] + dx - dz * offset, fixture['z'] + dz + dx * offset
            bench_access.append(navigation.endpoint_report(
                f"bench-{fixture['x']}-{fixture['z']}-front-{offset}", point, graph, reached))
    navigation_result['bench_front_access'] = bench_access
    navigation_result['passed'] &= all(point['passed'] for point in bench_access)
    # A canopy stays traversable when it does not occupy the 1.8-block body space.
    # Only explicit low obstacles are removed; overhead leaves do not mask paths.
    return {'version': 1, 'mode': 'actual_after_snapshot' if after else 'candidate_overlay', 'scope': scope,
            'world_edits': 0, 'desired_blocks': len(desired), 'baseline_expected_states_verified': len(desired),
            'actual_exact_state_mismatches': len(mismatches) if after else None,
            'actual_mismatch_examples': mismatches[:30], 'fixtures': fixtures, 'walking': walking,
            'navigation': navigation_result,
            'passed': not mismatches and fixtures['passed'] and walking['passed'] and navigation_result['passed'],
            'note': 'Static support, leaf-distance and point-sampled navigation checks; not a complete moving-player collision simulation. Actual mode uses sequential observed snapshots.'}


def render_map(document, metadata, report, path, boundary_columns=None, boundary_note=None):
    """Render actual captured surface cells with semantic material colors."""
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgb
    from matplotlib.collections import LineCollection

    if document.get('source') != 'paper_world_surface' or document.get('world_uuid') != metadata['scope']['world_id']:
        raise ValueError('Rendering requires an actual Paper map of this project world')
    semantic = {'minecraft:smooth_sandstone': '#e8ddbd', 'minecraft:cut_sandstone': '#d5c7a5',
                'minecraft:smooth_sandstone_slab': '#e8ddbd', 'minecraft:grass_block': '#87a75f',
                'minecraft:oak_leaves': '#78924d', 'minecraft:spruce_leaves': '#3e6851',
                'minecraft:spruce_log': '#765637', 'minecraft:green_concrete': '#548338',
                'minecraft:spruce_fence': '#7b5839', 'minecraft:spruce_stairs': '#967147',
                'minecraft:allium': '#b388ce', 'minecraft:oxeye_daisy': '#faf3d6',
                'minecraft:azure_bluet': '#f2f0db', 'minecraft:pink_tulip': '#efa8b7',
                'minecraft:white_tulip': '#f7f3e6', 'minecraft:lantern': '#ecc565'}
    palette = []
    for name, fallback in zip(document['palette'], document['palette_rgb']):
        color = '#68a494' if 'waxed_oxidized_cut_copper' in name else semantic.get(name, fallback)
        palette.append(to_rgb(color))
    heights = np.asarray(document['surface_y'], dtype=float).reshape(document['length'], document['width'])
    indices = np.asarray(document['material_index']).reshape(heights.shape)
    rgb = np.asarray(palette)[indices]
    dz, dx = np.gradient(heights)
    shade = np.clip(.79 + .26 * (.55 * dx + .55 * dz + .63) / np.sqrt(1 + dx * dx + dz * dz), .64, 1.06)
    for index, name in enumerate(document['palette']):
        if name.removeprefix('minecraft:') in FLOWERS or name.endswith('_concrete'):
            shade[indices == index] = 1
    rgb = np.clip(rgb * shade[:, :, None], 0, 1)
    fig, ax = plt.subplots(figsize=(11, 12), facecolor='#f3f0e6')
    ax.imshow(rgb, interpolation='nearest', origin='upper',
              extent=(document['min_x'], document['max_x'] + 1, document['max_z'] + 1, document['min_z']))
    if boundary_columns:
        boundary = set(map(tuple, boundary_columns))
        segments = [[(x + .5, z + .5), (x + dx + .5, z + dz + .5)]
                    for x, z in boundary for dx, dz in ((1, 0), (0, 1)) if (x + dx, z + dz) in boundary]
        ax.add_collection(LineCollection(segments, colors='#a74640', linewidths=1, alpha=.85, zorder=5))
        ax.scatter([x + .5 for x, z in boundary], [z + .5 for x, z in boundary],
                   s=2, color='#a74640', alpha=.85, zorder=5, label='Invisible wall · observed barrier blocks')
        ax.legend(loc='upper left', fontsize=8, facecolor='#faf7ed', framealpha=.94, edgecolor='#bcbfac')
    ax.set(xlim=(-52, 53), ylim=(67, -47), xlabel='X · east →', ylabel='Z (positive south)')
    ax.set_aspect('equal')
    ax.tick_params(colors='#596451', labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('#9ca28d')
    ax.annotate('N', xy=(47, -44), xytext=(47, -35), ha='center', va='center',
                fontsize=11, weight='bold', color='#254534', arrowprops=dict(arrowstyle='-|>', color='#254534'))
    ax.plot([-47, -37], [62, 62], color='#254534', lw=2)
    ax.text(-42, 60, '10 blocks', ha='center', fontsize=8, color='#254534',
            bbox=dict(fc='#faf7ed', ec='none', pad=2, alpha=.9))
    fig.suptitle('SHACRAFT  /  ARRIVAL GARDEN 01', x=.5, y=.975, fontsize=17, weight='bold', color='#244732')
    fig.text(.5, .945, 'Captured server surface · original brand inlay · planted gardens',
             ha='center', fontsize=10, color='#586751')
    fig.text(.5, .035, f"{metadata['planters']} garden beds · {metadata['trees']} conifers · {metadata['benches']} benches · {metadata['new_lamps']} copper-capped lamps\n"
             'Observed block positions and materials · semantic colors and height shading.'
             + ('\n' + boundary_note if boundary_note else ''),
             ha='center', fontsize=9, color='#586751', linespacing=1.7)
    fig.subplots_adjust(left=.09, right=.97, top=.917, bottom=.135 if boundary_note else .105)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)


class FakeSnapshot:
    scope = {'project_id': 'test', 'world_id': 'world', 'world_epoch': 'epoch'}

    def __init__(self, states):
        self.states = states

    def state(self, x, y, z):
        return self.states.get((x, y, z), 'minecraft:air')


class PlazaQATests(unittest.TestCase):
    def test_flower_soil_and_hanging_lantern_support(self):
        desired = {(0, 96, 0): 'minecraft:white_tulip',
                   (2, 100, 0): 'minecraft:lantern[hanging=true,waterlogged=false]'}
        states = {**desired, (0, 95, 0): 'minecraft:grass_block[snowy=false]', (2, 101, 0): 'minecraft:waxed_oxidized_cut_copper'}
        result = check_fixtures(Reader(FakeSnapshot(states)), desired, {'fixtures': []})
        self.assertTrue(result['passed'])
        del states[(2, 101, 0)]
        states[(0, 95, 0)] = 'minecraft:smooth_sandstone'
        result = check_fixtures(Reader(FakeSnapshot(states)), desired, {'fixtures': []})
        self.assertEqual({f['reason'] for f in result['failures']}, {'flower_without_valid_soil', 'lantern_without_dry_center_support'})

    def test_leaf_distance_uses_unchanged_neighbors_and_requires_persistence(self):
        leaf = 'minecraft:spruce_leaves[distance=2,persistent=true,waterlogged=false]'
        desired = {(0, 100, 0): leaf}
        states = {**desired, (1, 100, 0): 'minecraft:oak_leaves[distance=1,persistent=true,waterlogged=false]',
                  (2, 100, 0): 'minecraft:spruce_log[axis=y]'}
        result = check_fixtures(Reader(FakeSnapshot(states)), desired, {'fixtures': []})
        self.assertTrue(result['passed'])
        states[(0, 100, 0)] = leaf.replace('persistent=true', 'persistent=false')
        self.assertFalse(check_fixtures(Reader(FakeSnapshot(states)), desired, {'fixtures': []})['passed'])

    def test_disconnected_tree_trunk_is_rejected(self):
        desired = {(0, 96, 0): 'minecraft:spruce_log[axis=y]', (0, 98, 0): 'minecraft:spruce_log[axis=y]'}
        states = {**desired, (0, 95, 0): 'minecraft:dirt'}
        result = check_fixtures(Reader(FakeSnapshot(states)), desired, {'fixtures': [{'type': 'conifer', 'x': 0, 'z': 0}]})
        self.assertFalse(result['passed'])
        self.assertIn('discontinuous_planned_trunk', {f['reason'] for f in result['failures']})

    def test_grass_under_opaque_root_is_unstable_but_dirt_is_valid(self):
        desired = {(0, 96, 0): 'minecraft:spruce_log[axis=y]'}
        states = {**desired, (0, 95, 0): 'minecraft:grass_block[snowy=false]'}
        metadata = {'fixtures': [{'type': 'conifer', 'x': 0, 'z': 0}]}
        result = check_fixtures(Reader(FakeSnapshot(states)), desired, metadata)
        self.assertEqual(result['failures'][0]['reason'], 'grass_under_opaque_trunk_will_decay_to_dirt')
        states[(0, 95, 0)] = 'minecraft:dirt'
        self.assertTrue(check_fixtures(Reader(FakeSnapshot(states)), desired, metadata)['passed'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stage = ROOT / '.runtime/plaza-stage03'
    parser.add_argument('--before', type=Path, default=stage / 'before.json.gz')
    parser.add_argument('--after', type=Path)
    parser.add_argument('--layout', type=Path, default=stage / 'plaza.json')
    parser.add_argument('--metadata', type=Path, default=stage / 'plaza.metadata.json')
    parser.add_argument('--walk', type=Path, default=stage / 'plaza.walk.json')
    parser.add_argument('--navigation', type=Path, default=ROOT / '.runtime/foundations-stage02/navigation-verified-walkable-input.json')
    parser.add_argument('--report', type=Path, default=stage / 'candidate-qa.json')
    parser.add_argument('--map', type=Path, help='Actual after surface map, used only with --png and --after')
    parser.add_argument('--png', type=Path, help='Focused map of the captured arrival garden')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(PlazaQATests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    layout, metadata, walk, nav = [json.loads(p.read_text()) for p in (args.layout, args.metadata, args.walk, args.navigation)]
    before = survey.load_snapshot(args.before, layout['scope'])
    after = survey.load_snapshot(args.after, layout['scope']) if args.after else None
    report = audit(before, layout, metadata, walk, nav, after)
    paths = {'before': args.before, 'layout': args.layout, 'metadata': args.metadata, 'walk': args.walk, 'navigation': args.navigation}
    if args.after:
        paths['after'] = args.after
    report['input_sha256'] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    survey.terrain.save(args.report, report)
    if args.png:
        if not args.map or not args.after:
            parser.error('--png requires an actual --map and --after snapshot')
        render_map(json.loads(args.map.read_text()), metadata, report, args.png)
    print(json.dumps({'passed': report['passed'], 'mode': report['mode'], 'desired_blocks': report['desired_blocks'],
                      'exact_mismatches': report['actual_exact_state_mismatches'],
                      'fixtures': report['fixtures'], 'walk_points': report['walking']['checked_points'],
                      'walk_failures': report['walking']['failures'][:20],
                      'navigation_passed': report['navigation']['passed'],
                      'unreachable_clear_columns': len(report['navigation']['unreachable_clear_columns']),
                      'route_failures': [r['id'] for r in report['navigation']['routes'] if not r['passed']],
                      'report': str(args.report.resolve())}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
