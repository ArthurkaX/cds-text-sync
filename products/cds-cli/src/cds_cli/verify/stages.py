"""The stages of the gate, and the registry that orders them.

Every stage is a callable ``(ctx) -> StageResult`` that must not raise: the gate
reports a broken stage as ``error`` and carries on, because a crash in one check
should not destroy the verdict of the others. ``run_stage`` enforces that.

Adding a stage is deliberately cheap -- write the callable, add one row to
``STAGES``. The next two rows to be added are ST semantics (phase 2) and the
compiled-screen checks; both were left out of the skeleton on purpose.
"""

import os
import time

from cds_text_sync.engine.reverse_pipe_client import send_command_reverse

from cds_cli.verify.model import (
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIPPED,
    Problem,
    StageResult,
)

#: Previews are generated artefacts, not sources. Linting them reports the
#: compiler's own output back at the author.
_PREVIEW_SUFFIXES = (".preview.svg",)

#: Sketches live here by convention -- it is the default output folder of
#: ``cts visu new``.
_SKETCH_DIR = ".visu"

#: Cap on a ``reason`` string. The pipe client raises long multi-line
#: diagnostics; the report is read by an agent, so keep the first line and let
#: ``cts daemon status`` be the place for the full story.
_MAX_REASON = 200


def _brief(exc):
    """First line of an exception message, capped."""
    text = str(exc).strip().splitlines()
    head = text[0].strip() if text else type(exc).__name__
    if len(head) > _MAX_REASON:
        head = head[: _MAX_REASON - 3] + "..."
    return head


class VerifyContext:
    """Everything a stage needs, resolved once."""

    def __init__(
        self,
        sync_folder,
        project_view="",
        probe_timeout=2.0,
        build_timeout=None,
        test_timeout=None,
        test_file="",
    ):
        self.sync_folder = sync_folder
        self.project_view = project_view
        self.probe_timeout = probe_timeout
        self.build_timeout = build_timeout
        self.test_timeout = test_timeout
        self.test_file = test_file
        # Cached daemon liveness: probing once keeps a multi-stage run from
        # paying the timeout for every daemon-backed stage.
        self._daemon_alive = None
        self._daemon_reason = ""

    def daemon_alive(self):
        """Probe the daemon once, cheaply, and remember the answer.

        This exists because the normal daemon path is not safe for
        orchestration: ``_daemon_timeout`` in the daemon handlers makes its own
        ``timeout_profile`` call with a 10s budget and swallows the failure, so
        a dead daemon costs ten seconds *before* the real request is even sent.
        A short ``ping`` up front turns that into a fast, honest "skipped".
        """
        if self._daemon_alive is None:
            try:
                resp = send_command_reverse("ping", {}, timeout=self.probe_timeout)
                self._daemon_alive = bool(resp.get("ok"))
                if not self._daemon_alive:
                    self._daemon_reason = str(
                        resp.get("error") or "daemon answered but not ok"
                    )
            except Exception as exc:
                # Every transport failure in reverse_pipe_client is a plain
                # RuntimeError -- there is no dedicated "not running" type, so
                # the message is the only signal available.
                self._daemon_alive = False
                self._daemon_reason = (
                    f"daemon not responding ({self.probe_timeout}s probe): "
                    f"{_brief(exc)}"
                )
        return self._daemon_alive

    @property
    def daemon_reason(self):
        return self._daemon_reason


# -- analyze ------------------------------------------------------------------


def stage_analyze(ctx):
    """Static analysis of the exported ``.st`` files. Offline, in-process."""
    from cds_static_analyzer import runner, service

    workspace, config, result = service.analyze(ctx.sync_folder)

    # ``incomplete_override="ignore"`` keeps this to a pass/fail answer about
    # the *code*; incompleteness is the report's business, not the stage's.
    code = runner.exit_code(result, config, incomplete_override="ignore")

    problems = []
    for finding in result.findings:
        location = getattr(finding, "location", None)
        problems.append(
            Problem(
                message=finding.message,
                severity=finding.severity,
                rule=finding.rule_id,
                file=getattr(location, "path", "") or "",
                line=getattr(location, "line", None),
            )
        )

    summary = {}
    if getattr(result, "summary", None) is not None:
        summary = {
            "findings": getattr(result.summary, "total", len(result.findings)),
            "by_severity": dict(getattr(result.summary, "by_severity", {}) or {}),
            "files": getattr(result.summary, "files", None),
            "fail_on": config.fail_on,
        }
        summary = {k: v for k, v in summary.items() if v is not None}

    reason = ""
    if not result.complete:
        count = len(getattr(result, "diagnostics", []) or [])
        reason = f"analysis incomplete: {count} diagnostic(s)"

    return StageResult(
        "analyze",
        STATUS_FAIL if code else STATUS_PASS,
        reason=reason,
        summary=summary,
        problems=problems,
        complete=bool(result.complete),
    )


