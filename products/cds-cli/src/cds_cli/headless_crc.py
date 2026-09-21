"""Stateless launcher for the IDE-side headless PLC CRC script."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
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
