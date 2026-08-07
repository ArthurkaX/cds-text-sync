"""Compatibility surface for the shared Structured Text declaration parser."""

from cts_shared.st import declarations as _shared

SCALAR_TYPES = _shared.SCALAR_TYPES
_split_top_level = _shared._split_top_level
_split_statements = _shared._split_statements
_parse_member_statement = _shared._parse_member_statement
parse_var_blocks = _shared.parse_var_blocks
parse_dut = _shared.parse_dut
_base_type_name = _shared._base_type_name
_split_dims = _shared._split_dims
classify_type = _shared.classify_type

__all__ = [
    "SCALAR_TYPES",
    "parse_var_blocks",
    "parse_dut",
    "classify_type",
]
