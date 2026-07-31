# -*- coding: utf-8 -*-
"""
builder_frame.py - Frame capture / tokenization for the visu builder.

The capture-frame path (spec 1/2): read an existing VisuFbFrame element,
extract its interface params, and tokenize its XML fragment into a reusable
golden template (@@X@@/@@Y@@/.../@@PARAM_MEMBERS@@ placeholders) plus a catalog
dict. This is the inverse of element rendering and shares none of its state,
so it lives in its own module; builder.py re-exports the names as a facade.

Indentation here is tabs, preserved verbatim from the original builder.py.
"""

from __future__ import print_function

import re

from .xml_ns import find_named, strip_ns


# Member IDs whose <Value> text becomes a template placeholder.
_FRAME_TOKEN_GEOMETRY = {
	1649127785: "@@X@@",
	357335551: "@@Y@@",
	2422045748: "@@WIDTH@@",
	2134141914: "@@HEIGHT@@",
	550940142: "@@CENTER_X@@",
	1473355128: "@@CENTER_Y@@",
}


def _member_map(element):
	"""Map member id -> {value, kind, color, canonical_name} for one element.

	Duplicated from screen_xml._member_map for convenience (avoids extra
	cross-module coupling in the frame-capture code path).
	"""
	out = {}
	member_container = find_named(element, "Single", "VisualElemMemberList")
	mlist = (
		find_named(member_container, "List", "VisualElemMemberList")
		if member_container is not None
		else None
	)
	if mlist is None:
		return out
	for member in list(mlist):
		if strip_ns(member.tag) != "Single":
			continue
		idc = find_named(member, "Single", "Id")
		if idc is None or not idc.text:
			continue
		mid = int(idc.text.strip())
		scalar = find_named(member, "Single", "Value")
		if scalar is not None:
			out[mid] = {"kind": "scalar", "value": (scalar.text or "")}
			continue
		listval = find_named(member, "List", "Value")
		if listval is not None:
			inner = list(listval)
			if inner and find_named(inner[0], "Single", "Color") is not None:
				color_el = find_named(inner[0], "Single", "Color")
				cn_el = find_named(inner[0], "Single", "CanonicalName")
				out[mid] = {
					"kind": "color",
					"color": (color_el.text or "").strip()
					if color_el is not None
					else "",
					"canonical_name": (cn_el.text or "") if cn_el is not None else "",
				}
			else:
				out[mid] = {"kind": "list", "value": None}
	return out


def _extract_frame_params(element):
	"""Extract interface params from a VisuFbFrame *element*.

	Returns ``(params_list, visu_name)`` where each param dict has keys
	``name``, ``member_id``, ``iec_type``, ``default``.
	Uses the same traversal as ``svg_export._render_frame``.
	"""
	# Build parent map for navigating descendants.
	parents = {c: p for p in element.iter() for c in p}

	# First non-null VisNodeRefs33 -> visu name + its holder element.
	visu_name = ""
	holder = None
	for child in element.iter():
		if strip_ns(child.tag) == "Single" and child.attrib.get("Name") == "VisNodeRefs33":
			text = (child.text or "").strip()
			if text:
				visu_name = text
				holder = parents.get(child)
				break

	if holder is None:
		return [], ""

	# Read live member values (to extract defaults).
	member_values = _member_map(element)

	params = []
	for direct_child in list(holder):
		if strip_ns(direct_child.tag) == "List" and direct_child.attrib.get("Name") == "TypeNodeChildren":
			for param_node in list(direct_child):
				if strip_ns(param_node.tag) != "Single":
					continue
				pname_el = find_named(param_node, "Single", "TypeNodeName")
				pid_el = find_named(param_node, "Single", "TypeNodeIdLong")
				if pname_el is None or pid_el is None:
					continue
				pname = (pname_el.text or "").strip()
				if not pname:
					continue
				try:
					pid = int(pid_el.text.strip())
				except (ValueError, TypeError):
					continue

				iec_type = ""
				type_node = find_named(param_node, "Single", "TypeNodeType")
				if type_node is not None:
					qn = find_named(type_node, "Single", "QualifiedName")
					if qn is not None and qn.text:
						iec_type = qn.text.strip()

				default = ""
				m = member_values.get(pid, {})
				if m.get("value") is not None:
					default = m["value"]

				params.append({
					"name": pname,
					"member_id": pid,
					"iec_type": iec_type,
					"default": default,
				})
			break
	return params, visu_name


