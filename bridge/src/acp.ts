import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile, rename } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { Readable, Writable } from 'node:stream';
import { fileURLToPath } from 'node:url';
import { client, ndJsonStream, PROTOCOL_VERSION, type ClientConnection, type McpServer, type SessionNotification } from '@agentclientprotocol/sdk';

import { agentEnvironment, codexPaths, prepareCodexHome } from './security.js';
import { BackendError } from './backend.js';
import { AGENT_INSTRUCTIONS as INSTRUCTIONS } from './building-guidance.js';
const INSTRUCTIONS_HASH = createHash('sha256').update(INSTRUCTIONS).digest('hex');
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
interface SavedSession { sessionId: string; summary: string; interrupted: boolean; instructionsHash?: string }


const MCP_STARTUP_MESSAGE = 'Minecraft MCP не запустился: инструменты строительства недоступны. Запрос остановлен; проверь настройки и процесс моста.';
const MINECRAFT_TOOLS = new Set(['project_context', 'material_search', 'material_describe', 'region_inspect', 'build_prepare', 'build_apply', 'operation_status', 'operation_cancel', 'operation_undo_prepare', 'part_get', 'part_define', 'camera_list', 'camera_capture', 'asset_list', 'schematic_export', 'schematic_import_prepare', 'terrain_preview', 'terrain_prepare', 'terrain_brush_prepare']);

