# Working on this repository

Code rules (Python and C#):

- Private by default: a Python helper starts with `_`, a C# member is `private`
  or `internal` unless another assembly needs it.
- Replacing an implementation deletes the old one in the same change; no second
  path kept "for compatibility" without a caller that needs it.
- No commented-out code, no unused parameters, no "kept for later" members.
- Dead code fails the checks: `tests/unit/test_dead_code.py` (vulture) for
  Python; the build (`products/codesys-agent/.editorconfig`) and
  `dotnet run -c Release --project products/codesys-agent/tools/DeadSymbols`
  for the agent. A name used only by reflection, by string or by a loader goes
  on their lists with the reason, not into a suppression on the spot.
