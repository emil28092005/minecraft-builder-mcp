import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { resolve } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { toolResult } from '../dist/tools.js';

test('real stdio MCP lists tools, validates recipes, calls backend and returns conflicts', async t => {
  const seen=[];
  const backend=createServer(async(req,res)=>{
    let body='';for await(const chunk of req) body+=chunk;
    const rpc=JSON.parse(body);seen.push(rpc);
    res.setHeader('content-type','application/json');
    res.end(JSON.stringify(rpc.method==='build_apply'?{ok:false,error:{code:'conflict',message:'Manual block changed.'}}:{ok:true,result:{project_id:'project',capabilities:['box']}}));
  });backend.listen(0,'127.0.0.1');await once(backend,'listening');
  const transport=new StdioClientTransport({command:process.execPath,args:[resolve('dist/mcp.js')],env:{MCB_BACKEND_URL:`http://127.0.0.1:${backend.address().port}`,MCB_AGENT_TOKEN:'agent',MCB_PROJECT_ID:'project',MCB_PLAYER_ID:'player'},stderr:'pipe'});
  const client=new Client({name:'test',version:'1'});
  t.after(async()=>{await client.close();backend.closeAllConnections();backend.close();});
  await client.connect(transport);
  assert.ok(client.getInstructions().includes('Avoid large rectangular plateaus'));
  assert.ok(client.getInstructions().includes('NOT as terrain_preview parameters'));
  const list=await client.listTools();assert.equal(list.tools.length,19);
  assert.ok(list.tools.some(tool=>tool.name==='schematic_import_prepare'));assert.ok(!list.tools.some(tool=>tool.name==='chat_poll'));
  const context=await client.callTool({name:'project_context',arguments:{player_id:'forged'}});
  assert.equal(JSON.parse(context.content[0].text).project_id,'project');
  assert.equal(seen[0].params.player_id,'player');
  const invalid=await client.callTool({name:'build_prepare',arguments:{recipe:{version:1,operations:[{type:'execute',code:'bad'}]}}});
  assert.equal(invalid.isError,true);assert.equal(seen.length,1);
  const prepared=await client.callTool({name:'build_prepare',arguments:{recipe:{version:1,operations:[{type:'box',min:{x:0,y:64,z:0},max:{x:2,y:66,z:2},block:'minecraft:stone'}]}}});
  assert.ok(!prepared.isError);assert.equal(seen[1].method,'build_prepare');
  const conflict=await client.callTool({name:'build_apply',arguments:{plan_id:'plan',plan_hash:'hash',idempotency_key:'key'}});
  assert.equal(conflict.isError,true);assert.equal(JSON.parse(conflict.content[0].text).code,'conflict');
  const beforeAssets=seen.length;
  const invalidPath=await client.callTool({name:'schematic_import_prepare',arguments:{asset_id:'../../secret',target:{x:0,y:64,z:0}}});assert.equal(invalidPath.isError,true);
  const invalidRotation=await client.callTool({name:'schematic_import_prepare',arguments:{asset_id:'asset',target:{x:0,y:64,z:0},rotation:45}});assert.equal(invalidRotation.isError,true);assert.equal(seen.length,beforeAssets);
  await client.callTool({name:'schematic_import_prepare',arguments:{asset_id:'asset',target:{x:0,y:64,z:0},rotation:90}});assert.equal(seen.at(-1).params.rotation,90);
  await client.callTool({name:'asset_list',arguments:{query:'tower'}});assert.equal(seen.at(-1).params.query,'tower');
  const recipe={version:1,min:{x:0,y:0,z:0},max:{x:31,y:31,z:31},base_height:8,seed:1,mode:'sculpt',noise:{amplitude:3,scale:16},palette:{rock:'minecraft:stone',soil:'minecraft:dirt',surface:'minecraft:grass_block',soil_depth:2},features:[{type:'plateau',min:{x:2,z:2},max:{x:8,z:8},height:14,falloff:4}],preserve:[]};
  await client.callTool({name:'terrain_preview',arguments:{recipe}});assert.equal(seen.at(-1).method,'terrain_preview');assert.equal(seen.at(-1).params.resolution,128);
  await client.callTool({name:'terrain_prepare',arguments:{terrain_id:'a'.repeat(64),tile_index:1}});assert.equal(seen.at(-1).method,'terrain_prepare');
  const beforeTerrain=seen.length;
  for(const args of [{recipe:{...recipe,script:'execute'}},{recipe:{...recipe,features:[{type:'channel',points:[],width:2,falloff:3,height:0}]}},{recipe:{...recipe,palette:{...recipe.palette,rock:'minecraft:water'}}}]) assert.equal((await client.callTool({name:'terrain_preview',arguments:args})).isError,true);
  assert.equal((await client.callTool({name:'terrain_prepare',arguments:{terrain_id:'../../file',tile_index:-1}})).isError,true);
  assert.equal(seen.length,beforeTerrain);
  const brush={min:{x:-4,y:0,z:-4},max:{x:4,y:12,z:4},center:{x:0,z:0},radius:3,action:'raise',amount:2};
  await client.callTool({name:'terrain_brush_prepare',arguments:{brush}});
  assert.equal(seen.at(-1).method,'terrain_brush_prepare');assert.equal(seen.at(-1).params.brush.falloff,0.5);
  const beforeBrush=seen.length;
  for(const bad of [{...brush,radius:50},{...brush,strength:2},{...brush,action:'execute'},{...brush,script:'run'}])assert.equal((await client.callTool({name:'terrain_brush_prepare',arguments:{brush:bad}})).isError,true);
  assert.equal(seen.length,beforeBrush);
});
test('material discovery uses bounded read-only calls and never expands registry in schemas or instructions', async t => {
  const seen=[];
  const backend=createServer(async(req,res)=>{
    let body='';for await(const chunk of req) body+=chunk;
    const rpc=JSON.parse(body);seen.push(rpc);
    const result=rpc.method==='material_search'
      ?{catalog_version:'v1',query:rpc.params.query??'',kind:rpc.params.kind,total:2,results:[{id:'minecraft:copper_door',block:true,item:true}],next_cursor:'next-page'}
      :rpc.method==='material_describe'
        ?{catalog_version:'v1',id:'minecraft:copper_door',block:true,item:true,placeable:true,default_state:'minecraft:copper_door[facing=north,half=lower,hinge=left,open=false,powered=false]',properties:{facing:['north','south','east','west'],half:['lower','upper'],hinge:['left','right'],open:['false','true'],powered:['false','true']}}
        :{status:'prepared'};
    res.setHeader('content-type','application/json');res.end(JSON.stringify({ok:true,result}));
  });backend.listen(0,'127.0.0.1');await once(backend,'listening');
  const transport=new StdioClientTransport({command:process.execPath,args:[resolve('dist/mcp.js')],env:{MCB_BACKEND_URL:`http://127.0.0.1:${backend.address().port}`,MCB_AGENT_TOKEN:'agent',MCB_PROJECT_ID:'project',MCB_PLAYER_ID:'player'},stderr:'pipe'});
  const client=new Client({name:'materials-test',version:'1'});
  t.after(async()=>{await client.close();backend.closeAllConnections();backend.close();});
  await client.connect(transport);
  const list=await client.listTools();
  const discovery=list.tools.filter(tool=>tool.name.startsWith('material_'));
  assert.deepEqual(discovery.map(tool=>tool.name),['material_search','material_describe']);
  for(const tool of discovery){assert.equal(tool.annotations.readOnlyHint,true);assert.equal(tool.annotations.idempotentHint,true);assert.equal(tool.annotations.destructiveHint,false);}
  assert.ok(client.getInstructions().includes('project_context contains only a catalog summary'));
  assert.ok(client.getInstructions().includes('do not enumerate the registry'));
  assert.ok(!JSON.stringify(discovery).includes('minecraft:copper_door'),'registry entries must be discovered, not embedded in the MCP tool catalog');
  const found=await client.callTool({name:'material_search',arguments:{query:'copper door'}});
  assert.equal(seen.at(-1).method,'material_search');assert.equal(seen.at(-1).params.limit,16);assert.equal(seen.at(-1).params.kind,'block');
  assert.equal(JSON.parse(found.content[0].text).results[0].id,'minecraft:copper_door');
  await client.callTool({name:'material_search',arguments:{query:'copper door',kind:'all',limit:32,cursor:'next-page'}});
  assert.equal(seen.at(-1).params.cursor,'next-page');assert.equal(seen.at(-1).params.kind,'all');
  const described=JSON.parse((await client.callTool({name:'material_describe',arguments:{id:'minecraft:copper_door'}})).content[0].text);
  assert.equal(seen.at(-1).method,'material_describe');assert.deepEqual(described.properties.half,['lower','upper']);
  const beforeInvalid=seen.length;
  for(const arguments_ of [{query:'x'.repeat(97)},{kind:'entity'},{limit:0},{limit:33},{limit:1.5},{cursor:''},{cursor:'x'.repeat(101)}]){
    assert.equal((await client.callTool({name:'material_search',arguments:arguments_})).isError,true);
  }
  for(const id of ['copper_door','minecraft:stone[foo=bar]','minecraft:chest{Items:[]}','other:stone','minecraft:../stone',`minecraft:${'x'.repeat(119)}`]){
    assert.equal((await client.callTool({name:'material_describe',arguments:{id}})).isError,true);
  }
  assert.equal(seen.length,beforeInvalid,'invalid discovery arguments must be rejected before backend transport');
  const box=block=>({version:1,operations:[{type:'box',min:{x:0,y:64,z:0},max:{x:0,y:64,z:0},block}]});
  for(const block of ['minecraft:copper_door[facing=west,half=lower,hinge=left,open=false,powered=false]','minecraft:water[level=0]']){
    assert.ok(!(await client.callTool({name:'build_prepare',arguments:{recipe:box(block)}})).isError,'ordinary recipes must not retain the old material allowlist');
  }
  const snapshot={pos:{x:0,y:64,z:0},state:'minecraft:chest[facing=north,type=single,waterlogged=false]',snapshot_id:'a'.repeat(64)};
  assert.ok(!(await client.callTool({name:'build_prepare',arguments:{recipe:box('minecraft:chest[facing=west]'),expected_blocks:[snapshot]}})).isError);
  assert.equal(seen.at(-1).params.expected_blocks[0].snapshot_id,snapshot.snapshot_id,'block-entity snapshot digest must survive MCP transport unchanged');
  const beforeBadSnapshot=seen.length;
  for(const snapshot_id of ['a'.repeat(63),'A'.repeat(64),'not-a-snapshot']){
    assert.equal((await client.callTool({name:'build_prepare',arguments:{recipe:box('minecraft:stone'),expected_blocks:[{...snapshot,snapshot_id}]}})).isError,true);
  }
  assert.equal(seen.length,beforeBadSnapshot);
  const beforeUnsafe=seen.length;
  for(const block of ['minecraft:command_block{Command:"say hello"}',`minecraft:stone[p=${'x'.repeat(1024)}]`]){
    assert.equal((await client.callTool({name:'build_prepare',arguments:{recipe:box(block)}})).isError,true);
  }
  assert.equal(seen.length,beforeUnsafe,'state length and no-NBT boundaries must hold before backend transport');
});
test('camera image is a native MCP image rather than a text context dump',()=>{
  const result=toolResult({status:'completed',captureId:'c1',imageBase64:'YWJj',mimeType:'image/png'});
  assert.equal(result.content[1].type,'image');assert.ok(!result.content[0].text.includes('YWJj'));
  assert.throws(()=>toolResult({status:'pending',imageBase64:'YWJj',mimeType:'image/png'}),/invalid/);
  assert.throws(()=>toolResult({blocks:'a'.repeat(70000)}),/too large/);
});
