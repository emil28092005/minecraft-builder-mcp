#!/usr/bin/env python3
"""Plan, apply, or verify the Gothic hall polish against its saved canonical baseline."""
import argparse
from collections import defaultdict
import fcntl
import importlib.util
import json
from pathlib import Path
import time

from builds.gothic_hall.scene import boxes

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.runtime/gothic-hall/polish'
MANIFEST = OUTPUT / 'manifest.json'
LEDGER = OUTPUT / 'ledger.json'
AIR = 'minecraft:air'
spec = importlib.util.spec_from_file_location('gothic_finish', ROOT / 'scripts/finish-gothic-hall.py')
finish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finish)
require, digest, point, position = finish.require, finish.digest, finish.point, finish.position


class Backend(finish.Backend):
    def rpc(self, method, params):
        try:
            return super().rpc(method, params)
        except RuntimeError as error:
            raise RuntimeError(str(error).replace('finish ledger', 'polish ledger')) from None


def matches(actual, requested):
    """Match explicit requested properties while accepting registry defaults."""
    def split(state):
        name, _, suffix = state.partition('[')
        properties = dict(item.split('=', 1) for item in suffix.rstrip(']').split(',') if item)
        return name, properties
    actual_name, actual_properties = split(actual)
    requested_name, requested_properties = split(requested)
    return actual_name == requested_name and all(
        actual_properties.get(key) == value for key, value in requested_properties.items())


def baseline():
    model, originals, plans = finish.references()
    patch = json.loads(finish.LEDGER.read_text())
    finish.validate_saved_finish(patch, finish.targets(model, originals), model, plans)
    states = dict(originals)
    states.update({point(c['pos']): c['desired'] for c in patch['changes']})
    return model, states, plans, patch


def bounds(positions):
    lo = tuple(min(p[i] for p in positions) for i in range(3))
    hi = tuple(max(p[i] for p in positions) for i in range(3))
    require((hi[0] - lo[0] + 1) * (hi[1] - lo[1] + 1) * (hi[2] - lo[2] + 1) <= 2048,
            'Inspection volume exceeds the 16x8x16 tile budget')
    return {'min': position(lo), 'max': position(hi)}


