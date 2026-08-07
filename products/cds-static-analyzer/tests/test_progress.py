"""Contracts for the optional progress sink.

The desktop UI polls the running analysis so a long run does not look like a
hang.  What it shows must therefore be the pipeline's own account of what it
is doing - counts that come from the same loops that do the work - and the
report must never be able to affect the result it describes.
"""

from cds_static_analyzer.config import ResolvedConfig
from cds_static_analyzer.project import build_st_snapshot
from cds_static_analyzer.runner import RunOptions, run_analysis
from cds_static_analyzer.workspace import Workspace

from st_helpers import fixture_project_view


def _record():
    reports = []
    return reports, lambda phase, done, total, detail: reports.append(
        (phase, done, total, detail)
    )


def _run(progress=None):
    view = fixture_project_view()
    snapshot = build_st_snapshot(view, progress=progress)
    result = run_analysis(
        Workspace(root=".", project_view=view, state_dir="."),
        snapshot,
        ResolvedConfig(),
        RunOptions(),
        progress=progress,
    )
    return snapshot, result


def test_parse_reports_a_real_total_from_the_first_file():
    """The walk finishes before any file is read, so the very first report
    already knows how many there are - a bar that grows its own total looks
    like it is going backwards."""
    reports, sink = _record()
    snapshot, _result = _run(sink)

    parse = [row for row in reports if row[0] == "parse"]
    totals = {row[2] for row in parse}
    assert len(totals) == 1
    total = totals.pop()
    assert total >= len(snapshot.units) > 0
    assert [row[1] for row in parse] == list(range(1, total + 1))
    assert all(row[3] for row in parse)  # every report names its file


def test_phases_arrive_in_pipeline_order():
    reports, sink = _record()
    _run(sink)

    seen = []
    for phase, _done, _total, _detail in reports:
        if phase not in seen:
            seen.append(phase)
    assert seen == ["parse", "prepare", "rules", "finalize"]


def test_rule_reports_count_up_to_the_number_of_enabled_rules():
    reports, sink = _record()
    _snapshot, result = _run(sink)

    rules = [row for row in reports if row[0] == "rules"]
    assert [row[1] for row in rules] == list(range(1, len(rules) + 1))
    assert {row[2] for row in rules} == {len(rules)}
    # The names are the enabled rules, in the order they are dispatched.
    assert [row[3] for row in rules] == result.summary.rules_run


def test_a_run_without_a_sink_produces_the_same_result():
    _snapshot, quiet = _run(None)
    _reports, sink = _record()
    _snapshot, watched = _run(sink)

    assert [f.fingerprint for f in quiet.findings] == [
        f.fingerprint for f in watched.findings
    ]


def test_parallel_unit_dispatch_keeps_the_result_deterministic():
    view = fixture_project_view()
    snapshot = build_st_snapshot(view)
    workspace = Workspace(root=".", project_view=view, state_dir=".")
    quiet = run_analysis(
        workspace,
        snapshot,
        ResolvedConfig(),
        RunOptions(workers=1),
    )
    parallel = run_analysis(
        workspace,
        snapshot,
        ResolvedConfig(),
        RunOptions(workers=4),
    )
    assert [f.to_dict() for f in quiet.findings] == [
        f.to_dict() for f in parallel.findings
    ]
    assert [d.to_dict() for d in quiet.diagnostics] == [
        d.to_dict() for d in parallel.diagnostics
    ]


def test_a_failing_sink_cannot_take_the_run_with_it():
    """The analysis is the product and the report is decoration: a UI that
    dies mid-poll must not lose the run."""

    def broken(phase, done, total, detail):
        raise RuntimeError("the page went away")

    _snapshot, quiet = _run(None)
    _snapshot, despite = _run(broken)

    assert [f.fingerprint for f in despite.findings] == [
        f.fingerprint for f in quiet.findings
    ]
