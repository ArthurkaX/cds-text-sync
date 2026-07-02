# -*- coding: utf-8 -*-
"""
test_gvl.py -- Tests for ``cli.visu.gvl``.

Verifies variable detection from element specs and correct .st file generation.
"""

import os
import sys
import tempfile

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import gvl


class TestCollectVariables:
    def test_text_var(self):
        elems = [{"params": {"text_var": "HMI.Temperature"}}]
        vars = gvl.collect_variables(elems)
        assert vars == {"HMI.Temperature": "Temperature"}

    def test_tap_var(self):
        elems = [{"params": {"tap_var": "HMI.PanelStart"}}]
        vars = gvl.collect_variables(elems)
        assert vars == {"HMI.PanelStart": "PanelStart"}

    def test_toggle_var(self):
        elems = [{"params": {"toggle_var": "HMI.PumpRun"}}]
        vars = gvl.collect_variables(elems)
        assert vars == {"HMI.PumpRun": "PumpRun"}

    def test_bare_var_no_gvl_prefix(self):
        elems = [{"params": {"text_var": "MyVar"}}]
        vars = gvl.collect_variables(elems)
        assert vars == {"MyVar": "MyVar"}

    def test_configured_inputs_variable(self):
        elems = [
            {
                "params": {
                    "configured_inputs": [
                        {"type": "tap", "values": {"variable": "HMI.Level"}}
                    ]
                }
            }
        ]
        vars = gvl.collect_variables(elems)
        assert vars == {"HMI.Level": "Level"}

    def test_input_actions_variable(self):
        elems = [
            {
                "params": {
                    "input_actions": [
                        {
                            "event": "OnMouseClick",
                            "type": "st_snippet",
                            "values": {"snippet": "HMI.Start := TRUE;"},
                        }
                    ]
                }
            }
        ]
        vars = gvl.collect_variables(elems)
        assert vars == {"HMI.Start": "Start"}

    def test_multiple_variables_deduplicated(self):
        elems = [
            {"params": {"text_var": "HMI.Temp"}},
            {"params": {"tap_var": "HMI.Temp"}},
        ]
        vars = gvl.collect_variables(elems)
        assert vars == {"HMI.Temp": "Temp"}

    def test_no_vars(self):
        elems = [{"params": {"x": "10", "y": "20"}}]
        vars = gvl.collect_variables(elems)
        assert vars == {}

    def test_empty_list(self):
        assert gvl.collect_variables([]) == {}


class TestGenerateGvl:
    def test_basic_output(self):
        vars = {"HMI.Temperature": "Temperature"}
        st = gvl.generate_gvl(vars)
        assert "{attribute 'qualified_only'}" in st
        assert "VAR_GLOBAL" in st
        assert "Temperature" in st
        assert "BOOL" in st
        assert "END_VAR" in st

    def test_multiple_vars(self):
        vars = {"HMI.A": "A", "HMI.B": "B"}
        st = gvl.generate_gvl(vars)
        assert "A" in st
        assert "B" in st

    def test_custom_gvl_name(self):
        vars = {"HMI.X": "X"}
        st = gvl.generate_gvl(vars, gvl_name="CustomGVL")
        # gvl_name doesn't appear in the .st body (only in the filename)
        assert "X" in st

    def test_custom_default_type(self):
        vars = {"HMI.X": "X"}
        st = gvl.generate_gvl(vars, default_type="INT")
        assert "INT" in st

    def test_empty_vars(self):
        assert gvl.generate_gvl({}) == ""


