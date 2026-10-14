import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import time
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox
from rootslaw_panel import Panel, Runner, Terminal, MouseKeyboard
from PyQt6.QtWidgets import QLineEdit

@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])

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
