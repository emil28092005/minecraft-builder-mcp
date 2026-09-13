#!/usr/bin/env python3
"""Read-only candidate/live station block, public-floor and containment QA.

Recipes use the checked layout contract {version:1,scope,blocks:[x,y,z,block,
expected]}. Metadata declares public_floors, air-only clear_regions and optional
containment bounds/seeds/authorized_caps. Flooding treats partial/unknown shapes
as passable, so a successful result does not rely on decorative collision shapes.
"""
import argparse
from collections import Counter, deque
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('station_base', ROOT / 'scripts/verify-balustrade.py')
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
survey, plaza = base.survey, base.plaza
FULL = plaza.STATIC_CUBES | {'barrier'}
N2 = ((1, 0), (-1, 0), (0, 1), (0, -1))
N3 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def full_cube(state):
    return plaza.parse(state)[0] in FULL


def bounded_box(document):
    box = survey.box_of(document['min'], document['max'])
    if survey.volume(box) > survey.MAX_VOXELS:
        raise ValueError('Verification box exceeds the snapshot voxel limit')
    return box


def positions(box):
    return ((x, y, z) for x in range(box['min']['x'], box['max']['x'] + 1)
            for y in range(box['min']['y'], box['max']['y'] + 1)
            for z in range(box['min']['z'], box['max']['z'] + 1))


def inside(at, box):
    return all(box['min'][axis] <= value <= box['max'][axis]
               for axis, value in zip(('x', 'y', 'z'), at))


def surface_shape(state):
    if full_cube(state):
        return [(0., 1.)]
    name, props = plaza.parse(state)
    if name in {'smooth_sandstone_slab', 'cut_sandstone_slab', 'waxed_oxidized_cut_copper_slab'}:
        if props.get('waterlogged') != 'false':
            return None
        return {'bottom': [(0., .5)], 'top': [(.5, 1.)], 'double': [(0., 1.)]}.get(props.get('type'))
    return survey.vertical_shape(state)


def public_floors(reader, floors):
    reports = []
    for floor in floors:
        name, feet, raw = floor['id'], floor['standing_y'], floor['clear_columns']
        if feet not in (99, 113):
            raise ValueError('This station stage declares public feet at Y99 or Y113')
        if (not isinstance(raw, list) or not raw or any(not isinstance(p, list) or len(p) != 2
                or any(type(v) is not int for v in p) for p in raw)):
            raise ValueError('Each public floor requires integer clear_columns [x,z]')
        clear = set(map(tuple, raw))
        if len(clear) != len(raw):
            raise ValueError('Duplicate public floor column')
        source = floor['source']['x'], floor['source']['z']
        if source not in clear:
            raise ValueError('Floor source is not a declared clear column')
        height = floor.get('min_headroom', 4)
        if type(height) not in (int, float) or not math.isfinite(height) or height < 1.8:
            raise ValueError('Headroom must be finite and at least 1.8 blocks')
        failures, valid = [], set()
        for x, z in sorted(clear):
            support = surface_shape(reader.state(x, feet - 1, z))
            reason = None
            if support is None or not any(abs(high - 1.) < 1e-8 for low, high in support):
                reason = 'missing_or_unknown_support_at_public_feet'
            else:
                for y in range(feet, math.ceil(feet + height)):
                    shape = surface_shape(reader.state(x, y, z))
                    if shape is None:
                        reason = 'unknown_shape_in_required_clearance'
                        break
                    if any(y + lo < feet + height and y + hi > feet for lo, hi in shape):
                        reason = 'occupied_required_clearance'
                        break
            if reason:
                failures.append({'x': x, 'z': z, 'standing_y': feet, 'reason': reason})
            else:
                valid.add((x, z))
        reached, queue = set(), deque([source])
        while queue:
            p = queue.popleft()
            if p in reached or p not in valid:
                continue
            reached.add(p)
            queue.extend((p[0] + dx, p[1] + dz) for dx, dz in N2)
        unreachable = sorted(clear - reached)
        reports.append({'id': name, 'standing_y': feet, 'required_headroom': height,
                        'declared_columns': len(clear), 'physically_clear_columns': len(valid),
                        'reachable_clear_columns': len(reached), 'failed_samples': len(failures),
                        'sample_failure_examples': failures[:30], 'unreachable_columns': len(unreachable),
                        'unreachable_examples': unreachable[:30], 'passed': not failures and not unreachable})
    return {'status': 'checked' if reports else 'not_provided', 'passed': bool(reports) and all(r['passed'] for r in reports),
            'floors': reports, 'method': 'Observed center supports and declared vertical headroom, then cardinal traversal across valid level-floor columns. No lift transitions are inferred.'}