# -- visu sketches ------------------------------------------------------------


def _find_sketches(sync_folder):
    """Sketch SVGs under ``.visu/``, excluding generated previews."""
    root = os.path.join(sync_folder, _SKETCH_DIR)
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if not name.lower().endswith(".svg"):
                continue
            if any(name.lower().endswith(s) for s in _PREVIEW_SUFFIXES):
                continue
            found.append(os.path.join(dirpath, name))
    return sorted(found)


def stage_visu_sketch(ctx):
    """Design lint over every sketch in ``.visu/``. Offline, pure function."""
    from cds_text_sync.visu.lint import lint_svg

    sketches = _find_sketches(ctx.sync_folder)
    if not sketches:
        return StageResult.skipped(
            "visu-sketch", f"no sketches found in {_SKETCH_DIR}/"
        )

    problems = []
    fatal = 0
    unreadable = 0
    tool_errors = 0
    tool_error_reason = ""
    for path in sketches:
        rel = os.path.relpath(path, ctx.sync_folder)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            findings, _parsed = lint_svg(text, project_dir=ctx.project_view or None)
        except OSError as exc:
            # A missing/locked file is an inability to inspect the project,
            # not a project finding. Keep any findings from other sketches,
            # but make the stage incomplete so CI cannot mistake it for a
            # complete answer.
            tool_errors += 1
            if not tool_error_reason:
                tool_error_reason = f"could not read {rel}: {_brief(exc)}"
            continue
        except Exception as exc:
            # Parse/validation failures are real defects in the authored SVG.
            unreadable += 1
            fatal += 1
            problems.append(
                Problem(
                    message=f"could not lint sketch: {exc}",
                    severity="error",
                    rule="sketch-unreadable",
                    file=rel,
                )
            )
            continue

        for finding in findings:
            if finding.severity == "error":
                fatal += 1
            index = getattr(finding, "index", None)
            problems.append(
                Problem(
                    message=finding.message,
                    severity=finding.severity,
                    rule=finding.rule,
                    file=rel,
                    where="" if index is None else f"elem {index}",
                )
            )

    summary = {
        "sketches": len(sketches),
        "findings": len(problems),
        "errors": fatal,
    }
    if unreadable:
        summary["unreadable"] = unreadable
    if tool_errors:
        summary["tool_errors"] = tool_errors

    # Only ``error`` severity is fatal, matching what ``cts visu lint`` already
    # does without ``--strict``. Warnings are reported, not fatal.
    return StageResult(
        "visu-sketch",
        STATUS_FAIL if fatal else (STATUS_ERROR if tool_errors else STATUS_PASS),
        reason=tool_error_reason,
        reason_code="tool_error" if tool_errors else "",
        summary=summary,
        problems=problems,
        complete=not tool_errors,
    )


# -- build --------------------------------------------------------------------


def _daemon_call(ctx, method, params, timeout, stage_name):
    """Send one daemon request, mapping failures onto stage statuses.

    Returns ``(response, stage_result)``; exactly one is non-None. The
    distinction that matters: a dead daemon is ``skipped`` (nothing was
    learned), while a daemon that answered with a refusal is ``error``.
    """
    if not ctx.daemon_alive():
        return None, StageResult.skipped(
            stage_name, ctx.daemon_reason, reason_code="daemon_unavailable"
        )
    try:
        return send_command_reverse(method, params, timeout=timeout), None
    except Exception as exc:
        return None, StageResult.skipped(
            stage_name,
            f"daemon stopped responding during {method}: {_brief(exc)}",
            reason_code="daemon_timeout",
        )


