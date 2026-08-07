"""CTS0084 - repeated control-flow branch bodies are likely accidental."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blanking import comment_spans
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_THEN = re.compile(r"\bTHEN\b", re.IGNORECASE)


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def _content_start(label, text, start):
    upper = label.strip().upper()
    if upper == "ELSE":
        match = re.match(r"\s*ELSE\b", text[start:], re.IGNORECASE)
        return start + (match.end() if match else 0)
    if upper.startswith(("IF ", "ELSIF ")):
        match = _THEN.search(text, start)
        return match.end() if match else start
    colon = text.find(":", start)
    return colon + 1 if colon >= 0 else start


def _normalise(source):
    chars = list(source)
    for start, end, _content in comment_spans(source):
        chars[start:end] = " " * (end - start)
    text = "".join(chars)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    text = re.sub(r"\s*([,;:=()\[\]^.+*/<>-])\s*", r"\1", text)
    return text


def check(unit, ctx):
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    text = section.raw
    for block in _walk(tree(unit)):
        if block.kind not in ("IF", "CASE"):
            continue
        branches = []
        for label, absolute_start, absolute_end in block.branches:
            if absolute_end is None:
                continue
            start = absolute_start - section.base
            end = absolute_end - section.base
            content_start = _content_start(label, text, start)
            normalised = _normalise(text[content_start:end])
            if not normalised or normalised == ";":
                continue
            branches.append((label.strip(), absolute_start, normalised))

        seen = {}
        for label, absolute_start, normalised in branches:
            previous = seen.get(normalised)
            if previous is None:
                seen[normalised] = (label, absolute_start)
                continue
            yield finding_in(
                message=(
                    f"branch '{label}' has the same body as branch "
                    f"'{previous[0]}' in the same {block.kind}"
                ),
                unit=unit,
                offset=absolute_start,
                end_offset=absolute_start + len(label),
                anchor=label,
                context=f"{previous[0]} and {label}",
            )


RULE = RuleSpec(
    id="CTS0084",
    title="Identical control-flow branch bodies",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="Two non-empty branches of one IF or CASE contain the same body.",
    topic="Code quality",
    check=check,
)
