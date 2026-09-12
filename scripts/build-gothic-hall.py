#!/usr/bin/env python3
"""Plan/apply/verify the Gothic reference build through checked Paper editor operations."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import uuid

from builds.gothic_hall.scene import build_scene, manifest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.runtime/gothic-hall'
CONFIG = ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml'

def save(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def point_key(value):
    return value['x'], value['y'], value['z']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'verify'])
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    config = CONFIG.read_text()
    def scalar(key):
        return re.search(r'^' + re.escape(key) + r':[ \t]*(.*?)$', config, re.M).group(1).strip().strip("'\"")
    scope = {'player_id': scalar('owner-uuid'), 'project_id': scalar('project-id')}
    assert scope['player_id'], 'An online project owner is required'
    token = scalar('agent-token')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def rpc(method, params):
        for attempt in range(100):
            data = {'method': method, 'params': {**params, **scope}, 'requestId': str(uuid.uuid4())}
            req = urllib.request.Request('http://127.0.0.1:' + scalar('http-port') + '/v1/rpc',
                data=json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            try:
                with opener.open(req, timeout=30) as response: body = json.load(response)
            except urllib.error.HTTPError as error:
                body = json.load(error)
            if body.get('ok'): return body['result']
            code = body.get('error', {}).get('code', 'unknown')
            if code == 'busy': time.sleep(.1); continue
            raise RuntimeError(f'{method}: {code}; no blind overwrite or replay performed')
        raise RuntimeError('Paper remained busy')

    context = rpc('project_context', {})
    if args.action == 'plan':
        voxels = build_scene(); model = manifest(voxels)
        allowed = set(context['supported_materials'])
        assert all(block.split('[')[0] in allowed for block in model['palette']), 'Unsupported material in blueprint'
        for batch in model['batches']:
            assert batch['blocks'] <= 4096
            expanded = {}
            for operation in batch['recipe']['operations']:
                a, b = operation['min'], operation['max']
                for y in range(a['y'], b['y'] + 1):
                    for z in range(a['z'], b['z'] + 1):
                        for x in range(a['x'], b['x'] + 1):
                            assert (x, y, z) not in expanded, 'Compression overlapped a voxel'
                            local = tuple(n - o for n, o in zip((x, y, z), model['origin']))
                            assert voxels.blocks[local] == operation['block'], 'Compression changed the blueprint'
                            expanded[(x, y, z)] = operation['block']
            assert len(expanded) == batch['blocks']
            for axis in ('x', 'y', 'z'):
                assert context['region']['min'][axis] <= batch['min'][axis] <= batch['max'][axis] <= context['region']['max'][axis]
        model['world_id'] = context['world_id']; model['world_epoch'] = context['world_epoch']
        path = OUTPUT / 'manifest.json'
        if (OUTPUT / 'ledger.json').exists() and path.exists():
            assert digest(json.loads(path.read_text())) == digest(model), 'Existing live build has a different blueprint; preserve it'
        save(path, model)
        print(json.dumps({'blocks': model['blocks'], 'batches': len(model['batches']), 'stages': model['stages'],
            'max_recipe_operations': max(len(b['recipe']['operations']) for b in model['batches'])}), flush=True)
        return

    model = json.loads((OUTPUT / 'manifest.json').read_text())
    assert model['world_id'] == context['world_id'] and model['world_epoch'] == context['world_epoch'], 'World identity changed'
    ledger_path = OUTPUT / 'ledger.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'manifest_sha256': digest(model), 'batches': {}}
    assert ledger['manifest_sha256'] == digest(model), 'Blueprint changed after writing began'
    for index, batch in enumerate(model['batches'], 1):
        record = ledger['batches'].get(batch['key'])
        if args.action == 'apply':
            if record is None:
                before = rpc('region_inspect', {'min': batch['min'], 'max': batch['max'], 'detail': 'summary'})
                assert set(before['palette']) == {'minecraft:air'}, f"Occupied site in batch {batch['key']}; preserve and review"
                plan = rpc('build_prepare', {'recipe': batch['recipe']})
                # The immutable persisted plan must still agree with the reviewed empty site.
                envelope = json.loads((CONFIG.parent / 'journal/plans' / (plan['plan_id'] + '.json')).read_text())
                persisted = json.loads(envelope['payload'])
                assert all(change['expected'] == 'minecraft:air' for change in persisted['changes']), 'Concurrent edit before prepare; stop'
                record = {'plan': plan, 'idempotency_key': 'gothic-hall-' + plan['plan_id']}
                ledger['batches'][batch['key']] = record; save(ledger_path, ledger)
            if not record.get('operation_id'):
                operation = rpc('build_apply', {**record['plan'], 'idempotency_key': record['idempotency_key']})
                record['operation_id'] = operation['operation_id']; save(ledger_path, ledger)
            for _ in range(600):
                status = rpc('operation_status', {'operation_id': record['operation_id']})
                if status['status'] not in ('queued', 'applying'): break
                time.sleep(.1)
            record['status'] = status; save(ledger_path, ledger)
            assert status['status'] == 'applied', f"Batch {batch['key']} stopped: {status['status']}; inspect the operation"
            print(json.dumps({'batch': index, 'of': len(model['batches']), 'key': batch['key'], 'written': status['written'],
                'stages': batch['stages'], 'operation_id': record['operation_id']}), flush=True)
        else:
            assert record and record.get('status', {}).get('status') == 'applied', 'Build is not fully applied'
            envelope = json.loads((CONFIG.parent / 'journal/plans' / (record['plan']['plan_id'] + '.json')).read_text())
            planned = json.loads(envelope['payload'])
            current = rpc('region_inspect', {'min': batch['min'], 'max': batch['max'], 'detail': 'blocks'})
            states = {point_key(block['pos']): block['state'] for block in current['blocks']}
            mismatches = [change['pos'] for change in planned['changes'] if states[point_key(change['pos'])] != change['desired']]
            assert not mismatches, f"Live geometry differs in batch {batch['key']} at {mismatches[:5]}; preserve edits"
    if args.action == 'verify':
        report = {'status': 'verified', 'blocks': model['blocks'], 'batches': len(model['batches']), 'verified_at': time.time(),
                  'manifest_sha256': digest(model), 'scope': scope}
        save(OUTPUT / 'verification.json', report)
        print(json.dumps(report), flush=True)
    else:
        print('GOTHIC HALL BUILD APPLIED', flush=True)

if __name__ == '__main__':
    main()
