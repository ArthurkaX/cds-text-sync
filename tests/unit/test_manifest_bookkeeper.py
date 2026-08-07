import json

from cds_text_sync.engine._manifest_bookkeeper import entries, hash_by_path, load


def test_manifest_entries_and_hashes_are_indexed_by_relative_path():
    manifest = {
        "entries": [
            {
                "xml_path": r"POU\Main.xml",
                "hash": "xml-hash",
                "projection_hashes": {r"POU\Main.st": "st-hash"},
            }
        ]
    }

    assert entries(manifest) == manifest["entries"]
    assert hash_by_path(manifest) == {
        "POU/Main.xml": "xml-hash",
        "POU/Main.st": "st-hash",
    }


def test_manifest_loader_returns_none_for_missing_or_invalid_file(tmp_path):
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")

    assert load(str(missing)) is None
    assert load(str(invalid)) is None


def test_manifest_loader_reads_json(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"entries": [{"guid": "1"}]}), encoding="utf-8")

    assert load(str(path)) == {"entries": [{"guid": "1"}]}
