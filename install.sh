#!/usr/bin/env bash
# GPL-3.0-or-later. Run as your normal Ubuntu user, not with sudo.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${EUID}" -eq 0 ]]; then
    printf 'Run bash install.sh as your normal user. The installer asks for sudo only if Ubuntu dependencies are missing.\n' >&2
    exit 1
fi
if ! command -v apt-get >/dev/null; then
    printf 'This installer currently supports Ubuntu/Debian with APT.\n' >&2
    exit 1
fi
packages=(python3 python3-venv libegl1 libgl1 libopengl0 libxcb-cursor0
          libxkbcommon-x11-0 libdbus-1-3 fonts-dejavu-core libxcb-icccm4
          libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0
          libxcb-xkb1 libwayland-client0 libwayland-cursor0 libwayland-egl1)
missing=()
for package in "${packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed'; then
        missing+=("$package")
    fi
done
if (( ${#missing[@]} )); then
    printf 'Ubuntu packages needed: %s\n' "${missing[*]}"
    sudo -- apt-get update
    sudo -- apt-get install -- "${missing[@]}"
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
if [[ ! -f "$project_dir/.venv/pyvenv.cfg" ]]; then
    python3 -m venv "$project_dir/.venv"
fi
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
"$project_dir/.venv/bin/python" -c 'import PyQt6, pyte; print("ROOTS dependencies ready")'
chmod +x "$project_dir/launch.sh"
"$project_dir/.venv/bin/python" "$project_dir/setup_launcher.py" "$project_dir"
printf '\nInstalled. Open Roots Ubuntu Interface from the Linux applications menu, or run:\n  bash %q\n' "$project_dir/launch.sh"
