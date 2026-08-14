"""Background workspace-scan job service with progress polling and a wall-clock budget.

The scanner drives ``analyzer.analyze_path`` (or a test double) over the files
in a workspace file index, runs every parse under a strict per-file wall-clock
budget, and publishes the section 8.2 ``file_result`` rows as pollable events.
It has no CODESYS or pywebview dependency.

Why the per-future budget bound exists (this is the whole point of the class):
a task already running inside a ``ProcessPoolExecutor`` worker cannot be
interrupted, so without a deadline the job thread would block forever inside
``future.result()`` on one pathological file - reproducing the original hang
in this architecture, where a Stop button cannot help because it could never
run.  The scanner therefore never waits on a future without a timeout derived
from ``budget_seconds``, records a timeout as an error row, and keeps going,
so a single wedged file can never fail or stall the scan.
"""

from __future__ import annotations

import concurrent.futures
import os
import threading
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

from . import workspace as workspace_mod
from .analyzer import analyze_path
from .model import STATE_ERROR, STATE_FSM, file_result
from .workspace import resolve_in_root


def _analyze_worker(path_text: str, relative: str) -> dict:
    """Module-level worker entry point, picklable under Windows spawn.

    Call the analyzer through this module-level name so tests can monkeypatch
    ``cds_text_sync.fsm.scanner._analyze_worker`` with a counting wrapper and
    so ``ProcessPoolExecutor`` can pickle the reference for the child process.
    """
    return analyze_path(path_text, relative=relative)


def _submit_inline(fn, *args) -> concurrent.futures.Future:
    """Run *fn* in a fresh daemon thread and return its result as a Future.

    ``max_workers=1`` means "run inline, create no process pool at all".  The
    worker still runs on its own thread so the wall-clock budget can be applied
    uniformly via ``future.result(timeout=...)`` - an inline call in the job
    thread itself could not be interrupted any more than a pool task could.
    """
    future = concurrent.futures.Future()

    def _drain(done):
        try:
            done.exception()  # mark any unretrieved exception as retrieved
        except BaseException:
            pass

    future.add_done_callback(_drain)

    def runner():
        try:
            result = fn(*args)
        except BaseException as error:
            future.set_exception(error)
        else:
            future.set_result(result)

    threading.Thread(target=runner, daemon=True).start()
    return future


def _completed_future(value) -> concurrent.futures.Future:
    """A Future that is already resolved, for cache hits and inline errors."""
    future = concurrent.futures.Future()
    future.set_result(value)
    return future


