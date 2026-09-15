#!/usr/bin/env bash
# Thin wrapper: delegates all real logic to claude_runner.py.
# Resolves its own directory so it can be invoked from anywhere.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"

exec "$PYTHON_BIN" "$SCRIPT_DIR/claude_runner.py" "$@"
