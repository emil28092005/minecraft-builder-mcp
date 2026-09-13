#!/usr/bin/env python3
"""Read-only proof of a closed, observed full-cube Minecraft zone enclosure.

The membrane is derived independently from an extruded XZ mask minus explicit
excluded voxels: every six-neighbor exterior shell voxel must be a full cube. An
exterior flood treats every unknown/partial block as empty, overestimating escape
routes. Swept 0.6 x 1.8 player AABB probes additionally test cardinal/diagonal
crossings, half-block stair rises, floor drops and roof ascent. These sample
probes supplement the complete membrane proof; they are not the proof itself.

This verifies static continuous movement, not spectator, commands, breaking,
plugin teleportation, or arbitrary discontinuous teleport/pearl behavior.
"""
import argparse
from collections import Counter, deque
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('containment_base', ROOT / 'scripts/verify-balustrade.py')
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
survey, plaza = base.survey, base.plaza
FULL = plaza.STATIC_CUBES | {'barrier'}
N2 = ((1, 0), (-1, 0), (0, 1), (0, -1))
N3 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
WIDTH, HEIGHT = .6, 1.8


def full_cube(state):
    return plaza.parse(state)[0] in FULL


def mask_geometry(metadata):
    raw = metadata['interior_columns']
    if (not isinstance(raw, list) or not raw or any(not isinstance(p, list) or len(p) != 2
            or any(type(v) is not int for v in p) for p in raw)):
        raise ValueError('interior_columns must be nonempty integer [x,z] pairs')
    interior = set(map(tuple, raw))
    if len(interior) != len(raw):
        raise ValueError('Duplicate interior column')
    floor, roof = metadata['floor_y'], metadata['roof_y']
    if type(floor) is not int or type(roof) is not int or roof - floor < 4:
        raise ValueError('Integer floor_y and roof_y need at least three free interior rows')
    shell = {(x + dx, z + dz) for x, z in interior for dx, dz in N2} - interior
    footprint = interior | shell
    reached, queue = set(), deque([next(iter(interior))])
    while queue:
        p = queue.popleft()
        if p in reached or p not in interior:
            continue
        reached.add(p)
        queue.extend((p[0] + dx, p[1] + dz) for dx, dz in N2)
    if reached != interior:
        raise ValueError('Interior mask must be one cardinally connected component')
    for key in ('wall_columns', 'shell_columns'):
        if ('interior_excluded_voxels' not in metadata and key in metadata
                and set(map(tuple, metadata[key])) != shell):
            raise ValueError(f'Claimed {key} differ from the independently derived complete shell')
    bounds = ((min(x for x, z in footprint) - 1, floor - 1, min(z for x, z in footprint) - 1),
              (max(x for x, z in footprint) + 1, roof + 1, max(z for x, z in footprint) + 1))
    if math.prod(hi - lo + 1 for lo, hi in zip(*bounds)) > survey.MAX_VOXELS:
        raise ValueError('Enclosure verification exceeds the bounded snapshot voxel limit')
    raw_excluded = metadata.get('interior_excluded_voxels', [])
    if (not isinstance(raw_excluded, list) or any(not isinstance(p, list) or len(p) != 3
            or any(type(v) is not int for v in p) for p in raw_excluded)):
        raise ValueError('interior_excluded_voxels must contain integer [x,y,z] triples')
    excluded = set(map(tuple, raw_excluded))
    if len(excluded) != len(raw_excluded):
        raise ValueError('Duplicate excluded interior voxel')
    volume = {(x, y, z) for x, z in interior for y in range(floor + 1, roof)}
    if not excluded <= volume:
        raise ValueError('Excluded voxel is outside the base extruded interior')
    volume -= excluded
    if not volume:
        raise ValueError('Excluded voxels remove the whole enclosure interior')
    membrane_voxels = {(x + dx, y + dy, z + dz) for x, y, z in volume for dx, dy, dz in N3} - volume
    return interior, shell, footprint, floor, roof, bounds, volume, membrane_voxels, excluded


