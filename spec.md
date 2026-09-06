# Reliability and Safety Remediation Specification

## 1. Purpose

This specification defines the implementation work accepted from `review.md`.
The work is intentionally split into small, independently verifiable changes so
that the named-pipe transport, filesystem safety, export reliability, and parser
behavior can be reviewed without mixing unrelated risks.

The implementation is divided into three delivery phases:

1. Repair Windows overlapped named-pipe I/O.
2. Harden patch paths and make folder exports crash-safe at the file level.
3. Improve ST section parsing and raw CLI argument validation.

No production behavior should be changed outside these areas.

## 2. Scope

### Required work

- Correct overlapped `ConnectNamedPipe`, `ReadFile`, and `WriteFile` handling.
- Enforce one request deadline across pipe connect, write, and read operations.
- Validate patch source and destination paths against their allowed roots.
- Write manifests, projections, and generated XML through one atomic-write helper.
- Abort export when a previously managed file cannot be deleted.
- Parse the ST `IMPLEMENTATION` marker case-insensitively and with safe whitespace handling.
- Reject unexpected positional arguments passed to `cts raw` / `cts rp`.
- Add regression tests for every changed behavior.

### Optional hardening included only if it remains small

- Keep findings without line numbers out of adjacent-line merging.
- Restrict analyzer UI `open_file` targets to analyzer-supported source extensions.
- Replace remaining raw visualization Member IDs with named constants when
  `svg_export.py` is next changed for functional work.

### Explicit non-goals

- Replacing visualization overlap checks with an R-tree or grid index.
- Automatically deleting `.cds-casefix-*` recovery files.
- Rewriting the call-tree parser for the multiline method-call example from the review.
- Replacing the FSM normalization cache.
- Removing the CODESYS bridge's deliberate `sys.path` setup.
- Making an entire multi-file export transactional. Atomic writes protect each
  file, but a complete export may still be interrupted between files.

## 3. Delivery Plan

## Phase 1 — Windows Named-Pipe Transport

Implement this phase as an isolated change because it affects every reverse-pipe
command and has the highest regression risk.

### Step 1.1 — Add a transport integration test

Add a Windows-only test for
`products/cds-text-sync/src/cds_text_sync/engine/reverse_pipe_client.py` that does
not require CODESYS.

The test must:

1. Create the reverse-pipe server through the production client code.
2. Start a small test pipe peer in a separate thread.
3. Connect the peer to the named pipe.
4. Read one length-prefixed JSON request.
5. Write one length-prefixed JSON response.
6. Assert that `send_command()` returns the decoded response.
7. Fail on the current invalid `lpOverlapped=None` implementation.

Use a unique pipe name per test process to prevent collisions with a running
CODESYS daemon or parallel test workers. Mark the test skipped on non-Windows
platforms.

### Step 1.2 — Correct the Win32 declarations

Review and correct the `ctypes` declarations used by the transport:

- Define `OVERLAPPED` with pointer-sized `Internal` and `InternalHigh` fields.
- Add explicit constants for `WAIT_OBJECT_0`, `WAIT_TIMEOUT`, and relevant error codes.
- Declare `CancelIoEx` and prefer it over `CancelIo` for operation-specific cancellation.
- Ensure the `ReadFile`, `WriteFile`, `GetOverlappedResult`, event, and cancellation
  signatures accept the pointer types actually passed by the implementation.

The implementation must remain compatible with 32-bit and 64-bit CPython on Windows.

### Step 1.3 — Introduce one overlapped-operation primitive

Create a private helper that performs one overlapped read or write operation.
It must:

1. Allocate a fresh manual-reset event and a fresh `OVERLAPPED` structure.
2. Start the Win32 operation with a non-null `lpOverlapped` pointer.
3. Accept immediate synchronous completion as success.
4. On `ERROR_IO_PENDING`, wait only for the remaining request deadline.
5. Call `GetOverlappedResult` after the event is signaled.
6. Cancel the specific pending operation on timeout or failure.
7. Close the event in all paths.
8. Return the actual transferred byte count.

Do not reuse one `OVERLAPPED` structure for concurrent or sequential operations.

### Step 1.4 — Make framing deadline-aware

