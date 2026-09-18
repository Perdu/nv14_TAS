"""Bundled launch paths, cache policy and comparison-encoder integration."""
from dataclasses import dataclass
from functools import wraps
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tools import encode_leaderboard_ghosts as ghosts


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "encode_leaderboard_ghosts.py"
LEVEL = "0" * 713 + "|5^100,100"
DEMO = "3:0"


def board(mode):
    if mode == "speedrun":
        return ('<table><tr><td>88</td><td>4</td><td>'
                '<a href="get_lv_demo_only_speedrun.php?pk=17">3</a></td>'
                '<td>1</td><td>A+B%Player</td></tr></table>')
    return ("results=1&4name0=jc239&4score0=20000&4pkey0=9&4epnum0=88&4levnum0=4"
            "&4name1=A+B%Player&4score1=10000&4pkey1=17&4epnum1=88&4levnum1=4")


def response(mode):
    return DEMO if mode == "speedrun" else f"results=1&name=A+B%Player&score=10000&demo={DEMO}"


def cache_files(root, mode):
    folder = root / "highscore" / "88-4" if mode == "highscore" else root / "88-4"
    return (folder, folder / ("leaderboard.txt" if mode == "highscore" else "leaderboard.html"),
            folder / ("demo_17.response.txt" if mode == "highscore" else "demo_17.txt"))


def seed_cache(root, mode, *, replay=True):
    folder, board_path, response_path = cache_files(root, mode)
    folder.mkdir(parents=True, exist_ok=True)
    board_path.write_text(board(mode), encoding="utf-8")
    if replay:
        response_path.write_text(response(mode), encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Unexpected network request")
    monkeypatch.setattr(ghosts, "fetch", fail)
    # Import discovery must not leak sys.path changes into other tests.
    monkeypatch.setattr(sys, "path", list(sys.path))


@pytest.mark.parametrize("mode", ["speedrun", "highscore"])
def test_offline_download_only_needs_no_site_packages_from_foreign_cwd(tmp_path, mode):
    folder = seed_cache(tmp_path / "leaderboard_ghost_cache", mode)
    # -I ignores inherited PYTHONPATH, -S removes installed dependencies.
    result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT),
                             "--download-only", "--offline", "--mode", mode],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((folder / "selection.json").read_text())
    assert manifest["download_policy"] == "offline"
    assert manifest["actual_count"] == 1
    assert manifest["ghosts"][0]["player"] == "A+B%Player"
    assert (folder / "demo_17.txt").read_text().strip() == DEMO
    if mode == "highscore":
        assert manifest["excluded_entries"][0]["player"] == "jc239"


@pytest.mark.parametrize("mode", ["speedrun", "highscore"])
@pytest.mark.parametrize("policy,existing,expected", [
    ([], "all", 0), ([], "board", 1), ([], "none", 2),
    (["--online"], "all", 2), (["--refresh"], "all", 2),
])
def test_download_policy_preserves_cache_first_and_explicit_refresh(
        tmp_path, monkeypatch, mode, policy, existing, expected):
    cache = tmp_path / "downloads"
    if existing != "none":
        seed_cache(cache, mode, replay=existing == "all")
    calls = []

    def fetch(url, timeout, delay, form=None):
        calls.append((url, form))
        return board(mode) if "topscores" in url or "lv_speedrun.php" in url else response(mode)

    monkeypatch.setattr(ghosts, "fetch", fetch)
    assert ghosts.main(["--download-only", "--cache-dir", str(cache), "--mode", mode, *policy]) == 0
    assert len(calls) == expected
    folder, _, _ = cache_files(cache, mode)
    manifest = json.loads((folder / "selection.json").read_text())
    assert manifest["download_policy"] == ("online" if policy else "cache-first")
    if mode == "highscore" and calls:
        assert calls[-1][1] == {"pk": "17"}
        if expected == 2:
            assert calls[0][1] == {"episode_number": 88}


