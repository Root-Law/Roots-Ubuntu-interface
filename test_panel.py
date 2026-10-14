import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import time
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PyQt6.QtCore import QSettings, QStandardPaths
import rootslaw_panel as panel_module
from rootslaw_panel import Panel, Runner, Terminal, MouseKeyboard
from PyQt6.QtWidgets import QLineEdit

@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def isolate_application_preferences(app, tmp_path, monkeypatch):
    # Running pytest must not change the user's selected project or command keys.
    monkeypatch.setattr(panel_module, 'QSettings', lambda *args: QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda location: str(tmp_path / 'config'))

def wait(app, result):
    deadline = time.monotonic() + 5
    while not result and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert result, 'process did not report completion'

def test_nonzero_exit_preserves_output_and_reports_failure(app, tmp_path):
    runner = Runner()
    result, output = [], []
    runner.completed.connect(lambda *values: result.append(values))
    runner.output.connect(output.append)
    runner.start(sys.executable, ['-c', 'import sys; print("error evidence", flush=True); sys.exit(7)'], tmp_path)
    wait(app, result)
    assert result == [(False, 'Exit code 7')]
    assert 'error evidence' in ''.join(output)
    assert not runner.active

def test_missing_program_reports_failure_once(app, tmp_path):
    runner = Runner()
    result = []
    runner.completed.connect(lambda *values: result.append(values))
    runner.start('/does/not/exist/rootslaw', [], tmp_path)
    wait(app, result)
    assert len(result) == 1 and result[0][0] is False
    assert not runner.active

def test_system_check_completes_and_restores_controls(app):
    panel = Panel()
    result = []
    panel.runner.completed.connect(lambda *values: result.append(values))
    panel.observe()
    assert all(not button.isEnabled() for button in panel.action_buttons)
    wait(app, result)
    assert result[0][0] is True
    assert all(button.isEnabled() for button in panel.action_buttons)
    assert 'No cleanup or health verdict' in panel.console.toPlainText()
    panel.close()

def test_split_utf8_output_keeps_character(app, tmp_path):
    runner = Runner()
    result, output = [], []
    runner.completed.connect(lambda *values: result.append(values))
    runner.output.connect(output.append)
    script = 'import os,time; os.write(1,b"\\xe2"); time.sleep(.05); os.write(1,b"\\x9c\\x93")'
    runner.start(sys.executable, ['-c', script], tmp_path)
    wait(app, result)
    assert ''.join(output) == '✓'

