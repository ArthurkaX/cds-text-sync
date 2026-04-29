# -*- coding: utf-8 -*-
"""
ide_apply_patch_regression.py - Fast fake-IDE checks for ide_apply_patch.
"""
import os
import tempfile

from ide_apply_patch import apply_patch


class RegressionFailure(Exception):
    pass


class PouType(object):
    Program = "Program"
    Function = "Function"
    FunctionBlock = "FunctionBlock"


class FakeTextDocument(object):
    def __init__(self, owner, kind):
        self.owner = owner
        self.kind = kind
        self.text = ""

    def replace(self, value):
        self.text = value
        self.owner.project.events.append("replace:{0}:{1}:{2}".format(
            self.owner.name,
            self.kind,
            value,
        ))


class FakeObject(object):
    def __init__(self, project, name, parent=None):
        self.project = project
        self.name = name
        self.parent = parent
        self.guid = name
        self.children = []
        self.has_textual_declaration = True
        self.has_textual_implementation = True
        self.textual_declaration = FakeTextDocument(self, "declaration")
        self.textual_implementation = FakeTextDocument(self, "implementation")

    def get_name(self):
        return self.name

    def get_children(self, recursive=False):
        if not recursive:
            return list(self.children)
        result = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_children(recursive=True))
        return result

    def _add_child(self, child):
        self.children.append(child)
        return child

    def create_folder(self, name):
        self.project.events.append("create_folder:{0}:{1}".format(self.name, name))
        return self._add_child(FakeObject(self.project, name, self))

    def create_pou(self, name, pou_type):
        self.project.events.append("create_pou:{0}:{1}:{2}".format(self.name, name, pou_type))
        return self._add_child(FakeObject(self.project, name, self))

    def create_gvl(self, name):
        self.project.events.append("create_gvl:{0}:{1}".format(self.name, name))
        return self._add_child(FakeObject(self.project, name, self))

    def create_dut(self, name):
        self.project.events.append("create_dut:{0}:{1}".format(self.name, name))
        return self._add_child(FakeObject(self.project, name, self))

    def create_method(self, name):
        self.project.events.append("create_method:{0}:{1}".format(self.name, name))
        return self._add_child(FakeObject(self.project, name, self))


class FakeProject(FakeObject):
    def __init__(self):
        self.events = []
        FakeObject.__init__(self, self, "Project", None)

    def import_native(self, patch_path):
        self.events.append("import_native:{0}".format(os.path.basename(patch_path)))


def _write_patch(content):
    handle, path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    with open(path, "w") as f:
        f.write(content)
    return path


def _assert(condition, message):
    if not condition:
        raise RegressionFailure(message)


def main():
    patch_path = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Project>'
        '<CreateTextObjects>'
        '<CreateTextObject Path="Device/Application/NewParent.st" Name="NewParent" Kind="pou">'
        '<Declaration>FUNCTION_BLOCK NewParent\nVAR\nEND_VAR</Declaration>'
        '<Implementation>enabled := TRUE;</Implementation>'
        '</CreateTextObject>'
        '<CreateTextObject Path="Device/Application/NewDut.st" Name="NewDut" Kind="dut">'
        '<Declaration>TYPE NewDut : INT; END_TYPE</Declaration>'
        '</CreateTextObject>'
        '<CreateTextObject Path="Device/Application/NewGlobals.st" Name="NewGlobals" Kind="gvl">'
        '<Declaration>VAR_GLOBAL\n    g_value : INT;\nEND_VAR</Declaration>'
        '</CreateTextObject>'
        '<CreateTextObject Path="Device/Application/NewParent.Init.st" Name="Init" Kind="method" ParentName="NewParent">'
        '<Declaration>METHOD Init : BOOL\nVAR_INPUT\nEND_VAR</Declaration>'
        '<Implementation>Init := TRUE;</Implementation>'
        '</CreateTextObject>'
        '</CreateTextObjects>'
        '</Project>'
    )
    try:
        project = FakeProject()
        if not apply_patch(None, project, patch_path):
            raise RegressionFailure("apply_patch returned False")

        events = project.events
        _assert("create_folder:Project:Device" in events, "Device folder was not created")
        _assert("create_folder:Device:Application" in events, "Application folder was not created")
        _assert(
            "create_pou:Application:NewParent:FunctionBlock" in events,
            "FunctionBlock POU was not created with the expected type",
        )
        _assert("create_dut:Application:NewDut" in events, "DUT was not created")
        _assert("create_gvl:Application:NewGlobals" in events, "GVL was not created")
        _assert("create_method:NewParent:Init" in events, "Method was not created under parent POU")
        _assert(
            events.index("create_pou:Application:NewParent:FunctionBlock")
            < events.index("create_method:NewParent:Init"),
            "Method was created before parent POU",
        )

        new_parent = project.children[0].children[0].children[0]
        _assert(
            new_parent.textual_declaration.text.startswith("FUNCTION_BLOCK NewParent"),
            "Parent declaration was not written",
        )
        _assert(new_parent.textual_implementation.text == "enabled := TRUE;", "Parent implementation was not written")
        init = new_parent.children[0]
        _assert(init.textual_declaration.text.startswith("METHOD Init"), "Method declaration was not written")
        _assert(init.textual_implementation.text == "Init := TRUE;", "Method implementation was not written")
    finally:
        if os.path.exists(patch_path):
            os.remove(patch_path)

    print("ide_apply_patch_regression: PASS")


if __name__ == "__main__":
    main()