def membrane(reader, geometry):
    interior, _, _, floor, roof, _ = geometry[:6]
    failures, materials, counts = [], Counter(), Counter()
    for x, y, z in sorted(geometry[7]):
        kind = ('floor' if y == floor else 'roof' if y == roof else
                'wall' if (x, z) not in interior else 'folded_boundary')
        counts[kind] += 1
        state = reader.state(x, y, z)
        materials[plaza.parse(state)[0]] += 1
        if not full_cube(state):
            failures.append({'at': [x, y, z], 'part': kind, 'actual': state})
    return {'passed': not failures, 'required_voxels': sum(counts.values()), 'parts': dict(counts),
            'observed_materials': dict(materials), 'nonfull_voxels': len(failures), 'examples': failures[:30],
            'method': 'Every voxel in N6(interior volume) minus interior volume must be an observed full collision cube.'}


def conservative_exterior_flood(reader, geometry, source):
    lo, hi = geometry[5]
    blocked, passable, unknown = set(), set(), Counter()
    boundary = []
    for x in range(lo[0], hi[0] + 1):
        for y in range(lo[1], hi[1] + 1):
            for z in range(lo[2], hi[2] + 1):
                p = x, y, z
                state = reader.state(*p)
                if full_cube(state):
                    blocked.add(p)
                    continue
                passable.add(p)
                if state not in survey.AIR:
                    unknown[plaza.parse(state)[0]] += 1
                if any(v in (low, high) for v, low, high in zip(p, lo, hi)):
                    boundary.append(p)
    reached, queue = set(boundary), deque(boundary)
    while queue:
        x, y, z = queue.popleft()
        for dx, dy, dz in N3:
            p = x + dx, y + dy, z + dz
            if p in passable and p not in reached:
                reached.add(p)
                queue.append(p)
    leaks = sorted(reached & geometry[6])
    source_cell = tuple(math.floor(v) for v in source)
    return {'passed': not leaks, 'observed_voxels': len(blocked) + len(passable),
            'exterior_reached_voxels': len(reached), 'interior_reached_from_exterior': len(leaks),
            'source_reached_from_exterior': source_cell in reached,
            'unknown_or_partial_blocks_treated_as_empty': dict(unknown), 'leak_examples': leaks[:30],
            'method': 'Six-neighbor free-voxel exterior flood; only known full collision cubes obstruct it.'}


def segment_box(start, finish, low, high):
    """Slab intersection with the interior of an expanded block AABB.

    Face contact is legal: a player's feet resting exactly on paving must not
    make every horizontal probe appear blocked before reaching the guard.
    """
    enter, leave = 0., 1.
    for a, b, lo, hi in zip(start, finish, low, high):
        lo, hi = lo + 1e-9, hi - 1e-9
        delta = b - a
        if abs(delta) < 1e-12:
            if a < lo or a > hi:
                return False
            continue
        first, last = sorted(((lo - a) / delta, (hi - a) / delta))
        enter, leave = max(enter, first), min(leave, last)
        if enter > leave:
            return False
    return True


def swept_player_hits_full_cube(reader, start, finish):
    radius = WIDTH / 2
    low = [math.floor(min(start[i], finish[i]) - (radius if i != 1 else 0)) for i in range(3)]
    high = [math.floor(max(start[i], finish[i]) + (radius if i != 1 else HEIGHT)) for i in range(3)]
    for x in range(low[0], high[0] + 1):
        for y in range(low[1], high[1] + 1):
            for z in range(low[2], high[2] + 1):
                if full_cube(reader.state(x, y, z)) and segment_box(
                        start, finish, (x - radius, y - HEIGHT, z - radius),
                        (x + 1 + radius, y + 1, z + 1 + radius)):
                    return True
    return False


