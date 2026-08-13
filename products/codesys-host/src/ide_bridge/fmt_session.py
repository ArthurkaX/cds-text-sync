# -*- coding: utf-8 -*-
"""Pure session controller for the Project_fmt workflow.

This module has no WinForms, CODESYS, or threading imports.  It owns the
explicit state machine that the picker, scanner, preview, and apply steps
share, and every command returns a small :class:`Outcome` describing the next
UI action instead of opening dialogs itself.

Design rules (fix_specs.md section 2):

* CODESYS wrappers are never touched here; the view adapter supplies a
  ``scan_one(index)`` callback that performs the read and formatting on the
  host thread.
* Cancellation is state, not an event-handler side effect: every scheduled
  unit checks the same flag before invoking any callback.
* Display labels are derived from state; label text is never used to infer
  state.
* Illegal transitions raise one controlled :class:`SessionError`.
* Rollback is best effort; nothing here claims atomicity.

The module is IronPython 2.7 safe (no f-strings, no annotations, no
dataclasses, no Python 3-only builtin keywords).
"""

from __future__ import print_function


class SessionState(object):
    """Plain string constants so state compares equal to literals."""

    CREATED = "created"
    DISCOVERING = "discovering"
    READY = "ready"
    SCANNING = "scanning"
    PREVIEWING = "previewing"
    APPLYING = "applying"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


# Item analysis states.  One explicit value, never a combination of nullable
# status/analysis/display strings.
ANALYSIS_PENDING = "pending"
ANALYSIS_READING = "reading"
ANALYSIS_UNCHANGED = "unchanged"
ANALYSIS_CHANGED = "changed"
ANALYSIS_ERROR = "error"

MAX_DIAGNOSTICS = 50


class SessionError(Exception):
    """One controlled error for every illegal transition or callback failure."""


class Outcome(object):
    """A small result describing the next UI action."""

    def __init__(self, action, **fields):
        self.action = action
        for key, value in fields.items():
            setattr(self, key, value)

    def __repr__(self):
        return "Outcome({0})".format(self.action)


