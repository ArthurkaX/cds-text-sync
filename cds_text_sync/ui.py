"""Optional local desktop UI for the offline static analyzer.

The UI is deliberately a thin adapter over the analysis engine: it never
talks to CODESYS or the daemon, and a normal run does not write state.
``pywebview`` is imported only by :func:`launch`, so the main CLI remains
usable without its optional dependency.
"""

from __future__ import annotations

import os
from pathlib import Path

from cds_text_sync.analyze import state as state_mod
from cds_text_sync.analyze.config import ConfigError, load_config
from cds_text_sync.analyze.project import build_snapshot
from cds_text_sync.analyze.registry import RegistryError, load_builtin_rules
from cds_text_sync.analyze.runner import RunOptions, filter_result, run_analysis
from cds_text_sync.analyze.state import baseline_fingerprints, is_expired
from cds_text_sync.analyze.workspace import WorkspaceError, WorkspaceResolver


def analyze_workspace(workspace_path: str) -> dict:
    """Return the same JSON envelope that ``cts analyze`` would display.

    Errors are data rather than exceptions because they cross the JavaScript
    bridge.  This function intentionally performs no baseline/triage writes.
    """
    try:
        workspace = WorkspaceResolver(workspace=workspace_path).resolve()
        config = load_config(workspace.config_path)
        snapshot = build_snapshot(workspace.project_view)
        result = run_analysis(workspace, snapshot, config, RunOptions())
        state_mod.validate_baseline_schema(workspace.state_dir)
        suppressions = state_mod.read_suppressions(workspace.state_dir)
        baseline, _ = state_mod.read_baseline(workspace.state_dir)
        suppressed = {row["fingerprint"] for row in suppressions if not is_expired(row)}
        filter_result(result, suppressed, baseline_fingerprints(baseline))
        return {
            "ok": True,
            "workspace": workspace.root,
            "project_view": workspace.project_view,
            "result": result.to_dict(),
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

    def initial_state(self) -> dict:
        return {"workspace": self.initial_workspace}

    def analyze(self, workspace_path: str) -> dict:
        response = analyze_workspace(workspace_path)
        if response.get("ok"):
            self._last_project_view = response["project_view"]
        return response

    def rules(self, workspace_path: str) -> dict:
        """Return the human-analyzer rule catalog and project settings."""
        try:
            workspace = WorkspaceResolver(workspace=workspace_path).resolve()
            config = load_config(workspace.config_path)
            catalog = []
            topics = {1: "Code quality", 2: "Interfaces", 4: "Data consistency"}
            for rule_id, rule in sorted(load_builtin_rules().items()):
                try:
                    documentation = Path(rule.doc_path).read_text(encoding="utf-8")
                except OSError:
                    documentation = rule.summary
                catalog.append({
                    "id": rule.id, "title": rule.title, "summary": rule.summary,
                    "severity": rule.severity, "topic": topics.get(int(rule_id[3:]), "General"),
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
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            import re
            section = re.compile(rf"(?ms)^\[rules\.{re.escape(rule_id)}\]\s*$.*?(?=^\[|\Z)")
            value = "true" if enabled else "false"
            block = f"[rules.{rule_id}]\nenabled = {value}\n"
            match = section.search(text)
            if match:
                current = match.group(0)
                if re.search(r"(?m)^enabled\s*=", current):
                    current = re.sub(r"(?m)^enabled\s*=.*$", f"enabled = {value}", current, count=1)
                else:
                    current = current.rstrip() + f"\nenabled = {value}\n"
                text = text[:match.start()] + current + text[match.end():]
            else:
                text = text.rstrip() + ("\n\n" if text.strip() else "") + block
            path.write_text(text, encoding="utf-8", newline="\n")
            return {"ok": True}
        except (WorkspaceError, ConfigError, RegistryError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def choose_workspace(self) -> str:
        """Open a native folder dialog; called only from the local window."""
        import webview

        folders = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return folders[0] if folders else ""

    def open_file(self, relative_path: str) -> dict:
        """Open an analyzed source file with the Windows file association."""
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
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]  # Windows only.
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


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