def player_probes(reader, geometry, source):
    interior, _, _, floor, roof, _ = geometry[:6]
    counts, missed = Counter(), []
    source_clear = all(reader.state(x, y, z) in survey.AIR
                       for x in range(math.floor(source[0] - WIDTH / 2), math.floor(source[0] + WIDTH / 2) + 1)
                       for y in range(math.floor(source[1]), math.ceil(source[1] + HEIGHT))
                       for z in range(math.floor(source[2] - WIDTH / 2), math.floor(source[2] + WIDTH / 2) + 1))
    # Cross each boundary in cardinal and diagonal directions, including half-
    # block stair rises/drops. Fixed-height samples also cover free flight rows.
    heights = sorted({float(floor + 1), float(source[1]), roof - HEIGHT - .05})
    for x, z in sorted(interior):
        for dx, dz in itertools.product((-1, 0, 1), repeat=2):
            if (dx == dz == 0) or (x + dx, z + dz) in interior:
                continue
            for y in heights:
                for dy in (-.5, 0., .5):
                    start = (x + .5, y, z + .5)
                    finish = (x + dx + .5, y + dy, z + dz + .5)
                    kind = 'diagonal' if dx and dz else 'cardinal'
                    counts[kind] += 1
                    if not swept_player_hits_full_cube(reader, start, finish):
                        missed.append({'kind': kind, 'from': start, 'to': finish})
    # Test the locally folded boundary as well as the original outer perimeter.
    # The complete membrane check covers every height even when a sample starts
    # in an already obstructed partial-height pocket.
    for x, y, z in sorted(geometry[8] & geometry[7]):
        for dx, dy, dz in N3:
            p = x + dx, y + dy, z + dz
            if p not in geometry[6]:
                continue
            start, finish = (p[0] + .5, float(p[1]), p[2] + .5), (x + .5, float(y), z + .5)
            counts['folded_boundary'] += 1
            if not swept_player_hits_full_cube(reader, start, finish):
                missed.append({'kind': 'folded_boundary', 'from': start, 'to': finish})
    for kind, start, finish in [('floor', (source[0], floor + 1.1, source[2]),
                               (source[0], floor - .5, source[2])),
                              ('roof', (source[0], roof - HEIGHT - .1, source[2]),
                               (source[0], roof - .5, source[2]))]:
        counts[kind] += 1
        if not swept_player_hits_full_cube(reader, start, finish):
            missed.append({'kind': kind, 'from': start, 'to': finish})
    return {'passed': source_clear and not missed, 'player_width': WIDTH, 'player_height': HEIGHT,
            'source_headroom_observed_air': source_clear, 'swept_crossing_probes': dict(counts),
            'unblocked_probes': len(missed), 'examples': missed[:30],
            'note': 'Supplementary swept-AABB boundary probes; the independently derived full membrane is the complete static containment criterion.'}


def volume_components(reader, geometry, source):
    """Report geometric components; every one is still checked for containment."""
    pending, components = set(geometry[6]), []
    source_cell = tuple(math.floor(v) for v in source)
    while pending:
        queue, count, nonfull, contains_source = deque([next(iter(pending))]), 0, 0, False
        while queue:
            p = queue.popleft()
            if p not in pending:
                continue
            pending.remove(p)
            count += 1
            nonfull += not full_cube(reader.state(*p))
            contains_source |= p == source_cell
            queue.extend((p[0] + dx, p[1] + dy, p[2] + dz) for dx, dy, dz in N3)
        components.append({'voxels': count, 'nonfull_voxels': nonfull, 'contains_source': contains_source})
    return {'components': sorted(components, key=lambda c: c['voxels'], reverse=True),
            'source_in_volume': any(c['contains_source'] for c in components),
            'note': 'Disconnected sealed components are reported, not treated as escapes. The entire required membrane and exterior flood are checked.'}


