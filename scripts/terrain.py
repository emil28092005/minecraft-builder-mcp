#!/usr/bin/env python3
"""Offline heightmap previews and bounded, resumable terrain batches. Uses the normal checked RPC editor."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mcb_launcher', ROOT / 'scripts/bridge.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class RpcError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(f'{code}: {message}')
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RpcError('redirect_rejected', 'Backend redirects are not permitted')


class Backend:
    def __init__(self, config, console=False):
        text = config.read_text()
        self.token = launcher.scalar(text, 'agent-token')
        self.scope = {'player_id': 'console' if console else launcher.scalar(text, 'owner-uuid'),
                      'project_id': launcher.scalar(text, 'project-id')}
        port = int(launcher.scalar(text, 'http-port'))
        if not 1 <= port <= 65535 or not self.token or not self.scope['player_id']:
            raise ValueError('Invalid backend configuration or unbound owner')
        self.url = f'http://127.0.0.1:{port}/v1/rpc'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, method, **params):
        body = json.dumps({'method': method, 'params': {**params, **self.scope}, 'requestId': str(uuid.uuid4())}).encode()
        for _ in range(100):
            request = urllib.request.Request(self.url, data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
            try:
                with self.opener.open(request, timeout=30) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as error:
                data = json.load(error)
            if data.get('ok'):
                return data['result']
            failure = data.get('error', {})
            if failure.get('code') == 'busy':
                time.sleep(.1)
                continue
            raise RpcError(failure.get('code', 'invalid_response'), failure.get('message', 'Backend rejected request').replace(self.token, '[REDACTED]'))
        raise RpcError('busy', 'Backend did not become ready')


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def finish(backend, operation):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = backend.call('operation_status', operation_id=operation)
        if result['status'] in ('applied', 'conflict', 'failed', 'cancelled', 'recovery_required'):
            return result
        time.sleep(.15)
    raise RuntimeError(f'Operation still running: {operation}; resume with the same manifest')


def apply_plan(backend, entry, manifest, path):
    # Persist plan and stable key BEFORE transmission. Unknown outcomes reuse this exact request.
    entry.setdefault('idempotency_key', 'terrain-' + str(uuid.uuid4()))
    save(path, manifest)
    if 'operation_id' not in entry:
        result = backend.call('build_apply', plan_id=entry['plan_id'], plan_hash=entry['plan_hash'], idempotency_key=entry['idempotency_key'])
        entry['operation_id'] = result['operation_id']
        save(path, manifest)
    result = finish(backend, entry['operation_id'])
    entry['status'] = result['status']
    entry['written'] = result['written']
    save(path, manifest)
    if result['status'] != 'applied':
        raise RuntimeError(f"Stopped on {result['status']}: {entry['operation_id']}. Inspect conflicts; no new plan or blind retry was created.")


def run_batch(args):
    backend = Backend(args.config, args.console)
    context = backend.call('project_context')
    scope = {key: context[key] for key in ('project_id', 'world_id', 'world_epoch')}
    path = args.manifest.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads(path.read_text()) if path.exists() else None
        if manifest and manifest['scope'] != scope:
            raise RuntimeError('Manifest belongs to another project/world/epoch')
        if args.command == 'undo':
            if manifest is None:
                raise RuntimeError('Manifest not found')
            # Resolve an apply whose response was lost BEFORE assuming there is nothing to undo.
            for entry in reversed(manifest['tiles']):
                if 'idempotency_key' in entry and 'operation_id' not in entry:
                    raise RuntimeError('Uncertain apply response. Resume the original apply with this manifest to resolve its stable key before undo; undo will not start an unconfirmed write.')
                if 'operation_id' not in entry:
                    continue
                result = finish(backend, entry['operation_id'])
                if result['status'] == 'recovery_required':
                    raise RuntimeError('Interrupted server operation requires recovery review first')
                if not result['written']:
                    continue
                if 'undo' not in entry:
                    entry['undo'] = backend.call('operation_undo_prepare', operation_id=entry['operation_id'])
                    save(path, manifest)
                apply_plan(backend, entry['undo'], manifest, path)
            manifest['undone'] = True; save(path, manifest)
            print(json.dumps({'status': 'undone', 'manifest': str(path)}))
            return
        recipe = json.loads(args.recipe.read_text())
        preview = backend.call('terrain_preview', recipe=recipe, resolution=64)
        terrain_id = preview['terrain_id']
        if manifest:
            if manifest['terrain_id'] != terrain_id or manifest['start'] != args.start or manifest['count'] != args.count or manifest['tile_budget'] != preview['tile_budget']:
                raise RuntimeError('Recipe or tile range differs from saved batch')
            if manifest.get('undone') or any('undo' in entry for entry in manifest['tiles']):
                raise RuntimeError('Batch has begun undo; finish undo and use a NEW manifest for new work')
        else:
            if args.start < 0 or not 1 <= args.count <= 64 or args.start + args.count > preview['tile_count']:
                raise RuntimeError('Choose 1..64 existing tiles per batch')
            manifest = {'version': 1, 'scope': scope, 'terrain_id': terrain_id, 'recipe': recipe,
                        'start': args.start, 'count': args.count, 'tile_budget': preview['tile_budget'], 'tiles': []}
            save(path, manifest)
        # The entire requested envelope must fit; never silently clip to an unrelated current project.
        for axis in ('x', 'y', 'z'):
            if recipe['min'][axis] < context['region']['min'][axis] or recipe['max'][axis] > context['region']['max'][axis]:
                raise RuntimeError('Recipe exceeds selected project area; choose a dedicated terrain site first')
        for index in range(args.start, args.start + args.count):
            entry = next((e for e in manifest['tiles'] if e['tile_index'] == index), None)
            if entry is None:
                entry = backend.call('terrain_prepare', terrain_id=terrain_id, tile_index=index)
                manifest['tiles'].append(entry)
                save(path, manifest)
            if entry.get('status') == 'empty' or entry.get('changed_blocks') == 0:
                continue
            if entry.get('status') in ('conflict', 'cancelled', 'failed', 'recovery_required'):
                raise RuntimeError('Batch stopped previously; inspect or undo it instead of forcing through')
            apply_plan(backend, entry, manifest, path)
            print(json.dumps({'tile': index, 'status': entry['status'], 'written': entry['written']}), flush=True)
        print(json.dumps({'status': 'completed', 'manifest': str(path), 'tiles': len(manifest['tiles'])}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    preview = sub.add_parser('preview', help='Render the exact height field OFFLINE; no server or world mutation')
    preview.add_argument('recipe', type=Path)
    preview.add_argument('--output', type=Path, required=True)
    for name in ('apply', 'undo'):
        p = sub.add_parser(name)
        p.add_argument('--manifest', type=Path, required=True)
        p.add_argument('--config', type=Path, default=ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml')
        p.add_argument('--console', action='store_true', help='Only for an explicitly configured isolated fixture')
        p.add_argument('--execute', action='store_true', required=True, help='Explicitly perform this world edit')
        if name == 'apply':
            p.add_argument('recipe', type=Path)
            p.add_argument('--start', type=int, required=True)
            p.add_argument('--count', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'preview':
        java = Path(os.environ.get('MCB_JAVA_HOME', str(Path.home() / '.cache/minecraft-builder-mcp/jdk-25.0.2'))) / 'bin/java'
        jar = ROOT / 'paper-plugin/target/paper-plugin-0.1.0-SNAPSHOT.jar'
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(java), '-Djava.awt.headless=true', '-cp', str(jar), 'io.github.minecraftbuilder.paper.TerrainPreview', str(args.recipe.resolve()), str(args.output.resolve()), str(args.output.with_suffix('.json').resolve())], check=True)
        print(args.output)
    else:
        run_batch(args)


if __name__ == '__main__':
    main()
