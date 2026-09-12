import test from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as pause } from 'node:timers/promises';
import { ChatRunner, promptWithContext } from '../dist/chat-runner.js';

const message=(id,projectId='p',playerId='u',type='prompt')=>({id,projectId,playerId,text:id,type});
async function eventually(predicate){for(let i=0;i<400;i++){if(predicate())return;await pause(5);}assert.fail('Condition timed out');}
test('projects run concurrently while each project stays ordered, replies remain private',async()=>{
  const polls=[[message('one'),message('two'),message('other','q','v')]];const replies=[];const started=[];const release=new Map();
  const backend={async call(method,params){if(method==='chat_poll'){assert.match(params.client_id,/^[0-9a-f-]{36}$/);return {messages:polls.shift()??[]};}replies.push(params);return {};}};
  const runner=new ChatRunner(backend,()=>({async prompt(text,reply){started.push(text);await new Promise(done=>release.set(text,done));await reply(`answer ${text}`,true);},async cancel(){},close(){}}));
  try{
    await runner.poll();await eventually(()=>started.length===2);
    assert.deepEqual(started,['one','other']);release.get('one')();await eventually(()=>started.includes('two'));
    release.get('two')();release.get('other')();await eventually(()=>replies.filter(item=>item.done).length===3);
    assert.equal(replies.find(item=>item.text==='answer other').playerId,'v');
    assert.equal(replies.find(item=>item.text==='answer two').playerId,'u');
  }finally{runner.close();}
});
test('stop reaches active session during prompt and drops only that player queued messages',async()=>{
  const polls=[[message('one'),message('two')],[message('stop','p','u','cancel')]];const replies=[];let release;let cancelled=0;
  const backend={async call(method,params){if(method==='chat_poll'){assert.match(params.client_id,/^[0-9a-f-]{36}$/);return {messages:polls.shift()??[]};}replies.push(params);return {};}};
  const runner=new ChatRunner(backend,()=>({async prompt(text,reply){await new Promise(done=>release=done);await reply('stopped',true);},async cancel(){cancelled++;release();},close(){}}));
  try{await runner.poll();await eventually(()=>release);await runner.poll();assert.equal(cancelled,1);assert.ok(replies.some(item=>item.id==='two'&&item.done));}finally{runner.close();}
});
test('replayed polling message ID does not start duplicate agent turn',async()=>{
  let calls=0;const request=message('one');
  const backend={async call(method){return method==='chat_poll'?{messages:[request]}:{};}};
  const runner=new ChatRunner(backend,()=>({async prompt(){calls++;},async cancel(){},close(){}}));
  try{await runner.poll();await pause(1);await runner.poll();await pause(1);assert.equal(calls,1);}finally{runner.close();}
});

test('player position, gaze and target are forwarded for each request without arbitrary payload fields',()=>{
 const first=promptWithContext({...message('build here'),playerPosition:{x:1,y:65,z:3,yaw:90,pitch:10,secret:'hidden'},lookTarget:{x:5,y:64,z:8},worldId:'world'});
 assert.ok(first.includes('"x":1'));assert.ok(first.includes('"yaw":90'));assert.ok(first.includes('"lookTarget"'));assert.ok(!first.includes('hidden'));
 const next=promptWithContext({...message('build here'),playerPosition:{x:9,y:65,z:3}});assert.ok(next.includes('"x":9'));
});
