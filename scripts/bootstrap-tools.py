#!/usr/bin/env python3
"""Install checksum-pinned local tools without changing system Java (Linux x64)."""
import hashlib
import os
from pathlib import Path
import platform
import tarfile
import urllib.request

ROOT = Path(os.environ.get('MCB_TOOL_CACHE', str(Path.home()/'.cache/minecraft-builder-mcp')))
TOOLS = [
    ('jdk25.tar.gz', 'https://download.java.net/java/GA/jdk25.0.2/b1e0dfa218384cb9959bdcb897162d4e/10/GPL/openjdk-25.0.2_linux-x64_bin.tar.gz', 'sha256', '555ce0821e4fe175ea50d54518cd6fbece9663c1998de529bc6ce429534457df', 'jdk-25.0.2'),
    ('maven.tar.gz', 'https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.11/apache-maven-3.9.11-bin.tar.gz', 'sha512', 'bcfe4fe305c962ace56ac7b5fc7a08b87d5abd8b7e89027ab251069faebee516b0ded8961445d6d91ec1985dfe30f8153268843c89aa392733d1a3ec956c9978', 'apache-maven-3.9.11'),
]
if __name__ == '__main__':
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('Automatic JDK bootstrap supports Linux x64; set JAVA_HOME and use Maven 3.9.11 on your platform.')
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, url, algorithm, checksum, directory in TOOLS:
        archive = ROOT/name
        if not archive.exists():
            temporary = archive.with_suffix('.download')
            urllib.request.urlretrieve(url, temporary)
            temporary.replace(archive)
        if hashlib.new(algorithm, archive.read_bytes()).hexdigest() != checksum:
            raise SystemExit(f'Checksum mismatch: {archive}; remove the corrupt archive and retry.')
        if not (ROOT/directory).exists():
            with tarfile.open(archive) as tf:
                tf.extractall(ROOT, filter='data')
        print(ROOT/directory)
