"""Contract tests for the analyzer-owned neutral ST declaration parser."""

from cds_static_analyzer.st.declarations import classify_type, parse_dut, parse_var_blocks


def test_parse_var_blocks_preserves_scope_members_and_initializers():
    declaration = """
    PROGRAM Main
    VAR_INPUT
        first, second : INT;
    END_VAR
    VAR
        values AT %MW0 : ARRAY[1..4] OF BYTE := [1, 2, 3, 4];
    END_VAR
    END_PROGRAM
    """

    blocks = parse_var_blocks(declaration)

    assert [block["scope"] for block in blocks] == ["VAR_INPUT", "VAR"]
    assert [member["name"] for member in blocks[0]["members"]] == ["first", "second"]
    assert blocks[1]["members"] == [
        {
            "name": "values",
            "type": "ARRAY[1..4] OF BYTE",
            "scope": "VAR",
            "line": 7,
            "initial": "[1, 2, 3, 4]",
        }
    ]


def test_parse_dut_supports_struct_enum_and_alias():
    struct = parse_dut("TYPE Point : STRUCT x : INT; y : INT; END_STRUCT END_TYPE")
    enum = parse_dut("TYPE State : (Idle, Running := 4, Done); END_TYPE")
    alias = parse_dut("TYPE Counter : UDINT; END_TYPE")

    assert struct["kind"] == "struct"
    assert [field["name"] for field in struct["fields"]] == ["x", "y"]
    assert enum["kind"] == "enum"
    assert [field["value"] for field in enum["fields"]] == [0, 4, 5]
    assert alias == {"name": "Counter", "kind": "alias", "fields": [], "base": "UDINT"}


def test_classify_type_returns_only_neutral_type_information():
    assert classify_type("INT") == {"kind": "scalar", "base": "INT"}
    assert classify_type("ARRAY[-2..3, 0..7] OF BYTE") == {
        "kind": "array",
        "elem": "BYTE",
        "dims": [("-2", "3"), ("0", "7")],
    }
    assert classify_type("MyStruct") == {"kind": "ref", "name": "MyStruct"}
