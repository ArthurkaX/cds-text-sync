# Refactor Plan: Remove Metadata Files & DRY Cleanup

**Date:** 2026-02-23  
**Goal:** Remove `_config.json` and `_metadata.csv`, switch to direct IDE↔Disk comparison, apply DRY principles.

---

## Summary of Changes

| What                       | Before                                                | After                                                      |
| -------------------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| `_config.json`             | Written on export, mirrors Project Properties         | **Removed** — Project Properties is single source of truth |
| `_metadata.csv`            | Written on export, used as baseline for 3-way compare | **Removed** — direct 2-way IDE↔Disk comparison             |
| Comparison                 | 3-way (IDE vs metadata vs Disk) → direction arrows    | 2-way (IDE vs Disk) → "Different" / "Identical"            |
| Object type classification | Duplicated in export.py + compare_engine.py           | Single `classify_object()` function                        |
| Metadata dict creation     | Repeated 8× across managers                           | **Removed** — managers return `(status, rel_path)` only    |
| `ConfigManager.export()`   | 90% copy of `NativeManager.export()`                  | Calls `super().export()` with `recursive=True` param       |
| `RESERVED_FILES`           | Hardcoded in 2 places                                 | Single constant in `codesys_constants.py`                  |

---

## Phase 1: Extract Shared Logic (DRY — no behavior changes)

### 1.1 — `classify_object()` → `codesys_managers.py`

Extract the repeated "determine effective type" logic into a shared function.

**Currently duplicated in:**

- `Project_export.py` lines 286-325
- `codesys_compare_engine.py` lines 99-122

**New function:**

```python
# codesys_managers.py

def classify_object(obj):
    """
    Determine the effective export type for a CODESYS object.

    Returns:
        (effective_type, is_xml, should_skip)
        - effective_type: the resolved type GUID (e.g. NVL replaces GVL)
        - is_xml: True if object should be exported/compared as native XML
        - should_skip: True if object should be ignored (property_accessor, task, etc.)
    """
    obj_type = safe_str(obj.type)
    effective_type = obj_type
    is_xml = False

    # Skip non-exportable
    if obj_type == TYPE_GUIDS["property_accessor"]:
        return obj_type, False, True
    if obj_type == TYPE_GUIDS["task"]:
        return obj_type, False, True

    # NVL detection: GVL that is actually a Network Variable List
    if obj_type == TYPE_GUIDS["gvl"]:
        try:
            if is_nvl(obj):
                effective_type = TYPE_GUIDS["nvl_sender"]
                is_xml = True
        except:
            pass

    # Graphical POU detection (LD, CFC, FBD → XML)
    if not is_xml and effective_type in [TYPE_GUIDS["pou"], TYPE_GUIDS["action"], TYPE_GUIDS["method"]]:
        try:
            if is_graphical_pou(obj):
                is_xml = True
        except:
            pass

    # XML_TYPES are always XML
    if effective_type in XML_TYPES:
        is_xml = True

    # Check if type is exportable at all
    if effective_type not in EXPORTABLE_TYPES and effective_type not in XML_TYPES:
        return effective_type, is_xml, True

    return effective_type, is_xml, False
```

**Both `Project_export.py` and `codesys_compare_engine.py` will call:**

```python
effective_type, is_xml, should_skip = classify_object(obj)
if should_skip:
    continue
```

### 1.2 — `RESERVED_FILES` → `codesys_constants.py`

Move from `codesys_compare_engine.py` (line 40) and `Project_export.py` (line 45) into constants.

```python
# codesys_constants.py (add)

RESERVED_FILES = {
    "_metadata.json", "_config.json", "_metadata.csv", "BASE_DIR",
    "sync_debug.log", "compare.log", ".project", ".gitattributes",
    ".gitignore"
}
```

Both consumers import from constants instead of redeclaring.

### 1.3 — `ConfigManager.export()` → reuse `NativeManager.export()`

`ConfigManager.export()` (lines 894-968) is 90% identical to `NativeManager.export()` (lines 770-843). The only difference is `recursive=True`.

