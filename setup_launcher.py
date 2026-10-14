# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a desktop shortcut and executable shell shortcut for this checkout."""
from pathlib import Path
import os
import shlex
import sys

def desktop_quote(value):
    # Desktop Entry Exec quoting differs from shell quoting. Escape field codes too.
    text = str(value).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        text = text.replace(char, '\\' + char)
    return '"' + text + '"'

def install_launchers(project, data_home=None, home=None):
    project = Path(project).resolve()
    if any(ord(char) < 32 for char in str(project)):
        raise ValueError('The checkout path must not contain line breaks or control characters.')
    home = Path(home or Path.home())
    data = Path(data_home or os.environ.get('XDG_DATA_HOME', home / '.local/share'))
    apps = data / 'applications'
    apps.mkdir(parents=True, exist_ok=True)
    desktop = apps / 'roots-ubuntu-interface.desktop'
    desktop.write_text('[Desktop Entry]\nType=Application\nName=Roots Ubuntu Interface\n'
        'Comment=Touchpad workbench for Ubuntu\n'
        f'Exec=/bin/bash {desktop_quote(project / "launch.sh")}\n'
        f'Icon={project / "assets/roots.svg"}\n'
        'Terminal=false\nCategories=Development;Utility;\nStartupNotify=true\n', encoding='utf-8')
    bin_dir = home / '.local/bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / 'roots-ubuntu'
    launcher.write_text('#!/usr/bin/env bash\nexec /bin/bash ' + shlex.quote(str(project / 'launch.sh')) + ' "$@"\n', encoding='utf-8')
    launcher.chmod(0o755)
    print('Application-menu shortcut installed:', desktop)
    print('Terminal shortcut installed:', launcher)
    return desktop, launcher

if __name__ == '__main__':
    install_launchers(sys.argv[1])
