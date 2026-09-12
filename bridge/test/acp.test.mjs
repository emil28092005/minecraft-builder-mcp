import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { CodexSession, agentEnvironment } from '../dist/acp.js';
async function fixture(t){
  const stateDir=await mkdtemp(join(tmpdir(),'mcb-acp-'));t.after(()=>rm(stateDir,{recursive:true,force:true}));
  const log=join(stateDir,'protocol.jsonl');
  const options={backendUrl:'http://127.0.0.1:8765',agentToken:'agent-secret',stateDir,command:process.execPath,args:[resolve('test/fixtures/mock-acp.mjs'),log],env:{...process.env,MCB_TOKEN:'ADMIN SECRET'}};
  const records=async()=> (await readFile(log,'utf8').catch(()=>'' )).trim().split('\n').filter(Boolean).map(JSON.parse);
  return {options,records};
}
test('ACP initializes, injects scoped MCP, preserves sessions, suppresses private replay and thoughts',async t=>{
  const {options,records}=await fixture(t);const messages=[];
  let session=new CodexSession({projectId:'project',playerId:'player'},options);t.after(()=>session.close());
  await session.prompt('Build a tower',async(text,done)=>messages.push({text,done}));
  await session.prompt('Make it higher',async(text,done)=>messages.push({text,done}));
  assert.ok(messages.some(item=>item.text.includes('Built turn 2')));
  assert.ok(!messages.some(item=>item.text.includes('SECRET THOUGHT')));
  session.close();session=new CodexSession({projectId:'project',playerId:'player'},options);
  await session.prompt('Resume',async(text,done)=>messages.push({text,done}));
  assert.ok(!messages.some(item=>item.text.includes('PRIVATE HISTORY')));
  const all=await records();assert.equal(all.filter(item=>item.method==='session/new').length,1);assert.equal(all.filter(item=>item.method==='session/load').length,1);
  const mcp=all.find(item=>item.method==='session/new').params.mcpServers[0];
  assert.ok(mcp.env.some(item=>item.name==='MCB_PLAYER_ID'&&item.value==='player'));
  assert.ok(!JSON.stringify(all).includes('ADMIN SECRET'));
});
test('permission requests fail closed and explain in chat',async t=>{
  const {options,records}=await fixture(t);const messages=[];
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  await session.prompt('request-permission',async text=>messages.push(text));
  assert.ok(messages.some(text=>text.includes('отклонено')));
  assert.equal((await records()).find(item=>item.id==='approval').result.outcome.outcome,'cancelled');
});
test('ACP cancel completes active prompt without ending the whole daemon',async t=>{
  const {options,records}=await fixture(t);const messages=[];
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  const work=session.prompt('wait-for-cancel',async text=>messages.push(text));
  for(let i=0;i<100;i++){await pause(10);if((await records()).some(item=>item.method==='session/prompt'))break;}
  await session.cancel();await work;
  assert.ok(messages.some(text=>text.includes('Остановлено')));
});
test('child environment allowlists secrets and forces dedicated Codex configuration',()=>{
  const env=agentEnvironment({PATH:'/bin',HOME:'/home/test',MCB_TOKEN:'admin',MCB_AGENT_TOKEN:'agent',AWS_SECRET_ACCESS_KEY:'private',OPENAI_API_KEY:'inherited',MCB_OPENAI_API_KEY:'opt-in',CODEX_CONFIG:'{"sandbox_mode":"danger-full-access"}'},{home:'/isolated/home',codexHome:'/isolated/codex'});
  assert.equal(env.HOME,'/isolated/home');assert.equal(env.CODEX_HOME,'/isolated/codex');assert.equal(env.AWS_SECRET_ACCESS_KEY,undefined);assert.equal(env.MCB_TOKEN,undefined);assert.equal(env.OPENAI_API_KEY,'opt-in');assert.equal(JSON.parse(env.CODEX_CONFIG).features.shell_tool,false);assert.equal(env.INITIAL_AGENT_MODE,'read-only');
});

test('cancel during startup does not send a prompt after initialization completes',async t=>{
 const {options,records}=await fixture(t);const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
 const work=session.prompt('must-not-send',async()=>{});await session.cancel();await work;
 assert.ok(!(await records()).some(item=>item.method==='session/prompt'));
});
