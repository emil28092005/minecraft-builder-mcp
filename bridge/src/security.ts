import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { delimiter, dirname, join, resolve } from 'node:path';

// These are supported by the pinned Codex 0.153.4 runtime and official configuration reference.
export const CODEX_CONFIG = {
  sandbox_mode: 'read-only', approval_policy: 'on-request', approvals_reviewer: 'user',
  cli_auth_credentials_store: 'file', allow_login_shell: false, web_search: 'disabled',
  sandbox_workspace_write: { network_access: false, writable_roots: [], exclude_slash_tmp: true, exclude_tmpdir_env_var: true },
  shell_environment_policy: { inherit: 'none' },
  features: {
    shell_tool: false, unified_exec: false, shell_snapshot: false,
    apps: false, hooks: false, multi_agent: false, plugins: false, remote_plugin: false,
    browser_use: false, browser_use_external: false, browser_use_full_cdp_access: false,
    computer_use: false, image_generation: false, code_mode: false, code_mode_host: false,
    skill_mcp_dependency_install: false,
  },
};
export const CODEX_CONFIG_TOML = `# Managed by minecraft-builder-mcp; use a dedicated CODEX_HOME.\nsandbox_mode = "read-only"\napproval_policy = "on-request"\napprovals_reviewer = "user"\ncli_auth_credentials_store = "file"\nallow_login_shell = false\nweb_search = "disabled"\n\n[sandbox_workspace_write]\nnetwork_access = false\nwritable_roots = []\nexclude_slash_tmp = true\nexclude_tmpdir_env_var = true\n\n[shell_environment_policy]\ninherit = "none"\n\n[features]\n${Object.entries(CODEX_CONFIG.features).map(([key,value]) => `${key} = ${value}`).join('\n')}\n`;

export interface CodexPaths { home: string; codexHome: string }
export function codexPaths(stateDir: string, codexHome?: string): CodexPaths {
  const state = resolve(stateDir);
  return { home: join(state, 'home'), codexHome: resolve(codexHome ?? join(state, 'codex-home')) };
}
export async function prepareCodexHome(paths: CodexPaths): Promise<void> {
  for (const directory of [paths.home, paths.codexHome, join(paths.home,'.config'), join(paths.home,'.cache'), join(paths.home,'tmp')]) await mkdir(directory,{recursive:true,mode:0o700});
  const configPath = join(paths.codexHome, 'config.toml');
  let existing: string | undefined;
  try { existing = await readFile(configPath, 'utf8'); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
  if (existing !== undefined && existing !== CODEX_CONFIG_TOML) {
    throw new Error('MCB_CODEX_HOME contains a different config.toml. Choose a dedicated empty Codex home or the bridge-managed home; existing settings will not be overwritten.');
  }
  if (existing === undefined) {
    try { await writeFile(configPath, CODEX_CONFIG_TOML, { flag: 'wx', mode: 0o600 }); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST' || await readFile(configPath,'utf8') !== CODEX_CONFIG_TOML) throw error;
    }
  }
}

/** Explicit allowlist; arbitrary user cloud credentials, global Codex settings and bridge tokens stay outside the child. */
export function agentEnvironment(source: NodeJS.ProcessEnv, paths: CodexPaths): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = {};
  for (const key of ['LANG','LC_ALL','LC_CTYPE','TZ','SystemRoot','WINDIR','PATHEXT']) if (source[key] !== undefined) result[key] = source[key];
  result.PATH = [dirname(process.execPath), ...(source.PATH ? [source.PATH] : process.platform === 'win32' ? [] : ['/usr/bin','/bin'])].join(delimiter);
  result.HOME = paths.home; result.USERPROFILE = paths.home;
  result.XDG_CONFIG_HOME = join(paths.home,'.config'); result.XDG_CACHE_HOME = join(paths.home,'.cache');
  result.APPDATA = join(paths.home,'.config'); result.LOCALAPPDATA = join(paths.home,'.cache');
  result.TMPDIR = join(paths.home,'tmp'); result.TEMP = result.TMPDIR; result.TMP = result.TMPDIR;
  result.CODEX_HOME = paths.codexHome;
  result.CODEX_CONFIG = JSON.stringify(CODEX_CONFIG);
  result.INITIAL_AGENT_MODE = 'read-only'; result.NO_BROWSER = '1';
  if (source.MCB_OPENAI_API_KEY) result.OPENAI_API_KEY = source.MCB_OPENAI_API_KEY;
  if (source.MCB_CODEX_API_KEY) result.CODEX_API_KEY = source.MCB_CODEX_API_KEY;
  return result;
}
export function securityReport(paths: CodexPaths) {
  return {
    codexHome: paths.codexHome, osHome: paths.home, globalUserConfigurationInherited: false,
    authentication: 'Dedicated login or explicitly supplied MCB_OPENAI_API_KEY/MCB_CODEX_API_KEY; never copied automatically',
    configuredSandbox: 'read-only', adapterMode: 'read-only', adapterVersion: '1.11.0',
    adapterTurnSandbox: 'workspace-write', approvalPolicy: 'on-request', approvalsReviewer: 'user',
    sandboxedCommandNetwork: false, shellToolRequested: false, unifiedExecRequested: false,
    pinnedCliFeatureProbe: { codexVersion: '0.153.4', platform: 'linux', shell_tool: false, unified_exec: true },
    inheritedMcpServers: false, acpFilesystem: false, acpTerminal: false,
    runtimeVerified: false,
    limitations: [
      'Pinned Codex reports unified_exec enabled even when disabled explicitly; shell_tool is disabled. A real model tool-availability check has not run.',
      'codex-acp 1.11.0 overrides turn sandbox to workspace-write even in its read-only mode; the session directory and temporary paths may remain writable.',
      'Sandboxed-command network restrictions do not sandbox the bridge, ACP adapter or MCP server processes; these remain trusted local programs.',
      'No real model turn or end-to-end sandbox probe has run; configuration and initialization alone do not prove OS-level isolation.',
      'Administrator-managed Codex settings and repository-local configuration can also apply; use the dedicated project/state directory and inspect doctor output.',
    ],
  };
}
