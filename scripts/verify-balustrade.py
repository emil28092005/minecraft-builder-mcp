#!/usr/bin/env python3
"""Read-only candidate and observed-volume QA for the arrival-square balustrade.

Checks stable capped-wall states, cardinal continuity, grounded footings, original
road masks, preserved garden fixtures and remaining walkable floor. Actual mode
also compares every captured voxel against baseline plus the desired overlay.
"""
import argparse
from collections import Counter, deque
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('balustrade_plaza_qa', ROOT / 'scripts/verify-plaza.py')
plaza = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plaza)
survey = plaza.survey
N = {'east': (1, 0), 'north': (0, -1), 'south': (0, 1), 'west': (-1, 0)}
CAP = 'minecraft:smooth_sandstone_slab[type=bottom,waterlogged=false]'


def coordinates(document):
    result = {}
    for row in document['blocks']:
        at = tuple(survey.point(row)[axis] for axis in ('x', 'y', 'z'))
        if at in result:
            raise ValueError(f'Duplicate desired position {at}')
        result[at] = row['block']
    return result


def stable_wall_properties(connected, capped=True):
    """Vanilla 26.2 WallBlock under a full bottom face (the bottom slab cap).

    Cap coverage makes arms tall. shouldRaisePost suppresses the post for either
    opposite tall pair only after its endpoint/corner/T asymmetry condition.
    """
    ns = connected['north'] != connected['south']
    ew = connected['east'] != connected['west']
    opposite = ((connected['north'] and connected['south']) or
                (connected['east'] and connected['west']))
    up = ns or ew or not opposite
    return {**{name: ('tall' if capped else 'low') if connected[name] else 'none' for name in N},
            'up': str(up).lower(), 'waterlogged': 'false'}


def wall_neighbor(state):
    name, _ = plaza.parse(state)
    return name.endswith('_wall') or name in plaza.STATIC_CUBES


