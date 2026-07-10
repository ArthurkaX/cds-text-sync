# -*- coding: utf-8 -*-
"""
ide_apply_patch.pyw - Apply a prepared IMPORT.xml patch to the IDE.
Must be compatible with IronPython 2.7.
"""

from __future__ import print_function

import codecs
import copy
import os
import re
import tempfile
import xml.etree.ElementTree as ET

from ide_runtime_common import normalize_guid, object_name


class ApplyPatchResult(object):
    def __init__(self):
        self.success = True
        self.error = ""
        self.applied_guids = []
        self.native_guids = []
        self.textual_guids = []
        self.created_paths = []
        self.failed_guids = []
        self.failures = []

    def __nonzero__(self):
        return bool(self.success)

    def __bool__(self):
        return bool(self.success)

    def add_applied(self, guid, mode):
        guid = normalize_guid(guid)
        if guid and guid not in self.applied_guids:
            self.applied_guids.append(guid)
        if mode == "native" and guid and guid not in self.native_guids:
            self.native_guids.append(guid)
        if mode == "textual" and guid and guid not in self.textual_guids:
            self.textual_guids.append(guid)

    def add_created(self, path):
        path = str(path or "")
        if path and path not in self.created_paths:
            self.created_paths.append(path)

    def fail(self, error, guid=None):
        self.success = False
        self.error = str(error)
        normalized_guid = normalize_guid(guid)
        if normalized_guid and normalized_guid not in self.failed_guids:
            self.failed_guids.append(normalized_guid)
        self.failures.append(
            {
                "guid": normalized_guid,
                "error": self.error,
            }
        )
        return self

    def summary(self):
        parts = []
        if self.applied_guids:
            parts.append("applied={0}".format(len(self.applied_guids)))
        if self.created_paths:
            parts.append("created={0}".format(len(self.created_paths)))
        if self.failed_guids:
            parts.append("failed_guids={0}".format(",".join(self.failed_guids)))
        if self.error:
            parts.append("error=" + self.error)
        return "; ".join(parts) or ("success" if self.success else "failed")


def _parse_patch(patch_path):
    root = ET.parse(patch_path).getroot()
    return {
        "root": root,
        "guids": _patch_object_guids(root),
        "texts": _patch_text_by_guid(root),
        "build_attrs": _patch_build_attrs_by_guid(root),
        "text_creates": _text_create_entries(root),
        "native_creates": _native_create_entries(root),
    }


def _patch_object_guids(root):
    guids = []
    for elem in root.iter():
        if elem.attrib.get("Name") != "MetaObject":
            continue
        for child in list(elem):
            if child.attrib.get("Name") == "Guid" and child.text:
                guid = normalize_guid(child.text)
                if guid and guid not in guids:
                    guids.append(guid)
                break
    return guids


def _children(element):
    try:
        return list(element)
    except Exception:
        return []


def _named_child(element, name):
    for child in _children(element):
        if child.attrib.get("Name") == name:
            return child
    return None


def _named_descendant(element, name):
    for child in element.iter():
        if child.attrib.get("Name") == name:
            return child
    return None


