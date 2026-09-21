import json

from cds_cli import headless_crc


def test_load_single_target():
    assert headless_crc.load_targets("192.0.2.10", "G") == [
        {"ip": "192.0.2.10", "gateway": "G", "request_id": "1"}
    ]


def test_load_batch_preserves_request_ids_and_defaults(tmp_path):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps({"targets": [{"request_id": "a", "ip": "192.0.2.1"}, {"ip": "192.0.2.2"}]}))
    assert headless_crc.load_targets(input_path=str(path), gateway="G") == [
        {"request_id": "a", "ip": "192.0.2.1", "gateway": "G"},
        {"ip": "192.0.2.2", "gateway": "G", "request_id": "2"},
    ]


def test_load_batch_leaves_bad_row_for_per_target_validation(tmp_path):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps({"targets": [{"ip": "192.0.2.1"}, {"name": "missing ip"}, 42]}))
    assert headless_crc.load_targets(input_path=str(path))[1:] == [
        {"name": "missing ip", "gateway": "Gateway-1", "request_id": "2"},
        {"value": 42, "gateway": "Gateway-1", "request_id": "3"},
    ]


def test_discovery_is_stateless(monkeypatch, tmp_path):
    exe = tmp_path / "ide.exe"
    exe.write_text("")
    monkeypatch.setenv("CDS_CRC_CODESYS_EXE", str(exe))
    monkeypatch.setenv("CDS_CRC_CODESYS_PROFILE", "profile")
    assert headless_crc.discover_ides()[0] == (str(exe), "profile")


def test_profile_guess_removes_full_descriptor_suffix(tmp_path):
    common = tmp_path / "IDE" / "Common"
    common.mkdir(parents=True)
    exe = common / "CODESYS.exe"
    exe.write_text("")
    profiles = tmp_path / "IDE" / "Profiles"
    profiles.mkdir()
    (profiles / "Vendor IDE 1.2.profile.xml").write_text("")
    assert headless_crc._profile_guess(exe) == "Vendor IDE 1.2"


def test_single_run_passes_headless_arguments(monkeypatch, tmp_path):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]

        class Completed:
            returncode = 0
            stderr = ""

        return Completed()

    monkeypatch.setattr(headless_crc.subprocess, "run", fake_run)
    payload = headless_crc._run("ide.exe", "profile", [{"ip": "192.0.2.1"}])
    assert "--noUI" in seen["args"]
    assert any(str(item).startswith("--runscript=") for item in seen["args"])
    assert not any(str(item).startswith("--scriptargs") for item in seen["args"])
    assert seen["env"]["CDS_HEADLESS_CRC_INPUT"].endswith("targets.json")
    assert seen["env"]["CDS_HEADLESS_CRC_OUTPUT"].endswith("result.json")
    assert payload["ok"] is False
