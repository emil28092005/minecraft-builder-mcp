#!/usr/bin/env python3
"""Prepare/apply 18 checked Gothic-hall corrections; verify the entire original build plus this patch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from builds.gothic_hall.scene import build_scene

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.runtime/gothic-hall'
CONFIG = ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml'
LEDGER = OUTPUT / 'finish-ledger.json'
STAIR = 'minecraft:stone_brick_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def point(value):
    return value['x'], value['y'], value['z']


def position(values):
    return dict(zip(('x', 'y', 'z'), values))


def canonical(state):
    if '[' not in state:
        return state
    name, properties = state.rstrip(']').split('[', 1)
    return name + '[' + ','.join(sorted(properties.split(','))) + ']'


def envelope(path, kind):
    data = json.loads(path.read_text())
    require(data.get('format') == 1 and data.get('kind') == kind, 'Unexpected journal envelope')
    require(data.get('id') == path.stem, 'Journal identity mismatch')
    require(hashlib.sha256(data['payload'].encode()).hexdigest() == data['sha256'], 'Journal checksum mismatch')
    value = json.loads(data['payload'])
    require(value['id'] == path.stem, 'Journal payload identity mismatch')
    return value, data['sha256']


def save(path, data, immutable=False):
    """Fully persist a complete JSON file; immutable files are never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.finish-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, path)  # Atomic publication with fail-if-existing semantics.
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Paper RPC redirect refused')


