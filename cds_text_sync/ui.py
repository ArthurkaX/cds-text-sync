"""Optional local desktop UI for the offline static analyzer.

The UI is deliberately a thin adapter over the analysis engine: it never
talks to CODESYS or the daemon, and a normal run does not write state.
``pywebview`` is imported only by :func:`launch`, so the main CLI remains
usable without its optional dependency.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from cds_text_sync.analyze import state as state_mod
from cds_text_sync.analyze.config import ConfigError, load_config, set_rule_enabled
from cds_text_sync.analyze.registry import RegistryError, load_builtin_rules
from cds_text_sync.analyze.runner import RunOptions
from cds_text_sync.analyze.service import analyze as run_service
from cds_text_sync.analyze.triage import TriageError, apply_decisions
from cds_text_sync.analyze.workspace import WorkspaceError, WorkspaceResolver


def analyze_workspace(workspace_path: str) -> dict:
    """Return the same JSON envelope that ``cts analyze`` would display.

    Errors are data rather than exceptions because they cross the JavaScript
    bridge.  This function intentionally performs no baseline/triage writes.
    """
    try:
        workspace, _config, result = run_service(
            workspace_path, RunOptions(), apply_state=True
        )
        return {
            "ok": True,
            "workspace": workspace.root,
            "project_view": workspace.project_view,
            "result": result.to_dict(),
            "_result_object": result,
        }
    except (WorkspaceError, ConfigError, RegistryError, state_mod.StateError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # Do not leave the window with an opaque bridge error.
        return {"ok": False, "error": f"Analysis failed unexpectedly: {exc}"}


class AnalyzerApi:
    """Methods exposed to the local pywebview page."""

    def __init__(self, initial_workspace: str = ""):
        self.initial_workspace = initial_workspace
        self._last_project_view = ""
        self._last_analysis = None
        self._last_result = None

    def initial_state(self) -> dict:
        return {"workspace": self.initial_workspace}

    def analyze(self, workspace_path: str) -> dict:
        response = analyze_workspace(workspace_path)
        if response.get("ok"):
            self._last_project_view = response["project_view"]
            self._last_analysis = (response["workspace"], response["result"])
            self._last_result = response.pop("_result_object", None)
        return response

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
                    "enabled": config.enabled_for(rule.id, True),
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
                workspace = WorkspaceResolver(workspace=workspace_path).resolve()
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


def launch(initial_workspace: str = "") -> int:
    """Create the native window, or explain how to install the UI extra."""
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
        min_size=(920, 600),
    )
    webview.start()
    return 0
