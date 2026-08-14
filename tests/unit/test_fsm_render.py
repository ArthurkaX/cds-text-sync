"""Unit tests for the FSM rendering helpers (cds_text_sync.fsm.render)."""

import json
import xml.etree.ElementTree as ET

from cds_text_sync.engine.variable_map import ST_IMPLEMENTATION_MARKER, split_decl_impl
from cds_text_sync.fsm import layout_payload, machine_payload, to_mermaid_text, to_svg
from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_layout import build_layout
from cts_shared.st.fsm_mermaid import to_mermaid


SAMPLE_ST = (
    "PROGRAM Motor\n"
    "VAR\n"
    "  state : INT;\n"
    "  start : BOOL;\n"
    "  done : BOOL;\n"
    "END_VAR\n"
    + ST_IMPLEMENTATION_MARKER + "\n"
    "CASE state OF\n"
    "  0: IF start THEN state := 1; END_IF\n"
    "  1: IF done THEN state := 2; END_IF\n"
    "  2: state := 0;\n"
    "END_CASE\n"
)


def _body(text):
    """The section a file scan feeds to find_machines."""
    _decl, impl = split_decl_impl(text)
    return impl if impl is not None else text


def _first_machine(text):
    return next(machine for machine in find_machines(_body(text)) if machine.is_fsm)


def _payload(text):
    return machine_payload(_first_machine(text))


def _data_values(svg, name):
    """The values of one ``data-*`` attribute across every SVG element."""
    root = ET.fromstring(svg)
    return [element.get(name) for element in root.iter() if element.get(name) is not None]


# ---------------------------------------------------------------------------
# layout_payload: JSON-safe geometry
# ---------------------------------------------------------------------------


def test_layout_payload_round_trips_as_json():
    geometry = layout_payload(_payload(SAMPLE_ST))
    assert json.dumps(geometry)
    assert json.loads(json.dumps(geometry)) == geometry


def test_layout_payload_reports_positive_geometry():
    payload = _payload(SAMPLE_ST)
    geometry = layout_payload(payload)
    assert geometry["width"] > 0
    assert geometry["height"] > 0
    assert len(geometry["steps"]) == len(payload["states"])
    assert geometry["prefix"] == ""
    assert geometry["dropped"] == 0
    assert geometry["columns"] >= 1
    for step in geometry["steps"]:
        assert set(step) == {
            "number", "label", "full_label", "x", "y", "w", "h",
            "initial", "priority", "col", "row", "inbound",
        }
    for link in geometry["links"]:
        for px, py in link["points"]:
            assert isinstance(px, int) and isinstance(py, int)


# ---------------------------------------------------------------------------
# to_svg: well-formed, safe standalone document
# ---------------------------------------------------------------------------


def test_to_svg_is_a_well_formed_document():
    svg = to_svg(_payload(SAMPLE_ST))
    body = svg.lstrip()
    if body.startswith("<?xml"):
        body = body.split("?>", 1)[1].lstrip()
    assert body.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    root = ET.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"


def test_to_svg_draws_one_step_per_state():
    payload = _payload(SAMPLE_ST)
    svg = to_svg(payload)
    # The number of step rects equals the number of states (the background
    # rect and any double border are separate <rect> elements, so count the
    # step boxes by their divider <line> instead).
    lines = svg.count("<line")
    assert lines >= len(payload["states"])
    for state in payload["states"]:
        assert state["label"] in svg


def test_to_svg_escapes_source_text():
    # Rename state "0" everywhere the payload references it, or the renamed
    # state becomes a disconnected island and its transitions get dropped.
    evil_label = "<script>alert(1)</script>"
    payload = _payload(SAMPLE_ST)
    payload["states"][0]["label"] = evil_label
    payload["transitions"][0]["source"] = evil_label      # 0 -> 1
    payload["transitions"][2]["target"] = evil_label      # 2 -> 0
    payload["transitions"][1]["guard"] = 'a & b "quoted"'  # 1 -> 2

    svg = to_svg(payload)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    assert "&amp;" in svg
    assert "&quot;" in svg
    ET.fromstring(svg)


def test_to_svg_escapes_title():
    svg = to_svg(_payload(SAMPLE_ST), title='A & <B> "title"')
    assert "A &amp; &lt;B&gt; &quot;title&quot;" in svg
    assert "<title>" in svg
    ET.fromstring(svg)