class Scanner:
    """A background workspace-scan job service.

    One scan runs on one worker thread that drives parsing and records events.
    Starting a new scan supersedes the previous job: the old one is marked
    cancelled and its later results are ignored.  ``poll_scan`` returns a
    snapshot plus only the events after the supplied cursor, so a frontend can
    poll with the returned cursor and never see duplicates.
    """

    def __init__(self, workspace, budget_seconds=10.0, max_workers=None):
        self._workspace = str(Path(workspace).expanduser().resolve())
        # Store the resolved source root via workspace.source_root, accepting
        # either a sync folder or a path pointing straight at project-view.
        self.source_root = workspace_mod.source_root(Path(self._workspace))
        self.budget_seconds = float(budget_seconds)
        if max_workers is None:
            # Copy the fsm_search rule: never more than 6, never more than CPU
            # count.  The candidate-count clamp happens per scan in
            # ``_effective_workers``.
            max_workers = min(6, os.cpu_count() or 1)
        self._max_workers = max(1, int(max_workers))
        self._lock = threading.Lock()
        # Relative path -> {"size": ..., "mtime_ns": ...} from the last index.
        self._file_index: dict = {}
        # Relative path -> {"fingerprint": ..., "result": ...}.  Only
        # successful (non-timeout) results are cached.
        self._cache: dict = {}
        self._jobs: dict = {}
        self._current = None
        self._pools = []
        self._closed = False

    # ------------------------------------------------------------------ index

    def _effective_workers(self, candidate_count: int) -> int:
        # Copy the fsm_search rule: min(6, cpu), clamped to the candidate
        # count, and never below 1 so a zero-file workspace stays inline.
        return max(1, min(self._max_workers, candidate_count or 1))

    def bootstrap(self) -> dict:
        """Delegate to ``workspace.bootstrap`` and remember the file index."""
        payload = workspace_mod.bootstrap(self._workspace)
        index = {
            entry["path"]: {"size": entry["size"], "mtime_ns": entry["mtime_ns"]}
            for entry in payload["files"]
        }
        with self._lock:
            self._file_index = index
        return payload

    def refresh_workspace(self) -> dict:
        """Re-read the index, dropping cache entries that went stale.

        A cached entry is dropped when its file's ``(size, mtime_ns)`` changed
        or the file disappeared; unchanged entries are kept.  Returns the new
        bootstrap payload.
        """
        payload = workspace_mod.bootstrap(self._workspace)
        new_index = {
            entry["path"]: {"size": entry["size"], "mtime_ns": entry["mtime_ns"]}
            for entry in payload["files"]
        }
        with self._lock:
            for relative in list(self._cache):
                current = new_index.get(relative)
                cached_fingerprint = self._cache[relative]["fingerprint"]
                if current is None or current != cached_fingerprint:
                    del self._cache[relative]
            self._file_index = new_index
        return payload

    # ----------------------------------------------------------------- cache

    def _cache_get(self, relative: str):
        with self._lock:
            entry = self._cache.get(relative)
            if entry is None:
                return None
            return {"fingerprint": entry["fingerprint"], "result": entry["result"]}

    def _cache_success(self, relative: str, result: dict) -> None:
        """Cache only successful (non-timeout) results that carry a fingerprint."""
        fingerprint = result.get("fingerprint")
        if result["state"] != STATE_ERROR and fingerprint:
            with self._lock:
                self._cache[relative] = {"fingerprint": fingerprint, "result": result}

    # --------------------------------------------------------------- scanning

    def start_scan(self, paths=None) -> dict:
        """Start one background scan; returns ``{"job_id": str, "total": int}``.

        *paths* is an optional list of relative paths; None means the whole
        index.  A new scan supersedes any previous job: the old one is marked
        cancelled and its later results are ignored.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Scanner is closed")
            if paths is None:
                paths = list(self._file_index)
            else:
                paths = [str(path) for path in paths]
            total = len(paths)
            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "state": "queued",
                "total": total,
                "completed": 0,
                "hits": 0,
                "errors": 0,
                "wedged": 0,
                "events": [],
                "cancel": threading.Event(),
                "done": threading.Event(),
                "paths": paths,
                "pending": [],
                "snapshot": {
                    "state": "queued",
                    "total": total,
                    "completed": 0,
                    "hits": 0,
                    "errors": 0,
                },
            }
            self._jobs[job_id] = job
            old = self._current
            if old is not None and old is not job:
                old["cancel"].set()
                for future in old["pending"]:
                    future.cancel()
                old["pending"] = []
            self._current = job
            thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
            thread.start()
        return {"job_id": job_id, "total": total}

    def poll_scan(self, job_id, cursor=0) -> dict:
        """Snapshot of one job; ``events`` holds only events after *cursor*.

        Following ui.py's ``_record_progress`` convention, the worker replaces
        the snapshot dict wholesale and the poll copies it under the lock, so
        a poll never observes a half-written progress report.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {
                    "job_id": job_id,
                    "state": "failed",
                    "total": 0,
                    "completed": 0,
                    "hits": 0,
                    "errors": 0,
                    "cursor": 0,
                    "events": [],
                }
            snapshot = dict(job["snapshot"])
            try:
                start = max(0, int(cursor or 0))
            except (TypeError, ValueError):
                start = 0
            events = list(job["events"][start:])
        return {
            "job_id": job_id,
            "state": snapshot["state"],
            "total": snapshot["total"],
            "completed": snapshot["completed"],
            "hits": snapshot["hits"],
            "errors": snapshot["errors"],
            "cursor": start + len(events),
            "events": events,
        }

    def cancel_scan(self, job_id) -> dict:
        """Cooperative cancel: set the flag, cancel unstarted futures, stop consuming."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"ok": False, "state": "failed"}
            if job["done"].is_set():
                return {"ok": False, "state": job["snapshot"]["state"]}
            job["cancel"].set()
            for future in job["pending"]:
                future.cancel()
            job["pending"] = []
            return {"ok": True, "state": job["snapshot"]["state"]}

    def analyze_file(self, relative_path) -> dict:
        """Analyze a single prioritized file, respecting the same budget.

        Runs inline (on its own thread), never behind the job queue, and never
        blocks on a queued scan.  The cache is consulted first.
        """
        relative_path = str(relative_path)
        resolved = resolve_in_root(self.source_root, relative_path)
        if resolved is None:
            return file_result(
                relative_path, [], error=f"Path escapes the source root: {relative_path}"
            )
        if not resolved.is_file():
            return file_result(
                relative_path, [], error=f"Source file does not exist: {relative_path}"
            )
        fingerprint = workspace_mod.fingerprint(resolved)
        cached = self._cache_get(relative_path)
        if cached is not None and cached["fingerprint"] == fingerprint:
            return cached["result"]
        future = _submit_inline(_analyze_worker, str(resolved), relative_path)
        try:
            result = future.result(timeout=self.budget_seconds)
        except FutureTimeoutError:
            return file_result(
                relative_path, [], error=self._budget_message()
            )
        except Exception as error:
            return file_result(relative_path, [], error=str(error))
        self._cache_success(relative_path, result)
        return result

    def close(self) -> None:
        """Shut executors down without waiting; safe to call twice."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for job in self._jobs.values():
                job["cancel"].set()
                for future in job["pending"]:
                    future.cancel()
                job["pending"] = []
            pools = self._pools
            self._pools = []
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # ------------------------------------------------------------------ jobs

    def _budget_message(self) -> str:
        return f"Parse exceeded the {self.budget_seconds:.1f} s budget."

    def _set_state(self, job, state) -> None:
        with self._lock:
            job["state"] = state
            job["snapshot"] = {
                "state": state,
                "total": job["total"],
                "completed": job["completed"],
                "hits": job["hits"],
                "errors": job["errors"],
            }

    def _emit(self, job, result) -> bool:
        """Record one file result; returns False when the job was cancelled.

        Following ui.py's ``_record_progress`` convention: build the snapshot
        dict and replace it wholesale so a poll never sees a half-written
        progress report.
        """
        with self._lock:
            if job["cancel"].is_set():
                return False
            job["events"].append(result)
            job["completed"] += 1
            if result["state"] == STATE_ERROR:
                job["errors"] += 1
            elif result["state"] == STATE_FSM:
                job["hits"] += 1
            job["snapshot"] = {
                "state": job["state"],
                "total": job["total"],
                "completed": job["completed"],
                "hits": job["hits"],
                "errors": job["errors"],
            }
            return True

    def _run_job(self, job) -> None:
        try:
            self._set_state(job, "running")
            workers = self._effective_workers(len(job["paths"]))
            if workers == 1:
                self._run_inline(job, job["paths"])
            else:
                self._run_pool(job, job["paths"], workers)
        except Exception as error:
            self._set_state(job, "failed")
            job["error"] = str(error)
        finally:
            with self._lock:
                if job["cancel"].is_set():
                    if job["state"] != "failed":
                        job["state"] = "cancelled"
                elif job["state"] == "running":
                    job["state"] = "completed"
                job["snapshot"] = {
                    "state": job["state"],
                    "total": job["total"],
                    "completed": job["completed"],
                    "hits": job["hits"],
                    "errors": job["errors"],
                }
                job["done"].set()

    def _run_inline(self, job, candidates) -> None:
        """Parse every candidate in this process, one fresh thread each.

        No process pool is created; each file still runs under the wall-clock
        budget via ``_submit_inline`` + ``future.result(timeout=...)``.
        """
        for relative in candidates:
            if job["cancel"].is_set():
                break
            result = self._analyze_one_inline(job, relative)
            if result is None or job["cancel"].is_set():
                break
            self._emit(job, result)

    def _analyze_one_inline(self, job, relative: str):
        resolved = resolve_in_root(self.source_root, relative)
        if resolved is None or not resolved.is_file():
            return file_result(
                relative, [], error=f"Source file is missing or outside the workspace: {relative}"
            )
        fingerprint = workspace_mod.fingerprint(resolved)
        cached = self._cache_get(relative)
        if cached is not None and cached["fingerprint"] == fingerprint:
            return cached["result"]
        future = _submit_inline(_analyze_worker, str(resolved), relative)
        try:
            result = future.result(timeout=self.budget_seconds)
        except FutureTimeoutError:
            job["wedged"] += 1
            return file_result(relative, [], error=self._budget_message())
        except Exception as error:
            return file_result(relative, [], error=str(error))
        self._cache_success(relative, result)
        return result

    def _run_pool(self, job, candidates, workers) -> None:
        pool = ProcessPoolExecutor(max_workers=workers)
        with self._lock:
            self._pools.append(pool)
        try:
            remaining = iter(candidates)
            available = workers
            pending = deque()
            for _ in range(available):
                try:
                    relative = next(remaining)
                except StopIteration:
                    break
                self._submit_next(job, pending, relative, pool)
            wedged = 0
            while pending:
                if job["cancel"].is_set():
                    break
                relative, future = pending.popleft()
                with self._lock:
                    if future in job["pending"]:
                        job["pending"].remove(future)
                try:
                    result = future.result(timeout=self.budget_seconds)
                except FutureTimeoutError:
                    wedged += 1
                    job["wedged"] += 1
                    # The wedged worker's slot is lost for the rest of the job;
                    # shrink the in-flight window so queued work does not pile
                    # up behind a worker that will never finish.  The pool is
                    # torn down below so the slot is reclaimed at job end.
                    available = max(0, workers - wedged)
                    result = file_result(relative, [], error=self._budget_message())
                except Exception as error:
                    result = file_result(relative, [], error=str(error))
                if job["cancel"].is_set():
                    break
                self._emit(job, result)
                self._cache_success(relative, result)
                while len(pending) < available:
                    try:
                        relative = next(remaining)
                    except StopIteration:
                        break
                    self._submit_next(job, pending, relative, pool)
        finally:
            with self._lock:
                if pool in self._pools:
                    self._pools.remove(pool)
                job["pending"] = []
            pool.shutdown(wait=False, cancel_futures=True)

    def _submit_next(self, job, pending, relative, pool) -> None:
        """Submit one candidate to *pool*, honouring the cache first."""
        resolved = resolve_in_root(self.source_root, relative)
        if resolved is None or not resolved.is_file():
            future = _completed_future(
                file_result(
                    relative, [], error=f"Source file is missing or outside the workspace: {relative}"
                )
            )
        else:
            fingerprint = workspace_mod.fingerprint(resolved)
            cached = self._cache_get(relative)
            if cached is not None and cached["fingerprint"] == fingerprint:
                future = _completed_future(cached["result"])
            else:
                future = pool.submit(_analyze_worker, str(resolved), relative)
        pending.append((relative, future))
        with self._lock:
            job["pending"].append(future)