Update `_write_msg` and `_read_msg` to use the overlapped helper and the absolute
deadline created by `send_command()`.

Requirements:

- The four-byte header and JSON body must be fully transferred even when Win32
  completes an operation with a partial byte count.
- A zero-byte read must be treated as a broken or closed pipe, not as a loop retry.
- The existing maximum response-size validation must remain in force.
- Connect, write, and read must consume the same timeout budget; no phase may
  reset the timeout.
- Timeout errors must retain the command name and the existing explanation that
  timing out the client does not cancel work already running in CODESYS.

### Step 1.5 — Remove the reader-thread workaround

Once reads are genuinely overlapped and deadline-aware, remove the daemon reader
thread from `send_command()`. Waiting and cancellation should happen in the
calling thread through the operation event and `CancelIoEx`.

Resource cleanup must be idempotent. Never call pipe operations with an invalid
handle after it has already been closed.

### Step 1.6 — Cover failure modes

Add tests for:

- successful request/response exchange;
- a response larger than one read buffer;
- partial header and body transfers;
- peer disconnect while reading the header;
- peer disconnect while reading the body;
- connect timeout;
- response timeout;
- oversized response rejection;
- cleanup after an exception, including event and pipe handles.

Where exact Win32 timing would make a test flaky, test the operation helper with
a narrow fake API boundary and keep at least one real Windows pipe integration test.

### Phase 1 acceptance criteria

- No `ReadFile`, `WriteFile`, or `ConnectNamedPipe` call on an overlapped handle
  passes a null `lpOverlapped` pointer.
- Reverse-pipe commands preserve one end-to-end timeout.
- Timeout cancellation does not depend on cancelling I/O from another thread.
- The Windows integration test passes repeatedly and does not leave handles or threads behind.
- Existing reverse-pipe error messages remain actionable.

## Phase 2 — Patch Path Safety and Export Reliability

### Step 2.1 — Add a resolved-path containment helper for patch creation

Add a small helper in the CLI patch module, or reuse a shared helper only if doing
so does not create an undesirable package dependency.

The helper must:

1. Reject empty paths and paths containing no file name.
2. Resolve the candidate against an explicit root.
3. Resolve existing symlinks and Windows junctions in parent directories.
4. Verify the resolved candidate is strictly below the resolved root.
5. Reject absolute drive paths, UNC paths, rooted paths, and `..` escapes.
6. Return the safe resolved path or raise a clear validation error.

Use `pathlib.Path` and `Path.is_relative_to`, as the project requires Python 3.11 or newer.

### Step 2.2 — Validate both sides of every patch copy

In `products/cds-cli/src/cds_cli/_cli_handlers_patch.py`, validate paths twice:

- Resolve the source below `layout.view_root` before checking `is_file()`.
- Resolve the destination below `target_root` before creating directories or copying.

Validation must happen during the initial collection pass as well as immediately
before copying, so an invalid path cannot appear as a valid entry in dry-run output.
An unsafe path is a fatal error. Do not classify it as a merely missing file.

Do not create `out_dir`, `target_root`, or any destination parent until every
changeset path has passed validation. This prevents a rejected changeset from
leaving a partial patch directory.

### Step 2.3 — Add patch path regression tests

Add tests for:

- a normal nested `.st` path;
- `../` source traversal;
- traversal that targets a location outside the patch output;
- an absolute Windows drive path;
- a UNC path;
- mixed `/` and `\\` separators;
- a path whose existing parent is a symlink or junction outside the root;
- dry-run rejection without filesystem writes;
- no partial patch output when any one changeset entry is unsafe.

Tests that require Windows junction behavior may be Windows-only. Symlink tests
should gracefully skip when the current account cannot create symlinks.

### Step 2.4 — Introduce an atomic text-write helper

Add one private, reusable helper for generated text files in the folder engine.
It must:

1. Ensure the destination parent exists.
2. Create a uniquely named temporary file in that same directory.
3. Write using the requested encoding and newline behavior.
4. Flush Python buffers and call `os.fsync` before replacement.
5. Close the temporary file.
6. Publish it with `os.replace(temp_path, destination)`.
7. Remove the new temporary file if writing or replacement fails.
8. Preserve the original destination when an error occurs before `os.replace`.