def test_to_svg_preserves_non_ascii_text():
    # Rename state "1" everywhere it is referenced so the machine stays
    # connected and every transition is still drawn.
    cyr_label = "Состояние"
    payload = _payload(SAMPLE_ST)
    payload["states"][1]["label"] = cyr_label
    payload["transitions"][0]["target"] = cyr_label        # 0 -> 1
    payload["transitions"][1]["source"] = cyr_label        # 1 -> 2
    payload["transitions"][1]["guard"] = "завершено И готово"

    svg = to_svg(payload)
    assert cyr_label in svg
    assert "завершено И готово" in svg
    ET.fromstring(svg)


def test_to_svg_preserves_non_ascii_in_data_state():
    cyr_label = "Состояние"
    payload = _payload(SAMPLE_ST)
    payload["states"][1]["label"] = cyr_label
    payload["transitions"][0]["target"] = cyr_label
    payload["transitions"][1]["source"] = cyr_label

    assert cyr_label in _data_values(to_svg(payload), "data-state")


# ---------------------------------------------------------------------------
# determinism: identical input -> byte-identical output
# ---------------------------------------------------------------------------


def test_to_svg_deterministic_across_calls():
    payload = _payload(SAMPLE_ST)
    assert to_svg(payload) == to_svg(payload)


def test_to_svg_deterministic_across_independent_payloads():
    # Two separately-built payloads from the same source must render the
    # same bytes - dict ordering and object identity must not leak into SVG.
    assert to_svg(_payload(SAMPLE_ST)) == to_svg(_payload(SAMPLE_ST))


def test_layout_payload_deterministic():
    payload = _payload(SAMPLE_ST)
    assert layout_payload(payload) == layout_payload(payload)
    assert layout_payload(_payload(SAMPLE_ST)) == layout_payload(_payload(SAMPLE_ST))


# ---------------------------------------------------------------------------
# stable selection ids: data-transition / data-state
# ---------------------------------------------------------------------------


def test_svg_data_transition_indices_are_payload_relative():
    payload = _payload(SAMPLE_ST)
    assert len(payload["transitions"]) >= 3
    indices = [int(value) for value in _data_values(to_svg(payload), "data-transition")]
    assert indices
    for index in indices:
        assert 0 <= index < len(payload["transitions"])
    # Every payload transition is drawn exactly once, so the set of emitted
    # indices is exactly the payload's transition range.
    assert set(indices) == set(range(len(payload["transitions"])))


def test_layout_payload_transition_index_matches_payload_order():
    payload = _payload(SAMPLE_ST)
    geometry = layout_payload(payload)
    seen = set()
    for link in geometry["links"]:
        assert set(link) >= {"transition_index", "kind", "points"}
        index = link["transition_index"]
        assert index is not None
        assert 0 <= index < len(payload["transitions"])
        seen.add(index)
    assert seen == set(range(len(payload["transitions"])))


def test_svg_and_layout_agree_on_transition_indices():
    payload = _payload(SAMPLE_ST)
    svg_indices = {int(v) for v in _data_values(to_svg(payload), "data-transition")}
    geometry = layout_payload(payload)
    layout_indices = {
        link["transition_index"]
        for link in geometry["links"]
        if link["transition_index"] is not None
    }
    assert svg_indices == layout_indices


def test_svg_data_state_covers_every_state_label():
    payload = _payload(SAMPLE_ST)
    states = set(_data_values(to_svg(payload), "data-state"))
    assert states == {state["label"] for state in payload["states"]}


# ---------------------------------------------------------------------------
# to_mermaid_text
# ---------------------------------------------------------------------------


def test_to_mermaid_text_matches_shared_renderer():
    machine = _first_machine(SAMPLE_ST)
    payload = machine_payload(machine)
    assert to_mermaid_text(payload) == to_mermaid(machine)
    assert to_mermaid_text(payload, title="Motor") == to_mermaid(machine, title="Motor")


def test_to_mermaid_text_equivalence_with_build_layout():
    # The payload adapter is the same seam build_layout already consumes.
    machine = _first_machine(SAMPLE_ST)
    payload = machine_payload(machine)
    layout = build_layout(machine)
    assert layout.width > 0
    assert to_mermaid_text(payload) == to_mermaid(machine)


# ---------------------------------------------------------------------------
# empty machine
# ---------------------------------------------------------------------------


def test_empty_machine_renders_valid_svg_and_layout():
    payload = {
        "selector": "state",
        "states": [],
        "transitions": [],
        "deferred": False,
        "numeric": True,
        "warnings": [],
    }
    geometry = layout_payload(payload)
    assert geometry["steps"] == []
    assert geometry["links"] == []
    assert geometry["chips"] == []
    assert geometry["any_box"] is None
    assert geometry["width"] > 0
    assert geometry["height"] > 0

    svg = to_svg(payload)
    assert svg.rstrip().endswith("</svg>")
    ET.fromstring(svg)
