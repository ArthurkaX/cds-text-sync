# -*- coding: utf-8 -*-
"""
ide_apply_patch_regression.py - Fast fake-IDE checks for ide_apply_patch.
"""

import os
import tempfile
import xml.etree.ElementTree as ET

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
        self.owner.project.events.append(
            "replace:{0}:{1}:{2}".format(
                self.owner.name,
                self.kind,
                value,
            )
        )


class FakeObject(object):
    def __init__(self, project, name, parent=None, no_create_child=False):
        self.project = project
        self.name = name
        self.parent = parent
        self.no_create_child = no_create_child
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
        return self._add_child(
            FakeObject(
                self.project,
                name,
                self,
                no_create_child=(name == "NoCreateChildFolder"),
            )
        )

    def create_pou(self, name, pou_type, return_type=None):
        # Mirror the real CODESYS API: FUNCTION requires a return_type. Record
        # it in the event when present so tests can assert it was passed.
        if return_type is None:
            self.project.events.append(
                "create_pou:{0}:{1}:{2}".format(self.name, name, pou_type)
            )
        else:
            self.project.events.append(
                "create_pou:{0}:{1}:{2}:{3}".format(
                    self.name, name, pou_type, return_type
                )
            )
        return self._add_child(FakeObject(self.project, name, self))

    def create_gvl(self, name):
        self.project.events.append("create_gvl:{0}:{1}".format(self.name, name))
        return self._add_child(FakeObject(self.project, name, self))

    def create_child(self, name, type_guid):
        if self.no_create_child:
            raise AttributeError("create_child is not available on {0}".format(self.name))
        # Check project-level fail_guids (used by FakeProjectNoCreateChild).
        if hasattr(self.project, "fail_guids") and self.project.fail_guids:
            guid_str = str(type_guid).strip("{").strip("}").lower()
            for fail in self.project.fail_guids:
                if guid_str == str(fail).strip("{").strip("}").lower():
                    raise Exception(
                        "create_child failed for type_guid {0}".format(type_guid)
                    )
        self.project.events.append(
            "create_child:{0}:{1}:{2}".format(self.name, name, type_guid)
        )
        return self._add_child(FakeObject(self.project, name, self))

    def create_persistentvars(self, name):
        if getattr(self.project, "disable_persistentvars", False):
            raise AttributeError(
                "create_persistentvars is not available on {0}".format(self.name)
            )
        self.project.events.append(
            "create_persistentvars:{0}:{1}".format(self.name, name)
        )
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
        try:
            root = ET.parse(patch_path).getroot()
            if root.tag != "Project":
                return
            name = None
            path_parts = []
            for elem in root.iter():
                if elem.attrib.get("Name") == "MetaObject":
                    for child in list(elem):
                        if child.attrib.get("Name") == "Name":
                            name = child.text
                            break
                if elem.attrib.get("Name") == "Path":
                    for child in list(elem):
                        if child.text:
                            path_parts.append(child.text)
            if not name:
                return
            current = self
            for part in path_parts:
                found = None
                for child in current.children:
                    if child.name == part:
                        found = child
                        break
                if found is None:
                    found = current._add_child(FakeObject(self, part, current))
                current = found
            current._add_child(FakeObject(self, name, current))
        except Exception:
            pass


class FakeProjectNoCreateChild(FakeProject):
    """A fake project where create_child fails for certain type GUIDs.

    Simulates CODESYS environments where the first GUID candidate is rejected
    and the fallback GUID must be tried instead.
    """

    def __init__(self, fail_guids=None):
        super(FakeProjectNoCreateChild, self).__init__()
        self.fail_guids = set(fail_guids or [])


