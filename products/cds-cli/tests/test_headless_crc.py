import json
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from cds_cli import headless_crc


def test_load_single_target():
    assert headless_crc.load_targets("192.0.2.10", "G") == [
        {"ip": "192.0.2.10", "gateway": "G", "request_id": "1"}
    ]


def test_load_single_target_passes_credential_environment_names(monkeypatch):
    monkeypatch.setenv("CDS_CRC_PLC_USERNAME", "probe")
    monkeypatch.setenv("CDS_CRC_PLC_PASSWORD", "secret")
    assert headless_crc.load_targets("192.0.2.10", "G") == [{
        "ip": "192.0.2.10", "gateway": "G", "request_id": "1",
        "credentials": {
            "username_env": "CDS_CRC_PLC_USERNAME",
            "password_env": "CDS_CRC_PLC_PASSWORD",
        },
    }]


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


def test_profile_guess_uses_numeric_version_order(tmp_path):
    common = tmp_path / "IDE" / "Common"
    common.mkdir(parents=True)
    exe = common / "CODESYS.exe"
    exe.write_text("")
    profiles = tmp_path / "IDE" / "Profiles"
    profiles.mkdir()
    (profiles / "CODESYS V3.5 SP9.profile.xml").write_text("")
    (profiles / "CODESYS V3.5 SP22.profile.xml").write_text("")
    assert headless_crc._profile_guess(exe) == "CODESYS V3.5 SP22"


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


