"""-l should never start a normal search just because the shortcut isn't multi."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import tas


@pytest.mark.parametrize('mode', ['auto', 'goal', 'local', 'both', 'hybrid',
                                  'random', 'multi', 'merge', 'repair'])
def test_any_shortcut_routes_l_to_read_only_user_splice_summary(tmp_path, monkeypatch, mode):
    root = tmp_path / 'optimiser'
    root.mkdir()
    route = tmp_path / 'splices' / '01-0' / 'multi-splicer.toml'
    route.parent.mkdir(parents=True)
    route.write_text('[multi-splicer]\nsplice-files=["100","end"]\n')
    monkeypatch.setattr(tas, 'ROOT', root)
    command = tas.build_command(mode, '01-0', env={}, extra=['-l'])
    assert command[2:4] == ['auto', '../n_levels/01-0.ltm']
    assert '--splice-config' in command
    assert command[command.index('--splice-config')+1].endswith('/multi-splicer.toml')
    assert '--auto-runs' not in command
    assert '--goal-config' not in command
    assert '--stagnation-rounds' not in command
    assert '--splice-merge-repair-only' not in command
    assert command[-1] == '-l'


def test_list_shortcut_never_creates_work_files_or_publishes(tmp_path, monkeypatch):
    root = tmp_path / 'optimiser'
    root.mkdir()
    route = tmp_path / 'splices' / '01-0' / 'multi-splicer.toml'
    route.parent.mkdir(parents=True)
    route.write_text('[multi-splicer]\nsplice-files=["end"]\n')
    monkeypatch.setattr(tas, 'ROOT', root)
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(tas.subprocess, 'run', run)
    assert tas.main(['local', '01-0', '-l'], env={}) == 0
    assert len(commands) == 1
    assert commands[0][2] == 'auto'
    assert not (root / 'wip').exists()


def test_list_requires_route_instead_of_falling_back_to_search(tmp_path, monkeypatch):
    monkeypatch.setattr(tas, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='requires a multi-splicer.toml'):
        tas.build_command('auto', '01-0', env={}, extra=['-l'])
    with pytest.raises(ValueError, match='requires a multi-splicer.toml'):
        tas.build_command('local', '01-0', env={}, extra=['-l'])
