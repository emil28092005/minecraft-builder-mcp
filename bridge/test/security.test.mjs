import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {codexPaths,prepareCodexHome,CODEX_CONFIG_TOML,securityReport} from '../dist/security.js';
test('dedicated home gets known config and never overwrites existing user configuration',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mcb-security-'));t.after(()=>rm(root,{recursive:true,force:true}));
 const paths=codexPaths(root);await prepareCodexHome(paths);
 assert.equal(await readFile(join(paths.codexHome,'config.toml'),'utf8'),CODEX_CONFIG_TOML);
 await prepareCodexHome(paths);
 await writeFile(join(paths.codexHome,'config.toml'),'sandbox_mode = "danger-full-access"\n');
 await assert.rejects(prepareCodexHome(paths),/will not be overwritten/);
 assert.equal(await readFile(join(paths.codexHome,'config.toml'),'utf8'),'sandbox_mode = "danger-full-access"\n');
});
test('doctor security report describes upstream workspace-write limitation honestly',()=>{
 const report=securityReport(codexPaths('/state'));
 assert.equal(report.configuredSandbox,'read-only');assert.equal(report.adapterTurnSandbox,'workspace-write');assert.equal(report.runtimeVerified,false);
 assert.equal(report.pinnedCliFeatureProbe.unified_exec,true);
 assert.ok(report.limitations.some(text=>text.includes('temporary paths')));
});
