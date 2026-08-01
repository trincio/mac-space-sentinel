#!/bin/zsh
# Thin, location-independent launcher. No install and no destructive default.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/env python3 "$SCRIPT_DIR/mac-space-sentinel.py" "$@"
