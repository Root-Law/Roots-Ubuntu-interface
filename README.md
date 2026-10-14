# Roots Ubuntu Interface

**A touchpad-first Ubuntu workbench with an interactive terminal, saved command keys and guided developer tools.**

Built for a laptop with a working touchpad and a broken physical keyboard. The Ember edition uses dark burgundy, red console borders and warm amber highlights. A physical keyboard remains supported.

Repository: [Root-Law/Roots-Ubuntu-interface](https://github.com/Root-Law/Roots-Ubuntu-interface)

## Install from GitHub

Ubuntu 22.04 or newer is the installer target; development checks currently run on Ubuntu 24.04. Use your normal Ubuntu account. On WSL2, Linux GUI support (WSLg) must be available. Native Ubuntu with a graphical desktop also works for the Linux features; the Windows launchers need WSL interop.

If Git is not installed, install it first:

```bash
sudo apt-get update
sudo apt-get install git
```

Then run these steps in order:

```bash
git clone https://github.com/Root-Law/Roots-Ubuntu-interface.git
cd Roots-Ubuntu-interface
bash install.sh
```

The installer checks Ubuntu dependencies, asks for sudo only when needed, creates this application's `.venv`, installs PyQt6 and pyte, and adds an application-menu shortcut. It does not alter `.bashrc`, replace the existing `Root` alias, or install development packages automatically. Keep the checkout in place: the shortcut launches it.

After installation, click **Roots Ubuntu Interface** in the Linux application menu. With WSLg, the shortcut can also appear in Windows Start under the Ubuntu distribution. You can also run:

```bash
bash launch.sh
```

For a completely broken keyboard during initial setup, use Windows **Settings → Accessibility → Keyboard → On-Screen Keyboard**, or Ubuntu's accessibility keyboard. Commands can be copied from a shared text file. Enter sudo passwords locally, not into shared files. After setup, the application has its own clickable keyboard.

## First session with the touchpad

1. Open **Developer** and click **Choose project**, or **New project folder** to make a folder with the on-screen keyboard.
2. Choose **Create project .venv**, then **Run in project / live output**.
3. Open **Packages**, choose **Python / project .venv** and the **Python tests** package set. Click **Use selected package set**, then **Install selected packages** and review the request. This installs `pytest` into that project, not the application or system Python.
4. Return to **Developer**, select **Run pytest** and click **Run in project / live output**. It will report the actual result, including when no tests exist or pytest is not installed.
5. Open **Terminal**, click **On-screen keyboard**, and use the touchpad to type. Enter submits; Tab completes; arrows recall/edit commands; **Interrupt / Ctrl+C** stops a running foreground command. The extra-key selector includes Home, End, Delete, Page Up/Down and F1–F12.

## Pages

| Page | Purpose |
| --- | --- |
| Workspace | Select a Linux project and launch VS Code, GIMP, Notepad++, Windows Explorer or a configured shared folder |
| System | Read Ubuntu version, memory visible to WSL, disk space and development-command paths |
| Maintenance | Read system state or prepare APT cache cleanup; no automatic RAM-cache flushing |
| Terminal | Interactive Bash, on-screen keyboard, command drafts, copy/paste and interrupt |
| Command Keys | Create, edit, delete and reuse locally saved full commands |
| Developer | Python environments, pytest runs/collection/last failures, CMake and Cargo actions |
| Packages | Guided project Python installs and Ubuntu APT package requests |

The **Show activity** button reveals or hides real command output. The terminal and keyboards have more room when the activity panel is hidden. Pages scroll on smaller displays. Buttons respond to a normal single click or touchpad tap; no hover-only actions or timed gestures are required.

## Saved command keys

Open **Command Keys**. Choose the on-screen keyboard target for the button name or saved command, enter both, and click **Save command key**. You can paste a command from the clipboard and then edit it.

Example names and commands:

| Button name | Full command |
| --- | --- |
| My tests | `.venv/bin/python -m pytest -q` |
| List tests | `.venv/bin/python -m pytest --collect-only -q` |
| Files here | `ls -lah` |
| Git changes | `git status --short` |
| Build C++ | `cmake --build build` |
| Check Rust | `cargo check` |

Clicking a saved key loads a command into the terminal draft. Review it, click **Send text**, then **ENTER** at an idle Bash prompt. Commands are run through `bash -c` from the currently selected project; changes inside that child shell do not persist in the terminal, and interactive aliases are not automatically available there. Saving a key does not execute it. Keys are single-line shell commands and can still change files when you execute them.

Keys are stored privately on the local machine in the Qt application configuration directory as `commands.json`, not in the Git repository. They are plain text: do not save passwords, tokens or secrets. Settings are separate from Leon's original cyan application.

## Package installation

**Python:** create the project's `.venv` first. Pick a suggested package set or enter package names using the clickable keyboard. Normal names and `name==version` are supported. The exact interpreter and arguments are shown before installation, and pip output streams to the activity panel. No `sudo pip`, system Python writes or `--break-system-packages` are used.

**Ubuntu / APT:** suggested sets include Python essentials, C++ tools, Ubuntu's Rust/Cargo packages, and terminal utilities. Installation prepares a reviewed `sudo apt-get install` command in the terminal draft. You click Send text and ENTER. Use the on-screen keyboard with **Type into Bash** for sudo passwords; Bash/TTY echo settings control whether input is visible. Answer APT's own installation prompt with `y` and Enter. If package lists are stale, use **Review APT index refresh in Terminal** first.

APT-installed Rust versions follow Ubuntu repositories. Rustup/toolchain management is not included in this first release. Package presets are conveniences, not recommendations for every project.

## Windows applications

Set the Windows home folder under `/mnt/c/Users` and the shared folder using the Workspace buttons. VS Code needs its `code` command on PATH. Notepad++ is searched in common Windows install locations. GIMP uses its Windows Store app ID. These launchers report dispatch, not verified application readiness; installations that differ may need configuration in a future release.

## Update

Close the application first, then in the checkout:

```bash
git pull --ff-only
bash install.sh
```

Local settings and saved keys remain outside the checkout. Do not update this copy over the separate cyan app if you want to keep both.

## Tests and current limits

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The suite covers process errors, streamed UTF-8 output, interactive Bash, Ctrl+C, terminal resize, nano exit, TTY-hidden input, command persistence, package validation, project isolation and launcher quoting. CI runs offscreen on Ubuntu with Python 3.12 and 3.14. Windows app dispatch, WSLg display behavior and physical ThinkPad touchpad usability require real-device checks. No exact ThinkPad model is required by the application.

This is a first working release, not a full terminal-emulator replacement. Mouse-aware TUI programs, every alternate-screen/color behavior, key repeat, non-US layouts and all applications' accessibility needs are not yet covered. Closing the app ends its Bash session and may stop its commands. Bash retains its usual shell history; terminal input is not copied into saved activity logs. The activity log is a rolling buffer, not a complete audit trail.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). The project uses the GPL version of PyQt6. See [Riverbank's PyQt licensing information](https://www.riverbankcomputing.com/software/pyqt).

## Roadmap

Next priorities: test on the friend's ThinkPad, configurable app executables, larger optional key sizes, preset import/export, keyboard layouts and a more complete terminal behavior suite.