def check_guard(reader, metadata):
    columns = set(map(tuple, metadata['fence_columns']))
    piers = set(map(tuple, metadata['pier_columns']))
    failures, listed = [], []
    if not columns or not piers <= columns:
        raise ValueError('Fence columns and piers must form a nonempty valid set')
    for index, raw in enumerate(metadata['path_runs']):
        run = list(map(tuple, raw))
        if len(run) < 2 or run[0] not in piers or run[-1] not in piers:
            failures.append({'reason': 'run_needs_pier_endpoints', 'run': index})
        for a, b in zip(run, run[1:]):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                failures.append({'reason': 'noncardinal_guard_gap', 'from': a, 'to': b})
        listed.extend(run)
    if len(listed) != len(set(listed)) or set(listed) != columns:
        failures.append({'reason': 'path_runs_do_not_cover_fence_once'})
    for x, z in sorted(columns):
        state = reader.state(x, 96, z)
        material, props = plaza.parse(state)
        if (x, z) in piers:
            if material != 'cut_sandstone':
                failures.append({'at': [x, 96, z], 'reason': 'pier_material', 'actual': state})
        else:
            connections = {name: wall_neighbor(reader.state(x + dx, 96, z + dz))
                           for name, (dx, dz) in N.items()}
            expected = stable_wall_properties(connections)
            if material != 'stone_brick_wall' or props != expected:
                failures.append({'at': [x, 96, z], 'reason': 'unstable_wall_state',
                                 'actual': state, 'expected_properties': expected})
        if reader.state(x, 97, z) != CAP:
            failures.append({'at': [x, 97, z], 'reason': 'missing_continuous_bottom_cap'})
        if plaza.parse(reader.state(x, 95, z))[0] not in plaza.STATIC_CUBES:
            failures.append({'at': [x, 95, z], 'reason': 'guard_without_full_base'})
    for footing in metadata['footing_columns']:
        x, z, bottom = footing['x'], footing['z'], footing['support_y']
        if (x, z) not in columns or not 70 <= bottom < 95:
            raise ValueError('Unexpected footing coordinate or support height')
        if plaza.parse(reader.state(x, bottom, z))[0] == 'grass_block':
            failures.append({'at': [x, bottom, z], 'reason': 'grass_under_opaque_footing_will_decay_to_dirt'})
        for y in range(bottom, 96):
            if plaza.parse(reader.state(x, y, z))[0] not in plaza.STATIC_CUBES:
                failures.append({'at': [x, y, z], 'reason': 'footing_gap_or_unknown_support'})
    # A newly connected pier also changes the reciprocal side of an old road
    # rail. Inspect real neighbors, including walls absent from compiler masks.
    adjacent = {(x + dx, z + dz) for x, z in columns for dx, dz in N.values()
                if (x + dx, z + dz) not in columns and
                plaza.parse(reader.state(x + dx, 96, z + dz))[0] == 'stone_brick_wall'}
    for x, z in sorted(adjacent):
        above = reader.state(x, 97, z)
        if above not in survey.AIR and above != CAP:
            failures.append({'at': [x, 97, z], 'reason': 'unknown_neighbor_rail_top_shape', 'actual': above})
            continue
        connected = {name: wall_neighbor(reader.state(x + dx, 96, z + dz))
                     for name, (dx, dz) in N.items()}
        actual = reader.state(x, 96, z)
        expected = stable_wall_properties(connected, above == CAP)
        if plaza.parse(actual)[1] != expected:
            failures.append({'at': [x, 96, z], 'reason': 'unstable_reciprocal_road_rail',
                             'actual': actual, 'expected_properties': expected})
    pending, components = set(columns), []
    while pending:
        seen, queue = set(), deque([next(iter(pending))])
        while queue:
            p = queue.popleft()
            if p not in pending:
                continue
            pending.remove(p)
            seen.add(p)
            queue.extend((p[0] + dx, p[1] + dz) for dx, dz in N.values())
        components.append(len(seen))
    if sorted(components) != sorted(len(run) for run in metadata['path_runs']):
        failures.append({'reason': 'actual_cardinal_components_differ_from_runs', 'components': components})
    return {'passed': not failures, 'columns': len(columns), 'piers': len(piers),
            'cardinal_components': sorted(components), 'grounded_footings': len(metadata['footing_columns']),
            'adjacent_road_rails': len(adjacent),
            'failures': failures}


def captured_voxels(snapshot):
    for cell in snapshot.cells.values():
        lo, hi, index = cell['min'], cell['max'], 0
        for y in range(lo['y'], hi['y'] + 1):
            for z in range(lo['z'], hi['z'] + 1):
                for x in range(lo['x'], hi['x'] + 1):
                    yield (x, y, z), cell['palette'][cell['indices'][index]]
                    index += 1


def compare_volume(before, after, desired):
    mismatches, counts = [], Counter()
    for at, baseline in captured_voxels(before):
        changed = at in desired
        counts['desired_voxels' if changed else 'outside_desired_voxels'] += 1
        actual, expected = after.state(*at), desired.get(at, baseline)
        if actual != expected:
            counts['desired_mismatches' if changed else 'outside_desired_mismatches'] += 1
            if len(mismatches) < 30:
                mismatches.append({'at': list(at), 'expected': expected, 'actual': actual,
                                   'inside_desired': changed})
    if counts['desired_voxels'] != len(desired):
        raise ValueError('Desired blocks extend outside the captured baseline volume')
    return {'passed': not mismatches, **dict(counts), 'mismatch_examples': mismatches,
            'scope_note': 'Every voxel inside the supplied before snapshot; no claim for unobserved exterior voxels.'}


