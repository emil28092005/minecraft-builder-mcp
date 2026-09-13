// Opt-in live test in an isolated all-air fixture. No credentials are printed.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { readFile } from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
const client=new Client({name:'terrain-live-test',version:'1'});
const transport=new StdioClientTransport({command:process.execPath,args:[resolve('dist/mcp.js')],env:Object.fromEntries(Object.entries(process.env).filter(([k,v])=>v!==undefined&&k!=='MCB_TOKEN')),stderr:'pipe'});
async function call(name,args={},allowError=false){for(let i=0;i<100;i++){
 const result=await client.callTool({name,arguments:args});const data=JSON.parse(result.content.find(c=>c.type==='text').text);
 if(result.isError&&data.code==='busy'){await pause(100);continue;}
 if(result.isError&&!allowError)throw new Error(`${name}: ${data.code}: ${data.message}`);
 return {data,result};
}throw new Error('Still busy');}
async function done(id){for(let i=0;i<1000;i++){const {data}=await call('operation_status',{operation_id:id});if(['applied','conflict','cancelled','failed','recovery_required'].includes(data.status))return data;await pause(50);}throw new Error(`Still running: ${id}`);}
async function apply(plan){const args={plan_id:plan.plan_id,plan_hash:plan.plan_hash,idempotency_key:'terrain-test-'+randomUUID()};const {data}=await call('build_apply',args);const result=await done(data.operation_id);return {args,result};}
async function undo(id){const {data}=await call('operation_undo_prepare',{operation_id:id});const {result}=await apply(data);assert.equal(result.status,'applied');return result;}
const recipe=JSON.parse(await readFile('../examples/terrain/small-hill.json','utf8'));
const {min,max}=recipe;
const inspect=async()=> (await call('region_inspect',{min,max,detail:'blocks'})).data.blocks;
const air=blocks=>assert.ok(blocks.every(b=>b.state==='minecraft:air'));
try{
 await client.connect(transport);
 const {data:context}=await call('project_context');assert.ok(context.capabilities.includes('terrain_prepare'));
 air(await inspect());
 const {data:preview,result:previewResult}=await call('terrain_preview',{recipe});
 assert.equal(preview.kind,'terrain_heightmap_preview');assert.equal(preview.world_verified,false);assert.equal(preview.tile_count,1);
 const png=previewResult.content.find(c=>c.type==='image');assert.ok(png);assert.equal(Buffer.from(png.data,'base64').subarray(1,4).toString(),'PNG');
 air(await inspect());
 const {data:plan}=await call('terrain_prepare',{terrain_id:preview.terrain_id,tile_index:0});air(await inspect());assert.ok(plan.changed_blocks>0);
 const {args,result}=await apply(plan);assert.equal(result.status,'applied');
 assert.equal((await call('build_apply',args)).data.operation_id,result.operation_id);
 const built=await inspect();assert.ok(built.some(b=>b.state.startsWith('minecraft:grass_block')));assert.ok(built.some(b=>b.state==='minecraft:dirt'));
 assert.equal(built.filter(b=>b.state!=='minecraft:air').length,result.written);
 assert.equal((await call('terrain_prepare',{terrain_id:preview.terrain_id,tile_index:0})).data.status,'empty');
 await undo(result.operation_id);air(await inspect());
 console.log(JSON.stringify({check:'terrain-native-preview-prepare-apply-idempotency-undo',status:'passed',written:result.written}));
 const {data:stale}=await call('terrain_prepare',{terrain_id:preview.terrain_id,tile_index:0});
 const {data:goldPlan}=await call('build_prepare',{recipe:{version:1,operations:[{type:'box',min,max:min,block:'minecraft:gold_block'}]}});
 const {result:gold}=await apply(goldPlan);assert.equal(gold.status,'applied');
 const denied=await call('terrain_prepare',{terrain_id:preview.terrain_id,tile_index:0},true);assert.equal(denied.data.code,'protected_terrain');
 const {result:conflict}=await apply(stale);assert.equal(conflict.status,'conflict');assert.equal(conflict.written,0);
 const masked=structuredClone(recipe);masked.preserve=[{min,max:min}];
 const {data:maskedPreview}=await call('terrain_preview',{recipe:masked});
 const {data:maskedPlan}=await call('terrain_prepare',{terrain_id:maskedPreview.terrain_id,tile_index:0});
 const {result:maskedDone}=await apply(maskedPlan);assert.equal(maskedDone.status,'applied');
 assert.equal((await call('region_inspect',{min,max:min,detail:'blocks'})).data.blocks[0].state,'minecraft:gold_block');
 await undo(maskedDone.operation_id);await undo(gold.operation_id);air(await inspect());
 console.log(JSON.stringify({check:'protected-existing-build-preserve-mask-and-stale-plan-conflict',status:'passed'}));
 const empty=structuredClone(recipe);empty.preserve=[{min,max}];
 const {data:emptyPreview}=await call('terrain_preview',{recipe:empty});assert.equal((await call('terrain_prepare',{terrain_id:emptyPreview.terrain_id,tile_index:0})).data.status,'empty');
 const outside=structuredClone(recipe);outside.min.x=200;outside.max.x=207;
 const {data:outsidePreview}=await call('terrain_preview',{recipe:outside});assert.equal((await call('terrain_prepare',{terrain_id:outsidePreview.terrain_id,tile_index:0},true)).data.code,'out_of_bounds');
 assert.equal((await call('terrain_prepare',{terrain_id:'0'.repeat(64),tile_index:0},true)).data.code,'not_found');
 air(await inspect());console.log('LIVE TERRAIN MCP PASSED; test area restored to air');
}finally{await client.close();}
