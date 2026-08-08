"""Optional local desktop UI for the offline static analyzer.

The UI is deliberately a thin adapter over the analysis engine: it never
talks to CODESYS or the daemon, and a normal run does not write state.
``pywebview`` is imported only by :func:`launch`, so the main CLI remains
usable without its optional dependency.
"""

from __future__ import annotations

import os
import difflib
import hashlib
import subprocess
from pathlib import Path

from cds_static_analyzer import state as state_mod
from cds_static_analyzer.config import ConfigError, load_config, set_rule_enabled
from cds_static_analyzer.registry import RegistryError, load_builtin_rules
from cds_static_analyzer.runner import RunOptions
from cds_static_analyzer.service import analyze as run_service
from cds_static_analyzer.triage import TriageError, apply_decisions
from cds_static_analyzer.workspace import WorkspaceError, WorkspaceResolver
from cds_text_sync import __version__


def _repair_mojibake(text: str) -> str:
    """Repair an obvious UTF-8 -> Latin-1 -> UTF-8 round trip for display.

    Some CODESYS exports contain Russian comments that were decoded as a
    single-byte encoding and encoded as UTF-8 again.  Do not apply a broad
    encoding guess: only transform text when it is entirely single-byte and
    the conversion removes the characteristic C1 controls and ``Ð``/``Ñ``
    markers.  The source file itself is never rewritten by this helper.
    """

    def badness(value: str) -> int:
        return sum(
            1
            for char in value
            if "\x80" <= char <= "\x9f" or char in "ÃÂÐÑ"
        )

    current = text
    for _ in range(2):
        if any(ord(char) > 0xFF for char in current):
            break
        try:
            candidate = current.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if badness(candidate) >= badness(current):
            break
        current = candidate
    return current


def _read_autofix_source(path: Path):
    """Return ``(text_lf, newline, had_bom, raw)`` for an ST source file.

    Autofix must not rewrite a whole file just because Python's universal
    newline translation turned CRLF into LF.  The rule fixers are written for
    LF and split on ``"\\n"``, so they are handed LF-normalized text; on
    write-back the original dominant line ending and a leading UTF-8 BOM are
    restored.

    Line-ending rule: if the file contains any CRLF, write CRLF for every
    line ending, otherwise write LF.  This deliberately normalizes a mixed
    file to CRLF; that is the intentional trade-off for the common CODESYS
    export layout.
    """
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if had_bom else raw
    text = body.decode("utf-8", errors="replace")
    newline = "\r\n" if b"\r\n" in body else "\n"
    return text.replace("\r\n", "\n"), newline, had_bom, raw