def stage_build(ctx):
    """Compile the active application through the IDE. Needs the daemon."""
    from cds_cli.verify.fingerprint import workspace_fingerprint

    expected_fingerprint, fingerprint_complete, fingerprint_errors = (
        workspace_fingerprint(ctx.sync_folder)
    )
    params = {}
    if fingerprint_complete:
        params["workspace_fingerprint"] = expected_fingerprint
    resp, skipped = _daemon_call(
        ctx, "build", params, ctx.build_timeout or 120, "build"
    )
    if skipped is not None:
        return skipped

    if not isinstance(resp, dict):
        return StageResult.errored("build", "daemon returned a non-object response")

    data = resp.get("data")
    if not resp.get("ok") and not isinstance(data, dict):
        # No payload means the daemon refused before compiling -- no project
        # open, no application. Nothing was verified.
        return StageResult.errored(
            "build",
            str(resp.get("error") or "build refused"),
            reason_code="daemon_refused",
        )
    if not isinstance(data, dict):
        return StageResult.errored(
            "build", "daemon returned no build payload", reason_code="invalid_payload"
        )

    # Newer daemons report the sync root used by the active IDE project. A
    # mismatch means the compiler answered for another checkout; do not turn
    # that answer into evidence about this workspace. Older daemons omit the
    # field and remain compatible until the full import-freshness handshake lands.
    reported_sync = data.get("sync_folder")
    if reported_sync:
        expected = os.path.normcase(os.path.normpath(os.path.abspath(ctx.sync_folder)))
        actual = os.path.normcase(os.path.normpath(os.path.abspath(str(reported_sync))))
        if expected != actual:
            return StageResult.skipped(
                "build",
                "IDE sync-folder does not match the requested workspace",
                reason_code="stale_ide",
            )

    # Newer daemons echo a content fingerprint computed from their configured
    # sync folder.  A mismatch means the IDE built a different snapshot (or
    # the files changed while the request was in flight), so its success is
    # not evidence about this workspace.  Omitted fields remain compatible
    # with older daemons until the full import-freshness handshake lands.
    reported_fingerprint = data.get("workspace_fingerprint")
    reported_fingerprint_complete = data.get("workspace_fingerprint_complete")
    if reported_fingerprint_complete is not None and not isinstance(
        reported_fingerprint_complete, bool
    ):
        return StageResult.errored(
            "build",
            "invalid build payload: workspace_fingerprint_complete must be boolean",
            reason_code="invalid_payload",
        )
    if fingerprint_complete and reported_fingerprint_complete is False:
        return StageResult.skipped(
            "build",
            "IDE could not compute a complete workspace fingerprint",
            reason_code="identity_unknown",
        )
    if reported_fingerprint:
        if not isinstance(reported_fingerprint, str) or len(reported_fingerprint) != 64:
            return StageResult.errored(
                "build",
                "invalid build payload: workspace_fingerprint must be SHA-256",
                reason_code="invalid_payload",
            )
        if fingerprint_complete and reported_fingerprint.lower() != expected_fingerprint:
            return StageResult.skipped(
                "build",
                "IDE workspace fingerprint does not match the requested workspace",
                reason_code="stale_ide",
            )

    import_freshness = data.get("import_freshness")
    if import_freshness is not None:
        if import_freshness not in ("verified", "stale", "unknown"):
            return StageResult.errored(
                "build",
                "invalid build payload: import_freshness must be verified, stale, or unknown",
                reason_code="invalid_payload",
            )
        if import_freshness == "stale":
            return StageResult(
                "build",
                STATUS_SKIPPED,
                reason="workspace has changed since the last successful IDE import",
                reason_code="stale_ide",
                summary={"import_freshness": import_freshness},
                complete=False,
            )
        if import_freshness == "unknown":
            return StageResult(
                "build",
                STATUS_SKIPPED,
                reason="IDE import freshness could not be confirmed",
                reason_code="identity_unknown",
                summary={"import_freshness": import_freshness},
                complete=False,
            )

    errors = data.get("errors", 0)
    warnings = data.get("warnings", 0)
    for field, value in (("errors", errors), ("warnings", warnings)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return StageResult.errored(
                "build",
                f"invalid build payload: {field} must be a non-negative number",
                reason_code="invalid_payload",
            )
    errors = int(errors)
    warnings = int(warnings)

    messages = data.get("messages") or []
    if not isinstance(messages, list):
        return StageResult.errored(
            "build", "invalid build payload: messages must be a list", reason_code="invalid_payload"
        )

    problems = []
    malformed_messages = 0
    for message in messages:
        if not isinstance(message, dict):
            malformed_messages += 1
            continue
        severity = str(message.get("severity", ""))
        if "Error" not in severity:
            continue
        problems.append(
            Problem(
                message=str(message.get("text", "")),
                severity="error",
                rule=str(message.get("code", "")),
                where=str(message.get("object", "")),
            )
        )

    summary = {
        "application": data.get("application", ""),
        "errors": errors,
        "warnings": warnings,
    }
    if reported_fingerprint:
        summary["workspace_fingerprint"] = reported_fingerprint
    if import_freshness is not None:
        summary["import_freshness"] = import_freshness
    if not fingerprint_complete:
        summary["workspace_fingerprint_complete"] = False
        if fingerprint_errors:
            summary["workspace_fingerprint_errors"] = len(fingerprint_errors)
    diagnostics_complete = bool(data.get("diagnostics_complete", True)) and not malformed_messages
    if not diagnostics_complete:
        summary["diagnostics_complete"] = False
    elapsed = data.get("elapsed_seconds")
    if elapsed is not None:
        summary["elapsed_seconds"] = elapsed

    if errors == 0 and problems:
        errors = len(problems)
        summary["errors"] = errors
    if not resp.get("ok") and errors == 0 and not problems:
        return StageResult.errored(
            "build",
            "daemon returned ok=false without compiler diagnostics",
            reason_code="invalid_payload",
        )

    reason = ""
    reason_code = ""
    if not diagnostics_complete:
        reason = "compiler diagnostics are incomplete"
        reason_code = "tool_error"

    # A compiler error is a confirmed project failure. Missing diagnostics are
    # reported as incomplete even when the daemon's top-level flag says ok.
    build_failed = errors > 0 or bool(problems) or not resp.get("ok")
    status = STATUS_FAIL if build_failed else STATUS_PASS
    if not diagnostics_complete and not build_failed:
        status = STATUS_ERROR
    return StageResult(
        "build",
        status,
        reason=reason,
        reason_code=reason_code,
        summary=summary,
        problems=problems,
        complete=diagnostics_complete,
    )


# -- test ---------------------------------------------------------------------


def _test_payload_verdict(data):
    """Return ``(failed, complete, reason)`` from a CICD payload.

    The daemon's transport ``ok`` only says that the request was handled. The
    actual test verdict is nested in ``data`` (and, for bulk runs, in each
    result). Keeping this reduction in one place prevents a successful RPC
    carrying failed tests from becoming a false ``pass``.
    """
    if not isinstance(data, dict):
        return False, False, "test payload is not an object"

    summary = data.get("summary")
    if summary is not None and not isinstance(summary, dict):
        return False, False, "test payload summary is not an object"
    summary = summary or {}
    not_ok = summary.get("not_ok")
    if not_ok is not None:
        if isinstance(not_ok, bool) or not isinstance(not_ok, (int, float)) or not_ok < 0:
            return False, False, "test payload summary.not_ok is invalid"
        not_ok = int(not_ok)

    status = str(data.get("status", "")).strip().upper()
    nested_ok = data.get("ok")
    if nested_ok is not None and not isinstance(nested_ok, bool):
        return False, False, "test payload ok is not boolean"

    results = data.get("results", [])
    if results is None:
        results = []
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        return False, False, "test payload results is not a list of objects"

    result_failed = False
    for entry in results:
        if str(entry.get("status", "")).upper() == "FAIL" or entry.get("error"):
            result_failed = True
        tests = entry.get("tests", []) or []
        if not isinstance(tests, list) or any(not isinstance(test, dict) for test in tests):
            return False, False, "test payload contains an invalid tests list"
        if any(str(test.get("status", "")).upper() == "FAIL" for test in tests):
            result_failed = True

    if status in ("FAIL", "FAILED"):
        return True, True, ""
    if status in ("SUCCESS", "PASS"):
        if nested_ok is False or (not_ok is not None and not_ok > 0) or result_failed:
            return True, True, ""
        return False, True, ""
    if status:
        return False, False, f"unknown test payload status: {status}"

    # Accept a status-less payload only when it contains an explicit nested
    # boolean verdict. Otherwise there is not enough evidence for a pass.
    if nested_ok is not None:
        return (not nested_ok) or bool(not_ok), True, ""
    if not_ok is not None:
        return not_ok > 0, True, ""
    if result_failed:
        return True, True, ""
    return False, False, "test payload has no verdict"


def stage_test(ctx):
    """Run the JSON test plans from ``.test/``. Opt-in: connects to the PLC."""
    params = {}
    if ctx.test_file:
        params["file"] = ctx.test_file

    resp, skipped = _daemon_call(
        ctx, "cicd", params, ctx.test_timeout or 120, "test"
    )
    if skipped is not None:
        return skipped

    if not isinstance(resp, dict):
        return StageResult.errored("test", "daemon returned a non-object response")

    data = resp.get("data")
    if not resp.get("ok") and not isinstance(data, dict):
        return StageResult.errored(
            "test",
            str(resp.get("error") or "test run refused"),
            reason_code="daemon_refused",
        )
    if not isinstance(data, dict):
        return StageResult.errored(
            "test", "daemon returned no test payload", reason_code="invalid_payload"
        )

    entries = data.get("results") or []
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        return StageResult.errored(
            "test", "invalid test payload: results must be a list", reason_code="invalid_payload"
        )

    problems = []
    for entry in entries:
        plan = entry.get("file") or entry.get("plan") or ""
        error = entry.get("error")
        if error:
            problems.append(
                Problem(message=str(error), severity="error", file=str(plan))
            )
        tests = entry.get("tests") or []
        if not isinstance(tests, list) or any(not isinstance(test, dict) for test in tests):
            return StageResult.errored(
                "test",
                "invalid test payload: tests must be a list",
                reason_code="invalid_payload",
            )
        for test in tests:
            if test.get("status") == "FAIL":
                name = test.get("name") or test.get("test") or "?"
                detail = test.get("message") or test.get("error") or "failed"
                problems.append(
                    Problem(
                        message=f"{name}: {detail}",
                        severity="error",
                        file=str(plan),
                    )
                )

    summary = dict(data.get("summary") or {})
    if data.get("status"):
        summary["status"] = data["status"]

    failed, complete, payload_reason = _test_payload_verdict(data)
    if failed and not problems:
        problems.append(
            Problem(
                message=payload_reason or "one or more tests failed",
                severity="error",
            )
        )
    if not complete:
        return StageResult(
            "test",
            STATUS_ERROR,
            reason=payload_reason,
            reason_code="invalid_payload",
            summary=summary,
            problems=problems,
            complete=False,
        )

    return StageResult(
        "test",
        STATUS_FAIL if failed else STATUS_PASS,
        summary=summary,
        problems=problems,
    )


# -- registry -----------------------------------------------------------------


class Stage:
    """One row of the gate: what to run, and whether it runs by default."""

    def __init__(self, name, func, needs_daemon=False, opt_in=False, help=""):
        self.name = name
        self.func = func
        self.needs_daemon = needs_daemon
        # Opt-in stages stay out of the default gate because they reach past
        # the project: ``test`` connects to a PLC and starts an application.
        self.opt_in = opt_in
        self.help = help


STAGES = [
    Stage(
        "analyze",
        stage_analyze,
        help="static analysis of the exported .st files",
    ),
    Stage(
        "visu-sketch",
        stage_visu_sketch,
        help="design lint of every SVG sketch in .visu/",
    ),
    Stage(
        "build",
        stage_build,
        needs_daemon=True,
        help="compile the active application through the IDE",
    ),
    Stage(
        "test",
        stage_test,
        needs_daemon=True,
        opt_in=True,
        help="run the JSON test plans from .test/ against the PLC",
    ),
]

STAGE_NAMES = [s.name for s in STAGES]


def run_stage(stage, ctx):
    """Run one stage, timing it and containing any crash as ``error``."""
    start = time.time()
    try:
        result = stage.func(ctx)
    except Exception as exc:
        result = StageResult.errored(stage.name, f"{type(exc).__name__}: {exc}")
    result.duration_ms = int((time.time() - start) * 1000)
    return result


__all__ = [
    "STAGES",
    "STAGE_NAMES",
    "Stage",
    "VerifyContext",
    "run_stage",
]