**Refactor approach:**

```python
class NativeManager(ObjectManager):
    def export(self, obj, context, recursive=False):
        # ... single implementation ...
        projects_obj.primary.export_native([obj], tmp_path, recursive=recursive)
        # ...

class ConfigManager(NativeManager):
    def export(self, obj, context):
        return super(ConfigManager, self).export(obj, context, recursive=True)
```

---

## Phase 2: Remove Metadata Files

### 2.1 — Remove `save_metadata()` from `codesys_utils.py`

Delete the `save_metadata()` function (lines 873-975).  
This function writes `_config.json` and `_metadata.csv`.

**Impact:**

- `Project_export.py` line 368 — calls `save_metadata()` → **remove**
- `codesys_compare_engine.py` line 621 — calls inside `finalize_import()` → **remove**
- `Project_compare.py` line 225 — calls `save_metadata()` after export → **remove**

### 2.2 — Remove `load_metadata()` from `codesys_utils.py`

Delete the `load_metadata()` function (lines 652-712).  
This function reads `_config.json` and `_metadata.csv`.

**Impact:**

- `Project_compare.py` line 62 — calls `load_metadata()` → **remove**
- `Project_import.py` line 55 — calls `load_metadata()` → **remove**

### 2.3 — Remove metadata dict from Manager `export()` methods

All manager `export()` methods currently write to `context['metadata']['objects'][rel_path]`.

**Replace with:** `context['exported_paths'].add(rel_path)`

Affected managers:

- `FolderManager.export()` — lines 368, 385 → add to `exported_paths`
- `POUManager.export()` — lines 459, 479 → add to `exported_paths`
- `PropertyManager.export()` — lines 612, 633 → add to `exported_paths`
- `NativeManager.export()` — lines 815, 835 → add to `exported_paths`
- `ConfigManager.export()` — lines 940, 960 → merged into NativeManager (Phase 1.3)

### 2.4 — Remove `update_object_metadata()` from `codesys_compare_engine.py`

Delete function (lines 441-467). Was used after import to update metadata entries.  
No longer needed — there is no metadata to update.

### 2.5 — Simplify `finalize_import()` in `codesys_compare_engine.py`

**Before:**

```python
def finalize_import(base_dir, metadata, project, projects_obj, ...):
    save_metadata(base_dir, metadata)  # ← REMOVE
    project.save()
    backup_project_binary(...)
```

**After:**

```python
def finalize_import(project, projects_obj, base_dir, updated_count, created_count, deleted_count=0):
    if updated_count > 0 or created_count > 0 or deleted_count > 0:
        should_save = get_project_prop("cds-sync-save-after-import", True)
        backup_binary = get_project_prop("cds-sync-backup-binary", False)
        if should_save or backup_binary:
            project.save()
            if backup_binary:
                backup_project_binary(base_dir, projects_obj)
```

### 2.6 — Remove `MetadataLock` usage

`MetadataLock` was designed to protect concurrent metadata file writes.  
Without metadata files, there is no need for file-based locking.

- `Project_export.py` line 367 — `with MetadataLock(...)` → **remove wrapper**
- `codesys_compare_engine.py` line 674 — `with MetadataLock(...)` → **remove wrapper**

Keep `MetadataLock` class in `codesys_utils.py` for now (may be useful later), but remove all call sites.

### 2.7 — Update `.gitignore` template in `ensure_git_configs()`

Remove entries for `_config.json` and `_metadata.csv` from the generated `.gitignore`.

```python
# codesys_utils.py ensure_git_configs() — remove these lines:
"_config.json",
"_metadata.csv",
```

---

## Phase 3: Simplify `Project_export.py`

### 3.1 — Remove metadata structure

**Before (lines 170-195):**

```python
metadata = {
    "project_name": ...,
    "export_timestamp": ...,
    "export_xml": ...,
    "objects": {}
}
```

**After:**

```python
export_xml = get_project_prop("cds-sync-export-xml", False)
exported_paths = set()  # For orphan cleanup
```