class Backend:
    def __init__(self):
        config = CONFIG.read_text()

        def scalar(name):
            match = re.search(r'^' + re.escape(name) + r':[ \t]*(.*?)$', config, re.M)
            require(match is not None, 'Required Paper configuration field is missing')
            return match.group(1).strip().strip("'\"")

        self.scope = {'player_id': scalar('owner-uuid'), 'project_id': scalar('project-id')}
        require(self.scope['player_id'], 'An online bound owner is required')
        self.token = scalar('agent-token')
        port = scalar('http-port')
        require(port.isdigit() and 1 <= int(port) <= 65535, 'Invalid Paper port')
        self.url = 'http://127.0.0.1:' + port + '/v1/rpc'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def rpc(self, method, params):
        for _ in range(100):
            payload = {'method': method, 'params': {**params, **self.scope}, 'requestId': str(uuid.uuid4())}
            request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={
                'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
            try:
                with self.opener.open(request, timeout=30) as response:
                    raw = response.read(2_097_153)
            except urllib.error.HTTPError as error:
                raw = error.read(2_097_153)
            except (OSError, urllib.error.URLError):
                raise RuntimeError(f'{method}: connection interrupted; reuse the existing finish ledger') from None
            require(len(raw) <= 2_097_152, 'Paper response exceeded limit')
            body = json.loads(raw)
            if body.get('ok'):
                return body['result']
            code = body.get('error', {}).get('code', 'unknown')
            if code == 'busy':
                time.sleep(.1)
                continue
            raise RuntimeError(f'{method}: {code}; no blind overwrite or new idempotency key was used')
        raise RuntimeError('Paper remained busy')


def references():
    model = json.loads((OUTPUT / 'manifest.json').read_text())
    base = json.loads((OUTPUT / 'ledger.json').read_text())
    require(base['manifest_sha256'] == digest(model), 'Original manifest no longer matches its ledger')
    require(model['blocks'] == 29354 and len(model['batches']) == len(base['batches']) == 87,
            'Expected the original completed 29,354-block, 87-plan build')
    require({b['key'] for b in model['batches']} == set(base['batches']), 'Original batch set changed')
    states, plans = {}, {}
    for batch in model['batches']:
        record = base['batches'][batch['key']]
        require(record.get('status', {}).get('status') == 'applied', 'Original build has an incomplete batch')
        summary = record['plan']
        plan, checksum = envelope(CONFIG.parent / 'journal/plans' / (summary['plan_id'] + '.json'), 'plan')
        require(checksum == summary['plan_hash'], 'Original saved plan hash changed')
        require(plan['worldEpoch'] == model['world_epoch'] and plan['region']['worldId'] == model['world_id'],
                'Original plan world identity differs')
        require(len(plan['changes']) == batch['blocks'], 'Original plan block count differs')
        for change in plan['changes']:
            at = point(change['pos'])
            require(at not in states, 'Original plans overlap')
            states[at] = change['desired']
        plans[batch['key']] = {'plan_id': plan['id'], 'sha256': checksum, 'plan': plan}
    require(len(states) == model['blocks'], 'Original saved plans are incomplete')
    return model, states, plans


def targets(model, states):
    scene = build_scene()
    local = [(x, 30, z) for x in (6, 32) for z in (14, 22, 30, 38, 46, 54)]
    local += [(x, 34, 12) for x in (7, 31)]
    local += [(35, 8, z) for z in range(36, 40)]
    require(len(local) == len(set(local)) == 18, 'Finish mask must contain exactly 18 cells')
    result = []
    for at in local:
        world = tuple(a + b for a, b in zip(at, model['origin']))
        before = states.get(world)
        require(before is not None and canonical(scene.blocks.get(at, 'minecraft:air')) == canonical(before),
                f'Frozen scene differs from original canonical plan at local {at}')
        desired = STAIR if at[0] == 35 else 'minecraft:stone_bricks'
        if at[0] != 35:
            require(before == 'minecraft:stone_brick_slab[type=bottom,waterlogged=false]',
                    f'Expected the original pinnacle cap at local {at}')
        else:
            require(before == 'minecraft:spruce_planks', f'Expected the original gallery floor at local {at}')
        result.append({'local': list(at), 'pos': position(world), 'expected': before, 'desired': desired})
    return result


def inspect_patch(backend, changes, field):
    for group in ([c for c in changes if c['local'][1] == y] for y in (30, 34, 8)):
        locations = [point(c['pos']) for c in group]
        lo = position([min(p[i] for p in locations) for i in range(3)])
        hi = position([max(p[i] for p in locations) for i in range(3)])
        result = backend.rpc('region_inspect', {'min': lo, 'max': hi, 'detail': 'blocks'})
        live = {point(b['pos']): b['state'] for b in result['blocks']}
        for change in group:
            require(live.get(point(change['pos'])) == change[field],
                    f'Live {field} mismatch at local {tuple(change["local"])}; preserve current world')


def validate_saved_finish(ledger, changes, model, plans):
    require(ledger['version'] == 1 and ledger['manifest_sha256'] == digest(model), 'Finish ledger blueprint mismatch')
    require(ledger['changes'] == changes, 'Immutable finish mask changed')
    sources = {key: {'plan_id': value['plan_id'], 'sha256': value['sha256']} for key, value in plans.items()}
    require(ledger['source_plans'] == sources, 'Original plan references changed')
    plan, checksum = envelope(CONFIG.parent / 'journal/plans' / (ledger['plan']['plan_id'] + '.json'), 'plan')
    require(checksum == ledger['plan']['plan_hash'], 'Prepared finish plan hash mismatch')
    require(plan['worldEpoch'] == model['world_epoch'] and plan['region']['worldId'] == model['world_id'],
            'Finish plan world identity changed')
    expected = {point(c['pos']): (c['expected'], c['desired']) for c in changes}
    actual = {point(c['pos']): (c['expected'], c['desired']) for c in plan['changes']}
    require(len(plan['changes']) == 18 and actual == expected,
            'Prepared expected/desired states differ from reviewed original states; do not apply')


def operation_id(ledger):
    matches = []
    for path in (CONFIG.parent / 'journal/operations').glob('*.json'):
        operation, _ = envelope(path, 'operation')
        if operation['planId'] == ledger['plan']['plan_id'] and operation['idempotencyKey'] == ledger['idempotency_key']:
            matches.append(operation['id'])
    require(len(matches) <= 1, 'Multiple operations share the finish identity')
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'verify'])
    args = parser.parse_args()
    model, originals, plans = references()
    changes = targets(model, originals)
    backend = Backend()
    context = backend.rpc('project_context', {})
    require(context['world_id'] == model['world_id'] and context['world_epoch'] == model['world_epoch'],
            'Live world identity changed')
    if args.action == 'plan' and not LEDGER.exists():
        inspect_patch(backend, changes, 'expected')
        recipe = {'version': 1, 'operations': [
            {'type': 'box', 'min': c['pos'], 'max': c['pos'], 'block': c['desired']} for c in changes]}
        summary = backend.rpc('build_prepare', {'recipe': recipe})
        ledger = {'version': 1, 'manifest_sha256': digest(model), 'scope': backend.scope,
                  'source_plans': {k: {'plan_id': p['plan_id'], 'sha256': p['sha256']} for k, p in plans.items()},
                  'changes': changes, 'plan': summary, 'idempotency_key': 'gothic-hall-finish-' + summary['plan_id']}
        validate_saved_finish(ledger, changes, model, plans)
        save(LEDGER, ledger, immutable=True)
    require(LEDGER.is_file(), 'Run plan first; finish-ledger.json must be durably saved before applying')
    ledger = json.loads(LEDGER.read_text())
    validate_saved_finish(ledger, changes, model, plans)
    require(ledger['scope'] == backend.scope, 'Finish owner/project scope changed')
    if args.action == 'plan':
        print(json.dumps({'status': 'prepared', 'changes': 18, 'plan_id': ledger['plan']['plan_id'],
                          'expires_at': ledger['plan']['expires_at'], 'immutable_ledger': str(LEDGER)}))
        return
    ident = operation_id(ledger)
    if args.action == 'apply':
        # Always keep the persisted key. A lost response must never cause a fresh operation.
        if ident is None:
            result = backend.rpc('build_apply', {**ledger['plan'], 'idempotency_key': ledger['idempotency_key']})
            ident = result['operation_id']
        for _ in range(600):
            status = backend.rpc('operation_status', {'operation_id': ident})
            if status['status'] not in ('queued', 'applying'):
                break
            time.sleep(.1)
        require(status['status'] == 'applied', f'Finish operation stopped: {status["status"]}; inspect before continuing')
        inspect_patch(backend, changes, 'desired')
        print(json.dumps({'status': 'applied', 'changes': 18, 'written': status['written'], 'operation_id': ident}))
        return
    require(ident is not None, 'Finish operation has not been applied')
    status = backend.rpc('operation_status', {'operation_id': ident})
    require(status['status'] == 'applied', 'Finish operation is not fully applied')
    final = dict(originals)
    final.update({point(c['pos']): c['desired'] for c in changes})
    for batch in model['batches']:
        result = backend.rpc('region_inspect', {'min': batch['min'], 'max': batch['max'], 'detail': 'blocks'})
        live = {point(b['pos']): b['state'] for b in result['blocks']}
        for change in plans[batch['key']]['plan']['changes']:
            at = point(change['pos'])
            require(live.get(at) == final[at], f'Final build differs at world {at}; preserve current world')
    report = {'status': 'verified', 'blocks': len(final), 'batches': len(model['batches']), 'finish_changes': 18,
              'operation_id': ident, 'manifest_sha256': digest(model), 'finish_ledger_sha256': digest(ledger),
              'verified_at': time.time(), 'scope': backend.scope}
    save(OUTPUT / 'finish-verification.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        raise SystemExit('Finish stopped: ' + str(error)) from None
