from pathlib import Path

from cds_text_sync.fsm_search import search_workspace


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_search_workspace_filters_paths_before_parsing(tmp_path):
    view = tmp_path / "project-view"
    _write(
        view / "Machines" / "Motor.st",
        """FUNCTION_BLOCK Motor
// --- implementation ---
CASE state OF
  IDLE: next_state := RUN;
  RUN: next_state := IDLE;
END_CASE;
""",
    )
    _write(
        view / "Utilities" / "NoMachine.st",
        """FUNCTION NoMachine : BOOL
// --- implementation ---
value := 1;
""",
    )

    result = search_workspace(tmp_path, "motor", workers=1)

    assert result["scanned"] == 1
    assert result["workers"] == 1
    assert [row["path"] for row in result["results"]] == ["Machines/Motor.st"]
    machine = result["results"][0]["machines"][0]
    assert machine["selector"] == "state"
    assert [state["label"] for state in machine["states"]] == ["IDLE", "RUN"]


def test_search_workspace_accepts_project_view_as_its_root(tmp_path):
    _write(
        tmp_path / "One.st",
        """CASE state OF
  A: state := B;
  B: state := A;
END_CASE;
""",
    )

    result = search_workspace(tmp_path, "", workers=1)

    assert result["scanned"] == 1
    assert result["results"][0]["path"] == "One.st"


def test_search_workspace_lists_matching_paths_without_parsing(tmp_path):
    _write(tmp_path / "Machine.st", "this is not Structured Text")

    result = search_workspace(tmp_path, "machine", parse=False)

    assert result["scanned"] == 0
    assert result["workers"] == 0
    assert result["candidates"] == ["Machine.st"]
    assert result["results"] == []
