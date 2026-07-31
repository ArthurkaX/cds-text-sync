# -*- coding: utf-8 -*-
"""
test_setup_dryrun_guard.py — CTS_SETUP_DRYRUN has to mean what its name says.

setup.ps1 is the only thing in this repository that deletes a user's files. It
is delivered by `irm | iex`, so it cannot take a -WhatIf parameter; the
rehearsal switch is an environment variable instead, and the plan called for
running every migration branch under it before a release.

That switch used to guard only the migration moves. A run with it set still
deleted and replaced the body tree, downloaded, pip-installed and wrote the
ScriptDir stubs — so a "rehearsal" performed a real installation, and pointing
it at a working clone would have destroyed uncommitted work.

The guarantee is narrow and worth stating exactly: with the variable set,
nothing outside %TEMP% is created, moved or deleted. This test holds every
mutating cmdlet in the script to it, so the next edit cannot quietly reopen the
hole.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SETUP = Path(__file__).parent.parent.parent / "irm" / "setup.ps1"

# Cmdlets that touch the filesystem or the Python environment.
MUTATORS = re.compile(
    r"\b(Remove-Item|Move-Item|Copy-Item|New-Item|Set-Content|Out-File"
    r"|Expand-Archive|Install-CliCommand)\b"
    r"|\[System\.IO\.Directory\]::Delete"
    r"|pip[\"'\s,)]+.*\b(install|uninstall)\b"
)

# Paths that live under %TEMP%. Writing and deleting these is what a rehearsal
# is allowed to do, so they need no guard.
TEMP_SCOPED = re.compile(r"\$tempZipPath|\$tempExtractPath|\$stashDir|\$env:TEMP")

# Lines that only build a string or echo one are not mutations. A `function
# Install-CliCommand {` line names the cmdlet without calling it.
NOT_A_CALL = re.compile(r"^\s*(#|Write-Host|function\s|\"|')")

BLOCK_OPENERS = ("if", "elseif", "else", "foreach", "for", "while", "try",
                 "catch", "finally", "function", "switch", "do")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _opens_block(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("}"):
        stripped = stripped[1:].strip()
    return stripped.startswith(BLOCK_OPENERS) and stripped.endswith("{")


def _guards_against_dry_run(line: str) -> bool:
    """`if (-not $dryRun) {` and `if (... -and -not $dryRun) {`."""
    return bool(re.search(r"-not\s+\$dryRun", line))


def _is_dry_run_branch(line: str) -> bool:
    """`if ($dryRun) {` — the branch that only prints what would happen.

    `elseif` has to be spelled out: there is no word boundary before the `if`
    inside it, so a plain `\\bif` silently never matches an elseif chain.
    """
    return bool(re.search(r"\b(?:if|elseif)\s*\(\s*\$dryRun\s*\)", line))


def _self_guarding_functions(lines):
    """Functions that return early when $dryRun is set: name -> that return's line.

    Self-guarding is the better design for anything with more than one call
    site, so the test has to recognise it: a call site added later cannot
    reopen the hole, and the caller is not required to remember the flag.
    """
    safe = {}
    current = None
    pending = False
    for index, line in enumerate(lines):
        match = re.match(r"^function\s+([\w-]+)\s*\{", line)
        if match:
            current, pending = match.group(1), False
            continue
        if current is None:
            continue
        if line.startswith("}"):
            current = None
        elif _is_dry_run_branch(line):
            pending = True
        elif pending and re.search(r"\breturn\b", line):
            safe[current] = index
            current = None
    return safe


@pytest.fixture(scope="module")
def lines():
    assert SETUP.exists(), SETUP
    return SETUP.read_text(encoding="utf-8-sig").splitlines()


def _ancestors(lines, index):
    """Block-opening lines enclosing ``index``, innermost first.

    Indentation is the structure here: the script is uniformly four-space
    indented, and brace counting would trip over braces inside strings.
    """
    out = []
    depth = _indent(lines[index])
    for i in range(index - 1, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        if _indent(line) < depth and _opens_block(line):
            out.append((i, line))
            depth = _indent(line)
            if depth == 0:
                break
    return out


def _matching_if(lines, else_index):
    """The condition an `} else {` answers to.

    Returns every `if`/`elseif` at the same indent above it, because
    `if A {} elseif ($dryRun) {} else {}` reaches the final branch only when
    $dryRun is false — the else is guarded by the elseif.
    """
    depth = _indent(lines[else_index])
    out = []
    for i in range(else_index - 1, -1, -1):
        line = lines[i]
        if not line.strip() or _indent(line) != depth:
            continue
        stripped = line.strip()
        if stripped.startswith("if ("):
            out.append(line)
            break
        if stripped.startswith("}") and "elseif" in stripped.split("{")[0]:
            out.append(line)
    return out


def _is_guarded(lines, index):
    safe = _self_guarding_functions(lines)
    for i, ancestor in _ancestors(lines, index):
        if _guards_against_dry_run(ancestor):
            return True
        # `if ($dryRun) { ...report... } else { ...act... }`
        if ancestor.strip().startswith("}") and "else" in ancestor.split("{")[0]:
            if any(_is_dry_run_branch(c) for c in _matching_if(lines, i)):
                return True
        if _is_dry_run_branch(ancestor):
            # Inside the reporting branch: it prints, it does not act. Anything
            # mutating in here would be a bug, so do not call it guarded.
            return False
        match = re.match(r"^function\s+([\w-]+)\s*\{", ancestor)
        if match and index > safe.get(match.group(1), index):
            # Past the function's own early return.
            return True
    return False


def _mutating_lines(lines):
    safe = _self_guarding_functions(lines)
    for index, line in enumerate(lines):
        if NOT_A_CALL.match(line) or not line.strip():
            continue
        if not MUTATORS.search(line):
            continue
        if TEMP_SCOPED.search(line):
            continue
        # Calling a function that returns early on $dryRun needs no guard.
        if any(re.search(r"\b" + name + r"\b", line) for name in safe):
            continue
        yield index, line


def test_the_script_still_has_mutating_calls_to_check(lines):
    """A regex that matched nothing would make every other test vacuous."""
    found = list(_mutating_lines(lines))
    assert len(found) >= 8, "the mutation regex stopped matching; fix the test"


def test_every_mutation_outside_temp_is_guarded(lines):
    unguarded = [
        "  setup.ps1:{0}: {1}".format(index + 1, line.strip())
        for index, line in _mutating_lines(lines)
        if not _is_guarded(lines, index)
    ]
    assert not unguarded, (
        "These run even with CTS_SETUP_DRYRUN set, so a rehearsal would change "
        "the operator's machine:\n" + "\n".join(unguarded)
    )


def test_the_dry_run_flag_is_read_once(lines):
    """One spelling, so a site cannot be guarded by a typo that is always false."""
    source = "\n".join(lines)
    assert source.count("$env:CTS_SETUP_DRYRUN") == 2, (
        "read the environment variable once into $dryRun (plus the comment "
        "naming it); guard every site with $dryRun"
    )
    assert re.search(r"^\$dryRun\s*=", source, re.MULTILINE)


def test_the_backup_of_an_earlier_real_run_is_not_deleted(lines):
    """A rehearsal makes no backup, so any .backup found belongs to a real one."""
    for index, line in enumerate(lines):
        if "Remove-Item" in line and "$bodyPath.backup" in line:
            assert _is_guarded(lines, index), (
                "setup.ps1:{0} deletes a backup left by an earlier real "
                "install".format(index + 1)
            )
            return
    pytest.fail("the backup cleanup went away; re-target this test")


def test_the_pip_install_guards_itself(lines):
    """`pip install -e` rewrites the operator's environment — it may not rely
    on the caller remembering the flag."""
    assert "Install-CliCommand" in _self_guarding_functions(lines), (
        "Install-CliCommand must return early when $dryRun is set; without "
        "that, every call site has to be guarded by hand and a new one will "
        "eventually reopen the hole"
    )


def test_the_menu_generator_is_asked_for_its_own_dry_run(lines):
    """install_menu can validate for real and write nothing — use that."""
    source = "\n".join(lines)
    assert '$menuArgs += "--dry-run"' in source, (
        "a rehearsal should still exercise the stub generator, its ScriptDir "
        "discovery and its guards, via install_menu --dry-run"
    )
