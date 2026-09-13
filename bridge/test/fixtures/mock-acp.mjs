import { createInterface } from 'node:readline';
import { appendFileSync } from 'node:fs';
import { setTimeout as pause } from 'node:timers/promises';
import { greetingChunks, followUpChunks, longReply, overlongWord, tokenChunks } from './streamed-replies.mjs';
const send = value => process.stdout.write(JSON.stringify({jsonrpc:'2.0',...value})+'\n');
const startupFailure = (sessionId = 'session-one') => send({method:'session/update',params:{sessionId,update:{sessionUpdate:'tool_call',toolCallId:'mcp_startup.minecraft-builder-mcp',title:'mcp__minecraft-builder-mcp__startup',kind:'other',status:'failed',content:[{type:'content',content:{type:'text',text:'PRIVATE STARTUP DETAIL agent-secret'}}]}}});
let promptId;let cancelled=false;let turn=0;
for await (const line of createInterface({input:process.stdin})) {
  const msg=JSON.parse(line);
  if(process.argv[2]) appendFileSync(process.argv[2],JSON.stringify(msg)+'\n');
  if(msg.method==='initialize') send({id:msg.id,result:{protocolVersion:1,agentCapabilities:{loadSession:true},authMethods:[]}});
  else if(msg.method==='session/new') {
    if(process.argv[3]==='mcp-fail-new') startupFailure();
    if(process.argv[3]==='mcp-fail-other-session') startupFailure('unrelated-session');
    send({id:msg.id,result:{sessionId:'session-one'}});
  }
  else if(msg.method==='session/load') {
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text:'PRIVATE HISTORY'}}}});
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'tool_call',toolCallId:'old-mcp-tool-call',title:'mcp__minecraft-builder-mcp__project_context',kind:'other',status:'failed',content:[{type:'content',content:{type:'text',text:'PRIVATE HISTORY FAILED TOOL'}}]}}});
    if(process.argv[3]==='mcp-fail-load') startupFailure();
    send({id:msg.id,result:{}});
  }
  else if(msg.method==='session/prompt') {
    turn++;promptId=msg.id;
    const content=msg.params.prompt[0].text;
    if(content.includes('mcp-fail-active')) {startupFailure();continue;}
    if(content.includes('wait-for-cancel')) continue;
    if(content.includes('mcp-approval-')) {
      const mode=content.match(/mcp-approval-([a-z-]+)/)?.[1];
      const server=mode==='foreign'?'other-server':'minecraft-builder-mcp';
      const tool=mode==='unknown'?'run_shell':mode==='material-search'?'material_search':mode==='material-describe'?'material_describe':mode==='terrain-preview'?'terrain_preview':mode==='terrain-prepare'?'terrain_prepare':mode==='terrain-brush'?'terrain_brush_prepare':'build_prepare';
      const sid=mode==='wrong-session'?'other-session':'session-one';
      if(mode!=='uncorrelated') send({method:'session/update',params:{sessionId:sid,update:{sessionUpdate:'tool_call',toolCallId:'mc-call',kind:'execute',title:`mcp.${server}.${tool}`,status:'in_progress',rawInput:{server,tool,arguments:{}},_meta:{is_mcp_tool_call:true}}}});
      if(mode==='completed') send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'tool_call_update',toolCallId:'mc-call',status:'completed'}}});
      send({id:'approval',method:'session/request_permission',params:{sessionId:'session-one',toolCall:{toolCallId:'mc-call',kind:'execute',status:'pending'},...(mode==='no-meta'?{}:{_meta:{is_mcp_tool_approval:true}}),options:[{optionId:mode==='persistent'?'allow_always':'allow_once',name:'Allow',kind:mode==='persistent'?'allow_always':'allow_once'}]}});continue;
    }
    if(content.includes('request-permission')) {send({id:'approval',method:'session/request_permission',params:{sessionId:'session-one',toolCall:{toolCallId:'dangerous',title:'Permission',kind:'execute'},options:[{optionId:'yes',name:'Allow',kind:'allow_once'}]}});continue;}
    if(content.includes('stream-greeting') || content.includes('stream-follow-up') || content.includes('stream-slow-delivery') || content.includes('stream-overlong-word')) {
      const greeting = content.includes('stream-greeting');
      const chunks = greeting ? greetingChunks : content.includes('stream-follow-up') ? followUpChunks : tokenChunks(content.includes('stream-overlong-word') ? overlongWord : longReply);
      // Real models can think for seconds before emitting their first incomplete token.
      if(greeting) await pause(1600);
      for(const text of chunks) {
        send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text}}}});
        await pause(greeting ? 12 : 1);
      }
      send({id:msg.id,result:{stopReason:'end_turn'}});
      continue;
    }
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_thought_chunk',content:{type:'text',text:'SECRET THOUGHT'}}}});
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text:`Built turn ${turn}.`}}}});
    send({id:msg.id,result:{stopReason:'end_turn'}});
  } else if(msg.method==='session/cancel') {cancelled=true;send({id:promptId,result:{stopReason:'cancelled'}});}
  else if(msg.id==='approval') {send({id:promptId,result:{stopReason:'end_turn'}});}
}
