import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile, rename } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { Readable, Writable } from 'node:stream';
import { fileURLToPath } from 'node:url';
import { client, ndJsonStream, PROTOCOL_VERSION, type ClientConnection, type McpServer, type SessionNotification } from '@agentclientprotocol/sdk';

import { agentEnvironment, codexPaths, prepareCodexHome } from './security.js';
export { agentEnvironment } from './security.js';

const require = createRequire(import.meta.url);
export interface ChatMessage { id: string; playerId: string; projectId: string; text: string; type?: 'prompt' | 'cancel' | 'reset'; playerPosition?: { x: number; y: number; z: number; yaw?: number; pitch?: number }; worldId?: string; lookTarget?: { x: number; y: number; z: number } }
export type Reply = (text: string, done: boolean, error?: boolean) => Promise<void>;
export interface AgentSession { prompt(text: string, reply: Reply): Promise<void>; cancel(): Promise<void>; close(): void }
export interface AcpOptions {
  backendUrl: string; agentToken: string; stateDir: string; codexHome?: string;
  command?: string; args?: string[]; model?: string; authMethod?: string;
  timeoutMs?: number; startupTimeoutMs?: number;
  env?: NodeJS.ProcessEnv;
}
interface SavedSession { sessionId: string; summary: string; interrupted: boolean }

const INSTRUCTIONS = `You are the Minecraft builder for the current authorized project. Respond in the player's language using short game-chat messages. Use only minecraft-builder-mcp to inspect and edit the world. Begin each new task with project_context; read relevant world data before designing. Only implemented server capabilities may be used. Prepare compact geometry, inspect statistics, apply using stable idempotency keys, and poll operation_status. Preserve manual edits: conflict requires localized redesign or the user's decision, never blindly overwrite fresh snapshots. A cancelled or failed operation may have partial writes. Camera requests are asynchronous; poll capture_id and inspect actual image. If unavailable, explicitly say visually unverified. Never use console commands, shell, files, or other MCP servers to modify Minecraft. Do not claim any action completed without server evidence.`;

