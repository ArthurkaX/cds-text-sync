"""
symbols.py - Project-wide symbol table (PROJECT_SYMBOLS capability).

Built purely from the units of a ProjectSnapshot: POU / function / method
names, DUT type names and GVL members. Keys are lowercased because IEC
61131-3 identifiers are case-insensitive.
"""

from __future__ import annotations

from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.decl import all_members


class Symbol:
    def __init__(self, name, kind, owner=None, path=None):
        self.name = name
        self.kind = kind
        self.owner = owner
        self.path = path

    def to_dict(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "owner": self.owner,
            "path": self.path,
        }

    def __repr__(self):
        return f"<Symbol {self.name} {self.kind}>"


class ProjectSymbols:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self._table = {}

        for unit in snapshot.units:
            if unit.kind == K.UNKNOWN:
                continue
            # Object names: POUs, functions, methods, actions, DUTs, GVLs.
            self._add(unit.qualified_name, unit.kind, unit.owner_name, unit.source_path)
            # GVL members (bare and GVL-qualified).
            if unit.kind in (K.GVL, K.GVL_PERSISTENT):
                for member in all_members(unit):
                    self._add(
                        member["name"], "member", unit.qualified_name, unit.source_path
                    )
                    self._add(
                        f"{unit.qualified_name}.{member['name']}",
                        "member",
                        unit.qualified_name,
                        unit.source_path,
                    )
            # DUT type names are unit names already; FB instance-visible
            # fields are not in the table (scoping is a rule concern).

    def _add(self, name, kind, owner, path):
        key = (name or "").strip().lower()
        if not key:
            return
        existing = self._table.get(key)
        if existing is None:
            self._table[key] = Symbol(name, kind, owner, path)

    def lookup(self, name):
        return self._table.get((name or "").strip().lower())

    def has(self, name):
        return (name or "").strip().lower() in self._table

    def __contains__(self, name):
        return self.has(name)

    def names(self):
        return sorted(self._table)