class TestWriteGvlFile:
    def test_writes_file(self, tmp_path):
        path = os.path.join(str(tmp_path), "TestGVL.st")
        gvl.write_gvl_file(path, "VAR_GLOBAL\nEND_VAR")
        assert os.path.isfile(path)
        with open(path) as f:
            assert "VAR_GLOBAL" in f.read()

    def test_creates_parent_dir(self, tmp_path):
        path = os.path.join(str(tmp_path), "sub", "dir", "Test.st")
        gvl.write_gvl_file(path, "VAR_GLOBAL\nEND_VAR")
        assert os.path.isfile(path)

    def test_empty_content_does_nothing(self, tmp_path):
        path = os.path.join(str(tmp_path), "empty.st")
        gvl.write_gvl_file(path, "")
        assert not os.path.isfile(path)


class TestDetectExistingVariables:
    def test_detects_vars(self, tmp_path):
        path = os.path.join(str(tmp_path), "Existing.st")
        with open(path, "w") as f:
            f.write("VAR_GLOBAL\n    Temperature : INT;\nEND_VAR\n")
        existing = gvl.detect_existing_variables(path)
        assert "Temperature" in existing

    def test_no_file(self):
        assert gvl.detect_existing_variables("/nonexistent.st") == set()

    def test_empty_file(self, tmp_path):
        path = os.path.join(str(tmp_path), "Empty.st")
        with open(path, "w") as f:
            f.write("")
        assert gvl.detect_existing_variables(path) == set()


class TestEnsureGvl:
    def test_creates_new_file(self, tmp_path):
        pou_dir = os.path.join(str(tmp_path), "POUs")
        os.makedirs(pou_dir)
        elems = [{"params": {"text_var": "HMI.Test"}}]
        result = gvl.ensure_gvl(str(tmp_path), elems, gvl_name="VisuVars")
        assert result is not None
        assert os.path.isfile(result)
        with open(result) as f:
            assert "Test" in f.read()

    def test_appends_to_existing(self, tmp_path):
        pou_dir = os.path.join(str(tmp_path), "POUs")
        os.makedirs(pou_dir)
        path = os.path.join(pou_dir, "VisuVars.st")
        with open(path, "w") as f:
            f.write("{attribute 'qualified_only'}\nVAR_GLOBAL\nEND_VAR\n")
        elems = [{"params": {"text_var": "HMI.NewVar"}}]
        result = gvl.ensure_gvl(str(tmp_path), elems, gvl_name="VisuVars")
        with open(result) as f:
            content = f.read()
            assert "NewVar" in content
            assert "qualified_only" in content

    def test_no_vars_returns_none(self, tmp_path):
        result = gvl.ensure_gvl(str(tmp_path), [], gvl_name="VisuVars")
        assert result is None

    def test_custom_gvl_path(self, tmp_path):
        custom_path = os.path.join(str(tmp_path), "Custom.st")
        elems = [{"params": {"text_var": "HMI.X"}}]
        result = gvl.ensure_gvl(
            str(tmp_path), elems, gvl_name="VisuVars", gvl_path=custom_path
        )
        assert result == custom_path
        assert os.path.isfile(custom_path)


class TestInferType:
    def test_float(self):
        assert gvl._infer_type("%3.1f C") == "REAL"

    def test_float_variants(self):
        for fmt in ("%f", "%.2F", "%e", "%g"):
            assert gvl._infer_type(fmt) == "REAL", fmt

    def test_int(self):
        assert gvl._infer_type("%d") == "INT"
        assert gvl._infer_type("count=%i") == "INT"

    def test_string(self):
        assert gvl._infer_type("%s") == "STRING"

    def test_empty_and_none_default_bool(self):
        assert gvl._infer_type("") == "BOOL"
        assert gvl._infer_type(None) == "BOOL"

    def test_no_conversion_is_bool(self):
        assert gvl._infer_type("Level OK") == "BOOL"


