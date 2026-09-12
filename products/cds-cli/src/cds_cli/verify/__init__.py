"""``cts verify`` -- run every applicable check and return one verdict.

The command exists because an agent should not have to know the names of four
different checks, run them in the right order, and reduce four outputs to a
decision. It asks one question ("is this project in a shippable state?") and
answers it in one shape, with one exit code.

Offline stages are read-only: nothing here rewrites source, baseline or
suppression files. Build updates IDE state, and the opt-in test stage may
connect to a target and execute writes/resets from a test plan.
"""

import json
import os

from cds_cli._cli_io import _print_error, _print_info
from cds_cli.verify.model import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIPPED,
    StageResult,
    VerifyReport,
    VerifyStartError,
)
from cds_cli.verify.stages import (
    STAGE_NAMES,
    STAGES,
    VerifyContext,
    run_stage,
)

#: How far up the tree to look for a project-view/ before giving up.
_MAX_ANCESTORS = 6


def _resolve_sync_folder(sync_folder):
    """Find the sync folder without ever touching the daemon.

    Resolution is deliberately offline: asking the daemon for its sync folder
    would make even the offline stages pay a pipe timeout when no IDE is
    running, which is the common case for an agent. An explicit
    ``--sync-folder`` wins; otherwise walk up from the current directory
    looking for a ``project-view/``, the same shape the analyzer resolves.
    """
    if sync_folder:
        base = os.path.abspath(sync_folder)
        # Accept project-view/ itself, as the other commands do.
        if os.path.basename(os.path.normpath(base)) == "project-view" and os.path.isdir(
            base
        ):
            base = os.path.dirname(os.path.normpath(base))
        if not os.path.isdir(base):
            raise VerifyStartError(f"No such folder: {base}")
        if not os.path.isdir(os.path.join(base, "project-view")):
            raise VerifyStartError(
                f"No project-view/ in {base}. Export the project once "
                "(cts export, or Project_export.py) before verifying."
            )
        return base

    current = os.path.abspath(os.getcwd())
    for _ in range(_MAX_ANCESTORS):
        if os.path.isdir(os.path.join(current, "project-view")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise VerifyStartError(
        "No project-view/ found here or in any parent folder. "
        "Pass --sync-folder <path> to point at the project."
    )


def _select_stages(only, with_test):
    """Pick the stages to run, validating ``--only`` against the registry."""
    if only:
        wanted = [name.strip() for name in only.split(",") if name.strip()]
        if not wanted:
            raise VerifyStartError("--only must name at least one stage")
        unknown = [n for n in wanted if n not in STAGE_NAMES]
        if unknown:
            raise VerifyStartError(
                "Unknown stage(s): {0}. Available: {1}".format(
                    ", ".join(unknown), ", ".join(STAGE_NAMES)
                )
            )
        # Registry order, not the order the user typed: the cheap offline
        # checks must run before the slow one that occupies the IDE.
        return [s for s in STAGES if s.name in wanted]

    return [s for s in STAGES if not s.opt_in or (with_test and s.name == "test")]


def _next_steps(report, selected, with_test):
    """Concrete commands to run next. The gate advises, not just judges."""
    steps = []
    by_name = {s.stage: s for s in report.stages}

    for stage in report.stages:
        if stage.status != STATUS_FAIL:
            continue
        if stage.stage == "analyze":
            steps.append("cts analyze --pretty        # full findings with context")
        elif stage.stage == "visu-sketch":
            steps.append(
                "cts visu lint --svg <sketch> --fix   # snaps the mechanical findings"
            )
        elif stage.stage == "build":
            steps.append("cts read-log --last 50      # full compiler output")
        elif stage.stage == "test":
            steps.append("cts test --pretty           # per-step test detail")

    build = by_name.get("build")
    if build is not None and build.status == STATUS_SKIPPED:
        if build.reason_code in ("stale_ide", "identity_unknown"):
            steps.append(
                "cts import --save  # apply current project-view/ to the IDE, then re-run verify"
            )
        else:
            steps.append(
                "open the project in CODESYS and re-run  # for a compiler verdict"
            )

    ran_test = any(s.name == "test" for s in selected)
    if not ran_test and not with_test and report.verdict != STATUS_FAIL:
        steps.append("cts verify --with-test      # also run the .test/ plans")

    return steps


def run_verify(args, output_fmt="json"):
    """Entry point for the ``verify`` command. Returns an exit code."""
    try:
        sync_folder = _resolve_sync_folder(getattr(args, "sync_folder", "") or "")
        selected = _select_stages(
            getattr(args, "only", "") or "", getattr(args, "with_test", False)
        )
    except VerifyStartError as exc:
        _print_error(str(exc))
        return exc.exit_code

    incomplete = getattr(args, "incomplete", "warn") or "warn"

    ctx = VerifyContext(
        sync_folder=sync_folder,
        project_view=os.path.join(sync_folder, "project-view"),
        probe_timeout=getattr(args, "probe_timeout", 2.0),
        build_timeout=getattr(args, "build_timeout", None),
        test_timeout=getattr(args, "test_timeout", None),
        test_file=getattr(args, "test_file", "") or "",
    )

    report = VerifyReport(sync_folder=sync_folder)
    for stage in selected:
        # CICD execution is meaningful only after a selected build delivered a
        # complete successful verdict. An explicit ``--only test`` remains
        # supported for users who intentionally rely on an already-built
        # application; the dependency guard applies whenever build was part of
        # this run and failed or was incomplete.
        if stage.name == "test":
            build = next((item for item in report.stages if item.stage == "build"), None)
            if build is not None and (
                build.status != STATUS_PASS or not build.complete
            ):
                report.add(
                    StageResult.skipped(
                        "test",
                        "test requires a complete successful build in this run",
                        reason_code="dependency_failed",
                    )
                )
                continue
        report.add(run_stage(stage, ctx))

    report.next_steps = _next_steps(
        report, selected, getattr(args, "with_test", False)
    )

    if output_fmt == "text":
        print(report.to_text(incomplete))
    else:
        print(json.dumps(report.to_dict(incomplete), indent=2, ensure_ascii=False))

    if not report.complete and incomplete == "warn":
        skipped = [s.stage for s in report.stages if s.incomplete]
        _print_info(
            "Incomplete: {0} did not deliver a verdict. "
            "Use --incomplete error to make this fatal.".format(", ".join(skipped))
        )

    return report.exit_code(incomplete)


__all__ = ["run_verify"]
