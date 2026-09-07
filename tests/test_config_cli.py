# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import os
import sys

import pytest

from kolint.cli import main
from kolint.config import find_config, load_config
from kolint.core import expand_selector, resolve_selection
from kolint.engine import build_rules, run
from kolint.core import Segment

pytest.importorskip("tomllib") if sys.version_info >= (3, 11) else pytest.importorskip("tomli")

CONFIG = """
[kolint]
extend-select = ["KO004"]
ignore = ["KO401"]
exit-level = "error"
records = "[].strings[]"

[kolint.KO006]
terms = ["성직자", "코볼드"]

[kolint.KO302.speakers]
Archivist = "formal"
Scout = "casual"

[kolint.KO102]
allow_han = true
"""


def test_load_config(tmp_path):
    p = tmp_path / "kolint.toml"
    p.write_text(CONFIG, encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.extend_select == ["KO004"]
    assert cfg.ignore == ["KO401"]
    assert cfg.exit_level == "error"
    assert cfg.records == "[].strings[]"
    assert cfg.options_for("KO006")["terms"] == ["성직자", "코볼드"]
    assert cfg.options_for("KO302")["speakers"]["Archivist"] == "formal"
    assert cfg.options_for("KO102")["allow_han"] is True


def test_config_drives_rule_selection(tmp_path):
    p = tmp_path / "kolint.toml"
    p.write_text(CONFIG, encoding="utf-8")
    cfg = load_config(str(p))
    codes = [r.code for r in build_rules(cfg)]
    assert "KO004" in codes      # extend-select
    assert "KO401" not in codes  # ignore
    assert "KO006" in codes      # needs_config, and config is present
    assert "KO007" not in codes  # opt-in, not selected


def test_config_reaches_the_rules(tmp_path):
    p = tmp_path / "kolint.toml"
    p.write_text(CONFIG, encoding="utf-8")
    rules = build_rules(load_config(str(p)))
    # KO006 knows the glossary...
    assert run([Segment(target="성직자을 만났다.")], rules)
    # ...and KO102 was told 한자 is allowed.
    han = [d for d in run([Segment(target="도쿄(東京)", source="Tokyo")], rules)
           if d.code == "KO102"]
    assert not han


def test_find_config_walks_up(tmp_path):
    (tmp_path / "kolint.toml").write_text("[kolint]\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    cwd = os.getcwd()
    try:
        os.chdir(str(nested))
        assert find_config() == str(tmp_path / "kolint.toml")
    finally:
        os.chdir(cwd)


def test_missing_config_is_not_an_error(tmp_path):
    cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        cfg = load_config()
        assert cfg.path is None
        assert cfg.select is None
    finally:
        os.chdir(cwd)


def test_bad_speech_level_in_config_is_reported(tmp_path, capsys):
    (tmp_path / "bad.toml").write_text(
        '[kolint.KO302.speakers]\nArchivist = "존댓말"\n', encoding="utf-8"
    )
    (tmp_path / "x.txt").write_text("안녕하세요.\n", encoding="utf-8")
    rc = main(["check", str(tmp_path / "x.txt"), "--config", str(tmp_path / "bad.toml")])
    assert rc == 2
    assert "KO302" in capsys.readouterr().err


# --- selectors ---------------------------------------------------------------

def test_expand_selector():
    assert expand_selector("KO001") == ["KO001"]
    assert set(expand_selector("KO0")) >= {"KO001", "KO002", "KO003", "KO005"}
    assert len(expand_selector("all")) >= 19
    assert expand_selector("KO999") == []


def test_resolve_selection_defaults_exclude_opt_in_rules():
    default = resolve_selection()
    assert "KO001" in default
    assert "KO004" not in default
    assert "KO007" not in default


def test_resolve_selection_ignore_wins_over_extend():
    codes = resolve_selection(extend_select=["KO007"], ignore=["KO007"])
    assert "KO007" not in codes


# --- CLI ---------------------------------------------------------------------

def _capture(argv):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def test_rules_subcommand():
    rc, out, _ = _capture(["rules"])
    assert rc == 0 and "KO001" in out and "KO004" not in out
    rc, out, _ = _capture(["rules", "--all"])
    assert rc == 0 and "KO004" in out and "opt-in" in out


def test_explain_subcommand():
    rc, out, _ = _capture(["explain", "KO005"])
    assert rc == 0
    assert "KO005" in out and "플레이스홀더" in out
    rc, _, err = _capture(["explain", "KO999"])
    assert rc == 2 and "알 수 없는" in err


def test_json_format(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("그는 문을 열었는다.\n", encoding="utf-8")
    rc, out, _ = _capture(["check", str(p), "--select", "KO002", "--format", "json"])
    assert rc == 1
    payload = json.loads(out)
    assert payload[0]["code"] == "KO002"
    assert payload[0]["fix"] == "그는 문을 열었다."
    assert payload[0]["line"] == 1


def test_github_format(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("그는 문을 열었는다.\n", encoding="utf-8")
    _, out, _ = _capture(["check", str(p), "--select", "KO002", "--format", "github"])
    assert out.startswith("::error file=")
    assert "KO002" in out


def test_exit_levels(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("당신은 걷는다.\n", encoding="utf-8")  # KO401 only, severity info
    assert _capture(["check", str(p), "--select", "KO401", "--format", "quiet"])[0] == 0
    assert _capture(
        ["check", str(p), "--select", "KO401", "--format", "quiet", "--exit-level", "info"]
    )[0] == 1
    assert _capture(
        ["check", str(p), "--select", "KO401", "--format", "quiet", "--exit-level", "never"]
    )[0] == 0


def test_diff_does_not_write(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("그는 문을 열었는다.\n", encoding="utf-8")
    rc, out, _ = _capture(["check", str(p), "--select", "KO002", "--diff"])
    assert "- 그는 문을 열었는다." in out
    assert "+ 그는 문을 열었다." in out
    assert p.read_text(encoding="utf-8") == "그는 문을 열었는다.\n"


def test_directory_walk(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("그는 열었는다.\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("source,target\nx,그는 닫았는다.\n", encoding="utf-8")
    (tmp_path / "ignore.bin").write_text("nope\n", encoding="utf-8")
    rc, out, _ = _capture(["check", str(tmp_path), "--select", "KO002", "--format", "json"])
    payload = json.loads(out)
    assert len(payload) == 2


def test_unknown_path_is_a_usage_error(tmp_path):
    rc, _, err = _capture(["check", str(tmp_path / "nope.json"), "--format", "quiet"])
    assert rc == 2
    assert "읽기 실패" in err


def test_example_corpus_exercises_the_documented_rules():
    """The README shows these codes; keep examples/sample.json demonstrating them."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample = os.path.join(here, "examples", "sample.json")
    rc, out, _ = _capture(
        ["check", sample, "--extend-select", "KO004", "--format", "json",
         "--exit-level", "never"]
    )
    codes = {d["code"] for d in json.loads(out)}
    assert {
        "KO002", "KO003", "KO005", "KO101", "KO102", "KO103",
        "KO104", "KO201", "KO301", "KO401", "KO402", "KO403",
    } <= codes
    # And the one that should stay silent: the source repeats too.
    assert "KO105" not in codes


def test_shipped_example_config_parses():
    """examples/kolint.toml is documentation people copy; it must be valid TOML."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = load_config(os.path.join(here, "examples", "kolint.toml"))
    assert cfg.records == "[].strings[]"
    assert cfg.extend_select == ["KO004"]
    assert cfg.options_for("KO103")["ignore_pattern"] == r"^\[NOLOC\]"
    assert cfg.options_for("KO302")["speakers"]["Archivist"] == "formal"
    # And every rule it configures must actually build.
    assert [r.code for r in build_rules(cfg)]


def test_readme_config_block_parses():
    """The TOML shown in the README must be valid too."""
    import re as _re

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    readme = open(os.path.join(here, "README.md"), encoding="utf-8").read()
    blocks = _re.findall(r"```toml\n(.*?)```", readme, _re.DOTALL)
    assert blocks, "README lost its toml example"
    for block in blocks:
        p = os.path.join(os.path.dirname(__file__), "_readme_tmp.toml")
        with open(p, "w", encoding="utf-8") as fp:
            fp.write(block)
        try:
            load_config(p)
        finally:
            os.remove(p)
