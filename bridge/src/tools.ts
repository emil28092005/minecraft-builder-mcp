import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { BackendError, type RpcBackend } from './backend.js';

const id = z.string().min(1).max(200);
const position = z.object({ x: z.number().int().min(-30_000_000).max(30_000_000), y: z.number().int().min(-4096).max(4096), z: z.number().int().min(-30_000_000).max(30_000_000) }).strict();
const block = z.string().regex(/^minecraft:[a-z0-9_]+(?:\[[a-z0-9_=,]+\])?$/).max(200);
// Deliberate small declarative language: the Paper compiler enforces all resource limits again.
const shape = z.discriminatedUnion('type', [
  z.object({ type: z.literal('box'), min: position, max: position, block, hollow: z.boolean().optional() }).strict(),
  z.object({ type: z.literal('line'), from: position, to: position, block }).strict(),
  z.object({ type: z.literal('cylinder'), center: position, radius: z.number().int().min(0).max(128), height: z.number().int().min(1).max(256), block, hollow: z.boolean().optional() }).strict(),
]);
const operation = z.union([shape, z.object({ type: z.literal('repeat'), count: z.number().int().min(1).max(128), offset: position, operations: z.array(shape).min(1).max(256) }).strict()]);
const recipe = z.object({ version: z.literal(1), operations: z.array(operation).min(1).max(256) }).strict();
const pose = z.object({ x: z.number().finite(), y: z.number().finite(), z: z.number().finite(), yaw: z.number().min(-360).max(360), pitch: z.number().min(-90).max(90), fov: z.number().int().min(30).max(110).optional(), width: z.number().int().min(320).max(1920).optional(), height: z.number().int().min(180).max(1080).optional() }).strict();

export function toolResult(result: unknown): CallToolResult {
  let metadata = result;
  const content: CallToolResult['content'] = [];
  if (result && typeof result === 'object' && 'imageBase64' in result) {
    const { imageBase64, mimeType, ...rest } = result as Record<string, unknown>;
    if (rest.status !== 'completed' || typeof imageBase64 !== 'string' || imageBase64.length > 12_000_000 || !['image/png', 'image/jpeg'].includes(String(mimeType)) || !/^[A-Za-z0-9+/]*={0,2}$/.test(imageBase64)) {
      throw new BackendError('invalid_image', 'Camera returned an invalid or oversized capture.');
    }
    metadata = rest;
    content.push({ type: 'image', data: imageBase64, mimeType: String(mimeType) });
  }
  const text = JSON.stringify(metadata ?? null);
  if (Buffer.byteLength(text) > 65_536) throw new BackendError('context_limit', 'Result is too large for model context. Request a smaller region or summary.');
  content.unshift({ type: 'text', text });
  return { content };
}

export function createMcpServer(backend: RpcBackend): McpServer {
  const server = new McpServer({ name: 'minecraft-builder-mcp', version: '0.1.0' }, { instructions:
    'Build only through these tools in the server-authorized project. Start with project_context and region_inspect. Prepare a compact recipe, inspect its summary, then apply with the returned plan ID/hash and a stable unique idempotency key. Conflicts preserve manual edits: never re-read and blindly overwrite them. Query operation_status until terminal; cancellation can leave partial edits. Camera unavailable means visually unverified. Never claim success from preparation alone.' });
  function register(name: string, description: string, inputSchema: z.ZodRawShape, readOnly: boolean, idempotent = false) {
    server.registerTool(name, { description, inputSchema, annotations: { readOnlyHint: readOnly, destructiveHint: !readOnly, idempotentHint: idempotent, openWorldHint: false } }, async (args) => {
      try { return toolResult(await backend.call(name, args as Record<string, unknown>)); }
      catch (error) {
        const failure = error instanceof BackendError ? { code: error.code, message: error.message, details: error.details } : { code: 'bridge_error', message: 'The bridge could not complete this request.' };
        const text = JSON.stringify(failure);
        return { isError: true, content: [{ type: 'text', text: Buffer.byteLength(text) <= 32_768 ? text : JSON.stringify({ code: failure.code, message: failure.message, details: 'Details exceed the context budget; inspect a smaller area.' }) }] };
      }
    });
  }
  register('project_context', 'Get authorized world, project, area, capabilities, supported blocks, and operation summaries. No full-world dump.', {}, true, true);
  register('region_inspect', 'Inspect a bounded inclusive region. Prefer summary; blocks detail is only for a small local area. Both min and max are required; inspect a small section of the project area.', { min: position, max: position, detail: z.enum(['summary', 'blocks']).default('summary') }, true, true);
  register('build_prepare', 'Prepare immutable geometry without changing the world. Use supported recipe operations from project_context. Returns plan_id, plan_hash and compact statistics.', { recipe, part_id: id.optional(), dependencies: z.array(position).max(512).optional() }, false);
  register('build_apply', 'Apply a prepared plan with compare-before-write protection. Reuse the SAME idempotency_key after uncertain transport outcome; query project_context to recover an unknown operation ID, then operation_status first.', { plan_id: id, plan_hash: id, idempotency_key: id }, false, true);
  register('operation_status', 'Get exact state, changed count, conflicts and completion. A terminal cancelled/conflict state can include partial writes.', { operation_id: id }, true, true);
  register('operation_cancel', 'Request cancellation before the next server batch. Already applied changes remain journaled.', { operation_id: id }, false, true);
  register('operation_undo_prepare', 'Prepare checked undo of a recorded operation. Manual edits after construction become conflicts. Apply returned undo plan with build_apply.', { operation_id: id }, false);
  register('part_get', 'Get named part metadata and protected status, without expanding every block.', { part_id: id }, true, true);
  register('part_define', 'Register an exact part mask from a completed operation. Server rejects unsupported membership or overlap.', { name: z.string().min(1).max(64), operation_id: id }, false);
  register('camera_list', 'List saved camera poses and whether a camera client is connected.', {}, true, true);
  register('camera_capture', 'Request a real capture by saved camera_id or pose. A pending response returns captureId; poll using capture_id. Only completed results contain an image. Camera unavailable is not a successful visual check.', { camera_id: id.optional(), pose: pose.optional(), after_operation_id: id.optional(), capture_id: id.optional() }, true);
  register('asset_list', 'List up to 64 local schematic assets with dimensions and metadata, optionally filtered by query. No network library or generated thumbnails. Place .schem files manually in the plugin data/schematics directory; asset IDs never accept arbitrary paths.', { query: z.string().max(64).optional() }, true, true);
  register('schematic_export', 'Export a dense inclusive region of at most 4096 supported blocks as a local Sponge v2 .schem asset. Optional origin is the clipboard anchor. Returns an asset ID and metadata; files remain in the plugin data/schematics directory.', { name: z.string().min(1).max(64).regex(/^[^\u0000-\u001f\u007f]+$/), min: position, max: position, origin: position.optional() }, false);
  register('schematic_import_prepare', 'Prepare a checked import of a local .schem asset at target, optionally rotating 0/90/180/270 degrees. Rejects entities, block entities and unsupported blocks. Returns a normal plan; inspect it and use build_apply to edit the world.', { asset_id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/), target: position, rotation: z.union([z.literal(0),z.literal(90),z.literal(180),z.literal(270)]).default(0) }, false);
  return server;
}
