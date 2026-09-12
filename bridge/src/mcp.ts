#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { backendFromEnv } from './backend.js';
import { createMcpServer } from './tools.js';
try {
  const server = createMcpServer(backendFromEnv());
  await server.connect(new StdioServerTransport());
  const shutdown = () => { void server.close().finally(() => process.exit(0)); };
  process.once('SIGINT', shutdown); process.once('SIGTERM', shutdown);
} catch (error) { console.error(error instanceof Error ? error.message : 'MCP startup failed.'); process.exitCode = 1; }
