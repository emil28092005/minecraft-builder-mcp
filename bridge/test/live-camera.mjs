// Opt-in real MCP image check. The configured online spectator is teleported.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

for (const key of ['MCB_AGENT_TOKEN', 'MCB_PLAYER_ID', 'MCB_PROJECT_ID', 'MCB_CAPTURE_POSE']) {
  assert.ok(process.env[key], `${key} is required`);
}
const pose = JSON.parse(process.env.MCB_CAPTURE_POSE);
const transport = new StdioClientTransport({ command: process.execPath, args: [resolve('dist/mcp.js')],
  env: Object.fromEntries(Object.entries(process.env).filter(([key, value]) => value !== undefined && key !== 'MCB_TOKEN')), stderr: 'pipe' });
const client = new Client({ name: 'minecraft-builder-live-camera', version: '0.1.0' });
const startedAt = Date.now();
async function capture(args) {
  const reply = await client.callTool({ name: 'camera_capture', arguments: args });
  assert.notEqual(reply.isError, true, 'Camera MCP returned an error');
  const metadata = JSON.parse(reply.content.find(item => item.type === 'text').text);
  assert.equal('imageBase64' in metadata, false, 'Image must be a separate MCP content block');
  return { reply, metadata };
}
try {
  await client.connect(transport);
  const args = { pose };
  if (process.env.MCB_AFTER_OPERATION_ID) args.after_operation_id = process.env.MCB_AFTER_OPERATION_ID;
  let current = await capture(args);
  const id = current.metadata.captureId;
  for (let attempt = 0; current.metadata.status === 'pending' && attempt < 150; attempt++) {
    await pause(200);
    current = await capture({ capture_id: id });
  }
  const { reply, metadata } = current;
  assert.equal(metadata.status, 'completed', 'A real completed capture is required');
  assert.equal(metadata.captureId, id);
  assert.ok(Date.parse(metadata.capturedAt) >= startedAt - 1000, 'Frame must be newly captured');
  const images = reply.content.filter(item => item.type === 'image');
  assert.equal(images.length, 1);
  assert.equal(images[0].mimeType, 'image/png');
  const png = Buffer.from(images[0].data, 'base64');
  assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  assert.equal(png.readUInt32BE(16), metadata.width);
  assert.equal(png.readUInt32BE(20), metadata.height);
  const directory = resolve(process.env.MCB_CAMERA_OUTPUT_DIR ?? '../.runtime/camera-test');
  await mkdir(directory, { recursive: true });
  const stem = `mcp-${id}`;
  const report = { ...metadata, transport: 'MCP stdio ImageContent', imageBytes: png.length,
    imageSha256: createHash('sha256').update(png).digest('hex') };
  await writeFile(resolve(directory, `${stem}.png`), png, { mode: 0o600, flag: 'wx' });
  await writeFile(resolve(directory, `${stem}.json`), JSON.stringify(report, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
  console.log(JSON.stringify({ status: 'passed', transport: report.transport, width: metadata.width,
    height: metadata.height, imageBytes: png.length, imagePath: resolve(directory, `${stem}.png`) }));
} finally {
  await client.close();
}