def _tokenize_frame(fragment_text, param_ids):
	"""Tokenize a VisuFbFrame XML *fragment_text* into a golden template.

	*param_ids* is a set of member IDs whose value members should be
	removed from the top VisualElemMemberList. Returns the template text
	with ``@@X@@``, ``@@Y@@``, ``@@WIDTH@@``, ``@@HEIGHT@@``,
	``@@CENTER_X@@``, ``@@CENTER_Y@@``, ``@@IDENTIFIER@@``,
	``@@VISUAL_ELEMENT_ID@@``, and ``@@PARAM_MEMBERS@@`` placeholders.
	"""
	text = fragment_text

	# 1. Tokenize geometry member values.
	for mid, placeholder in _FRAME_TOKEN_GEOMETRY.items():
		id_marker = '<Single Name="Id" Type="long">' + str(mid) + '</Single>'
		idx = text.find(id_marker)
		if idx < 0:
			continue
		val_tag = '<Single Name="Value"'
		val_idx = text.find(val_tag, idx)
		if val_idx < 0:
			continue
		tag_close = text.find('>', val_idx)
		if tag_close < 0:
			continue
		val_close = text.find('</Single>', tag_close)
		if val_close < 0:
			continue
		text = text[:tag_close + 1] + placeholder + text[val_close:]

	# 2. Tokenize GenElemInst_N identifier.
	text = re.sub(
		r'(VisualElementIdentifier" Type="string">)GenElemInst_\d+(</Single>)',
		r'\1@@IDENTIFIER@@\2',
		text,
	)

	# 3. Tokenize VisualElementId int value.
	text = re.sub(
		r'(VisualElementId" Type="int">)\d+(</Single>)',
		r'\1@@VISUAL_ELEMENT_ID@@\2',
		text,
	)

	# 4. Remove param value members from the top VisualElemMemberList and
	#    insert @@PARAM_MEMBERS@@ before its closing </List>.
	list_marker = '<List Name="VisualElemMemberList"'
	list_start = text.find(list_marker)
	if list_start < 0:
		return text

	# Find matching close (handle nested <List> depth).
	pos = text.find('>', list_start) + 1
	depth = 0
	close_pos = -1
	i = pos
	while i < len(text):
		next_open = text.find('<List', i)
		next_close = text.find('</List>', i)
		if next_close < 0:
			break
		if next_open >= 0 and next_open < next_close:
			tag_end = text.find('>', next_open)
			is_self_closing = tag_end >= 0 and text[tag_end - 1:tag_end + 1] == '/>'
			if not is_self_closing:
				depth += 1
			i = tag_end + 1 if tag_end >= 0 else next_open + 5
		else:
			if depth == 0:
				close_pos = next_close
				break
			depth -= 1
			i = next_close + 6

	if close_pos < 0:
		return text

	after_open = text.index('>', list_start) + 1
	list_content = text[after_open:close_pos]

	# Remove member blocks whose <Id> is in param_ids.
	def _drop_if_param(m):
		block = m.group(0)
		_idm = re.search(r'<Single Name="Id" Type="long">(\d+)</Single>', block)
		if _idm and int(_idm.group(1)) in param_ids:
			return ""
		return block

	member_re = re.compile(
		r'<Single Type="\{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02\}" Method="IArchivable">'
		r'.*?</Single>',
		re.DOTALL,
	)
	cleaned = member_re.sub(_drop_if_param, list_content)
	cleaned = cleaned.rstrip()
	indent_member = " " * 16
	indent_list = " " * 12
	new_content = cleaned + "\n" + indent_member + "@@PARAM_MEMBERS@@\n" + indent_list
	text = text[:after_open] + new_content + text[close_pos:]
	return text


def _build_frame_catalog(visu_name, params):
	"""Build a frame catalog dict for a captured golden template.

	Returns a dict suitable for writing as ``<visu_name>.json``.
	"""
	return {
		"type": "frame",
		"visualElementTypeName": "VisuFbFrame",
		"visu": visu_name,
		"golden_template": visu_name + ".xml.tmpl",
		"base_members": [],
		"params": [
			{
				"name": p["name"],
				"member_id": p["member_id"],
				"iec_type": p["iec_type"],
				"default": p["default"],
			}
			for p in params
		],
	}
