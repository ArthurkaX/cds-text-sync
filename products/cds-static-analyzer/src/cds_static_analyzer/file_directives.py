"""Source-level directives that apply to a complete ST file."""

from __future__ import annotations

import re

_LINE_RE = re.compile(
    r"(?im)^[ \t]*//[ \t]*cts:ignore-file\b([^\r\n]*)"
)
_BLOCK_RE = re.compile(
    r"(?ims)^[ \t]*\(\*[ \t]*cts:ignore-file\b(.*?)[ \t]*\*\)"
)


def directive_info(text: str):
    """Return ``(rules, issues)`` for file directives.

    Issues are ``(kind, detail, line)`` tuples and are intentionally kept
    parser-level so the runner can attach source paths and rule metadata.
    """
    rules: set[str] = set()
    issues = []
    for match in (*_LINE_RE.finditer(text or ""), *_BLOCK_RE.finditer(text or "")):
        raw = match.group(1).strip()
        line = (text or "")[: match.start()].count("\n") + 1
        delimiter = "--" if "--" in raw else ("—" if "—" in raw else None)
        if delimiter is None:
            issues.append(("directive-missing-reason", "reason is required", line))
            continue
        payload = raw.split(delimiter, 1)[0]
        if delimiter == "—":
            issues.append(("directive-em-dash", "use '--' before the reason", line))
        for token in re.split(r"[\s,]+", payload.strip()):
            token = token.upper()
            if token == "*" or re.fullmatch(r"CTS\d{4}", token):
                rules.add(token)
            elif token:
                issues.append(("directive-invalid-rule", token, line))
    return frozenset(rules), tuple(issues)


def ignored_rules(text: str) -> frozenset[str]:
    """Return rule IDs disabled for the whole source file.

    A directive is deliberately line-oriented so prose in a normal comment
    cannot accidentally become an instruction.  The text before ``--`` is
    the rule list; the remainder is a human-readable reason.
    """
    rules, _ = directive_info(text)
    return rules


def is_ignored(rule_id: str, rules: frozenset[str]) -> bool:
    return "*" in rules or rule_id in rules
