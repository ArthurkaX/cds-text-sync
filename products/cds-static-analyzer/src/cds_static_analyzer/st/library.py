"""Names of standard IEC 61131-3 and CODESYS library symbols."""

from __future__ import annotations


KNOWN_FUNCTIONS = frozenset(
    {
        "ABS", "ACOS", "ASIN", "ATAN", "COS", "EXP", "LN", "LOG", "SIN", "SQRT", "TAN",
        "SEL", "MAX", "MIN", "LIMIT", "MUX",
        "GT", "GE", "EQ", "LE", "LT", "NE",
        "SHL", "SHR", "ROL", "ROR",
        "LEFT", "RIGHT", "MID", "LEN", "FIND", "REPLACE", "INSERT", "DELETE",
        "CONCAT", "MOVE", "DEREF", "ADR", "REF", "SIZEOF",
        "TO_STRING", "TO_WSTRING", "TRUNC", "INT", "REAL", "LREAL", "DINT", "UDINT",
        "WORD", "DWORD", "BYTE", "BOOL",
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
    return upper in KNOWN_FUNCTIONS or any(
        upper.startswith(prefix)
        for prefix in (
            "TO_", "BOOL_TO_", "INT_TO_", "REAL_TO_", "STRING_TO_", "WORD_TO_"
        )
    )


def is_known_function_block(name):
    return (name or "").strip().rsplit(".", 1)[-1].upper() in KNOWN_FUNCTION_BLOCKS
