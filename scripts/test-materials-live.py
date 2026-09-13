#!/usr/bin/env python3
"""Opt-in live integration checks against the isolated material-integration Paper world.

Requires .runtime/material-test-server/test-access.json provisioned by the operator.
Never targets the lobby: both scope and project identity are checked before mutation.
Run phase 'before-restart', restart the isolated server, then run 'after-restart'.
"""
import argparse
import json
import socket
import struct
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime/material-test-server'


class TestServer:
    def __init__(self):
        self.auth = json.loads((RUNTIME / 'test-access.json').read_text())
        context = self.rpc('project_context')
        assert context['project_id'] == 'material-integration', 'Refusing a non-test project'
        assert context['region']['max']['x'] == 511, 'Unexpected test region'

    def rpc(self, method, **params):
        body = json.dumps({'method': method, 'params': dict(params, player_id='console', project_id='material-integration')}).encode()
        request = urllib.request.Request('http://127.0.0.1:18765/v1/rpc', data=body,
            headers={'Authorization': 'Bearer ' + self.auth['agent'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                value = json.load(response)
        except urllib.error.HTTPError as error:
            value = json.load(error)
        if not value['ok']:
            raise RuntimeError(json.dumps(value['error']))
        return value['result']

    def rcon(self, command):
        def receive(stream):
            def exact(count):
                result = b''
                while len(result) < count:
                    piece = stream.recv(count-len(result))
                    if not piece:
                        raise EOFError('RCON disconnected')
                    result += piece
                return result
            length, = struct.unpack('<i', exact(4))
            if not 10 <= length <= 1048576:
                raise ValueError('Invalid RCON packet size')
            packet = exact(length)
            return struct.unpack('<ii', packet[:8]), packet[8:-2].decode()
        def send(stream, request_id, kind, text):
            packet = struct.pack('<ii', request_id, kind) + text.encode() + b'\0\0'
            stream.sendall(struct.pack('<i', len(packet)) + packet)
        with socket.create_connection(('127.0.0.1', 25586), timeout=10) as stream:
            send(stream, 1, 3, self.auth['rcon'])
            while True:
                (request_id, kind), _ = receive(stream)
                assert request_id != -1, 'RCON authentication failed'
                if kind == 2:
                    break
            send(stream, 2, 2, command)
            while True:
                (request_id, _), text = receive(stream)
                if request_id == 2:
                    return text

    def block(self, x, y, z):
        pos = dict(x=x, y=y, z=z)
        return self.rpc('region_inspect', min=pos, max=pos, detail='blocks')['blocks'][0]

    def prepare(self, targets, expected=None):
        operations = [dict(type='box', min=pos, max=pos, block=state) for pos, state in targets]
        params = {'recipe': dict(version=1, operations=operations)}
        if expected is not None:
            params['expected_blocks'] = expected
        return self.rpc('build_prepare', **params)

    def apply(self, plan, expected_status='applied'):
        result = self.rpc('build_apply', plan_id=plan['plan_id'], plan_hash=plan['plan_hash'], idempotency_key=str(uuid.uuid4()))
        deadline = time.monotonic()+40
        while result['status'] in ('queued', 'applying'):
            assert time.monotonic() < deadline, 'Operation did not finish'
            time.sleep(.08)
            result = self.rpc('operation_status', operation_id=result['operation_id'])
        assert result['status'] == expected_status, result
        time.sleep(.12)  # allow the terminal receipt to flush before starting another operation
        return result

    def undo(self, operation_id):
        return self.apply(self.rpc('operation_undo_prepare', operation_id=operation_id))


def expect_error(action, code):
    try:
        action()
    except RuntimeError as error:
        assert code in str(error), str(error)
    else:
        raise AssertionError('Expected ' + code)


def before_restart(server):
    context = server.rpc('project_context')
    assert 'supported_materials' not in context
    assert context['material_catalog']['blocks'] > 1000
    assert len(json.dumps(context['material_catalog'])) < 256
    first = server.rpc('material_search', query='trapdoor')
    second = server.rpc('material_search', query='trapdoor', cursor=first['next_cursor'])
    ids = [e['id'] for e in first['results']+second['results']]
    assert len(first['results']) == 16 and len(ids) == len(set(ids)) == first['total']
    expect_error(lambda: server.rpc('material_search', query='stairs', cursor=first['next_cursor']), 'invalid_cursor')
    expect_error(lambda: server.rpc('material_search', limit=33), 'invalid_material_query')
    descriptions = [server.rpc('material_describe', id=material) for material in (
        'minecraft:cherry_trapdoor', 'minecraft:water', 'minecraft:oak_wall_sign',
        'minecraft:redstone_wire', 'minecraft:wheat', 'minecraft:decorated_pot')]
    assert set(descriptions[0]['properties']['open']) == {'true', 'false'}
    assert len(descriptions[1]['properties']['level']) == 16
    assert server.rpc('material_describe', id='minecraft:diamond_sword')['placeable'] is False
    expect_error(lambda: server.rpc('material_describe', id='minecraft:not_a_real_material'), 'invalid_material')
    server.rcon('forceload add 0 0 79 79')
    server.rcon('gamerule minecraft:random_tick_speed 0')
    server.rcon('fill 28 99 28 60 99 44 minecraft:stone')

    # Newly available ordinary states, paired door halves, water and waterlogging.
    samples = [
        ((32,100,32),'minecraft:cherry_trapdoor[facing=north,half=bottom,open=true,powered=false,waterlogged=true]'),
        ((34,100,32),'minecraft:green_carpet'),
        ((36,100,32),'minecraft:potted_oxeye_daisy'),
        ((38,100,32),'minecraft:white_candle[candles=3,lit=true,waterlogged=false]'),
        ((40,100,32),'minecraft:water[level=0]'),
        ((42,100,32),'minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]'),
        ((42,101,32),'minecraft:oak_door[facing=north,half=upper,hinge=left,open=false,powered=false]'),
    ]
    targets = [(dict(zip(('x','y','z'),pos)),state) for pos,state in samples]
    baseline = [server.block(*pos) for pos,_ in samples]
    result = server.apply(server.prepare(targets, baseline))
    for (pos, state) in targets:
        assert server.block(**pos)['state'] == state
    server.undo(result['operation_id'])
    assert [server.block(*pos) for pos,_ in samples] == baseline

    # Fixture data is known test content; private snapshots must stay out of model responses.
    server.rcon('setblock 32 100 36 minecraft:chest[facing=north]')
    server.rcon('data merge block 32 100 36 {Items:[{Slot:0b,id:"minecraft:diamond",count:7}]}')
    server.rcon('setblock 36 100 36 minecraft:oak_sign')
    server.rcon('data merge block 36 100 36 {front_text:{messages:["MCP snapshot test","","",""]}}')
    server.rcon('setblock 40 100 36 minecraft:decorated_pot')
    chest = server.block(32,100,36)
    sign = server.block(36,100,36)
    pot = server.block(40,100,36)
    assert all(len(v['snapshot_id']) == 64 for v in (chest,sign,pot))
    assert 'minecraft:diamond' in server.rcon('data get block 32 100 36 Items')
    assert 'MCP snapshot test' in server.rcon('data get block 36 100 36 front_text')
    assert 'MCP snapshot test' not in json.dumps(sign)
    expect_error(lambda:server.prepare([(chest['pos'],'minecraft:stone')], [dict(pos=chest['pos'],state=chest['state'])]), 'snapshot_id')

    rotate = server.apply(server.prepare([(chest['pos'],chest['state'].replace('facing=north','facing=east'))],[chest]))
    assert 'minecraft:diamond' in server.rcon('data get block 32 100 36 Items')
    server.undo(rotate['operation_id'])
    assert server.block(32,100,36) == chest

    stale = server.prepare([(chest['pos'],'minecraft:stone')],[chest])
    server.rcon('data modify block 32 100 36 Items[0].count set value 9')
    changed = server.block(32,100,36)
    assert changed['snapshot_id'] != chest['snapshot_id']
    expect_error(lambda:server.prepare([(chest['pos'],'minecraft:stone')],[chest]), 'stale_snapshot')
    conflict = server.apply(stale, 'conflict')
    assert 'minecraft:diamond' not in json.dumps(conflict)
    assert '\u0000mcb-block' not in json.dumps(conflict)
    assert conflict['conflicts'][0]['current_snapshot_id'] == changed['snapshot_id']
    server.rcon('data modify block 32 100 36 Items[0].count set value 7')
    assert server.block(32,100,36) == chest

    # Block-entity export must fail rather than silently strip contents.
    expect_error(lambda:server.rpc('schematic_export',name='reject-tile',min=chest['pos'],max=chest['pos']), 'unsupported_block_entity')
    trap_pos=dict(x=44,y=100,z=36)
    trap='minecraft:cherry_trapdoor[facing=north,half=bottom,open=true,powered=false,waterlogged=true]'
    placed=server.apply(server.prepare([(trap_pos,trap)]))
    asset=server.rpc('schematic_export',name='new-material-rotation',min=trap_pos,max=trap_pos)
    target=dict(x=46,y=100,z=36)
    imported=server.apply(server.rpc('schematic_import_prepare',asset_id=asset['assetId'],target=target,rotation=90))
    assert 'facing=east' in server.block(**target)['state']
    server.undo(imported['operation_id']);server.undo(placed['operation_id'])

    before = [chest, sign, pot]
    replaced = server.apply(server.prepare([(v['pos'],'minecraft:stone') for v in before],before))
    item_check=server.rcon('execute if entity @e[type=minecraft:item,x=28,y=98,z=32,dx=16,dy=6,dz=8] run say UNEXPECTED_ITEM_DROP')
    assert 'UNEXPECTED_ITEM_DROP' not in item_check
    receipt={'catalog':context['material_catalog'],'catalog_summary_bytes':len(json.dumps(context['material_catalog'],separators=(',',':')).encode()),'search_page_bytes':len(json.dumps(first).encode()),'description_bytes':[len(json.dumps(v).encode()) for v in descriptions],
        'checks':['bounded search/pagination','property domains','item-only distinction','new blocks and fluids apply/undo','paired doors','private block-entity digests','same-material inventory preservation','manual-content stale snapshot and apply conflict','no inventory drops','schematic new-material native rotation','schematic block-entity export rejection'],
        'restart_operation_id':replaced['operation_id'],'before_restart_blocks':before,'phase':'awaiting_restart'}
    (RUNTIME/'live-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    server.rcon('save-all flush')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('before_restart_blocks','restart_operation_id')},indent=2),flush=True)


def after_restart(server):
    receipt=json.loads((RUNTIME/'live-receipt.json').read_text())
    server.rcon('forceload add 0 0 79 79')
    server.undo(receipt['restart_operation_id'])
    for expected in receipt['before_restart_blocks']:
        assert server.block(**expected['pos']) == expected
    assert 'minecraft:diamond' in server.rcon('data get block 32 100 36 Items')
    assert 'MCP snapshot test' in server.rcon('data get block 36 100 36 front_text')
    receipt['checks'].append('complete chest/sign/pot undo after Paper restart')
    receipt['phase']='complete'
    (RUNTIME/'live-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Complete: chest contents, sign text and decorated-pot snapshot restored exactly after restart.',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('before-restart','after-restart'))
    args=parser.parse_args()
    server=TestServer()
    (before_restart if args.phase=='before-restart' else after_restart)(server)
