#!/usr/bin/env python3
"""Build the opt-in isolated Paper regression probe; never install or run it."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".runtime" / "material-registry-probe"
PLUGIN = """name: MaterialRegistryProbe
version: '1.0'
main: probe.MaterialRegistryProbe
api-version: '26.2'
depend: [MinecraftBuilderMCP]
commands:
  registryprobe:
    description: Run isolated all-registry block snapshot verification
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-home", type=Path, default=ROOT / ".runtime" / "server",
                        help="Prepared Paper installation whose libraries supply the compile classpath")
    parser.add_argument("--java-home", type=Path,
                        default=Path(os.environ.get("MCB_JAVA_HOME", str(Path.home() / ".cache" / "minecraft-builder-mcp" / "jdk-25.0.2"))),
                        help="JDK 25 or newer; defaults to the project's downloaded JDK")
    args = parser.parse_args()
    libraries = sorted((args.paper_home / "libraries").rglob("*.jar"))
    if not libraries:
        parser.error("No Paper dependency jars found; prepare the local development server first")
    javac, jar = args.java_home / "bin" / "javac", args.java_home / "bin" / "jar"
    if not javac.is_file() or not jar.is_file():
        parser.error("JDK javac/jar unavailable; supply --java-home or MCB_JAVA_HOME")
    classes = OUTPUT / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    subprocess.run([str(javac), "--release", "25", "-cp", os.pathsep.join(str(p.resolve()) for p in libraries),
                    "-d", str(classes), str(Path(__file__).with_name("MaterialRegistryProbe.java"))], check=True)
    (classes / "plugin.yml").write_text(PLUGIN, encoding="utf-8")
    output = OUTPUT / "material-registry-probe.jar"
    subprocess.run([str(jar), "--create", "--file", str(output), "-C", str(classes), "."], check=True)
    print(output)


if __name__ == "__main__":
    main()
