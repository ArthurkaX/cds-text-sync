"""Names of standard IEC 61131-3 and CODESYS library symbols."""

from __future__ import annotations

import re


KNOWN_FUNCTIONS = frozenset(
    {
        "ABS", "ACOS", "ASIN", "ATAN", "COS", "EXP", "LN", "LOG", "SIN", "SQRT", "TAN",
        "SEL", "MAX", "MIN", "LIMIT", "MUX",
        "GT", "GE", "EQ", "LE", "LT", "NE",
        "SHL", "SHR", "ROL", "ROR",
        "LEFT", "RIGHT", "MID", "LEN", "FIND", "REPLACE", "INSERT", "DELETE",
        "CONCAT", "MOVE", "DEREF", "ADR", "REF", "SIZEOF",
        "TO_STRING", "TO_WSTRING", "TRUNC", "INT", "REAL", "LREAL", "DINT", "UDINT",
        "WORD", "DWORD", "BYTE", "BOOL", "TIME", "DATE", "DT", "TOD",
        "STRING", "WSTRING", "LOWER_BOUND", "UPPER_BOUND",
        "SYSMEMCPY", "SYSSOCKBIND", "SYSSOCKCLOSE", "SYSSOCKCREATE",
        "SYSSOCKGETOPTION", "SYSSOCKHTONS", "SYSSOCKINETADDR",
        "SYSSOCKIOCTL", "SYSSOCKRECVFROM", "SYSSOCKSENDTO",
        "SYSSOCKSETOPTION", "SYSSOCKSHUTDOWN",
        "CMADDCOMPONENT2", "COMPONENT_MANAGER.CMADDCOMPONENT2",
        "CMPLOG.LOGADD2", "IECTASKGETCURRENT", "IECTASKGETINFO3",
        "SYSTIMEGETMS",
    }
)

KNOWN_FUNCTION_BLOCKS = frozenset(
    {
        "TON", "TOF", "TP", "R_TRIG", "F_TRIG", "SR", "RS", "CTU", "CTD", "CTUD",
        "PID", "INTEGRAL", "DERIVATIVE",
    }
)


def is_known_function(name):
    upper = (name or "").strip().upper()
    # IEC conversion functions use ``SOURCE_TO_DEST`` names (for example
    # ``DINT_TO_LREAL``).  They are library functions even when a particular
    # width/type combination is not listed in the small built-in table.
    conversion_name = bool(re.fullmatch(r"[A-Z][A-Z0-9]*_TO_[A-Z][A-Z0-9]*", upper))
    return upper in KNOWN_FUNCTIONS or upper.startswith("TO_") or conversion_name


def is_known_function_block(name):
    return (name or "").strip().rsplit(".", 1)[-1].upper() in KNOWN_FUNCTION_BLOCKS
