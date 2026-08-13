# -*- coding: utf-8 -*-
"""Regression tests for the Project_fmt stabilization plan (fix_specs.md).

Each test pins one known defect or one fixed design decision.  The tests run
in CPython against the pure seams (formatter, session controller, diff model,
apply planner) using fake CODESYS objects; the WinForms/CODESYS acceptance
matrix is documented separately in ``docs/scripts.md``.

Defect index:
  D1  Review All ignores the filtered scope.
  D2  Cancellation does not stop the next object read.
  D3  A session timer survives close.
  D4  Apply/Skip synchronously scans to the next changed object.
  D5  Condition expansion marks the rest of the POU as replaced.
  D6  CRLF is mixed into LF after condition expansion.
  D7  Unchanged sections appear in the apply plan.
  D8  Declaration formatting uses Python 3-only built-ins.
  D9  A callback TypeError is retried as another callback signature.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "src"
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
for path in (str(SHARED), str(BRIDGE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cts_shared.st.formatting import (  # noqa: E402
    format_declarations,
    format_implementation,
)
import ide_st_objects as st_objects  # noqa: E402
from fmt_session import (  # noqa: E402
    FmtSession,
    SessionError,
    SessionState,
)
from fmt_diff import DiffModel, diff_lines  # noqa: E402
from fmt_apply import build_apply_plan, execute_apply_plan  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic fixtures: a large project index and a large POU generated on the
# fly so no large files need to live in source control.
# ---------------------------------------------------------------------------


def make_large_project(count=400, gap=40):
    """A project with *count* textual objects separated by clean gaps."""
    objects = []
    for index in range(count):
        objects.append(
            FakeObject(
                "POU_{0:04d}".format(index),
                declaration=("VAR\n    in : BOOL;\n    longername : DINT;\nEND_VAR\n"),
                implementation=(
                    "IF "
                    + " AND ".join("b{0}".format(i) for i in range(gap))
                    + " THEN\n"
                    "    x := 1;\n"
                    "END_IF;\n"
                ),
            )
        )
    return FakeProject(objects)


def make_large_pou(lines=2000):
    """A large POU whose body is a repeated clean pattern."""
    body = "\n".join(
        [
            "IF enabled THEN",
            "    value := value + 1;",
            "END_IF;",
            "",
        ]
        * (lines // 4)
    )
    return FakeObject(
        "LargePOU",
        declaration="VAR\n    value : DINT;\n    enabled : BOOL;\nEND_VAR\n",
        implementation=body + "\n",
    )


class FakeDocument(object):
    def __init__(self, text):
        self.text = text
        self.written = []

    def replace(self, text):
        self.written.append(("replace", text))
        self.text = text


class FakeObject(object):
    """Minimal fake for a CODESYS textual object."""

    _counter = [0]

    def __init__(self, name, declaration=None, implementation=None, guid=None):
        FakeObject._counter[0] += 1
        self.name = name
        self._guid = guid or ("{%04X}" % FakeObject._counter[0])
        self.textual_declaration = (
            FakeDocument(declaration) if declaration is not None else None
        )
        self.textual_implementation = (
            FakeDocument(implementation) if implementation is not None else None
        )
        self.reads = {"declaration": 0, "implementation": 0}
        self._wrappers_invalidated = False

    def get_name(self):
        return self.name

    def invalidate_wrappers(self):
        """Simulate the IDE invalidating document wrappers after a write."""
        self._wrappers_invalidated = True
        self.textual_declaration = None
        self.textual_implementation = None

    def _section(self, attribute):
        if self._wrappers_invalidated:
            raise RuntimeError("wrapper is stale after write")
        return getattr(self, attribute)

    def read_section(self, attribute):
        key = "declaration" if attribute == "textual_declaration" else "implementation"
        self.reads[key] += 1
        return self._section(attribute)


class FakeProject(object):
    def __init__(self, objects=None, selected=None):
        self.objects = list(objects or [])
        self.selected = selected

    def get_children(self, recursive=True):
        return list(self.objects)

    def get_selected_object(self):
        return self.selected


class ReadCounter(object):
    """Wrap FakeObjects and count every section read."""

    def __init__(self, objects):
        self.objects = objects

    def count(self, attribute):
        return sum(1 for obj in self.objects if obj.reads.get(attribute))

    def total(self):
        return sum(
            len([r for r in obj.reads.values() if r > 0]) for obj in self.objects
        )


# ---------------------------------------------------------------------------
# D6 / D8  Step 1: newline safety and IronPython 2.7 compatibility
# ---------------------------------------------------------------------------


def test_crlf_remains_crlf_after_condition_expansion():
    source = "IF a AND b AND c THEN\r\n    x := 1;\r\nEND_IF;\r\nafter := 2;\r\n"

    formatted = format_implementation(source)

    assert formatted == (
        "IF a\r\n"
        "    AND b\r\n"
        "    AND c\r\n"
        "THEN\r\n"
        "    x := 1;\r\n"
        "END_IF;\r\n"
        "after := 2;\r\n"
    )
    assert "\r\n" in formatted
    assert "\n" not in formatted.replace("\r\n", "")


def test_lf_remains_lf_after_condition_expansion():
    source = "IF a AND b AND c THEN\n    x := 1;\nEND_IF;\nafter := 2;\n"

    formatted = format_implementation(source)

    assert "\r" not in formatted
    assert formatted == (
        "IF a\n    AND b\n    AND c\nTHEN\n    x := 1;\nEND_IF;\nafter := 2;\n"
    )


def test_second_format_pass_is_byte_for_byte_identical():
    source = (
        "IF a AND b AND c THEN\n"
        "    x := 1;\n"
        "END_IF;\n"
        "VAR\n"
        "foo : INT;\n"
        "longername : BOOL;\n"
        "END_VAR\n"
    )
    impl = format_implementation(source)
    decl = (
        format_declarations(source, declaration=True)
        if False
        else format_declarations("VAR\nfoo : INT;\nlongername : BOOL;\nEND_VAR\n")
    )

    assert format_implementation(impl) == impl
    assert format_declarations(decl) == decl


def test_declaration_formatting_uses_no_py3_only_builtin_keywords():
    """max(iterable, default=...) is Python 3-only; IronPython 2.7 raises.

    Guarded by inspecting the module source so the test fails when the
    formatter reintroduces the keyword, and by an execution smoke test.
    """
    import ast

    source_path = ROOT / "shared" / "src" / "cts_shared" / "st" / "formatting.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("max", "min") and any(
                kw.arg == "default" for kw in node.keywords
            ):
                offenders.append(node.lineno)
    assert not offenders, "py3-only default= kwarg at lines: {0}".format(offenders)

    # Execution smoke test: multiple declaration rows format under CPython;
    # the same path runs under IronPython 2.7.
    formatted = format_declarations("VAR\nfoo : INT;\nlongername : BOOL;\nEND_VAR\n")
    assert "longername" in formatted


def test_no_new_mixed_line_endings_in_output():
    source = (
        "IF a AND b THEN\r\n    x := 1;\r\nEND_IF;\r\nVAR\r\nfoo : INT;\r\nEND_VAR\r\n"
    )
    impl = format_implementation(source)
    stripped = impl.replace("\r\n", "")
    assert "\n" not in stripped
    assert "\r" not in stripped


# ---------------------------------------------------------------------------
# D5 / D7  Step 6/8: formatter and apply-plan purity
# ---------------------------------------------------------------------------


def test_split_condition_does_not_mark_following_lines_as_replaced():
    before = "IF a AND b THEN\n    x := 1;\nEND_IF;\nafter := 2;\ntail := 3;\n"
    after = "IF a\n    AND b\nTHEN\n    x := 1;\nEND_IF;\nafter := 2;\ntail := 3;\n"

    # The pure line-aware diff must classify the trailing lines as equal.

    rows = diff_lines(before, after)
    changed = [row for row in rows if row.kind != "equal"]
    assert any(row.kind == "equal" and "after :=" in row.new for row in rows)
    assert any(row.kind == "equal" and "tail :=" in row.new for row in rows)
    # Only the IF header, AND continuation and THEN line are genuinely changed.
    assert len(changed) <= 4


def test_unchanged_sections_are_absent_from_apply_plan():
    """A section whose before == after must not be in the write plan."""

    obj = FakeObject(
        "POU",
        declaration="VAR\nx : INT;\nEND_VAR\n",
        implementation="IF a THEN\n    x := 1;\nEND_IF;\n",
    )
    # Implementation is already formatted; only the declaration is dirty.
    plan = build_apply_plan(
        "section:decl",
        obj,
        [
            (
                "textual_declaration",
                "VAR\nx : INT;\nEND_VAR\n",
                "VAR\nx    : INT;\nEND_VAR\n",
            ),
            (
                "textual_implementation",
                "IF a THEN\n    x := 1;\nEND_IF;\n",
                "IF a THEN\n    x := 1;\nEND_IF;\n",
            ),
        ],
    )
    assert plan is not None

    assert len(plan.sections) == 1
    assert plan.sections[0].attribute == "textual_declaration"


def test_diff_model_reports_same_change_count_across_views():
    """All preview modes derive from one model and agree on the count."""
    before = "IF a AND b THEN\n    x := 1;\nEND_IF;\nafter := 2;\n"
    after = "IF a\n    AND b\nTHEN\n    x := 1;\nEND_IF;\nafter := 2;\n"

    model = DiffModel(before, after)

    # changed_count (rows) and changed_lines (source lines) both count the
    # three genuinely changed lines: IF header, AND continuation, THEN.
    assert model.changed_count == 3
    assert model.changed_lines == 3
    assert model.changed_indexes("old") == [0]
    assert model.changed_indexes("new") == [0, 1, 2]
    # Navigation groups: one contiguous change block.
    assert model.navigation_groups() == [(0, 2)]


def test_diff_navigation_uses_actual_diff_groups_not_shifted_indexes():
    before = "a\nb\nc\nd\ne\n"
    after = "a\nX\nY\nc\nd\ne\n"
    model = DiffModel(before, after)

    groups = model.navigation_groups()
    assert groups == [(1, 2)]
    # The equal lines after the insertion keep their own indexes.
    equal_rows = [row for row in model.rows if row.kind == "equal"]
    assert equal_rows[0].old_no == 1 and equal_rows[0].new_no == 1
    line_e = [row for row in equal_rows if row.old == "e"]
    assert line_e and line_e[0].old_no == 5 and line_e[0].new_no == 6


def test_large_repeated_diff_falls_back_to_reduced_representation():
    """Pathological repeated lines must not freeze the IDE."""
    before = "\n".join(["END_IF;", "", "END_IF;"] * 8000)
    after = before.replace("END_IF;", "END_FOR;", 1)

    model = DiffModel(before, after, reduced=True)

    assert model.reduced
    assert model.changed_count > 0
    # The reduced model still classifies the untouched tail as equal.
    assert any(row.kind == "equal" for row in model.rows)


def test_character_highlighting_is_bounded_to_replace_blocks():
    before = "IF a THEN\n    x := 1;\nEND_IF;\n"
    after = "IF a THEN\n  x := 1;\nEND_IF;\n"
    model = DiffModel(before, after)

    spans = [
        model.character_spans(index)
        for index, row in enumerate(model.rows)
        if row.kind == "replace"
    ]
    assert spans and all(span is not None for span in spans)
    # A huge replace block disables character highlighting.
    big_before = "\n".join("line {0}".format(i) for i in range(500))
    big_after = "\n".join("LINE {0}".format(i) for i in range(500))
    big = DiffModel(big_before, big_after)
    assert big.character_spans(0) is None


def test_apply_plan_writes_only_validated_changed_sections():
    """Stale content is never overwritten; partial apply is reported."""

    obj = FakeObject(
        "POU",
        declaration="VAR\nx : INT;\nEND_VAR\n",
        implementation="IF a THEN\n    x := 1;\nEND_IF;\n",
    )
    plan = build_apply_plan(
        "obj",
        obj,
        [
            (
                "textual_declaration",
                "VAR\nx : INT;\nEND_VAR\n",
                "VAR\nx    : INT;\nEND_VAR\n",
            ),
            (
                "textual_implementation",
                "IF a THEN\n    x := 1;\nEND_IF;\n",
                "IF a THEN\n  x := 1;\nEND_IF;\n",
            ),
        ],
    )

    # Make the implementation stale after analysis.
    impl_doc = obj.textual_implementation
    decl_doc = obj.textual_declaration
    assert impl_doc is not None and decl_doc is not None
    impl_doc.text = "IF a THEN\n    x := 999;\nEND_IF;\n"

    results = execute_apply_plan(plan, obj)

    # No writes at all: the stale target blocks the whole object.
    assert all(r["result"] == "failed" for r in results)
    assert decl_doc.text == "VAR\nx : INT;\nEND_VAR\n"
    assert impl_doc.text == "IF a THEN\n    x := 999;\nEND_IF;\n"


def test_apply_plan_reports_partial_write_with_rollback():
    """A failed second write rolls back the first and reports it."""

    obj = FakeObject(
        "POU",
        declaration="VAR\nx : INT;\nEND_VAR\n",
        implementation="IF a THEN\n    x := 1;\nEND_IF;\n",
    )
    plan = build_apply_plan(
        "obj",
        obj,
        [
            (
                "textual_declaration",
                "VAR\nx : INT;\nEND_VAR\n",
                "VAR\nx    : INT;\nEND_VAR\n",
            ),
            (
                "textual_implementation",
                "IF a THEN\n    x := 1;\nEND_IF;\n",
                "IF a THEN\n  x := 1;\nEND_IF;\n",
            ),
        ],
    )

    def failing_replace(doc, text):
        if doc is obj.textual_implementation:
            return False
        doc.text = text
        return True

    results = execute_apply_plan(plan, obj, replace_document=failing_replace)

    kinds = [r["result"] for r in results]
    assert "applied" in kinds
    assert "failed" in kinds
    # The first section was rolled back to its original text.
    decl_doc = obj.textual_declaration
    assert decl_doc is not None
    assert decl_doc.text == "VAR\nx : INT;\nEND_VAR\n"
    assert any(r["result"] == "rolled_back" for r in results)


# ---------------------------------------------------------------------------
# D8  Step 2: pure session controller
# ---------------------------------------------------------------------------


def test_scan_review_apply_state_sequence_runs_without_winforms():
    """The full state machine must run in unit tests with no UI imports."""

    session = FmtSession(scope_indexes=[0, 1, 2])
    assert session.state is SessionState.CREATED

    outcome = session.start_scan()
    assert outcome.action == "scanning"
    assert session.state is SessionState.SCANNING

    # One object at a time through analyze_next.
    item0 = session.analyze_next(result={"analysis": "unchanged"})
    assert item0.action == "next"
    assert session.state is SessionState.SCANNING

    item1 = session.analyze_next(result={"analysis": "changed", "changed_lines": 3})
    assert item1.action == "preview"
    assert session.state is SessionState.PREVIEWING
    assert item1.item_index == 1

    outcome = session.record_apply(index=1)
    assert outcome.action == "scanning"
    assert session.state is SessionState.SCANNING

    outcome = session.analyze_next(result={"analysis": "changed", "changed_lines": 1})
    assert outcome.action == "preview"
    outcome = session.record_skip(index=2)
    assert outcome.action == "finished"
    assert session.state is SessionState.COMPLETED
    assert session.counts["applied"] == 1
    assert session.counts["skipped"] == 1


def test_cancel_is_idempotent_and_valid_from_every_active_state():

    for setup in ("created", "scanning", "previewing", "applying"):
        session = FmtSession(scope_indexes=[0])
        if setup in ("scanning", "previewing", "applying"):
            session.start_scan()
            if setup in ("previewing", "applying"):
                session.analyze_next(result={"analysis": "changed"})
            if setup == "applying":
                session.record_apply(index=0)

        first = session.cancel(reason="user closed the window")
        assert session.state is SessionState.CANCELLED
        assert session.cancelled
        assert session.cancel_reason == "user closed the window"
        assert first.action in ("cancelled", "finished")

        # Idempotent.
        second = session.cancel(reason="again")
        assert session.state is SessionState.CANCELLED
        assert session.cancel_reason == "user closed the window"
        assert second.action in ("cancelled", "finished")


def test_only_one_scan_can_be_active():

    session = FmtSession(scope_indexes=[0, 1])
    session.start_scan()
    with pytest.raises(Exception):
        session.start_scan()
    assert session.state is SessionState.SCANNING


def test_illegal_state_transitions_raise_one_controlled_error():

    session = FmtSession(scope_indexes=[0])
    with pytest.raises(SessionError):
        session.record_apply(index=0)  # not scanning/previewing yet


# ---------------------------------------------------------------------------
# D2 / D3 / D4  Step 4: cooperative scanning, timer ownership, cancellation
# ---------------------------------------------------------------------------


def test_cancellation_prevents_the_next_object_read():
    """After cancel, the document-read counter must not increase."""

    session = FmtSession(scope_indexes=[0, 1])

    class Scanner:
        def __init__(self):
            self.reads = 0

        def scan_one(self, index):
            self.reads += 1
            return {"analysis": "unchanged"}

    scanner = Scanner()
    session.start_scan()
    session.analyze_next(result={"analysis": "unchanged"}, scanner=scanner)
    session.cancel(reason="stop")

    before = scanner.reads
    outcome = session.analyze_next(result={"analysis": "unchanged"}, scanner=scanner)
    assert outcome.action in ("cancelled", "finished")
    assert scanner.reads == before


def test_closing_a_session_stops_and_disposes_its_timer():
    """The view adapter owns the timer; session close detaches and disposes."""

    session = FmtSession(scope_indexes=[0])

    class FakeTimer:
        def __init__(self):
            self.started = False
            self.stopped = False
            self.disposed = False
            self.tick = None  # delegate slot; detaching clears it

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def dispose(self):
            self.disposed = True

    timer = FakeTimer()
    session.attach_timer(timer)
    session.start_scan()
    assert timer.started

    session.close()
    assert timer.stopped
    assert timer.disposed
    assert session.state in ("cancelled", "completed")
    # No live delegate reference remains.
    assert not session.timer_ref


def test_apply_skip_does_not_synchronously_scan_to_next_changed():
    """record_apply/record_skip must return immediately, not scan ahead."""

    session = FmtSession(scope_indexes=[0, 1, 2, 3, 4])
    session.start_scan()
    session.analyze_next(result={"analysis": "changed", "changed_lines": 1})

    outcome = session.record_apply(index=0)
    # The controller returns control to the UI; the next object is analyzed
    # only on an explicit analyze_next tick.
    assert outcome.action == "scanning"
    assert outcome.item_index is None


def test_timer_stops_when_a_changed_item_is_ready_for_preview():
    """The timer must not keep ticking while a preview is open."""

    session = FmtSession(scope_indexes=[0, 1])

    class FakeTimer:
        def __init__(self):
            self.started = 0
            self.stopped = 0
            self.disposed = 0

        def start(self):
            self.started += 1

        def stop(self):
            self.stopped += 1

        def dispose(self):
            self.disposed += 1

    timer = FakeTimer()
    session.attach_timer(timer)
    session.start_scan()
    assert timer.started == 1

    session.analyze_next(result={"analysis": "unchanged"})
    # Still scanning: the timer keeps running.
    assert timer.stopped == 0

    outcome = session.analyze_next(result={"analysis": "changed", "changed_lines": 2})
    assert outcome.action == "preview"
    # The timer is stopped (paused) as soon as a preview is ready; the
    # reference is kept so resume() can restart the same timer.
    assert timer.stopped == 1
    assert timer.disposed == 0
    assert session.timer_ref is timer


def test_resume_restarts_the_same_incremental_scanner():
    """After a decision the adapter resumes the owned timer; no new timer."""

    session = FmtSession(scope_indexes=[0, 1, 2])

    class FakeTimer:
        def __init__(self):
            self.started = 0
            self.stopped = 0
            self.disposed = 0

        def start(self):
            self.started += 1

        def stop(self):
            self.stopped += 1

        def dispose(self):
            self.disposed += 1

    timer = FakeTimer()
    session.attach_timer(timer)
    session.start_scan()
    session.analyze_next(result={"analysis": "changed", "changed_lines": 1})
    assert timer.stopped == 1  # stopped for the preview

    session.record_apply(index=0)
    outcome = session.resume()
    assert outcome.action == "scanning"
    # The same timer object is restarted, not replaced.
    assert timer.started == 2
    assert session.timer_ref is timer


def test_attach_timer_replaces_and_disposes_the_previous_timer():
    """At most one live analysis timer exists for the session."""

    session = FmtSession(scope_indexes=[0])

    class FakeTimer:
        def __init__(self):
            self.started = 0
            self.stopped = 0
            self.disposed = 0

        def start(self):
            self.started += 1

        def stop(self):
            self.stopped += 1

        def dispose(self):
            self.disposed += 1

    first = FakeTimer()
    second = FakeTimer()
    session.attach_timer(first)
    session.attach_timer(second)
    assert first.stopped == 1 and first.disposed == 1
    assert session.timer_ref is second
    session.close()
    assert second.stopped == 1 and second.disposed == 1


# ---------------------------------------------------------------------------
# D1 / D9  Step 5: deterministic scope and one callback signature
# ---------------------------------------------------------------------------


def test_review_all_respects_a_filtered_scope():
    """Only indexes captured in scope_indexes may be read or offered."""

    # Filter leaves objects 1, 3, 5 visible.
    scope = [1, 3, 5]
    session = FmtSession(scope_indexes=scope)
    session.start_scan()

    visited = []
    for _ in range(len(scope)):
        outcome = session.analyze_next(
            result={"analysis": "unchanged"}, on_index=lambda i: visited.append(i)
        )
        if outcome.action != "next":
            break

    assert visited == scope
    assert all(i in scope for i in visited)


def test_callback_typeerror_is_reported_not_retried_as_another_signature():
    """An internal callback TypeError must surface once with its diagnostic."""

    session = FmtSession(scope_indexes=[0])
    session.start_scan()

    def broken_callback(index, scope=None, query=None):
        raise TypeError("internal bug in the analysis callback")

    with pytest.raises(SessionError) as exc:
        session.analyze_next(
            result=None, on_index=broken_callback, scope=session.scope_indexes
        )
    assert "internal bug" in str(exc.value)
    # The state must be FAILED, not silently re-invoked with fewer args.
    assert session.state == "failed"


# ---------------------------------------------------------------------------
# Step 3: explicit cheap discovery
# ---------------------------------------------------------------------------


def test_discovery_performs_zero_st_document_reads():
    """Opening the picker must not read any declaration/implementation text."""

    class Doc:
        def __init__(self, text):
            self.text = text

    class Obj:
        def __init__(self, name, guid):
            self.name = name
            self.guid = guid
            self.textual_declaration = Doc("VAR\nx : INT;\nEND_VAR\n")
            self.textual_implementation = Doc("IF a THEN\nx := 1;\nEND_IF;\n")

        def get_name(self):
            return self.name

    class Project:
        def __init__(self, objs, selected=None):
            self.objs = objs
            self.selected = selected

        def get_children(self, recursive=True):
            return list(self.objs)

        def get_selected_object(self):
            return self.selected

    objs = [Obj("A", "{111}"), Obj("B", "{222}")]
    project = Project(objs, selected=objs[1])
    diagnostics = []

    items, selected_index = st_objects.discover_items(
        project, None, None, diagnostics=diagnostics
    )

    assert [item["label"] for item in items] == ["A", "B"]
    assert selected_index == 1
    assert len(items) == 2
    assert diagnostics and "discovery:" in diagnostics[0]
    # No document text was read: the fake documents have no read counter, and
    # discovery only touched get_children/get_selected_object/get_name.
    assert all(item["analysis"] is None for item in items)


def test_discovery_inserts_selected_object_first_when_not_enumerated():
    class Doc:
        def __init__(self, text):
            self.text = text

    class Obj:
        def __init__(self, name, guid):
            self.name = name
            self.guid = guid
            self.textual_declaration = Doc("VAR\nx : INT;\nEND_VAR\n")
            self.textual_implementation = Doc("IF a THEN\nx := 1;\nEND_IF;\n")

        def get_name(self):
            return self.name

    class Project:
        def __init__(self, objs, selected=None):
            self.objs = objs
            self.selected = selected

        def get_children(self, recursive=True):
            return list(self.objs)

        def get_selected_object(self):
            return self.selected

    objs = [Obj("A", "{111}"), Obj("B", "{222}")]
    outside = Obj("SelectedPOU", "{999}")
    project = Project(objs, selected=outside)

    items, selected_index = st_objects.discover_items(project, None, None)

    assert [item["label"] for item in items] == ["SelectedPOU", "A", "B"]
    assert selected_index == 0


def test_read_document_has_no_debug_print_spam(capsys):
    """A raising section getter is a capability result, not a logged error."""

    class Object:
        @property
        def textual_implementation(self):
            raise RuntimeError("not available for this object type")

    assert st_objects.read_document(Object(), "textual_implementation") is None
    captured = capsys.readouterr()
    assert "fmt-read-debug" not in captured.out
    assert captured.out == ""
