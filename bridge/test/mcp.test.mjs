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
  const list=await client.listTools();assert.equal(list.tools.length,14);
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
});
test('camera image is a native MCP image rather than a text context dump',()=>{
  const result=toolResult({status:'completed',captureId:'c1',imageBase64:'YWJj',mimeType:'image/png'});
  assert.equal(result.content[1].type,'image');assert.ok(!result.content[0].text.includes('YWJj'));
  assert.throws(()=>toolResult({status:'pending',imageBase64:'YWJj',mimeType:'image/png'}),/invalid/);
  assert.throws(()=>toolResult({blocks:'a'.repeat(70000)}),/too large/);
});