def audit(before, layout, metadata, garden_plan, garden_metadata, garden_walk, nav, after=None):
    scope = survey.scope_of(layout['scope'])
    if any(value != scope for value in (before.scope, metadata['scope'], garden_plan['scope'],
                                       garden_metadata['scope'], garden_walk['scope'])) or (after and after.scope != scope):
        raise ValueError('Project/world/epoch differs between inputs')
    desired, failures = coordinates(layout), []
    for row in layout['blocks']:
        at = tuple(row[a] for a in ('x', 'y', 'z'))
        if before.state(*at) != row['expected']:
            raise ValueError(f'Stale expected block at {at}')
    fence = set(map(tuple, metadata['fence_columns']))
    road = {tuple(p) for route in nav['routes'] for p in route['clear_cells']}
    bench = set(map(tuple, garden_metadata['bench_access_columns']))
    for x, y, z in desired:
        if (x, z) in road or (x, z) in bench:
            failures.append({'at': [x, y, z], 'reason': 'protected_road_or_bench_column_edited'})
    if fence & (road | bench):
        failures.append({'reason': 'fence_declared_on_protected_road_or_bench'})
    reader = plaza.Reader(after or before, None if after else desired)
    guard = check_guard(reader, metadata)
    old_desired = coordinates(garden_plan)
    protected = {at: state for at, state in old_desired.items()
                 if plaza.parse(state)[0] in plaza.FLOWERS | {'spruce_stairs', 'spruce_fence', 'lantern',
                     'iron_chain', 'iron_bars', 'gold_block'} or any(part in state for part in ('_leaves', '_log', 'waxed_oxidized_cut_copper'))}
    for fixture in garden_metadata['fixtures']:
        if fixture['type'] in ('conifer', 'topiary'):
            at = fixture['x'], 95, fixture['z']
            protected[at] = before.state(*at)
    lost = [{'at': list(at), 'expected': state, 'actual': reader.state(*at)}
            for at, state in protected.items() if reader.state(*at) != state]
    fixture_report = plaza.check_fixtures(reader, old_desired, garden_metadata)
    blocked = set(map(tuple, garden_metadata['unwalkable_columns'])) | fence
    points = [p for p in garden_walk['points'] if (p['x'], p['z']) not in fence]
    walking = survey.verify_walkable(reader, points)
    navigation = json.loads(json.dumps(nav))
    for cell in navigation['cells']:
        if (cell['x'], cell['z']) in blocked:
            cell['clear'] = False
    nav_report = plaza.navigation.audit(navigation)
    graph = plaza.navigation.surface_graph(plaza.navigation.normalize_cells(navigation))
    reached = plaza.navigation.reachable(graph, (0, 9))
    bench_report = [plaza.navigation.endpoint_report(f'bench-access-{x}-{z}', (x, z), graph, reached)
                    for x, z in sorted(bench)]
    nav_report['bench_access'] = bench_report
    nav_report['passed'] &= all(row['passed'] for row in bench_report)
    volume = compare_volume(before, after, desired) if after else None
    passed = (not failures and not lost and guard['passed'] and fixture_report['passed'] and
              walking['passed'] and nav_report['passed'] and (volume is None or volume['passed']))
    return {'version': 1, 'scope': scope, 'mode': 'actual_after_snapshot' if after else 'candidate_overlay',
            'passed': passed, 'world_edits': 0, 'desired_blocks': len(desired), 'guard': guard,
            'protected_road_columns': len(road), 'protection_failures': failures,
            'preserved_fixture_states': len(protected), 'lost_fixtures': lost[:30],
            'fixtures': fixture_report, 'walking': walking, 'navigation': nav_report,
            'volume': volume, 'note': 'Point-sampled body headroom and navigation; not a full moving-player collision simulation.'}


