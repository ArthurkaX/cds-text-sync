from cds_text_sync.engine._pending_files import iter_files


def test_iter_files_skips_hidden_entries_and_returns_relative_paths(tmp_path):
    (tmp_path / "HMI").mkdir()
    (tmp_path / ".dump").mkdir()
    (tmp_path / "HMI" / "Main.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / "HMI" / ".hidden.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / ".dump" / "Ignored.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / "HMI" / "Main.st").write_text("PROGRAM Main", encoding="utf-8")

    assert list(iter_files(str(tmp_path), ".xml")) == [
        ("HMI/Main.xml", str(tmp_path / "HMI" / "Main.xml"))
    ]


def test_iter_files_missing_root_is_empty(tmp_path):
    assert list(iter_files(str(tmp_path / "missing"), ".st")) == []
