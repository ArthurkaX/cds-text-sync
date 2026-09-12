"""Result model for ``cts verify``: stages, problems, and one verdict.

The shapes here *are* the public contract of the command. An agent reads this
JSON to decide what to do next, so two properties matter more than convenience:

* A stage that could not run is ``skipped``, never ``fail``. An agent working
  without a live IDE must not be told it broke the project.
* Problem lists are capped. Flooding an agent's context with three hundred
  findings makes the verdict less useful, not more.
"""

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"

#: Statuses that mean "this stage did not deliver a verdict".
INCOMPLETE_STATUSES = (STATUS_SKIPPED, STATUS_ERROR)

#: Per-stage cap on reported problems. The full count survives in
#: ``problem_count`` so a truncated report never hides how bad things are.
MAX_PROBLEMS_PER_STAGE = 20

SCHEMA_VERSION = 2


class Problem:
    """One concrete thing to fix, normalised across every stage.

    Stages report findings in their own vocabularies -- the analyzer has
    ``rule_id`` plus a ``Location``, the sketch linter has a rule name plus an
    element index, the compiler has a message code plus an object name. They
    are flattened here so an agent parses one shape instead of four.
    """

    def __init__(self, message, severity="", rule="", file="", line=None, where=""):
        self.message = message
        self.severity = severity
        self.rule = rule
        self.file = file
        self.line = line
        # Free-form locator for stages with no line number: an SVG element
        # index, a CODESYS object name.
        self.where = where

    def to_dict(self):
        data = {"message": self.message}
        for key, value in (
            ("severity", self.severity),
            ("rule", self.rule),
            ("file", self.file),
            ("where", self.where),
        ):
            if value:
                data[key] = value
        if self.line is not None:
            data["line"] = self.line
        return data

    def to_line(self):
        """One-line human rendering: ``file:line [rule] message``."""
        head = self.file or self.where
        if head and self.line is not None:
            head = f"{head}:{self.line}"
        parts = []
        if head:
            parts.append(head)
        if self.rule:
            parts.append(f"[{self.rule}]")
        parts.append(self.message)
        return " ".join(parts)


class StageResult:
    """The outcome of one stage of the gate."""

    def __init__(
        self,
        stage,
        status,
        reason="",
        reason_code="",
        summary=None,
        problems=None,
        duration_ms=None,
        complete=True,
    ):
        self.stage = stage
        self.status = status
        # Why a stage was skipped, or why it errored. Empty for pass/fail.
        self.reason = reason
        # Stable machine-readable counterpart to ``reason``. Human text is
        # intentionally free to evolve; agents and CI should branch on this.
        self.reason_code = reason_code
        self.summary = summary or {}
        self._problems = list(problems or [])
        self.duration_ms = duration_ms
        # A stage can run to completion and still have covered only part of
        # the project -- the analyzer reports exactly this when it cannot read
        # a file. That is incompleteness, not a pass.
        self.complete = complete

    @property
    def problem_count(self):
        """Total problems found, including any beyond the reporting cap."""
        return len(self._problems)

    @property
    def truncated(self):
        return self.problem_count > MAX_PROBLEMS_PER_STAGE

    @property
    def problems(self):
        """The reported slice of the problems, capped."""
        return self._problems[:MAX_PROBLEMS_PER_STAGE]

    @property
    def incomplete(self):
        return self.status in INCOMPLETE_STATUSES or not self.complete

    def to_dict(self):
        data = {"stage": self.stage, "status": self.status}
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if not self.complete:
            data["complete"] = False
        if self.reason:
            data["reason"] = self.reason
        if self.reason_code:
            data["reason_code"] = self.reason_code
        if self.summary:
            data["summary"] = self.summary
        if self._problems:
            data["problems"] = [p.to_dict() for p in self.problems]
            data["problem_count"] = self.problem_count
            data["truncated"] = self.truncated
        return data

    # -- constructors for the common cases ---------------------------------

    @classmethod
    def skipped(cls, stage, reason, reason_code="daemon_unavailable"):
        """A stage that could not run. Never counts against the verdict."""
        return cls(
            stage, STATUS_SKIPPED, reason=reason, reason_code=reason_code
        )

    @classmethod
    def errored(cls, stage, reason, reason_code="tool_error"):
        """A stage that broke. Incompleteness, not a failure of the project."""
        return cls(stage, STATUS_ERROR, reason=reason, reason_code=reason_code)


class VerifyReport:
    """Every stage result plus the single verdict derived from them."""

    def __init__(self, sync_folder="", stages=None, next_steps=None):
        self.sync_folder = sync_folder
        self.stages = list(stages or [])
        self.next_steps = list(next_steps or [])

    def add(self, stage_result):
        self.stages.append(stage_result)
        return stage_result

    @property
    def verdict(self):
        """``fail`` only when a stage actually found problems.

        Skipped and errored stages deliberately do not fail the gate -- they
        make it *incomplete*, which is reported separately.
        """
        if any(s.status == STATUS_FAIL for s in self.stages):
            return STATUS_FAIL
        return STATUS_PASS

    @property
    def complete(self):
        # An empty selection is a configuration error, not a verified project.
        return bool(self.stages) and not any(s.incomplete for s in self.stages)

    def exit_code(self, incomplete="warn"):
        """Exit policy, mirroring ``cds_static_analyzer.runner.exit_code``.

        0 pass, 1 real problems, 3 incomplete under ``--incomplete error``.
        Code 2 is raised before a report exists (see ``VerifyStartError``).
        """
        if self.verdict == STATUS_FAIL:
            return 1
        if incomplete == "error" and not self.complete:
            return 3
        return 0

    def to_dict(self, incomplete="warn"):
        data = {
            "schema_version": SCHEMA_VERSION,
            "verdict": self.verdict,
            "complete": self.complete,
            "exit_code": self.exit_code(incomplete),
        }
        if self.sync_folder:
            data["sync_folder"] = self.sync_folder
        data["stages"] = [s.to_dict() for s in self.stages]
        if self.next_steps:
            data["next"] = list(self.next_steps)
        return data

    def to_text(self, incomplete="warn"):
        """Human rendering. Same information, read top to bottom."""
        lines = []
        for stage in self.stages:
            head = f"[{stage.status.upper()}] {stage.stage}"
            if stage.duration_ms is not None:
                head += f" ({stage.duration_ms} ms)"
            if stage.reason:
                head += f" -- {stage.reason}"
            lines.append(head)
            for problem in stage.problems:
                lines.append(f"    {problem.to_line()}")
            if stage.truncated:
                hidden = stage.problem_count - len(stage.problems)
                lines.append(f"    ... and {hidden} more ({stage.problem_count} total)")

        lines.append("")
        verdict = f"verdict: {self.verdict}"
        if not self.complete:
            verdict += " (incomplete -- some stages did not run)"
        lines.append(verdict)
        if self.next_steps:
            lines.append("next:")
            for step in self.next_steps:
                lines.append(f"    {step}")
        return "\n".join(lines)


class VerifyStartError(Exception):
    """The gate could not start at all. Always exit code 2.

    Distinct from a failing stage: nothing was verified, so reporting ``fail``
    would claim knowledge the command does not have.
    """

    exit_code = 2


__all__ = [
    "MAX_PROBLEMS_PER_STAGE",
    "SCHEMA_VERSION",
    "STATUS_ERROR",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_SKIPPED",
    "Problem",
    "StageResult",
    "VerifyReport",
    "VerifyStartError",
]