### 3.2 — Simplify export context

**Before:**

```python
context = {
    'export_dir': export_dir,
    'metadata': metadata,
    'property_accessors': property_accessors
}
```

**After:**

```python
context = {
    'export_dir': export_dir,
    'export_xml': export_xml,
    'property_accessors': property_accessors,
    'exported_paths': exported_paths  # set() for orphan tracking
}
```

### 3.3 — Use `classify_object()` in the export loop

**Before (lines 274-337):** ~60 lines of type classification + manager selection.

**After:**

```python
for obj in all_objects:
    effective_type, is_xml, should_skip = classify_object(obj)
    if should_skip:
        continue

    # XML gate: skip non-always-exported XML types when export_xml is off
    if is_xml and effective_type in XML_TYPES:
        always_exported = effective_type in [
            TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]
        ]
        if not always_exported and not export_xml:
            continue

    # Select manager
    if is_xml:
        manager = managers["native"] if effective_type not in managers else managers[effective_type]
    elif effective_type in managers:
        manager = managers[effective_type]
    else:
        manager = managers["default"]

    context['effective_type'] = effective_type
    result = manager.export(obj, context)
    # ... count results ...
```

### 3.4 — Remove metadata persistence block

**Remove lines 342-371:**

```python
# Phase 7: Cleanup empty folders from metadata  ← REMOVE
# ... filter metadata ...
# with MetadataLock(...):
#     save_metadata(...)
```

**Replace with:**

```python
# Orphan cleanup now uses exported_paths set directly
if not cleanup_orphaned_files(export_dir, exported_paths, silent=silent):
    return
```

### 3.5 — Remove project mismatch check (lines 196-224)

This checked `_metadata.json` for project name conflicts. Without metadata files, this is unnecessary.
The project is identified via Project Properties.

---

## Phase 4: Rewrite `codesys_compare_engine.py` — Two-Way Comparison

### 4.1 — New `find_all_changes()` signature

**Before:**

```python
def find_all_changes(base_dir, projects_obj, metadata):
```

**After:**

```python
def find_all_changes(base_dir, projects_obj, export_xml=False):
```

No metadata parameter. `export_xml` controls whether XML types are included.

### 4.2 — Two-way comparison logic

**New algorithm:**

```python
def find_all_changes(base_dir, projects_obj, export_xml=False):
    """
    Direct two-way comparison: IDE objects ↔ Disk files.

    Returns:
        {
            "different":        [{"name", "path", "type", "type_guid", "obj",
                                  "ide_content", "disk_content"}, ...],
            "new_in_ide":       [{"name", "path", "type", "type_guid", "obj"}, ...],
            "new_on_disk":      [{"name", "path", "file_path"}, ...],
            "unchanged_count":  int
        }
    """
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    property_accessors = collect_property_accessors(all_ide_objects)

    ide_paths = {}  # rel_path → obj (to match disk files later)
    different = []
    new_in_ide = []
    unchanged_count = 0

    # ── Pass 1: For each IDE object, find & compare with disk file ──
    for obj in all_ide_objects:
        effective_type, is_xml, should_skip = classify_object(obj)
        if should_skip:
            continue

        # ... XML gate (export_xml check) ...

        rel_path = build_expected_path(obj, effective_type, is_xml)
        ide_paths[rel_path] = obj

        file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))

        if os.path.exists(file_path):
            # Compare content
            ide_content = get_ide_content(obj, is_xml, property_accessors, projects_obj)
            disk_content = read_file(file_path)

            if contents_are_equal(ide_content, disk_content, is_xml):
                unchanged_count += 1
            else:
                different.append({
                    "name": obj.get_name(), "path": rel_path,
                    "type": type_name, "type_guid": effective_type,
                    "obj": obj, "ide_content": ide_content, "disk_content": disk_content
                })
        else:
            new_in_ide.append({
                "name": obj.get_name(), "path": rel_path,
                "type": type_name, "type_guid": effective_type, "obj": obj
            })

    # ── Pass 2: Walk disk, find files not matching any IDE object ──
    new_on_disk = scan_new_disk_files(base_dir, ide_paths)

    return {
        "different": different,
        "new_in_ide": new_in_ide,
        "new_on_disk": new_on_disk,
        "unchanged_count": unchanged_count
    }
```

