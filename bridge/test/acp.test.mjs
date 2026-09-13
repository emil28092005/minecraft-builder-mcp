import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { CodexSession, agentEnvironment } from '../dist/acp.js';
import { longReply, overlongWord } from './fixtures/streamed-replies.mjs';
async function fixture(t){
  const stateDir=await mkdtemp(join(tmpdir(),'mcb-acp-'));t.after(()=>rm(stateDir,{recursive:true,force:true}));
  const log=join(stateDir,'protocol.jsonl');
  const options={backendUrl:'http://127.0.0.1:8765',agentToken:'agent-secret',stateDir,command:process.execPath,args:[resolve('test/fixtures/mock-acp.mjs'),log],env:{...process.env,MCB_TOKEN:'ADMIN SECRET'}};
  const records=async()=> (await readFile(log,'utf8').catch(()=>'' )).trim().split('\n').filter(Boolean).map(JSON.parse);
  return {options,records};
}
test('updated terrain and material guidance reaches resumed ACP sessions once without resetting history',async t=>{
  const {options,records}=await fixture(t);
  let session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  await session.prompt('first request',async()=>{});session.close();
  const key=createHash('sha256').update('p\0u').digest('hex').slice(0,32);
  const file=join(options.stateDir,key,'session.json');
  const saved=JSON.parse(await readFile(file,'utf8'));saved.instructionsHash='older-prompt';
  await writeFile(file,JSON.stringify(saved));
  session=new CodexSession({projectId:'p',playerId:'u'},options);
  await session.prompt('after update',async()=>{});
  await session.prompt('next request',async()=>{});session.close();
  session=new CodexSession({projectId:'p',playerId:'u'},options);
  await session.prompt('same guidance after restart',async()=>{});
  const calls=await records();const prompts=calls.filter(v=>v.method==='session/prompt').map(v=>v.params.prompt[0].text);
  assert.ok(prompts[1].includes('shacraft-natural-v1'));
  assert.ok(prompts[1].includes('Avoid large rectangular plateaus'));
  assert.ok(prompts[1].includes('NOT as terrain_preview parameters'));
  for(const prompt of [prompts[0],prompts[1]]) {
    assert.ok(prompt.includes('project_context contains only a catalog summary'));
    assert.ok(prompt.includes('material_search'));
    assert.ok(prompt.includes('material_describe for 1–3 chosen materials'));
    assert.ok(prompt.includes('do not enumerate the registry'));
    assert.ok(prompt.includes('item-only materials can be discovered but cannot be placed'));
  }
  assert.equal(prompts[2],'next request');assert.equal(prompts[3],'same guidance after restart');
  assert.equal(calls.filter(v=>v.method==='session/new').length,1);
  assert.equal(calls.filter(v=>v.method==='session/load').length,2);
});
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
test('MCP startup failure before session creation stops the prompt and redacts diagnostics',async t=>{
  const {options,records}=await fixture(t);options.args.push('mcp-fail-new');const messages=[];
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  await assert.rejects(session.prompt('Must not run',async text=>messages.push(text)),error=>error.code==='mcp_unavailable');
  assert.ok(!(await records()).some(item=>item.method==='session/prompt'));
  assert.deepEqual(messages,['Minecraft MCP не запустился: инструменты строительства недоступны. Запрос остановлен; проверь настройки и процесс моста.']);
  assert.ok(!messages.join(' ').includes('agent-secret'));
});
test('MCP startup failure during load stops the new turn while historical failures stay private',async t=>{
  const {options,records}=await fixture(t);const messages=[];
  let session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  await session.prompt('First turn',async()=>{});session.close();options.args.push('mcp-fail-load');
  session=new CodexSession({projectId:'p',playerId:'u'},options);
  await assert.rejects(session.prompt('Must not run',async text=>messages.push(text)),error=>error.code==='mcp_unavailable');
  assert.equal((await records()).filter(item=>item.method==='session/prompt').length,1);
  assert.ok(messages.some(text=>text.includes('Minecraft MCP не запустился')));
  assert.ok(!messages.join(' ').includes('PRIVATE'));
});
test('MCP startup failures from another session do not block the selected session',async t=>{
  const {options}=await fixture(t);options.args.push('mcp-fail-other-session');const messages=[];
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  await session.prompt('Continue selected session',async text=>messages.push(text));
  assert.ok(messages.some(text=>text.includes('Built turn 1')));
  assert.ok(!messages.some(text=>text.includes('MCP не запустился')));
});
test('an asynchronous MCP startup failure interrupts an active turn with a safe explanation',async t=>{
  const {options}=await fixture(t);const messages=[];
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  await assert.rejects(session.prompt('mcp-fail-active',async(text,done)=>messages.push({text,done})),error=>error.code==='mcp_unavailable');
  assert.ok(messages.some(item=>item.text.includes('Minecraft MCP не запустился')));
  assert.ok(!messages.some(item=>item.done || item.text.includes('agent-secret')));
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

test('delayed token streams keep words intact and flush the next turn independently',async t=>{
  const {options}=await fixture(t);
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  const first=[];
  await session.prompt('stream-greeting',async(text,done)=>first.push({text,done}));
  const visible=items=>items.filter(item=>item.text).map(item=>item.text).join(' ').replace(/\s+/g,' ').trim();
  assert.equal(visible(first),'Привет! Что построим?','ACP token boundaries must not become game-chat word boundaries');
  assert.equal(first.at(-1).done,true);
  assert.equal(first.filter(item=>item.done).length,1);
  await pause(1600);
  const second=[];
  await session.prompt('stream-follow-up',async(text,done)=>second.push({text,done}));
  assert.equal(visible(second),'Понятно. Проверяю освещение','a new prompt resets buffering and completion flushes an unfinished sentence');
  assert.equal(second.at(-1).done,true);
  assert.equal(second.filter(item=>item.done).length,1);
});

test('slow chat delivery preserves streamed text order and completes after the final reply',async t=>{
  const {options}=await fixture(t);
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  const messages=[];let inFlight=0;let maxInFlight=0;let calls=0;
  await session.prompt('stream-slow-delivery',async(text,done)=>{
    const call=++calls;
    maxInFlight=Math.max(maxInFlight,++inFlight);
    // A slower first HTTP reply must not let later chunks or the done marker overtake it.
    await pause(call===1 ? 100 : 3);
    messages.push({text,done});
    inFlight--;
  });
  assert.equal(inFlight,0,'prompt completion must await all chat replies');
  assert.equal(maxInFlight,1,'chat replies must be serialized');
  assert.equal(messages.at(-1).done,true);
  assert.equal(messages.filter(item=>item.done).length,1);
  const visible=messages.filter(item=>item.text).map(item=>item.text);
  assert.ok(visible.length>1,'long replies need multiple Minecraft chat messages');
  assert.ok(visible.every(text=>text.length<=240),'chat messages must respect the UTF-16 length bound');
  assert.ok(visible.every(text=>text.isWellFormed()),'chunking must not split a surrogate pair');
  assert.equal(visible.join(' ').replace(/\s+/g,' ').trim(),longReply,'visible text must retain every word exactly once and in order');
});

test('a word longer than one chat message is bounded without splitting emoji',async t=>{
  const {options}=await fixture(t);
  const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
  const messages=[];
  await session.prompt('stream-overlong-word',async(text,done)=>messages.push({text,done}));
  const visible=messages.filter(item=>item.text).map(item=>item.text);
  assert.ok(visible.length>1);
  assert.ok(visible.every(text=>text.length<=240 && text.isWellFormed()));
  assert.equal(visible.join(''),overlongWord,'an unavoidable long-word split must preserve all Unicode text');
  assert.equal(messages.at(-1).done,true);
});


test('only correlated Minecraft tools receive one-use approval in the active session',async t=>{
 for(const mode of ['valid','material-search','material-describe','terrain-preview','terrain-prepare','terrain-brush','foreign','unknown','wrong-session','uncorrelated','completed','no-meta','persistent']) {
  await t.test(mode,async t=>{
   const {options,records}=await fixture(t);const messages=[];
   const session=new CodexSession({projectId:'p',playerId:'u'},options);t.after(()=>session.close());
   await session.prompt('mcp-approval-'+mode,async text=>messages.push(text));
   const response=(await records()).find(item=>item.id==='approval').result.outcome;
   assert.deepEqual(response,['valid','material-search','material-describe','terrain-preview','terrain-prepare','terrain-brush'].includes(mode)?{outcome:'selected',optionId:'allow_once'}:{outcome:'cancelled'});
   assert.equal(messages.some(text=>text.includes('отклонено')),!['valid','material-search','material-describe','terrain-preview','terrain-prepare','terrain-brush'].includes(mode));
  });
 }
});