def preserved_decor(before, reader, desired):
    protected, failures = 0, []
    for at, state in base.captured_voxels(before):
        name, _ = plaza.parse(state)
        if (name not in plaza.FLOWERS | {'lantern', 'spruce_fence', 'spruce_stairs', 'iron_chain'}
                and not any(suffix in name for suffix in ('_leaves', '_log', 'waxed_oxidized_cut_copper'))):
            continue
        protected += 1
        if reader.state(*at) != state:
            failures.append({'at': list(at), 'before': state, 'after': reader.state(*at), 'in_plan': at in desired})
    return {'passed': not failures, 'protected_observed_states': protected, 'changed_states': len(failures),
            'examples': failures[:30]}


def audit(before, layout, metadata, after=None):
    scope = survey.scope_of(layout['scope'])
    if scope != before.scope or scope != metadata['scope'] or (after and after.scope != scope):
        raise ValueError('Project/world/epoch differs between containment inputs')
    desired = base.coordinates(layout)
    for row in layout['blocks']:
        p = tuple(row[a] for a in ('x', 'y', 'z'))
        if before.state(*p) != row['expected']:
            raise ValueError(f'Expected plan state differs from observed baseline at {p}')
    source = tuple(metadata['source'][axis] for axis in ('x', 'y', 'z'))
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in source):
        raise ValueError('Source must contain finite x/y/z player feet coordinates')
    geometry = mask_geometry(metadata)
    if tuple(math.floor(v) for v in source) not in geometry[6] or not geometry[3] < source[1] < geometry[4] - HEIGHT:
        raise ValueError('Source is outside the enclosure interior')
    reader = plaza.Reader(after or before, None if after else desired)
    closed = membrane(reader, geometry)
    flood = conservative_exterior_flood(reader, geometry, source)
    probes = player_probes(reader, geometry, source)
    components = volume_components(reader, geometry, source)
    decor = preserved_decor(before, reader, desired)
    volume = base.compare_volume(before, after, desired) if after else None
    return {'version': 1, 'scope': scope, 'world_edits': 0,
            'mode': 'actual_after_snapshot' if after else 'candidate_overlay',
            'desired_blocks': len(desired), 'interior_columns': len(geometry[0]),
            'independently_derived_wall_columns': len(geometry[1]),
            'interior_voxels': len(geometry[6]), 'interior_excluded_voxels': len(geometry[8]),
            'volume_components': components,
            'membrane': closed, 'exterior_flood': flood, 'player_probes': probes,
            'preserved_decor': decor, 'volume': volume,
            'passed': all(r['passed'] for r in (closed, flood, probes, decor)) and (volume is None or volume['passed']),
            'limitations': 'Static continuous collision containment for normal nonspectator players only. No protection against spectator, breaking/removing blocks, operator commands, plugin teleports or arbitrary discontinuous teleport/pearl behavior. Actual snapshots are sequential, not atomic.'}