def clear_regions(reader, regions):
    reports = []
    for region in regions:
        box, failures, checked = bounded_box(region), [], 0
        for at in positions(box):
            checked += 1
            state = reader.state(*at)
            if state not in survey.AIR:
                failures.append({'at': list(at), 'actual': state})
        reports.append({'id': region['id'], 'bounds': box, 'checked_voxels': checked,
                        'nonair_voxels': len(failures), 'examples': failures[:30], 'passed': not failures})
    return {'status': 'checked' if reports else 'not_provided', 'passed': bool(reports) and all(r['passed'] for r in reports),
            'regions': reports, 'method': 'Every declared doorway/cabin/aisle clearance voxel must be observed air.'}


def named_access(reader, metadata):
    """Ensure furnishing targets are not silently filtered out of public topology."""
    interior = metadata.get('interior')
    if interior is None:
        return {'status': 'not_provided', 'passed': True}
    failures, targets_by_floor, lift_reports = [], {}, []
    floors = {f['standing_y']: set(map(tuple, f['clear_columns'])) for f in metadata['public_floors']}
    for raw_feet, navigation in interior['navigation'].items():
        feet = int(raw_feet)
        targets = navigation['named_targets']
        targets_by_floor[raw_feet] = len(targets)
        if feet not in floors or not targets:
            failures.append({'reason': 'missing_floor_or_named_targets', 'standing_y': feet})
        for target in targets:
            x, z = target['x'], target['z']
            if target['y'] != feet or (x, z) not in floors.get(feet, set()):
                failures.append({'reason': 'named_target_missing_from_public_topology', 'target': target})
            if not full_cube(reader.state(x, feet - 1, z)) or any(
                    reader.state(x, y, z) not in survey.AIR for y in range(feet, feet + 4)):
                failures.append({'reason': 'named_target_missing_full_support_or_four_air', 'target': target})
    for level, lift in interior['lift'].items():
        selector = tuple(lift['selector_block'])
        landing = tuple(lift['landing_block'])
        selector_state = reader.state(*selector)
        x, feet, z = landing
        passed = selector_state == 'minecraft:gold_block' and full_cube(reader.state(x, feet - 1, z)) and all(
            reader.state(x, y, z) in survey.AIR for y in range(feet, feet + 4))
        lift_reports.append({'floor': level, 'selector': selector, 'observed_selector': selector_state,
                             'landing': landing, 'passed': passed})
        if not passed:
            failures.append({'reason': 'lift_selector_or_landing_obstructed', 'floor': level})
    return {'status': 'checked', 'passed': not failures, 'named_targets_per_floor': targets_by_floor,
            'lift_landings': lift_reports, 'failures': failures,
            'method': 'Named furnishing targets must remain in the independently verified public-floor topology with full support and four air blocks. Gold selector and landing voxels are checked; runtime lift operation is not inferred.'}


def fixture_stability(reader, desired):
    fixtures = {p: s for p, s in desired.items() if plaza.parse(s)[0] in {'lantern', 'spruce_leaves'}}
    report = plaza.check_fixtures(reader, fixtures, {'fixtures': []})
    report['checked'].pop('root_connected_logs', None)
    logs = {p: s for p, s in desired.items() if plaza.parse(s)[0] == 'spruce_log'}
    roots = [p for p in logs if (p[0], p[1] - 1, p[2]) not in logs]
    for x, y, z in roots:
        below = reader.state(x, y - 1, z)
        if plaza.parse(below)[0] not in {'dirt', 'moss_block'}:
            report['failures'].append({'reason': 'station_topiary_or_diorama_root_without_soil',
                                       'at': [x, y, z], 'below': below})
    report['checked'].update({'spruce_logs': len(logs), 'topiary_or_diorama_roots': len(roots)})
    report['passed'] = not report['failures']
    report['status'] = 'checked'
    report['method'] = 'Planned lantern support, persistent leaf distances against the full observed neighborhood, and station topiary/diorama roots on stable dirt or moss.'
    return report