def _local_name(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _text_blob(section):
    if section is None:
        return None
    blob = _named_descendant(section, "TextBlobForSerialisation")
    if blob is not None:
        return blob.text or ""
    return None


def _patch_text_by_guid(root):
    result = {}
    for entry in root.iter():
        meta = _named_child(entry, "MetaObject")
        if meta is None:
            continue
        guid_elem = _named_child(meta, "Guid")
        if guid_elem is None or not guid_elem.text:
            continue
        obj_elem = _named_child(entry, "Object")
        if obj_elem is None:
            continue

        guid = normalize_guid(guid_elem.text)
        implementation = _text_blob(_named_child(obj_elem, "Implementation"))
        declaration = _text_blob(_named_child(obj_elem, "Interface"))
        if declaration is None:
            declaration = _text_blob(_named_child(obj_elem, "Declaration"))
        result[guid] = {
            "declaration": declaration,
            "implementation": implementation,
        }
    return result


def _text_create_entries(root):
    result = []
    for elem in root.iter():
        if _local_name(elem.tag) != "CreateTextObject":
            continue
        declaration = None
        implementation = None
        for child in list(elem):
            child_name = _local_name(child.tag)
            if child_name == "Declaration":
                declaration = child.text or ""
            elif child_name == "Implementation":
                implementation = child.text or ""
        result.append(
            {
                "path": elem.attrib.get("Path", ""),
                "name": elem.attrib.get("Name", ""),
                "kind": elem.attrib.get("Kind", ""),
                "type_guid": elem.attrib.get("TypeGuid", ""),
                "parent_name": elem.attrib.get("ParentName", ""),
                "declaration": declaration,
                "implementation": implementation,
            }
        )
    return result


def _native_create_entries(root):
    result = []
    for elem in root.iter():
        if _local_name(elem.tag) != "CreateNativeObject":
            continue
        native_xml = None
        for child in list(elem):
            if _local_name(child.tag) == "NativeXml":
                native_xml = child.text or ""
                break
        result.append(
            {
                "path": elem.attrib.get("Path", ""),
                "name": elem.attrib.get("Name", ""),
                "type_guid": elem.attrib.get("TypeGuid", ""),
                "native_xml": native_xml,
            }
        )
    return result


def _bool_text(value):
    return str(value or "").strip().lower() == "true"


def _patch_build_attrs_by_guid(root):
    result = {}
    xml_to_attr = {
        "ExcludeFromBuild": "exclude_from_build",
        "LinkAlways": "link_always",
        "External": "external_implementation",
        "EnableSystemCall": "enable_system_call",
    }
    for entry in root.iter():
        meta = _named_child(entry, "MetaObject")
        if meta is None:
            continue
        guid_elem = _named_child(meta, "Guid")
        if guid_elem is None or not guid_elem.text:
            continue

        attrs = {}
        for xml_name, attr_name in xml_to_attr.items():
            elem = _named_descendant(meta, xml_name)
            if elem is not None and elem.text is not None:
                attrs[attr_name] = _bool_text(elem.text)

        if attrs:
            result[normalize_guid(guid_elem.text)] = attrs
    return result


def _entry_guid(entry):
    meta = _named_child(entry, "MetaObject")
    if meta is None:
        return ""
    guid_elem = _named_child(meta, "Guid")
    if guid_elem is None or not guid_elem.text:
        return ""
    return normalize_guid(guid_elem.text)


def _write_filtered_patch(source_root, target_guids):
    target = {}
    for guid in target_guids:
        target[normalize_guid(guid)] = True

    filtered_root = ET.Element(source_root.tag, source_root.attrib)

    for structured_view in list(source_root):
        filtered_view = copy.deepcopy(structured_view)
        entry_list = _named_descendant(filtered_view, "EntryList")
        if entry_list is None:
            continue

        kept = 0
        for entry in list(entry_list):
            if _entry_guid(entry) not in target:
                entry_list.remove(entry)
            else:
                kept += 1

        if kept:
            filtered_root.append(filtered_view)

    handle, filtered_path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    ET.ElementTree(filtered_root).write(
        filtered_path, encoding="utf-8", xml_declaration=True
    )
    return filtered_path


def _write_patch_without_text_creates(source_root):
    filtered_root = copy.deepcopy(source_root)
    for child in list(filtered_root):
        if _local_name(child.tag) == "CreateTextObjects":
            filtered_root.remove(child)
    handle, filtered_path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    ET.ElementTree(filtered_root).write(
        filtered_path, encoding="utf-8", xml_declaration=True
    )
    return filtered_path


def _build_guid_map(project):
    guid_map = {}
    try:
        objects = project.get_children(recursive=True)
    except Exception:
        return guid_map

    for obj in objects:
        try:
            guid = normalize_guid(obj.guid)
            if guid:
                guid_map[guid] = obj
        except Exception:
            pass
    return guid_map


def _children_of(obj):
    try:
        return obj.get_children()
    except Exception:
        return []


def _find_child_transparent(parent, name):
    name_lower = str(name or "").lower()
    if not name_lower:
        return None
    for child in _children_of(parent):
        if object_name(child).lower() == name_lower:
            return child
    for child in _children_of(parent):
        if object_name(child).lower() == "plc logic":
            for grandchild in _children_of(child):
                if object_name(grandchild).lower() == name_lower:
                    return grandchild
    return None


def _create_folder(parent, name):
    if hasattr(parent, "create_folder"):
        return parent.create_folder(name)
    folder_guid = "{738bea1e-99bb-4f04-90bb-a7a567e74e3a}"
    if hasattr(parent, "create_child"):
        return parent.create_child(name, _to_system_guid(folder_guid))
    return None


def _ensure_container_path_with_chain(project, rel_path):
    path = str(rel_path or "").replace("\\", "/")
    if "/" in path:
        path = path.rsplit("/", 1)[0]
    else:
        path = ""
    if not path or path == ".":
        return project, [project]

    current = project
    chain = [project]
    for part in path.split("/"):
        if not part or part.startswith("."):
            continue
        found = _find_child_transparent(current, part)
        if found is None:
            try:
                found = _create_folder(current, part)
            except Exception as e:
                print("Failed to create folder '{0}': {1}".format(part, e))
                found = None
            if found is None:
                found = _find_child_transparent(current, part)
        if found is None:
            return None, chain
        current = found
        chain.append(current)
    return current, chain


def _find_pou_type_enum():
    candidates = []
    try:
        candidates.append(PouType)
    except Exception:
        pass
    try:
        import __main__

        if hasattr(__main__, "PouType"):
            candidates.append(__main__.PouType)
    except Exception:
        pass
    try:
        from ScriptEngine import PouType as script_engine_pou_type

        candidates.append(script_engine_pou_type)
    except Exception:
        pass
    return candidates[0] if candidates else None


def _pou_type_name(declaration):
    text = str(declaration or "").lstrip().upper()
    if text.startswith("FUNCTION_BLOCK"):
        return "FunctionBlock"
    if text.startswith("FUNCTION"):
        return "Function"
    return "Program"


# Matches the return type in a 'FUNCTION <name> : <TYPE>' header line.
# <TYPE> is captured greedily so it covers STRING(80), qualified names
# (NS.TYPE), and arrays (ARRAY[..] OF X); trailing comments are stripped
# separately.  FUNCTION_BLOCK headers do not match (no ' : ' after name).
_FUNCTION_RETURN_RE = re.compile(
    r"^\s*FUNCTION\s+\w+\s*:\s*(.+?)\s*$", re.IGNORECASE
)


def _pou_return_type(declaration):
    """Extract the return type from a FUNCTION declaration header.

    Returns the type string (e.g. 'BOOL', 'STRING(80)', 'My.UserType') or
    None when the declaration has no scalar return type (a FUNCTION without
    a return type, or a non-FUNCTION POU).
    """
    text = str(declaration or "")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip leading pragmas / attributes / comments before the header.
        if line.startswith("{") or line.startswith("//") or line.startswith("(*"):
            continue
        match = _FUNCTION_RETURN_RE.match(line)
        if match is None:
            # First meaningful line is the header; if it has no ' : <type>'
            # (plain FUNCTION, FUNCTION_BLOCK, PROGRAM) there is no return type.
            return None
        return_type = match.group(1)
        # Drop any trailing line comment that follows the type.
        for marker in ("//", "(*"):
            idx = return_type.find(marker)
            if idx != -1:
                return_type = return_type[:idx]
        return_type = return_type.strip()
        return return_type or None
    return None


def _call_create_pou(container, name, pou_type, return_type=None):
    """Call container.create_pou, passing return_type only when given.

    The CODESYS signature is create_pou(name, type, return_type, ...); the
    parameter is required for FUNCTION POUs and rejected/ignored otherwise.
    Tries positional first, then keyword, for cross-version compatibility.
    """
    if return_type is None:
        return container.create_pou(name, pou_type)
    try:
        return container.create_pou(name, pou_type, return_type)
    except TypeError:
        return container.create_pou(name, pou_type, return_type=return_type)


def _create_pou(container, name, declaration):
    if not hasattr(container, "create_pou"):
        return None
    pou_type_enum = _find_pou_type_enum()
    if pou_type_enum is None:
        return None
    pou_type_name = _pou_type_name(declaration)
    pou_type = getattr(pou_type_enum, pou_type_name, None)
    if pou_type is None and pou_type_name == "FunctionBlock":
        pou_type = getattr(pou_type_enum, "Function_Block", None)
    if pou_type is None:
        pou_type = getattr(pou_type_enum, "Program", None)
    if pou_type is None:
        return None
    if pou_type_name == "Function":
        return_type = _pou_return_type(declaration)
        if not return_type:
            raise Exception(
                "Cannot create FUNCTION '{0}': no return type found in its "
                "declaration. Expected a header line 'FUNCTION {0} : <TYPE>'.".format(
                    name
                )
            )
        return _call_create_pou(container, name, pou_type, return_type)
    return _call_create_pou(container, name, pou_type)


# Multiple GUID candidates per kind, tried in order.
# Different CODESYS versions may use different type GUIDs for the same
# logical object type.  The first GUID that successfully creates an object
# wins.  A patch may provide an explicit TypeGuid (preferred), followed by
# built-in fallback candidates below.
KIND_TYPE_GUIDS = {
    "persistent_gvl": [
        "{3183921b-cc91-4712-9781-c3b6555122b5}",
        "{261bd6e6-249c-4232-bb6f-84c2fbeef430}",
    ],
    "task_local_gvl": [
        "{c2cda7a9-0ba4-4146-b563-22a42fa0eb72}",
    ],
}


def _find_create_container(container, create_method_name):
    """Walk up the parent chain to find a container that has the given create_* method."""
    visited = set()
    current = container
    while current is not None:
        if hasattr(current, create_method_name):
            return current
        obj_id = id(current)
        if obj_id in visited:
            break
        visited.add(obj_id)
        try:
            current = current.parent
        except Exception:
            break
    return None


def _create_container_candidates(container, container_chain=None, method_name=None):
    """Return likely create targets, deepest path container first.

    CODESYS IronPython objects may not report scripting methods reliably via
    hasattr/getattr.  Callers should still attempt the method and catch errors.
    """
    result = []
    seen = set()

    def add(candidate):
        if candidate is None:
            return
        obj_id = id(candidate)
        if obj_id in seen:
            return
        seen.add(obj_id)
        result.append(candidate)

    for candidate in reversed(list(container_chain or [])):
        add(candidate)

    current = container
    while current is not None:
        add(current)
        try:
            current = current.parent
        except Exception:
            break

    if method_name:
        target = _find_create_container(container, method_name)
        add(target)

    return result


def _to_system_guid(guid_string):
    """Convert a GUID string to System.Guid for CODESYS IronPython compatibility.

    In IronPython, create_child(name, type_guid) expects a System.Guid object
    rather than a plain Python string.  This helper tries the conversion and
    falls back to the raw string if System is unavailable (e.g. CPython).
    """
    try:
        import System
    except ImportError:
        return guid_string
    try:
        return System.Guid(guid_string.strip("{}"))
    except Exception:
        # System.Guid might reject the format; fall back to raw string.
        return guid_string


def _create_child_with_guid(target, name, guid_candidates):
    """Try create_child(name, type_guid) with each GUID candidate.

    The CODESYS IronPython API requires System.Guid for the type_guid
    parameter.  This helper attempts the call with each GUID (converting
    to System.Guid when necessary) and returns the first successful result.
    """
    if not isinstance(guid_candidates, (list, tuple)):
        guid_candidates = [guid_candidates]
    for guid_string in guid_candidates:
        guid_value = _to_system_guid(guid_string)
        try:
            obj = target.create_child(name, guid_value)
            if obj is not None:
                return obj
        except Exception:
            pass
    return None


def _create_text_object(container, entry, container_chain=None):
    kind = str(entry.get("kind") or "").lower()
    name = entry.get("name") or ""
    declaration = entry.get("declaration")
    type_guid = entry.get("type_guid") or ""

    if kind == "pou":
        obj = _create_pou(container, name, declaration)
        if obj is not None:
            return obj
    if kind == "gvl":
        target = _find_create_container(container, "create_gvl")
        if target is not None:
            return target.create_gvl(name)
    if kind in ("persistent_gvl", "task_local_gvl"):
        # CODESYS Scripting API has no create_persistent / create_task_local_gvl method.
        # Use create_child(name, type_guid) with the appropriate type GUID,
        # walking up the parent chain to find a container that supports create_child.

        # Build candidate list: explicit TypeGuid first, then profile/create_type_guids,
        # then built-in fallbacks.
        candidates = []
        if type_guid:
            candidates.append(type_guid)
        for fallback in KIND_TYPE_GUIDS.get(kind) or []:
            if fallback not in candidates:
                candidates.append(fallback)

        for target in _create_container_candidates(
            container, container_chain, "create_child"
        ):
            obj = _create_child_with_guid(target, name, candidates)
            if obj is not None:
                return obj

        # Fallback for persistent_gvl: try known method name variants.
        if kind == "persistent_gvl":
            for method_name in (
                "create_persistentvars",
                "create_persistent",
                "create_persistent_variable_list",
            ):
                for target in _create_container_candidates(
                    container, container_chain, method_name
                ):
                    try:
                        method = getattr(target, method_name)
                        obj = method(name)
                        if obj is not None:
                            return obj
                    except Exception:
                        pass

    if kind == "dut":
        target = _find_create_container(container, "create_dut")
        if target is not None:
            return target.create_dut(name)
    if kind == "method" and hasattr(container, "create_method"):
        return container.create_method(name)
    if kind == "action" and hasattr(container, "create_action"):
        return container.create_action(name)
    if kind == "property" and hasattr(container, "create_property"):
        return container.create_property(name)
    raise Exception("Unsupported text object creation kind or API: {0}".format(kind))


def _apply_text_create(project, entry, created_by_name):
    container, container_chain = _ensure_container_path_with_chain(
        project, entry.get("path")
    )
    if container is None:
        raise Exception("Could not resolve container for {0}".format(entry.get("path")))

    parent_name = entry.get("parent_name")
    if parent_name:
        parent = created_by_name.get(str(parent_name).lower())
        if parent is None:
            parent = _find_child_transparent(container, parent_name)
        if parent is None:
            raise Exception(
                "Could not resolve parent POU '{0}' for {1}".format(
                    parent_name, entry.get("path")
                )
            )
        container = parent

    existing = _find_child_transparent(container, entry.get("name"))
    if existing is not None:
        obj = existing
    else:
        obj = _create_text_object(
            container,
            entry,
            container_chain=container_chain,
        )
    if obj is None:
        raise Exception(
            "CODESYS did not return created object for {0}".format(entry.get("path"))
        )

    _apply_textual_patch(obj, entry)
    created_by_name[object_name(obj).lower()] = obj
    print("Created textual object from: " + str(entry.get("path")))
    return True


def _apply_text_creates(project, text_creates, created_by_name, result):
    for entry in text_creates:
        try:
            _apply_text_create(project, entry, created_by_name)
            result.add_created(entry.get("path"))
        except Exception as error:
            print(
                "Error creating textual object {0}: {1}".format(
                    entry.get("path"), error
                )
            )
            return result.fail(error)
    return None


def _native_create_wrapper_guid(container):
    """Best-effort '{guid}' for the StructuredView, mirroring the working MODIFY
    path. Decorative for a create (placement comes from calling import_native on
    the container + the entry's embedded ParentGuid); included for fidelity."""
    try:
        guid = getattr(container, "guid", None)
    except Exception:
        guid = None
    if not guid:
        return ""
    text = normalize_guid(str(guid))
    if not text:
        return ""
    return ' Guid="{{{0}}}"'.format(text)


def _wrap_native_object_xml(native_xml, container):
    """Wrap a bare <Single Type="{6198ad31-...}"> object export in the batch
    envelope CODESYS export_native produces / import_native consumes:
    <Project><StructuredView><Single Type="{3daac5e4-...}"><Null Name="Profile"/>
    <List2 Name="EntryList">{entry}</List2></Single></StructuredView></Project>.

    A bare <Single> is the single-object native form; import_native silently
    no-ops on it, so the object never appears. The MODIFY path always feeds this
    envelope (see _patch_builder.build_patch / _write_filtered_patch)."""
    text = native_xml or ""
    stripped = text.lstrip()
    if stripped.startswith("<?xml"):
        end = stripped.find("?>")
        if end != -1:
            text = stripped[end + 2:].lstrip()
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<Project>\n"
        "<StructuredView{0}>\n".format(_native_create_wrapper_guid(container))
        + "<Single xml:space=\"preserve\" "
        "Type=\"{3daac5e4-660e-42e4-9cea-3711b98bfb63}\" Method=\"IArchivable\">\n"
        "<Null Name=\"Profile\" />\n"
        "<List2 Name=\"EntryList\">\n"
        + text
        + "\n</List2>\n</Single>\n</StructuredView>\n</Project>\n"
    )


