#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$project_root"
tool_cache="${MCB_TOOL_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/minecraft-builder-mcp}"
./mvnw package
npm --prefix bridge ci --ignore-scripts
npm --prefix bridge test
export JAVA_HOME="${MCB_JAVA_HOME:-$tool_cache/jdk-25.0.2}"
camera-mod/gradlew --project-dir camera-mod build
