"""CTS0067 - enumeration declarations should use the strict attribute."""

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import declaration

def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    info = decl.dut_info(unit)
    if not info or info.get("kind") != "enum" or info.get("strict"):
        return
    offset = declaration(unit).at(0)
    yield finding_in(message=f"enumeration '{info['name']}' is not declared with {{attribute 'strict'}}",
                     unit=unit, offset=offset, end_offset=offset + len(info["name"]),
                     anchor=info["name"], context=info["name"])

RULE = RuleSpec(id="CTS0067", title="Non-strict enumeration", severity="suspicious",
                scope=Scope.UNIT, requires={Capability.DECLARATIONS}, kinds="TYPE",
                summary="Enumerations should use the strict attribute.", topic="Correctness", check=check)
