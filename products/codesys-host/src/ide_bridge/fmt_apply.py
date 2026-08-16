# -*- coding: utf-8 -*-
"""Two-phase apply plan for the Project_fmt workflow.

Phase A (prepare and validate) is pure: it keeps only sections where
``before != after`` and resolves the target document wrappers.  Phase B
(write and report) is performed by the host adapter through
:func:`execute_apply_plan`, which reads every target fresh, refuses stale
content, writes validated sections only, and attempts best-effort rollback
with fresh wrappers on failure.

Outcomes are structured per section: ``applied``, ``failed``,
``rolled_back``, ``rollback_failed``, or ``unverified``.  Nothing here claims
atomicity; rollback is best effort.

The module is IronPython 2.7 safe (no f-strings, no annotations, no
dataclasses, no Python 3-only builtin keywords).
"""

from __future__ import print_function

from ide_st_objects import read_document as _read_document
from ide_handlers_sync import _replace_text_document as _replace_text_document

# Result kinds for one section write.
APPLIED = "applied"
FAILED = "failed"
ROLLED_BACK = "rolled_back"
ROLLBACK_FAILED = "rollback_failed"
UNVERIFIED = "unverified"


class ApplySection(object):
    """One validated write: attribute, reviewed before/after, target doc."""

    __slots__ = ("attribute", "before", "after", "document", "result")

    def __init__(self, attribute, before, after, document=None):
        self.attribute = attribute
        self.before = before
        self.after = after
        self.document = document
        self.result = None

    def __repr__(self):
        return "ApplySection({0}, result={1})".format(self.attribute, self.result)


class ApplyPlan(object):
    """The validated write plan for one object."""

    def __init__(self, object_key, sections):
        self.object_key = object_key
        self.sections = sections

    @property
    def changed_sections(self):
        return [section for section in self.sections if section.before != section.after]

    def __repr__(self):
        return "ApplyPlan({0}, {1} section(s))".format(
            self.object_key, len(self.sections)
        )


def build_apply_plan(object_key, obj, writes):
    """Build the plan from reviewed ``(attribute, before, after)`` writes.

    Only sections where ``before != after`` are included; unchanged sections
    are never assigned.  Document wrappers are resolved lazily during
    execution so the plan stays pure and testable.
    """
    sections = []
    for attribute, before, after in writes:
        if before == after:
            continue
        sections.append(ApplySection(attribute, before, after))
    return ApplyPlan(object_key, sections)


def _resolve_document(obj, attribute):
    """Resolve a fresh document wrapper for one section."""
    try:
        return getattr(obj, attribute, None)
    except Exception:
        return None


def execute_apply_plan(plan, obj, read_document=None, replace_document=None):
    """Phase B: validate, write, and report per-section results.

    *read_document* defaults to :func:`ide_st_objects.read_document`;
    *replace_document* defaults to
    :func:`ide_handlers_sync._replace_text_document`.  Both are injectable so
    the two-phase behavior is testable with fakes.

    Returns a list of per-section result dicts:
    ``{"attribute", "result", "detail"}``.
    """
    read_document = read_document or _read_document
    replace_document = replace_document or _replace_text_document

    results = []
    written = []  # (section, document, original) for best-effort rollback

    # Phase A: validate every target against the reviewed before text.
    for section in plan.sections:
        document = _resolve_document(obj, section.attribute)
        if document is None:
            results.append(
                {
                    "attribute": section.attribute,
                    "result": FAILED,
                    "detail": "section is not available on the object",
                }
            )
            continue
        try:
            current = read_document(obj, section.attribute)
        except Exception as error:
            results.append(
                {
                    "attribute": section.attribute,
                    "result": FAILED,
                    "detail": "could not read target: {0}".format(error),
                }
            )
            continue
        if current != section.before:
            results.append(
                {
                    "attribute": section.attribute,
                    "result": FAILED,
                    "detail": "target changed after analysis; preview it again",
                }
            )
            continue
        section.document = document
        section.result = "validated"

    # If any target is stale or unreadable, perform no writes at all.
    if any(result["result"] == FAILED for result in results):
        return results

    # Phase B: write the validated sections only.
    for section in plan.sections:
        write_error = ""
        try:
            ok = replace_document(section.document, section.after)
        except Exception as error:
            ok = False
            write_error = str(error)
        if not ok:
            section.result = FAILED
            results.append(
                {
                    "attribute": section.attribute,
                    "result": FAILED,
                    "detail": "write failed"
                    + (": " + write_error if write_error else ""),
                }
            )
            continue
        written.append((section, section.document, section.before))
        section.result = APPLIED
        results.append(
            {
                "attribute": section.attribute,
                "result": APPLIED,
                "detail": "",
            }
        )

    if any(result["result"] == FAILED for result in results):
        # Best-effort rollback of already written sections using fresh
        # wrappers where possible.
        for section, _document, original in reversed(written):
            fresh = _resolve_document(obj, section.attribute)
            if fresh is None:
                section.result = ROLLBACK_FAILED
                results.append(
                    {
                        "attribute": section.attribute,
                        "result": ROLLBACK_FAILED,
                        "detail": "could not resolve a fresh wrapper for rollback",
                    }
                )
                continue
            try:
                ok = replace_document(fresh, original)
            except Exception:
                ok = False
            if ok:
                section.result = ROLLED_BACK
                results.append(
                    {
                        "attribute": section.attribute,
                        "result": ROLLED_BACK,
                        "detail": "",
                    }
                )
            else:
                section.result = ROLLBACK_FAILED
                results.append(
                    {
                        "attribute": section.attribute,
                        "result": ROLLBACK_FAILED,
                        "detail": "rollback write failed",
                    }
                )
    return results


__all__ = [
    "ApplyPlan",
    "ApplySection",
    "build_apply_plan",
    "execute_apply_plan",
    "APPLIED",
    "FAILED",
    "ROLLED_BACK",
    "ROLLBACK_FAILED",
    "UNVERIFIED",
]
