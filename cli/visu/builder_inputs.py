# -*- coding: utf-8 -*-
"""
builder_inputs.py - Input-action rendering for the visu builder.

Renders the input-action XML that a golden element template pulls in through its
placeholders:

  - @@PARAM_MEMBERS@@                  (VisuFbFrame param members)
  - @@CONFIGURED_COMPLEX_INPUTS@@      (tap / toggle / catalog-defined inputs)
  - @@VISUAL_ELEMENT_INPUT_ACTIONS@@   (per-event action dictionary)

These are leaf renderers: they depend only on the shared primitives in
_builder_base and never call back into element rendering, so builder.py can
import them without a cycle. builder.py re-exports the public names, so callers
(and tests) reach them via the builder facade as before.
"""

from __future__ import print_function

import json
import os

from ._builder_base import BuilderError, _MB, _MEMBER_TYPE, _esc

# Lazy-loaded input-action catalog (input_actions.json).
_INPUT_ACTIONS = None


def _render_frame_param_members(catalog, params):
    """Render ``@@PARAM_MEMBERS@@`` for VisuFbFrame elements.

    Each param from the catalog that has a non-empty resolved value becomes
    a member block in the VisualElemMemberList. Params whose resolved value
    is "" (or whose name is absent from *params* and whose default is "")
    are omitted -- matching CODESYS behaviour.
    """
    provided = params.get("params", {})
    members = []
    for param in catalog.get("params", []):
        name = param["name"]
        value = provided.get(name, param.get("default", ""))
        if value == "":
            continue
        mid = param["member_id"]
        members.append(
            '{mb}<Single Type="{mt}" Method="IArchivable">\n'
            '{mb} <Single Name="Id" Type="long">{mid}</Single>\n'
            '{mb} <Single Name="Value" Type="string">{val}</Single>\n'
            '{mb}</Single>'.format(
                mb=_MB,
                mt=_MEMBER_TYPE,
                mid=mid,
                val=_esc(value),
            )
        )
    return "\n".join(members)


def _render_configured_complex_inputs(params, tap_var, toggle_var):
    actions = list(params.get("configured_inputs", []))
    if tap_var:
        actions.append({"type": "tap", "values": {"variable": tap_var}})
    if toggle_var:
        actions.append(
            {
                "type": "toggle",
                "values": {
                    "variable": toggle_var,
                    "toggle_on": params.get("toggle_on", "False"),
                },
            }
        )
    if not actions:
        return (
            '              <Array Name="ConfiguredComplexInputs" '
            'Type="{1de566f6-72a7-494c-9353-9a418172c96e}" />'
        )
    rendered = []
    for item in actions:
        action = _configured_complex_input(item["type"])
        members = _render_complex_input_members(action, item.get("values", {}))
        rendered.append(_render_configured_complex_input(action, members))
    return (
        '              <Array Name="ConfiguredComplexInputs" Type="{1de566f6-72a7-494c-9353-9a418172c96e}">\n'
        + "".join(rendered)
        + "              </Array>"
    )


def _render_configured_complex_input(action, members):
    block = (
        '                <Single Type="{1de566f6-72a7-494c-9353-9a418172c96e}" Method="IArchivable">\n'
        '                  <Null Name="DescriptionTree" />\n'
        '                  <Single Name="VisualElemMemberList" Type="{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}" Method="IArchivable">\n'
        '                    <List Name="VisualElemMemberList" Type="{a4b83bea-3742-489c-9fe8-d96d68dba7ab}">\n'
        "{members}"
        "                    </List>\n"
        "                  </Single>\n"
        '                  <Single Name="SignatureName" Type="string">@@SIGNATURE@@</Single>\n'
        '                  <Single Name="Name" Type="string">@@NAME@@</Single>\n'
        '                  <Single Name="Description" Type="string">@@DESCRIPTION@@</Single>\n'
        "                </Single>\n"
    )
    block = block.replace("{members}", members)
    block = block.replace("@@SIGNATURE@@", _esc(action["signature_name"]))
    block = block.replace("@@NAME@@", _esc(action["name"]))
    block = block.replace("@@DESCRIPTION@@", _esc(action["description"]))
    return block


def _configured_complex_input(name):
    global _INPUT_ACTIONS
    if _INPUT_ACTIONS is None:
        path = os.path.join(os.path.dirname(__file__), "catalog", "input_actions.json")
        with open(path, "r") as f:
            _INPUT_ACTIONS = json.load(f)
    try:
        return _INPUT_ACTIONS["configured_complex_inputs"][name]
    except KeyError:
        raise BuilderError("Unknown configured complex input: {0}".format(name))


