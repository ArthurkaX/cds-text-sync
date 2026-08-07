"""CTS0090 - overridable method call during FB_Init."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_METHOD_HEADER = re.compile(
    r"\bMETHOD(?:\s+(?:PUBLIC|PROTECTED|PRIVATE|INTERNAL))?\s+"
    r"(?P<name>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)
_FB_HEADER = re.compile(
    r"\bFUNCTION_BLOCK\s+(?P<name>[A-Za-z_]\w*)\b"
    r"(?P<tail>.*?)(?:\bEND_FUNCTION_BLOCK\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_EXTENDS = re.compile(r"\bEXTENDS\s+(?P<base>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\b", re.IGNORECASE)
_BARE_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(")
_THIS_CALL = re.compile(r"\bTHIS\s*\^?\s*\.\s*(?P<name>[A-Za-z_]\w*)\s*\(", re.IGNORECASE)
_CONTROL_WORDS = {"IF", "FOR", "WHILE", "CASE", "REPEAT", "RETURN", "SEL", "MUX"}


def _method_name(unit):
    match = _METHOD_HEADER.search(unit.declaration or "")
    if match:
        return match.group("name")
    return unit.qualified_name.rsplit(".", 1)[-1]


def _fb_info(ctx):
    by_name = {}
    bases = {}
    for unit in ctx.units:
        if unit.kind != K.FUNCTION_BLOCK:
            continue
        key = unit.qualified_name.casefold()
        by_name[key] = unit
        by_name.setdefault(key.rsplit(".", 1)[-1], unit)
        match = _FB_HEADER.search(unit.declaration or "")
        extends = _EXTENDS.search(match.group("tail") if match else "")
        if extends:
            bases[key] = extends.group("base").casefold().rsplit(".", 1)[-1]

    methods = {}
    for unit in ctx.units:
        if unit.kind != K.METHOD or not unit.owner_name:
            continue
        owner = unit.owner_name.casefold()
        method = _method_name(unit).casefold()
        methods.setdefault(owner, set()).add(method)
    return by_name, bases, methods


def _resolve_fb(name, by_name):
    key = (name or "").casefold().rsplit(".", 1)[-1]
    return by_name.get(key)


def _is_descendant(candidate, ancestor, bases, by_name):
    current = candidate
    seen = set()
    while current and current not in seen:
        seen.add(current)
        base = bases.get(current)
        if not base:
            return False
        resolved = _resolve_fb(base, by_name)
        if resolved is None:
            return False
        current = resolved.qualified_name.casefold()
        if current == ancestor:
            return True
    return False


def _overridable_methods(owner_key, by_name, bases, methods):
    candidates = set(methods.get(owner_key, ()))
    ancestor = owner_key
    seen = set()
    while ancestor not in seen:
        seen.add(ancestor)
        base = bases.get(ancestor)
        if not base:
            break
        resolved = _resolve_fb(base, by_name)
        if resolved is None:
            break
        ancestor = resolved.qualified_name.casefold()
        candidates.update(methods.get(ancestor, ()))

    for method in candidates:
        for candidate in by_name.values():
            candidate_key = candidate.qualified_name.casefold()
            if candidate_key != owner_key and _is_descendant(
                candidate_key, owner_key, bases, by_name
            ) and method in methods.get(candidate_key, ()):
                yield method
                break


def _is_super_call(text, start):
    prefix = text[:start]
    return bool(re.search(r"SUPER\s*\^?\s*\.\s*$", prefix, re.IGNORECASE))


def check(unit, ctx):
    if unit.kind != K.METHOD or not unit.owner_name or _method_name(unit).casefold() != "fb_init":
        return
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    by_name, bases, methods = _fb_info(ctx)
    owner = _resolve_fb(unit.owner_name, by_name)
    if owner is None:
        return
    owner_key = owner.qualified_name.casefold()
    overridable = set(_overridable_methods(owner_key, by_name, bases, methods))
    if not overridable:
        return

    seen = set()
    for match in _THIS_CALL.finditer(section.text):
        name = match.group("name")
        key = name.casefold()
        if key in overridable and key not in seen:
            seen.add(key)
            yield finding_in(
                message=(
                    f"overridable method '{name}' is called from FB_Init; "
                    "derived state may not be initialized"
                ),
                unit=unit,
                offset=section.at(match.start("name")),
                end_offset=section.at(match.end("name")),
                anchor=name,
                context=match.group(0),
            )

    for match in _BARE_CALL.finditer(section.text):
        name = match.group("name")
        key = name.casefold()
        if key in _CONTROL_WORDS or key not in overridable or key in seen:
            continue
        if match.start() and section.text[:match.start()].rstrip().endswith((".", "^")):
            continue
        if _is_super_call(section.text, match.start()):
            continue
        seen.add(key)
        yield finding_in(
            message=(
                f"overridable method '{name}' is called from FB_Init; "
                "derived state may not be initialized"
            ),
            unit=unit,
            offset=section.at(match.start("name")),
            end_offset=section.at(match.end("name")),
            anchor=name,
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0090",
    title="Overridable method called from FB_Init",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds=(K.METHOD,),
    summary="Dynamic dispatch during FB_Init can reach partially initialized derived state.",
    topic="Correctness",
    check=check,
)
