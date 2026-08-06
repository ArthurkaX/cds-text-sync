"""The progress-report contract shared by the analysis pipeline.

Analysing a real project takes long enough that a UI has to show what is
happening, so the entry points accept an optional callback::

    progress(phase, done, total, detail)

``phase`` is one of :data:`PHASES`, ``done``/``total`` count the steps of that
phase - ``total`` is ``0`` when it cannot be known before the phase starts -
and ``detail`` names the file or rule currently being worked on.  Reports are
write-only: nothing in the pipeline reads them back, and a run without a sink
behaves exactly as it did before progress existed.
"""

from __future__ import annotations

#: Emitted in this order.  ``parse`` reads the sources, ``prepare`` resolves
#: rule capabilities (which can start git), ``rules`` dispatches the enabled
#: rules, ``finalize`` merges and fingerprints what they found.
PHASES = ("parse", "prepare", "rules", "finalize")


def emit(progress, phase, done, total=0, detail=""):
    """Report one step, or do nothing when no sink is attached.

    A broken sink must never take the run with it: the analysis is the
    product and the report is decoration.  This is the same reasoning that
    fences the staleness probe in :func:`cds_static_analyzer.runner.run_analysis`.
    """
    if progress is None:
        return
    try:
        progress(phase, int(done), int(total), str(detail))
    except Exception:
        pass