def conservative_containment(reader, metadata):
    if metadata is None:
        return {'status': 'not_proven', 'passed': False, 'reason': 'No containment bounds, seeds and authorized entrance caps were supplied.'}
    box = bounded_box(metadata['bounds'])
    caps, cap_reports = set(), []
    for region in metadata.get('authorized_caps', []):
        cap_box = bounded_box(region)
        points = set(positions(cap_box))
        if not points or not all(inside(p, box) for p in points):
            raise ValueError('Authorized virtual cap lies outside surveyed containment bounds')
        caps |= points
        cap_reports.append({'id': region['id'], 'bounds': cap_box, 'voxels': len(points)})
    blocked, passable, unknown = set(), set(), Counter()
    for at in positions(box):
        state = reader.state(*at)
        if full_cube(state) or at in caps:
            blocked.add(at)
        else:
            passable.add(at)
            if state not in survey.AIR:
                unknown[plaza.parse(state)[0]] += 1
    regions = [(r['id'], bounded_box(r)) for r in metadata.get('forbidden_regions', [])]
    roof_y = metadata.get('forbidden_y_at_or_above', 126)
    if type(roof_y) is not int:
        raise ValueError('Forbidden roof threshold must be an integer Y')
    seeds = metadata.get('seeds')
    if not isinstance(seeds, list) or not seeds:
        raise ValueError('Containment requires explicit public aisle/cabin seeds')
    reports = []
    for seed in seeds:
        coordinates = [seed[axis] for axis in ('x', 'y', 'z')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in coordinates):
            raise ValueError('Seed coordinates must be finite')
        source = tuple(math.floor(v) for v in coordinates)
        if not inside(source, box) or source in caps:
            raise ValueError('Containment source is outside its observed box or inside a virtual cap')
        low, high = seed.get('min_y'), seed.get('max_y')
        if any(v is not None and type(v) is not int for v in (low, high)):
            raise ValueError('Per-floor minimum/maximum reachable Y must be integers')
        reached, queue, violations, examples = set(), deque([source]), Counter(), []
        while queue:
            p = queue.popleft()
            if p in reached or p not in passable:
                continue
            reached.add(p)
            reasons = []
            if any(value in (box['min'][axis], box['max'][axis]) for axis, value in zip(('x', 'y', 'z'), p)):
                reasons.append('survey_boundary_reachable')
            if p[1] >= roof_y:
                reasons.append('roof_space_reachable')
            if low is not None and p[1] < low:
                reasons.append('below_public_floor_reachable')
            if high is not None and p[1] > high:
                reasons.append('above_public_room_reachable')
            reasons.extend('forbidden_region:' + name for name, bounds in regions if inside(p, bounds))
            for reason in reasons:
                violations[reason] += 1
                if len(examples) < 30:
                    examples.append({'at': list(p), 'reason': reason})
            queue.extend((p[0] + dx, p[1] + dy, p[2] + dz) for dx, dy, dz in N3)
        source_air = reader.state(*source) in survey.AIR
        reports.append({'id': seed['id'], 'source': list(source), 'source_observed_air': source_air,
                        'reachable_voxels': len(reached), 'minimum_reached_y': min((p[1] for p in reached), default=None),
                        'maximum_reached_y': max((p[1] for p in reached), default=None),
                        'violation_counts': dict(violations), 'examples': examples,
                        'passed': source_air and bool(reached) and not violations})
    return {'status': 'checked', 'passed': all(r['passed'] for r in reports), 'bounds': box,
            'observed_voxels': len(blocked) + len(passable), 'authorized_virtual_caps': cap_reports,
            'partial_or_unknown_materials_treated_as_passable': dict(unknown), 'seeds': reports,
            'method': 'Independent 6-neighbor floods from each public room/cabin seed. Known full cubes including glass block movement; partial/unknown shapes are treated as empty. Authorized entrance caps are virtual audit boundaries only.',
            'limits': 'This overestimates continuous player movement and does not simulate teleportation, spectator, block removal or lift operation. Failed floods through partial shapes require review; they are not automatically proven playable escape paths.'}


