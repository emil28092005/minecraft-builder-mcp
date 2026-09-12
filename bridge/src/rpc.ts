#!/usr/bin/env node
import { backendFromEnv } from './backend.js';
try {
  const [method, raw = '{}'] = process.argv.slice(2);
  if (!method || !/^[a-z_]+$/.test(method)) throw new Error('Usage: node dist/rpc.js method \'{"params":"values"}\'');
  const params: unknown = JSON.parse(raw);
  if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error('RPC params must be a JSON object.');
  console.log(JSON.stringify(await backendFromEnv().call(method, params as Record<string, unknown>), null, 2));
} catch (error) { console.error(error instanceof Error ? error.message : 'RPC failed.'); process.exitCode = 1; }
