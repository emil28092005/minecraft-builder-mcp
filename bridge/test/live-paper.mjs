// Opt-in integration driver. It mutates and restores a tiny all-air area on a real development Paper server.
// Credentials arrive only through the environment; this driver never prints them.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

for (const name of ['MCB_AGENT_TOKEN','MCB_PLAYER_ID','MCB_PROJECT_ID']) if (!process.env[name]) throw new Error(`${name} is required`);
const transport = new StdioClientTransport({ command: process.execPath, args: [resolve('dist/mcp.js')], env: Object.fromEntries(Object.entries(process.env).filter(([key,value]) => value !== undefined && key !== 'MCB_TOKEN')), stderr: 'pipe' });
const client = new Client({ name: 'minecraft-builder-live-smoke', version: '0.1.0' });
async function tool(name, args = {}, allowError = false) {
  for (let attempt = 0; attempt < 100; attempt++) {
    const result = await client.callTool({ name, arguments: args });
    const data = JSON.parse(result.content.find(item => item.type === 'text').text);
    if (result.isError && data.code === 'busy') { await pause(50); continue; }
    if (result.isError && !allowError) throw new Error(`${name}: ${data.code}: ${data.message}`);
    return { data, isError: result.isError === true };
  }
  throw new Error(`${name}: backend remained busy`);
}
async function finished(operation_id) {
  for (let attempt=0; attempt<400; attempt++) {
    const {data} = await tool('operation_status',{operation_id});
    if (['applied','conflict','failed','cancelled','recovery_required'].includes(data.status)) return data;
    await pause(50);
  }
  throw new Error(`Operation did not finish within 20 seconds: ${operation_id}`);
}
const min = {x:Number(process.env.MCB_TEST_X ?? 0), y:Number(process.env.MCB_TEST_Y ?? 96), z:Number(process.env.MCB_TEST_Z ?? 0)};
const max = {x:min.x+2,y:min.y+2,z:min.z+2};
let operation;
try {
  await client.connect(transport);
  const {data:context} = await tool('project_context');
  console.log(JSON.stringify({step:'context',project_id:context.project_id,world_id:context.world_id,capabilities:context.capabilities}));
  const {data:before} = await tool('region_inspect',{min,max,detail:'blocks'});
  assert.equal(before.blocks.length,27); assert.ok(before.blocks.every(block=>block.state==='minecraft:air'),'Test area must be entirely air; choose MCB_TEST_X/Y/Z in the configured project region.');
  const {data:plan} = await tool('build_prepare',{recipe:{version:1,operations:[{type:'box',min,max,block:'minecraft:stone_bricks',hollow:true}]}});
  assert.equal(plan.changed_blocks,26);
  const apply = {plan_id:plan.plan_id,plan_hash:plan.plan_hash,idempotency_key:`live-smoke-${randomUUID()}`};
  const {data:started} = await tool('build_apply',apply); operation=started.operation_id;
  const done = await finished(operation); assert.equal(done.status,'applied'); assert.equal(done.written,26);
  const {data:replayed} = await tool('build_apply',apply); assert.equal(replayed.operation_id,operation);
  const {data:after} = await tool('region_inspect',{min,max,detail:'blocks'});
  assert.equal(after.blocks.filter(block=>block.state==='minecraft:stone_bricks').length,26);
  assert.equal(after.blocks.filter(block=>block.state==='minecraft:air').length,1);
  console.log(JSON.stringify({step:'build-and-idempotency',operation_id:operation,status:done.status,written:done.written}));
  const {data:exported}=await tool('schematic_export',{name:'Live MCP hollow box',min,max,origin:min});
  assert.match(exported.assetId,/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/);
  const {data:library}=await tool('asset_list',{query:'Live MCP hollow box'});
  assert.ok(library.assets.some(asset=>asset.assetId===exported.assetId),'Exported schematic must be listed by asset ID');
  console.log(JSON.stringify({step:'schematic-export',asset_id:exported.assetId,width:exported.width,height:exported.height,length:exported.length}));
  const {data:undo} = await tool('operation_undo_prepare',{operation_id:operation});
  const {data:undoStarted} = await tool('build_apply',{plan_id:undo.plan_id,plan_hash:undo.plan_hash,idempotency_key:`live-undo-${randomUUID()}`});
  const undoDone=await finished(undoStarted.operation_id); assert.equal(undoDone.status,'applied');
  const {data:restored}=await tool('region_inspect',{min,max,detail:'blocks'});assert.ok(restored.blocks.every(block=>block.state==='minecraft:air'));
  console.log(JSON.stringify({step:'checked-undo',operation_id:undoStarted.operation_id,status:undoDone.status,restored_air_blocks:27}));
  const {data:importPlan}=await tool('schematic_import_prepare',{asset_id:exported.assetId,target:min,rotation:0});
  assert.equal(importPlan.changed_blocks,26);
  const {data:importStarted}=await tool('build_apply',{plan_id:importPlan.plan_id,plan_hash:importPlan.plan_hash,idempotency_key:`live-import-${randomUUID()}`});
  operation=importStarted.operation_id;
  const imported=await finished(operation);assert.equal(imported.status,'applied');assert.equal(imported.written,26);
  const {data:importedBlocks}=await tool('region_inspect',{min,max,detail:'blocks'});
  assert.equal(importedBlocks.blocks.length,27);
  assert.equal(importedBlocks.blocks.filter(block=>block.state==='minecraft:stone_bricks').length,26);
  assert.equal(importedBlocks.blocks.filter(block=>block.state==='minecraft:air').length,1);
  const {data:importUndo}=await tool('operation_undo_prepare',{operation_id:operation});
  const {data:importUndoStarted}=await tool('build_apply',{plan_id:importUndo.plan_id,plan_hash:importUndo.plan_hash,idempotency_key:`live-import-undo-${randomUUID()}`});
  const importUndoDone=await finished(importUndoStarted.operation_id);assert.equal(importUndoDone.status,'applied');
  const {data:importRestored}=await tool('region_inspect',{min,max,detail:'blocks'});
  assert.equal(importRestored.blocks.length,27);assert.ok(importRestored.blocks.every(block=>block.state==='minecraft:air'));
  console.log(JSON.stringify({step:'schematic-roundtrip-and-undo',asset_id:exported.assetId,import_operation_id:operation,undo_operation_id:importUndoStarted.operation_id,written:imported.written,restored_air_blocks:27}));
  operation=undefined;
  const cameras = await tool('camera_list');
  if(!cameras.data.configured){const unavailable=await tool('camera_capture',{pose:{x:min.x,y:min.y,z:min.z,yaw:0,pitch:0}},true);assert.equal(unavailable.isError,true);assert.equal(unavailable.data.code,'camera_unavailable');console.log(JSON.stringify({step:'camera',status:'honestly-unavailable'}));}
  const bounds=context.region;
  const outside={x:bounds.max.x+1,y:bounds.min.y,z:bounds.min.z};
  const denied=await tool('region_inspect',{min:outside,max:outside},true);assert.equal(denied.isError,true);assert.equal(denied.data.code,'out_of_bounds');
  console.log(JSON.stringify({step:'scope-boundary',status:'rejected',code:denied.data.code}));
  console.log('LIVE MCP SMOKE PASSED');
} catch(error) {
  if(operation) console.error(`Inspect operation ${operation}; test failure can leave blocks. No blind cleanup was attempted.`);
  throw error;
} finally { await client.close(); }
