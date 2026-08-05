"""
kinds.py - Canonical kind taxonomy for ``cts analyze``.

The existing detectors in ``engine`` are not reusable as-is for the analyzer:

* ``variable_map.detect_owner_kind`` collapses FUNCTION and METHOD into
  ``function``;
* ``folder_reader._detect_st_kind`` collapses PROGRAM / FUNCTION_BLOCK /
  FUNCTION into ``pou``.

Both are right for their tasks, but "state is forbidden in a function" must
not fire on a method, and "virtual call in FB_Init" is meaningless on a
program. So the analyzer has its own taxonomy.

Per the implementation plan, v1 determines a kind from the ST keyword and the
project-view structure -- not from GUIDs or IDE.xml. Unknown objects stay
``unknown``; a Diagnostic is recorded only when a rule actually needed the
object parsed.

Groups: ``CALLABLE``, ``POU``, ``TYPE``, ``ANY``. A rule declares a group
(or a list of kinds); the runner expands groups before dispatch.
"""

from __future__ import annotations

import re

from cds_static_analyzer.st.blanking import blank_noise
from cds_static_analyzer.st.declarations import parse_dut

_blank_noise = blank_noise

# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------

PROGRAM = "program"
FUNCTION_BLOCK = "function_block"
FUNCTION = "function"
METHOD = "method"
ACTION = "action"
PROPERTY_GET = "property_get"
PROPERTY_SET = "property_set"
INTERFACE = "interface"
GVL = "gvl"
GVL_PERSISTENT = "gvl_persistent"
STRUCT = "struct"
ENUM = "enum"
UNION = "union"
ALIAS = "alias"
VISUALIZATION = "visualization"
TEXTLIST = "textlist"
TASK_CONFIG = "task_config"
UNKNOWN = "unknown"

ALL_KINDS = frozenset(
    {
        PROGRAM,
        FUNCTION_BLOCK,
        FUNCTION,
        METHOD,
        ACTION,
        PROPERTY_GET,
        PROPERTY_SET,
        INTERFACE,
        GVL,
        GVL_PERSISTENT,
        STRUCT,
        ENUM,
        UNION,
        ALIAS,
        VISUALIZATION,
        TEXTLIST,
        TASK_CONFIG,
        UNKNOWN,
    }
)

CALLABLE = frozenset(
    {
        PROGRAM,
        FUNCTION_BLOCK,
        FUNCTION,
        METHOD,
        ACTION,
        PROPERTY_GET,
        PROPERTY_SET,
    }
)
POU = frozenset(
    {
        PROGRAM,
        FUNCTION_BLOCK,
        FUNCTION,
        METHOD,
        ACTION,
        PROPERTY_GET,
        PROPERTY_SET,
        INTERFACE,
    }
)
TYPE = frozenset({STRUCT, ENUM, UNION, ALIAS})
ANY = frozenset(ALL_KINDS)

GROUPS = {
    "CALLABLE": CALLABLE,
    "POU": POU,
    "TYPE": TYPE,
    "ANY": ANY,
}

# Kinds that live in native XML files rather than .st projections.
XML_KINDS = frozenset({VISUALIZATION, TEXTLIST, TASK_CONFIG})


def expand_kinds(spec):
    """Expand a rule's kind declaration into a set of concrete kinds.

    Accepts a single kind name, a group name, or a list of both.
    """
    if spec is None:
        return set(ANY)
    if isinstance(spec, str):
        items = [spec]
    else:
        items = list(spec)
    result = set()
    for item in items:
        key = str(item).upper()
        if key in GROUPS:
            result |= GROUPS[key]
        elif str(item) in ALL_KINDS:
            result.add(str(item))
        else:
            raise ValueError(f"unknown kind or group: {item!r}")
    return result


# ---------------------------------------------------------------------------
# ST keyword detection
# ---------------------------------------------------------------------------

# Leading keyword of the first non-attribute, non-comment line.
_HEADER_KEYWORDS = frozenset(
    {
        "PROGRAM",
        "FUNCTION_BLOCK",
        "FUNCTION",
        "METHOD",
        "ACTION",
        "PROPERTY",
        "INTERFACE",
        "TYPE",
        "VAR_GLOBAL",
    }
)


def _leading_keyword(decl):
    """Return the first significant keyword of *decl*, uppercased, or None.

    Attribute pragmas and comments are blanked by ``_blank_noise``, so the
    first non-empty line is the header line itself. A first token that is not
    a known header keyword means the blob cannot be classified.
    """
    blanked = _blank_noise(decl or "")
    for raw_line in blanked.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        first = line.split()[0].upper()
        if first in _HEADER_KEYWORDS:
            return first
        return None
    return None


def classify_st_decl(decl):
    """Classify a .st declaration blob into a canonical kind.

    Returns ``UNKNOWN`` when the blob has no recognisable header.
    """
    keyword = _leading_keyword(decl)
    if keyword is None:
        return UNKNOWN

    if keyword == "PROGRAM":
        return PROGRAM
    if keyword == "FUNCTION_BLOCK":
        return FUNCTION_BLOCK
    if keyword == "FUNCTION":
        return FUNCTION
    if keyword == "METHOD":
        return METHOD
    if keyword == "ACTION":
        return ACTION
    if keyword == "INTERFACE":
        return INTERFACE
    if keyword == "PROPERTY":
        # property X GET / property X SET
        blanked = _blank_noise(decl or "")
        first = blanked.split("\n", 1)[0]
        if re.search(r"\bSET\b", first, re.IGNORECASE):
            return PROPERTY_SET
        return PROPERTY_GET
    if keyword == "TYPE":
        return _classify_dut(decl)
    if keyword == "VAR_GLOBAL":
        blanked = _blank_noise(decl or "")
        head = blanked.split("\n", 1)[0].upper()
        if "PERSISTENT" in head:
            return GVL_PERSISTENT
        return GVL
    return UNKNOWN


def _classify_dut(decl):
    """TYPE ... END_TYPE -> struct | union | enum | alias."""
    parsed = parse_dut(decl)
    if parsed is None:
        return UNKNOWN
    if parsed["kind"] == "enum":
        return ENUM
    # variable_map maps UNION to "struct"; distinguish by keyword.
    blanked = _blank_noise(decl or "")
    if re.search(r"\bUNION\b", blanked, re.IGNORECASE):
        return UNION
    if parsed["kind"] == "struct":
        return STRUCT
    return ALIAS


def detect_owner_from_filename(relpath):
    """Owner id for a file whose stem carries ``Owner.Child`` (methods,
    actions, properties). Returns the parent stem or None."""
    stem = relpath.rsplit("/", 1)[-1]
    if "." in stem:
        base = stem.rsplit(".", 1)[0]
        return base
    return None
