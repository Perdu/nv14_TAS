"""Color is shared by every optimisation strategy; only new bests are green."""
from __future__ import annotations

from nv14_cli import CommonConfig, _print_best_line, parse_arguments


def test_color_enabled_by_default_on_every_optimisation_mode():
    for mode in ("auto", "local", "jump-pattern"):
        args = parse_arguments([mode, "input.txt"])
        assert args.color is True
        assert CommonConfig.from_namespace(args).color is True
        assert parse_arguments([mode, "input.txt", "--no-color"]).color is False
        assert parse_arguments([mode, "input.txt", "--color"]).color is True


def test_common_toml_color_and_cli_override(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text("[common]\ncolor = false\n", encoding="utf-8")
    for mode in ("auto", "local", "jump-pattern"):
        assert parse_arguments([mode, "input.txt", "--config", str(config)]).color is False
        assert parse_arguments([mode, "input.txt", "--config", str(config), "--color"]).color is True
    config.write_text("[common]\ncolor = true\n", encoding="utf-8")
    assert parse_arguments(["auto", "input.txt", "--config", str(config), "--no-color"]).color is False


def test_mode_toml_can_override_color(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text("[common]\ncolor = true\n[local]\ncolor = false\n", encoding="utf-8")
    assert parse_arguments(["local", "input.txt", "--config", str(config)]).color is False
    assert parse_arguments(["auto", "input.txt", "--config", str(config)]).color is True


def test_best_line_has_green_prefix_and_reset_only_if_enabled(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    _print_best_line("[local:best] a better result", color=True)
    assert capsys.readouterr().out == "\x1b[32m[local:best] a better result\x1b[0m\n"
    _print_best_line("[local:best] a better result", color=False)
    assert capsys.readouterr().out == "[local:best] a better result\n"


def test_noninteractive_output_remains_ansi_free(capsys):
    _print_best_line("[auto:checkpoint] saved best #1", color=True)
    assert capsys.readouterr().out == "[auto:checkpoint] saved best #1\n"