@pytest.mark.parametrize("mode", ["speedrun", "highscore"])
@pytest.mark.parametrize("missing", ["board", "replay"])
def test_offline_missing_files_fail_without_fetch(tmp_path, mode, missing):
    if missing == "replay":
        seed_cache(tmp_path, mode, replay=False)
    with pytest.raises(FileNotFoundError, match="Offline cache missing"):
        ghosts.main(["--download-only", "--offline", "--mode", mode, "--cache-dir", str(tmp_path)])


def test_highscore_exclusions_are_additive_offline_and_count_is_up_to_slots(tmp_path, capsys):
    folder = seed_cache(tmp_path, "highscore")
    args = ["--download-only", "--offline", "--mode", "highscore", "--cache-dir", str(tmp_path)]
    assert ghosts.main([*args, "--count", "20"]) == 0
    assert "using 1 eligible" in capsys.readouterr().err
    assert json.loads((folder / "selection.json").read_text())["requested_count"] == 20
    exclusions = tmp_path / "excluded.txt"
    exclusions.write_text("\ufeff# Comment\n\n  a+b%player  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="No eligible highscore runs"):
        ghosts.main([*args, "--exclude-players-file", str(exclusions)])
    with pytest.raises(ValueError, match="No eligible highscore runs"):
        ghosts.main([*args, "--exclude-player", "A+B%PLAYER"])


def test_speedrun_count_is_strict_and_mismatched_replays_are_rejected(tmp_path):
    folder = seed_cache(tmp_path, "speedrun")
    args = ["--download-only", "--offline", "--cache-dir", str(tmp_path)]
    with pytest.raises(ValueError, match="requested 2"):
        ghosts.main([*args, "--count", "2"])
    (folder / "demo_17.txt").write_text("2:0")
    with pytest.raises(ValueError, match="Leaderboard says 3 frames"):
        ghosts.main(args)


@pytest.mark.parametrize("body", ["results=1&name=Other&score=10000&demo=3:0",
                                      "results=1&name=A+B%Player&score=9999&demo=3:0"])
def test_highscore_response_mismatch_is_not_silently_reused(tmp_path, body):
    folder = seed_cache(tmp_path, "highscore")
    (folder / "demo_17.response.txt").write_text(body)
    with pytest.raises(ValueError, match="Replay/leaderboard mismatch"):
        ghosts.main(["--download-only", "--offline", "--mode", "highscore", "--cache-dir", str(tmp_path)])


@pytest.mark.parametrize("copied", [False, True])
def test_source_discovery_and_explicit_override_in_isolated_python(tmp_path, copied):
    script = SCRIPT
    if copied:
        script = tmp_path / SCRIPT.name
        shutil.copyfile(SCRIPT, script)
        shutil.copyfile(ROOT / "nv14_video.py", tmp_path / "nv14_video.py")
    override = tmp_path / "override"
    override.mkdir()
    (override / "nv14_video.py").write_text("MARKER = 'explicit'\n")
    code = ("import json, runpy, sys; "
            "ns=runpy.run_path(sys.argv[1]); "
            "root=ns['configure_optimizer_path'](sys.argv[2] if len(sys.argv)>2 else None); "
            "print(json.dumps({'root': str(root), 'first': sys.path[0]}))")
    for args, expected in (([], tmp_path if copied else ROOT), ([str(override)], override)):
        result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(script), *args],
                                cwd=tmp_path, capture_output=True, text=True, timeout=20, check=True)
        assert json.loads(result.stdout) == {"root": str(expected), "first": str(expected)}


@pytest.fixture
def fake_encoder(monkeypatch):
    pytest.importorskip("PIL")
    import nv14_native
    import nv14_video as video
    calls = []

    @dataclass
    class Result:
        output_path: Path
        duration_seconds: float = .1
        render_workers: int = 8
        render_quality: str = "fast"
        replays: tuple = ()
        timings: dict | None = None

    @wraps(video.encode_replay_video)
    def encode(source, output, **kwargs):
        calls.append((source, output, kwargs))
        return Result(output, timings={"total_seconds": .1} if kwargs["profile"] else None)

    monkeypatch.setattr(video, "encode_replay_video", encode)
    monkeypatch.setattr(video, "_find_ffmpeg", lambda path: "ffmpeg")
    monkeypatch.setattr(nv14_native, "require_native", lambda: SimpleNamespace(
        NativeState=SimpleNamespace(capture_visual_frames=True)))
    return calls


