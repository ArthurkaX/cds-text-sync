"""
config.py - Loading ``cts-analyze.toml``.

Configuration is data (rules stay code). The config file may:

* set the quality policy (``fail_on``, ``incomplete``);
* pick the git base for history rules;
* override per-rule severity and enabled state;
* tune per-rule options (``[rules.<id>] options.<name> = ...``);
* scope rules to path globs (``[[rule_scope]]``).

TOML is parsed with ``tomllib`` (3.11+); on older Pythons a config file is
reported as unsupported instead of being silently ignored.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from cds_text_sync.analyze.model import is_valid_severity

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    tomllib = None

DEFAULT_FAIL_ON = "suspicious"
DEFAULT_INCOMPLETE = "warn"

# Rules that are available in the catalog but are intentionally opt-in for a
# normal project-wide run. Keep this list small and explain each entry in the
# rule documentation: these checks are useful in selected projects, but their
# signal depends on a project convention or a platform limitation.
DEFAULT_DISABLED_RULES = frozenset({"CTS0034"})

VALID_INCOMPLETE = ("warn", "error", "ignore")


class ConfigError(Exception):
    """The config file is malformed or contradictory."""


def set_rule_enabled(config_path, rule_id, enabled):
    """Update one ``[rules.<id>] enabled`` value and validate the result.

    The small text edit intentionally preserves comments and unrelated TOML
    content.  The resulting file is parsed through :func:`load_config` before
    it is committed, so the UI cannot leave a syntactically invalid config.
    """
    rule_id = str(rule_id or "").strip().upper()
    if not re.fullmatch(r"CTS\d{4}", rule_id):
        raise ConfigError(f"invalid rule id: {rule_id!r}")
    path = Path(config_path)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    section = re.compile(
        rf"(?ms)^\[rules\.{re.escape(rule_id)}\]\s*$.*?(?=^\[|\Z)"
    )
    value = "true" if bool(enabled) else "false"
    block = f"[rules.{rule_id}]\nenabled = {value}\n"
    match = section.search(text)
    if match:
        current = match.group(0)
        if re.search(r"(?m)^enabled\s*=", current):
            current = re.sub(
                r"(?m)^enabled\s*=.*$", f"enabled = {value}", current, count=1
            )
        else:
            current = current.rstrip() + f"\nenabled = {value}\n"
        text = text[: match.start()] + current + text[match.end() :]
    else:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + block
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_bytes() if path.is_file() else None
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        load_config(str(path))
    except Exception:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
        raise


class RuleScope:
    def __init__(self, path_glob, enabled=True, exclude=None):
        self.path_glob = path_glob
        self.enabled = enabled
        self.exclude = frozenset(exclude or ())

    def __repr__(self):
        return (
            f"<RuleScope {self.path_glob} enabled={self.enabled} "
            f"exclude={sorted(self.exclude)}>"
        )


class ResolvedConfig:
    def __init__(self):
        self.fail_on = DEFAULT_FAIL_ON
        self.incomplete = DEFAULT_INCOMPLETE
        self.rule_overrides = {}  # rule_id -> {"enabled": bool, "severity": str, "options": {name: value}}
        self.scopes = []  # list[RuleScope]
        self.config_path = None

    # -- rule level --------------------------------------------------------

    def severity_for(self, rule_id, default):
        override = self.rule_overrides.get(rule_id, {})
        return override.get("severity") or default

    def enabled_for(self, rule_id, default=None):
        if default is None:
            default = str(rule_id).strip().upper() not in DEFAULT_DISABLED_RULES
        override = self.rule_overrides.get(rule_id, {})
        return override.get("enabled", default)

    def options_for(self, rule_id):
        """Raw configured options for *rule_id* (empty dict when unset).

        Values are unvalidated: unknown keys and type mismatches are surfaced
        per-run as ``rule-option`` Diagnostics, never a config-load error, so
        a typo cannot stop the analyzer from starting.
        """
        return dict(self.rule_overrides.get(rule_id, {}).get("options", {}))

    # -- unit level --------------------------------------------------------

    def path_excluded(self, relpath):
        """True if every rule is disabled for *relpath*."""
        for scope in self.scopes:
            if not scope.enabled and _glob_match(scope.path_glob, relpath):
                return True
        return False

    def rules_excluded_for(self, relpath):
        excluded = set()
        for scope in self.scopes:
            if not _glob_match(scope.path_glob, relpath):
                continue
            excluded |= scope.exclude
        return excluded


def _glob_match(pattern, relpath):
    """Glob match with ``**`` (any depth), ``*`` (within a segment)."""
    regex = _glob_to_regex(pattern)
    return re.match(regex, relpath) is not None


@lru_cache(maxsize=256)
def _glob_to_regex(pattern):
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c in ".[](){}^$+|\\":
            out.append("\\" + c)
        else:
            out.append(c)
        i += 1
    return "^" + "".join(out) + "$"


def load_config(config_path):
    """Load and validate a config file. Returns a ResolvedConfig.

    Raises ConfigError on malformed content.
    """
    config = ResolvedConfig()
    if not config_path or not os.path.isfile(config_path):
        return config
    if tomllib is None:
        raise ConfigError(
            "cts-analyze.toml requires Python 3.11+ (tomllib). "
            "Remove the config file or upgrade Python."
        )
    with open(config_path, "rb") as fh:
        try:
            data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"cannot parse {config_path}: {exc}") from exc

    config.config_path = config_path
    analyze = data.get("analyze", {}) or {}
    if not isinstance(analyze, dict):
        raise ConfigError("[analyze] must be a table")

    fail_on = str(analyze.get("fail_on", DEFAULT_FAIL_ON)).strip().lower()
    if not is_valid_severity(fail_on):
        raise ConfigError(
            f"[analyze] fail_on must be one of danger|suspicious|style, got {fail_on!r}"
        )
    config.fail_on = fail_on

    incomplete = str(analyze.get("incomplete", DEFAULT_INCOMPLETE)).strip().lower()
    if incomplete not in VALID_INCOMPLETE:
        raise ConfigError(
            f"[analyze] incomplete must be one of warn|error|ignore, got {incomplete!r}"
        )
    config.incomplete = incomplete

    rules = data.get("rules", {}) or {}
    if not isinstance(rules, dict):
        raise ConfigError("[rules] must be a table")
    for rule_id, override in rules.items():
        rule_id = str(rule_id).strip().upper()
        if not re.fullmatch(r"CTS\d{4}", rule_id):
            raise ConfigError(f"[rules.{rule_id}] has an invalid rule id")
        if not isinstance(override, dict):
            raise ConfigError(f"[rules.{rule_id}] must be a table")
        entry = {}
        if "enabled" in override:
            entry["enabled"] = bool(override["enabled"])
        if "severity" in override:
            sev = str(override["severity"]).strip().lower()
            if not is_valid_severity(sev):
                raise ConfigError(
                    f"[rules.{rule_id}] severity must be one of "
                    f"danger|suspicious|style, got {sev!r}"
                )
            entry["severity"] = sev
        if "options" in override:
            opts = override["options"]
            if not isinstance(opts, dict):
                raise ConfigError(f"[rules.{rule_id}] options must be a table")
            # Values are stored raw; per-rule validation/coercion happens in
            # the runner so a typo here never prevents the analyzer starting.
            entry["options"] = dict(opts)
        config.rule_overrides[rule_id] = entry

    # Validate config IDs against the built-in catalog so typos do not become
    # silent no-ops. The import is lazy to keep registry independent of config.
    if config.rule_overrides:
        from cds_text_sync.analyze.registry import load_builtin_rules

        unknown = sorted(set(config.rule_overrides) - set(load_builtin_rules()))
        if unknown:
            raise ConfigError(
                "unknown rule id(s) in [rules]: " + ", ".join(unknown)
            )

    for idx, raw in enumerate(data.get("rule_scope", []) or []):
        if not isinstance(raw, dict) or not raw.get("path"):
            raise ConfigError(f"rule_scope[{idx}] needs a 'path' glob")
        scope = RuleScope(
            path_glob=str(raw["path"]),
            enabled=bool(raw.get("enabled", True)),
            exclude=[
                str(rule_id).strip().upper()
                for rule_id in (raw.get("exclude", []) or [])
            ],
        )
        config.scopes.append(scope)

    return config
