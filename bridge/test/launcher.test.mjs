import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';

test('launcher doctor and login status share a dedicated home without requiring Paper or starting login',async t=>{
 const state=await mkdtemp(join(tmpdir(),'mcb-launcher-'));t.after(()=>rm(state,{recursive:true,force:true}));
 const env={...process.env,MCB_STATE_DIR:state,MCB_CODEX_HOME:join(state,'codex-home'),MCB_OPENAI_API_KEY:'',MCB_CODEX_API_KEY:''};
 const run=args=>spawnSync('python3',[resolve('../scripts/bridge.py'),...args,'--config',join(state,'absent-config.yml')],{env,encoding:'utf8',timeout:20_000});
 const doctor=run(['doctor']);assert.equal(doctor.status,0,doctor.stderr);
 const data=JSON.parse(doctor.stdout);assert.equal(data.codex.codexHome,env.MCB_CODEX_HOME);
 assert.equal(data.codex.login.env.MCB_STATE_DIR,state);
 for(const args of [['status'],['login','status'],['login','--status']]){
  const status=run(args);assert.equal(status.status,1,status.stderr);assert.match(status.stdout+status.stderr,/not logged in/i);
  assert.ok(!(status.stdout+status.stderr).includes('device code'));
 }
});
