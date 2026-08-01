"""JSON-only command contract for machine visualization validation."""

from __future__ import annotations

import json
from pathlib import Path

from .dead_explicit_color import lint


def cmd_visu_lint(args) -> int:
    path = Path(args.xml)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    findings = lint(text, path=str(path))
    print(json.dumps({"schema_version": 1, "ok": not findings, "findings": findings}, ensure_ascii=False))
    return 1 if findings else 0
