"""Small deterministic behavior facts extracted from ST implementations."""

from __future__ import annotations

import re

from cds_static_analyzer.model import line_col_of
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_CASE = re.compile(r"\bCASE\s+(?P<state>[A-Za-z_]\w*)\s+OF\b", re.IGNORECASE)
_RETURN = re.compile(r"\bRETURN\b", re.IGNORECASE)
_FOR = re.compile(
    r"\bFOR\s+(?P<name>[A-Za-z_]\w*)\s*:=\s*(?P<start>[^\s]+)\s+"
    r"TO\s+(?P<end>[^\s]+)(?:\s+BY\s+(?P<step>[^\s]+))?",
    re.IGNORECASE,
)
_WHILE = re.compile(r"\bWHILE\s+(?P<condition>[^\r\n]+?)\s+DO\b", re.IGNORECASE)
_TIMER_CALL = re.compile(r"\b(?P<instance>[A-Za-z_]\w*)\s*\(", re.IGNORECASE)
_COUNTER = re.compile(
    r"\b(?:[A-Za-z_]\w*(?:retry|retries|timeout|attempt|counter)\w*|"
    r"(?:retry|retries|timeout|attempt|counter)[A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=", re.IGNORECASE)
_STATUS_FLAG = re.compile(
    r"(?:error|fault|alarm|warning|invalid|status|state|done|complete|completed|"
    r"success|failed|failure|busy|ready|valid|active|enabled|disabled|timeout|retry)",
    re.IGNORECASE,
)
_CASE_LABEL = re.compile(r"^\s*(?P<label>[A-Za-z_]\w*|-?\d+)\s*:", re.MULTILINE)
_PROTECTIVE_IF = re.compile(
    r"\bIF\s+(?P<condition>[^\r\n]+?)\s+THEN\b", re.IGNORECASE
)


def _fact(kind, unit, section, offset, confidence="high", **details):
    absolute = section.at(offset)
    line, column = line_col_of(unit.text, absolute)
    return {
        "kind": kind,
        "confidence": confidence,
        "source_span": {"line": line, "column": column},
        **details,
    }


def extract_behavior(unit):
    """Return ``(status, facts, summary)`` without copying implementation text."""
    if unit.kind not in K.CALLABLE:
        return "not_extracted", [], ""
    section = body(unit)
    if not section:
        return "not_extracted", [], ""
    text = section.text
    facts = []

    for match in _CASE.finditer(text):
        labels = []
        tail = text[match.end() :]
        end = re.search(r"\bEND_CASE\b", tail, re.IGNORECASE)
        block = tail[: end.start()] if end else tail
        for label in _CASE_LABEL.finditer(block):
            labels.append(label.group("label"))
        facts.append(_fact(
            "case_state", unit, section, match.start(),
            state_variable=match.group("state"), labels=labels,
        ))

    for match in _RETURN.finditer(text):
        trailing = text[match.end():].strip()
        facts.append(_fact(
            "return", unit, section, match.start(),
            position="early" if trailing else "final",
        ))

    for match in _PROTECTIVE_IF.finditer(text):
        condition = match.group("condition").strip()
        if re.search(r"\b(?:NOT|ERROR|FAULT|INVALID|DISABLE|TIMEOUT|BUSY)\b", condition, re.IGNORECASE):
            facts.append(_fact(
                "protective_branch", unit, section, match.start(),
                condition=condition, confidence="medium",
            ))

    for match in _FOR.finditer(text):
        facts.append(_fact(
            "for_loop", unit, section, match.start(),
            variable=match.group("name"), start=match.group("start"),
            end=match.group("end"), step=match.group("step") or "1",
        ))
    for match in _WHILE.finditer(text):
        facts.append(_fact(
            "while_loop", unit, section, match.start(),
            condition=match.group("condition").strip(), confidence="medium",
        ))

    timer_types = {"ton", "tof", "tp"}
    timer_names = {
        str(member.get("name") or "").casefold()
        for member in decl.all_members(unit)
        if str(member.get("type") or "").split(".")[-1].casefold() in timer_types
    }
    for match in _TIMER_CALL.finditer(text):
        instance = match.group("instance")
        if instance.casefold() not in timer_names and instance.casefold() not in timer_types:
            continue
        facts.append(_fact(
            "timer_call", unit, section, match.start(),
            instance=instance,
        ))

    output_names = {
        str(member.get("name") or "").casefold()
        for block in decl.var_blocks(unit)
        if block.get("scope") == "VAR_OUTPUT"
        for member in block.get("members") or []
    }
    for match in _ASSIGNMENT.finditer(text):
        name = match.group("name")
        if name.casefold() in output_names:
            facts.append(_fact(
                "output_write", unit, section, match.start(), output=name,
            ))
        status_match = _STATUS_FLAG.search(name)
        if status_match:
            token = status_match.group(0).casefold()
            if token in {"error", "fault", "alarm", "warning", "invalid", "failed", "failure"}:
                category = "error"
            elif token in {"done", "complete", "completed", "success"}:
                category = "completion"
            elif token in {"busy", "ready", "valid", "active", "enabled", "disabled"}:
                category = "control"
            elif token in {"state"}:
                category = "state"
            else:
                category = "status"
            facts.append(_fact(
                "status_write", unit, section, match.start(),
                flag=name, category=category, confidence="medium",
            ))

    seen_counters = set()
    for match in _COUNTER.finditer(text):
        name = match.group(0)
        if name.casefold() in seen_counters:
            continue
        seen_counters.add(name.casefold())
        facts.append(_fact(
            "counter", unit, section, match.start(), confidence="medium",
            name=name,
        ))

    facts.sort(key=lambda fact: (fact["source_span"]["line"], fact["kind"]))
    if not facts:
        return "not_extracted", [], ""
    counts = {}
    for fact in facts:
        counts[fact["kind"]] = counts.get(fact["kind"], 0) + 1
    summary = ", ".join(f"{count} {kind}" for kind, count in sorted(counts.items()))
    return "partial", facts, summary


__all__ = ["extract_behavior"]