export class CodexSession implements AgentSession {
  private child?: ChildProcessWithoutNullStreams;
  private connection?: ClientConnection;
  private sessionId?: string;
  private currentReply?: Reply;
  private active = false;
  private cancelled = false;
  private buffer = '';
  private finalText = '';
  private sentChars = 0;
  private delivery: Promise<void> = Promise.resolve();
  private firstPrompt = true;
  private instructionsHash = '';
  private summary = '';
  private reportReset = false;
  private reportInterrupted = false;
  private readonly mcpStartupFailures = new Set<string>();
  private readonly minecraftCalls = new Set<string>();
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
    this.instructionsHash = saved?.instructionsHash ?? '';
    this.reportInterrupted = saved?.interrupted ?? false;
    const executable = this.options.command ?? process.execPath;
    const args = this.options.args ?? (this.options.command ? [] : [require.resolve('@agentclientprotocol/codex-acp')]);
    this.mcpStartupFailures.clear();
    const child = spawn(executable, args, { cwd: this.dir, stdio: ['pipe','pipe','pipe'], env: agentEnvironment(this.options.env ?? process.env, paths), shell: false, detached: process.platform !== 'win32' });
    this.child = child;
    // Adapter stderr may contain prompts or secrets. Drain it without logging raw content.
    child.stderr.resume();
    const app = client({ name: 'minecraft-builder-mcp-chat' });
    app.onRequest('session/request_permission', async ({ params }) => {
      // Only correlate a one-use approval to a known Minecraft call advertised
      // by this adapter in this active owner turn. Paper enforces the scope.
      if (this.child === child && this.active && !this.cancelled && !this.mcpStartupError() && params.sessionId === this.sessionId
        && params._meta?.is_mcp_tool_approval === true
        && this.minecraftCalls.has(params.toolCall.toolCallId)
        && params.options.some(option => option.kind === 'allow_once' && option.optionId === 'allow_once')) {
        this.minecraftCalls.delete(params.toolCall.toolCallId);
        return { outcome: { outcome: 'selected', optionId: 'allow_once' } };
      }
      await this.currentReply?.('Codex запросил дополнительное разрешение. Оно отклонено: подтверждение через игровой чат пока не реализовано.', false, true);
      return { outcome: { outcome: 'cancelled' } };
    });
    app.onNotification('session/update', ({ params }) => {
      if (this.child === child) return this.onUpdate(params);
    });
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
      const mcpError = this.mcpStartupError();
      if (mcpError) throw mcpError;
      if (this.options.model) {
        const config = configOptions?.find(option => option.category === 'model' || option.id === 'model');
        if (!config) throw new Error('Agent did not advertise a model selector; unset MCB_MODEL or use a compatible adapter.');
        await connection.agent.request('session/set_config_option', { sessionId: this.sessionId, configId: config.id, value: this.options.model });
      }
      await this.save(false);
      const lateMcpError = this.mcpStartupError();
      if (lateMcpError) throw lateMcpError;
    } catch (error) { this.close(); throw error; }
    finally { clearTimeout(setupTimeout); }
  }
  private mcpStartupError(): BackendError | undefined {
    return this.sessionId && this.mcpStartupFailures.has(this.sessionId)
      ? new BackendError('mcp_unavailable', MCP_STARTUP_MESSAGE) : undefined;
  }
  private async onUpdate(params: SessionNotification): Promise<void> {
    const update = params.update;
    // codex-acp 1.11.0 synthesizes this reserved startup event separately from
    // thread history. It can arrive before session/new or session/load returns.
    // Never expose its raw content: startup errors may contain tokens or paths.
    if (update.sessionUpdate === 'tool_call' && update.toolCallId === 'mcp_startup.minecraft-builder-mcp'
      && update.title === 'mcp__minecraft-builder-mcp__startup' && update.kind === 'other' && update.status === 'failed') {
      this.mcpStartupFailures.add(params.sessionId);
      const error = this.mcpStartupError();
      if (error && this.active) this.connection?.close(error);
      return;
    }
    // History replay from session/load is suppressed; another player's chat never receives it.
    if (!this.active || params.sessionId !== this.sessionId || !this.currentReply || this.mcpStartupError()) return;
    if (update.sessionUpdate === 'tool_call') {
      const input = update.rawInput as Record<string, unknown> | undefined;
      if (update._meta?.is_mcp_tool_call === true && update.kind === 'execute'
        && (update.status === 'pending' || update.status === 'in_progress')
        && input?.server === 'minecraft-builder-mcp' && typeof input.tool === 'string'
        && MINECRAFT_TOOLS.has(input.tool) && update.title === `mcp.minecraft-builder-mcp.${input.tool}`
        && this.minecraftCalls.size < 128) this.minecraftCalls.add(update.toolCallId);
    } else if (update.sessionUpdate === 'tool_call_update'
      && (update.status === 'completed' || update.status === 'failed')) this.minecraftCalls.delete(update.toolCallId);
    if (update.sessionUpdate === 'agent_message_chunk' && update.content.type === 'text') {
      this.finalText = (this.finalText + update.content.text).slice(0, 8000);
      const remaining = Math.max(0, 8000 - this.sentChars - this.buffer.length);
      this.buffer += update.content.text.slice(0, safeTextEnd(update.content.text, remaining));
      await this.flush(false);
    }
    // Deliberately do not forward thought chunks, tool arguments, or raw terminal output.
  }
  private async flush(done: boolean): Promise<void> {
    const reply = this.currentReply;
    if (!reply) return;
    const { messages, remainder } = chatMessages(this.buffer, done);
    // Reserve text synchronously: ACP notifications can arrive while a reply is
    // awaiting HTTP delivery. They must not flush or account for the same text.
    this.buffer = remainder;
    for (const message of messages) {
      const clean = message.slice(0, safeTextEnd(message, Math.max(0, 8000 - this.sentChars)));
      if (!clean) continue;
      this.sentChars += clean.length;
      this.delivery = this.delivery.then(() => reply(clean, false));
    }
    if (done) {
      const status = this.cancelled ? 'Остановлено. Уже изменённые блоки остаются в истории.' : this.sentChars ? '' : 'Ход Codex завершён без текстового ответа; состояние мира доступно через /ai status.';
      this.delivery = this.delivery.then(() => reply(status, true));
    }
    await this.delivery;
  }
  async prompt(text: string, reply: Reply): Promise<void> {
    if (this.active) throw new Error('This ACP session already has an active turn.');
    this.currentReply = reply; this.cancelled = false;
    try {
      await this.start();
      const mcpError = this.mcpStartupError();
      if (mcpError) throw mcpError;
    } catch (error) {
      if (error instanceof BackendError && error.code === 'mcp_unavailable') await reply(MCP_STARTUP_MESSAGE, false, true);
      this.currentReply = undefined;
      throw error;
    }
    if (this.cancelled) { await reply('Запрос остановлен до отправки Codex.', true); this.currentReply = undefined; return; }
    if (this.reportReset) { await reply('Начат новый диалог Codex с сохранённой краткой сводкой проекта.', false); this.reportReset = false; }
    if (this.reportInterrupted) { await reply('Предыдущий ход был прерван перезапуском. Проверю состояние операций перед новым строительством.', false); this.reportInterrupted = false; }
    this.active = true; this.buffer = ''; this.finalText = ''; this.sentChars = 0; this.delivery = Promise.resolve(); this.minecraftCalls.clear();
    const prefix = (this.firstPrompt || this.instructionsHash !== INSTRUCTIONS_HASH) ? `${INSTRUCTIONS}\n${this.summary ? `Previous compact summary (historical, verify world): ${this.summary}\n` : ''}\nPlayer request:\n` : '';
    await this.save(true);
    const timeout = setTimeout(() => { void this.cancel().catch(() => this.close()); }, this.options.timeoutMs ?? 15 * 60_000);
    try {
      const startupError = this.mcpStartupError();
      if (startupError) throw startupError;
      const result = await this.connection!.agent.request('session/prompt', { sessionId: this.sessionId!, prompt: [{ type: 'text', text: `${prefix}${text}` }] });
      const mcpError = this.mcpStartupError();
      if (mcpError) throw mcpError;
      this.firstPrompt = false;
      this.instructionsHash = INSTRUCTIONS_HASH;
      this.cancelled ||= result.stopReason === 'cancelled';
      this.summary = `Last player request: ${text.slice(0,2000)}\nLast agent response: ${this.finalText.slice(0,3000)}`;
      await this.save(false);
      const lateMcpError = this.mcpStartupError();
      if (lateMcpError) throw lateMcpError;
      await this.flush(true);
    } catch (error) {
      const mcpError = this.mcpStartupError();
      if (mcpError) {
        await this.delivery;
        await reply(MCP_STARTUP_MESSAGE, false, true);
        throw mcpError;
      }
      throw error;
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
    await writeFile(temp, JSON.stringify({ sessionId: this.sessionId, summary: this.summary, interrupted, instructionsHash: this.instructionsHash }), { mode: 0o600 });
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

/** Keep unfinished words until more tokens arrive; never emit a token on a timer. */
function chatMessages(buffer: string, done: boolean): { messages: string[]; remainder: string } {
  let text = buffer.replace(/[\u0000-\u0009\u000b-\u001f\u007f§]/g, ' ').trimStart();
  const messages: string[] = [];
  while (text) {
    const limit = safeTextEnd(text, 240);
    // A following separator confirms the sentence boundary. A punctuation token
    // alone may still be followed by closing quotes or another punctuation mark.
    const sentence = /[.!?…]["'»”\])]*(?=\s)|\n/u.exec(text);
    let end = sentence ? sentence.index + sentence[0].length : 0;
    if (!end || end > limit) {
      if (text.length <= limit) {
        if (!done) break;
        end = text.length;
      } else {
        end = 0;
        for (let i = limit; i > 0; i--) {
          if (/\s/u.test(text[i]!)) { end = i; break; }
        }
        if (!end) end = limit; // A single overlong word still needs a bounded message.
      }
    }
    const message = text.slice(0, end).replace(/\s+/gu, ' ').trim();
    text = text.slice(end).trimStart();
    if (message) messages.push(message);
  }
  return { messages, remainder: text };
}

function safeTextEnd(text: string, max: number): number {
  let end = Math.min(text.length, max);
  const last = text.charCodeAt(end - 1);
  if (end < text.length && last >= 0xd800 && last <= 0xdbff) end--;
  return end;
}

function terminateAgentTree(child: ChildProcessWithoutNullStreams, signal: NodeJS.Signals): void {
  try {
    // The adapter launches Codex and MCP children. On Unix all are in our own process group.
    if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal);
    else if (child.exitCode === null) child.kill(signal);
  } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') child.kill(signal); }
}