def audit(before, recipe, metadata, after=None):
    scope = survey.scope_of(recipe['scope'])
    if scope != before.scope or scope != metadata['scope'] or (after and after.scope != scope):
        raise ValueError('Recipe, metadata and snapshots differ in project/world/epoch')
    desired = base.coordinates(recipe)
    for row in recipe['blocks']:
        at = tuple(row[axis] for axis in ('x', 'y', 'z'))
        if before.state(*at) != row['expected']:
            raise ValueError(f'Recipe expected state differs from observed baseline at {at}')
    reader = plaza.Reader(after or before, None if after else desired)
    floor_report = public_floors(reader, metadata.get('public_floors', []))
    clearance = clear_regions(reader, metadata.get('clear_regions', []))
    access = named_access(reader, metadata)
    fixtures = fixture_stability(reader, desired)
    containment = conservative_containment(reader, metadata.get('containment'))
    volume = base.compare_volume(before, after, desired) if after else None
    unproven = []
    if floor_report['status'] == 'not_provided':
        unproven.append('Public floor support/headroom/reachability: no clear-column topology supplied.')
    if clearance['status'] == 'not_provided':
        unproven.append('Doorway and lift cabin clearances: no explicit clearance regions supplied.')
    if containment['status'] == 'not_proven':
        unproven.append('Windows, floor separation and roof/private-space containment: no flood contract supplied.')
    provided = [r for r in (floor_report, clearance, access, fixtures, containment) if r['status'] == 'checked']
    supported_passed = all(r['passed'] for r in provided) and (volume is None or volume['passed'])
    return {'version': 1, 'scope': scope, 'world_edits': 0,
            'mode': 'actual_after_snapshot' if after else 'candidate_overlay', 'desired_blocks': len(desired),
            'expected_states_verified_against_baseline': len(desired), 'public_floors': floor_report,
            'clear_regions': clearance, 'named_access': access, 'fixtures': fixtures,
            'containment': containment, 'volume': volume,
            'supported_checks_passed': supported_passed, 'unproven_checks': unproven,
            'passed': supported_passed and not unproven,
            'limits': 'Only observed block states are verified. Block entity text, display entities, gameplay/sign destinations and operational lift transitions require separate runtime checks. Actual snapshots are sequential, not atomic.'}


class FakeReader:
    def __init__(self, states):
        self.states = states

    def state(self, x, y, z):
        return self.states.get((x, y, z), 'minecraft:air')