def _apply_native_create(project, entry):
    container, _chain = _ensure_container_path_with_chain(
        project, entry.get("path")
    )
    if container is None:
        raise Exception("Could not resolve container for {0}".format(entry.get("path")))

    name = entry.get("name")
    existing = _find_child_transparent(container, name)
    if existing is not None:
        print("Native object already exists, skipping: " + str(entry.get("path")))
        return False

    wrapped = _wrap_native_object_xml(entry.get("native_xml"), container)

    temp_path = None
    try:
        handle, temp_path = tempfile.mkstemp(suffix=".xml")
        os.close(handle)
        with codecs.open(temp_path, "w", "utf-8") as f:
            f.write(wrapped)
        container.import_native(temp_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    # import_native silently no-ops on a payload it cannot place, so verify the
    # object actually appeared and fail loudly otherwise -- the message is
    # surfaced via apply_patch -> log_error into sync_debug.log.
    created = _find_child_transparent(container, name)
    if created is None:
        raise Exception(
            "import_native did not create '{0}' under {1} "
            "(CODESYS rejected the native payload)".format(name, entry.get("path"))
        )
    print("Created native object from: " + str(entry.get("path")))
    return True


def _apply_native_creates(project, native_creates, result):
    for entry in native_creates:
        try:
            _apply_native_create(project, entry)
            result.add_created(entry.get("path"))
        except Exception as error:
            print(
                "Error creating native object {0}: {1}".format(
                    entry.get("path"), error
                )
            )
            return result.fail(error)
    return None


def _replace_text_document(doc, value):
    if doc.text == value:
        return False
    try:
        doc.text = value
    except Exception:
        doc.replace(value)
    return True


def _text_document(obj, attr_name):
    if obj is None or not hasattr(obj, attr_name):
        return None
    return getattr(obj, attr_name)


def _apply_textual_patch(obj, texts):
    updated = False
    declaration = texts.get("declaration")
    implementation = texts.get("implementation")

    declaration_doc = _text_document(obj, "textual_declaration")
    if declaration is not None and declaration_doc is not None:
        updated = _replace_text_document(declaration_doc, declaration) or updated

    implementation_doc = _text_document(obj, "textual_implementation")
    if implementation is not None and implementation_doc is not None:
        updated = _replace_text_document(implementation_doc, implementation) or updated

    return updated


def _set_bool_property(target, prop_name, value):
    if target is None or not hasattr(target, prop_name):
        return None
    current_value = getattr(target, prop_name)
    if bool(current_value) == bool(value):
        return False
    setattr(target, prop_name, bool(value))
    return True


def _apply_build_attrs_patch(obj, attrs):
    updated = False
    for prop_name, value in attrs.items():
        result = None
        try:
            build_props = getattr(obj, "build_properties", None)
            valid_check = prop_name + "_is_valid"
            if build_props is not None and hasattr(build_props, valid_check):
                if not getattr(build_props, valid_check):
                    result = False
            if result is None:
                result = _set_bool_property(build_props, prop_name, value)
            if result is None:
                result = _set_bool_property(obj, prop_name, value)
        except Exception as e:
            print(
                "Warning: could not apply build property {0}: {1}".format(prop_name, e)
            )
            result = False

        if result is True:
            updated = True
    return updated


def _can_apply_textual_patch(obj, texts):
    declaration = texts.get("declaration")
    implementation = texts.get("implementation")

    if (
        declaration is not None
        and _text_document(obj, "textual_declaration")
        is not None
    ):
        return True
    if (
        implementation is not None
        and _text_document(obj, "textual_implementation")
        is not None
    ):
        return True
    return False


def _apply_native_patch(project, obj, patch_path):
    parent = None
    try:
        parent = obj.parent
    except Exception:
        parent = None

    if parent is not None and hasattr(parent, "import_native"):
        parent.import_native(patch_path)
    else:
        project.import_native(patch_path)


def _apply_native_patches(project, guid_map, patch_root, native_guids, result):
    for guid in native_guids:
        obj = guid_map.get(guid)
        if obj is None:
            continue
        filtered_patch_path = None
        try:
            filtered_patch_path = _write_filtered_patch(patch_root, [guid])
            print("Applying native patch for non-textual object: " + str(guid))
            _apply_native_patch(project, obj, filtered_patch_path)
            result.add_applied(guid, "native")
        except Exception as error:
            result.fail(error, guid)
            raise
        finally:
            if filtered_patch_path and os.path.exists(filtered_patch_path):
                try:
                    os.remove(filtered_patch_path)
                except Exception:
                    pass


def apply_patch(system, project, patch_path):
    """
    Applies the pre-computed IMPORT.xml to the current project.
    """
    result = ApplyPatchResult()
    print("Applying patch from: " + patch_path)
    if not os.path.exists(patch_path):
        print("Patch file not found.")
        return result.fail("Patch file not found.")

    try:
        patch_data = _parse_patch(patch_path)
        patch_root = patch_data["root"]
        patch_guids = patch_data["guids"]
        patch_texts = patch_data["texts"]
        patch_build_attrs = patch_data["build_attrs"]
        text_creates = patch_data["text_creates"]
        native_creates = patch_data["native_creates"]
        guid_map = _build_guid_map(project)
        existing_objects = [guid_map[guid] for guid in patch_guids if guid in guid_map]
        created_by_name = {}

        if existing_objects:
            textual_handled = []
            for guid in patch_guids:
                obj = guid_map.get(guid)
                texts = patch_texts.get(guid)
                if obj is None or texts is None:
                    continue
                if not _can_apply_textual_patch(obj, texts):
                    continue
                try:
                    text_updated = _apply_textual_patch(obj, texts)
                    attrs_updated = _apply_build_attrs_patch(
                        obj, patch_build_attrs.get(guid, {})
                    )
                except Exception as error:
                    print(
                        "Error applying textual patch for object {0}: {1}".format(
                            guid, error
                        )
                    )
                    return result.fail(error, guid)
                if text_updated or attrs_updated:
                    print("Applied textual patch for object: " + str(guid))
                else:
                    print("Textual patch already current for object: " + str(guid))
                textual_handled.append(guid)
                result.add_applied(guid, "textual")

            if len(textual_handled) == len(existing_objects):
                create_error = _apply_text_creates(
                    project, text_creates, created_by_name, result
                )
                if create_error is not None:
                    return create_error
                native_error = _apply_native_creates(project, native_creates, result)
                if native_error is not None:
                    return native_error
                return result

            native_guids = []
            for guid in patch_guids:
                if guid in guid_map and guid not in textual_handled:
                    native_guids.append(guid)

            if native_guids:
                _apply_native_patches(
                    project, guid_map, patch_root, native_guids, result
                )
            create_error = _apply_text_creates(
                project, text_creates, created_by_name, result
            )
            if create_error is not None:
                return create_error
            native_error = _apply_native_creates(project, native_creates, result)
            if native_error is not None:
                return native_error
            return result

        if patch_guids:
            native_patch_path = None
            try:
                native_patch_path = _write_patch_without_text_creates(patch_root)
                project.import_native(native_patch_path)
                for guid in patch_guids:
                    result.add_applied(guid, "native")
            finally:
                if native_patch_path and os.path.exists(native_patch_path):
                    try:
                        os.remove(native_patch_path)
                    except Exception:
                        pass
        create_error = _apply_text_creates(
            project, text_creates, created_by_name, result
        )
        if create_error is not None:
            return create_error
        native_error = _apply_native_creates(project, native_creates, result)
        if native_error is not None:
            return native_error
        return result
    except Exception as e:
        print("Error applying patch: " + str(e))
        return result.fail(e)
