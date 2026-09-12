#!/usr/bin/env python3
"""Prism Java wrapper: inject the camera secret without putting it in launcher arguments/logs."""
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    if len(sys.argv) < 2:
        raise SystemExit('This helper is a Prism WrapperCommand; it requires the Java command.')
    config = Path(os.environ.get('MCB_CAMERA_PAPER_CONFIG', str(ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml')))
    try:
        data = config.read_text()
        token_match = re.search(r'^camera-token:[ \t]*([^\r\n]+)$', data, re.M)
        port_match = re.search(r'^camera-port:[ \t]*(\d+)[ \t]*$', data, re.M)
        token = token_match.group(1).strip().strip("'\"") if token_match else ''
        port = int(port_match.group(1)) if port_match else 8766
        if not re.fullmatch(r'[A-Za-z0-9._~-]{32,512}', token) or not 1024 <= port <= 65535:
            raise ValueError('Invalid camera configuration')
    except (OSError, ValueError):
        raise SystemExit('Cannot read a valid camera token/port from the private Paper config.')
    environment = dict(os.environ, MCB_CAMERA_TOKEN=token, MCB_CAMERA_PORT=str(port))
    os.execvpe(sys.argv[1], sys.argv[1:], environment)

if __name__ == '__main__':
    main()