class FmtSession(object):
    """Explicit state object for one picker/scan/preview/apply session.

    Holds plain Python values only: a stable session identifier, ordered item
    records, the active scope indexes, the scan cursor, the preview index,
    the cancellation flag and reason, applied/skipped/failed/pending counts,
    bounded diagnostics, and the owned UI timer reference.
    """

    def __init__(self, items=None, scope_indexes=None, session_id=None):
        self.session_id = session_id or ("fmt-" + str(id(self)))
        self.scope_indexes = list(scope_indexes or [])
        if items is None:
            self.items = [self._blank_item(index) for index in self.scope_indexes]
        else:
            self.items = items
        self.state = SessionState.CREATED
        self.scan_cursor = 0
        self.preview_index = None
        self.cancelled = False
        self.cancel_reason = None
        self.counts = {
            "applied": 0,
            "skipped": 0,
            "failed": 0,
            "pending": len(self.scope_indexes),
        }
        self.diagnostics = []
        self.timer_ref = None
        self._closed = False

    # -- diagnostics -----------------------------------------------------

    def record_diagnostic(self, message):
        """Append one bounded diagnostic entry."""
        self.diagnostics.append(message)
        if len(self.diagnostics) > MAX_DIAGNOSTICS:
            del self.diagnostics[: len(self.diagnostics) - MAX_DIAGNOSTICS]

    # -- timer ownership -------------------------------------------------

    def attach_timer(self, timer):
        """The view adapter owns the UI timer; the session holds the reference.

        *timer* must expose ``start()``, ``stop()`` and ``dispose()``; the
        adapter wraps the WinForms ``System.Windows.Forms.Timer`` to that
        contract so this module stays UI-free.
        """
        self.timer_ref = timer

    def _start_timer(self):
        if self.timer_ref is not None:
            self.timer_ref.start()

    def _stop_timer(self):
        timer = self.timer_ref
        self.timer_ref = None
        if timer is not None:
            try:
                timer.stop()
            finally:
                timer.dispose()

    # -- commands --------------------------------------------------------

    def set_scope(self, scope_indexes):
        """Capture the ordered scope snapshot before a scan starts."""
        if self.state not in (SessionState.CREATED, SessionState.READY):
            raise SessionError("set_scope is only valid before scanning")
        self.scope_indexes = list(scope_indexes)
        self.counts["pending"] = len(self.scope_indexes)
        self.state = SessionState.READY
        return Outcome("ready", scope_size=len(self.scope_indexes))

    def start_scan(self):
        """Begin cooperative scanning; only one scan may be active."""
        if self.state not in (SessionState.CREATED, SessionState.READY):
            raise SessionError("start_scan is only valid from CREATED/READY")
        self.state = SessionState.SCANNING
        self.scan_cursor = 0
        self._start_timer()
        return Outcome("scanning", scope_size=len(self.scope_indexes))

    def cancel(self, reason="cancelled"):
        """Idempotent cancellation, valid from every state."""
        if self.cancelled:
            return Outcome("cancelled", reason=self.cancel_reason)
        self.cancelled = True
        self.cancel_reason = reason
        self.state = SessionState.CANCELLED
        self._stop_timer()
        return Outcome("cancelled", reason=reason)

    def analyze_next(self, result=None, scanner=None, on_index=None, scope=None):
        """Process at most one scope item.

        *result* is a plain dict with at least ``analysis``
        (``unchanged``/``changed``/``error``) plus optional ``changed_lines``,
        ``before``, ``after``, ``writes`` and ``error``.  When *result* is
        None and *scanner* is given, ``scanner.scan_one(index)`` is invoked
        (the adapter's host-thread read).  *on_index* is called with the
        index being processed.  *scope* is accepted for API symmetry; the
        controller always uses its captured ``scope_indexes``.

        A callback exception is reported once with its original diagnostic and
        fails the session; it is never retried with another signature.
        """
        if self.cancelled:
            return Outcome("cancelled", reason=self.cancel_reason)
        if self.state not in (SessionState.SCANNING, SessionState.APPLYING):
            raise SessionError("analyze_next is only valid while scanning")
        if self.scan_cursor >= len(self.scope_indexes):
            return self._finish_scan()
        index = self.scope_indexes[self.scan_cursor]
        self.scan_cursor += 1
        item = self._item_for(index)
        item["analysis"] = ANALYSIS_READING
        try:
            if on_index is not None:
                on_index(index)
            if result is None and scanner is not None:
                result = scanner.scan_one(index)
            if result is None:
                result = {"analysis": ANALYSIS_UNCHANGED}
        except Exception as error:
            item["analysis"] = ANALYSIS_ERROR
            item["error"] = str(error)
            self.counts["failed"] += 1
            self.state = SessionState.FAILED
            self.record_diagnostic(
                "analyze_next failed on index {0}: {1}".format(index, error)
            )
            raise SessionError(str(error))
        self._record_result(item, result)
        if item["analysis"] == ANALYSIS_CHANGED:
            self.preview_index = index
            self.state = SessionState.PREVIEWING
            return Outcome("preview", item_index=index, item=item)
        return Outcome("next", item_index=index, item=item)

    def select_item(self, index):
        """Open one item for preview without scanning the rest."""
        if self.state not in (
            SessionState.READY,
            SessionState.SCANNING,
            SessionState.PREVIEWING,
        ):
            raise SessionError("select_item is only valid while ready or scanning")
        self.preview_index = index
        return Outcome("preview", item_index=index, item=self._item_for(index))

    def record_apply(self, index):
        """Record one applied item and return control to the UI immediately."""
        return self._record_decision(index, "applied")

    def record_skip(self, index):
        """Record one skipped item and return control to the UI immediately."""
        return self._record_decision(index, "skipped")

    def finish(self):
        """Complete the review without scanning further."""
        if self.state not in (
            SessionState.PREVIEWING,
            SessionState.APPLYING,
            SessionState.SCANNING,
        ):
            raise SessionError("finish is only valid from an active review state")
        return self._finish_scan()

    def close(self):
        """Idempotent cleanup: stop the timer and cancel any active work."""
        if self._closed:
            return
        self._closed = True
        self._stop_timer()
        if self.state not in (
            SessionState.COMPLETED,
            SessionState.CANCELLED,
            SessionState.FAILED,
        ):
            self.cancel(reason="session closed")

    # -- internals -------------------------------------------------------

    def _blank_item(self, index):
        return {
            "index": index,
            "label": "item {0}".format(index),
            "analysis": ANALYSIS_PENDING,
            "changed_lines": 0,
            "before": None,
            "after": None,
            "writes": [],
            "error": None,
        }

    def _item_for(self, index):
        for item in self.items:
            if item.get("index") == index:
                return item
        item = self._blank_item(index)
        self.items.append(item)
        return item

    def _record_result(self, item, result):
        analysis = result.get("analysis", ANALYSIS_UNCHANGED)
        item["analysis"] = analysis
        item["changed_lines"] = result.get("changed_lines", 0)
        if "before" in result:
            item["before"] = result["before"]
        if "after" in result:
            item["after"] = result["after"]
        if "writes" in result:
            item["writes"] = result["writes"]
        if "error" in result:
            item["error"] = result["error"]
        if analysis == ANALYSIS_ERROR:
            self.counts["failed"] += 1
        self.counts["pending"] = max(0, len(self.scope_indexes) - self.scan_cursor)

    def _record_decision(self, index, kind):
        if self.state not in (SessionState.PREVIEWING, SessionState.APPLYING):
            raise SessionError(
                "record_apply/record_skip is only valid while previewing"
            )
        if index != self.preview_index:
            raise SessionError("decision index does not match the previewed item")
        self.counts[kind] += 1
        self.state = SessionState.APPLYING
        if self.scan_cursor >= len(self.scope_indexes):
            return self._finish_scan()
        self.state = SessionState.SCANNING
        return Outcome("scanning", item_index=None)

    def _finish_scan(self):
        self.state = SessionState.COMPLETED
        self._stop_timer()
        return Outcome("finished", counts=dict(self.counts))


__all__ = [
    "FmtSession",
    "Outcome",
    "SessionError",
    "SessionState",
    "ANALYSIS_PENDING",
    "ANALYSIS_READING",
    "ANALYSIS_UNCHANGED",
    "ANALYSIS_CHANGED",
    "ANALYSIS_ERROR",
]