def manifest(model, states, plans, patch):
    from builds.gothic_hall.polish_scene import finished_scene, build_scene
    before, after = finished_scene().blocks, build_scene().blocks
    origin = model['origin']

    def world(local):
        return tuple(a + b for a, b in zip(local, origin))

    require({world(p) for p in before} == set(states), 'Finished scene baseline mask changed')
    require(all(matches(states[world(p)], value) for p, value in before.items()),
            'Finished scene differs from the original plans plus the 18 finish states')
    changes, tiles = {}, defaultdict(dict)
    for local in sorted(before.keys() | after.keys()):
        old, desired = before.get(local, AIR), after.get(local, AIR)
        if finish.canonical(old) == finish.canonical(desired):
            continue
        require(-2 <= local[0] <= 68 and -1 <= local[1] <= 64 and -2 <= local[2] <= 68,
                'Polish extends beyond the agreed local bounds')
        at = world(local)
        expected = states.get(at, AIR)
        # Different spellings that only make existing default properties explicit
        # have no world effect and are omitted before requesting a server plan.
        if finish.canonical(expected) == finish.canonical(desired):
            continue
        changes[local] = {'pos': position(at), 'expected': expected, 'desired': desired}
        tiles[(local[0] // 16, local[1] // 8, local[2] // 16)][local] = desired
    batches = []
    for tile, cells in sorted(tiles.items()):
        compressed = boxes(cells)
        for start in range(0, len(compressed), 256):
            operations, selected = [], []
            for x1, y1, z1, x2, y2, z2, block in compressed[start:start + 256]:
                operations.append({'type': 'box', 'min': position(world((x1, y1, z1))),
                                   'max': position(world((x2, y2, z2))), 'block': block})
                selected.extend(changes[(x, y, z)]
                                for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)
                                for z in range(z1, z2 + 1))
            selected.sort(key=lambda c: point(c['pos']))
            require(len(selected) == len({point(c['pos']) for c in selected}) <= 2048,
                    'Compressed batch contains duplicates or exceeds the block budget')
            batches.append({'key': '_'.join(map(str, (*tile, start // 256))),
                            **bounds([point(c['pos']) for c in selected]), 'changes': selected,
                            'recipe': {'version': 1, 'operations': operations}})
    require(sum(len(b['changes']) for b in batches) == len(changes), 'Incomplete polish batch mask')
    return {'version': 1, 'name': 'Gothic hall polish', 'origin': origin,
            'world_id': model['world_id'], 'world_epoch': model['world_epoch'],
            'baseline_manifest_sha256': digest(model), 'finish_ledger_sha256': digest(patch),
            'source_plans': {key: {'plan_id': value['plan_id'], 'sha256': value['sha256']}
                             for key, value in plans.items()},
            'before_blocks': len(before), 'after_blocks': len(after), 'changes': len(changes),
            'added': sum(p not in before for p in changes),
            'removed': sum(p not in after for p in changes), 'batches': batches}


def prepared(record, batch, model, scope):
    plan, checksum = finish.envelope(
        finish.CONFIG.parent / 'journal/plans' / (record['plan']['plan_id'] + '.json'), 'plan')
    require(checksum == record['plan']['plan_hash'], 'Prepared polish plan hash changed')
    require(plan['worldEpoch'] == model['world_epoch'] and plan['region']['worldId'] == model['world_id'],
            'Prepared polish world identity changed')
    require(plan['projectId'] == scope['project_id'], 'Prepared polish project changed')
    expected = {point(c['pos']): c for c in batch['changes']}
    actual = {point(c['pos']): c for c in plan['changes']}
    require(len(plan['changes']) == len(actual) == len(expected) and actual.keys() == expected.keys(),
            'Prepared polish mask differs from the reviewed diff')
    for at, change in actual.items():
        require(change['expected'] == expected[at]['expected'],
                f'Prepared expected state changed at world {at}; preserve current world')
        require(matches(change['desired'], expected[at]['desired']),
                f'Prepared desired properties differ at world {at}')
    require(record['idempotency_key'] == 'gothic-hall-polish-' + plan['id'],
            'Polish idempotency identity changed')
    return {at: c['desired'] for at, c in actual.items()}


def inspect(backend, region, states, planter_soil=frozenset()):
    result = backend.rpc('region_inspect', {**region, 'detail': 'blocks'})
    live = {point(block['pos']): block['state'] for block in result['blocks']}
    variations = []
    for at, expected in states.items():
        # Verification may observe grass spreading over the newly planted soil.
        # Preparation and application pass no such allowance and remain exact.
        if at in planter_soil and expected == 'minecraft:dirt' and live.get(at) == 'minecraft:grass_block[snowy=false]':
            variations.append({'pos': position(at), 'expected': expected, 'observed': live[at]})
            continue
        require(live.get(at) == expected,
                f'Live state differs at world {at}; preserve current world and inspect before continuing')
    return variations


def completed(backend, record, apply=False):
    ident = finish.operation_id(record)
    if ident is None and apply:
        # The record and key have already been fsynced. A transport exception
        # escapes immediately; a later invocation first inspects the journal.
        result = backend.rpc('build_apply', {**record['plan'], 'idempotency_key': record['idempotency_key']})
        ident = result['operation_id']
    require(ident is not None, 'A required operation has not been applied')
    for _ in range(600 if apply else 1):
        status = backend.rpc('operation_status', {'operation_id': ident})
        if status['status'] not in ('queued', 'applying'):
            break
        if apply:
            time.sleep(.1)
    require(status['status'] == 'applied',
            f'Operation {ident} stopped at {status["status"]}; inspect before continuing')
    return ident


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'verify'])
    args = parser.parse_args()
    model, states, source_plans, patch = baseline()
    wanted = manifest(model, states, source_plans, patch)
    if MANIFEST.exists():
        require(digest(json.loads(MANIFEST.read_text())) == digest(wanted),
                'Immutable polish manifest differs from the current generator or baseline')
    else:
        require(args.action == 'plan', 'Run plan before apply or verify')
        finish.save(MANIFEST, wanted, immutable=True)
    backend = Backend()
    context = backend.rpc('project_context', {})
    require(context['world_id'] == model['world_id'] and context['world_epoch'] == model['world_epoch'],
            'Live world identity changed')
    require(patch['scope'] == backend.scope, 'Finished baseline owner/project scope changed')
    completed(backend, patch)
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text())
    else:
        require(args.action == 'plan', 'The polish ledger is missing; run plan first')
        ledger = {'version': 1, 'manifest_sha256': digest(wanted), 'scope': backend.scope, 'batches': {}}
        finish.save(LEDGER, ledger, immutable=True)
    require(ledger['version'] == 1 and ledger['manifest_sha256'] == digest(wanted)
            and ledger['scope'] == backend.scope, 'Polish ledger identity changed')
    require(set(ledger['batches']) <= {b['key'] for b in wanted['batches']}, 'Unknown polish ledger batch')
    canonical_targets = {}
    for batch in wanted['batches']:
        key = batch['key']
        if key not in ledger['batches']:
            require(args.action == 'plan', 'Some polish batches are not prepared; run plan first')
            inspect(backend, {'min': batch['min'], 'max': batch['max']},
                    {point(c['pos']): c['expected'] for c in batch['changes']})
            summary = backend.rpc('build_prepare', {'recipe': batch['recipe']})
            record = {'plan': summary, 'idempotency_key': 'gothic-hall-polish-' + summary['plan_id']}
            prepared(record, batch, wanted, backend.scope)
            # Existing records are never replaced. Atomic publication follows
            # server-plan validation and always precedes any build_apply call.
            ledger['batches'][key] = record
            finish.save(LEDGER, ledger)
        canonical_targets.update(prepared(ledger['batches'][key], batch, wanted, backend.scope))
    if args.action == 'plan':
        print(json.dumps({'status': 'prepared', 'changes': wanted['changes'],
                          'batches': len(wanted['batches']), 'ledger': str(LEDGER)}))
        return
    operations = []
    for index, batch in enumerate(wanted['batches'], 1):
        ident = completed(backend, ledger['batches'][batch['key']], apply=args.action == 'apply')
        operations.append(ident)
        if args.action == 'apply':
            inspect(backend, {'min': batch['min'], 'max': batch['max']},
                    {point(c['pos']): canonical_targets[point(c['pos'])] for c in batch['changes']})
            print(json.dumps({'status': 'applied', 'batch': index, 'batches': len(wanted['batches']),
                              'operation_id': ident}), flush=True)
    if args.action == 'apply':
        return
    final, tiles = {**states, **canonical_targets}, defaultdict(dict)
    for at, value in final.items():
        local = tuple(a - b for a, b in zip(at, wanted['origin']))
        tiles[(local[0] // 16, local[1] // 8, local[2] // 16)][at] = value
    planter_soil = frozenset(at for at, state in canonical_targets.items()
                            if state == 'minecraft:dirt' and at[1] == wanted['origin'][1])
    soil_variations = []
    for _, group in sorted(tiles.items()):
        soil_variations.extend(inspect(backend, bounds(list(group)), group, planter_soil))
    report = {'status': 'verified', 'checked_positions': len(final),
              'blocks': sum(value != AIR for value in final.values()),
              'checked_air': sum(value == AIR for value in final.values()),
              'changes': wanted['changes'], 'inspection_tiles': len(tiles),
              'accepted_planter_grass': soil_variations,
              'manifest_sha256': digest(wanted), 'ledger_sha256': digest(ledger),
              'operations': operations, 'scope': backend.scope, 'verified_at': time.time()}
    finish.save(OUTPUT / 'verification.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with (OUTPUT / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        raise SystemExit('Polish stopped: ' + str(error)) from None
