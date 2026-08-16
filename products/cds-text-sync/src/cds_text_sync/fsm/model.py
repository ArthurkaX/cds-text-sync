"""FSM model: the single payload definitions and the round-trip adapter.

``machine_payload`` is the single definition of the machine payload shape
(section 8.3 of the migration spec).  Its body was carried verbatim from the
old ``fsm_search._machine_payload``; that seam module was deleted in section 12.
``file_result`` is the section 8.2 per-file payload.  ``machine_from_payload``
reverses ``machine_payload`` into attribute-accessible objects so the shared
layout and mermaid renderers can consume a payload.
"""

from __future__ import annotations

from types import SimpleNamespace

STATE_FSM = "fsm"
STATE_NONE = "none"
STATE_ERROR = "error"


def machine_payload(machine) -> dict:
    """Serialize one machine into the JSON-safe section 8.3 payload."""
    return {
        "selector": machine.selector,
        "states": [
            {
                "label": state.label,
                "aliases": state.aliases,
                "order": state.order,
                # The branch body, so the window can show the code a step runs.
                "start_offset": state.start_offset,
                "end_offset": state.end_offset,
            }
            for state in machine.states
        ],
        "transitions": [
            {
                "source": transition.source,
                "target": transition.target,
                "guard": transition.guard,
                "offset": transition.offset,
                "lhs": transition.lhs,
                "deferred": transition.deferred,
                # The arm body the transition fires inside; None when the
                # transition is unconditional (see fsm._action_span).
                "block_start": transition.block_start,
                "block_end": transition.block_end,
            }
            for transition in machine.transitions
        ],
        "deferred": machine.deferred,
        "numeric": machine.numeric,
        "warnings": machine.warnings,
    }


def file_result(path, machines, error=None, fingerprint=None) -> dict:
    """Serialize one analysed file into the JSON-safe section 8.2 payload.

    ``state`` is ``error`` when *error* is truthy, otherwise ``fsm`` when
    *machines* is non-empty, otherwise ``none``.
    """
    if error:
        state = STATE_ERROR
    elif machines:
        state = STATE_FSM
    else:
        state = STATE_NONE
    return {
        "path": path,
        "state": state,
        "machines": machines,
        "error": error,
        "fingerprint": fingerprint,
    }


def machine_from_payload(payload):
    """Adapt a machine payload dict back into an attribute-accessible object.

    ``cts_shared.st.fsm_layout.build_layout`` and
    ``cts_shared.st.fsm_mermaid.to_mermaid`` consume the result.  build_layout
    only reads label/offset/source/target/guard, but the full set (aliases,
    order, lhs, deferred, numeric, warnings) is carried so the adapter stays a
    faithful inverse of machine_payload and the round-trip is lossless.
    """
    machine = SimpleNamespace(
        selector=payload["selector"],
        states=[],
        transitions=[],
        deferred=payload["deferred"],
        numeric=payload["numeric"],
        warnings=payload["warnings"],
    )
    for state in payload["states"]:
        machine.states.append(SimpleNamespace(
            label=state["label"],
            aliases=state["aliases"],
            order=state["order"],
            start_offset=state.get("start_offset"),
            end_offset=state.get("end_offset"),
        ))
    for transition in payload["transitions"]:
        machine.transitions.append(SimpleNamespace(
            offset=transition["offset"],
            source=transition["source"],
            target=transition["target"],
            guard=transition["guard"],
            lhs=transition["lhs"],
            deferred=transition["deferred"],
            block_start=transition.get("block_start"),
            block_end=transition.get("block_end"),
        ))
    return machine