@pytest.mark.parametrize("packed", [False, True])
def test_primary_loading_encoder_options_without_report(tmp_path, monkeypatch, fake_encoder, packed, capsys):
    monkeypatch.chdir(tmp_path)
    seed_cache(tmp_path / "leaderboard_ghost_cache", "speedrun")
    primary = tmp_path / "primary.txt"
    primary.write_text(DEMO if packed else f"$My map#Author##{LEVEL}#{DEMO}#")
    old_report = tmp_path / "88-4_TAS_top1_exit.ghosts.json"
    if packed:
        old_report.write_text("existing report from an earlier release\n")
    args = [primary.name, "--offline", "--label-position", "top-left",
            "--secondary-gold", "animated", "--profile", "--render-memory-mib", "64",
            "--replay-cache-dir", "pose_cache", "--alignment", "exit"]
    if packed:
        (tmp_path / "levels.txt").write_text(f"$88-4 My map#Author##{LEVEL}#")
        args += ["--levels-file", "levels.txt", "--no-progress"]
    assert ghosts.main(args) == 0
    source, output, options = fake_encoder[0]
    assert source == Path("primary.txt")
    assert output == tmp_path / "88-4_TAS_top1_exit.mp4"
    assert options["secondary_replays"] == [tmp_path / "leaderboard_ghost_cache/88-4/demo_17.txt"]
    assert options["secondary_labels"] == ["A+B%Player - 3 f"]
    assert options["primary_label"] == "TAS - 3 f"
    assert options["scale"] == 2 and options["render_workers"] == 8
    assert options["render_quality"] == "fast" and options["preset"] == "medium"
    assert options["secondary_gold"] == "animated" and options["replay_alignment"] == "exit"
    assert options["profile"] and options["render_memory_mib"] == 64
    assert options["progress"] is (not packed)
    assert options["replay_cache_dir"] == Path("pose_cache")
    assert options.get("level_id") == ("88-4" if packed else None)
    if packed:
        assert old_report.read_text() == "existing report from an earlier release\n"
    else:
        assert not old_report.exists()
    selection = json.loads((tmp_path / "leaderboard_ghost_cache/88-4/selection.json").read_text())
    assert selection["primary_score_frames"] == 3
    assert "encoding" not in selection and "render_options" not in selection
    console = capsys.readouterr().out
    assert 'performance: {"total_seconds": 0.1}' in console
    assert ".ghosts.json" not in console and "details:" not in console


@pytest.mark.parametrize("destination", ["leaderboard_ghost_cache/other-level/out.mp4", "excluded.mp4"])
def test_output_protection_runs_before_download(tmp_path, monkeypatch, fake_encoder, destination):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "primary.txt").write_text(f"$My map#Author##{LEVEL}#{DEMO}#")
    (tmp_path / "excluded.mp4").write_text("# exclusion input\n")
    with pytest.raises(SystemExit) as exc:
        ghosts.main(["primary.txt", "--mode", "highscore", "--exclude-players-file",
                     "excluded.mp4", "-o", destination])
    assert exc.value.code == 2
    assert not fake_encoder
    assert (tmp_path / "excluded.mp4").read_text() == "# exclusion input\n"


@pytest.mark.parametrize("position", ["follow", "top-left"])
def test_remote_labels_fit_encoder_contract_without_losing_score(position):
    from nv14_render import validate_player_label
    label = ghosts.score_label("Name\n\t" + "x" * 150, 10000, position, "highscore")
    validate_player_label(label)
    assert len(label) == 128
    if position == "top-left":
        assert label.endswith(" - 250.000 s")


@pytest.mark.parametrize("args", [["--timeout", "nan"], ["--request-delay", "inf"],
                                  ["--render-memory-mib", "15"], ["--online", "--offline"]])
def test_invalid_options_fail_before_download(args):
    with pytest.raises(SystemExit) as exc:
        ghosts.main(["--download-only", *args])
    assert exc.value.code == 2