class ContainmentTests(unittest.TestCase):
    def scene(self):
        meta = {'interior_columns': [[0, 0], [1, 0], [0, 1], [1, 1]], 'floor_y': 0, 'roof_y': 5}
        geo = mask_geometry(meta)
        states = {}
        for x, z in geo[2]:
            for y in ([0, 5] if (x, z) in geo[0] else range(6)):
                states[x, y, z] = 'minecraft:barrier'
        reader = type('Reader', (), {'state': lambda self, x, y, z: states.get((x, y, z), 'minecraft:air')})()
        return meta, geo, states, reader

    def test_complete_shell_blocks_flight_diagonals_stairs_and_drops(self):
        _, geo, _, reader = self.scene()
        self.assertTrue(membrane(reader, geo)['passed'])
        self.assertTrue(conservative_exterior_flood(reader, geo, (.5, 1., .5))['passed'])
        self.assertTrue(player_probes(reader, geo, (.5, 1., .5))['passed'])

    def test_one_missing_wall_or_roof_voxel_leaks(self):
        for at in [(-1, 2, 0), (0, 5, 0), (0, 0, 0)]:
            _, geo, states, reader = self.scene()
            del states[at]
            self.assertFalse(membrane(reader, geo)['passed'])
            self.assertFalse(conservative_exterior_flood(reader, geo, (.5, 1., .5))['passed'])

    def test_floor_need_not_extend_under_exterior_wall(self):
        _, geo, states, reader = self.scene()
        for x, z in geo[1]:
            states.pop((x, 0, z), None)
        self.assertTrue(membrane(reader, geo)['passed'])
        self.assertTrue(conservative_exterior_flood(reader, geo, (.5, 1., .5))['passed'])

    def test_inward_fold_preserves_partial_stair_outside_and_missing_fold_leaks(self):
        meta, _, states, reader = self.scene()
        meta['interior_excluded_voxels'] = [[0, 2, 0]]
        geo = mask_geometry(meta)
        states[-1, 2, 0] = 'minecraft:stone_brick_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]'
        states[0, 2, 0] = 'minecraft:barrier'
        self.assertNotIn((-1, 2, 0), geo[7])
        self.assertTrue(membrane(reader, geo)['passed'])
        self.assertTrue(conservative_exterior_flood(reader, geo, (1.5, 1., 1.5))['passed'])
        self.assertTrue(player_probes(reader, geo, (1.5, 1., 1.5))['passed'])
        del states[0, 2, 0]
        self.assertFalse(membrane(reader, geo)['passed'])
        self.assertFalse(conservative_exterior_flood(reader, geo, (1.5, 1., 1.5))['passed'])

    def test_exclusions_must_be_unique_voxels_inside_original_volume(self):
        meta, _, _, _ = self.scene()
        for exclusions in [[[0, 2, 0], [0, 2, 0]], [[100, 2, 100]], [[0, 0, 0]]]:
            meta['interior_excluded_voxels'] = exclusions
            with self.assertRaises(ValueError):
                mask_geometry(meta)

    def test_stair_or_slab_cannot_substitute_for_solid_membrane(self):
        _, geo, states, reader = self.scene()
        states[-1, 2, 0] = 'minecraft:stone_brick_slab[type=bottom,waterlogged=false]'
        self.assertFalse(membrane(reader, geo)['passed'])
        self.assertFalse(conservative_exterior_flood(reader, geo, (.5, 1., .5))['passed'])
        states[-1, 2, 0] = 'minecraft:stone'
        self.assertTrue(membrane(reader, geo)['passed'])

    def test_swept_aabb_detects_diagonal_corner_and_vertical_collision(self):
        reader = type('Reader', (), {'state': lambda self, x, y, z: 'minecraft:barrier' if (x, y, z) == (1, 1, 1) else 'minecraft:air'})()
        self.assertTrue(swept_player_hits_full_cube(reader, (.5, 1., .5), (2.5, 1., 2.5)))
        self.assertFalse(swept_player_hits_full_cube(reader, (.2, 1., .2), (.2, 2., .2)))

    def test_standing_contact_with_floor_does_not_mask_an_open_horizontal_route(self):
        reader = type('Reader', (), {'state': lambda self, x, y, z: 'minecraft:stone' if y == 0 else 'minecraft:air'})()
        self.assertFalse(swept_player_hits_full_cube(reader, (.5, 1., .5), (2.5, 1., 2.5)))
        self.assertTrue(swept_player_hits_full_cube(reader, (.5, 1., .5), (.5, .5, .5)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--after', type=Path)
    parser.add_argument('--layout', type=Path)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(ContainmentTests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if any(getattr(args, key) is None for key in ('before', 'layout', 'metadata', 'report')):
        parser.error('--before, --layout, --metadata and --report are required')
    before = survey.load_snapshot(args.before)
    after = survey.load_snapshot(args.after, before.scope) if args.after else None
    report = audit(before, json.loads(args.layout.read_text()), json.loads(args.metadata.read_text()), after)
    paths = {key: getattr(args, key) for key in ('before', 'after', 'layout', 'metadata') if getattr(args, key)}
    report['input_sha256'] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    survey.terrain.save(args.report, report)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