def until(app, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition(), 'terminal condition timed out'

def terminal_text(term):
    return '\n'.join(term.screen.display)

def test_terminal_interactive_input_ctrl_c_and_shutdown(app, tmp_path):
    term = Terminal()
    term.resize(800, 400)
    term.show()
    term.start_shell(tmp_path)
    child = term.child
    try:
        # The helper owns a controlling TTY, and Bash starts in the selected folder.
        term.send(b"printf '\\nPTY_READY_%s\\n' \"$(test -t 0 && echo yes)\"\r")
        until(app, lambda: 'PTY_READY_yes' in terminal_text(term))
        term.send(b"sleep 30\r")
        for _ in range(15):
            app.processEvents()
            time.sleep(.01)
        term.send(b'\x03')
        term.send(b"printf '\\nAFTER_INTERRUPT_%s\\n' OK\r")
        until(app, lambda: 'AFTER_INTERRUPT_OK' in terminal_text(term))
        assert child.poll() is None
    finally:
        term.stop_shell()
        term.close()
    assert child.poll() is not None and term.fd is None

def test_terminal_resize_and_nano_screen(app, tmp_path):
    term = Terminal()
    term.resize(800, 400)
    term.show()
    term.start_shell(tmp_path)
    try:
        term.send(b'nano --ignorercfiles\r')
        until(app, lambda: 'GNU nano' in terminal_text(term))
        term.resize(650, 350)
        app.processEvents()
        assert term.screen.columns == (term.width() - 20) // term.geometry_cells()[0]
        term.send(b'\x18')
        until(app, lambda: os.tcgetpgrp(term.fd) == term.child.pid)
        term.send(b"printf '\\nNANO_EXIT_%s\\n' OK\r")
        until(app, lambda: 'NANO_EXIT_OK' in terminal_text(term))
    finally:
        term.stop_shell()
        term.close()

def test_cleanup_requires_manual_terminal_input(app, monkeypatch):
    panel = Panel()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    sent = []
    monkeypatch.setattr(panel.terminal, 'send', sent.append)
    try:
        panel.clean_cache()
        assert QApplication.clipboard().text() == 'sudo -- apt-get clean'
        assert sent == []
        assert not panel.runner.active
        assert panel.pages.currentIndex() == 3
    finally:
        panel.terminal.stop_shell()
        panel.close()

def test_mouse_keyboard_terminal_shift_ctrl_and_draft(app, monkeypatch):
    terminal = Terminal()
    draft = QLineEdit()
    keyboard = MouseKeyboard(terminal, draft)
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    keyboard.shift.setChecked(True)
    keyboard.character('1', '!')
    assert sent.pop() == b'!'
    keyboard.ctrl.setChecked(True)
    keyboard.character('c', 'C')
    assert sent.pop() == b'\x03'
    assert not keyboard.ctrl.isChecked()
    keyboard.special(b'\r')
    assert sent.pop() == b'\r'
    keyboard.target.setCurrentIndex(1)
    keyboard.character('a', 'A')
    assert draft.text() == 'A'
    keyboard.special(b'\r')
    assert sent == [], 'draft Enter must not execute a command'
    keyboard.special(b'\x7f')
    assert draft.text() == ''

def test_command_draft_sends_text_without_executing(app, monkeypatch):
    panel = Panel()
    sent = []
    monkeypatch.setattr(panel.terminal, 'send', sent.append)
    panel.composer.setText('pwd')
    panel.send_draft()
    assert sent == [b'pwd']
    panel.close()

def test_terminal_hidden_input_follows_tty_echo(app, tmp_path):
    term = Terminal()
    term.resize(900, 400)
    term.show()
    term.start_shell(tmp_path)
    try:
        term.send(b"stty -echo; printf '\\nINPUT_READY_%s\\n' YES; read -r secret; stty echo; printf '\\nINPUT_LENGTH_%s\\n' \"${#secret}\"\r")
        until(app, lambda: 'INPUT_READY_YES' in terminal_text(term))
        term.send(b'DUMMY-HIDDEN-INPUT\r')
        until(app, lambda: 'INPUT_LENGTH_18' in terminal_text(term))
        assert 'DUMMY-HIDDEN-INPUT' not in terminal_text(term)
    finally:
        term.stop_shell()
        term.close()

def test_saved_key_button_stages_without_terminal_injection(app, tmp_path, monkeypatch):
    from workbench import CommandBook
    panel = Panel()
    panel.command_book = CommandBook(tmp_path / 'commands.json')
    panel.saved_label.setText('My tests')
    panel.saved_command.setText('.venv/bin/python -m pytest -q')
    sent = []
    staged = []
    monkeypatch.setattr(panel.terminal, 'send', sent.append)
    monkeypatch.setattr(panel, 'stage', staged.append)
    panel.save_saved()
    panel.saved_grid.itemAt(0).widget().click()
    assert len(staged) == 1 and 'pytest -q' in staged[0]
    assert sent == []
    panel.close()

def test_python_package_install_uses_project_and_runner(app, tmp_path, monkeypatch):
    panel = Panel()
    python = tmp_path / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.touch()
    (tmp_path / '.venv/pyvenv.cfg').write_text('home=/usr/bin')
    panel.workspace = tmp_path
    panel.package_input.setText('pytest numpy')
    runs = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(panel, 'run', lambda *args: runs.append(args))
    panel.install_packages()
    assert runs == [('Install Python packages', str(python), ['-m', 'pip', 'install', 'pytest', 'numpy'])]
    panel.close()

def test_apt_install_is_staged_and_never_injected(app, tmp_path, monkeypatch):
    panel = Panel()
    panel.workspace = tmp_path
    panel.package_kind.setCurrentIndex(1)
    panel.package_input.setText('git nano')
    staged = []
    sent = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(panel, 'stage', staged.append)
    monkeypatch.setattr(panel.terminal, 'send', sent.append)
    panel.install_packages()
    assert len(staged) == 1 and 'sudo -- apt-get install -- git nano' in staged[0]
    assert sent == []
    panel.close()

def test_sidebar_does_not_scrunch_when_switching_pages(app):
    panel = Panel()
    panel.resize(760, 650)
    panel.show()
    try:
        for index in (5, 0, 1, 2, 3, 5):
            panel.navigate(index)
            app.processEvents()
            assert all(button.height() == 46 for button in panel.nav_buttons)
            positions = [button.y() for button in panel.nav_buttons]
            assert all(after - before == 56 for before, after in zip(positions, positions[1:]))
        assert panel.nav_buttons[-1].geometry().bottom() <= panel.sidebar_scroll.viewport().height()
        assert 120 <= panel.console.height() <= 160
    finally:
        panel.terminal.stop_shell()
        panel.close()

def test_help_opens_separately_and_topics_are_clickable(app):
    panel = Panel()
    panel.show_help('Terminal')
    try:
        dialog = panel.help_dialog
        assert dialog.isVisible()
        assert 'Click On-screen keyboard' in dialog.reader.toPlainText()
        dialog.topics.setCurrentText('Installing packages')
        assert 'click y and Enter' in dialog.reader.toPlainText()
        assert panel.pages.currentIndex() == 0
        dialog.close()
        panel.show_help('Saved command buttons')
        assert panel.help_dialog is dialog
        assert 'Save command key' in dialog.reader.toPlainText()
    finally:
        panel.help_dialog.close()
        panel.close()

def test_nano_file_picker_stages_without_injecting(app, tmp_path, monkeypatch):
    panel = Panel()
    file = tmp_path / 'file with spaces.py'
    file.write_text('print("test")')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(file), ''))
    staged, sent = [], []
    monkeypatch.setattr(panel, 'stage', staged.append)
    monkeypatch.setattr(panel.terminal, 'send', sent.append)
    panel.choose_nano_file()
    assert len(staged) == 1 and 'nano --' in staged[0] and str(file) in staged[0]
    assert sent == []
    panel.close()