class FakeProjectPersistentApiOnly(FakeProjectNoCreateChild):
    def __init__(self):
        super(FakeProjectPersistentApiOnly, self).__init__(
            fail_guids=[
                "{3183921b-cc91-4712-9781-c3b6555122b5}",
                "{261bd6e6-249c-4232-bb6f-84c2fbeef430}",
            ]
        )


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
    # --- Test existing textual object can be updated when only textual_declaration exists ---
    patch_path_existing_duck = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<StructuredView>"
        '<Single Name="EntryList">'
        "<Single>"
        '<Single Name="MetaObject">'
        '<Single Name="Guid">DuckText</Single>'
        "</Single>"
        '<Single Name="Object">'
        '<Single Name="Interface">'
        '<Single Name="TextBlobForSerialisation">VAR_GLOBAL\n    duck_value : INT;\nEND_VAR</Single>'
        "</Single>"
        "</Single>"
        "</Single>"
        "</Single>"
        "</StructuredView>"
        "</Project>"
    )
    try:
        project_existing_duck = FakeProject()
        duck_obj = project_existing_duck._add_child(
            FakeObject(project_existing_duck, "DuckText", project_existing_duck)
        )
        duck_obj.has_textual_declaration = False
        if not apply_patch(None, project_existing_duck, patch_path_existing_duck):
            raise RegressionFailure("apply_patch for duck textual object returned False")
        _assert(
            duck_obj.textual_declaration.text
            == "VAR_GLOBAL\n    duck_value : INT;\nEND_VAR",
            "Existing textual object with false has_textual_declaration was not updated",
        )
    finally:
        if os.path.exists(patch_path_existing_duck):
            os.remove(patch_path_existing_duck)

    patch_path = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<CreateTextObjects>"
        '<CreateTextObject Path="Device/Application/NewParent.st" Name="NewParent" Kind="pou">'
        "<Declaration>FUNCTION_BLOCK NewParent\nVAR\nEND_VAR</Declaration>"
        "<Implementation>enabled := TRUE;</Implementation>"
        "</CreateTextObject>"
        '<CreateTextObject Path="Device/Application/NewDut.st" Name="NewDut" Kind="dut">'
        "<Declaration>TYPE NewDut : INT; END_TYPE</Declaration>"
        "</CreateTextObject>"
        '<CreateTextObject Path="Device/Application/NewGlobals.st" Name="NewGlobals" Kind="gvl">'
        "<Declaration>VAR_GLOBAL\n    g_value : INT;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        '<CreateTextObject Path="Device/Application/NewPersistent.st" Name="NewPersistent" Kind="persistent_gvl">'
        "<Declaration>VAR_GLOBAL PERSISTENT\n    p_value : INT;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        '<CreateTextObject Path="Device/Application/NewParent.Init.st" Name="Init" Kind="method" ParentName="NewParent">'
        "<Declaration>METHOD Init : BOOL\nVAR_INPUT\nEND_VAR</Declaration>"
        "<Implementation>Init := TRUE;</Implementation>"
        "</CreateTextObject>"
        '<CreateTextObject Path="Device/Application/NewFunc.st" Name="NewFunc" Kind="pou">'
        "<Declaration>FUNCTION NewFunc : BOOL\nVAR_INPUT\nEND_VAR</Declaration>"
        "<Implementation>NewFunc := TRUE;</Implementation>"
        "</CreateTextObject>"
        "</CreateTextObjects>"
        "</Project>"
    )
    try:
        project = FakeProject()
        if not apply_patch(None, project, patch_path):
            raise RegressionFailure("apply_patch returned False")

        events = project.events
        _assert(
            "create_folder:Project:Device" in events, "Device folder was not created"
        )
        _assert(
            "create_folder:Device:Application" in events,
            "Application folder was not created",
        )
        _assert(
            "create_pou:Application:NewParent:FunctionBlock" in events,
            "FunctionBlock POU was not created with the expected type",
        )
        _assert("create_dut:Application:NewDut" in events, "DUT was not created")
        _assert("create_gvl:Application:NewGlobals" in events, "GVL was not created")
        _assert(
            "create_pou:Application:NewFunc:Function:BOOL" in events,
            "FUNCTION POU was not created with its parsed return type",
        )
        _assert(
            "create_child:Application:NewPersistent:{3183921b-cc91-4712-9781-c3b6555122b5}"
            in events,
            "Persistent GVL was not created via create_child",
        )
        _assert(
            "create_method:NewParent:Init" in events,
            "Method was not created under parent POU",
        )
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
        _assert(
            new_parent.textual_implementation.text == "enabled := TRUE;",
            "Parent implementation was not written",
        )
        init = new_parent.children[0]
        _assert(
            init.textual_declaration.text.startswith("METHOD Init"),
            "Method declaration was not written",
        )
        _assert(
            init.textual_implementation.text == "Init := TRUE;",
            "Method implementation was not written",
        )
    finally:
        if os.path.exists(patch_path):
            os.remove(patch_path)

    # --- Test task_local_gvl creation ---
    patch_path_tl = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<CreateTextObjects>"
        '<CreateTextObject Path="Device/Application/TaskLocalGVL.st" Name="TaskLocalGVL" Kind="task_local_gvl">'
        "<Declaration>{attribute 'qualified_only'}\nVAR_GLOBAL\n    x : INT;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        "</CreateTextObjects>"
        "</Project>"
    )
    try:
        project_tl = FakeProject()
        if not apply_patch(None, project_tl, patch_path_tl):
            raise RegressionFailure("apply_patch for task_local_gvl returned False")
        tl_events = project_tl.events
        _assert(
            "create_child:Application:TaskLocalGVL:{c2cda7a9-0ba4-4146-b563-22a42fa0eb72}"
            in tl_events,
            "Task local GVL was not created via create_child with expected GUID",
        )
    finally:
        if os.path.exists(patch_path_tl):
            os.remove(patch_path_tl)

    # --- Test GUID fallback: first GUID fails, second succeeds ---
    patch_path_fb = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<CreateTextObjects>"
        '<CreateTextObject Path="Device/Application/FallbackPersistent.st" Name="FallbackPersistent" Kind="persistent_gvl">'
        "<Declaration>VAR_GLOBAL PERSISTENT\n    fb : BOOL;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        "</CreateTextObjects>"
        "</Project>"
    )
    try:
        # Simulate a CODESYS environment where the first GUID is rejected.
        project_fb = FakeProjectNoCreateChild(
            fail_guids=["{3183921b-cc91-4712-9781-c3b6555122b5}"],
        )
        if not apply_patch(None, project_fb, patch_path_fb):
            raise RegressionFailure("apply_patch for GUID fallback returned False")
        fb_events = project_fb.events
        _assert(
            "create_child:Application:FallbackPersistent:{261bd6e6-249c-4232-bb6f-84c2fbeef430}"
            in fb_events,
            "Persistent GVL fallback GUID was not used after first GUID failed",
        )
    finally:
        if os.path.exists(patch_path_fb):
            os.remove(patch_path_fb)

    # --- Test TypeGuid is preferred over fallback candidates ---
    patch_path_tg = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<CreateTextObjects>"
        '<CreateTextObject Path="Device/Application/ProfilePreferred.st" Name="ProfilePreferred" Kind="persistent_gvl" TypeGuid="{261bd6e6-249c-4232-bb6f-84c2fbeef430}">'
        "<Declaration>VAR_GLOBAL PERSISTENT\n    pref : BOOL;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        "</CreateTextObjects>"
        "</Project>"
    )
    try:
        project_tg = FakeProject()
        if not apply_patch(None, project_tg, patch_path_tg):
            raise RegressionFailure("apply_patch for TypeGuid-first returned False")
        tg_events = project_tg.events
        _assert(
            "create_child:Application:ProfilePreferred:{261bd6e6-249c-4232-bb6f-84c2fbeef430}"
            in tg_events,
            "TypeGuid from patch was not preferred over built-in fallback GUID",
        )
    finally:
        if os.path.exists(patch_path_tg):
            os.remove(patch_path_tg)

    # --- Test official persistent variable list API fallback ---
    patch_path_pvars = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<CreateTextObjects>"
        '<CreateTextObject Path="Device/Application/PersistentApiOnly.st" Name="PersistentApiOnly" Kind="persistent_gvl" TypeGuid="{261bd6e6-249c-4232-bb6f-84c2fbeef430}">'
        "<Declaration>VAR_GLOBAL PERSISTENT\n    api_value : BOOL;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        "</CreateTextObjects>"
        "</Project>"
    )
    try:
        project_pvars = FakeProjectPersistentApiOnly()
        if not apply_patch(None, project_pvars, patch_path_pvars):
            raise RegressionFailure("apply_patch for create_persistentvars returned False")
        pvars_events = project_pvars.events
        _assert(
            "create_persistentvars:Application:PersistentApiOnly" in pvars_events,
            "Persistent GVL was not created via create_persistentvars fallback",
        )
    finally:
        if os.path.exists(patch_path_pvars):
            os.remove(patch_path_pvars)

    # --- Test create_child fallback to parent path containers ---
    patch_path_nested = _write_patch(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<Project>"
        "<CreateTextObjects>"
        '<CreateTextObject Path="Device/Application/NoCreateChildFolder/NestedPersistent.st" Name="NestedPersistent" Kind="persistent_gvl" TypeGuid="{261bd6e6-249c-4232-bb6f-84c2fbeef430}">'
        "<Declaration>VAR_GLOBAL PERSISTENT\n    nested : BOOL;\nEND_VAR</Declaration>"
        "</CreateTextObject>"
        "</CreateTextObjects>"
        "</Project>"
    )
    try:
        project_nested = FakeProject()
        if not apply_patch(None, project_nested, patch_path_nested):
            raise RegressionFailure("apply_patch for nested parent fallback returned False")
        nested_events = project_nested.events
        _assert(
            "create_child:Application:NestedPersistent:{261bd6e6-249c-4232-bb6f-84c2fbeef430}"
            in nested_events,
            "Persistent GVL was not retried on parent container after folder create_child failed",
        )
    finally:
        if os.path.exists(patch_path_nested):
            os.remove(patch_path_nested)

    print("ide_apply_patch_regression: PASS")


if __name__ == "__main__":
    main()
