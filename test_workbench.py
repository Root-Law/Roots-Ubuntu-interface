from pathlib import Path
import json
import os
import subprocess
import pytest
from workbench import CommandBook, package_command, package_names, staged_command, developer_commands
from setup_launcher import install_launchers, desktop_quote

def test_saved_keys_survive_restart_update_and_delete(tmp_path):
    path = tmp_path / 'commands.json'
    book = CommandBook(path)
    saved = book.upsert('Tests', '.venv/bin/python -m pytest -q')
    assert CommandBook(path).load() == [saved]
    updated = book.upsert('All tests', '.venv/bin/python -m pytest', saved['id'])
    assert len(book.load()) == 1 and book.load()[0] == updated
    assert path.stat().st_mode & 0o777 == 0o600
    book.delete(saved['id'])
    assert book.load() == []

@pytest.mark.parametrize('command', ['echo ok\nrm x', 'echo\x1btest', '\tpython'])
def test_saved_key_rejects_control_characters(tmp_path, command):
    with pytest.raises(ValueError):
        CommandBook(tmp_path / 'commands.json').upsert('Key', command)

def test_corrupt_command_file_is_not_overwritten(tmp_path):
    path = tmp_path / 'commands.json'
    path.write_text('not JSON')
    with pytest.raises(ValueError):
        CommandBook(path).upsert('Key', 'pwd')
    assert path.read_text() == 'not JSON'

@pytest.mark.parametrize('text', ['--upgrade', 'pytest;touch /tmp/x', '$(whoami)', 'https://example.com/x', ''])
def test_package_input_rejects_options_urls_and_shell_syntax(text):
    with pytest.raises(ValueError):
        package_names(text, python=True)

def test_python_installs_only_into_valid_project_environment(tmp_path):
    with pytest.raises(ValueError, match='Create'):
        package_command(tmp_path, 'pytest', python=True)
    python = tmp_path / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.touch()
    with pytest.raises(ValueError, match='pyvenv.cfg'):
        package_command(tmp_path, 'pytest', python=True)
    (tmp_path / '.venv/pyvenv.cfg').write_text('home = /usr/bin')
    assert package_command(tmp_path, 'pytest==9.0.0 numpy', True) == [str(python), '-m', 'pip', 'install', 'pytest==9.0.0', 'numpy']

def test_apt_requires_sudo_and_preserves_names_as_arguments(tmp_path):
    assert package_command(tmp_path, 'build-essential cmake') == ['sudo', '--', 'apt-get', 'install', '--', 'build-essential', 'cmake']
    with pytest.raises(ValueError):
        package_command(tmp_path, 'git && whoami')

def test_project_paths_with_spaces_and_shell_punctuation_are_quoted(tmp_path):
    folder = tmp_path / 'project space; not-a-command'
    folder.mkdir()
    command = staged_command(folder, ['python3', '-c', 'print("correct project")'])
    result = subprocess.run(['/bin/bash', '-c', command], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'correct project'

def test_desktop_and_cli_launcher_handle_spaces(tmp_path):
    project = tmp_path / 'project with spaces'
    project.mkdir()
    (project / 'launch.sh').write_text('#!/bin/bash\nprintf "launched:%s" "$1"\n')
    home = tmp_path / 'user home'
    desktop, cli = install_launchers(project, tmp_path / 'data', home)
    assert 'Name=Roots Ubuntu Interface' in desktop.read_text()
    assert str(project / 'launch.sh') in desktop.read_text()
    result = subprocess.run([str(cli), 'one argument'], text=True, capture_output=True)
    assert result.returncode == 0 and result.stdout == 'launched:one argument'
    assert desktop_quote('100% $root') == '"100%% \\$root"'

def test_installer_and_launcher_parse():
    root = Path(__file__).parent
    assert subprocess.run(['bash', '-n', str(root / 'install.sh'), str(root / 'launch.sh')]).returncode == 0

def test_developer_pytest_actions_use_project_venv(tmp_path):
    commands = dict(developer_commands(tmp_path))
    assert commands['Run pytest'] == [str(tmp_path / '.venv/bin/python'), '-m', 'pytest', '-q']
    assert commands['Cargo tests'] == ['cargo', 'test']

def test_nano_command_handles_spaces_and_quotes(tmp_path):
    from workbench import nano_command
    path = tmp_path / "some file's name.py"
    path.write_text('print(1)')
    args = nano_command(path)
    assert args == ['nano', '--', str(path)]
    command = staged_command(tmp_path, args)
    import shlex
    assert shlex.split(command)[-3:] == args
    with pytest.raises(ValueError):
        nano_command(tmp_path / 'missing.py')

def test_git_mutations_are_reviewed_and_push_targets_only_head():
    from workbench import git_actions
    actions = {label: (args, review) for label, args, review in git_actions()}
    assert actions['Pull / fast-forward only'] == (['git', 'pull', '--ff-only', '--no-rebase'], True)
    assert actions['Status'][1] is False
    assert actions['Stage all changes'][1] is True
    assert actions['Push current branch'] == (['git', 'push', 'origin', 'HEAD'], True)
    assert not any('--force' in args for args, _ in actions.values())

def test_git_message_and_branch_input_stays_literal(tmp_path):
    from workbench import git_text_command
    message = 'fix "quotes"; $(do-not-run)'
    assert git_text_command('commit', message) == ['git', 'commit', '-m', message]
    assert git_text_command('new_branch', 'feature/nano-files') == ['git', 'switch', '-c', 'feature/nano-files']
    for name in ('-force', 'bad name', 'bad..branch', '../outside', 'branch\nnext'):
        with pytest.raises(ValueError):
            git_text_command('switch_branch', name)
    assert git_text_command('clone', 'https://github.com/Root-Law/Roots-Ubuntu-interface.git')[-1].endswith('.git')
    with pytest.raises(ValueError):
        git_text_command('clone', 'ext::sh -c unsafe')
    with pytest.raises(ValueError):
        git_text_command('clone', 'https://token@github.com/root/repo.git')