class BalustradeTests(unittest.TestCase):
    def test_stable_capped_wall_corner_and_straight_and_cross(self):
        for sides, up in [({'north', 'south'}, 'false'), ({'east', 'west'}, 'false'),
                          (set(N), 'false'), ({'north', 'east'}, 'true'),
                          ({'north', 'east', 'south'}, 'true'), ({'north'}, 'true')]:
            self.assertEqual(stable_wall_properties({n: n in sides for n in N})['up'], up)
        uncapped = stable_wall_properties({n: n in {'east', 'west'} for n in N}, False)
        self.assertEqual((uncapped['east'], uncapped['west'], uncapped['up']), ('low', 'low', 'false'))

    def test_volume_detects_unrelated_change_and_exact_properties(self):
        before = type('Snapshot', (), {'cells': {0: {'min': dict(x=0, y=0, z=0),
            'max': dict(x=1, y=0, z=0), 'palette': ['minecraft:air'], 'indices': [0, 0]}}})()
        states = {(0, 0, 0): CAP, (1, 0, 0): 'minecraft:stone'}
        after = type('After', (), {'state': lambda self, x, y, z: states[x, y, z]})()
        result = compare_volume(before, after, {(0, 0, 0): CAP})
        self.assertFalse(result['passed'])
        self.assertEqual(result['outside_desired_mismatches'], 1)
        states[(1, 0, 0)] = 'minecraft:air'
        self.assertTrue(compare_volume(before, after, {(0, 0, 0): CAP})['passed'])
        states[(0, 0, 0)] = CAP.replace('bottom', 'top')
        self.assertEqual(compare_volume(before, after, {(0, 0, 0): CAP})['desired_mismatches'], 1)

    def test_diagonal_run_is_rejected(self):
        states = {(x, y, z): 'minecraft:air' for x in range(-1, 3) for z in range(-1, 3) for y in range(95, 98)}
        for x, z in [(0, 0), (1, 1)]:
            states[x, 95, z] = 'minecraft:stone'
            states[x, 96, z] = 'minecraft:cut_sandstone'
            states[x, 97, z] = CAP
        reader = type('Reader', (), {'state': lambda self, x, y, z: states[x, y, z]})()
        meta = {'fence_columns': [[0, 0], [1, 1]], 'pier_columns': [[0, 0], [1, 1]],
                'path_runs': [[[0, 0], [1, 1]]], 'footing_columns': []}
        result = check_guard(reader, meta)
        self.assertIn('noncardinal_guard_gap', {f['reason'] for f in result['failures']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stage, garden = ROOT / '.runtime/balustrade-stage04', ROOT / '.runtime/plaza-stage03'
    parser.add_argument('--before', type=Path, default=stage / 'before-full.json.gz')
    parser.add_argument('--after', type=Path)
    parser.add_argument('--layout', type=Path, default=stage / 'balustrade.json')
    parser.add_argument('--metadata', type=Path, default=stage / 'balustrade.metadata.json')
    parser.add_argument('--garden-plan', type=Path, default=garden / 'plaza-polished.json')
    parser.add_argument('--garden-metadata', type=Path, default=garden / 'plaza-polished.metadata.json')
    parser.add_argument('--garden-walk', type=Path, default=garden / 'plaza-polished.walk.json')
    parser.add_argument('--navigation', type=Path, default=ROOT / '.runtime/foundations-stage02/navigation-verified-walkable-input.json')
    parser.add_argument('--report', type=Path, default=stage / 'candidate-qa.json')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(BalustradeTests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    paths = {key: getattr(args, key) for key in ('layout', 'metadata', 'garden_plan', 'garden_metadata', 'garden_walk', 'navigation')}
    documents = [json.loads(path.read_text()) for path in paths.values()]
    before = survey.load_snapshot(args.before)
    after = survey.load_snapshot(args.after, before.scope) if args.after else None
    report = audit(before, *documents, after=after)
    paths['before'] = args.before
    if args.after:
        paths['after'] = args.after
    report['input_sha256'] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    survey.terrain.save(args.report, report)
    print(json.dumps({key: report[key] for key in ('passed', 'mode', 'desired_blocks', 'guard', 'protection_failures',
                                                  'lost_fixtures', 'fixtures', 'volume')}
                     | {'walk_points': report['walking']['checked_points'], 'walk_failures': report['walking']['failures'][:10],
                        'navigation_passed': report['navigation']['passed'],
                        'unreachable_columns': report['navigation']['unreachable_clear_columns'],
                        'report': str(args.report.resolve())}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
