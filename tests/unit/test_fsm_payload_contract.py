# -*- coding: utf-8 -*-
"""
test_fsm_payload_contract.py -- pin the serialized FSM-pipeline output.

The payload dict and the mermaid render are what the IDE shell consumes, so an
upcoming refactor must not change them silently.  Every expected value below is
a hard-coded literal captured from the CURRENT implementation (see the scratch
script that produced it); if a refactor is behaviour-preserving, these tests
keep passing unchanged.
"""

import json

from cds_text_sync.fsm_search import _machine_payload, _source_root
from cds_text_sync.engine.variable_map import split_decl_impl
from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_mermaid import to_mermaid


NUMERIC_ST = (
    "PROGRAM NumericStateMachine\n"
    "VAR\n"
    "  state : INT;\n"
    "  start : BOOL;\n"
    "  done : BOOL;\n"
    "END_VAR\n"
    "// --- implementation ---\n"
    "CASE state OF\n"
    "  0: IF start THEN state := 1; END_IF\n"
    "  1: IF done THEN state := 2; END_IF\n"
    "  2: state := 0;\n"
    "END_CASE\n"
)

SYMBOLIC_ST = (
    "PROGRAM SymbolicStateMachine\n"
    "VAR\n"
    "  step : ST_State;\n"
    "  next_step : ST_State;\n"
    "  go : BOOL;\n"
    "  stop : BOOL;\n"
    "END_VAR\n"
    "// --- implementation ---\n"
    "CASE step OF\n"
    "  ST.Idle: IF go THEN next_step := ST.Run; END_IF\n"
    "  ST.Run: IF stop THEN next_step := ST.Idle; END_IF\n"
    "END_CASE\n"
)


def _body(text):
    """The implementation section a file scan feeds to find_machines."""
    _decl, impl = split_decl_impl(text)
    return impl if impl is not None else text


def _payloads(text):
    return [_machine_payload(m) for m in find_machines(_body(text)) if m.is_fsm]


# ---------------------------------------------------------------------------
# NUMERIC_ST: direct self-assignment, numeric labels, immediate commits
# ---------------------------------------------------------------------------


def test_machine_payload_shape():
    payload = _payloads(NUMERIC_ST)
    assert payload == [
        {
            "selector": "state",
            "states": [
                {"label": "0", "aliases": ["0"], "order": 0},
                {"label": "1", "aliases": ["1"], "order": 1},
                {"label": "2", "aliases": ["2"], "order": 2},
            ],
            "transitions": [
                {
                    "source": "0",
                    "target": "1",
                    "guard": "start",
                    "offset": 33,
                    "lhs": "state",
                    "deferred": False,
                },
                {
                    "source": "1",
                    "target": "2",
                    "guard": "done",
                    "offset": 70,
                    "lhs": "state",
                    "deferred": False,
                },
                {
                    "source": "2",
                    "target": "0",
                    "guard": "",
                    "offset": 94,
                    "lhs": "state",
                    "deferred": False,
                },
            ],
            "deferred": False,
            "numeric": True,
            "warnings": [],
        }
    ]
    assert set(payload[0]) == {
        "selector", "states", "transitions", "deferred", "numeric", "warnings",
    }


def test_machine_payload_is_json_safe():
    for sample in (NUMERIC_ST, SYMBOLIC_ST):
        payload = _payloads(sample)
        assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------------
# SYMBOLIC_ST: enum labels, next-twin selector (deferred), dotted labels
# ---------------------------------------------------------------------------


def test_symbolic_payload_shape():
    payload = _payloads(SYMBOLIC_ST)
    assert payload == [
        {
            "selector": "step",
            "states": [
                {"label": "ST.Idle", "aliases": ["ST.Idle"], "order": 0},
                {"label": "ST.Run", "aliases": ["ST.Run"], "order": 1},
            ],
            "transitions": [
                {
                    "source": "ST.Idle",
                    "target": "ST.Run",
                    "guard": "go",
                    "offset": 35,
                    "lhs": "next_step",
                    "deferred": True,
                },
                {
                    "source": "ST.Run",
                    "target": "ST.Idle",
                    "guard": "stop",
                    "offset": 86,
                    "lhs": "next_step",
                    "deferred": True,
                },
            ],
            "deferred": True,
            "numeric": False,
            "warnings": [],
        }
    ]
    assert set(payload[0]) == {
        "selector", "states", "transitions", "deferred", "numeric", "warnings",
    }


# ---------------------------------------------------------------------------
# Dispatch CASE: found by find_machines but never serialized
# ---------------------------------------------------------------------------


def test_only_is_fsm_machines_are_serialized():
    dispatch = (
        "PROGRAM Dispatcher\n"
        "VAR\n"
        "  cmd : CMD_Type;\n"
        "  len : INT;\n"
        "END_VAR\n"
        "// --- implementation ---\n"
        "CASE cmd OF\n"
        "  CMD.READ:\n"
        "    DoRead();\n"
        "  CMD.WRITE:\n"
        "    DoWrite();\n"
        "END_CASE\n"
    )
    machines = find_machines(_body(dispatch))
    assert machines
    assert all(not m.is_fsm for m in machines)
    assert [_machine_payload(m) for m in machines if m.is_fsm] == []
    assert all(m.warnings == [] for m in machines)


# ---------------------------------------------------------------------------
# Marker-less file: split_decl_impl yields no implementation, whole body scans
# ---------------------------------------------------------------------------


def test_marker_less_file_analyses_whole_body():
    text = (
        "PROGRAM MarkerLess\n"
        "VAR\n"
        "  st : INT;\n"
        "END_VAR\n"
        "CASE st OF\n"
        "  0: st := 1;\n"
        "  1: st := 0;\n"
        "END_CASE\n"
    )
    decl, impl = split_decl_impl(text)
    assert impl is None
    machines = find_machines(text)
    assert len(machines) == 1
    assert machines[0].is_fsm
    assert machines[0].selector == "st"


# ---------------------------------------------------------------------------
# Mermaid render
# ---------------------------------------------------------------------------


def test_mermaid_output():
    machine = find_machines(_body(NUMERIC_ST))[0]
    assert to_mermaid(machine) == (
        "stateDiagram-v2\n"
        "    s0 : 0\n"
        "    s1 : 1\n"
        "    s2 : 2\n"
        "    s0 --> s1 : start\n"
        "    s1 --> s2 : done\n"
        "    s2 --> s0"
    )
    assert to_mermaid(machine, title="X") == (
        "stateDiagram-v2\n"
        "    title: X\n"
        "    s0 : 0\n"
        "    s1 : 1\n"
        "    s2 : 2\n"
        "    s0 --> s1 : start\n"
        "    s1 --> s2 : done\n"
        "    s2 --> s0"
    )


# ---------------------------------------------------------------------------
# Workspace root resolution
# ---------------------------------------------------------------------------


def test_source_root_prefers_project_view(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_view = workspace / "project-view"
    project_view.mkdir()
    assert _source_root(workspace) == project_view
    assert _source_root(project_view) == project_view
    bare = tmp_path / "bare"
    bare.mkdir()
    assert _source_root(bare) == bare
