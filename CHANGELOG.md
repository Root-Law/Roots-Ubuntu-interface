# Changelog

## 0.1.2 — Git controls and nano file picker

- Add 08 / GITHUB with status/branch/history/change/remote information, reviewed fast-forward pull, fetch, staging, commits, branch creation/switching and push controls.
- Add a clickable keyboard for Git messages, branch names and clone URLs; keep arguments literal and show the selected repository folder.
- Add Open a file in nano to Terminal; prepare a quoted file command for review without injecting it into a running task.
- Ensure Git and nano are included by the Ubuntu installer.
- Extend touchpad help, regression tests and application-preference isolation during pytest.

## 0.1.1 — Stable menu and touchpad help

- Keep left-menu buttons at a fixed height when Developer/activity changes the available space; the menu scrolls on smaller windows.
- Reduce the activity panel to 120–160 pixels in height.
- Replace the terminal's keyboard-shortcut banner with a clickable help window.
- Add plain-language help for terminal input, saved command keys, Python tests, package installation and other tools.
- Add regression tests for page switching at a small window size and help navigation.

## 0.1.0 — Ember touchpad workbench

- Dark red/amber desktop interface with scrolling pages and clickable controls.
- Interactive Bash PTY, clipboard controls, on-screen keyboard, modifiers, cursor/function keys and interrupt.
- Saved command-key editor with atomic local persistence, edit/delete and review-before-execution.
- Python project environments, pytest collection/run/last-failure actions, CMake and Cargo helpers.
- Python-package installs isolated to the chosen project's `.venv`; APT requests staged in Bash for user review.
- GitHub clone/install scripts and Linux application-menu shortcut.
- Proportionate pytest coverage and GitHub Actions checks.

Built from the previously tested ROOTSLAW prototype; the existing cyan installation remains independent.
