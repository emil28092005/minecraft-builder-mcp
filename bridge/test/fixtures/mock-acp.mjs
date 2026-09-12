import { createInterface } from 'node:readline';
import { appendFileSync } from 'node:fs';
const send = value => process.stdout.write(JSON.stringify({jsonrpc:'2.0',...value})+'\n');
let promptId;let cancelled=false;let turn=0;
for await (const line of createInterface({input:process.stdin})) {
  const msg=JSON.parse(line);
  if(process.argv[2]) appendFileSync(process.argv[2],JSON.stringify(msg)+'\n');
  if(msg.method==='initialize') send({id:msg.id,result:{protocolVersion:1,agentCapabilities:{loadSession:true},authMethods:[]}});
  else if(msg.method==='session/new') send({id:msg.id,result:{sessionId:'session-one'}});
  else if(msg.method==='session/load') {
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text:'PRIVATE HISTORY'}}}});
    send({id:msg.id,result:{}});
  }
  else if(msg.method==='session/prompt') {
    turn++;promptId=msg.id;
    const content=msg.params.prompt[0].text;
    if(content.includes('wait-for-cancel')) continue;
    if(content.includes('request-permission')) {send({id:'approval',method:'session/request_permission',params:{sessionId:'session-one',toolCall:{toolCallId:'dangerous',title:'Permission',kind:'execute'},options:[{optionId:'yes',name:'Allow',kind:'allow_once'}]}});continue;}
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_thought_chunk',content:{type:'text',text:'SECRET THOUGHT'}}}});
    send({method:'session/update',params:{sessionId:'session-one',update:{sessionUpdate:'agent_message_chunk',content:{type:'text',text:`Built turn ${turn}.`}}}});
    send({id:msg.id,result:{stopReason:'end_turn'}});
  } else if(msg.method==='session/cancel') {cancelled=true;send({id:promptId,result:{stopReason:'cancelled'}});}
  else if(msg.id==='approval') {send({id:promptId,result:{stopReason:'end_turn'}});}
}