def _watch_args(tmp_path, **overrides):
    values = {
        "ip": "192.0.2.1",
        "gateway": "Gateway-1",
        "input": "",
        "ide": "ide.exe",
        "profile": "profile",
        "host_root": "",
        "interval": 10,
        "startup_timeout": 1,
        "watch_output": str(tmp_path / "cycles.jsonl"),
        "watch_control": str(tmp_path / "stop.json"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_watch_requires_dedicated_jsonl_output(tmp_path):
    args = _watch_args(tmp_path, watch_output="")
    with pytest.raises(ValueError, match="watch-output"):
        headless_crc.run_headless_crc_watch(args)


def test_watch_rejects_preexisting_control_file(tmp_path):
    control = tmp_path / "stop.json"
    control.write_text('{"action": "stop"}')
    with pytest.raises(ValueError, match="already exists"):
        headless_crc._watch_paths(_watch_args(tmp_path))


def test_watch_starts_one_ide_and_exposes_control_contract(monkeypatch, tmp_path, capsys):
    seen = {}

    class Process:
        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def fake_popen(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        seen["env"] = kwargs["env"]
        output = tmp_path / "cycles.jsonl"
        output.write_text(json.dumps({
            "event": "started",
            "session_id": kwargs["env"]["CDS_HEADLESS_CRC_WATCH_SESSION"],
        }) + "\n")
        return Process()

    monkeypatch.setattr(headless_crc.subprocess, "Popen", fake_popen)
    payload, code = headless_crc.run_headless_crc_watch(_watch_args(tmp_path))
    started = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["event"] == "watch_stopped"
    assert started["event"] == "watch_started"
    assert started["watch_control"].endswith("stop.json")
    assert seen["env"]["CDS_HEADLESS_CRC_WATCH"] == "1"
    assert seen["env"]["CDS_HEADLESS_CRC_WATCH_INTERVAL"] == "10"
    assert "--noUI" in seen["args"]
    assert seen["kwargs"]["stdout"] is headless_crc.subprocess.DEVNULL
    assert seen["kwargs"]["stderr"] is headless_crc.subprocess.DEVNULL


def test_stop_watch_removes_its_control_file(tmp_path):
    control = tmp_path / "stop.json"

    class Process:
        def wait(self, timeout=None):
            return 0

    assert headless_crc._stop_watch(Process(), control, "session") == 0
    assert not control.exists()


def test_auto_batch_does_not_replay_after_target_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(headless_crc, "discover_ides", lambda: [("first.exe", "profile"), ("second.exe", "profile")])

    def fake_run(exe, profile, targets, timeout, host_root):
        calls.append(exe)
        return {"ok": False, "results": [{"ok": False}], "summary": {"failed": 1}}

    monkeypatch.setattr(headless_crc, "_run", fake_run)
    args = SimpleNamespace(
        ip="192.0.2.1", gateway="Gateway-1", input="", ide="auto", profile="",
        timeout=10, host_root="",
    )
    payload, code = headless_crc.run_headless_crc(args)
    assert code == 1
    assert payload["results"] == [{"ok": False}]
    assert calls == ["first.exe"]


def _load_host_crc_module():
    path = Path(__file__).resolve().parents[3] / "products" / "codesys-host" / "headless" / "plc_crc.py"
    spec = importlib.util.spec_from_file_location("test_plc_crc_host", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_host_crc_reader_supports_cpython_bytes_and_name(tmp_path):
    host = _load_host_crc_module()

    class Remote:
        def upload_file(self, remote, local, binary):
            Path(local).write_bytes(bytes.fromhex("B11A9000") + bytes.fromhex("78563412") + b"Application\x00")

    result = host._read_crc(Remote(), str(tmp_path / "Application.crc"))
    assert result["crc"] == "00901AB1"
    assert result["metadata_timestamp_unix"] == 0x12345678
    assert result["application"] == "Application"


def test_host_crc_errors_distinguish_ambiguous_gateway():
    host = _load_host_crc_module()
    assert host._stable_error_code(RuntimeError("Gateway name is ambiguous: G"), "gateway") == "gateway_ambiguous"


def test_host_credentials_are_resolved_from_environment_only(monkeypatch):
    host = _load_host_crc_module()
    monkeypatch.setenv("CRC_TEST_USER", "probe")
    monkeypatch.setenv("CRC_TEST_PASSWORD", "do-not-report-this")

    class Online:
        def __init__(self):
            self.auth_fallback_modes = None
            self.calls = []

        def set_specific_credentials(self, device, username, password):
            self.calls.append((device, username, password))

    class CredentialSourceKind:
        none = object()

    online = Online()
    scriptengine = SimpleNamespace(online=online, CredentialSourceKind=CredentialSourceKind)
    device = object()
    host._configure_credentials({"credentials": {
        "username_env": "CRC_TEST_USER", "password_env": "CRC_TEST_PASSWORD",
    }}, device, scriptengine)

    assert online.auth_fallback_modes is CredentialSourceKind.none
    assert online.calls == [(device, "probe", "do-not-report-this")]


def test_host_credentials_accept_astra_online_enum(monkeypatch):
    host = _load_host_crc_module()
    monkeypatch.setenv("CRC_TEST_USER", "probe")
    monkeypatch.setenv("CRC_TEST_PASSWORD", "secret")

    class CredentialSourceKind:
        none = object()

    class Online:
        def set_specific_credentials(self, device, username, password):
            self.credentials = (device, username, password)

    online = Online()
    online.CredentialSourceKind = CredentialSourceKind
    host._configure_credentials({"credentials": {
        "username_env": "CRC_TEST_USER", "password_env": "CRC_TEST_PASSWORD",
    }}, object(), SimpleNamespace(online=online))
    assert online.auth_fallback_modes is CredentialSourceKind.none


def test_host_credentials_use_zero_when_profile_hides_enum(monkeypatch):
    host = _load_host_crc_module()
    monkeypatch.setenv("CRC_TEST_USER", "probe")
    monkeypatch.setenv("CRC_TEST_PASSWORD", "secret")

    class Online:
        def set_specific_credentials(self, device, username, password):
            self.credentials = (device, username, password)

    online = Online()
    host._configure_credentials({"credentials": {
        "username_env": "CRC_TEST_USER", "password_env": "CRC_TEST_PASSWORD",
    }}, object(), SimpleNamespace(online=online))
    assert online.auth_fallback_modes == 0


def test_host_credentials_missing_environment_never_exposes_secret(monkeypatch):
    host = _load_host_crc_module()
    monkeypatch.delenv("CRC_MISSING_PASSWORD", raising=False)
    target = {"credentials": {
        "username_env": "CRC_USER", "password_env": "CRC_MISSING_PASSWORD",
    }}
    with pytest.raises(RuntimeError, match="credential environment variable is not set") as error:
        host._configure_credentials(target, object(), SimpleNamespace(online=object()))
    assert "CRC_MISSING_PASSWORD" not in str(error.value)


def test_host_single_target_uses_conventional_credential_environment(monkeypatch):
    host = _load_host_crc_module()
    monkeypatch.setattr(host.sys, "argv", ["plc_crc.py", "--ip", "192.0.2.1"])
    monkeypatch.setenv("CDS_CRC_PLC_USERNAME", "probe")
    monkeypatch.setenv("CDS_CRC_PLC_PASSWORD", "secret")
    assert host._targets() == [{
        "ip": "192.0.2.1", "gateway": "Gateway-1", "request_id": "1",
        "credentials": {
            "username_env": "CDS_CRC_PLC_USERNAME",
            "password_env": "CDS_CRC_PLC_PASSWORD",
        },
    }]


def _load_online_helpers_module():
    path = Path(__file__).resolve().parents[3] / "products" / "codesys-host" / "src" / "ide_bridge" / "ide_online_helpers.py"
    spec = importlib.util.spec_from_file_location("test_ide_online_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daemon_login_uses_keep_without_deleting_foreign_apps(monkeypatch):
    helpers = _load_online_helpers_module()

    class OnlineChangeOption:
        Keep = object()

    monkeypatch.setitem(sys.modules, "scriptengine", SimpleNamespace(OnlineChangeOption=OnlineChangeOption))

    class Online:
        is_logged_in = False

        def __init__(self):
            self.calls = []

        def login(self, option, delete_foreign_apps):
            self.calls.append((option, delete_foreign_apps))

    online = Online()
    helpers._ensure_logged_in(online)
    assert online.calls == [(OnlineChangeOption.Keep, False)]


def test_daemon_full_download_uses_never_without_deleting_foreign_apps(monkeypatch):
    helpers = _load_online_helpers_module()

    class OnlineChangeOption:
        Never = object()

    monkeypatch.setitem(sys.modules, "scriptengine", SimpleNamespace(OnlineChangeOption=OnlineChangeOption))

    class Online:
        application_state = "run"

        def __init__(self):
            self.calls = []

        def logout(self):
            self.calls.append(("logout",))

        def login(self, option, delete_foreign_apps):
            self.calls.append((option, delete_foreign_apps))

    online = Online()
    monkeypatch.setattr(helpers, "ensure_online_connection", lambda project: (online, SimpleNamespace(get_name=lambda: "Application")))
    result = helpers.download_impl(object(), start=False)
    assert result["option"] == "Never"
    assert online.calls == [("logout",), (OnlineChangeOption.Never, False)]
