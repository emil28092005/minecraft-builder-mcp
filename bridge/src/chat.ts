#!/usr/bin/env node
import { resolve } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { backendFromEnv } from './backend.js';
import { CodexSession, type AcpOptions } from './acp.js';
import { ChatRunner } from './chat-runner.js';

let runner: ChatRunner | undefined;
try {
  if (!process.env.MCB_AGENT_TOKEN) throw new Error('MCB_AGENT_TOKEN is required for the agent MCP connection.');
  let args: string[] | undefined;
  if (process.env.MCB_ACP_ARGS) {
    const parsed: unknown = JSON.parse(process.env.MCB_ACP_ARGS);
    if (!Array.isArray(parsed) || !parsed.every(value => typeof value === 'string')) throw new Error('MCB_ACP_ARGS must be a JSON array of strings.');
    args = parsed;
  }
  const options: AcpOptions = {
    backendUrl: process.env.MCB_BACKEND_URL ?? 'http://127.0.0.1:8765',
    agentToken: process.env.MCB_AGENT_TOKEN,
    stateDir: resolve(process.env.MCB_STATE_DIR ?? '.state/chat'),
    command: process.env.MCB_ACP_COMMAND, args,
    codexHome: process.env.MCB_CODEX_HOME, model: process.env.MCB_MODEL, authMethod: process.env.MCB_ACP_AUTH_METHOD,
  };
  const backend = backendFromEnv(process.env, true);
  runner = new ChatRunner(backend, message => new CodexSession(message, options), { onError: code => console.error(`minecraft-builder-mcp: ${code}`) });
  let stopping = false;
  const stop = () => { stopping = true; runner?.close(); };
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  console.error('minecraft-builder-mcp chat bridge started (local Paper, ACP).');
  let failures = 0;
  while (!stopping) {
    try { await runner.poll(); failures = 0; }
    catch { failures++; if (failures === 1 || failures % 30 === 0) console.error('Paper chat polling failed; check local backend and admin token.'); }
    if (!stopping) await pause(Math.min(10_000, 750 * Math.max(1, failures)));
  }
} catch (error) { console.error(error instanceof Error ? error.message : 'Chat bridge failed.'); process.exitCode = 1; }
finally { runner?.close(); }
