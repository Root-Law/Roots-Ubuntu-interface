# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent command keys and validated package requests; no execution here."""
from pathlib import Path
import json
import os
import re
import shlex
import tempfile
import uuid
from urllib.parse import urlsplit

class CommandBook:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, list) or len(data) > 100:
            raise ValueError('Invalid command file: expected at most 100 saved commands.')
        for item in data:
            if not isinstance(item, dict) or set(item) != {'id', 'label', 'command'}:
                raise ValueError('Invalid saved command fields.')
            self.validate(item['label'], item['command'])
            if not isinstance(item['id'], str) or not item['id']:
                raise ValueError('Invalid command identifier.')
        if len({item['id'] for item in data}) != len(data):
            raise ValueError('Duplicate command identifiers.')
        return data

    @staticmethod
    def validate(label, command):
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError('Use a button name between 1 and 80 characters.')
        if not isinstance(command, str) or not command.strip() or len(command) > 8000:
            raise ValueError('Use a command between 1 and 8000 characters.')
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in label + command):
            raise ValueError('Saved commands must be one line with no control characters.')

    def save(self, items):
        if len(items) > 100:
            raise ValueError('Maximum 100 saved commands.')
        for item in items:
            self.validate(item['label'], item['command'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.commands-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(items, stream, indent=2, ensure_ascii=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def upsert(self, label, command, identifier=None):
        self.validate(label, command)
        items = self.load()
        item = {'id': identifier or uuid.uuid4().hex, 'label': label.strip(), 'command': command.strip()}
        if identifier:
            matches = [i for i, old in enumerate(items) if old['id'] == identifier]
            if not matches:
                raise ValueError('The selected saved command no longer exists.')
            items[matches[0]] = item
        else:
            items.append(item)
        self.save(items)
        return item

    def delete(self, identifier):
        self.save([item for item in self.load() if item['id'] != identifier])


def package_names(text, python=False):
    names = text.split()
    if not names or len(names) > 25:
        raise ValueError('Enter between 1 and 25 package names, separated by spaces.')
    pattern = (r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:==[A-Za-z0-9][A-Za-z0-9.+_-]*)?'
               if python else r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?')
    if any(not re.fullmatch(pattern, name) for name in names):
        raise ValueError('Use package names only. Python also accepts name==version. Options, URLs and shell punctuation are not supported.')
    return names


def project_python(workspace):
    path = Path(workspace) / '.venv/bin/python'
    if not path.is_file():
        raise ValueError('Create the selected project’s .venv first on the Developer page.')
    # Confirm it is a venv, not a lone binary placed at this path.
    if not (Path(workspace) / '.venv/pyvenv.cfg').is_file():
        raise ValueError('This .venv is missing pyvenv.cfg; select a valid project environment.')
    return str(path)


def package_command(workspace, text, python=False):
    names = package_names(text, python)
    if python:
        return [project_python(workspace), '-m', 'pip', 'install', *names]
    return ['sudo', '--', 'apt-get', 'install', '--', *names]


def staged_command(workspace, arguments):
    return 'cd -- ' + shlex.quote(str(workspace)) + ' && ' + shlex.join(arguments)


def developer_commands(workspace):
    venv = str(Path(workspace) / '.venv/bin/python')
    return [
        ('Python version', ['python3', '--version']),
        ('Create project .venv', ['python3', '-m', 'venv', '.venv']),
        ('Run pytest', [venv, '-m', 'pytest', '-q']),
        ('List collected tests', [venv, '-m', 'pytest', '--collect-only', '-q']),
        ('Stop at first test failure', [venv, '-m', 'pytest', '-x', '-q']),
        ('Repeat last failed tests', [venv, '-m', 'pytest', '--lf', '-q']),
        ('List Python packages', [venv, '-m', 'pip', 'list']),
        ('C++ compiler version', ['g++', '--version']),
        ('Configure CMake build', ['cmake', '-S', '.', '-B', 'build']),
        ('Build CMake project', ['cmake', '--build', 'build']),
        ('Rust compiler version', ['rustc', '--version']),
        ('Cargo check', ['cargo', 'check']),
        ('Cargo tests', ['cargo', 'test']),
        ('Cargo formatting check', ['cargo', 'fmt', '--check']),
    ]


def nano_command(filename):
    path = Path(filename).absolute()
    if not path.is_file():
        raise ValueError('Choose an existing file to open in nano.')
    if any(ord(char) < 32 or ord(char) == 127 for char in str(path)):
        raise ValueError('This file name contains control characters and cannot be loaded into the command draft.')
    return ['nano', '--', str(path)]


def git_actions():
    """False means show information; True means review in terminal before running."""
    return [
        ('Status', ['git', '--no-optional-locks', 'status', '--short', '--branch'], False),
        ('Current branch', ['git', 'branch', '--show-current'], False),
        ('List branches', ['git', '--no-pager', 'branch', '-a'], False),
        ('Recent commits', ['git', '--no-pager', 'log', '--oneline', '-n', '10'], False),
        ('Unstaged changes', ['git', '--no-pager', 'diff', '--stat'], False),
        ('Staged changes', ['git', '--no-pager', 'diff', '--cached', '--stat'], False),
        ('Remote addresses', ['git', 'remote', '-v'], False),
        ('Repository folder', ['git', 'rev-parse', '--show-toplevel'], False),
        ('Pull / fast-forward only', ['git', 'pull', '--ff-only', '--no-rebase'], True),
        ('Fetch remote updates', ['git', 'fetch', '--prune'], True),
        ('Stage all changes', ['git', 'add', '--all'], True),
        ('Initialize Git here', ['git', 'init'], True),
        ('Push current branch', ['git', 'push', 'origin', 'HEAD'], True),
        ('First push / set upstream', ['git', 'push', '-u', 'origin', 'HEAD'], True),
    ]


def git_text_command(action, text):
    text = text.strip()
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError('Enter one line of text for this action.')
    if action in ('new_branch', 'switch_branch'):
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]*', text)
                or '..' in text or '//' in text
                or any(part.startswith('.') or part.endswith(('.', '.lock')) for part in text.split('/'))
                or text.endswith('/')):
            raise ValueError('Use a branch name such as feature/my-work, without spaces, control characters or leading dashes.')
        return ['git', 'switch', '-c', text] if action == 'new_branch' else ['git', 'switch', '--', text]
    if action == 'commit':
        return ['git', 'commit', '-m', text]
    if action == 'clone':
        parsed = urlsplit(text)
        https = parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password
        ssh = parsed.scheme == 'ssh' and parsed.hostname and not parsed.password
        scp = re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+', text)
        if not (https or ssh or scp) or any(char.isspace() for char in text):
            raise ValueError('Use an HTTPS or SSH repository URL without an embedded password/token.')
        return ['git', 'clone', '--', text]
    raise ValueError('Unknown Git text action.')
