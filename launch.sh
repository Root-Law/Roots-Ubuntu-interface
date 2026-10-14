#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    printf 'Run bash install.sh in the project folder first.\n' >&2
    exit 1
fi
exec "$project_dir/.venv/bin/python" "$project_dir/rootslaw_panel.py" "$@"