class TestCollectVariableTypes:
    def test_textfield_format_gives_real(self):
        elems = [{"params": {"text_var": "HMI.OutTemp", "text": "%3.1f C"}}]
        assert gvl.collect_variable_types(elems) == {"HMI.OutTemp": "REAL"}

    def test_button_var_is_bool(self):
        elems = [{"params": {"tap_var": "HMI.Start"}}]
        assert gvl.collect_variable_types(elems) == {"HMI.Start": "BOOL"}

    def test_typed_wins_over_bool(self):
        elems = [
            {"params": {"tap_var": "HMI.V"}},
            {"params": {"text_var": "HMI.V", "text": "%d"}},
        ]
        assert gvl.collect_variable_types(elems) == {"HMI.V": "INT"}


class TestGenerateGvlTypes:
    def test_types_map_overrides_default(self):
        vars = {"HMI.OutTemp": "OutTemp"}
        st = gvl.generate_gvl(vars, types={"HMI.OutTemp": "REAL"})
        assert "OutTemp : REAL;" in st

    def test_generated_gvl_uses_inferred_real(self, tmp_path):
        pou_dir = os.path.join(str(tmp_path), "POUs")
        os.makedirs(pou_dir)
        elems = [{"params": {"text_var": "HMI.Foo", "text": "%3.1f"}}]
        result = gvl.ensure_gvl(str(tmp_path), elems, gvl_name="VisuVars")
        with open(result) as f:
            assert "Foo : REAL;" in f.read()


class TestScanProjectGvls:
    def test_finds_var_in_named_gvl(self, tmp_path):
        hmi_dir = os.path.join(str(tmp_path), "Runtime", "HMI")
        os.makedirs(hmi_dir)
        with open(os.path.join(hmi_dir, "HMI.st"), "w") as f:
            f.write("VAR_GLOBAL\n    OutTemp : REAL;\nEND_VAR\n")
        gvls = gvl.scan_project_gvls(str(tmp_path))
        assert "OutTemp" in gvls.get("HMI", set())

    def test_ignores_non_gvl_st(self, tmp_path):
        with open(os.path.join(str(tmp_path), "MAIN.st"), "w") as f:
            f.write("PROGRAM MAIN\nVAR\n    x : INT;\nEND_VAR\n")
        gvls = gvl.scan_project_gvls(str(tmp_path))
        assert "MAIN" not in gvls


class TestCrossGvlDedup:
    def test_var_in_other_gvl_not_redeclared(self, tmp_path):
        # HMI GVL already declares OutTemp -> VisuVars must not be written.
        pou_dir = os.path.join(str(tmp_path), "POUs")
        os.makedirs(pou_dir)
        hmi_dir = os.path.join(str(tmp_path), "Runtime", "HMI")
        os.makedirs(hmi_dir)
        with open(os.path.join(hmi_dir, "HMI.st"), "w") as f:
            f.write("VAR_GLOBAL\n    OutTemp : REAL;\nEND_VAR\n")
        elems = [{"params": {"text_var": "HMI.OutTemp", "text": "%3.1f"}}]
        result = gvl.ensure_gvl(str(tmp_path), elems, gvl_name="VisuVars")
        # Path is returned but the file is never created (nothing new to add).
        assert not os.path.isfile(os.path.join(pou_dir, "VisuVars.st"))

    def test_new_var_still_declared(self, tmp_path):
        pou_dir = os.path.join(str(tmp_path), "POUs")
        os.makedirs(pou_dir)
        hmi_dir = os.path.join(str(tmp_path), "Runtime", "HMI")
        os.makedirs(hmi_dir)
        with open(os.path.join(hmi_dir, "HMI.st"), "w") as f:
            f.write("VAR_GLOBAL\n    OutTemp : REAL;\nEND_VAR\n")
        # OutTemp exists in HMI; NewOne does not -> only NewOne declared.
        elems = [
            {"params": {"text_var": "HMI.OutTemp", "text": "%3.1f"}},
            {"params": {"tap_var": "HMI.NewOne"}},
        ]
        result = gvl.ensure_gvl(str(tmp_path), elems, gvl_name="VisuVars")
        with open(result) as f:
            content = f.read()
        assert "NewOne" in content
        assert "OutTemp" not in content
