#!/usr/bin/env python3
"""Actual Paper integration tests in the disposable .runtime/server fixture (EULA must already be accepted)."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
SERVER=ROOT/'.runtime/server'
TOKEN=''
ADMIN_TOKEN=''
SCOPE={'player_id':'console','project_id':'default'}

def request(method, params=None, expect_error=False, admin=False):
    payload={'method':method,'params':{**(params or {}),**SCOPE},'requestId':'live-test'}
    req=urllib.request.Request('http://127.0.0.1:8765/v1/rpc',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+(ADMIN_TOKEN if admin else TOKEN),'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=25) as r: body=json.load(r)
    except urllib.error.HTTPError as e: body=json.load(e)
    if expect_error:
        assert not body['ok'],body
        return body['error']
    assert body['ok'],body
    return body['result']

def pos(x=8,y=96,z=8):return {'x':x,'y':y,'z':z}
def inspect(at):return request('region_inspect',{'min':at,'max':at,'detail':'blocks'})['blocks'][0]['state']
def prepare(lo=None,hi=None,block='minecraft:stone_bricks',dependencies=None):
    return request('build_prepare',{'recipe':{'version':1,'operations':[{'type':'box','min':lo or pos(),'max':hi or pos(10,98,10),'block':block}]},'dependencies':dependencies or []})
def apply(plan,key):return request('build_apply',{'plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'idempotency_key':key})
def wait(predicate,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=predicate()
            if value:return value
        except (OSError,AssertionError):pass
        time.sleep(.1)
    raise AssertionError('Timed out waiting for expected test condition')
def terminal(op):
    state=request('operation_status',{'operation_id':op['operation_id']})
    return state if state['status'] not in ('queued','applying') else None

if __name__=='__main__':
    if not (SERVER/'eula.txt').exists() or 'eula=true' not in (SERVER/'eula.txt').read_text():
        raise SystemExit('First review/accept Minecraft EULA using scripts/dev-server.py --accept-eula. This test does not accept it.')
    try:
        urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=1)
    except OSError:pass
    else:raise SystemExit('Stop the current dev server before this test; it owns its server process.')
    config=SERVER/'plugins/MinecraftBuilderMCP/config.yml'
    if not config.exists():raise SystemExit('Start the prepared server once to generate its private config first.')
    previous=config.read_text()
    metadata_path=config.parent/'metadata.json'
    previous_metadata=metadata_path.read_bytes() if metadata_path.exists() else None
    config.write_text(previous.replace('allow-local-automation: false','allow-local-automation: true'))
    TOKEN=re.search(r'^agent-token: (.+)$',previous,re.M).group(1).strip().strip("'\"")
    ADMIN_TOKEN=re.search(r'^admin-token: (.+)$',previous,re.M).group(1).strip().strip("'\"")
    logpath=ROOT/'.runtime/live-server-test.log'
    results=[]
    log=logpath.open('w')
    def launch():return subprocess.Popen(['python3','scripts/dev-server.py','--run'],cwd=ROOT,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,text=True,start_new_session=True)
    process=launch()
    def console(command):
        process.stdin.write(command+'\n');process.stdin.flush()
    def report(name,**data):
        result={'test':name,**data};results.append(result);print(json.dumps(result),flush=True)
    try:
        wait(lambda:urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=1).status==200,90)
        console('forceload add 0 0 31 31')
        wait(lambda:inspect(pos())=='minecraft:air')
        initial=request('region_inspect',{'min':pos(),'max':pos(23,99,11),'detail':'summary'})
        assert initial['palette']=={'minecraft:air':256},initial['palette']

        plan=prepare()
        console('setblock 8 96 8 minecraft:granite')
        wait(lambda:inspect(pos())=='minecraft:granite')
        conflict=wait(lambda:terminal(apply(plan,'live-conflict-'+plan['plan_id'])))
        assert conflict['status']=='conflict' and conflict['written']==0,conflict
        assert inspect(pos())=='minecraft:granite'
        report('external-change-before-apply',status=conflict['status'],written=conflict['written'])
        console('setblock 8 96 8 minecraft:air');wait(lambda:inspect(pos())=='minecraft:air')

        dependency=pos(11,96,8)
        plan=prepare(dependencies=[dependency])
        console('setblock 11 96 8 minecraft:granite');wait(lambda:inspect(dependency)=='minecraft:granite')
        changed=wait(lambda:terminal(apply(plan,'live-dependency-'+plan['plan_id'])))
        assert changed['status']=='conflict' and changed['written']==0,changed
        report('read-dependency-conflict',status=changed['status'])
        console('setblock 11 96 8 minecraft:air');wait(lambda:inspect(dependency)=='minecraft:air')

        plan=prepare()
        op=apply(plan,'live-build-'+plan['plan_id']);built=wait(lambda:terminal(op));assert built['status']=='applied' and built['written']==27,built
        duplicate=apply(plan,'live-build-'+plan['plan_id']);assert duplicate['operation_id']==op['operation_id']
        console('setblock 8 96 8 minecraft:granite');wait(lambda:inspect(pos())=='minecraft:granite')
        error=request('operation_undo_prepare',{'operation_id':op['operation_id']},expect_error=True)
        assert inspect(pos())=='minecraft:granite'
        report('undo-preserves-later-external-change',error_code=error['code'])
        console('setblock 8 96 8 minecraft:stone_bricks');wait(lambda:inspect(pos())=='minecraft:stone_bricks')
        undo=request('operation_undo_prepare',{'operation_id':op['operation_id']})
        undone=wait(lambda:terminal(apply(undo,'live-undo-'+undo['plan_id'])));assert undone['status']=='applied',undone
        assert request('region_inspect',{'min':pos(),'max':pos(10,98,10),'detail':'summary'})['palette']=={'minecraft:air':27}
        report('build-idempotency-checked-undo',written=built['written'],restored=undone['written'])

        plan=prepare(pos(12,96,8),pos(23,99,11))
        op=apply(plan,'live-cancel-'+plan['plan_id'])
        request('operation_cancel',{'operation_id':op['operation_id']})
        cancelled=wait(lambda:terminal(op));assert cancelled['status']=='cancelled',cancelled
        if cancelled['written']:
            undo=request('operation_undo_prepare',{'operation_id':op['operation_id']})
            assert wait(lambda:terminal(apply(undo,'live-cancel-undo-'+undo['plan_id'])))['status']=='applied'
        report('cancellation',status=cancelled['status'],written=cancelled['written'])

        console('setblock 8 96 8 minecraft:chest');wait(lambda:inspect(pos()).startswith('minecraft:chest'))
        failure=request('build_prepare',{'recipe':{'version':1,'operations':[{'type':'box','min':pos(),'max':pos(),'block':'minecraft:stone'}]}},expect_error=True)
        assert inspect(pos()).startswith('minecraft:chest')
        console('setblock 8 96 8 minecraft:air');wait(lambda:inspect(pos())=='minecraft:air')
        report('unsupported-existing-block-protected',code=failure['code'])
        assert request('region_inspect',{'min':pos(),'max':pos(23,99,11),'detail':'summary'})['palette']=={'minecraft:air':256}
        report('fixture-cleanup',air_blocks=256)

        # Kill only the process group created by this harness, in the disposable fixture.
        lo,hi=pos(8,100,8),pos(23,115,23)
        assert request('region_inspect',{'min':lo,'max':hi,'detail':'summary'})['palette']=={'minecraft:air':4096}
        plan=prepare(lo,hi);op=apply(plan,'live-crash-'+plan['plan_id'])
        def in_progress():
            s=request('operation_status',{'operation_id':op['operation_id']})
            return s if s['written']>0 and s['status']=='applying' else None
        progress=wait(in_progress)
        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
        time.sleep(.5)
        # Simulate an administrator protecting an affected part while offline.
        # Recovery must retain authorization without requiring write permission.
        metadata=json.loads(previous_metadata) if previous_metadata else {'parts':[],'cameras':{}}
        metadata['parts'].append({'id':'live-recovery-protection','name':'Recovery test protection',
            'operationId':op['operation_id'],'positions':[lo],'locked':True})
        metadata_path.write_text(json.dumps(metadata))
        process=launch()
        wait(lambda:urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=1).status==200,90)
        console('forceload add 0 0 31 31')
        recovered=wait(lambda:terminal(op));assert recovered['status']=='recovery_required',recovered
        review=request('recovery_review',{'operation_id':op['operation_id']},admin=True)
        request('recovery_review',{'operation_id':op['operation_id']},expect_error=True)
        console('setblock 8 100 8 minecraft:granite');wait(lambda:inspect(lo)=='minecraft:granite')
        request('recovery_abandon',{'operation_id':op['operation_id'],'expected_digest':review['currentDigest']},expect_error=True,admin=True)
        fresh=request('recovery_review',{'operation_id':op['operation_id']},admin=True)
        abandoned=request('recovery_abandon',{'operation_id':op['operation_id'],'expected_digest':fresh['currentDigest']},admin=True)
        assert abandoned['status']=='failed' and inspect(lo)=='minecraft:granite',abandoned
        request('operation_undo_prepare',{'operation_id':op['operation_id']},expect_error=True)
        report('crash-recovery-abandon',written_before_crash=progress['written'],recovery_positions=fresh['positions'],foreign_block='preserved',replay=False,protected_part='recovery-allowed')

        console('fill 8 100 8 23 115 23 minecraft:air')
        wait(lambda:request('region_inspect',{'min':lo,'max':hi,'detail':'summary'})['palette']=={'minecraft:air':4096})
        protected_plan=prepare(lo,lo,block='minecraft:stone')
        blocked=request('build_apply',{'plan_id':protected_plan['plan_id'],'plan_hash':protected_plan['plan_hash'],
            'idempotency_key':'live-protected-'+protected_plan['plan_id']},expect_error=True)
        assert blocked['code']=='permission_denied' and inspect(lo)=='minecraft:air',blocked
        report('recovery-retains-part-write-protection',status='permission_denied')
        plan=prepare(pos(9,100,8),pos(9,100,8));new=wait(lambda:terminal(apply(plan,'live-after-recovery-'+plan['plan_id'])))
        assert new['status']=='applied',new
        undo=request('operation_undo_prepare',{'operation_id':new['operation_id']})
        assert wait(lambda:terminal(apply(undo,'live-after-recovery-undo-'+undo['plan_id'])))['status']=='applied'
        report('editing-after-durable-recovery',status='applied-and-undone')
        # Exercise the actual MCP stdio transport, including .schem roundtrip.
        smoke_env=dict(os.environ,MCB_AGENT_TOKEN=TOKEN,MCB_PLAYER_ID='console',
            MCB_PROJECT_ID='default',MCB_TEST_X='8',MCB_TEST_Y='96',MCB_TEST_Z='8',
            MCB_BACKEND_URL='http://127.0.0.1:8765')
        smoke_env.pop('MCB_TOKEN',None)
        smoke=subprocess.run(['node','test/live-paper.mjs'],cwd=ROOT/'bridge',env=smoke_env,
            text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
        (ROOT/'.runtime/live-mcp-results.log').write_text(smoke.stdout)
        print(smoke.stdout,flush=True)
        assert smoke.returncode==0,'Live MCP smoke failed; inspect .runtime/live-mcp-results.log'
        report('mcp-stdio-schematic-roundtrip',status='passed')
    finally:
        if process.poll() is None:
            try:console('stop');process.wait(timeout=30)
            except (OSError,subprocess.TimeoutExpired):process.terminate();process.wait(timeout=15)
        log.close();config.write_text(previous)
        if previous_metadata is None:metadata_path.unlink(missing_ok=True)
        else:metadata_path.write_bytes(previous_metadata)
        (ROOT/'.runtime/live-server-results.json').write_text(json.dumps(results,indent=2)+'\n')
    print('LIVE PAPER CONFLICT/UNDO/CANCEL/CRASH TESTS PASSED',flush=True)