class StationTests(unittest.TestCase):
    def room(self):
        box = {'min': {'x': -1, 'y': 98, 'z': -1}, 'max': {'x': 5, 'y': 127, 'z': 5}}
        states = {(x, y, z): 'minecraft:glass' for x in range(5) for y in range(99, 104) for z in range(5)
                  if x in (0, 4) or z in (0, 4) or y in (99, 103)}
        meta = {'bounds': box, 'seeds': [{'id': 'room', 'x': 2, 'y': 100, 'z': 2, 'min_y': 100, 'max_y': 102}]}
        return FakeReader(states), meta

    def test_closed_glass_room_is_contained_and_window_hole_is_detected(self):
        reader, metadata = self.room()
        self.assertTrue(conservative_containment(reader, metadata)['passed'])
        del reader.states[0, 101, 2]
        result = conservative_containment(reader, metadata)
        self.assertFalse(result['passed'])
        self.assertIn('survey_boundary_reachable', result['seeds'][0]['violation_counts'])

    def test_authorized_entrance_can_be_virtually_capped_without_changing_world(self):
        reader, metadata = self.room()
        del reader.states[0, 101, 2]
        metadata['authorized_caps'] = [{'id': 'entry', 'min': {'x': 0, 'y': 101, 'z': 2}, 'max': {'x': 0, 'y': 101, 'z': 2}}]
        self.assertTrue(conservative_containment(reader, metadata)['passed'])
        self.assertEqual(reader.state(0, 101, 2), 'minecraft:air')

    def test_partial_window_is_treated_as_open_and_upper_floor_hole_is_detected(self):
        reader, metadata = self.room()
        reader.states[0, 101, 2] = 'minecraft:iron_bars[east=false,north=true,south=true,waterlogged=false,west=false]'
        self.assertFalse(conservative_containment(reader, metadata)['passed'])
        reader, metadata = self.room()
        del reader.states[2, 99, 2]
        result = conservative_containment(reader, metadata)
        self.assertIn('below_public_floor_reachable', result['seeds'][0]['violation_counts'])

    def test_public_headroom_is_four_blocks_and_obstacle_disconnects_floor(self):
        reader = FakeReader({(x, 98, 0): 'minecraft:stone' for x in range(3)})
        floor = {'id': 'vestibule', 'standing_y': 99, 'source': {'x': 0, 'z': 0}, 'clear_columns': [[0, 0], [1, 0], [2, 0]]}
        self.assertTrue(public_floors(reader, [floor])['passed'])
        reader.states[1, 102, 0] = 'minecraft:lantern[hanging=true,waterlogged=false]'
        result = public_floors(reader, [floor])
        self.assertFalse(result['passed'])
        self.assertEqual(result['floors'][0]['unreachable_columns'], 2)

    def test_clearance_region_reports_real_door_obstruction(self):
        reader = FakeReader({(0, 99, 0): 'minecraft:stone'})
        region = {'id': 'door', 'min': {'x': 0, 'y': 99, 'z': 0}, 'max': {'x': 0, 'y': 102, 'z': 0}}
        self.assertEqual(clear_regions(reader, [region])['regions'][0]['nonair_voxels'], 1)

    def test_named_target_cannot_be_hidden_by_filtering_the_public_mask(self):
        reader = FakeReader({(x, 98, 0): 'minecraft:stone' for x in range(2)})
        metadata = {'public_floors': [{'standing_y': 99, 'clear_columns': [[0, 0]]}],
                    'interior': {'navigation': {'99': {'named_targets': [
                        {'name': 'bench-front', 'x': 1, 'y': 99, 'z': 0}]}}, 'lift': {}}}
        self.assertFalse(named_access(reader, metadata)['passed'])
        metadata['public_floors'][0]['clear_columns'].append([1, 0])
        self.assertTrue(named_access(reader, metadata)['passed'])

    def test_fixture_leaf_distance_and_lantern_support_use_actual_states(self):
        desired = {(0, 100, 0): 'minecraft:lantern[hanging=true,waterlogged=false]',
                   (2, 100, 0): 'minecraft:spruce_leaves[distance=1,persistent=true,waterlogged=false]'}
        reader = FakeReader(desired | {(0, 101, 0): 'minecraft:stone',
                                      (2, 99, 0): 'minecraft:spruce_log[axis=y]'})
        self.assertTrue(fixture_stability(reader, desired)['passed'])
        del reader.states[0, 101, 0]
        del reader.states[2, 99, 0]
        self.assertEqual(len(fixture_stability(reader, desired)['failures']), 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before', 'after', 'recipe', 'metadata', 'report'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(StationTests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if any(getattr(args, name) is None for name in ('before', 'recipe', 'metadata', 'report')):
        parser.error('--before, --recipe, --metadata and --report are required')
    before = survey.load_snapshot(args.before)
    after = survey.load_snapshot(args.after, before.scope) if args.after else None
    report = audit(before, json.loads(args.recipe.read_text()), json.loads(args.metadata.read_text()), after)
    paths = {name: getattr(args, name) for name in ('before', 'after', 'recipe', 'metadata') if getattr(args, name)}
    report['input_sha256'] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    survey.terrain.save(args.report, report)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 2 if report['supported_checks_passed'] and report['unproven_checks'] else 1)


if __name__ == '__main__':
    main()
