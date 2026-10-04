"""``cts guide``: the operating guides ship inside the package.

The guides used to live in ``skills/`` at the repository root, which is not
package data, so a pip/irm install had none of them. These tests pin the
contract: every topic is present as package data, the command lists and prints
them without an IDE, and an unknown topic fails loudly.
"""

import json

import pytest

from cds_cli import main as cli_main
from cds_cli._cli_parser import build_parser
from cds_cli.guides_data import TOPICS, GuideError, guide_root, read_file, read_topic


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["cts"] + argv)
    cli_main.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


def test_help_epilog_points_at_cts_guide():
    assert "cts guide" in build_parser().format_help()


def test_every_topic_file_is_shipped_in_package_data():
    root = guide_root()
    assert root.is_dir()
    for entry in TOPICS:
        path = root / entry["file"]
        assert path.is_file(), entry["file"]
        assert path.read_text(encoding="utf-8").strip()
        assert entry["summary"].strip()


def test_topic_extra_files_are_shipped():
    assert set(read_topic("visu-svg")["files"]) == {
        "advanced-elements.md",
        "examples/pid-schematic.svg",
        "examples/status-panel.svg",
    }
    assert read_topic("workflow")["files"] == []


def test_guide_lists_topics_and_the_guide_directory(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ["guide"])

    payload = json.loads(out)
    assert {item["topic"] for item in payload["topics"]} == {
        "workflow",
        "commands",
        "visu-svg",
    }
    assert payload["guide_dir"]
    assert all(item["summary"] for item in payload["topics"])


def test_guide_topic_prints_the_markdown_verbatim(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ["--pretty", "guide", "workflow"])

    assert out.startswith("# Operate CODESYS Text Sync")
    assert "cts guide commands" in out


def test_guide_topic_json_carries_topic_path_and_text(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ["guide", "commands"])

    payload = json.loads(out)
    assert payload["topic"] == "commands"
    assert payload["path"].endswith("commands.md")
    assert "cts ping" in payload["text"]


def test_guide_file_prints_a_shipped_example(monkeypatch, capsys):
    out, _ = _run(
        monkeypatch,
        capsys,
        ["guide", "visu-svg", "--file", "examples/pid-schematic.svg"],
    )

    payload = json.loads(out)
    assert payload["file"] == "examples/pid-schematic.svg"
    assert payload["text"].startswith("<svg")


def test_unknown_topic_exits_non_zero_and_lists_valid_topics(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, capsys, ["guide", "nope"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unknown guide topic" in err
    for topic in ("workflow", "commands", "visu-svg"):
        assert topic in err


def test_unknown_file_lists_the_available_files():
    with pytest.raises(GuideError) as exc:
        read_file("visu-svg", "examples/nope.svg")

    assert "examples/pid-schematic.svg" in str(exc.value)


def test_file_name_cannot_escape_the_topic_folder():
    with pytest.raises(GuideError):
        read_file("visu-svg", "../commands.md")


def test_guide_needs_no_ide_and_prints_no_daemon_note(monkeypatch, capsys):
    monkeypatch.setattr(cli_main, "discover", lambda b=1.0: [])

    out, err = _run(monkeypatch, capsys, ["--pretty", "guide", "workflow"])

    assert "no IDE answered" not in out + err
    assert out.startswith("# Operate CODESYS Text Sync")
