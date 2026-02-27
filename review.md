# Stability & Performance Review — cds-text-sync

## Critical Stability Issues

### 1. `FolderManager.export()` — `NameError` on every call

**File:** `codesys_managers.py:495`

```python
target_dir = os.path.join(context['export_dir'], *full_path_parts)
```

`full_path_parts` is never defined in this scope. This will crash every time a folder is exported. The variable should likely be derived from `rel_path`.

### 2. `NativeManager.export()` — undefined `obj_name`

**File:** `codesys_managers.py:890`

```python
log_error("Native export failed for " + obj_name + ": " + safe_str(e))
```

`obj_name` is never assigned in this method. Should be `safe_str(obj.get_name())`.

### 3. Bare `except:` clauses everywhere

The codebase has dozens of bare `except:` / `except: pass` blocks (e.g., `codesys_utils.py:55,81,117,148,161,251,315,317,771,787`; `codesys_managers.py:251,255,419,445`). These silently swallow `KeyboardInterrupt`, `SystemExit`, and real bugs, making debugging extremely difficult. At minimum, use `except Exception:`.

### 4. `contents_are_equal` log format bug

**File:** `codesys_compare_engine.py:147`

```python
log_info("Line %d DIFFERS:")
```

Missing the format argument — should be `log_info("Line %d DIFFERS:" % i)`.

---

## Performance Issues

### 5. LCS diff algorithm is O(N\*M) in both time and memory

**File:** `codesys_ui_diff.py:27-39`
Status : DONE;

The `_compute_lcs_matrix` allocates a full `(M+1)*(N+1)` Python list-of-lists. For a 5,000-line file vs. 5,000-line file, that's 25 million cells of Python ints. This will be very slow and memory-hungry. The 100KB warning at line 543 helps, but a line-count threshold would be more appropriate. Consider using a linear-space algorithm or Myers' diff.

### 6. `get_task_for_write` and `is_nvl` call `project.get_children(recursive=True)` per object

**File:** `codesys_managers.py:53,87`

`get_task_for_write` iterates all project objects to resolve a single GUID-to-name lookup. If called for N task-local GVLs, this is O(N\*total_objects). Should accept a pre-built cache.

### 7. `collect_property_accessors` does two full O(N) passes

**File:** `codesys_managers.py:310-372`

Pass 2 re-scans all objects and re-calls `obj.get_children()` for every property. Since Pass 1 already found accessors via parent references, Pass 2 is redundant in the common case. Could be merged or short-circuited.

### 8. `find_all_changes` exports every XML object to temp file for comparison

**File:** `codesys_compare_engine.py:46-74`

Each XML object is exported to disk, read back, then compared. For large projects with many visualizations/configs, this is a significant I/O bottleneck. No caching is done across calls.

### 9. `update_application_count_flag` calls `get_children(recursive=True)` separately

**File:** `codesys_utils.py:354`

This is another full tree traversal that happens on every export/build/import. The count could be piggy-backed onto the main object iteration.

### 10. Module force-reload on every export

**File:** `Project_export.py:8-10`

```python
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]
```

This deletes all `codesys_*` modules from cache, forcing re-import. Useful during development but adds startup latency in production and can cause subtle issues with singleton state (like `_logger` being re-created).

---

## Minor Stability Concerns

### 11. CRC32 for content hashing

**File:** `codesys_utils.py:210-218`

CRC32 has higher collision probability than SHA256. For a sync tool where false "identical" = data loss, this is a non-trivial risk. The speed gain is marginal for typical file sizes.

### 12. `_metadata_thread_lock` defined but never used

**File:** `codesys_utils.py:20`

Dead code.

### 13. Daemon `time.sleep(0.5)` on UI thread

**File:** `Project_daemon.py:435`

After showing the dashboard, the daemon sleeps 500ms on the WinForms timer tick callback. This blocks the UI message pump. Could use a cooldown flag checked on the next tick instead.

### 14. `_on_save_button_click` generates incorrect filenames

**File:** `codesys_ui_diff.py:498`

The `ext` variable is always `.st` even for XML diffs, and the filename format string produces `disk_{name}_{ext}` which creates double-extension artifacts.

### 15. `cleanup_orphaned_files` modifies `dirs[:]` in `topdown=False` walk

**File:** `Project_export.py:115`

Modifying `dirs` only affects traversal when `topdown=True`. In `topdown=False` mode it's a no-op.

---

## Summary

| Category                | Count | Severity   |
| ----------------------- | ----- | ---------- |
| Crash bugs (NameError)  | 2     | **High**   |
| Silent error swallowing | ~40+  | **Medium** |
| Format string bug       | 1     | **Low**    |
| Performance hotspots    | 5     | **Medium** |
| Dead code / no-op logic | 3     | **Low**    |

The two `NameError` bugs (#1, #2) are the most urgent — they will crash at runtime. The bare `except` pattern (#3) is the most pervasive quality concern. The LCS performance (#5) and repeated tree traversals (#6, #9) are the biggest performance drags for large projects.
