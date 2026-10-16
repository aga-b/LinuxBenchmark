#!/usr/bin/env bash
# Compatibility entry point for Dell R740 / generic Linux acceptance tests.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.9+ gerekli. Debian/Proxmox: apt-get install python3' >&2
  exit 3
fi
exec python3 "$SCRIPT_DIR/linuxbenchmark.py" "$@"
