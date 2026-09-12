#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { agentEnvironment, codexPaths, prepareCodexHome } from './security.js';
try {
  const args = process.argv.slice(2);
  if (args.length > 1 || (args[0] !== undefined && args[0] !== 'status')) throw new Error('Usage: npm run login [-- status]');
  const paths = codexPaths(resolve(process.env.MCB_STATE_DIR ?? '.state/chat'), process.env.MCB_CODEX_HOME);
  await prepareCodexHome(paths);
  const require = createRequire(import.meta.url);
  const child = spawn(process.execPath, [require.resolve('@openai/codex/bin/codex.js'), 'login', ...(args[0] === 'status' ? ['status'] : ['--device-auth'])], { stdio: 'inherit', env: agentEnvironment(process.env, paths), shell: false });
  child.once('error', () => { console.error('Unable to launch the pinned Codex login command.'); process.exitCode = 1; });
  child.once('exit', code => { process.exitCode = code ?? 1; });
} catch (error) { console.error(error instanceof Error ? error.message : 'Codex login helper failed.'); process.exitCode = 1; }