export class CodexSession implements AgentSession {
  private child?: ChildProcessWithoutNullStreams;
  private connection?: ClientConnection;
  private sessionId?: string;
  private currentReply?: Reply;
  private active = false;
  private cancelled = false;
  private buffer = '';
  private finalText = '';
  private lastSent = 0;
  private sentChars = 0;
  private firstPrompt = true;
  private summary = '';
  private reportReset = false;
  private reportInterrupted = false;
  private readonly dir: string;
  private readonly stateFile: string;
  constructor(private readonly message: Pick<ChatMessage, 'projectId' | 'playerId'>, private readonly options: AcpOptions) {
    const key = createHash('sha256').update(`${message.projectId}\0${message.playerId}`).digest('hex').slice(0,32);
    this.dir = join(resolve(options.stateDir), key); this.stateFile = join(this.dir, 'session.json');
  }
  private async start(): Promise<void> {
    if (this.connection && !this.connection.signal.aborted) return;
    await mkdir(this.dir, { recursive: true, mode: 0o700 });
    const paths = codexPaths(this.options.stateDir, this.options.codexHome);
    await prepareCodexHome(paths);
    let saved: SavedSession | undefined;
    try {
      const raw = JSON.parse(await readFile(this.stateFile, 'utf8')) as SavedSession;
      if (typeof raw.sessionId === 'string' && typeof raw.summary === 'string') saved = raw;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') this.reportReset = true;
    }
    this.summary = saved?.summary.slice(0, 5000) ?? '';
    this.reportInterrupted = saved?.interrupted ?? false;
    const executable = this.options.command ?? process.execPath;
    const args = this.options.args ?? (this.options.command ? [] : [require.resolve('@agentclientprotocol/codex-acp')]);
    const child = spawn(executable, args, { cwd: this.dir, stdio: ['pipe','pipe','pipe'], env: agentEnvironment(this.options.env ?? process.env, paths), shell: false, detached: process.platform !== 'win32' });
    this.child = child;
    // Adapter stderr may contain prompts or secrets. Drain it without logging raw content.
    child.stderr.resume();
    const app = client({ name: 'minecraft-builder-mcp-chat' });
    app.onRequest('session/request_permission', async () => {
      await this.currentReply?.('Codex запросил дополнительное разрешение. Оно отклонено: подтверждение через игровой чат пока не реализовано.', false, true);
      return { outcome: { outcome: 'cancelled' } };
    });
    app.onNotification('session/update', ({ params }) => this.onUpdate(params));
    this.connection = app.connect(ndJsonStream(Writable.toWeb(child.stdin), Readable.toWeb(child.stdout) as unknown as ReadableStream<Uint8Array>));
    const connection = this.connection;
    child.once('error', () => connection.close(new Error('Cannot start the ACP process. Check MCB_ACP_COMMAND.')));
    child.once('exit', () => connection.close(new Error('ACP process exited. Check Codex authentication and installation.')));
    const setupTimeout = setTimeout(() => connection.close(new Error('ACP startup timed out.')), this.options.startupTimeoutMs ?? 30_000);
    try {
      const init = await connection.agent.request('initialize', { protocolVersion: PROTOCOL_VERSION, clientInfo: { name:'minecraft-builder-mcp',version:'0.1.0' }, clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false } });
      if (init.protocolVersion !== PROTOCOL_VERSION) throw new Error('ACP protocol version is incompatible.');
      if (this.options.authMethod) {
        if (!init.authMethods?.some(method => method.id === this.options.authMethod)) throw new Error('MCB_ACP_AUTH_METHOD was not advertised by the agent.');
        await connection.agent.request('authenticate', { methodId: this.options.authMethod });
      }
      const mcpServers: McpServer[] = [{ name: 'minecraft-builder-mcp', command: process.execPath,
        args: [fileURLToPath(new URL('./mcp.js', import.meta.url))], env: [
          { name: 'MCB_BACKEND_URL', value: this.options.backendUrl },
          { name: 'MCB_AGENT_TOKEN', value: this.options.agentToken },
          { name: 'MCB_PLAYER_ID', value: this.message.playerId },
          { name: 'MCB_PROJECT_ID', value: this.message.projectId },
        ] }];
      let configOptions;
      if (saved && init.agentCapabilities?.loadSession) {
        try {
          const loaded = await connection.agent.request('session/load', { sessionId: saved.sessionId, cwd: this.dir, mcpServers });
          this.sessionId = saved.sessionId; configOptions = loaded.configOptions; this.firstPrompt = false;
        } catch { this.reportReset = true; }
      }
      if (!this.sessionId) {
        const created = await connection.agent.request('session/new', { cwd: this.dir, mcpServers });
        this.sessionId = created.sessionId; configOptions = created.configOptions; this.firstPrompt = true;
        if (saved) this.reportReset = true;
      }
      if (this.options.model) {
        const config = configOptions?.find(option => option.category === 'model' || option.id === 'model');
        if (!config) throw new Error('Agent did not advertise a model selector; unset MCB_MODEL or use a compatible adapter.');
        await connection.agent.request('session/set_config_option', { sessionId: this.sessionId, configId: config.id, value: this.options.model });
      }
      await this.save(false);
    } catch (error) { this.close(); throw error; }
    finally { clearTimeout(setupTimeout); }
  }
  private async onUpdate(params: SessionNotification): Promise<void> {
    // History replay from session/load is suppressed; another player's chat never receives it.
    if (!this.active || params.sessionId !== this.sessionId || !this.currentReply) return;
    const update = params.update;
    if (update.sessionUpdate === 'agent_message_chunk' && update.content.type === 'text') {
      this.finalText = (this.finalText + update.content.text).slice(0, 8000);
      this.buffer += update.content.text;
      if (this.buffer.length >= 180 || Date.now() - this.lastSent >= 1500) await this.flush(false);
    }
    // Deliberately do not forward thought chunks, tool arguments, or raw terminal output.
  }
  private async flush(done: boolean): Promise<void> {
    const remaining = Math.max(0, 8000 - this.sentChars);
    const clean = this.buffer.replace(/[\u0000-\u001f\u007f§]/g, ' ').trim().slice(0, remaining);
    this.buffer = '';
    if (clean) {
      for (let offset = 0; offset < clean.length; offset += 240) await this.currentReply?.(clean.slice(offset, offset + 240), false);
      this.sentChars += clean.length;
    }
    this.lastSent = Date.now();
    if (done) await this.currentReply?.(this.cancelled ? 'Остановлено. Уже изменённые блоки остаются в истории.' : this.sentChars ? '' : 'Ход Codex завершён без текстового ответа; состояние мира доступно через /ai status.', true);
  }
  async prompt(text: string, reply: Reply): Promise<void> {
    if (this.active) throw new Error('This ACP session already has an active turn.');
    this.currentReply = reply; this.cancelled = false;
    await this.start();
    if (this.cancelled) { await reply('Запрос остановлен до отправки Codex.', true); this.currentReply = undefined; return; }
    if (this.reportReset) { await reply('Начат новый диалог Codex с сохранённой краткой сводкой проекта.', false); this.reportReset = false; }
    if (this.reportInterrupted) { await reply('Предыдущий ход был прерван перезапуском. Проверю состояние операций перед новым строительством.', false); this.reportInterrupted = false; }
    this.active = true; this.buffer = ''; this.finalText = ''; this.sentChars = 0;
    const prefix = this.firstPrompt ? `${INSTRUCTIONS}\n${this.summary ? `Previous compact summary (historical, verify world): ${this.summary}\n` : ''}\nPlayer request:\n` : '';
    await this.save(true);
    const timeout = setTimeout(() => { void this.cancel().catch(() => this.close()); }, this.options.timeoutMs ?? 15 * 60_000);
    try {
      const result = await this.connection!.agent.request('session/prompt', { sessionId: this.sessionId!, prompt: [{ type: 'text', text: `${prefix}${text}` }] });
      this.firstPrompt = false;
      this.cancelled ||= result.stopReason === 'cancelled';
      this.summary = `Last player request: ${text.slice(0,2000)}\nLast agent response: ${this.finalText.slice(0,3000)}`;
      await this.save(false);
      await this.flush(true);
    } finally { clearTimeout(timeout); this.active = false; this.currentReply = undefined; }
  }
  async cancel(): Promise<void> {
    this.cancelled = true;
    if (this.sessionId && this.connection && !this.connection.signal.aborted) {
      await this.connection.agent.notify('session/cancel', { sessionId: this.sessionId });
      // A stuck adapter must not keep a project queue blocked forever.
      const target = this.connection;
      setTimeout(() => { if (this.active && this.connection === target) this.close(); }, 5000).unref();
    }
  }
  private async save(interrupted: boolean): Promise<void> {
    const temp = `${this.stateFile}.tmp`;
    await writeFile(temp, JSON.stringify({ sessionId: this.sessionId, summary: this.summary, interrupted }), { mode: 0o600 });
    await rename(temp, this.stateFile);
  }
  close(): void {
    this.connection?.close(); this.connection = undefined;
    const child = this.child;
    if (child) {
      terminateAgentTree(child, 'SIGTERM');
      setTimeout(() => terminateAgentTree(child, 'SIGKILL'), 3000).unref();
    }
    this.child = undefined; this.sessionId = undefined;
  }
}

function terminateAgentTree(child: ChildProcessWithoutNullStreams, signal: NodeJS.Signals): void {
  try {
    // The adapter launches Codex and MCP children. On Unix all are in our own process group.
    if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal);
    else if (child.exitCode === null) child.kill(signal);
  } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') child.kill(signal); }
}