def _render_complex_input_members(action, values):
    rendered = []
    for member in action.get("members", []):
        value = values.get(member["name"], "")
        rendered.append(
            '                      <Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">\n'
            '                        <Single Name="Id" Type="long">@@MEMBER_ID@@</Single>\n'
            '                        <Single Name="Value" Type="@@KIND@@">@@VALUE@@</Single>\n'
            "                      </Single>\n".replace(
                "@@MEMBER_ID@@", str(int(member["member_id"]))
            )
            .replace("@@KIND@@", _esc(member.get("kind", "string")))
            .replace("@@VALUE@@", _esc(value))
        )
    return "".join(rendered)


def _visual_input_action(name):
    global _INPUT_ACTIONS
    if _INPUT_ACTIONS is None:
        _configured_complex_input("tap")
    try:
        return _INPUT_ACTIONS["visual_element_input_actions"][name]
    except KeyError:
        raise BuilderError("Unknown visual element input action: {0}".format(name))


def _render_visual_element_input_actions(actions):
    if not actions:
        return (
            '              <Dictionary Type="System.Collections.Hashtable" '
            'Name="VisualElementInputActions" />'
        )
    by_event = {}
    for action in actions:
        by_event.setdefault(action["event"], []).append(action)
    entries = []
    for event in sorted(by_event):
        entries.append(_render_input_action_entry(event, by_event[event]))
    return (
        '              <Dictionary Type="System.Collections.Hashtable" Name="VisualElementInputActions">\n'
        + "".join(entries)
        + "              </Dictionary>"
    )


def _render_input_action_entry(event, actions):
    cfg = _visual_input_action("array_type")
    rendered_actions = []
    for action in actions:
        spec = _visual_input_action(action["type"])
        rendered_actions.append(_render_input_action(spec, action.get("values", {})))
    block = (
        "                <Entry>\n"
        "                  <Key>\n"
        '                    <Single Type="string">@@EVENT@@</Single>\n'
        "                  </Key>\n"
        "                  <Value>\n"
        '                    <Array Type="@@ARRAY_TYPE@@">\n'
        "@@ACTIONS@@"
        "                    </Array>\n"
        "                  </Value>\n"
        "                </Entry>\n"
    )
    return (
        block.replace("@@EVENT@@", _esc(event))
        .replace("@@ARRAY_TYPE@@", _esc(cfg))
        .replace("@@ACTIONS@@", "".join(rendered_actions))
    )


def _render_input_action(spec, values):
    fields = []
    for field in spec.get("fields", []):
        kind = field["kind"]
        xml_name = field["xml_name"]
        if kind == "null":
            fields.append(
                ' <Null Name="{0}" />\n'.format(_esc(xml_name))
            )
            continue
        if kind == "dict":
            from_key = field.get("from")
            dict_values = values.get(from_key) if from_key else None
            if from_key and dict_values:
                lines = []
                lines.append(
                    ' <Dictionary Type="System.Collections.Hashtable" '
                    'Name="{0}">\n'.format(_esc(xml_name))
                )
                for key, val in dict_values.items():
                    lines.extend([
                        '  <Entry>\n',
                        '   <Key>\n',
                        '    <Single Type="string">{0}</Single>\n'.format(
                            _esc(key)),
                        '   </Key>\n',
                        '   <Value>\n',
                        '    <Single Type="string">{0}</Single>\n'.format(
                            _esc(val)),
                        '   </Value>\n',
                        '  </Entry>\n',
                    ])
                lines.append(' </Dictionary>\n')
                fields.append("".join(lines))
            else:
                fields.append(
                    ' <Dictionary Type="System.Collections.Hashtable" '
                    'Name="{0}" />\n'.format(
                        _esc(xml_name)
                    )
                )
            continue
        value = values.get(field.get("name"), field.get("default", ""))
        fields.append(
            '                        <Single Name="@@NAME@@" Type="@@TYPE@@">@@VALUE@@</Single>\n'.replace(
                "@@NAME@@", _esc(xml_name)
            )
            .replace("@@TYPE@@", _esc(kind))
            .replace("@@VALUE@@", _esc(value))
        )
    return (
        '                      <Single Type="@@TYPE@@" Method="IArchivable">\n'
        + "".join(fields)
        + "                      </Single>\n"
    ).replace("@@TYPE@@", _esc(spec["type"]))
