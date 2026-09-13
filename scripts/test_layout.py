"""Layout placement safety and resume checks; uses a simulated RPC world, never Minecraft."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('layout', Path(__file__).with_name('layout.py'))
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)

SCOPE = {'project_id': 'project', 'world_id': 'world', 'world_epoch': 'epoch'}


def document(blocks):
    return layout.normalize({'version': 1, 'scope': SCOPE, 'blocks': blocks})


def block(x, y=60, z=0, material='minecraft:lime_concrete', expected='minecraft:air'):
    return {'x': x, 'y': y, 'z': z, 'block': material, 'expected': expected}


class FakeBackend:
    def __init__(self):
        self.world, self.plans, self.operations, self.keys, self.calls = {}, {}, {}, {}, []
        self.lose_apply = False
        self.corrupt_after_apply = False
        self.context = {**SCOPE, 'checked_expected_blocks': True,
                        'region': {'min': {'x': -512, 'y': -64, 'z': -512}, 'max': {'x': 511, 'y': 319, 'z': 511}}}

    def state(self, at):
        return self.world.get(at, 'minecraft:air')

    def new_plan(self, changes, undo_of=None):
        plan_id = 'p' + str(len(self.plans))
        self.plans[plan_id] = {'changes': changes, 'undo_of': undo_of}
        return {'plan_id': plan_id, 'plan_hash': 'hash-' + plan_id,
                'changed_blocks': sum(e != d for _, e, d in changes)}

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'project_context':
            return self.context
        if method == 'region_inspect':
            lo, hi = params['min'], params['max']
            self.assert_bounded(lo, hi)
            return {'world_epoch': SCOPE['world_epoch'], 'truncated': False,
                    'blocks': [{'pos': {'x': x, 'y': y, 'z': z}, 'state': self.state((x, y, z))}
                               for y in range(lo['y'], hi['y'] + 1) for z in range(lo['z'], hi['z'] + 1)
                               for x in range(lo['x'], hi['x'] + 1)]}
        if method == 'build_prepare':
            desired = {}
            for op in params['recipe']['operations']:
                for y in range(op['min']['y'], op['max']['y'] + 1):
                    for z in range(op['min']['z'], op['max']['z'] + 1):
                        for x in range(op['min']['x'], op['max']['x'] + 1):
                            desired[(x, y, z)] = op['block']
            expected = {layout.position(e['pos']): e['state'] for e in params['expected_blocks']}
            if desired.keys() != expected.keys():
                raise AssertionError('Expected states must cover exactly the desired mask')
            if any(self.state(at) != state for at, state in expected.items()):
                raise RuntimeError('stale_snapshot')
            return self.new_plan([(at, expected[at], state) for at, state in desired.items()])
        if method == 'build_apply':
            key = params['idempotency_key']
            if key in self.keys:
                return self.operations[self.keys[key]]
            operation = 'o' + str(len(self.operations))
            plan = self.plans[params['plan_id']]
            written, status = 0, 'applied'
            receipts = []
            for at, expected, desired in plan['changes']:
                if self.state(at) != expected:
                    status = 'conflict'
                    break
                if expected != desired:
                    self.world[at] = desired
                    receipts.append((at, expected, desired))
                    written += 1
            self.operations[operation] = {'operation_id': operation, 'status': status, 'written': written,
                                          'plan_id': params['plan_id'], 'receipts': receipts}
            self.keys[key] = operation
            if self.corrupt_after_apply:
                self.world[plan['changes'][0][0]] = 'minecraft:gold_block'
            if self.lose_apply:
                self.lose_apply = False
                raise TimeoutError('Simulated response lost after the world changed')
            return self.operations[operation]
        if method == 'operation_status':
            return self.operations[params['operation_id']]
        if method == 'operation_undo_prepare':
            source = self.operations[params['operation_id']]
            changes = [(at, desired, expected) for at, expected, desired in source['receipts']]
            if any(self.state(at) != expected for at, expected, _ in changes):
                raise RuntimeError('Manual edit conflicts with guarded undo')
            return self.new_plan(changes, params['operation_id'])
        raise AssertionError(f'Unexpected RPC {method}')

    @staticmethod
    def assert_bounded(lo, hi):
        if layout.volume({'min': lo, 'max': hi}) > 4096:
            raise AssertionError('Unbounded inspection')


class LayoutTests(unittest.TestCase):
    def test_dense_layout_preserves_every_position_and_respects_all_budgets(self):
        value = document([block(x, y, z) for x in range(-20, 20) for y in range(63, 67) for z in range(-20, 20)])
        batches = layout.make_batches(value['blocks'])
        actual = [b for batch in batches for b in batch['blocks']]
        self.assertEqual(sorted(actual, key=layout.position), value['blocks'])
        self.assertGreater(len(batches), 1)
        for batch in batches:
            self.assertLessEqual(len(batch['blocks']), 4096)
            self.assertLessEqual(len(batch['recipe']['operations']), 256)
            self.assertLessEqual(len(layout.read_groups(batch['blocks'])), 32)
            for group in layout.read_groups(batch['blocks']):
                self.assertLessEqual(layout.volume(layout.bounds(group)), 4096)
        self.assertEqual(layout.make_batches(list(reversed(value['blocks']))), batches)

    def test_compression_does_not_fill_holes_or_merge_materials(self):
        value = document([block(0), block(1), block(3), block(4, material='minecraft:red_concrete')])
        operations = layout.make_batches(value['blocks'])[0]['recipe']['operations']
        self.assertEqual(len(operations), 3)
        lime = [o for o in operations if o['block'] == 'minecraft:lime_concrete']
        self.assertEqual([(o['min']['x'], o['max']['x']) for o in lime], [(0, 1), (3, 3)])

    def test_duplicate_and_invalid_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            document([block(0), block(0)])
        with self.assertRaisesRegex(ValueError, '32-bit'):
            document([block(True)])

    def test_manual_edit_stops_before_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend()
            backend.world[(0, 60, 0)] = 'minecraft:gold_block'
            with self.assertRaisesRegex(RuntimeError, 'Block mismatch'):
                layout.apply_layout(backend, document([block(0)]), Path(directory) / 'ledger.json')
            self.assertNotIn('build_prepare', [method for method, _ in backend.calls])
            self.assertEqual(backend.state((0, 60, 0)), 'minecraft:gold_block')

    def test_expected_surface_replacement_is_sent_atomically_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend()
            backend.world[(0, 60, 0)] = 'minecraft:grass_block'
            path = Path(directory) / 'ledger.json'
            result = layout.apply_layout(backend, document([block(0, expected='minecraft:grass_block')]), path, progress=lambda _: None)
            self.assertEqual(result['status'], 'completed')
            prepared = next(params for method, params in backend.calls if method == 'build_prepare')
            self.assertEqual(prepared['expected_blocks'], [{'pos': {'x': 0, 'y': 60, 'z': 0}, 'state': 'minecraft:grass_block'}])
            self.assertIn('verified_at', json.loads(path.read_text())['batches'][0])

    def test_lost_apply_response_resumes_same_key_without_failing_old_expected_read(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            backend.lose_apply = True
            value = document([block(0)])
            with self.assertRaises(TimeoutError):
                layout.apply_layout(backend, value, path, progress=lambda _: None)
            self.assertEqual(backend.state((0, 60, 0)), 'minecraft:lime_concrete')
            before = json.loads(path.read_text())['batches'][0]
            self.assertIn('idempotency_key', before)
            self.assertNotIn('operation_id', before)
            layout.apply_layout(backend, value, path, progress=lambda _: None)
            applies = [params for method, params in backend.calls if method == 'build_apply']
            self.assertEqual(len(applies), 2)
            self.assertEqual(applies[0], applies[1])
            self.assertEqual(len(backend.plans), 1)
            self.assertTrue(json.loads(path.read_text())['completed'])

    def test_existing_conflict_is_not_reprepared(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            value = document([block(0)])
            manifest = layout.load_or_create(path, value, layout.make_batches(value['blocks']))
            manifest['batches'][0]['status'] = 'conflict'
            layout.terrain.save(path, manifest)
            with self.assertRaisesRegex(RuntimeError, 'stopped on conflict'):
                layout.apply_layout(backend, value, path)
            self.assertEqual([method for method, _ in backend.calls], ['project_context'])

    def test_old_server_scope_and_changed_input_are_rejected_without_write(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            value = document([block(0)])
            backend.context['checked_expected_blocks'] = False
            with self.assertRaisesRegex(RuntimeError, 'atomic checked_expected_blocks'):
                layout.apply_layout(backend, value, path)
            backend.context['checked_expected_blocks'] = True
            backend.context['world_epoch'] = 'other'
            with self.assertRaisesRegex(RuntimeError, 'another project'):
                layout.apply_layout(backend, value, path)
            backend.context['world_epoch'] = 'epoch'
            layout.load_or_create(path, value, layout.make_batches(value['blocks']))
            with self.assertRaisesRegex(RuntimeError, 'digest'):
                layout.apply_layout(backend, document([block(1)]), path)
            self.assertFalse(backend.plans)

    def test_post_apply_verification_stops_before_next_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            # More than 32 separate read cells creates several small, cheap batches.
            value = document([block(x * 16, z=z * 16) for x in range(-4, 5) for z in range(-4, 5)])
            backend.corrupt_after_apply = True
            with self.assertRaisesRegex(RuntimeError, 'Block mismatch'):
                layout.apply_layout(backend, value, path)
            self.assertEqual(len(backend.plans), 1)
            saved = json.loads(path.read_text())
            self.assertNotIn('verified_at', saved['batches'][0])
            self.assertNotIn('completed', saved)

    def test_undo_is_reverse_order_and_refuses_resume_apply_after_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            value = document([block(x * 16, z=z * 16) for x in range(-4, 5) for z in range(-4, 5)])
            layout.apply_layout(backend, value, path, progress=lambda _: None)
            source_ids = [e['operation_id'] for e in json.loads(path.read_text())['batches']]
            result = layout.undo_layout(backend, path, progress=lambda _: None)
            self.assertEqual(result['status'], 'undone')
            undo_ids = [params['operation_id'] for method, params in backend.calls if method == 'operation_undo_prepare']
            self.assertEqual(undo_ids, list(reversed(source_ids)))
            self.assertTrue(all(backend.state(layout.position(b)) == b['expected'] for b in value['blocks']))
            with self.assertRaisesRegex(RuntimeError, 'begun undo'):
                layout.apply_layout(backend, value, path)

    def test_undo_does_not_start_an_unknown_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            backend.lose_apply = True
            with self.assertRaises(TimeoutError):
                layout.apply_layout(backend, document([block(0)]), path)
            calls_before = len(backend.calls)
            with self.assertRaisesRegex(RuntimeError, 'Uncertain apply'):
                layout.undo_layout(backend, path)
            self.assertEqual([m for m, _ in backend.calls[calls_before:]], ['project_context'])

    def test_undo_preserves_later_manual_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, path = FakeBackend(), Path(directory) / 'ledger.json'
            layout.apply_layout(backend, document([block(0)]), path, progress=lambda _: None)
            backend.world[(0, 60, 0)] = 'minecraft:gold_block'
            with self.assertRaisesRegex(RuntimeError, 'Manual edit'):
                layout.undo_layout(backend, path)
            self.assertEqual(backend.state((0, 60, 0)), 'minecraft:gold_block')


if __name__ == '__main__':
    unittest.main()