def analyze_workspace(workspace_path: str) -> dict:
    """Return the same JSON envelope that ``cts analyze`` would display.

    Errors are data rather than exceptions because they cross the JavaScript
    bridge.  This function intentionally performs no baseline/triage writes.
    """
    try:
        workspace, _config, result = run_service(workspace_path, RunOptions(), apply_state=True)
        return {
            "ok": True,
            "workspace": workspace.root,
            "project_view": workspace.project_view,
            "result": _ui_result_dict(result),
        }
    except (WorkspaceError, ConfigError, RegistryError, state_mod.StateError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # Do not leave the window with an opaque bridge error.
        return {"ok": False, "error": f"Analysis failed unexpectedly: {exc}"}


def _ui_result_dict(result) -> dict:
    """Add UI-only capabilities without changing the CLI result contract."""
    payload = result.to_dict()
    fixable = {
        rule_id: rule.fix is not None for rule_id, rule in load_builtin_rules().items()
    }
    for finding in payload.get("findings", []):
        finding["fixable"] = bool(fixable.get(finding.get("rule_id"), False))
    return payload


class AnalyzerApi:
    """Methods exposed to the local pywebview page."""

    #: What :meth:`progress` reports when no run is in flight.
    IDLE_PROGRESS = {"running": False, "phase": "", "done": 0, "total": 0, "detail": ""}

    def __init__(self, initial_workspace: str = ""):
        self.initial_workspace = initial_workspace
        self._last_project_view = ""
        self._last_analysis = None
        self._last_result = None
        self._progress = dict(self.IDLE_PROGRESS)

    def initial_state(self) -> dict:
        return {"workspace": self.initial_workspace, "analyzer_version": __version__}

    def progress(self) -> dict:
        """Snapshot of the run currently in flight, polled by the page.

        pywebview dispatches every bridge call on its own thread, so this is
        read while :meth:`analyze` is still working.  ``_record`` replaces the
        whole dict instead of mutating it, so a poll either sees the previous
        report or the next one, never a half-written one, and no lock is
        needed on either side.
        """
        return dict(self._progress)

    def _record_progress(self, phase, done, total, detail) -> None:
        self._progress = {
            "running": True,
            "phase": str(phase),
            "done": int(done),
            "total": int(total),
            "detail": str(detail),
        }

    def analyze(self, workspace_path: str) -> dict:
        self._record_progress("start", 0, 0, "")
        try:
            workspace, _config, result = run_service(
                workspace_path,
                RunOptions(),
                apply_state=True,
                progress=self._record_progress,
            )
            response = {
                "ok": True,
                "workspace": workspace.root,
                "project_view": workspace.project_view,
                "result": _ui_result_dict(result),
            }
            self._last_project_view = workspace.project_view
            self._last_analysis = (workspace.root, response["result"])
            self._last_result = result
            return response
        except (WorkspaceError, ConfigError, RegistryError, state_mod.StateError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"Analysis failed unexpectedly: {exc}"}
        finally:
            # A poll that arrives after the answer must not keep the page
            # showing a phase that is already over.
            self._progress = dict(self.IDLE_PROGRESS)

    def rules(self, workspace_path: str) -> dict:
        """Return the human-analyzer rule catalog and project settings."""
        try:
            workspace = WorkspaceResolver(workspace=workspace_path).resolve()
            config = load_config(workspace.config_path)
            catalog = []
            for rule_id, rule in sorted(load_builtin_rules().items()):
                try:
                    documentation = Path(rule.doc_path).read_text(encoding="utf-8")
                except OSError:
                    documentation = rule.summary
                catalog.append({
                    "id": rule.id, "title": rule.title, "summary": rule.summary,
                    "severity": rule.severity, "topic": rule.topic,
                    "fixable": rule.fix is not None,
                    "enabled": config.enabled_for(rule.id),
                    "documentation": documentation,
                })
            return {"ok": True, "rules": catalog, "config_path": workspace.config_path or ""}
        except (WorkspaceError, ConfigError, RegistryError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def set_rule_enabled(self, workspace_path: str, rule_id: str, enabled: bool) -> dict:
        """Persist one project-level rule switch in ``cts-analyze.toml``."""
        rule_id = (rule_id or "").strip().upper()
        try:
            if rule_id not in load_builtin_rules():
                return {"ok": False, "error": f"Unknown rule: {rule_id}"}
            workspace = WorkspaceResolver(workspace=workspace_path).resolve()
            path = Path(workspace.config_path or Path(workspace.root) / "cts-analyze.toml")
            set_rule_enabled(path, rule_id, enabled)
            return {"ok": True}
        except (WorkspaceError, ConfigError, RegistryError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def choose_workspace(self) -> str:
        """Open a native folder dialog; called only from the local window."""
        import webview

        folders = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return folders[0] if folders else ""

    def open_file(self, relative_path: str, line: int | None = None) -> dict:
        """Open an analyzed source file, preferably at its finding line."""
        if not self._last_project_view:
            return {"ok": False, "error": "Run analysis before opening a file."}
        root = Path(self._last_project_view).resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return {"ok": False, "error": "Invalid source path."}
        if not target.is_file():
            return {"ok": False, "error": f"Source file no longer exists: {relative_path}"}
        if line:
            try:
                subprocess.Popen(
                    ["code", "-g", f"{target}:{int(line)}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {"ok": True, "opened_at_line": int(line)}
            except (OSError, ValueError):
                pass
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]  # Windows only.
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def _read_source(self, relative_path):
        """Return ``(lines, None)`` for an analyzed ST file, or ``(None, error)``.

        The webview is allowed to inspect only ST files below the last analyzed
        project-view.  This keeps the context panel useful without turning the
        UI bridge into a general-purpose file reader.
        """
        if not self._last_project_view:
            return None, {"ok": False, "error": "Run analysis before opening source context."}
        target, error = self._source_target(self._last_project_view, relative_path)
        if error is not None:
            return None, error
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            # ST uses LF as its source line separator.  ``splitlines`` also
            # treats U+0085 inside an exported comment as a new source line.
            return _repair_mojibake(text).split("\n"), None
        except OSError as exc:
            return None, {"ok": False, "error": str(exc)}

    @staticmethod
    def _source_target(project_view, relative_path):
        root = Path(project_view).resolve()
        target = (root / str(relative_path or "")).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None, {"ok": False, "error": "Invalid source path."}
        if target.suffix.lower() != ".st":
            return None, {"ok": False, "error": "Only .st source context is available."}
        if not target.is_file():
            return None, {"ok": False, "error": f"Source file no longer exists: {relative_path}"}
        return target, None

    def source_context(
        self, relative_path: str, line: int | None = None, radius: int = 5
    ) -> dict:
        """Return a small source excerpt for the selected finding."""
        lines, error = self._read_source(relative_path)
        if error is not None:
            return error
        selected = max(1, int(line or 1))
        safe_radius = max(1, min(int(radius or 5), 12))
        start = max(1, selected - safe_radius)
        end = min(len(lines), selected + safe_radius)
        return {
            "ok": True,
            "path": str(relative_path),
            "start_line": start,
            "lines": [
                {"number": number, "text": lines[number - 1], "hot": number == selected}
                for number in range(start, end + 1)
            ],
        }

    def source_spans(
        self, relative_path: str, lines: list | None = None, radius: int = 5
    ) -> dict:
        """Return excerpts covering every occurrence line of one case.

        The list groups a whole file into a single case, so the detail panel
        has to show all of its occurrences at once.  Windows that touch or
        overlap are coalesced; a window that follows a skipped region carries
        ``gap_before`` so the page can draw a separator instead of implying
        the excerpt is contiguous.
        """
        source, error = self._read_source(relative_path)
        if error is not None:
            return error
        wanted = set()
        for value in lines or []:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= len(source):
                wanted.add(number)
        if not wanted:
            return {"ok": False, "error": "No source lines to show for this case."}
        safe_radius = max(1, min(int(radius or 5), 12))
        windows: list[list[int]] = []
        for number in sorted(wanted):
            start = max(1, number - safe_radius)
            end = min(len(source), number + safe_radius)
            if windows and start <= windows[-1][1] + 1:
                windows[-1][1] = max(windows[-1][1], end)
            else:
                windows.append([start, end])
        return {
            "ok": True,
            "path": str(relative_path),
            "hot_lines": sorted(wanted),
            "spans": [
                {
                    "start_line": start,
                    "gap_before": index > 0,
                    "lines": [
                        {"number": n, "text": source[n - 1], "hot": n in wanted}
                        for n in range(start, end + 1)
                    ],
                }
                for index, (start, end) in enumerate(windows)
            ],
        }

    def _autofix_context(self, workspace_path: str, finding: dict):
        if not isinstance(finding, dict):
            return None, None, None, {"ok": False, "error": "Finding data is missing."}
        rule_id = str(finding.get("rule_id", "")).strip()
        if not rule_id:
            return None, None, None, {"ok": False, "error": "Finding rule is missing."}
        try:
            workspace = WorkspaceResolver(workspace=workspace_path).resolve()
            target, error = self._source_target(
                workspace.project_view,
                (finding.get("location") or {}).get("path", ""),
            )
            if error is not None:
                return None, None, None, error
            rule = load_builtin_rules().get(rule_id)
            if rule is None or rule.fix is None:
                return None, None, None, {
                    "ok": False,
                    "error": f"Rule {rule_id} does not provide a safe autofix.",
                }
            before, newline, had_bom, raw = _read_autofix_source(target)
            after = rule.fix(before, finding)
            if not isinstance(after, str) or after == before:
                # The raw bytes ride along so that :meth:`autofix_apply` can
                # still run its stale-source guard before this verdict wins.
                return None, None, None, {
                    "ok": False,
                    "error": "This finding has no applicable source change.",
                    "raw": raw,
                }
            return target, rule, after, {
                "newline": newline,
                "had_bom": had_bom,
                "raw": raw,
                "text_lf": before,
            }
        except (WorkspaceError, ConfigError, RegistryError, OSError) as exc:
            return None, None, None, {"ok": False, "error": str(exc)}
        except Exception as exc:
            return None, None, None, {
                "ok": False,
                "error": f"Autofix preview failed unexpectedly: {exc}",
            }

    def autofix_preview(self, workspace_path: str, finding: dict) -> dict:
        """Return a non-mutating unified diff for a registered rule fixer.

        ``before_hash`` is the SHA-256 of the on-disk bytes, so an external
        edit that only changes line endings is still detected as "changed".
        """
        target, rule, after, meta = self._autofix_context(workspace_path, finding)
        if isinstance(meta, dict) and meta.get("ok") is False:
            return meta
        relative = str((finding.get("location") or {}).get("path", "")).replace("\\", "/")
        diff = list(
            difflib.unified_diff(
                meta["text_lf"].splitlines(),
                after.splitlines(),
                fromfile="Before",
                tofile="After",
                lineterm="",
            )
        )
        return {
            "ok": True,
            "rule_id": rule.id,
            "rule_title": rule.title,
            "path": relative,
            "before_hash": hashlib.sha256(meta["raw"]).hexdigest(),
            "diff": diff,
        }

    def autofix_apply(
        self, workspace_path: str, finding: dict, before_hash: str = ""
    ) -> dict:
        """Apply a previously previewed fix only if the source is unchanged.

        ``before_hash`` is the SHA-256 of the on-disk bytes captured at
        preview time; it guards against an external edit, including one that
        only changed line endings.
        """
        target, rule, after, meta = self._autofix_context(workspace_path, finding)
        if isinstance(meta, dict) and meta.get("ok") is False:
            # The fixer reported an error.  When it is the "no applicable
            # source change" verdict, the on-disk raw bytes still ride along so
            # an external edit that only changed line endings is caught here.
            if "raw" in meta:
                current_hash = hashlib.sha256(meta["raw"]).hexdigest()
                if before_hash and before_hash != current_hash:
                    return {
                        "ok": False,
                        "error": "Source changed after the preview. Generate a new preview first.",
                    }
            return meta
        current_hash = hashlib.sha256(meta["raw"]).hexdigest()
        if before_hash and before_hash != current_hash:
            return {
                "ok": False,
                "error": "Source changed after the preview. Generate a new preview first.",
            }
        try:
            with target.open("w", encoding="utf-8", newline="") as handle:
                # Restore the original dominant line ending and a leading BOM.
                # ``_read_autofix_source`` normalizes a mixed file to CRLF, so
                # writing CRLF for every line ending is the intentional rule.
                if meta["had_bom"]:
                    handle.write("\ufeff")
                handle.write(after.replace("\n", meta["newline"]))
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        relative = str((finding.get("location") or {}).get("path", "")).replace("\\", "/")
        return {"ok": True, "rule_id": rule.id, "path": relative}

    def suppression_entry(self, finding: dict) -> dict:
        """Return a ready-to-edit TOML suppression entry for one finding."""
        if not isinstance(finding, dict) or not str(finding.get("fingerprint", "")).strip():
            return {"ok": False, "error": "Finding fingerprint is missing."}
        import json

        lines = [
            "[[suppress]]",
            f"fingerprint = {json.dumps(str(finding['fingerprint']))}",
        ]
        for key in ("rule_id", "unit_id"):
            value = str(finding.get(key, "")).strip()
            if value:
                lines.append(f"{key} = {json.dumps(value)}")
        lines.append('reason = "TODO: explain why this finding is accepted"')
        return {"ok": True, "text": "\n".join(lines) + "\n"}

    def triage(self, workspace_path: str, finding: dict, action: str, reason: str = "") -> dict:
        """Apply one UI triage decision using the CLI's canonical state format."""
        return self.triage_many(workspace_path, [finding], action, reason)

    def triage_many(
        self, workspace_path: str, findings: list[dict], action: str, reason: str = ""
    ) -> dict:
        """Apply one decision atomically to several findings."""
        action = (action or "").strip()
        if action not in ("suppress", "fix-later", "baseline"):
            return {"ok": False, "error": f"Unknown triage action: {action}"}
        findings = findings if isinstance(findings, list) else []
        if not findings or any(not str((item or {}).get("fingerprint", "")).strip() for item in findings):
            return {"ok": False, "error": "Finding fingerprint is missing."}
        if action == "suppress" and not reason.strip():
            return {"ok": False, "error": "A reason is required for suppression."}
        try:
            workspace = WorkspaceResolver(workspace=workspace_path).resolve()
            if self._last_result is not None and self._last_project_view:
                if Path(workspace.project_view).resolve() == Path(self._last_project_view).resolve():
                    result = self._last_result
                else:
                    _workspace, _config, result = run_service(
                        workspace_path, RunOptions(), apply_state=False
                    )
            else:
                _workspace, _config, result = run_service(
                    workspace_path, RunOptions(), apply_state=False
                )
            decisions = [
                {
                    "fingerprint": str(item["fingerprint"]).strip(),
                    "action": action,
                    "reason": reason.strip(),
                    "note": reason.strip() if action == "fix-later" else "",
                    "rule_id": str(item.get("rule_id", "")),
                    "unit_id": str(item.get("unit_id", "")),
                }
                for item in findings
            ]
            summary = apply_decisions(workspace, result, decisions)
            return {"ok": True, "summary": summary}
        except (WorkspaceError, ConfigError, RegistryError, TriageError, state_mod.StateError, OSError) as exc:
            return {"ok": False, "error": str(exc)}


def _resolve_initial_workspace(initial_workspace: str = "") -> str:
    """Resolve the explicit workspace or the CODESYS launcher fallback."""
    return (initial_workspace or os.environ.get("CTS_INITIAL_WORKSPACE", "")).strip()


def launch(initial_workspace: str = "") -> int:
    """Create the native window, or explain how to install the UI extra."""
    initial_workspace = _resolve_initial_workspace(initial_workspace)
    try:
        import webview
    except ImportError:
        print(
            "[ERROR] The desktop UI is optional. Install it with: "
            'pip install -e ".[ui]"',
            file=__import__("sys").stderr,
        )
        return 2

    page = Path(__file__).with_name("ui_assets") / "index.html"
    webview.create_window(
        "CTS Static Analysis",
        page.as_uri(),
        js_api=AnalyzerApi(initial_workspace),
        width=1240,
        height=780,
        min_size=(980, 640),
    )
    webview.start()
    return 0
