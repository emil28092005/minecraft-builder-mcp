#!/usr/bin/env python3
"""Place an explicit block layout with checked snapshots, resumable receipts, and guarded undo."""
import argparse
from collections import Counter, defaultdict
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

spec = importlib.util.spec_from_file_location('layout_terrain', Path(__file__).with_name('terrain.py'))
terrain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terrain)
ROOT = terrain.ROOT
MAX_BLOCKS = 4096
MAX_OPERATIONS = 256
MAX_READ_CELLS = 32
SCOPE_KEYS = ('project_id', 'world_id', 'world_epoch')
FAILED = ('conflict', 'cancelled', 'failed', 'recovery_required')
STATE = re.compile(r'minecraft:[a-z0-9_]+(?:\[[a-z0-9_=,]+\])?\Z')


def position(block):
    return tuple(block[axis] for axis in ('x', 'y', 'z'))


def coordinates(at):
    return dict(zip(('x', 'y', 'z'), at))


def normalize(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Layout version must be 1')
    scope = value.get('scope', {})
    if not isinstance(scope, dict) or any(not isinstance(scope.get(k), str) or not scope[k] for k in SCOPE_KEYS):
        raise ValueError('Layout requires project_id, world_id, and world_epoch')
    source = value.get('blocks')
    if not isinstance(source, list) or not 1 <= len(source) <= 1_000_000:
        raise ValueError('Layout must contain 1..1,000,000 explicit blocks')
    blocks, seen = [], set()
    for raw in source:
        if not isinstance(raw, dict):
            raise ValueError('Every block must be an object')
        if any(type(raw.get(a)) is not int or not -2**31 <= raw[a] < 2**31 for a in ('x', 'y', 'z')):
            raise ValueError('Block coordinates must be signed 32-bit integers')
        at = position(raw)
        if at in seen:
            raise ValueError(f'Duplicate block position: {at}')
        seen.add(at)
        block, expected = raw.get('block'), raw.get('expected', 'minecraft:air')
        if any(not isinstance(s, str) or len(s) > 512 or not STATE.fullmatch(s) for s in (block, expected)):
            raise ValueError(f'Invalid block state at {at}; use full minecraft: names')
        blocks.append({**coordinates(at), 'block': block, 'expected': expected})
    blocks.sort(key=position)
    return {'version': 1, 'scope': {k: scope[k] for k in SCOPE_KEYS}, 'blocks': blocks}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_cell(block):
    return (block['x'] // 16, block['y'] // 16, block['z'] // 16)


def bounds(blocks):
    return {'min': {a: min(b[a] for b in blocks) for a in ('x', 'y', 'z')},
            'max': {a: max(b[a] for b in blocks) for a in ('x', 'y', 'z')}}


def volume(box):
    return (box['max']['x'] - box['min']['x'] + 1) * (box['max']['y'] - box['min']['y'] + 1) * (box['max']['z'] - box['min']['z'] + 1)


def read_groups(blocks):
    cells = defaultdict(list)
    for block in blocks:
        cells[read_cell(block)].append(block)
    return [cells[key] for key in sorted(cells)]


def compressed_runs(blocks):
    """Runs never cross a 16³ read cell, so every inspection is bounded to 4096 voxels."""
    rows = defaultdict(list)
    for block in blocks:
        rows[(*read_cell(block), block['y'], block['z'], block['block'])].append(block)
    for key in sorted(rows):
        row = sorted(rows[key], key=lambda b: b['x'])
        run = []
        for block in row:
            if run and block['x'] != run[-1]['x'] + 1:
                yield run
                run = []
            run.append(block)
        if run:
            yield run


def make_batches(blocks):
    batches, batch, cells = [], [], set()
    for run in compressed_runs(blocks):
        cell = read_cell(run[0])
        if batch and (len(batch) >= MAX_OPERATIONS or sum(len(r) for r in batch) + len(run) > MAX_BLOCKS
                      or len(cells | {cell}) > MAX_READ_CELLS):
            batches.append(batch)
            batch, cells = [], set()
        batch.append(run)
        cells.add(cell)
    if batch:
        batches.append(batch)
    result = []
    for index, runs in enumerate(batches):
        selected = [b for run in runs for b in run]
        operations = [{'type': 'box', 'min': coordinates(position(run[0])),
                       'max': coordinates(position(run[-1])), 'block': run[0]['block']} for run in runs]
        result.append({'index': index, 'blocks': selected, 'recipe': {'version': 1, 'operations': operations}})
    return result


def check_context(context, layout, require_checked=True):
    if {key: context.get(key) for key in SCOPE_KEYS} != layout['scope']:
        raise RuntimeError('Layout belongs to another project/world/epoch')
    if require_checked and context.get('checked_expected_blocks') is not True:
        raise RuntimeError('Server lacks atomic checked_expected_blocks; update the plugin before placing this layout')
    area = context.get('region', {})
    for block in layout['blocks']:
        if any(not area.get('min', {}).get(a, 1) <= block[a] <= area.get('max', {}).get(a, 0) for a in ('x', 'y', 'z')):
            raise RuntimeError(f'Layout exceeds selected project area at {position(block)}')


def inspect_states(backend, blocks, epoch):
    states = {}
    for group in read_groups(blocks):
        box = bounds(group)
        result = backend.call('region_inspect', **box, detail='blocks')
        if result.get('world_epoch') != epoch or result.get('truncated') is not False:
            raise RuntimeError('Inspection was truncated or returned a different world epoch')
        found = {}
        for item in result.get('blocks', []):
            at = position(item['pos'])
            if at in found:
                raise RuntimeError('Inspection contained duplicate positions')
            found[at] = item['state']
        if len(found) != volume(box):
            raise RuntimeError('Inspection did not return the complete bounded region')
        for block in group:
            at = position(block)
            if at not in found:
                raise RuntimeError(f'Inspection omitted {at}')
            states[at] = found[at]
    return states


def verify(backend, blocks, epoch, field):
    states = inspect_states(backend, blocks, epoch)
    mismatches = [(position(b), b[field], states[position(b)]) for b in blocks if states[position(b)] != b[field]]
    if mismatches:
        at, expected, actual = mismatches[0]
        raise RuntimeError(f'Block mismatch at {at}: expected {expected}, found {actual} ({len(mismatches)} mismatches); no blind overwrite')
    return len(blocks)


def load_or_create(path, layout, batches):
    expected_digest = digest(layout)
    snapshot = path.with_suffix(path.suffix + '.input.json')
    if path.exists():
        manifest = json.loads(path.read_text())
        if (manifest.get('version') != 1 or manifest.get('planning_version') != 1
                or manifest.get('scope') != layout['scope'] or manifest.get('input_digest') != expected_digest):
            raise RuntimeError('Manifest layout digest, planning version, or project/world/epoch differs; do not reuse it')
        if not snapshot.exists() or digest(normalize(json.loads(snapshot.read_text()))) != expected_digest:
            raise RuntimeError('Saved layout input is missing or changed')
        if len(manifest.get('batches', [])) != len(batches):
            raise RuntimeError('Saved batch count differs from deterministic planner')
        for saved, planned in zip(manifest['batches'], batches):
            if saved.get('index') != planned['index'] or saved.get('digest') != digest(planned):
                raise RuntimeError('Saved batch differs from deterministic planner')
        return manifest
    if snapshot.exists() and digest(normalize(json.loads(snapshot.read_text()))) != expected_digest:
        raise RuntimeError('An orphaned layout input differs; choose a new manifest path')
    terrain.save(snapshot, layout)
    manifest = {'version': 1, 'planning_version': 1, 'scope': layout['scope'],
                'input_digest': expected_digest, 'blocks': len(layout['blocks']),
                'batches': [{'index': b['index'], 'digest': digest(b), 'blocks': len(b['blocks'])} for b in batches]}
    terrain.save(path, manifest)
    return manifest


def apply_layout(backend, layout, path, progress=print):
    check_context(backend.call('project_context'), layout)
    batches = make_batches(layout['blocks'])
    manifest = load_or_create(path, layout, batches)
    if manifest.get('undo_started') or manifest.get('undone') or any('undo' in e for e in manifest['batches']):
        raise RuntimeError('Layout has begun undo; finish undo and use a new manifest for new work')
    epoch = layout['scope']['world_epoch']
    for batch, entry in zip(batches, manifest['batches']):
        if entry.get('status') in FAILED:
            raise RuntimeError(f"Batch {entry['index']} stopped on {entry['status']}; inspect or undo it instead of creating a new plan")
        if entry.get('status') == 'applied':
            verify(backend, batch['blocks'], epoch, 'block')
            continue
        # An unknown apply may already have changed the world: resolve its same stable key first.
        if 'idempotency_key' not in entry and 'operation_id' not in entry:
            verify(backend, batch['blocks'], epoch, 'expected')
            if 'plan_id' not in entry:
                prepared = backend.call('build_prepare', recipe=batch['recipe'], expected_blocks=[
                    {'pos': coordinates(position(b)), 'state': b['expected']} for b in batch['blocks']])
                entry.update(prepared)
                terrain.save(path, manifest)
        terrain.apply_plan(backend, entry, manifest, path)
        verify(backend, batch['blocks'], epoch, 'block')
        entry['verified_at'] = int(time.time())
        terrain.save(path, manifest)
        progress(json.dumps({'batch': entry['index'] + 1, 'batches': len(batches), 'status': 'verified',
                             'written': entry['written'], 'operation_id': entry['operation_id']}))
    manifest['completed'] = True
    terrain.save(path, manifest)
    return {'status': 'completed', 'blocks': len(layout['blocks']), 'batches': len(batches), 'manifest': str(path)}


def undo_layout(backend, path, progress=print):
    snapshot = path.with_suffix(path.suffix + '.input.json')
    if not path.exists() or not snapshot.exists():
        raise RuntimeError('Manifest or saved layout input not found')
    layout = normalize(json.loads(snapshot.read_text()))
    check_context(backend.call('project_context'), layout, require_checked=False)
    batches = make_batches(layout['blocks'])
    manifest = load_or_create(path, layout, batches)
    for entry in manifest['batches']:
        if 'idempotency_key' in entry and 'operation_id' not in entry:
            raise RuntimeError('Uncertain apply response. Resume apply with the same manifest first; undo will not start an unconfirmed write')
    manifest['undo_started'] = True
    terrain.save(path, manifest)
    for batch, entry in reversed(list(zip(batches, manifest['batches']))):
        if 'operation_id' not in entry:
            continue
        source = terrain.finish(backend, entry['operation_id'])
        if source['status'] == 'recovery_required':
            raise RuntimeError('Interrupted server operation requires recovery review before undo')
        if not source['written']:
            continue
        if 'undo' not in entry:
            entry['undo'] = backend.call('operation_undo_prepare', operation_id=entry['operation_id'])
            terrain.save(path, manifest)
        if entry['undo'].get('status') in FAILED:
            raise RuntimeError(f"Undo stopped on {entry['undo']['status']}; inspect conflicts before taking further action")
        terrain.apply_plan(backend, entry['undo'], manifest, path)
        # Only a fully applied source has receipts for every changed position. A guarded partial
        # undo intentionally leaves conflicting manual edits alone; the server verifies its receipts.
        if source['status'] == 'applied':
            verify(backend, batch['blocks'], layout['scope']['world_epoch'], 'expected')
            entry['undo']['verified_at'] = int(time.time())
        else:
            entry['undo']['verification'] = 'server_receipts_only_for_partial_source'
        terrain.save(path, manifest)
        progress(json.dumps({'batch': entry['index'] + 1, 'status': 'undone', 'written': entry['undo']['written']}))
    manifest['undone'] = True
    terrain.save(path, manifest)
    return {'status': 'undone', 'manifest': str(path)}


def report(layout):
    batches = make_batches(layout['blocks'])
    boxes = [bounds(group) for b in batches for group in read_groups(b['blocks'])]
    return {'status': 'offline_report', 'scope': layout['scope'], 'input_digest': digest(layout),
            'blocks': len(layout['blocks']), 'batches': len(batches), 'bounds': bounds(layout['blocks']),
            'materials': dict(sorted(Counter(b['block'] for b in layout['blocks']).items())),
            'inspection_requests_per_pass': len(boxes), 'inspection_voxels_per_pass': sum(map(volume, boxes)),
            'max_inspection_volume': max(map(volume, boxes)),
            'max_batch_blocks': max(len(b['blocks']) for b in batches),
            'max_batch_operations': max(len(b['recipe']['operations']) for b in batches)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('report', help='Report deterministic batching offline; no server required')
    p.add_argument('layout', type=Path)
    descriptions = {'prepare': 'Save immutable input and check current blocks without editing the world',
                    'apply': 'Place or resume the layout through checked, journalled RPC',
                    'undo': 'Undo recorded layout operations in reverse order, preserving later edits'}
    for name, description in descriptions.items():
        p = sub.add_parser(name, help=description)
        if name != 'undo':
            p.add_argument('layout', type=Path)
        p.add_argument('--manifest', type=Path, required=True)
        p.add_argument('--config', type=Path, default=ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml')
        p.add_argument('--console', action='store_true', help='Only for an explicitly configured isolated fixture')
        if name != 'prepare':
            p.add_argument('--execute', action='store_true', required=True, help='Explicitly perform this world edit')
    args = parser.parse_args()
    if args.command == 'report':
        print(json.dumps(report(normalize(json.loads(args.layout.read_text()))), indent=2))
        return
    path = args.manifest.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backend = terrain.Backend(args.config, args.console)
        if args.command == 'undo':
            result = undo_layout(backend, path, progress=lambda s: print(s, flush=True))
        else:
            layout = normalize(json.loads(args.layout.read_text()))
            if args.command == 'prepare':
                check_context(backend.call('project_context'), layout)
                batches = make_batches(layout['blocks'])
                manifest = load_or_create(path, layout, batches)
                if any('plan_id' in e for e in manifest['batches']):
                    raise RuntimeError('This manifest already has plans; use apply to resume, or report for an offline summary')
                for batch in batches:
                    verify(backend, batch['blocks'], layout['scope']['world_epoch'], 'expected')
                result = {**report(layout), 'status': 'prepared_input', 'manifest': str(path)}
            else:
                result = apply_layout(backend, layout, path, progress=lambda s: print(s, flush=True))
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(f'Layout stopped: {error}', file=sys.stderr)
        sys.exit(1)
