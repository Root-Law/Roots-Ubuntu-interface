#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""ROOTS touchpad workbench. Python 3.10+, PyQt6; Ubuntu/WSL2."""
import codecs
import os
from pathlib import Path
import shutil
import sys
import errno
import fcntl
import pty
import signal
import struct
import subprocess
import termios
import shlex
from datetime import datetime

from PyQt6.QtCore import Qt, QProcess, QSettings, QTimer, QSocketNotifier, QStandardPaths, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QGraphicsDropShadowEffect,
    QStackedWidget, QVBoxLayout, QWidget, QLineEdit, QComboBox, QScrollArea, QLayout, QDialog,
)
import pyte
from workbench import CommandBook, package_command, project_python, developer_commands, staged_command

WINDOWS_HOME = Path('/mnt/c/Users')
GIMP_ID = r'shell:AppsFolder\GIMP.43237F745459_nq49gba4h4mx8!GIMP'


class Terminal(QWidget):
    """An interactive PTY with a pyte screen; terminal input is never logged."""
    state_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(QFont('DejaVu Sans Mono', 11))
        self.setStyleSheet('font-family: "DejaVu Sans Mono"; font-size: 14px;')
        self.setMinimumSize(400, 140)
        self.screen = pyte.HistoryScreen(80, 24, history=1000)
        self.stream = pyte.ByteStream(self.screen)
        self.fd = None
        self.child = None
        self.notifier = None
        self.pending = bytearray()
        self.selection = None
        self.drag_start = None
        self.blink_on = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.ticks = 0

    def start_shell(self, folder):
        if self.child and self.child.poll() is None:
            self.setFocus()
            return
        self.stop_shell()
        self.screen.reset()
        master, slave = pty.openpty()
        self.fd = master
        try:
            self.resize_pty()
            env = dict(os.environ, TERM='linux', COLORTERM='truecolor')
            self.child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--terminal-child', str(folder)],
                stdin=slave, stdout=slave, stderr=slave, env=env,
                start_new_session=True, close_fds=True,
            )
        except Exception:
            os.close(master)
            self.fd = None
            raise
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        self.notifier = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self.read_pty)
        self.state_changed.emit('BASH ACTIVE / input goes directly to Ubuntu')
        self.setFocus()

    def geometry_cells(self):
        metrics = QFontMetrics(self.font())
        return max(1, metrics.horizontalAdvance('M')), max(1, metrics.height())

    def resize_pty(self):
        cw, ch = self.geometry_cells()
        cols, rows = max(10, (self.width() - 20) // cw), max(3, (self.height() - 20) // ch)
        self.screen.resize(lines=rows, columns=cols)
        if self.fd is not None:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

    def resizeEvent(self, event):
        self.selection = None
        self.resize_pty()
        self.update()

    def read_pty(self, *args):
        if self.fd is None:
            return
        # Bound each event so output-heavy commands cannot starve the UI.
        for _ in range(16):
            try:
                data = os.read(self.fd, 4096)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno == errno.EIO:
                    self.close_fd()
                    break
                self.state_changed.emit(f'TERMINAL READ ERROR / {exc}')
                self.close_fd()
                break
            if not data:
                self.close_fd()
                break
            self.selection = None
            self.stream.feed(data)
        self.update()

    def send(self, data):
        if self.fd is None or not self.child or self.child.poll() is not None:
            return
        while self.screen.history.position < self.screen.history.size:
            old = self.screen.history.position
            self.screen.next_page()
            if self.screen.history.position == old:
                break
        self.selection = None
        self.pending.extend(data)
        self.flush_input()

    def flush_input(self):
        if self.fd is not None and self.pending:
            try:
                count = os.write(self.fd, self.pending[:4096])
                del self.pending[:count]
            except BlockingIOError:
                pass
            except OSError:
                self.pending.clear()

    def tick(self):
        self.flush_input()
        self.ticks += 1
        if self.ticks % 6 == 0:
            self.blink_on = not self.blink_on
            self.update()
        if self.child and self.child.poll() is not None:
            code = self.child.returncode
            self.read_pty()
            self.close_fd()
            self.child = None
            self.state_changed.emit(f'SHELL EXITED / code {code}. Use Start Bash to reopen.')

    def close_fd(self):
        if self.notifier:
            self.notifier.setEnabled(False)
            self.notifier.deleteLater()
            self.notifier = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def stop_shell(self):
        self.close_fd()
        if self.child:
            if self.child.poll() is None:
                try:
                    os.killpg(self.child.pid, signal.SIGHUP)
                    self.child.wait(timeout=.3)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=1)
                except ProcessLookupError:
                    self.child.wait(timeout=1)
            self.child = None
        self.pending.clear()

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy_selection()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste()
            return
        if shift and key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            (self.screen.prev_page if key == Qt.Key.Key_PageUp else self.screen.next_page)()
            self.update()
            return
        mapping = {
            Qt.Key.Key_Return: b'\r', Qt.Key.Key_Enter: b'\r', Qt.Key.Key_Backspace: b'\x7f',
            Qt.Key.Key_Tab: b'\t', Qt.Key.Key_Backtab: b'\x1b[Z', Qt.Key.Key_Escape: b'\x1b',
            Qt.Key.Key_Up: b'\x1b[A', Qt.Key.Key_Down: b'\x1b[B',
            Qt.Key.Key_Right: b'\x1b[C', Qt.Key.Key_Left: b'\x1b[D',
            Qt.Key.Key_Home: b'\x1b[1~', Qt.Key.Key_End: b'\x1b[4~',
            Qt.Key.Key_Delete: b'\x1b[3~', Qt.Key.Key_Insert: b'\x1b[2~',
            Qt.Key.Key_PageUp: b'\x1b[5~', Qt.Key.Key_PageDown: b'\x1b[6~',
        }
        if ctrl and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            self.send(bytes([key - Qt.Key.Key_A + 1]))
        elif key in mapping:
            self.send(mapping[key])
        elif event.text():
            prefix = b'\x1b' if mods & Qt.KeyboardModifier.AltModifier else b''
            self.send(prefix + event.text().encode('utf-8'))
        else:
            super().keyPressEvent(event)

    def paste(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        if '\n' in text or '\r' in text:
            answer = QMessageBox.question(self, 'Paste multiple lines?', 'This paste contains line breaks and may execute commands immediately. Paste it into Bash?')
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.send(text.replace('\r\n', '\n').replace('\n', '\r').encode('utf-8'))

    def cell(self, point):
        cw, ch = self.geometry_cells()
        return (max(0, min(self.screen.lines - 1, int((point.y() - 10) // ch))),
                max(0, min(self.screen.columns - 1, int((point.x() - 10) // cw))))

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = self.cell(event.position())
            self.selection = (self.drag_start, self.drag_start)
            self.update()

    def mouseMoveEvent(self, event):
        if self.drag_start and event.buttons() & Qt.MouseButton.LeftButton:
            self.selection = (self.drag_start, self.cell(event.position()))
            self.update()

    def wheelEvent(self, event):
        (self.screen.prev_page if event.angleDelta().y() > 0 else self.screen.next_page)()
        self.selection = None
        self.update()

    def copy_selection(self):
        if not self.selection:
            return
        start, end = sorted(self.selection)
        lines = []
        for row in range(start[0], end[0] + 1):
            left = start[1] if row == start[0] else 0
            right = end[1] if row == end[0] else self.screen.columns - 1
            lines.append(''.join(self.screen.buffer[row][col].data for col in range(left, right + 1)).rstrip())
        QApplication.clipboard().setText('\n'.join(lines))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#0e0809'))
        painter.setFont(self.font())
        cw, ch = self.geometry_cells()
        ascent = QFontMetrics(self.font()).ascent()
        palette = dict(black='#0b1119', red='#ff718b', green='#99f5c5', brown='#edc77b',
                       blue='#6dacf7', magenta='#c397ff', cyan='#ff9560', white='#d9ebf2',
                       default='#ffe0a2')
        bounds = sorted(self.selection) if self.selection else None
        for row in range(self.screen.lines):
            for col in range(self.screen.columns):
                char = self.screen.buffer[row][col]
                fg = QColor(palette.get(char.fg, '#' + char.fg))
                bg = QColor('#0e0809') if char.bg == 'default' else QColor(palette.get(char.bg, '#' + char.bg))
                if char.reverse:
                    fg, bg = bg, fg
                if bounds and bounds[0] <= (row, col) <= bounds[1]:
                    bg = QColor('#744032')
                x, y = 10 + col * cw, 10 + row * ch
                painter.fillRect(x, y, cw, ch, bg)
                painter.setPen(fg)
                painter.drawText(x, y + ascent, char.data)
                if char.underscore:
                    painter.drawLine(x, y + ch - 2, x + cw, y + ch - 2)
        if self.hasFocus() and self.blink_on and not self.screen.cursor.hidden:
            painter.fillRect(10 + self.screen.cursor.x * cw,
                             10 + self.screen.cursor.y * ch + ch - 3, cw, 3, QColor('#ffba66'))
        painter.setPen(QPen(QColor('#ff694c'), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)


def system_report():
    """Read WSL observations, without changing system state."""
    print('> SYSTEM OBSERVATION / UBUNTU + WSL', flush=True)
    print(Path('/etc/os-release').read_text(), flush=True)
    print('Kernel:', os.uname().release, flush=True)
    fields = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        fields[key] = int(value.split()[0])
    print('\n> MEMORY VISIBLE TO UBUNTU (not total Windows RAM)', flush=True)
    for key in ('MemTotal', 'MemAvailable', 'Cached'):
        print(f'{key}: {fields[key] / 1024**2:.2f} GiB', flush=True)
    print('Linux reclaims caches when memory is needed.', flush=True)
    print('\n> FILESYSTEM SPACE', flush=True)
    for location in (Path.home(), Path('/mnt/c')):
        if location.exists():
            usage = shutil.disk_usage(location)
            print(f'{location}: {usage.free / 1024**3:.1f} GiB free / '
                  f'{usage.total / 1024**3:.1f} GiB total', flush=True)
    print('\n> DEVELOPMENT COMMAND PATHS', flush=True)
    for name in ('python3', 'rustc', 'cargo', 'gcc', 'g++', 'git', 'code'):
        print(f'{name}: {shutil.which(name) or "not found on PATH"}', flush=True)
    print('\n> Observation complete. No cleanup or health verdict performed.', flush=True)


class MouseKeyboard(QWidget):
    """Mouse input routed explicitly to Bash or an editable command draft."""
    def __init__(self, terminal, composer):
        super().__init__()
        self.terminal, self.composer = terminal, composer
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        toolbar = QHBoxLayout()
        self.target = QComboBox()
        self.target.addItems(['Type into Bash', 'Edit command draft'])
        self.edit_targets = [composer]
        toolbar.addWidget(self.target)
        self.shift = self.button('SHIFT', lambda: None, checkable=True)
        self.ctrl = self.button('CTRL', lambda: None, checkable=True)
        toolbar.addWidget(self.shift)
        toolbar.addWidget(self.ctrl)
        layout.addLayout(toolbar)
        self.characters = []
        rows = [('`1234567890-=', '~!@#$%^&*()_+'),
                ('qwertyuiop[]\\', 'QWERTYUIOP{}|'),
                ("asdfghjkl;'", 'ASDFGHJKL:\"'),
                ('zxcvbnm,./', 'ZXCVBNM<>?')]
        for normal, shifted in rows:
            row = QHBoxLayout()
            row.setSpacing(3)
            for lower, upper in zip(normal, shifted):
                button = self.button(lower, lambda checked=False, ch=lower, up=upper: self.character(ch, up))
                self.characters.append((button, lower, upper))
                row.addWidget(button)
            layout.addLayout(row)
        self.shift.toggled.connect(self.update_labels)
        specials = QHBoxLayout()
        for label, data in [('Space', b' '), ('Tab', b'\t'), ('Backspace', b'\x7f'),
                            ('←', b'\x1b[D'), ('→', b'\x1b[C'),
                            ('↑', b'\x1b[A'), ('↓', b'\x1b[B'),
                            ('Esc', b'\x1b'), ('Enter', b'\r')]:
            specials.addWidget(self.button(label, lambda checked=False, value=data: self.special(value)))
        layout.addLayout(specials)
        extras = QHBoxLayout()
        self.extra_keys = QComboBox()
        keys = [('Home', b'\x1b[1~'), ('End', b'\x1b[4~'), ('Delete', b'\x1b[3~'),
                ('Page Up', b'\x1b[5~'), ('Page Down', b'\x1b[6~')]
        keys += [(f'F{i}', b'\x1b[[' + bytes([64 + i])) for i in range(1, 6)]
        keys += [(f'F{i}', f'\x1b[{n}~'.encode()) for i, n in zip(range(6, 13), [17, 18, 19, 20, 21, 23, 24])]
        for name, data in keys:
            self.extra_keys.addItem(name, data)
        extras.addWidget(self.extra_keys, 1)
        extras.addWidget(self.button('Send selected key', lambda: self.special(self.extra_keys.currentData())))
        layout.addLayout(extras)

    def button(self, text, callback, checkable=False):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setMinimumWidth(25)
        button.setCheckable(checkable)
        button.setStyleSheet('QPushButton { padding: 4px; min-height: 22px; font-family: "DejaVu Sans Mono"; font-size: 13px; text-align: center; }')
        button.clicked.connect(callback)
        return button

    def update_labels(self):
        for button, lower, upper in self.characters:
            button.setText(upper if self.shift.isChecked() else lower)

    def add_target(self, name, editor):
        self.edit_targets.append(editor)
        self.target.addItem(name)

    def editor(self):
        index = self.target.currentIndex() - 1
        return self.edit_targets[index] if index >= 0 else None

    def character(self, lower, upper):
        text = upper if self.shift.isChecked() else lower
        editor = self.editor()
        if editor is not None:
            if self.ctrl.isChecked() and lower == 'a':
                editor.selectAll()
            elif not self.ctrl.isChecked():
                editor.insert(text)
        else:
            if self.ctrl.isChecked() and len(lower) == 1 and '@' <= lower.upper() <= '_':
                self.terminal.send(bytes([ord(lower.upper()) & 31]))
            else:
                self.terminal.send(text.encode('utf-8'))
        self.ctrl.setChecked(False)

    def special(self, value):
        if self.target.currentIndex() == 0:
            self.terminal.send(value)
            return
        editor = self.editor()
        if value == b' ':
            editor.insert(' ')
        elif value == b'\x7f':
            editor.backspace()
        elif value == b'\x1b[D':
            editor.cursorBackward(False, 1)
        elif value == b'\x1b[C':
            editor.cursorForward(False, 1)
        elif value == b'\x1b[1~':
            editor.home(False)
        elif value == b'\x1b[4~':
            editor.end(False)
        elif value == b'\x1b[3~':
            editor.del_()
        # Enter never executes an editable draft. The Send text button is explicit.


class Runner(QWidget):
    output = pyqtSignal(str)
    completed = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finish)
        self.process.errorOccurred.connect(self.error)
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.active = False

    def start(self, program, arguments, cwd):
        if self.active:
            return False
        self.active = True
        self.decoder.reset()
        self.process.setWorkingDirectory(str(cwd))
        self.process.start(program, arguments)
        return True

    def read_output(self):
        chunk = bytes(self.process.readAllStandardOutput())
        if chunk:
            self.output.emit(self.decoder.decode(chunk))

    def finish(self, code, status):
        if not self.active:
            return
        self.read_output()
        remaining = self.decoder.decode(b'', final=True)
        if remaining:
            self.output.emit(remaining)
        self.active = False
        good = code == 0 and status == QProcess.ExitStatus.NormalExit
        self.completed.emit(good, f'Exit code {code}' if status == QProcess.ExitStatus.NormalExit
                            else 'Process crashed')

    def error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.active:
            self.active = False
            self.completed.emit(False, self.process.errorString())


class CircuitHeader(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(102)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#130b0d'))
        p.setPen(QPen(QColor('#57282a'), 1))
        for offset in range(0, 5):
            x = self.width() - 285 + offset * 32
            p.drawLine(x, 0, x, 36)
            p.drawLine(x, 36, x + 36, 72)
            p.drawLine(x + 36, 72, self.width(), 72)
        p.setPen(QColor('#ffba66'))
        p.setFont(QFont('DejaVu Sans Mono', 23, QFont.Weight.Bold))
        p.drawText(24, 46, 'ROOTS / EMBER')
        p.setFont(QFont('DejaVu Sans Mono', 10))
        p.setPen(QColor('#bba6a0'))
        p.drawText(25, 75, 'TOUCHPAD WORKBENCH  /  UBUNTU · WSL2')
        p.setPen(QPen(QColor('#ff694c'), 2))
        p.drawLine(0, 100, self.width(), 100)


STYLE = '''
QWidget { background: #100b0d; color: #f2ded5; font-family: "DejaVu Sans"; font-size: 14px; }
QFrame#panel { background: #1b1013; border: 1px solid #79402d; border-top: 2px solid #ff9560; border-radius: 7px; }
QLabel { background: transparent; }
QLabel#eyebrow { color: #ffc077; font-family: "DejaVu Sans Mono"; font-size: 12px; }
QLabel#path { color: #bda9a1; font-family: "DejaVu Sans Mono"; }
QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #382022,stop:1 #1b0e12); border: 1px solid #854538; border-top: 1px solid #aa6650; border-radius: 5px; padding: 12px; text-align: left; }
QPushButton:hover { background: #4b2427; border: 1px solid #ffc077; color: #ffe5a1; }
QPushButton:pressed { background: #73382f; }
QPushButton:checked { border-left: 3px solid #ffba66; color: #ffba66; background: #4b2427; }
QPushButton:disabled { color: #816b64; border-color: #422b29; }
QPlainTextEdit { background: #100809; color: #ffe0a2; border: 1px solid #844239; padding: 12px; font-family: "DejaVu Sans Mono"; font-size: 13px; selection-background-color: #784635; }
QProgressBar { background: #2b161a; border: none; height: 4px; }
QProgressBar::chunk { background: #ff9560; }
QMessageBox QLabel { min-width: 360px; }
'''


class Panel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ROOTS / Ubuntu Interface — Ember')
        self.resize(1040, 800)
        self.setMinimumSize(760, 650)
        self.settings = QSettings('Root-Law', 'RootsUbuntuInterface')
        data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        self.command_book = CommandBook(data / 'commands.json')
        self.windows_home = Path(self.settings.value('windows_home', str(WINDOWS_HOME)))
        self.share_folder = Path(self.settings.value('share_folder', str(Path.home())))
        saved = Path(self.settings.value('workspace', str(Path.home())))
        self.workspace = saved if saved.is_dir() else Path.home()
        self.runner = Runner(self)
        self.folder_result = None
        self.runner.output.connect(self.stream)
        self.runner.output.connect(self.capture_folder_path)
        self.runner.completed.connect(self.completed)
        self.terminal = None
        self.action_buttons = []
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(CircuitHeader())
        body = QHBoxLayout()
        nav = QVBoxLayout()
        nav.setSpacing(10)
        self.pages = QStackedWidget()
        self.nav_buttons = []
        for index, name in enumerate(('01 / WORKSPACE', '02 / SYSTEM', '03 / MAINTENANCE', '04 / TERMINAL', '05 / COMMAND KEYS', '06 / DEVELOPER', '07 / PACKAGES')):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setFixedWidth(185)
            button.clicked.connect(lambda checked, i=index: self.navigate(i))
            self.nav_buttons.append(button)
            nav.addWidget(button)
        nav.addStretch()
        body.addLayout(nav)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.make_workspace()
        self.make_system()
        self.make_maintenance()
        self.make_terminal()
        self.make_commands()
        self.make_developer()
        self.make_packages()
        self.navigate(0)
        console_header = QHBoxLayout()
        caption = QLabel('LIVE ACTIVITY / REAL COMMAND OUTPUT')
        self.activity_caption = caption
        caption.setObjectName('eyebrow')
        console_header.addWidget(caption)
        console_header.addStretch()
        self.cursor = QLabel('IDLE ▌')
        self.cursor.setObjectName('eyebrow')
        console_header.addWidget(self.cursor)
        layout.addLayout(console_header)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(210)
        self.console.document().setMaximumBlockCount(2000)
        self.glow(self.console, '#ac3e23')
        layout.addWidget(self.console, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.status = QLabel('READY / manual control')
        self.status.setObjectName('eyebrow')
        bottom.addWidget(self.status, 1)
        self.activity_toggle = QPushButton('Show activity')
        self.activity_toggle.setCheckable(True)
        self.activity_toggle.setChecked(True)
        self.activity_toggle.toggled.connect(self.show_activity)
        bottom.addWidget(self.activity_toggle)
        for name, callback in (('Save activity', self.save_log), ('Clear', self.console.clear)):
            button = QPushButton(name)
            button.clicked.connect(callback)
            bottom.addWidget(button)
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.blink)
        self.timer.start(600)
        self.phase = False
        self.log('CONSOLE INITIALIZED / no maintenance runs automatically')
        self.log('Select a workspace, launch a tool, or request a system observation.')
        self.refresh_saved_commands()

    def frame(self, heading, description):
        frame = QFrame()
        frame.setObjectName('panel')
        self.glow(frame, '#6f281a')
        box = QVBoxLayout(frame)
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        box.setContentsMargins(20, 18, 20, 18)
        title = QLabel(heading)
        title.setObjectName('eyebrow')
        box.addWidget(title)
        detail = QLabel(description)
        detail.setWordWrap(True)
        box.addWidget(detail)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(frame)
        self.pages.addWidget(scroll)
        return box

    def glow(self, widget, color):
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(20)
        effect.setColor(QColor(color))
        effect.setOffset(0, 3)
        widget.setGraphicsEffect(effect)

    def make_workspace(self):
        box = self.frame('WORKSPACE / LAUNCH CONTROL', 'Your Ubuntu workspace and Windows creative tools.')
        self.path_label = QLabel(str(self.workspace))
        self.path_label.setObjectName('path')
        self.path_label.setWordWrap(True)
        box.addWidget(self.path_label)
        choose = QPushButton('Choose project folder…')
        choose.clicked.connect(self.choose_workspace)
        box.addWidget(choose)
        grid = QGridLayout()
        npp = '/mnt/c/Program Files (x86)/Notepad++/notepad++.exe'
        entries = [
            ('01 / VS CODE', lambda: self.launch('VS Code', 'code', [str(self.workspace)])),
            ('02 / GIMP', lambda: self.launch('GIMP', 'explorer.exe', [GIMP_ID])),
            ('03 / NOTEPAD++', self.launch_notepad),
            ('04 / SHARED FOLDER', lambda: self.open_folder(self.share_folder)),
            ('05 / WINDOWS HOME', lambda: self.open_folder(self.windows_home)),
            ('06 / EXPLORER HERE', lambda: self.open_folder(self.workspace)),
        ]
        for i, (name, callback) in enumerate(entries):
            button = QPushButton(name)
            button.setMinimumHeight(58)
            button.clicked.connect(callback)
            grid.addWidget(button, i // 2, i % 2)
        box.addLayout(grid)
        config = QHBoxLayout()
        for text, key in [('Set Windows home…', 'windows_home'), ('Set shared folder…', 'share_folder')]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, field=key: self.configure_folder(field))
            config.addWidget(button)
        box.addLayout(config)

    def launch_notepad(self):
        candidates = [Path('/mnt/c/Program Files/Notepad++/notepad++.exe'),
                      Path('/mnt/c/Program Files (x86)/Notepad++/notepad++.exe'),
                      self.windows_home / 'AppData/Local/Programs/Notepad++/notepad++.exe']
        match = next((path for path in candidates if path.is_file()), None)
        if match:
            self.launch('Notepad++', str(match), [])
        else:
            self.log('Notepad++ not found in the common install locations. Use the terminal or Windows Start to launch it.')

    def configure_folder(self, key):
        folder = QFileDialog.getExistingDirectory(self, 'Choose folder', str(getattr(self, key)))
        if folder:
            setattr(self, key, Path(folder))
            self.settings.setValue(key, folder)
            self.log(f'{key.replace("_", " ")} configured: {folder}')

    def make_system(self):
        box = self.frame('SYSTEM / OBSERVATION', 'Read Ubuntu version, WSL memory, filesystem space and available command paths. These checks do not certify overall machine health.')
        self.task_button(box, 'REFRESH SYSTEM READINGS', self.observe)
        box.addStretch()

    def make_maintenance(self):
        box = self.frame('MAINTENANCE / MANUAL SERVICE', 'APT cleanup removes cached package downloads. It does not uninstall software. RAM caches are left to Linux to manage.')
        self.task_button(box, 'CHECK SYSTEM / READ ONLY', self.observe)
        self.task_button(box, 'PREPARE APT CACHE CLEANUP', self.clean_cache)
        info = QLabel('Cleanup opens the embedded terminal and copies the command for you. Paste it when Bash is ready, then enter your Ubuntu sudo password there if asked. Commands are never injected into a running terminal task.\n\nYour existing maintenance.sh is not executed by this panel.')
        info.setWordWrap(True)
        box.addWidget(info)
        box.addStretch()

    def task_button(self, layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        self.action_buttons.append(button)
        layout.addWidget(button)

    def make_terminal(self):
        box = self.frame('TERMINAL / INTERACTIVE UBUNTU BASH',
                         'Ctrl+C interrupts · Ctrl+Shift+C copies selection · Ctrl+Shift+V pastes · Shift+PageUp/Down scrolls. Shell directory is independent of the launcher workspace.')
        toolbar = QHBoxLayout()
        self.terminal = Terminal()
        self.terminal_status = QLabel('BASH OFFLINE / select Terminal or Start Bash')
        self.terminal_status.setObjectName('eyebrow')
        self.terminal_status.setWordWrap(True)
        self.terminal.state_changed.connect(self.terminal_status.setText)
        for title, callback in [('Start Bash', self.start_terminal),
                                ('Copy selection', self.terminal.copy_selection),
                                ('Paste', self.terminal.paste),
                                ('Interrupt / Ctrl+C', lambda: self.terminal.send(b'\x03'))]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        box.addLayout(toolbar)
        box.addWidget(self.terminal_status)
        box.addWidget(self.terminal, 1)
        self.composer = QLineEdit()
        self.composer.setPlaceholderText('Optional command draft — sending text does not press Enter')
        draft = QHBoxLayout()
        draft.addWidget(self.composer, 1)
        send = QPushButton('Send text')
        send.clicked.connect(self.send_draft)
        draft.addWidget(send)
        box.addLayout(draft)
        presets = QHBoxLayout()
        self.presets = QComboBox()
        self.presets.addItems(['Choose command…', 'pwd', 'ls -lah', 'python3 --version', 'git status --short', 'free -h', 'df -h', 'ps -eo pid,comm,%cpu,%mem --sort=-%cpu', 'uname -a', 'tree -L 2'])
        load = QPushButton('Load into draft')
        load.clicked.connect(lambda: self.composer.setText(self.presets.currentText()) if self.presets.currentIndex() else None)
        presets.addWidget(self.presets, 1)
        presets.addWidget(load)
        self.keyboard = MouseKeyboard(self.terminal, self.composer)
        toggle = QPushButton('On-screen keyboard')
        toggle.setCheckable(True)
        toggle.toggled.connect(self.keyboard.setVisible)
        presets.addWidget(toggle)
        box.addLayout(presets)
        box.addWidget(self.keyboard)
        self.keyboard.hide()
        enter = QPushButton('ENTER / execute terminal input')
        enter.clicked.connect(lambda: self.terminal.send(b'\r'))
        presets.addWidget(enter)

    def send_draft(self):
        # Never store drafts; they may contain sensitive text.
        self.terminal.send(self.composer.text().encode('utf-8'))
        self.terminal.setFocus()

    def small_button(self, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        return button

    def show_error(self, text):
        QMessageBox.information(self, 'Action needs attention', str(text))
        self.log(f'ACTION NOT COMPLETED / {text}')

    def stage(self, command):
        """Review only: never inject into a terminal task or press Enter."""
        self.navigate(3)
        self.composer.setText(command)
        self.terminal_status.setText('COMMAND READY / review draft, click Send text, then ENTER at an idle Bash prompt')

    def make_commands(self):
        box = self.frame('COMMAND KEYS / YOUR OWN SHORTCUTS',
                         'Save a full command under a named button. Clicking a key loads it into the terminal draft for review. Stored locally as plain text: do not save passwords or secrets.')
        self.saved_grid = QGridLayout()
        box.addLayout(self.saved_grid)
        self.saved_choice = QComboBox()
        box.addWidget(self.saved_choice)
        row = QHBoxLayout()
        for text, fn in [('Edit selected', self.edit_saved), ('New key', self.new_saved), ('Delete selected', self.delete_saved)]:
            row.addWidget(self.small_button(text, fn))
        box.addLayout(row)
        self.saved_label = QLineEdit()
        self.saved_label.setPlaceholderText('Button name — for example: Run my tests')
        self.saved_command = QLineEdit()
        self.saved_command.setPlaceholderText('Full command — for example: .venv/bin/python -m pytest -q')
        box.addWidget(self.saved_label)
        box.addWidget(self.saved_command)
        row = QHBoxLayout()
        row.addWidget(self.small_button('Paste into command', lambda: self.saved_command.setText(QApplication.clipboard().text())))
        row.addWidget(self.small_button('Save command key', self.save_saved))
        box.addLayout(row)
        self.saved_edit_id = None
        keyboard = MouseKeyboard(self.terminal, self.saved_label)
        keyboard.target.setItemText(1, 'Edit button name')
        keyboard.add_target('Edit saved command', self.saved_command)
        keyboard.target.setCurrentIndex(1)
        box.addWidget(keyboard)

    def refresh_saved_commands(self):
        while self.saved_grid.count():
            item = self.saved_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.saved_choice.clear()
        try:
            items = self.command_book.load()
        except (ValueError, OSError) as exc:
            self.show_error(f'Cannot read saved commands: {exc}. Existing file has not been replaced.')
            return
        self.saved_choice.addItem('Choose a saved key…', None)
        for index, item in enumerate(items):
            self.saved_choice.addItem(item['label'], item)
            button = self.small_button(item['label'], lambda checked=False, command=item['command']: self.stage(staged_command(self.workspace, ['/bin/bash', '-c', command])))
            button.setToolTip(item['command'])
            button.setMinimumHeight(46)
            self.saved_grid.addWidget(button, index // 2, index % 2)
        if not items:
            self.saved_grid.addWidget(QLabel('No keys saved yet. Add one below using the on-screen keyboard.'), 0, 0)

    def new_saved(self):
        self.saved_edit_id = None
        self.saved_label.clear()
        self.saved_command.clear()

    def edit_saved(self):
        item = self.saved_choice.currentData()
        if item:
            self.saved_edit_id = item['id']
            self.saved_label.setText(item['label'])
            self.saved_command.setText(item['command'])

    def save_saved(self):
        try:
            self.command_book.upsert(self.saved_label.text(), self.saved_command.text(), self.saved_edit_id)
        except (ValueError, OSError) as exc:
            self.show_error(exc)
            return
        self.new_saved()
        self.refresh_saved_commands()
        self.log('Command key saved locally.')

    def delete_saved(self):
        item = self.saved_choice.currentData()
        if item and QMessageBox.question(self, 'Delete command key?', f'Delete the saved key "{item["label"]}"?') == QMessageBox.StandardButton.Yes:
            try:
                self.command_book.delete(item['id'])
            except (ValueError, OSError) as exc:
                self.show_error(exc)
                return
            self.new_saved()
            self.refresh_saved_commands()

    def make_developer(self):
        box = self.frame('DEVELOPER / PYTHON FIRST',
                         'Choose a project, create its Python environment, install pytest on the Packages page, then run tests here. C++/CMake and Rust/Cargo actions are included when those tools are installed.')
        self.dev_path = QLabel(str(self.workspace))
        self.dev_path.setWordWrap(True)
        box.addWidget(self.dev_path)
        row = QHBoxLayout()
        row.addWidget(self.small_button('Choose project…', self.choose_workspace))
        row.addWidget(self.small_button('New project folder…', self.new_project))
        box.addLayout(row)
        self.dev_choice = QComboBox()
        self.dev_choice.addItems([label for label, _ in developer_commands(self.workspace)])
        box.addWidget(self.dev_choice)
        self.dev_preview = QLabel()
        self.dev_preview.setWordWrap(True)
        self.dev_preview.setObjectName('path')
        box.addWidget(self.dev_preview)
        self.dev_choice.currentIndexChanged.connect(self.refresh_project_views)
        row = QHBoxLayout()
        row.addWidget(self.small_button('Review in terminal', self.stage_developer))
        run = self.small_button('Run in project / live output', self.run_developer)
        self.action_buttons.append(run)
        row.addWidget(run)
        box.addLayout(row)
        info = QLabel('Python packages and pytest use this project’s .venv. The application’s own environment stays separate. Test commands execute your project code. Results appear in Live Activity with the real exit status.')
        info.setWordWrap(True)
        box.addWidget(info)
        box.addStretch()

    def refresh_project_views(self, *args):
        if hasattr(self, 'dev_choice'):
            self.dev_path.setText(str(self.workspace))
            commands = developer_commands(self.workspace)
            self.dev_preview.setText(staged_command(self.workspace, commands[self.dev_choice.currentIndex()][1]))
        if hasattr(self, 'package_path'):
            self.package_path.setText(str(self.workspace))
            self.preview_package()

    def stage_developer(self):
        _, args = developer_commands(self.workspace)[self.dev_choice.currentIndex()]
        self.stage(staged_command(self.workspace, args))

    def run_developer(self):
        label, args = developer_commands(self.workspace)[self.dev_choice.currentIndex()]
        try:
            if args[0].endswith('/.venv/bin/python'):
                project_python(self.workspace)
            if label == 'Create project .venv' and (self.workspace / '.venv').exists():
                raise ValueError('This project already has .venv. It has not been overwritten.')
        except ValueError as exc:
            self.show_error(exc)
            return
        self.run(label, args[0], args[1:])

    def new_project(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('New project folder')
        dialog.resize(780, 370)
        box = QVBoxLayout(dialog)
        heading = QLabel(f'Create a new folder inside: {self.workspace}')
        heading.setWordWrap(True)
        box.addWidget(heading)
        name = QLineEdit()
        name.setPlaceholderText('Folder name')
        box.addWidget(name)
        keyboard = MouseKeyboard(self.terminal, name)
        keyboard.target.setItemText(1, 'Edit folder name')
        keyboard.target.setCurrentIndex(1)
        box.addWidget(keyboard)
        box.addWidget(self.small_button('Create folder', dialog.accept))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = name.text().strip()
            if not text or text in ('.', '..') or '/' in text or '\\' in text or any(ord(ch) < 32 for ch in text):
                self.show_error('Use a single folder name, not a path.')
                return
            try:
                folder = self.workspace / text
                folder.mkdir()
                self.set_workspace(folder)
            except OSError as exc:
                self.show_error(exc)

    def make_packages(self):
        box = self.frame('PACKAGES / GUIDED INSTALLATION',
                         'Python libraries go into the selected project’s .venv. Ubuntu packages use APT and may ask for your sudo password in the terminal. Package names are not a guarantee of trust or suitability.')
        self.package_path = QLabel(str(self.workspace))
        self.package_path.setWordWrap(True)
        box.addWidget(self.package_path)
        box.addWidget(self.small_button('Choose project…', self.choose_workspace))
        self.package_kind = QComboBox()
        self.package_kind.addItems(['Python / project .venv', 'Ubuntu / APT'])
        box.addWidget(self.package_kind)
        self.package_presets = QComboBox()
        box.addWidget(self.package_presets)
        box.addWidget(self.small_button('Use selected package set', lambda: self.package_input.setText(self.package_presets.currentData() or '')))
        self.package_input = QLineEdit()
        self.package_input.setPlaceholderText('Package names separated by spaces')
        box.addWidget(self.package_input)
        self.package_preview = QLabel()
        self.package_preview.setWordWrap(True)
        self.package_preview.setObjectName('path')
        box.addWidget(self.package_preview)
        self.package_input.textChanged.connect(self.preview_package)
        self.package_kind.currentIndexChanged.connect(self.refresh_package_presets)
        self.package_install = self.small_button('Install selected packages', self.install_packages)
        self.action_buttons.append(self.package_install)
        box.addWidget(self.package_install)
        box.addWidget(self.small_button('Review APT index refresh in Terminal', lambda: self.stage('sudo -- apt-get update')))
        keyboard = MouseKeyboard(self.terminal, self.package_input)
        keyboard.target.setItemText(1, 'Edit package names')
        keyboard.target.setCurrentIndex(1)
        box.addWidget(keyboard)
        self.refresh_package_presets()
        self.refresh_project_views()

    def refresh_package_presets(self, *args):
        self.package_presets.clear()
        choices = ([('Python tests', 'pytest'), ('Numerical tools', 'numpy scipy'),
                    ('Plots and images', 'matplotlib pillow'), ('Game prototyping', 'pygame')]
                   if self.package_kind.currentIndex() == 0 else
                   [('Python essentials', 'python3-venv python3-pip git'),
                    ('C++ build tools', 'build-essential cmake pkg-config'),
                    ('Rust / Ubuntu packages', 'rustc cargo'), ('Terminal tools', 'nano htop tree')])
        for label, value in choices:
            self.package_presets.addItem(label, value)
        self.preview_package()

    def preview_package(self, *args):
        try:
            args = package_command(self.workspace, self.package_input.text(), self.package_kind.currentIndex() == 0)
            self.package_preview.setText(shlex.join(args))
        except ValueError as exc:
            self.package_preview.setText(str(exc))

    def install_packages(self):
        try:
            python = self.package_kind.currentIndex() == 0
            args = package_command(self.workspace, self.package_input.text(), python)
        except ValueError as exc:
            self.show_error(exc)
            return
        answer = QMessageBox.question(self, 'Review package installation',
            f'Project: {self.workspace}\n\n{shlex.join(args)}\n\n' +
            ('Install into this project’s virtual environment?' if python else
             'Prepare this in the terminal? Click Send text and ENTER when Bash is idle. APT will ask before installation.'))
        if answer == QMessageBox.StandardButton.Yes:
            if python:
                self.run('Install Python packages', args[0], args[1:])
            else:
                self.stage(staged_command(self.workspace, args))

    def start_terminal(self):
        try:
            self.terminal.start_shell(self.workspace)
        except OSError as exc:
            self.terminal_status.setText(f'SHELL START FAILED / {exc}')

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 3:
            self.start_terminal()
        if hasattr(self, 'console'):
            self.show_activity(index not in (3, 4, 6))

    def show_activity(self, visible):
        self.console.setVisible(visible)
        self.activity_caption.setVisible(visible)
        self.cursor.setVisible(visible)
        if hasattr(self, 'activity_toggle'):
            self.activity_toggle.setChecked(visible)

    def choose_workspace(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose Ubuntu project folder', str(self.workspace))
        if folder:
            self.set_workspace(Path(folder))

    def set_workspace(self, folder):
        self.workspace = Path(folder)
        self.settings.setValue('workspace', str(folder))
        self.path_label.setText(str(folder))
        self.refresh_project_views()
        self.log(f'Workspace selected: {folder}')

    def log(self, text):
        self.stream(f'\n[{datetime.now():%H:%M:%S}] > {text}\n')

    def stream(self, text):
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def launch(self, name, program, args):
        resolved = shutil.which(program)
        if not resolved:
            self.log(f'LAUNCH FAILED / {name}: command not found: {program}')
            return
        process = QProcess()
        process.setProgram(resolved)
        process.setArguments(args)
        process.setWorkingDirectory(str(self.workspace))
        good, pid = process.startDetached()
        self.log(f'Launch request dispatched / {name}. App readiness is not verified.' if good
                 else f'LAUNCH FAILED / {name}: {process.errorString()}')

    def open_folder(self, folder):
        if not folder.is_dir():
            self.log(f'OPEN FAILED / folder not found: {folder}')
            return
        self.run('Open folder in Windows Explorer', 'wslpath', ['-w', str(folder)], open_result=True)

    def run(self, title, program, args, open_result=False):
        if self.runner.active:
            self.log('BUSY / wait for the current command to finish.')
            return
        self.folder_result = '' if open_result else None
        self.log(f'START / {title}')
        self.show_activity(True)
        self.progress.setRange(0, 0)
        self.status.setText('RUNNING / progress is not measured')
        for button in self.action_buttons:
            button.setEnabled(False)
        self.runner.start(program, args, self.workspace)

    def observe(self):
        self.run('Read system state', sys.executable, ['-u', str(Path(__file__).resolve()), '--report'])

    def clean_cache(self):
        answer = QMessageBox.question(self, 'Prepare APT cleanup?', 'Copy sudo -- apt-get clean and open the terminal?\n\nPaste the command at a Bash prompt to remove cached package downloads. Installed packages stay installed. Enter your sudo password in the terminal if asked.')
        if answer == QMessageBox.StandardButton.Yes:
            QApplication.clipboard().setText('sudo -- apt-get clean')
            self.navigate(3)
            self.terminal_status.setText('CLEANUP PREPARED / paste at a Bash prompt with Ctrl+Shift+V, then Enter')
            self.log('APT cleanup command copied. Not executed: paste at an idle Bash prompt to run it.')

    def completed(self, good, detail):
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status.setText(('COMPLETED' if good else 'FAILED') + ' / ' + detail)
        self.log(('COMPLETED' if good else 'FAILED') + ' / ' + detail)
        for button in self.action_buttons:
            button.setEnabled(True)
        if self.folder_result is not None:
            result = self.folder_result.strip()
            self.folder_result = None
            if good and result:
                self.launch('Windows Explorer', 'explorer.exe', [result])

    def capture_folder_path(self, text):
        if self.folder_result is not None:
            self.folder_result += text

    def blink(self):
        self.phase = not self.phase
        self.cursor.setText(('RUNNING' if self.runner.active else 'IDLE') + (' ▌' if self.phase else '  '))

    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(self, 'Save activity', str(Path.home() / 'rootslaw-activity.txt'), 'Text files (*.txt)')
        if filename:
            try:
                Path(filename).write_text(self.console.toPlainText(), encoding='utf-8')
                self.log(f'Activity saved: {filename}')
            except OSError as exc:
                self.log(f'SAVE FAILED / {exc}')

    def closeEvent(self, event):
        if self.runner.active:
            QMessageBox.information(self, 'Operation running', 'Wait for the current operation to finish before closing.')
            event.ignore()
        else:
            if self.terminal and self.terminal.child and self.terminal.child.poll() is None:
                answer = QMessageBox.question(self, 'Close terminal session?',
                    'Closing the panel ends its Bash session and may stop commands running in it. Close now?')
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            if self.terminal:
                self.terminal.stop_shell()
            event.accept()


def main():
    if '--terminal-child' in sys.argv:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.chdir(sys.argv[sys.argv.index('--terminal-child') + 1])
        os.execv('/bin/bash', ['/bin/bash', '-i'])
    if '--report' in sys.argv:
        system_report()
        return
    app = QApplication(sys.argv)
    app.setApplicationName('RootsUbuntuInterface')
    app.setOrganizationName('Root-Law')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    panel = Panel()
    panel.show()
    if '--page' in sys.argv:
        panel.navigate(int(sys.argv[sys.argv.index('--page') + 1]))
    if '--preview' in sys.argv:
        destination = sys.argv[sys.argv.index('--preview') + 1]
        if '--terminal-preview' in sys.argv:
            panel.navigate(3)
            if '--mouse-preview' in sys.argv:
                panel.keyboard.show()
            def capture():
                panel.grab().save(destination)
                panel.terminal.stop_shell()
                app.quit()
            QTimer.singleShot(650, capture)
        else:
            QTimer.singleShot(250, lambda: (panel.grab().save(destination), app.quit()))
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