### 4.3 — Extract helpers

New helper functions needed in the rewritten engine:

```python
def build_expected_path(obj, effective_type, is_xml):
    """Build the expected rel_path for an IDE object."""
    # Move path-building logic here (currently duplicated in find_all_changes lines 124-145)
    ...

def get_ide_content(obj, is_xml, property_accessors, projects_obj):
    """Extract content from IDE object for comparison."""
    ...

def contents_are_equal(ide_content, disk_content, is_xml):
    """Compare two content strings, with XML-specific filtering."""
    ...
```

### 4.4 — Simplify `scan_new_disk_files()`

**Before:** takes `disk_objects` (metadata dict)
**After:** takes `ide_paths` (set of rel_paths from IDE)

```python
def scan_new_disk_files(base_dir, ide_paths):
    """Walk disk, find .st/.xml files not matching any IDE object path."""
    known_paths = set(ide_paths.keys())
    # ... rest is the same ...
```

### 4.5 — Simplify `perform_import_items()`

- Remove `update_object_metadata()` calls
- Remove metadata parameter
- Remove `MetadataLock` wrapper
- `finalize_import()` only saves project + optional backup

**Before:**

```python
def perform_import_items(primary_project, base_dir, to_sync, metadata, globals_ref=None):
```

**After:**

```python
def perform_import_items(primary_project, base_dir, to_sync, globals_ref=None):
```

---

## Phase 5: Update Consumers

### 5.1 — `Project_compare.py`

```python
def compare_project(projects_obj=None, silent=False):
    # ...
    # REMOVE: metadata = load_metadata(base_dir)
    export_xml = get_project_prop("cds-sync-export-xml", False)

    results = find_all_changes(base_dir, projects_obj, export_xml)

    # Changed: "modified" → "different" (no direction)
    different = results["different"]
    new_in_ide = results["new_in_ide"]
    new_on_disk = results["new_on_disk"]
    unchanged_count = results["unchanged_count"]

    # "deleted_from_ide" — REMOVED (covered by new_on_disk)
    # Direction arrows — REMOVED (just "Different")
```

**UI change:**

```
Before:  M IDE>   M DISK>   M BOTH>
After:   M        (Modified — IDE and Disk differ)
```

Simplify `CompareResultsForm`:

- Remove `ide_changes` / `disk_changes` / `both_changes` split
- Single "Modified (IDE ≠ Disk)" section
- Remove `deleted_from_ide` section (merged into `new_on_disk`)

### 5.2 — `Project_import.py`

```python
def import_project(projects_obj=None, silent=False):
    # ...
    # REMOVE: metadata = load_metadata(base_dir)
    export_xml = get_project_prop("cds-sync-export-xml", False)

    results = find_all_changes(base_dir, projects_obj, export_xml)

    different = results["different"]
    new_on_disk = results["new_on_disk"]

    to_import = different + [convert_new_on_disk(item) for item in new_on_disk]

    # REMOVE: metadata parameter
    updated, created, failed = perform_import_items(
        projects_obj.primary, base_dir, to_import, globals()
    )
```

### 5.3 — `perform_export()` in `Project_compare.py`

This function is called when user clicks "Export to Disk" in compare UI.  
Simplify: no metadata parameter, no `save_metadata()` call.

```python
def perform_export(base_dir, selected, new_in_ide):
    # ... export selected objects ...
    # REMOVE: save_metadata(base_dir, metadata)
    system.ui.info("Exported " + str(count) + " objects.")
```

---

## Phase 6: Cleanup

### 6.1 — Remove dead code from `codesys_utils.py`

- [ ] Remove `save_metadata()` function
- [ ] Remove `load_metadata()` function
- [ ] Remove CSV imports (`import csv`) if no longer used
- [ ] Keep `MetadataLock` class (may reuse as general sync lock later)
- [ ] Remove `_config.json` / `_metadata.csv` from `.gitignore` template

