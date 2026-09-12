#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "$0")" && pwd)"
tool_cache="${MCB_TOOL_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/minecraft-builder-mcp}"
if [[ ! -x "$tool_cache/apache-maven-3.9.11/bin/mvn" || ! -x "$tool_cache/jdk-25.0.2/bin/java" ]]; then
  MCB_TOOL_CACHE="$tool_cache" python3 "$project_root/scripts/bootstrap-tools.py"
fi
export JAVA_HOME="${MCB_JAVA_HOME:-$tool_cache/jdk-25.0.2}"
exec "$tool_cache/apache-maven-3.9.11/bin/mvn" "$@"
