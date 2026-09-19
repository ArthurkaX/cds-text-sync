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
    member = blocks[1]["members"][0]
    assert {key: member[key] for key in ("name", "type", "scope", "line", "initial")} == {
        "name": "values",
        "type": "ARRAY[1..4] OF BYTE",
        "scope": "VAR",
        "line": 7,
        "initial": "[1, 2, 3, 4]",
    }
    assert member["source_span"]["line"] == 7


def test_parse_var_blocks_preserves_retain_persistent_modifiers_and_spans():
    blocks = parse_var_blocks(
        "FUNCTION_BLOCK FB\n"
        "VAR RETAIN\n    xRetained : BOOL;\nEND_VAR\n"
        "VAR_GLOBAL PERSISTENT\n    xPersistent : INT;\nEND_VAR\n"
    )

    assert blocks[0]["retain"] is True
    assert blocks[0]["persistent"] is False
    assert blocks[1]["persistent"] is True
    assert blocks[0]["members"][0]["source_span"]["line"] == 3
    span = blocks[1]["members"][0]["source_span"]
    assert span["start"] < span["end"]


def test_parse_dut_supports_struct_enum_and_alias():
    struct = parse_dut("TYPE Point : STRUCT x : INT; y : INT; END_STRUCT END_TYPE")
    enum = parse_dut("TYPE State : (Idle, Running := 4, Done); END_TYPE")
    alias = parse_dut("TYPE Counter : UDINT; END_TYPE")

    assert struct["kind"] == "struct"
    assert [field["name"] for field in struct["fields"]] == ["x", "y"]
    assert enum["kind"] == "enum"
    assert [field["value"] for field in enum["fields"]] == [0, 4, 5]
    assert alias == {"name": "Counter", "kind": "alias", "fields": [], "base": "UDINT"}


def test_parse_dut_distinguishes_union_and_reports_partial_members():
    parsed = parse_dut(
        "TYPE Overlay : UNION first : WORD; broken member; second : BYTE; "
        "END_UNION END_TYPE"
    )

    assert parsed["kind"] == "union"
    assert [field["name"] for field in parsed["fields"]] == ["first", "second"]
    assert parsed["warnings"] == ["unparsed union member"]


def test_parse_dut_preserves_attributes_enum_base_comments_and_unknown_values():
    declaration = """
    {attribute 'qualified_only'}
    {attribute 'strict'}
    TYPE State :
    (
        Idle := 0, // waiting
        Running := ExternalValue, // running
        Done // cannot infer after an unknown value
    ) UINT;
    END_TYPE
    """

    parsed = parse_dut(declaration)

    assert parsed["attributes"] == ["qualified_only", "strict"]
    assert parsed["qualified_only"] is True
    assert parsed["strict"] is True
    assert parsed["base_type"] == "UINT"
    assert [field["type"] for field in parsed["fields"]] == ["UINT"] * 3
    assert parsed["fields"][0]["value"] == 0
    assert parsed["fields"][1]["value"] is None
    assert parsed["fields"][1]["raw_value"] == "ExternalValue"
    assert parsed["fields"][2]["value"] is None
    assert parsed["fields"][0]["comment"] == "waiting"


def test_parse_dut_preserves_struct_extends_fields_comments_and_lines():
    declaration = """
    TYPE Child EXTENDS Parent :
    STRUCT
        xValue : INT; // child value
        xReady : BOOL;
    END_STRUCT
    END_TYPE
    """

    parsed = parse_dut(declaration)

    assert parsed["extends"] == "Parent"
    assert [field["name"] for field in parsed["fields"]] == ["xValue", "xReady"]
    assert parsed["fields"][0]["comment"] == "child value"
    assert parsed["fields"][0]["line"] is not None


def test_classify_type_returns_only_neutral_type_information():
    assert classify_type("INT") == {"kind": "scalar", "base": "INT"}
    assert classify_type("ARRAY[-2..3, 0..7] OF BYTE") == {
        "kind": "array",
        "elem": "BYTE",
        "dims": [("-2", "3"), ("0", "7")],
    }
    assert classify_type("MyStruct") == {"kind": "ref", "name": "MyStruct"}