### 6.2 — Remove dead code from `codesys_compare_engine.py`

- [ ] Remove `update_object_metadata()` function
- [ ] Remove `TYPE_NAMES` reverse map (if UI no longer needs type→name mapping for direction)
- [ ] Simplify `finalize_import()` — remove metadata save, keep project save only

### 6.3 — Remove dead code from `codesys_managers.py`

- [ ] Remove all `context['metadata']['objects'][rel_path] = {...}` blocks from `export()` methods
- [ ] Replace with `context['exported_paths'].add(rel_path)`

### 6.4 — Remove files from reference project

- [ ] Delete `cds-text-sync-reference-project/_config.json`
- [ ] Delete `cds-text-sync-reference-project/_metadata.csv`

### 6.5 — Update `CompareResultsForm` in `codesys_ui.py`

- [ ] Merge `ide_changes` / `disk_changes` / `both_changes` → single `different` list
- [ ] Remove `deleted_from_ide` section (now just "new on disk")
- [ ] Simplify tag display: `M` instead of `M IDE> / M DISK> / M BOTH>`

---

## Execution Order

```
Phase 1.1  classify_object()          ← no behavior change, safe to apply first
Phase 1.2  RESERVED_FILES             ← no behavior change
Phase 1.3  ConfigManager simplify     ← no behavior change
  ↓ test export/compare/import still work identically ↓
Phase 2.3  Manager export() cleanup   ← add exported_paths, keep metadata (both)
Phase 3.*  Project_export.py          ← stop writing metadata files
  ↓ test: export works, files no longer written ↓
Phase 4.*  compare_engine rewrite     ← new 2-way comparison
Phase 5.*  Consumer updates           ← compare/import/UI simplified
  ↓ test: full compare/import cycle works ↓
Phase 2.1  Remove save_metadata()     ← dead code removal
Phase 2.2  Remove load_metadata()     ← dead code removal
Phase 6.*  Final cleanup              ← remove all dead code & files
```

---

## Risk Assessment

| Risk                                                       | Mitigation                                                         |
| ---------------------------------------------------------- | ------------------------------------------------------------------ |
| Export counts (new/updated/identical) become less accurate | Managers already check file content on disk — no change            |
| Orphan cleanup breaks                                      | `exported_paths` set replaces metadata dict — equivalent           |
| Import fails without metadata hash                         | Import already uses `force=True` — bypasses hash check             |
| Compare UI loses direction info                            | Acceptable trade-off. User sees "Different" and clicks Diff button |
| `Project_directory.py` metadata mismatch check             | Remove — project identity comes from Project Properties            |
| Reference project breaks                                   | Delete `_config.json` + `_metadata.csv` from reference             |

---

## Files Modified (Summary)

| File                        | Action                                                                                                                                   |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `codesys_constants.py`      | Add `RESERVED_FILES`                                                                                                                     |
| `codesys_managers.py`       | Add `classify_object()`, simplify `ConfigManager`, remove metadata dict writes                                                           |
| `codesys_utils.py`          | Remove `save_metadata()`, `load_metadata()`, update `.gitignore` template                                                                |
| `codesys_compare_engine.py` | Rewrite `find_all_changes()` (2-way), remove `update_object_metadata()`, simplify `finalize_import()`, simplify `perform_import_items()` |
| `Project_export.py`         | Remove metadata structure/persistence, use `classify_object()`, use `exported_paths` set                                                 |
| `Project_compare.py`        | Remove `load_metadata()`, update to new `find_all_changes()` API, simplify UI calls                                                      |
| `Project_import.py`         | Remove `load_metadata()`, update to new API                                                                                              |
| `codesys_ui.py`             | Simplify `CompareResultsForm` sections                                                                                                   |
| `_config.json`              | **DELETE** from reference project                                                                                                        |
| `_metadata.csv`             | **DELETE** from reference project                                                                                                        |
