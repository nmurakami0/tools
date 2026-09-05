#!/usr/bin/env bash
set -euo pipefail
# macOS Bash 3.2 compatible entry point; policy is in the adjacent Python module.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 (3.9+) is required; no resources were changed." >&2
  exit 1
fi
exec python3 "$SCRIPT_DIR/mac_disk_cleanup.py" "$@"
