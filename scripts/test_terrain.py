"""Regression checks for resumable local batches; no live world needed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('terrain', Path(__file__).with_name('terrain.py'))
terrain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terrain)


class BatchTests(unittest.TestCase):
    def test_lost_apply_response_reuses_persisted_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'batch.json'
            entry = {'plan_id': 'plan', 'plan_hash': 'hash'}
            manifest = {'tiles': [entry]}
            calls = []
            class Backend:
                def call(self, method, **params):
                    calls.append((method, params))
                    if len(calls) == 1:
                        raise TimeoutError('lost response')
                    return {'operation_id': 'operation'}
            backend = Backend()
            with self.assertRaises(TimeoutError):
                terrain.apply_plan(backend, entry, manifest, path)
            saved = terrain.json.loads(path.read_text())
            self.assertIn('idempotency_key', saved['tiles'][0])
            with patch.object(terrain, 'finish', return_value={'status': 'applied', 'written': 7}):
                terrain.apply_plan(backend, saved['tiles'][0], saved, path)
            self.assertEqual(calls[0], calls[1])
            self.assertEqual(terrain.json.loads(path.read_text())['tiles'][0]['operation_id'], 'operation')

    def test_conflict_is_persisted_and_reported_not_reprepared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'batch.json'
            entry = {'plan_id': 'p', 'plan_hash': 'h', 'operation_id': 'o'}
            class Backend:
                def call(self, *args, **kwargs):
                    raise AssertionError('Must not start another apply')
            with patch.object(terrain, 'finish', return_value={'status': 'conflict', 'written': 3}):
                with self.assertRaisesRegex(RuntimeError, 'conflict'):
                    terrain.apply_plan(Backend(), entry, {'tiles': [entry]}, path)
            self.assertEqual(terrain.json.loads(path.read_text())['tiles'][0]['status'], 'conflict')

    def test_undo_never_starts_an_unknown_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'batch.json'
            scope = {'project_id': 'p', 'world_id': 'w', 'world_epoch': 'e'}
            terrain.save(path, {'scope': scope, 'tiles': [{'idempotency_key': 'k', 'plan_id': 'p', 'plan_hash': 'h'}]})
            class Backend:
                def __init__(self, *args):
                    pass
                def call(self, method, **params):
                    if method != 'project_context':
                        raise AssertionError('Undo must not initiate a write to discover unknown apply outcome')
                    return scope
            args = terrain.argparse.Namespace(config=Path('unused'), console=True, manifest=path, command='undo')
            with patch.object(terrain, 'Backend', Backend):
                with self.assertRaisesRegex(RuntimeError, 'Uncertain apply'):
                    terrain.run_batch(args)


if __name__ == '__main__':
    unittest.main()
