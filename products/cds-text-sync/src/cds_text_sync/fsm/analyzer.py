"""Analyze one Structured Text file into JSON-safe machine payloads.

The file scan behaviour is exactly that of ``fsm_search._scan_file``: split on
the implementation marker, analyse the implementation section when the marker
is present and the WHOLE text when it is not, and keep only CASE sites where
``is_fsm`` is true.  ``analyze_path`` stays module-level so Windows process
spawning can pickle it as a worker entry point.
"""

from __future__ import annotations

from pathlib import Path

from cts_shared.st.fsm import find_machines

from cds_text_sync.engine.variable_map import split_decl_impl

from .model import file_result, machine_payload
from .workspace import fingerprint, read_source


def analyze_text(text: str) -> list[dict]:
    """Analyse ST text and return a machine payload for every FSM found."""
    _declaration, implementation = split_decl_impl(text)
    machines = [
        machine_payload(machine)
        for machine in find_machines(implementation if implementation is not None else text)
        if machine.is_fsm
    ]
    return machines


def analyze_path(path_text: str, relative: str | None = None) -> dict:
    """Read and analyse one ST file, returning a JSON-safe file result.

    *relative* when given is used as the payload ``path``, otherwise the raw
    *path_text* is used.  Any read/parse failure becomes one error row with a
    non-empty ``error`` and no fingerprint.
    """
    payload_path = relative if relative is not None else path_text
    try:
        path = Path(path_text)
        text = read_source(path)
        machines = analyze_text(text)
        return file_result(payload_path, machines, fingerprint=fingerprint(path))
    except Exception as error:
        return file_result(payload_path, [], error=str(error))
