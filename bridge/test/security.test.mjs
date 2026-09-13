import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,readdir,rm,stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {codexPaths,prepareCodexHome,CODEX_CONFIG,CODEX_CONFIG_TOML,securityReport} from '../dist/security.js';
const oldManagedConfig=CODEX_CONFIG_TOML.replace('code_mode_host = true\n','code_mode_host = false\n');
test('dedicated home gets known config and never overwrites existing user configuration',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mcb-security-'));t.after(()=>rm(root,{recursive:true,force:true}));
 const paths=codexPaths(root);await prepareCodexHome(paths);
 assert.equal(await readFile(join(paths.codexHome,'config.toml'),'utf8'),CODEX_CONFIG_TOML);
 await prepareCodexHome(paths);
 await writeFile(join(paths.codexHome,'config.toml'),'sandbox_mode = "danger-full-access"\n');
 await assert.rejects(prepareCodexHome(paths),/will not be overwritten/);
 assert.equal(await readFile(join(paths.codexHome,'config.toml'),'utf8'),'sandbox_mode = "danger-full-access"\n');
});
test('migrates only the known old managed config atomically, backs it up and preserves authentication',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mcb-security-'));t.after(()=>rm(root,{recursive:true,force:true}));
 const paths=codexPaths(root);await prepareCodexHome(paths);
 const configPath=join(paths.codexHome,'config.toml');
 const authPath=join(paths.codexHome,'auth.json');
 const syntheticAuth='{"test_fixture":"preserve-me-byte-for-byte"}\n';
 await writeFile(configPath,oldManagedConfig);await writeFile(authPath,syntheticAuth,{mode:0o600});
 await prepareCodexHome(paths);
 assert.equal(await readFile(configPath,'utf8'),CODEX_CONFIG_TOML);
 assert.equal(await readFile(`${configPath}.before-code-mode-host`,'utf8'),oldManagedConfig);
 assert.equal(await readFile(authPath,'utf8'),syntheticAuth);
 if(process.platform!=='win32'){
  assert.equal((await stat(configPath)).mode&0o777,0o600);
  assert.equal((await stat(`${configPath}.before-code-mode-host`)).mode&0o777,0o600);
 }
 await prepareCodexHome(paths);
 assert.equal(await readFile(configPath,'utf8'),CODEX_CONFIG_TOML);
 assert.equal(await readFile(`${configPath}.before-code-mode-host`,'utf8'),oldManagedConfig);
 assert.equal(await readFile(authPath,'utf8'),syntheticAuth);
 assert.equal((await readdir(paths.codexHome)).filter(name=>name.endsWith('.tmp')).length,0);
});
test('refuses even small custom changes to old managed configuration without creating a backup',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mcb-security-'));t.after(()=>rm(root,{recursive:true,force:true}));
 const paths=codexPaths(root);await prepareCodexHome(paths);
 const configPath=join(paths.codexHome,'config.toml');
 for(const custom of [oldManagedConfig+'# my settings\n',oldManagedConfig.replace('shell_tool = false','shell_tool = true')]){
  await writeFile(configPath,custom);
  await assert.rejects(prepareCodexHome(paths),/will not be overwritten/);
  assert.equal(await readFile(configPath,'utf8'),custom);
  await assert.rejects(readFile(`${configPath}.before-code-mode-host`),{code:'ENOENT'});
 }
});
test('resumes with an exact previous backup but refuses to overwrite a different backup',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mcb-security-'));t.after(()=>rm(root,{recursive:true,force:true}));
 const paths=codexPaths(root);await prepareCodexHome(paths);
 const configPath=join(paths.codexHome,'config.toml');const backupPath=`${configPath}.before-code-mode-host`;
 await writeFile(configPath,oldManagedConfig);await writeFile(backupPath,'different backup\n');
 await assert.rejects(prepareCodexHome(paths),/backup.*will not be overwritten/);
 assert.equal(await readFile(configPath,'utf8'),oldManagedConfig);
 assert.equal(await readFile(backupPath,'utf8'),'different backup\n');
 await writeFile(backupPath,oldManagedConfig);await prepareCodexHome(paths);
 assert.equal(await readFile(configPath,'utf8'),CODEX_CONFIG_TOML);
 assert.equal(await readFile(backupPath,'utf8'),oldManagedConfig);
});
test('code-mode host is enabled without enabling the separately restricted integrations',()=>{
 assert.equal(CODEX_CONFIG.features.code_mode_host,true);
 for(const [feature,enabled] of Object.entries(CODEX_CONFIG.features)){
  if(feature!=='code_mode_host')assert.equal(enabled,false,feature);
 }
 assert.equal(CODEX_CONFIG.sandbox_mode,'read-only');assert.equal(CODEX_CONFIG.web_search,'disabled');
});
test('doctor security report describes upstream workspace-write limitation honestly',()=>{
 const report=securityReport(codexPaths('/state'));
 assert.equal(report.configuredSandbox,'read-only');assert.equal(report.adapterTurnSandbox,'workspace-write');assert.equal(report.runtimeVerified,false);
 assert.equal(report.pinnedCliFeatureProbe.unified_exec,true);
 assert.equal(report.codeModeHostRequested,true);assert.equal(report.codeModeHostRequiredForModelToolMode,'code_mode_only');
 assert.ok(report.limitations.some(text=>text.includes('Doctor does not invoke a model')));
 assert.ok(report.limitations.some(text=>text.includes('temporary paths')));
});
