"""Coercion of loosely-typed values, shared by the host bridge and the engine.

The daemon receives parameters over JSON, the engine reads them back out of
snapshot files, and the Settings window reads them out of CODESYS project
properties.  All three end up asking "was this flag on?", and before this
module each answered with its own slightly different list of words — one
accepted "ok" where its sibling accepted "on", so the same snapshot field
meant different things depending on which code path read it.

IronPython 2.7 compatible: no annotations, no f-strings, no pathlib.
"""

TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


def as_bool(value, default=False):
    """Interpret *value* as a boolean flag, returning *default* if unknown.

    Real booleans pass through.  Everything else is trimmed and lowercased
    and matched against TRUE_VALUES / FALSE_VALUES; ``None`` and any
    unrecognised text (including empty) yield *default*, so callers keep
    control over what "not specified" means.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return default
