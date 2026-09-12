#!/usr/bin/env python3
"""Run the Bridge against the private local development server without displaying secrets."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def scalar(text, key):
    """Read only the top-level scalar fields emitted by the Paper configuration writer."""
    match = re.search(r'^' + re.escape(key) + r':[ \t]*(.*?)[ \t]*$', text, re.M)
    if not match:
        return ''
    raw = match.group(1).strip()
    if raw.startswith("'"):
        quoted = re.fullmatch(r"'((?:[^']|'')*)'[ \t]*(?:#.*)?", raw)
        if quoted:
            return quoted.group(1).replace("''", "'")
    elif raw.startswith('"'):
        quoted = re.fullmatch(r'("(?:[^"\\]|\\.)*")[ \t]*(?:#.*)?', raw)
        if quoted:
            try:
                return json.loads(quoted.group(1))
            except json.JSONDecodeError:
                pass
    else:
        return re.split(r'[ \t]+#', raw, maxsplit=1)[0].strip()
    raise SystemExit(f'Invalid scalar for {key}; use the Paper-generated configuration format.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['doctor', 'chat', 'mcp', 'login', 'status'])
    parser.add_argument('action', nargs='?', choices=['status'], help='Only for login: check authentication without starting a login flow')
    parser.add_argument('--status', action='store_true', help='With login: check authentication without starting login')
    parser.add_argument('--config', type=Path, default=ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml')
    parser.add_argument('--console', action='store_true', help='Use console scope only with allow-local-automation in the disposable fixture')
    args = parser.parse_args()
    if (args.action or args.status) and args.mode != 'login':
        parser.error('The status action is accepted only after login; alternatively use mode status.')

    # Login/authentication status needs no Paper config or Paper token. Always use the same
    # default state directory as the chat daemon, including when called from another cwd.
    env = dict(os.environ)
    env.setdefault('MCB_STATE_DIR', str(ROOT / '.runtime/bridge-state'))
    needs_backend = args.mode in ('chat', 'mcp')
    if needs_backend and not args.config.is_file():
        raise SystemExit('Start the Paper plugin once to generate its private config.')
    if args.mode in ('doctor', 'chat', 'mcp') and args.config.is_file():
        text = args.config.read_text()
        actor = 'console' if args.console else scalar(text, 'owner-uuid')
        if args.mode == 'mcp' and not actor:
            raise SystemExit('Bind the owner in game with /ai setup first.')
        port = scalar(text, 'http-port')
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise SystemExit('Paper http-port must be an integer in 1..65535.')
        env.update(MCB_BACKEND_URL='http://127.0.0.1:' + port,
                   MCB_TOKEN=scalar(text, 'admin-token'), MCB_AGENT_TOKEN=scalar(text, 'agent-token'),
                   MCB_PLAYER_ID=actor, MCB_PROJECT_ID=scalar(text, 'project-id'))

    target = 'dist/' + ('login' if args.mode in ('login', 'status') else args.mode) + '.js'
    if not (ROOT / 'bridge' / target).is_file():
        raise SystemExit('Build the Bridge first: cd bridge && npm ci --ignore-scripts && npm run build')
    command = ['node', target]
    if args.mode == 'status' or args.action == 'status' or args.status:
        command.append('status')
    return subprocess.call(command, cwd=ROOT / 'bridge', env=env)


if __name__ == '__main__':
    raise SystemExit(main())
