#!/usr/bin/env python3
"""Prepare/run a private disposable Paper fixture. Never accepts Minecraft EULA implicitly."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
CACHE=Path(os.environ.get('MCB_TOOL_CACHE', str(Path.home()/'.cache/minecraft-builder-mcp')))
URL='https://fill-data.papermc.io/v1/objects/7b7b3b43c009103e1971a0576c26f655a7dd9b56a0a2a4438e352c03a7fecd08/paper-26.2-123.jar'
SHA='7b7b3b43c009103e1971a0576c26f655a7dd9b56a0a2a4438e352c03a7fecd08'

def prepare():
    server=ROOT/'.runtime/server'
    server.mkdir(parents=True, exist_ok=True)
    jar=server/'paper.jar'
    if not jar.exists():
        tmp=jar.with_suffix('.download')
        request=urllib.request.Request(URL,headers={'User-Agent':'minecraft-builder-mcp/0.1 (local-development)'})
        with urllib.request.urlopen(request,timeout=60) as source, tmp.open('wb') as out:
            shutil.copyfileobj(source,out)
        tmp.replace(jar)
    if hashlib.sha256(jar.read_bytes()).hexdigest()!=SHA:
        raise SystemExit('Paper SHA256 mismatch; remove .runtime/server/paper.jar and retry')
    plugin=ROOT/'paper-plugin/target/paper-plugin-0.1.0-SNAPSHOT.jar'
    if not plugin.exists(): raise SystemExit('Build the plugin first: ./mvnw package')
    (server/'plugins').mkdir(exist_ok=True)
    shutil.copy2(plugin,server/'plugins/minecraft-builder-mcp.jar')
    properties=server/'server.properties'
    if not properties.exists():
        properties.write_text('server-ip=127.0.0.1\nserver-port=25575\nonline-mode=true\nlevel-name=world\nlevel-type=minecraft:flat\ngenerator-settings={"layers":[{"block":"minecraft:bedrock","height":1},{"block":"minecraft:dirt","height":2},{"block":"minecraft:grass_block","height":1}],"biome":"minecraft:plains"}\ngenerate-structures=false\nspawn-protection=0\nview-distance=5\nsimulation-distance=3\nmax-players=4\ngamemode=creative\ndifficulty=peaceful\nenable-rcon=false\nmotd=minecraft-builder-mcp private development world\n')
    if not (server/'eula.txt').exists(): (server/'eula.txt').write_text('eula=false\n')
    print(f'Prepared {server}; Paper SHA256 verified. No existing worlds modified.', flush=True)
    return server

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',action='store_true')
    ap.add_argument('--heap',default='2G',help='Maximum Java heap, e.g. 4G for the large lobby')
    ap.add_argument('--accept-eula',action='store_true',help='Explicitly accept https://www.minecraft.net/eula before starting this private test server')
    args=ap.parse_args()
    if not re.fullmatch(r'[1-9][0-9]*[MG]', args.heap):
        ap.error('--heap must be a positive integer followed by M or G')
    server=prepare()
    if args.accept_eula: (server/'eula.txt').write_text('# Accepted explicitly by the operator for this development server.\neula=true\n')
    if args.run:
        if 'eula=true' not in (server/'eula.txt').read_text():
            raise SystemExit('Minecraft EULA acceptance required: https://www.minecraft.net/eula ; review then rerun with --accept-eula if you agree.')
        java=Path(os.environ.get('MCB_JAVA_HOME',str(CACHE/'jdk-25.0.2')))/'bin/java'
        if not java.exists(): raise SystemExit('Run python3 scripts/bootstrap-tools.py first')
        raise SystemExit(subprocess.call([str(java),'-Dterminal.jline=false','-Dterminal.ansi=false','-Xms512M','-Xmx'+args.heap,'-jar','paper.jar','--nogui'],cwd=server))
