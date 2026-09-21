"""Stateless launcher for the IDE-side headless PLC CRC script."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[4]
_KNOWN = (
    (r"C:\Program Files\AstraRegul\Astra.IDE_64_1.7.2.1\Astra.IDE\Common\Astra.IDE.exe", "Astra.IDE_V1.7.2.1"),
    (r"C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe", "CODESYS V3.5 SP22 Patch 1"),
    (r"C:\Program Files\CODESYS 3.5.20.0\CODESYS\Common\CODESYS.exe", "CODESYS V3.5 SP20 Patch 0"),
)


def load_targets(ip="", gateway="Gateway-1", input_path=""):
    if input_path:
        with open(input_path, encoding="utf-8") as stream:
            payload = json.load(stream)
        targets = payload.get("targets", payload) if isinstance(payload, dict) else payload
        if not isinstance(targets, list) or not targets:
            raise ValueError("batch input must contain a non-empty targets array")
        result = []
        for index, target in enumerate(targets):
            # Per-target validation belongs to the IDE-side batch loop: one bad
            # row must not prevent all other PLCs from being checked.
            item = dict(target) if isinstance(target, dict) else {"value": target}
            item.setdefault("gateway", gateway)
            item.setdefault("request_id", str(index + 1))
            result.append(item)
        return result
    if not ip:
        raise ValueError("one of --ip or --input is required")
    return [{"ip": ip, "gateway": gateway, "request_id": "1"}]


def _script_path(host_root=""):
    override = host_root or os.environ.get("CDS_CODESYS_HOST_ROOT", "")
    if override:
        candidate = Path(override) / "headless" / "plc_crc.py"
        if candidate.is_file():
            return candidate
    candidate = _ROOT / "products" / "codesys-host" / "headless" / "plc_crc.py"
    if candidate.is_file():
        return candidate
    # Installed package layouts keep the host beside the CLI package.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "codesys-host" / "headless" / "plc_crc.py"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("headless/plc_crc.py was not found; use --host-root")


def discover_ides():
    """Return existing (executable, profile) pairs without persistent state."""
    pairs = []
    env_exe = os.environ.get("CDS_CRC_CODESYS_EXE")
    env_profile = os.environ.get("CDS_CRC_CODESYS_PROFILE")
    if env_exe:
        pairs.append((env_exe, env_profile or ""))
    for exe, profile in _KNOWN:
        if Path(exe).is_file():
            pairs.append((exe, profile))
    # Best-effort discovery of installed IDEs; this is intentionally ephemeral.
    for root in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                 Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))):
        for pattern in ("Astra.IDE.exe", "CODESYS.exe"):
            try:
                for exe_path in root.glob("**/" + pattern):
                    profile = "Astra.IDE_V1.7.2.1" if "astra" in str(exe_path).lower() else _profile_guess(exe_path)
                    pairs.append((str(exe_path), profile))
            except (OSError, ValueError):
                pass
    seen = set()
    unique = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    return unique


def _profile_guess(exe_path):
    """Infer a profile from nearby installed profile descriptors, if present."""
    for parent in [Path(exe_path)] + list(Path(exe_path).parents):
        profiles = parent / "Profiles"
        if profiles.is_dir():
            candidates = sorted(profiles.glob("*.profile.xml"))
            if candidates:
                suffix = ".profile.xml"
                name = candidates[-1].name
                return name[:-len(suffix)] if name.endswith(suffix) else candidates[-1].stem
    return ""


def _run(exe, profile, targets, timeout=None, host_root=""):
    with tempfile.TemporaryDirectory(prefix="cts-plc-crc-") as folder:
        folder = Path(folder)
        request = folder / "targets.json"
        result = folder / "result.json"
        request.write_text(json.dumps({"targets": targets}), encoding="utf-8")
        args = [
            str(exe),
            "--profile=" + profile,
            "--runscript=" + str(_script_path(host_root)),
            "--noUI",
            "--textPrompts",
        ]
        environment = os.environ.copy()
        environment["CDS_HEADLESS_CRC_INPUT"] = str(request)
        environment["CDS_HEADLESS_CRC_OUTPUT"] = str(result)
        completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, timeout=timeout, env=environment)
        if result.is_file():
            payload = json.loads(result.read_text(encoding="utf-8"))
        else:
            payload = {"ok": False, "error": {"code": "ide_failed", "message": completed.stderr.strip() or "IDE did not produce a result"}, "results": []}
        payload.setdefault("host", {"exe": str(exe), "profile": profile})
        payload["process"] = {"returncode": completed.returncode}
        return payload


def _watch_paths(args):
    """Validate externally visible watch paths without touching normal mode."""
    if not args.watch_output:
        raise ValueError("--watch-output is required with --watch")
    output = Path(args.watch_output).expanduser().resolve()
    control = Path(args.watch_control).expanduser().resolve() if args.watch_control else Path(
        str(output) + ".control.json"
    )
    if control.exists():
        raise ValueError("--watch-control must name a file that does not exist")
    return output, control


def _watch_started(output, session_id):
    """Return true after the IDE-side script has accepted this exact session."""
    if not output.is_file():
        return False
    try:
        with output.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "started" and event.get("session_id") == session_id:
                    return True
    except OSError:
        return False
    return False


def _watch_args(exe, profile, host_root=""):
    return [
        str(exe),
        "--profile=" + profile,
        "--runscript=" + str(_script_path(host_root)),
        "--noUI",
        "--textPrompts",
    ]


def _start_watch(exe, profile, targets, output, control, args):
    """Start one IDE, then wait only until its script is demonstrably ready."""
    session_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="cts-plc-crc-watch-") as folder:
        request = Path(folder) / "targets.json"
        request.write_text(json.dumps({"targets": targets}), encoding="utf-8")
        environment = os.environ.copy()
        environment.update({
            "CDS_HEADLESS_CRC_INPUT": str(request),
            "CDS_HEADLESS_CRC_WATCH": "1",
            "CDS_HEADLESS_CRC_WATCH_OUTPUT": str(output),
            "CDS_HEADLESS_CRC_WATCH_CONTROL": str(control),
            "CDS_HEADLESS_CRC_WATCH_INTERVAL": str(args.interval),
            "CDS_HEADLESS_CRC_WATCH_SESSION": session_id,
        })
        process = subprocess.Popen(_watch_args(exe, profile, getattr(args, "host_root", "")), env=environment)
        deadline = time.monotonic() + args.startup_timeout
        while time.monotonic() < deadline:
            if _watch_started(output, session_id):
                return process, session_id
            if process.poll() is not None:
                raise RuntimeError("IDE exited before the watch script became ready")
            time.sleep(0.1)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise RuntimeError("IDE watch script did not become ready before --startup-timeout")


def _stop_watch(process, control):
    """Ask for IDE-side cleanup first, with process termination as a fallback."""
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(json.dumps({"action": "stop"}), encoding="utf-8")
    try:
        return process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


def run_headless_crc_watch(args):
    """Run the opt-in long-lived mode; the ordinary CRC path is untouched."""
    if args.interval <= 0:
        raise ValueError("--interval must be greater than zero")
    if args.startup_timeout <= 0:
        raise ValueError("--startup-timeout must be greater than zero")
    targets = load_targets(args.ip, args.gateway, args.input)
    output, control = _watch_paths(args)
    candidates = [(args.ide, args.profile)] if args.ide != "auto" else discover_ides()
    if not candidates:
        return {"ok": False, "error": {"code": "ide_not_found", "message": "no CODESYS/Astra IDE found"}}, 2
    attempts = []
    for exe, profile in candidates:
        profile = profile or args.profile
        if not profile:
            attempts.append({"exe": exe, "error": {"code": "profile_required", "message": "profile is required when --ide is explicit"}})
            continue
        try:
            process, session_id = _start_watch(exe, profile, targets, output, control, args)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            attempts.append({"exe": exe, "profile": profile, "error": {"code": "ide_failed", "message": str(error)}})
            if args.ide != "auto":
                return {"ok": False, "error": attempts[-1]["error"], "attempts": attempts}, 1
            continue
        started = {
            "ok": True,
            "event": "watch_started",
            "session_id": session_id,
            "watch_output": str(output),
            "watch_control": str(control),
            "interval_seconds": args.interval,
            "host": {"exe": str(exe), "profile": profile},
        }
        print(json.dumps(started, ensure_ascii=False, sort_keys=True), flush=True)
        try:
            returncode = process.wait()
        except KeyboardInterrupt:
            returncode = _stop_watch(process, control)
        return {"ok": returncode == 0, "event": "watch_stopped", "session_id": session_id,
                "process": {"returncode": returncode}}, 0 if returncode == 0 else 1
    return {"ok": False, "error": {"code": "all_ides_failed", "message": "no candidate IDE completed startup"}, "attempts": attempts}, 1


def run_headless_crc(args):
    targets = load_targets(args.ip, args.gateway, args.input)
    candidates = [(args.ide, args.profile)] if args.ide != "auto" else discover_ides()
    if not candidates:
        return {"ok": False, "error": {"code": "ide_not_found", "message": "no CODESYS/Astra IDE found"}, "results": []}, 2
    attempts = []
    for exe, profile in candidates:
        if not profile:
            profile = args.profile
        if not profile:
            attempts.append({"exe": exe, "error": {"code": "profile_required", "message": "profile is required when --ide is explicit"}})
            continue
        try:
            payload = _run(exe, profile, targets, args.timeout, getattr(args, "host_root", ""))
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            attempts.append({"exe": exe, "profile": profile, "error": {"code": "ide_failed", "message": str(error)}})
            continue
        payload.setdefault("host", {"exe": exe, "profile": profile})
        if payload.get("ok") or args.ide != "auto":
            return payload, 0 if payload.get("ok") else 1
        attempts.append({"exe": exe, "profile": profile, "result": payload})
    return {"ok": False, "error": {"code": "all_ides_failed", "message": "no candidate IDE completed the operation"}, "attempts": attempts, "results": []}, 1
