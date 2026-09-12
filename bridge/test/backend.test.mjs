import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { BackendClient, backendFromEnv } from '../dist/backend.js';

async function fixture(t, handler) {
  const server = createServer(handler); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  return `http://127.0.0.1:${server.address().port}`;
}
test('transport injects trusted actor, authenticates and uses stable envelope', async t => {
  let request;
  const url = await fixture(t, async (req,res) => {
    assert.equal(req.headers.authorization,'Bearer private-token');
    let body = ''; for await (const chunk of req) body += chunk;
    request = JSON.parse(body); res.end(JSON.stringify({ok:true,result:{project:'p'}}));
  });
  const backend = new BackendClient({ url, token:'private-token', scope:{player_id:'owner',project_id:'p'} });
  assert.deepEqual(await backend.call('project_context',{player_id:'forged',project_id:'elsewhere'}),{project:'p'});
  assert.equal(request.params.player_id,'owner'); assert.equal(request.params.project_id,'p'); assert.ok(request.requestId);
});
test('backend error details redact the token', async t => {
  const url = await fixture(t, (_req,res) => {res.statusCode=400;res.end(JSON.stringify({ok:false,error:{code:'conflict',message:'private-token is hidden',details:{token:'private-token'}}}));});
  const backend = new BackendClient({url,token:'private-token'});
  await assert.rejects(backend.call('build_apply'),error => error.code==='conflict' && !error.message.includes('private-token') && error.details.token==='[REDACTED]');
});
test('response is bounded even with streaming and no content-length', async t => {
  const url = await fixture(t, (_req,res) => { res.write('x'.repeat(300)); res.end('x'.repeat(300)); });
  await assert.rejects(new BackendClient({url,token:'token',maxResponseBytes:100}).call('project_context'),error=>error.code==='response_too_large');
});
test('write timeout is not automatically retried', async t => {
  let calls=0; const url = await fixture(t, () => { calls++; });
  await assert.rejects(new BackendClient({url,token:'token',timeoutMs:30}).call('build_apply'),error=>error.code==='timeout');
  assert.equal(calls,1);
});
test('token cannot follow a redirect, invalid JSON cannot masquerade as result', async t => {
  const url = await fixture(t, (_req,res) => {res.writeHead(302,{location:'http://127.0.0.1:1'});res.end();});
  await assert.rejects(new BackendClient({url,token:'token'}).call('project_context'),error=>error.code==='unavailable');
});
test('remote endpoints and missing or conflated auth are rejected', () => {
  assert.throws(()=>new BackendClient({url:'http://example.com',token:'token'}),/loopback/);
  assert.throws(()=>backendFromEnv({MCB_TOKEN:'admin'}),/MCB_AGENT_TOKEN/);
  assert.throws(()=>backendFromEnv({MCB_AGENT_TOKEN:'agent'}),/MCB_PLAYER_ID/);
});
