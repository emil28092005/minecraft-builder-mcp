#!/usr/bin/env node
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { backendFromEnv } from './backend.js';
import { codexPaths, prepareCodexHome, securityReport } from './security.js';
const paths = codexPaths(resolve(process.env.MCB_STATE_DIR ?? '.state/chat'), process.env.MCB_CODEX_HOME);
try {
  await prepareCodexHome(paths);
  let backend: unknown;
  try { backend = await backendFromEnv(process.env, true).health(); }
  catch (error) { backend = { status: 'unavailable', message: error instanceof Error ? error.message : 'Health check failed.' }; }
  console.log(JSON.stringify({ bridge: '0.1.0', node: process.version, backend, codex: { ...securityReport(paths), login: { command: process.execPath, args: [fileURLToPath(new URL('./login.js', import.meta.url))], env: { MCB_STATE_DIR: resolve(process.env.MCB_STATE_DIR ?? '.state/chat'), MCB_CODEX_HOME: paths.codexHome }, method: 'device-auth (starts only when the user runs this command)' } } }, null, 2));
} catch (error) { console.error(error instanceof Error ? error.message : 'Doctor failed.'); process.exitCode = 1; }
