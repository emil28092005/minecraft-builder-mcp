import { randomUUID } from 'node:crypto';

export class BackendError extends Error {
  constructor(public readonly code: string, message: string, public readonly details?: unknown) {
    super(message); this.name = 'BackendError';
  }
}
export interface Scope { player_id: string; project_id: string }
export interface BackendOptions {
  url: string; token: string; scope?: Scope; timeoutMs?: number; maxResponseBytes?: number; maxRequestBytes?: number;
}
export interface RpcBackend { call(method: string, params?: Record<string, unknown>): Promise<unknown> }

export function validateBackendUrl(raw: string): URL {
  const url = new URL(raw);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.protocol !== 'http:') {
    throw new Error('MCB_BACKEND_URL must use HTTP on loopback. Use an SSH tunnel for remote Paper.');
  }
  if (url.username || url.password || url.search || url.hash || !['/', ''].includes(url.pathname)) {
    throw new Error('MCB_BACKEND_URL must contain only a loopback origin.');
  }
  return url;
}

export class BackendClient implements RpcBackend {
  readonly url: URL;
  constructor(private readonly options: BackendOptions) {
    this.url = validateBackendUrl(options.url);
    if (!options.token || /[\r\n]/.test(options.token)) throw new Error('Backend token is required.');
  }
  async call(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    // Scope always comes from the launcher, never from model-controlled arguments.
    const body = JSON.stringify({ method, params: { ...params, ...this.options.scope }, requestId: randomUUID() });
    if (Buffer.byteLength(body) > (this.options.maxRequestBytes ?? 1_048_576)) {
      throw new BackendError('request_too_large', 'Request exceeds the bridge byte limit.');
    }
    return this.request('/v1/rpc', { method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${this.options.token}` }, body }, true, method === 'camera_capture' ? 12_582_912 : undefined, method === 'camera_capture' ? 60_000 : undefined);
  }
  async health(): Promise<unknown> { return this.request('/health', { method: 'GET' }, false); }
  private async request(path: string, init: RequestInit, envelope = true, responseLimit?: number, requestTimeout?: number): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs ?? requestTimeout ?? 15_000);
    try {
      const response = await fetch(new URL(path, this.url), { ...init, signal: controller.signal, redirect: 'error' });
      const limit = this.options.maxResponseBytes ?? responseLimit ?? 2_097_152;
      if (Number(response.headers.get('content-length')) > limit) {
        await response.body?.cancel();
        throw new BackendError('response_too_large', 'Backend response exceeds the bridge byte limit.');
      }
      const reader = response.body?.getReader();
      if (!reader) throw new BackendError('invalid_response', 'Backend returned an empty response.');
      let bytes = 0; const chunks: Uint8Array[] = [];
      for (;;) {
        const { value, done } = await reader.read(); if (done) break;
        bytes += value.byteLength;
        if (bytes > limit) { await reader.cancel(); throw new BackendError('response_too_large', 'Backend response exceeds the bridge byte limit.'); }
        chunks.push(value);
      }
      let data: unknown;
      try { data = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch { throw new BackendError('invalid_response', 'Backend did not return valid JSON.'); }
      if (!envelope) {
        if (!response.ok) throw new BackendError(`http_${response.status}`, `Backend HTTP ${response.status}.`);
        return data;
      }
      if (!data || typeof data !== 'object' || !('ok' in data)) throw new BackendError('invalid_response', 'Backend response has no RPC envelope.');
      if (data.ok === true && 'result' in data && response.ok) return data.result;
      if (data.ok === false && 'error' in data && data.error && typeof data.error === 'object') {
        const error = data.error as Record<string, unknown>;
        throw new BackendError(typeof error.code === 'string' ? error.code : 'backend_error',
          this.redact(typeof error.message === 'string' ? error.message : 'Backend rejected the request.'),
          error.details ? JSON.parse(this.redact(JSON.stringify(error.details))) : undefined);
      }
      throw new BackendError('invalid_response', 'Backend returned an invalid RPC envelope.');
    } catch (error) {
      if (error instanceof BackendError) throw error;
      if (controller.signal.aborted) throw new BackendError('timeout', 'Backend request timed out. A write may have started; query operation status before retrying with the same idempotency key.');
      throw new BackendError('unavailable', 'Cannot reach the Paper backend. Check its process and local port.');
    } finally { clearTimeout(timer); }
  }
  private redact(value: string): string { return value.split(this.options.token).join('[REDACTED]'); }
}

export function backendFromEnv(env = process.env, admin = false): BackendClient {
  const token = admin ? env.MCB_TOKEN : env.MCB_AGENT_TOKEN;
  if (!token) throw new Error(`${admin ? 'MCB_TOKEN' : 'MCB_AGENT_TOKEN'} is required; tokens are separate for chat and tools.`);
  if (!admin && (!env.MCB_PLAYER_ID || !env.MCB_PROJECT_ID)) throw new Error('MCB_PLAYER_ID and MCB_PROJECT_ID are required for MCP tools.');
  return new BackendClient({ url: env.MCB_BACKEND_URL ?? 'http://127.0.0.1:8765', token,
    scope: admin ? undefined : { player_id: env.MCB_PLAYER_ID!, project_id: env.MCB_PROJECT_ID! } });
}
