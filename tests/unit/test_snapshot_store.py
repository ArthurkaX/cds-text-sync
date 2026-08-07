import json


def test_snapshot_store_round_trip(tmp_path):
    from pathlib import Path
    import sys

    bridge = Path(__file__).resolve().parents[2] / "products" / "codesys-host" / "src" / "ide_bridge"
    sys.path.insert(0, str(bridge))
    import snapshot_store

    path = tmp_path / "preset.json"
    data = {"schema_version": 1, "variables": [{"name": "x", "value": 3}]}
    assert snapshot_store.save(data, str(path)) == str(path)
    assert json.loads(path.read_text(encoding="utf-8")) == data
    assert snapshot_store.load(str(path)) == data


def test_snapshot_compare_is_pure():
    from pathlib import Path
    import sys

    bridge = Path(__file__).resolve().parents[2] / "products" / "codesys-host" / "src" / "ide_bridge"
    sys.path.insert(0, str(bridge))
    import snapshot_compare

    result = snapshot_compare.compare_documents(
        [{"path": "A.x", "type": "INT", "value": "1", "read_ok": True}],
        [{"path": "A.x", "type": "INT", "value": "2", "read_ok": True}],
    )
    assert result["value_changed"] == [{"path": "A.x", "was": "1", "now": "2"}]
