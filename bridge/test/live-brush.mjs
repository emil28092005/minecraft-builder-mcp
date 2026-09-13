// Opt-in isolated Paper test: relative edits, native preview, halo conflicts, full restoration.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { writeFile } from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
const client=new Client({name:'brush-live-test',version:'1'});
const transport=new StdioClientTransport({command:process.execPath,args:[resolve('dist/mcp.js')],env:Object.fromEntries(Object.entries(process.env).filter(([k,v])=>v!==undefined&&k!=='MCB_TOKEN')),stderr:'pipe'});
async function call(name,args={},allowError=false){for(let i=0;i<100;i++){
 const result=await client.callTool({name,arguments:args});const data=JSON.parse(result.content.find(c=>c.type==='text').text);
 if(result.isError&&data.code==='busy'){await pause(100);continue;}
 if(result.isError&&!allowError)throw new Error(`${name}: ${data.code}: ${data.message}`);
 return {data,result};
}throw new Error('Still busy');}
async function done(id){for(let i=0;i<1000;i++){const {data}=await call('operation_status',{operation_id:id});if(['applied','conflict','cancelled','failed','recovery_required'].includes(data.status))return data;await pause(50);}throw new Error(`Still running: ${id}`);}
async function apply(plan){const args={plan_id:plan.plan_id,plan_hash:plan.plan_hash,idempotency_key:'brush-test-'+randomUUID()};const {data}=await call('build_apply',args);return await done(data.operation_id);}
async function undo(id){const {data}=await call('operation_undo_prepare',{operation_id:id});const result=await apply(data);assert.equal(result.status,'applied');}
const min={x:-4,y:80,z:-4},max={x:4,y:92,z:4};
async function air(){const {data}=await call('region_inspect',{min,max,detail:'summary'});assert.deepEqual(data.palette,{'minecraft:air':1053});}
async function surface(){const {data}=await call('region_inspect',{min:{x:0,y:80,z:0},max:{x:0,y:92,z:0},detail:'blocks'});return Math.max(...data.blocks.filter(b=>b.state!=='minecraft:air').map(b=>b.pos.y));}
const brush={min,max,center:{x:0,z:0},radius:3,strength:1,falloff:0.5};
let base;
try{
 await client.connect(transport);
 assert.ok((await call('project_context')).data.capabilities.includes('terrain_brush_prepare'));await air();
 const {data:basePlan}=await call('build_prepare',{recipe:{version:1,operations:[
  {type:'box',min,max:{x:4,y:83,z:4},block:'minecraft:stone'},
  {type:'box',min:{x:-4,y:84,z:-4},max:{x:4,y:84,z:4},block:'minecraft:grass_block'},
 ]}});base=await apply(basePlan);assert.equal(base.status,'applied');assert.equal(await surface(),84);
 for(const [action,extra,expected] of [['raise',{amount:3},87],['lower',{amount:2},82],['flatten',{height:86},86]]){
  const {data:plan,result}=await call('terrain_brush_prepare',{brush:{...brush,action,...extra}});
  assert.equal(plan.plan_state,'prepared');assert.equal(plan.dependency_blocks,1053);assert.equal(plan.world_edited,false);assert.equal(await surface(),84);
  const png=result.content.find(c=>c.type==='image');assert.ok(png);
  if(action==='raise')await writeFile('../docs/references/terrain-brush-live-preview.png',Buffer.from(png.data,'base64'));
  const applied=await apply(plan);assert.equal(applied.status,'applied');assert.equal(await surface(),expected);
  await undo(applied.operation_id);assert.equal(await surface(),84);
  console.log(JSON.stringify({action,status:'passed',written:applied.written,center_after:expected,undo_height:84}));
 }
 const {data:spikePlan}=await call('terrain_brush_prepare',{brush:{...brush,radius:1,action:'raise',amount:4,falloff:0}});const spike=await apply(spikePlan);assert.equal(spike.status,'applied');
 const {data:smoothPlan}=await call('terrain_brush_prepare',{brush:{...brush,action:'smooth',smooth_radius:1}});const smooth=await apply(smoothPlan);assert.equal(smooth.status,'applied');assert.ok(await surface()<88);await undo(smooth.operation_id);assert.equal(await surface(),88);
 const spikeMin={x:-1,y:84,z:-1},spikeMax={x:1,y:88,z:1};
 const spikeSnapshot=(await call('region_inspect',{min:spikeMin,max:spikeMax,detail:'blocks'})).data.blocks;
 for(const b of spikeSnapshot){const inside=b.pos.x*b.pos.x+b.pos.z*b.pos.z<=1;assert.equal(b.state,inside?(b.pos.y===88?'minecraft:grass_block[snowy=false]':'minecraft:stone'):(b.pos.y===84?'minecraft:grass_block[snowy=false]':'minecraft:air'));}
 const {data:removeSpike}=await call('build_prepare',{recipe:{version:1,operations:[{type:'box',min:{x:-1,y:85,z:-1},max:spikeMax,block:'minecraft:air'},{type:'box',min:spikeMin,max:{x:1,y:84,z:1},block:'minecraft:grass_block'}]}});
 assert.equal((await apply(removeSpike)).status,'applied');assert.equal(await surface(),84);
 console.log(JSON.stringify({action:'smooth',status:'passed',written:smooth.written}));
 const {data:stale}=await call('terrain_brush_prepare',{brush:{...brush,action:'raise',amount:2}});
 const point={x:4,y:86,z:0};const {data:foreignPlan}=await call('build_prepare',{recipe:{version:1,operations:[{type:'box',min:point,max:point,block:'minecraft:gold_block'}]}});const foreign=await apply(foreignPlan);assert.equal(foreign.status,'applied');
 const conflict=await apply(stale);assert.equal(conflict.status,'conflict');assert.equal(conflict.written,0);
 const denied=await call('terrain_brush_prepare',{brush:{...brush,action:'raise',amount:2}},true);assert.ok(denied.result.isError);await undo(foreign.operation_id);
 const {data:empty}=await call('terrain_brush_prepare',{brush:{...brush,action:'flatten',height:84}});assert.equal(empty.plan_state,'empty');assert.ok(!empty.plan_id);
 // Base ownership has been superseded by checked brush undos. Verify every fixture cell,
 // then prepare a fresh checked cleanup of this isolated fixture; never force the old undo.
 const baseMax={x:4,y:84,z:4};
 const restored=(await call('region_inspect',{min,max:baseMax,detail:'blocks'})).data.blocks;
 assert.equal(restored.length,405);for(const b of restored)assert.equal(b.state,b.pos.y===84?'minecraft:grass_block[snowy=false]':'minecraft:stone');
 const {data:cleanup}=await call('build_prepare',{recipe:{version:1,operations:[{type:'box',min,max:baseMax,block:'minecraft:air'}]}});
 assert.equal((await apply(cleanup)).status,'applied');base=undefined;await air();console.log('LIVE BRUSH MCP PASSED; full fixture restored to air');
}finally{if(base)console.error(`Fixture needs inspection; base operation: ${base.operation_id}`);await client.close();}