The helper must not use a predictable fixed `.tmp` name because concurrent
exports and stale temporary files must not collide.

### Step 2.5 — Route generated output through atomic writes

Replace direct writes in `folder_writer.py` for:

- projection `.st` and `.csv` files;
- generated/externalized XML files;
- `.dump/manifest.json`.

Keep the manifest as the last successfully published file in a completed export.
Serialize JSON deterministically with the current indentation and add an explicit
UTF-8 encoding rather than relying on the operating-system default.

Do not atomically replace locally modified files that the dirty-file guard has
chosen to preserve.

### Step 2.6 — Fail closed on managed-file deletion errors

Change `_remove_previous_managed_files_from_root` so that a failure to delete an
existing managed file aborts the export with a `RuntimeError` that includes the
affected path and original OS error.

Do not continue to produce a new manifest after a failed deletion. A successful
"file already absent" condition is not an error, but a file that still exists
after an attempted deletion is.

### Step 2.7 — Add export failure tests

Add tests proving that:

- a successful atomic write produces the same bytes as before;
- an exception during temp-file writing leaves the old destination unchanged;
- a failed `os.replace` leaves the old destination unchanged and cleans the new temp file;
- manifest publication remains last;
- a manifest write failure does not truncate the previous manifest;
- a projection or XML write failure does not truncate its previous file;
- a mocked managed-file deletion failure aborts the export;
- no new manifest is published after a deletion failure;
- dirty files continue to be preserved exactly as before.

Use mocks for deletion failures instead of relying on platform-specific file-lock behavior.

### Phase 2 acceptance criteria

- No path supplied by a changeset can be read from outside the view root or
  written outside the patch target root.
- Unsafe changesets create no partial output directory.
- Generated XML, projection, and manifest files are individually atomic.
- The previous manifest survives any failed manifest write or replace operation.
- Export stops on a managed-file deletion failure and never publishes a manifest
  that pretends the deletion succeeded.
- Existing dirty-file and text-first behavior remains covered and unchanged.

## Phase 3 — ST Parsing and Raw CLI Validation

### Step 3.1 — Replace exact-string `IMPLEMENTATION` detection

In `products/cds-static-analyzer/src/cds_static_analyzer/project.py`, replace the
exact `"\nIMPLEMENTATION\n"` search with a line-oriented matcher.

The matcher must:

- be case-insensitive;
- recognize the marker at the beginning of the file;
- allow spaces and tabs after the keyword;
- accept both a following newline and end-of-file;
- use `[ \\t]*`, not `\\s*`, so it does not consume blank lines or code;
- preserve correct declaration and implementation `SourceSpan` offsets;
- avoid matching the word inside comments, strings, or a larger identifier.

Retain support for the legacy `// --- implementation ---` marker. If the legacy
marker is touched, apply the same line-boundary and offset rules without changing
its accepted spelling unnecessarily.

### Step 3.2 — Add ST split regression tests

Cover:

- canonical uppercase marker;
- lowercase and mixed-case markers;
- marker at byte offset zero;
- trailing spaces and tabs;
- LF and CRLF input;
- marker at end-of-file;
- blank lines immediately after the marker;
- `IMPLEMENTATION` text inside a line comment;
- `IMPLEMENTATION` text inside a block comment;
- an identifier containing the word;
- exact declaration and implementation spans and line numbers.

Run representative analyzer rules against the variants to prove that
implementation rules see the body and declaration rules still see declarations.

### Step 3.3 — Reject unexpected raw CLI positional arguments

Change `_parse_key_value_args` in
`products/cds-cli/src/cds_cli/_cli_io.py` so that a token not belonging to a
`--key [value]` pair raises a clear CLI usage error instead of being discarded.

Expected behavior:

- `cts raw ping --timeout 10` remains valid.
- Boolean flags without a following value remain valid.
- Negative numeric values following an option remain values, not option names.
- A standalone positional token after the method is rejected and named in the error.
- Repeated keys retain the current last-value-wins behavior unless separately specified.
- The deprecated `cts rp` alias behaves identically.

Do not add ad-hoc list parsing to `cts raw`. Users who need batch variable reads
should use the structured `cts read` command; raw daemon parameters remain simple
key/value strings.

