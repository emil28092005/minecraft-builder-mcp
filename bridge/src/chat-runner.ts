import { randomUUID } from 'node:crypto';
import { setTimeout as pause } from 'node:timers/promises';
import { type AgentSession, type ChatMessage, type Reply } from './acp.js';
import { BackendError, type RpcBackend } from './backend.js';

export interface ChatRunnerOptions { maxQueue?: number; maxSessions?: number; onError?: (code: string) => void }
export class ChatRunner {
  private readonly queues = new Map<string, ChatMessage[]>();
  private readonly running = new Set<string>();
  private readonly sessions = new Map<string, AgentSession>();
  private readonly active = new Map<string, { message: ChatMessage; session: AgentSession }>();
  private readonly seen = new Set<string>();
  private stopping = false;
  private readonly clientId = randomUUID();
  private readonly delivery = new Map<string, Promise<void>>();
  private readonly replyTime = new Map<string, number>();
  constructor(private readonly backend: RpcBackend, private readonly factory: (message: ChatMessage) => AgentSession, private readonly options: ChatRunnerOptions = {}) {}
  async poll(): Promise<void> {
    const response = await this.backend.call('chat_poll', { client_id: this.clientId });
    if (!response || typeof response !== 'object' || !('messages' in response) || !Array.isArray(response.messages)) throw new Error('Invalid chat_poll response.');
    for (const raw of response.messages) {
      if (!isChatMessage(raw)) { this.options.onError?.('invalid_chat_message'); continue; }
      if (this.seen.has(raw.id)) continue;
      this.seen.add(raw.id);
      if (this.seen.size > 10_000) this.seen.delete(this.seen.values().next().value!);
      if (raw.type === 'cancel') { await this.cancel(raw); continue; }
      if (raw.type === 'reset') {
        await this.reply(raw)('Сброс диалога пока не поддерживается. После перезапуска мост попытается возобновить сессию.', true, true); continue;
      }
      const queue = this.queues.get(raw.projectId) ?? [];
      if (queue.length >= (this.options.maxQueue ?? 8)) { await this.reply(raw)('Очередь проекта заполнена. Повтори запрос после завершения текущего.', true, true); continue; }
      queue.push(raw); this.queues.set(raw.projectId, queue);
      if (!this.running.has(raw.projectId)) void this.drain(raw.projectId);
    }
  }
  private reply(message: ChatMessage): Reply {
    return async (text, done, error) => {
      const channel = `${message.projectId}\0${message.playerId}`;
      const next = (this.delivery.get(channel) ?? Promise.resolve()).catch(() => {}).then(async () => {
        const delay = (this.replyTime.get(channel) ?? 0) + 250 - Date.now();
        if (text && delay > 0) await pause(delay);
        await this.backend.call('chat_reply', { id: message.id, playerId: message.playerId, text, done, ...(error ? { error: true } : {}) });
        this.replyTime.set(channel, Date.now());
      });
      this.delivery.set(channel, next);
      try { await next; } finally { if (this.delivery.get(channel) === next) this.delivery.delete(channel); }
    };
  }
  private async drain(projectId: string): Promise<void> {
    this.running.add(projectId);
    try {
      for (;;) {
        if (this.stopping) break;
        const message = this.queues.get(projectId)?.shift(); if (!message) break;
        const key = `${projectId}\0${message.playerId}`;
        let session = this.sessions.get(key);
        try {
          if (!session) {
            if (this.sessions.size >= (this.options.maxSessions ?? 8)) throw new Error('Session capacity reached.');
            session = this.factory(message); this.sessions.set(key, session);
          }
          this.active.set(projectId, { message, session });
          await this.reply(message)('Codex обрабатывает запрос. Остановка: /ai stop.', false);
          await session.prompt(promptWithContext(message), this.reply(message));
        } catch (error) {
          session?.close(); this.sessions.delete(key);
          const code = error instanceof BackendError ? error.code : 'acp_error';
          this.options.onError?.(code);
          await this.reply(message)(`Запрос не завершён (${code}). Проверь вход Codex и настройки ACP; изменения мира проверь через /ai status.`, true, true).catch(() => this.options.onError?.('chat_reply_failed'));
        } finally { this.active.delete(projectId); }
      }
    } finally { this.running.delete(projectId); if (!(this.queues.get(projectId)?.length)) this.queues.delete(projectId); }
  }
  private async cancel(message: ChatMessage): Promise<void> {
    const current = this.active.get(message.projectId);
    if (current && current.message.playerId === message.playerId) await current.session.cancel().catch(() => current.session.close());
    const queue = this.queues.get(message.projectId) ?? [];
    const cancelled = queue.filter(item => item.playerId === message.playerId);
    this.queues.set(message.projectId, queue.filter(item => item.playerId !== message.playerId));
    for (const item of cancelled) await this.reply(item)('Запрос удалён из очереди.', true);
    // Paper's /ai stop independently cancels any world operation. ACP cancellation alone is insufficient.
    await this.reply(message)('Остановка Codex запрошена; остановку записи выполняет сервер.', true);
  }
  close(): void {
    this.stopping = true;
    for (const session of this.sessions.values()) session.close();
  }
}
function isChatMessage(value: unknown): value is ChatMessage {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return ['id','playerId','projectId'].every(key => typeof item[key] === 'string' && (item[key] as string).length > 0 && (item[key] as string).length <= 200)
    && typeof item.text === 'string' && item.text.length <= 8000 && (item.type === undefined || ['prompt','cancel','reset'].includes(String(item.type)));
}

export function promptWithContext(message: ChatMessage): string {
  const context: Record<string, unknown> = {};
  function position(raw: unknown): Record<string, number> | undefined {
    if (!raw || typeof raw !== 'object') return undefined;
    const source = raw as Record<string, unknown>;
    if (!['x','y','z'].every(key => typeof source[key] === 'number' && Number.isFinite(source[key]))) return undefined;
    const result: Record<string, number> = {};
    for (const key of ['x','y','z','yaw','pitch']) if (typeof source[key] === 'number' && Number.isFinite(source[key])) result[key] = source[key];
    return result;
  }
  if (position(message.playerPosition)) context.playerPosition = position(message.playerPosition);
  if (position(message.lookTarget)) context.lookTarget = position(message.lookTarget);
  if (typeof message.worldId === 'string' && message.worldId.length <= 128) context.worldId = message.worldId;
  return Object.keys(context).length ? `Server-observed player context at request time (verify current project with project_context): ${JSON.stringify(context)}\nPlayer request:\n${message.text}` : message.text;
}