def test_git_information_runs_in_workspace_and_pull_is_staged(app, tmp_path, monkeypatch):
    panel = Panel()
    panel.set_workspace(tmp_path)
    runs, staged = [], []
    monkeypatch.setattr(panel, 'run', lambda *args: runs.append((args, panel.workspace)))
    monkeypatch.setattr(panel, 'stage', staged.append)
    panel.use_git_action('Current branch', ['git', 'branch', '--show-current'], False)
    panel.use_git_action('Pull', ['git', 'pull', '--ff-only'], True)
    assert runs == [(('Current branch', 'git', ['branch', '--show-current']), tmp_path)]
    assert len(staged) == 1 and str(tmp_path) in staged[0] and '--ff-only' in staged[0]
    assert panel.git_path.text() == str(tmp_path)
    assert panel.nav_buttons[7].text() == '08 / GITHUB'
    panel.close()

def test_nano_selected_file_saves_with_clickable_keyboard(app, tmp_path):
    import shlex
    from workbench import nano_command
    file = tmp_path / 'selected file.txt'
    file.write_text('EXISTING_CONTENT\n')
    term = Terminal()
    term.resize(900, 400)
    term.show()
    term.start_shell(tmp_path)
    keyboard = MouseKeyboard(term, QLineEdit())
    try:
        command = nano_command(file)
        command.insert(1, '--ignorercfiles')
        term.send(shlex.join(command).encode() + b'\r')
        until(app, lambda: 'EXISTING_CONTENT' in terminal_text(term) and 'GNU nano' in terminal_text(term))
        for character in 'added':
            keyboard.character(character, character.upper())
        keyboard.ctrl.setChecked(True)
        keyboard.character('o', 'O')
        until(app, lambda: 'File Name to Write' in terminal_text(term))
        keyboard.special(b'\r')
        until(app, lambda: 'added' in file.read_text())
        keyboard.ctrl.setChecked(True)
        keyboard.character('x', 'X')
        until(app, lambda: os.tcgetpgrp(term.fd) == term.child.pid)
    finally:
        term.stop_shell()
        term.close()