### Step 3.4 — Add raw CLI parsing tests

Add focused unit tests for:

- valid key/value pairs;
- boolean flags;
- negative numeric values;
- multiple unexpected positional arguments;
- a positional argument following a valid pair;
- identical failure behavior through `raw` and `rp` dispatch.

The CLI must exit non-zero and print an actionable message without contacting the daemon.

### Step 3.5 — Optional adjacent-merge guard

If included, update `_merge_adjacent` in
`products/cds-static-analyzer/src/cds_static_analyzer/runner.py` so findings with
`location.line is None` remain independent and are never merged into a line-based run.

Add a direct unit test containing one file-level finding and findings on lines 1
and 2. The two line findings may merge; the file-level finding must remain separate.

This is defensive hardening rather than a currently reachable built-in-rule defect.

### Step 3.6 — Optional analyzer UI extension allowlist

If included, validate the suffix in `AnalyzerApi.open_file` before launching an
external application. Allow only source types actually produced by the analyzer,
initially `.st` and `.xml`, compared case-insensitively.

Keep the existing resolved-root containment check. Add tests proving that an
allowed source opens and `.bat`, `.cmd`, `.exe`, and shortcut files are rejected.

### Phase 3 acceptance criteria

- Valid ST section variants produce correct declaration and implementation text
  with correct source offsets.
- Comment or identifier text cannot become a false section boundary.
- Unexpected raw CLI positionals fail before any daemon request is sent.
- Existing documented raw commands remain compatible.
- Optional hardening, if included, has direct unit coverage and no unrelated UI changes.

## 4. Work Explicitly Deferred or Rejected

### Visualization overlap indexing

Keep the current quadratic overlap and crowding checks. A local full-lint timing
was approximately 0.13 seconds for 600 elements and 0.34 seconds for 1,000
elements. Introduce spatial indexing only after a reproducible real-world profile
shows that these rules materially affect command latency.

### `.cds-casefix-*` cleanup

Do not delete the temporary recovery path in a `finally` block. If the second
rename and rollback both fail, that path may contain the only surviving copy of
the original file. A future improvement may log the recovery path more prominently,
but automatic deletion is out of scope.

### Multiline call-tree example

Do not change the method-call regex for `MyInstance\n.Method(...)`. The current
`\\s*` expressions around the dot already match newlines, so the reviewed example
is already supported. Broader call-tree parser improvements require separate
failing fixtures and a dedicated specification.

### Low-value cleanup

Do not change `ensure_dir`, the FSM cache eviction policy, or CODESYS bridge
`sys.path` behavior as part of this work. These changes do not address a current
correctness failure and would broaden regression scope.

## 5. Verification Strategy

After each phase:

1. Run the new focused tests first.
2. Run all directly affected unit-test modules.
3. Run the complete unit test suite.
4. Run repository formatting, linting, and static checks configured by CI.
5. Run `tools/ci_product_checks.py` and `tools/ci_analyze_checks.py` when applicable.
6. Review `git diff --check` and confirm no generated or temporary files remain.

Phase 1 must also be exercised on a real Windows host. Before release, run at
least `ping`, one small command, and one large response command against the real
CODESYS daemon, including a deliberately short timeout.

Phase 2 should be manually smoke-tested with both XML-first and text-first sync
folders. Confirm clean export, dirty-file preservation, patch dry-run, patch save,
and a second export over an existing manifest.

## 6. Compatibility Requirements

- Preserve the existing length-prefixed JSON wire format.
- Preserve CLI command names, output formats, and successful exit behavior.
- Preserve manifest schema and path separator conventions.
- Preserve generated XML, ST, and CSV contents byte-for-byte except for an
  explicit UTF-8 manifest encoding and any already-existing newline behavior.
- Preserve dirty-file protection and selected-GUID export behavior.
- Keep Windows-specific tests skipped cleanly on other platforms.

## 7. Completion Definition

The specification is complete when all required steps and their tests are merged,
all phase acceptance criteria pass, and the explicitly deferred items remain
unchanged. Optional hardening does not block completion unless it is started; if
started, it must meet its stated tests and acceptance criteria before merge.
