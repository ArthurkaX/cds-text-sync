# -*- coding: utf-8 -*-
"""
pipe_targets.py — Target selection and hello handshake parsing for multi-instance reverse pipe.

Pure Python module with no ctypes or Win32 dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cts_shared import wire


LEGACY = "LEGACY"


def parse_target(text: str | int) -> int:
    """Parse a target identifier into an integer PID.

    Accepts 'ide-3684', '3684', or 3684.
    Raises ValueError for invalid formats or non-positive PIDs.
    """
    if isinstance(text, int):
        if text <= 0:
            raise ValueError(f"Invalid target PID: {text}")
        return text
    if not isinstance(text, str):
        raise ValueError(f"Target must be str or int, got {type(text).__name__}")
    s = text.strip()
    if not s:
        raise ValueError("Target cannot be empty")
    if s.lower().startswith("ide-"):
        s = s[4:]
    try:
        pid = int(s)
        if pid <= 0:
            raise ValueError(f"Target PID must be positive, got {pid}")
        return pid
    except ValueError:
        raise ValueError(f"Invalid target '{text}': expected 'ide-<pid>' or integer PID")


def match_project(project: dict[str, Any] | None, expect: str) -> bool:
    """Check if the project matches an expected project name or path.

    Matching is case-insensitive. Accepts project stem name, .project filename,
    or normalized full path.
    """
    if not project or not isinstance(project, dict):
        return False
    if not expect or not isinstance(expect, str):
        return False

    exp = expect.strip()
    name = project.get("name")
    path = project.get("path")

    # Name matching (case-insensitive)
    if name and isinstance(name, str):
        if exp.lower() == name.lower():
            return True
        if exp.lower().endswith(".project") and exp[:-8].lower() == name.lower():
            return True

    # Path matching
    if path and isinstance(path, str):
        norm_exp = exp.replace("\\", "/").rstrip("/").lower()
        norm_path = path.replace("\\", "/").rstrip("/").lower()
        if norm_exp == norm_path:
            return True
        # Compare base filename and stem
        base = norm_path.split("/")[-1]
        stem = base[:-8] if base.endswith(".project") else base
        if exp.lower() == stem or exp.lower() == base:
            return True

    return False


@dataclass
class Hello:
    """Parsed H2 hello message from a CODESYS daemon."""

    protocol: int
    id: str
    pid: int
    version: str = ""
    poll_ms: int = 200
    project: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hello:
        # Field names, defaults and the nested-vs-bare envelope are decided in
        # cts_shared.wire, the same module the daemon builds the hello with.
        fields = wire.parse_hello(data)
        return cls(
            protocol=fields["protocol"],
            id=fields["id"],
            pid=fields["pid"],
            version=fields["version"],
            poll_ms=fields["poll_ms"],
            project=fields["project"],
        )


class TargetError(Exception):
    """Target resolution error. Not a RuntimeError, exits with code 2."""

    def __init__(self, code: str, message: str, instances: list[Hello] | None = None):
        super().__init__(message)
        self.code = code
        self.instances = instances or []


@dataclass
class Decision:
    """Outcome of the decision logic."""

    kind: str  # "send", "wait", "error"
    target: Hello | str | None = None  # Hello instance, LEGACY ("LEGACY"), or None
    error: TargetError | None = None


def format_ambiguous(
    hellos: dict[int, Hello] | list[Hello],
    extra_pids: set[int] | list[int] | None = None,
    legacy_pids: set[int] | list[int] | None = None,
) -> str:
    """Format the ambiguous_target error message with ready commands."""
    hello_list = list(hellos.values()) if isinstance(hellos, dict) else list(hellos)
    extra_list = list(extra_pids or ())
    legacy_list = list(legacy_pids or ())

    total_count = len(hello_list) + len(extra_list) + len(legacy_list)
    header = f"error: {total_count} IDE instances, choose one:"

    lines = [header]
    for h in sorted(hello_list, key=lambda x: x.pid):
        prj = h.project
        if prj and prj.get("name"):
            desc = prj["name"]
        elif prj and prj.get("path"):
            desc = prj["path"]
        else:
            desc = "no project"
        lines.append(f"  cts --target {h.id} ...   # {desc}")

    for pid in sorted(legacy_list):
        lines.append(f"  ide-{pid}                     # old daemon, no id")

    for pid in sorted(extra_list):
        lines.append(f"  ide-{pid}                     # daemon not answering")

    return "\n".join(lines)


def decide(
    hellos: dict[int, Hello],
    legacy_pids: set[int] | None = None,
    target_pid: int | None = None,
    codesys_pids: set[int] | None = None,
    window_over: bool = False,
) -> Decision:
    """Decide what to do given current hellos, legacy pids, and target request."""
    legacy = set(legacy_pids or ())
    codesys = set(codesys_pids or ())

    # Rule 1: With a target
    if target_pid is not None:
        if target_pid in hellos:
            chosen = hellos[target_pid]
            if chosen.protocol != 2:
                return Decision(
                    kind="error",
                    error=TargetError(
                        "protocol_mismatch",
                        f"error: protocol mismatch: daemon protocol {chosen.protocol} != client protocol 2 (update Project_daemon / cts)",
                        instances=list(hellos.values()),
                    ),
                )
            return Decision(kind="send", target=chosen)
        if window_over:
            live = list(hellos.values())
            if live:
                live_desc = ", ".join(h.id for h in live)
                msg = f"error: IDE instance ide-{target_pid} not found. Live instances: {live_desc}."
            else:
                msg = f"error: IDE instance ide-{target_pid} not found (no IDE answered)."
            return Decision(
                kind="error",
                error=TargetError("unknown_target", msg, instances=live),
            )
        return Decision(kind="wait")

    # Rule 2: No target, window not over
    if not window_over:
        return Decision(kind="wait")

    # Rule 3: No target, window over
    if len(hellos) == 0 and len(legacy) == 0:
        return Decision(kind="wait")

    extra = codesys - set(hellos.keys()) - legacy

    # Exactly 1 hello, no legacy, no extra CODESYS processes
    if len(hellos) == 1 and len(legacy) == 0 and len(extra) == 0:
        chosen = list(hellos.values())[0]
        if chosen.protocol != 2:
            return Decision(
                kind="error",
                error=TargetError(
                    "protocol_mismatch",
                    f"error: protocol mismatch: daemon protocol {chosen.protocol} != client protocol 2 (update Project_daemon / cts)",
                    instances=list(hellos.values()),
                ),
            )
        return Decision(kind="send", target=chosen)

    # Exactly 1 legacy, no hellos, no extra CODESYS processes
    if len(hellos) == 0 and len(legacy) == 1 and len(extra) == 0:
        return Decision(kind="send", target=LEGACY)

    # Otherwise ambiguous
    msg = format_ambiguous(hellos, extra_pids=extra, legacy_pids=legacy)
    return Decision(
        kind="error",
        error=TargetError("ambiguous_target", msg, instances=list(hellos.values())),
    )
