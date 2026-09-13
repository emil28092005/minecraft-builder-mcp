"""Read-only survey completeness, cache isolation and path-height regression tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location('foundation_survey', Path(__file__).with_name('foundation-survey.py'))
survey = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(survey)
SCOPE = {'project_id': 'project', 'world_id': 'world', 'world_epoch': 'epoch'}


class Backend:
    def __init__(self, states=None):
        self.states = states or {}
        self.calls = []
        self.mutate = None
        self.fail_call = None
        self.context = {**SCOPE, 'region': {'min': {'x': -64, 'y': -64, 'z': -64},
                                         'max': {'x': 63, 'y': 127, 'z': 63}}}

    def call(self, method, **params):
        self.calls.append(method)
        if method == 'project_context':
            return self.context
        if method != 'region_inspect':
            raise AssertionError('Only read-only RPC is allowed')
        if self.fail_call == self.calls.count('region_inspect'):
            raise RuntimeError('chunk_not_loaded')
        if survey.volume(params) > 4096:
            raise AssertionError('Unbounded inspection')
        lo, hi = params['min'], params['max']
        result = {'world_epoch': self.context['world_epoch'], 'truncated': False,
                  'blocks': [{'pos': {'x': x, 'y': y, 'z': z}, 'state': self.states.get((x, y, z), 'minecraft:air')}
                             for x in range(lo['x'], hi['x'] + 1) for y in range(lo['y'], hi['y'] + 1)
                             for z in range(lo['z'], hi['z'] + 1)]}
        if self.mutate:
            self.mutate(result)
        return result


def box(lo=(-2, 64, -2), hi=(2, 68, 2)):
    return survey.box_cells(dict(zip(survey.AXES, lo)), dict(zip(survey.AXES, hi)))


class SurveyTests(unittest.TestCase):
    def capture(self, backend=None, cells=None):
        backend = backend or Backend()
        cells = cells or box()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'survey.json.gz'
            result = survey.scan(backend, cells, path)
            loaded = survey.load_snapshot(path, SCOPE)
            self.assertEqual(loaded.document, result.document)
            return loaded

    def test_negative_cell_partition_and_exact_states(self):
        states = {(-2, 64, -2): 'minecraft:smooth_stone_slab[type=bottom,waterlogged=false]'}
        result = self.capture(Backend(states))
        self.assertEqual(result.state(-2, 64, -2), states[(-2, 64, -2)])
        self.assertEqual(result.state(2, 68, 2), 'minecraft:air')
        self.assertEqual(len(result.cells), 4)
        with self.assertRaises(KeyError):
            result.state(-3, 64, -2)
        with self.assertRaises(KeyError):
            result.state(17, 64, 0)

    def test_columns_do_not_assume_air_in_unread_cells(self):
        cells = survey.column_cells({'version': 1, 'columns': [
            {'x': -20, 'z': 1, 'min_y': 64, 'max_y': 68},
            {'x': 20, 'z': 1, 'min_y': 66, 'max_y': 72}]})
        result = self.capture(cells=cells)
        self.assertEqual(result.state(20, 69, 1), 'minecraft:air')
        with self.assertRaises(KeyError):
            result.state(0, 69, 1)
        with self.assertRaises(KeyError):
            result.state(20, 65, 1)

    def test_rejects_missing_duplicate_truncated_and_wrong_epoch(self):
        changes = [lambda r: r['blocks'].pop(),
                   lambda r: r['blocks'].append(r['blocks'][0]),
                   lambda r: r.update(truncated=True),
                   lambda r: r.update(world_epoch='different')]
        for mutate in changes:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                backend = Backend()
                backend.mutate = mutate
                path = Path(directory) / 'survey.json.gz'
                with self.assertRaises(RuntimeError):
                    survey.scan(backend, box(), path)
                self.assertFalse(path.exists())

    def test_out_of_area_fails_before_any_inspection(self):
        backend = Backend()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                survey.scan(backend, box((-65, 64, 0), (-60, 68, 0)), Path(directory) / 'survey.json.gz')
        self.assertEqual(backend.calls, ['project_context'])

    def test_explicit_resume_keeps_readonly_cache_and_checks_scope(self):
        backend = Backend()
        backend.fail_call = 2
        cells = box((-16, 64, 0), (16, 68, 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'survey.json.gz'
            with self.assertRaisesRegex(RuntimeError, 'chunk_not_loaded'):
                survey.scan(backend, cells, path)
            self.assertFalse(path.exists())
            with self.assertRaisesRegex(ValueError, '--resume'):
                survey.scan(backend, cells, path)
            backend.context['world_epoch'] = 'another-epoch'
            with self.assertRaisesRegex(ValueError, 'scope'):
                survey.scan(backend, cells, path, resume=True)
            backend.context['world_epoch'] = 'epoch'
            backend.fail_call = None
            result = survey.scan(backend, cells, path, resume=True)
            self.assertTrue(result.document['resumed_cache'])
            self.assertEqual(backend.calls.count('region_inspect'), 4)
            with self.assertRaisesRegex(ValueError, 'fresh path'):
                survey.scan(backend, cells, path, resume=True)

    def test_corrupt_cache_and_missing_snapshot_indices_are_rejected(self):
        snapshot = self.capture()
        snapshot.document['cells'][0]['indices'].pop()
        with self.assertRaisesRegex(ValueError, 'indices'):
            survey.Snapshot(snapshot.document, SCOPE)

    def test_foreign_scope_rejected(self):
        snapshot = self.capture()
        with self.assertRaisesRegex(ValueError, 'another project'):
            survey.Snapshot(snapshot.document, {**SCOPE, 'project_id': 'other'})

    def test_walkability_half_slab_fullblock_clearance_and_gradient(self):
        states = {(0, 64, 0): 'minecraft:stone',
                  (1, 65, 0): 'minecraft:smooth_stone_slab[type=bottom,waterlogged=false]',
                  (2, 65, 0): 'minecraft:stone'}
        snapshot = self.capture(Backend(states), box((0, 64, 0), (3, 69, 0)))
        points = [{'x': x, 'z': 0, 'standing_y': feet, 'route': 'main'}
                  for x, feet in [(0, 65), (1, 65.5), (2, 66)]]
        result = survey.verify_walkable(snapshot, points)
        self.assertTrue(result['passed'])
        self.assertEqual(result['checked_route_edges'], 2)
        points[1]['standing_y'] = 66
        result = survey.verify_walkable(snapshot, points)
        self.assertFalse(result['passed'])
        self.assertIn('missing_support_at_feet', [f['reason'] for f in result['failures']])
        self.assertIn('route_step_exceeds_half_block', [f['reason'] for f in result['failures']])

    def test_headroom_unknown_stairs_and_absent_observations_fail(self):
        states = {(0, 64, 0): 'minecraft:stone', (0, 66, 0): 'minecraft:stone',
                  (1, 64, 0): 'minecraft:stone_brick_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]'}
        snapshot = self.capture(Backend(states), box((0, 64, 0), (1, 68, 0)))
        result = survey.verify_walkable(snapshot, [{'x': x, 'z': 0, 'standing_y': 65} for x in (0, 1, 2)])
        self.assertEqual([f['reason'] for f in result['failures']],
                         ['blocked_headroom', 'unknown_support_shape', 'unobserved_block'])

    def test_straight_bottom_stair_profile_all_directions(self):
        sides = {'north': ((.5, .75), (.5, .25)), 'south': ((.5, .25), (.5, .75)),
                 'east': ((.25, .5), (.75, .5)), 'west': ((.75, .5), (.25, .5))}
        for facing, (low, high) in sides.items():
            with self.subTest(facing=facing):
                state = f'minecraft:stone_brick_stairs[facing={facing},half=bottom,shape=straight,waterlogged=false]'
                snapshot = self.capture(Backend({(0, 64, 0): state}), box((0, 64, 0), (0, 68, 0)))
                points = [{'x': 0, 'z': 0, 'sub_x': sub[0], 'sub_z': sub[1], 'standing_y': feet, 'route': facing}
                          for sub, feet in [(low, 64.5), (high, 65)]]
                result = survey.verify_walkable(snapshot, points)
                self.assertTrue(result['passed'], result)
                self.assertEqual(result['checked_route_edges'], 1)
                points[0]['standing_y'] = 65
                self.assertEqual(survey.verify_walkable(snapshot, points)['failures'][0]['reason'], 'missing_support_at_feet')

    def test_stair_headroom_riser_boundary_and_unsupported_shapes(self):
        base = 'minecraft:stone_brick_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]'
        snapshot = self.capture(Backend({(0, 64, 0): base, (0, 66, 0): 'minecraft:stone'}),
                                box((0, 64, 0), (0, 68, 0)))
        result = survey.verify_walkable(snapshot, [{'x': 0, 'z': 0, 'sub_z': .25, 'standing_y': 65}])
        self.assertEqual(result['failures'][0]['reason'], 'blocked_headroom')
        self.assertIsNone(survey.vertical_shape(base, .5, .5))
        self.assertIsNone(survey.vertical_shape(base.replace('straight', 'inner_left'), .5, .25))
        self.assertIsNone(survey.vertical_shape(base.replace('half=bottom', 'half=top'), .5, .25))
        self.assertIsNone(survey.vertical_shape(base.replace('waterlogged=false', 'waterlogged=true'), .5, .25))

    def test_route_subsamples_use_physical_positions_across_blocks(self):
        state = 'minecraft:stone_brick_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]'
        snapshot = self.capture(Backend({(0, 64, 0): state, (0, 65, -1): state}),
                                box((0, 64, -1), (0, 70, 0)))
        points = [{'x': 0, 'z': z, 'sub_z': sub_z, 'standing_y': feet, 'route': 'stair'}
                  for z, sub_z, feet in [(0, .75, 64.5), (0, .25, 65), (-1, .75, 65.5), (-1, .25, 66)]]
        result = survey.verify_walkable(snapshot, points)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['checked_route_edges'], 3)
        points[1]['sub_x'] = .6
        result = survey.verify_walkable(snapshot, points)
        self.assertIn('non_cardinal_route_step', [f['reason'] for f in result['failures']])


if __name__ == '__main__':
    unittest.main()
