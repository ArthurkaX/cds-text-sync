# -*- coding: utf-8 -*-
"""
Project_perf_test.py - Performance Profiling for CODESYS Text Sync

Measures and reports performance metrics for the compare engine,
helping identify bottlenecks and optimization opportunities.
"""

import os
import sys
import time
import codecs
import json
import tempfile
import collections
import subprocess
import imp
from collections import defaultdict

# --- Hidden Module Loader ---
def _load_hidden_module(name):
    """Load a .pyw module from the script directory and register it in sys.modules."""
    if name not in sys.modules:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, name + ".pyw")
        if os.path.exists(path):
            sys.modules[name] = imp.load_source(name, path)

# Force reload of shared modules
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

_load_hidden_module("codesys_constants")
_load_hidden_module("codesys_utils")
_load_hidden_module("codesys_managers")
_load_hidden_module("codesys_compare_engine")

from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, IMPLEMENTATION_TYPES, TYPE_NAMES, SCRIPT_VERSION
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_error, log_warning,
    resolve_projects, clean_filename, get_project_prop, calculate_hash
)
from codesys_managers import (
    collect_property_accessors, classify_object, build_expected_path, export_object_content,
    format_st_content, format_property_content, NativeManager
)


# ═══════════════════════════════════════════════════════════════════
#  PROFILER CLASS
# ═══════════════════════════════════════════════════════════════════

class PerformanceProfiler:
    """Tracks and reports performance metrics (anonymous mode only)."""
    
    def __init__(self):
        self.timings = {}
        self.counters = defaultdict(int)
        self.per_type_stats = defaultdict(lambda: {
            "total": 0.0, 
            "count": 0, 
            "max": 0.0, 
            "slow_times": []
        })
        self.environment = {}
        self.object_counts = defaultdict(int)
        
    def start(self, name):
        """Start timing a section."""
        self.timings[name] = {"start": time.time()}
        
    def end(self, name):
        """End timing a section."""
        if name in self.timings:
            self.timings[name]["elapsed"] = time.time() - self.timings[name]["start"]
            self.counters[name] += 1
            
    def track_object(self, obj_type, category, elapsed):
        """Track individual object processing time (anonymous - no paths stored).
        
        Args:
            obj_type: Object type name (e.g. 'pou', 'gvl', 'dut')
            category: Measurement category (e.g. 'ST extract', 'classify', 'compare')
            elapsed: Time in seconds
        """
        key = obj_type + " " + category
        self.per_type_stats[key]["total"] += elapsed
        self.per_type_stats[key]["count"] += 1
        if elapsed > self.per_type_stats[key]["max"]:
            self.per_type_stats[key]["max"] = elapsed
        if elapsed > 0.05:  # Track objects that take >50ms for percentile analysis
            self.per_type_stats[key]["slow_times"].append(elapsed)
    
    def count_object(self, obj_type):
        """Count objects by type."""
        self.object_counts[obj_type] += 1
            
    def get_report(self):
        """Generate performance report (anonymous)."""
        total_time = sum(t.get("elapsed", 0) for t in self.timings.values())
        
        report = {
            "total_time_sec": total_time,
            "environment": self.environment,
            "sections": {},
            "object_stats": {},
            "object_counts": dict(self.object_counts)
        }
        
        # Section timings
        for name, data in self.timings.items():
            if "elapsed" in data:
                pct = (data["elapsed"] / total_time * 100) if total_time > 0 else 0
                report["sections"][name] = {
                    "elapsed_sec": data["elapsed"],
                    "percent": pct
                }
        
        # Per-type statistics
        for key, stats in self.per_type_stats.items():
            avg = stats["total"] / stats["count"] if stats["count"] > 0 else 0
            stats_data = {
                "count": stats["count"],
                "total_sec": stats["total"],
                "avg_sec": avg,
                "max_sec": stats["max"]
            }
            if stats["slow_times"] and len(stats["slow_times"]) >= 5:
                sorted_slow = sorted(stats["slow_times"])
                p90_idx = int(len(sorted_slow) * 0.9)
                stats_data["p90_sec"] = sorted_slow[p90_idx]
            report["object_stats"][key] = stats_data
        
        return report
    
    def get_text_report(self, processed_count=0, active_count=0):
        """Generate formatted text report as string."""
        report = self.get_report()
        total = report["total_time_sec"]
        env = report.get("environment", {})
        
        lines = []
        lines.append("")
        lines.append("=" * 74)
        lines.append("PERFORMANCE ANALYSIS REPORT (Anonymous)")
        lines.append("=" * 74)
        
        # ── Environment ──
        lines.append("  Date       : " + env.get("timestamp", "N/A"))
        lines.append("  PC         : " + env.get("hostname", "N/A"))
        lines.append("  Script     : v" + env.get("script_version", "N/A"))
        lines.append("  export_xml : " + str(env.get("export_xml", "N/A")))
        lines.append("-" * 74)
        
        # ── Key Metrics (easy to compare) ──
        lines.append("KEY METRICS:")
        lines.append("  Total objects in project : {}".format(env.get("total_objects", "?")))
        lines.append("  Active (not skipped)     : {}".format(active_count))
        lines.append("  Total time               : {:.2f}s".format(total))
        if active_count > 0:
            ide_loop = report["sections"].get("IDE comparison loop", {}).get("elapsed_sec", 0)
            avg = ide_loop / active_count if ide_loop > 0 else 0
            lines.append("  Avg per active object    : {:.3f}s".format(avg))
            lines.append("  Projected 500 objects    : {:.1f}s".format(avg * 500))
            lines.append("  Projected 1000 objects   : {:.1f}s".format(avg * 1000))
        lines.append("=" * 74)
        
        # ── Section Breakdown ──
        lines.append("")
        lines.append("SECTIONS (sorted by time):")
        lines.append("-" * 74)
        for i, (name, data) in enumerate(sorted(report["sections"].items(),
                                              key=lambda x: x[1]["elapsed_sec"],
                                              reverse=True), 1):
            bar_len = int(data["percent"] / 2)
            bar = "█" * bar_len
            lines.append("  {:2d}. {:40s} {:7.2f}s ({:5.1f}%) {}".format(
                i, name[:40], data["elapsed_sec"], data["percent"], bar))
        
        # ── Unaccounted time ──
        ide_loop_time = report["sections"].get("IDE comparison loop", {}).get("elapsed_sec", 0)
        tracked_in_loop = sum(
            s["total_sec"] for s in report["object_stats"].values()
        )
        unaccounted = ide_loop_time - tracked_in_loop
        if ide_loop_time > 0:
            unaccounted_pct = (unaccounted / ide_loop_time * 100)
            lines.append("")
            lines.append("  IDE loop breakdown:")
            lines.append("    Tracked object time    : {:7.2f}s".format(tracked_in_loop))
            lines.append("    Unaccounted (overhead)  : {:7.2f}s ({:.1f}%)".format(
                unaccounted, unaccounted_pct))
            lines.append("    (path building, file existence checks, dict ops, iteration)")
        
        # ── Object Counts ──
        obj_counts = report.get("object_counts", {})
        if obj_counts:
            lines.append("")
            lines.append("OBJECT COUNTS BY TYPE:")
            lines.append("-" * 74)
            for type_name, count in sorted(obj_counts.items(), key=lambda x: x[1], reverse=True):
                lines.append("  {:30s} {:5d}".format(type_name, count))
        
        # ── Object Type Statistics ──
        # Group by category (extract, classify, compare, etc.)
        categories = defaultdict(list)
        for key, stats in report["object_stats"].items():
            # key format: "type_name category" e.g. "pou ST extract"
            parts = key.rsplit(" ", 1)
            if len(parts) == 2:
                categories[parts[1]].append((parts[0], stats))
            else:
                categories["other"].append((key, stats))
        
        for category in ["classify", "extract", "compare", "disk_read", "XML export", "other"]:
            items = categories.get(category, [])
            if not items:
                continue
            items.sort(key=lambda x: x[1]["avg_sec"], reverse=True)
            
            lines.append("")
            lines.append("OBJECT DETAILS — {} (by avg time):".format(category.upper()))
            lines.append("-" * 74)
            lines.append("  {:22s} {:>5s}  {:>7s}  {:>7s}  {:>7s}  {:>6s}".format(
                "Type", "Count", "Total", "Avg", "Max", "P90"))
            lines.append("  " + "-" * 68)
            for obj_type, stats in items:
                p90_str = "{:5.3f}s".format(stats.get("p90_sec", 0)) if "p90_sec" in stats else "  N/A "
                lines.append("  {:22s} {:5d}  {:6.2f}s  {:5.3f}s  {:5.3f}s  {}".format(
                    obj_type[:22],
                    stats["count"],
                    stats["total_sec"],
                    stats["avg_sec"],
                    stats["max_sec"],
                    p90_str
                ))
            cat_total = sum(s["total_sec"] for _, s in items)
            cat_count = sum(s["count"] for _, s in items)
            lines.append("  {:22s} {:5d}  {:6.2f}s".format("SUBTOTAL", cat_count, cat_total))
        
        return "\n".join(lines) + "\n"
    
    def get_insights_text(self, processed_count=0, active_count=0):
        """Generate insights section as string."""
        report = self.get_report()
        total = report["total_time_sec"]
        
        lines = []
        lines.append("=" * 74)
        lines.append("PERFORMANCE INSIGHTS:")
        lines.append("=" * 74)
        
        # Find SLOWEST SECTION
        sorted_sections = sorted(report["sections"].items(),
                              key=lambda x: x[1]["elapsed_sec"],
                              reverse=True)
        if sorted_sections:
            slowest_name, slowest_data = sorted_sections[0]
            slowest_pct = slowest_data["percent"]
            lines.append("⚠ MAIN BOTTLENECK: '{}' — {:.1f}% of total time ({:.2f}s)".format(
                slowest_name, slowest_pct, slowest_data["elapsed_sec"]))
            
            if "IDE comparison loop" in slowest_name:
                # Break down where time goes inside the loop
                extract_total = sum(
                    s["total_sec"] for k, s in report["object_stats"].items() if "extract" in k
                )
                classify_total = sum(
                    s["total_sec"] for k, s in report["object_stats"].items() if "classify" in k
                )
                compare_total = sum(
                    s["total_sec"] for k, s in report["object_stats"].items() if "compare" in k
                )
                xml_total = sum(
                    s["total_sec"] for k, s in report["object_stats"].items() if "XML export" in k
                )
                disk_total = sum(
                    s["total_sec"] for k, s in report["object_stats"].items() if "disk_read" in k
                )
                
                loop_time = slowest_data["elapsed_sec"]
                lines.append("  Loop time decomposition:")
                if classify_total > 0.1:
                    lines.append("    classify_object  : {:6.2f}s ({:4.1f}%)".format(
                        classify_total, classify_total / loop_time * 100))
                if extract_total > 0.1:
                    lines.append("    ST extraction    : {:6.2f}s ({:4.1f}%)".format(
                        extract_total, extract_total / loop_time * 100))
                if xml_total > 0.1:
                    lines.append("    XML export       : {:6.2f}s ({:4.1f}%)".format(
                        xml_total, xml_total / loop_time * 100))
                if compare_total > 0.1:
                    lines.append("    comparison       : {:6.2f}s ({:4.1f}%)".format(
                        compare_total, compare_total / loop_time * 100))
                if disk_total > 0.1:
                    lines.append("    disk read        : {:6.2f}s ({:4.1f}%)".format(
                        disk_total, disk_total / loop_time * 100))
            
            # Secondary bottlenecks (>10% of time)
            for i in range(1, len(sorted_sections)):
                if sorted_sections[i][1]["percent"] > 10:
                    lines.append("")
                    lines.append("⚠ SECONDARY BOTTLENECK: '{}' — {:.1f}% ({:.2f}s)".format(
                        sorted_sections[i][0],
                        sorted_sections[i][1]["percent"],
                        sorted_sections[i][1]["elapsed_sec"]))
        
        # Slowest classify calls (reveals is_nvl overhead)
        classify_stats = {k: v for k, v in report["object_stats"].items() if "classify" in k}
        if classify_stats:
            slowest_classify = max(classify_stats.items(), key=lambda x: x[1]["avg_sec"])
            if slowest_classify[1]["avg_sec"] > 0.005:
                lines.append("")
                lines.append("⚠ SLOW CLASSIFICATION: '{}' — {:.3f}s avg ({:.2f}s total, {} objects)".format(
                    slowest_classify[0],
                    slowest_classify[1]["avg_sec"],
                    slowest_classify[1]["total_sec"],
                    slowest_classify[1]["count"]))
                if "gvl" in slowest_classify[0].lower():
                    lines.append("  → Likely caused by is_nvl() doing native XML export for each GVL")
        
        lines.append("")
        lines.append("=" * 74)
        lines.append("This report is anonymous — no object names or paths included.")
        lines.append("Feel free to share this for performance analysis!")
        lines.append("=" * 74)
        
        return "\n".join(lines) + "\n"
    
    def print_report(self, processed_count=0, active_count=0):
        """Print formatted report to console."""
        print(self.get_text_report(processed_count, active_count))
        print(self.get_insights_text(processed_count, active_count))


# ═══════════════════════════════════════════════════════════════════
#  CONTENT EXTRACTION (copied from compare_engine for profiling)
# ═══════════════════════════════════════════════════════════════════

import tempfile

def get_ide_content_profiling(obj, is_xml, property_accessors, projects_obj, 
                              can_have_impl=False, profiler=None):
    """Extract content from IDE object for comparison (with profiling)."""
    
    obj_name = obj.get_name() if obj else "Unknown"
    obj_type = safe_str(obj.type)
    obj_type_name = TYPE_NAMES.get(obj_type, obj_type[:8])
    
    if is_xml:
        clean_name = clean_filename(obj_name)
        tmp_path = os.path.join(tempfile.gettempdir(), "cds_comp_" + clean_name + ".xml")
        start = time.time()
        try:
            monolithic_types = [
                TYPE_GUIDS["task_config"], TYPE_GUIDS["alarm_config"], 
                TYPE_GUIDS["visu_manager"], TYPE_GUIDS["softmotion_pool"]
            ]
            recursive = obj_type in monolithic_types
            
            if obj_type == TYPE_GUIDS["device"]:
                from codesys_utils import is_container_device
                recursive = not is_container_device(obj)
            
            projects_obj.primary.export_native([obj], tmp_path, recursive=recursive)
            export_time = time.time() - start
            
            if profiler:
                profiler.track_object(obj_type_name, "XML export", export_time)
            
            content = read_file(tmp_path)
            os.remove(tmp_path)
            return content
        except:
            return ""
    
    # ST content
    obj_guid = safe_str(obj.guid)
    
    start = time.time()
    
    if obj_type == TYPE_GUIDS["property"] and obj_guid in property_accessors:
        prop_data = property_accessors[obj_guid]
        declaration, _ = export_object_content(obj)

        get_impl = None
        if prop_data['get']:
            get_decl, get_impl_raw = export_object_content(prop_data['get'])
            get_impl = format_st_content(get_decl, get_impl_raw, False)

        set_impl = None
        if prop_data['set']:
            set_decl, set_impl_raw = export_object_content(prop_data['set'])
            set_impl = format_st_content(set_decl, set_impl_raw, False)

        result = format_property_content(declaration, get_impl, set_impl)
    else:
        declaration, implementation = export_object_content(obj)
        result = format_st_content(declaration, implementation, can_have_impl)
    
    st_extract_time = time.time() - start
    
    if profiler:
        profiler.track_object(obj_type_name, "extract", st_extract_time)
    
    return result


def read_file(file_path):
    """Read file content as UTF-8."""
    if not os.path.exists(file_path):
        return ""
    try:
        with codecs.open(file_path, "r", "utf-8") as f:
            return f.read()
    except:
        return ""


# ═══════════════════════════════════════════════════════════════════
#  MAIN PROFILING FUNCTION
# ═══════════════════════════════════════════════════════════════════

def run_speed_analysis():
    """Run complete performance analysis of the compare engine."""
    
    print("=" * 70)
    print("SPEED MEASURE: cds-text-sync Performance Analyzer")
    print("=" * 70)
    
    projects_obj = resolve_projects(None, globals())
    
    if projects_obj is None or not projects_obj.primary:
        msg = "Error: 'projects' object not found or no project open."
        system.ui.error(msg)
        return
    
    base_dir, error = load_base_dir()
    if error:
        system.ui.warning(error)
        return
    
    export_xml = get_project_prop("cds-sync-export-xml", False)
    
    profiler = PerformanceProfiler()
    
    # ── Environment info ──
    try:
        hostname = socket.gethostname()
    except:
        hostname = "unknown"
    
    profiler.environment = {
        "hostname": hostname,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "script_version": SCRIPT_VERSION,
        "export_xml": export_xml,
    }
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 1: Collect all IDE objects
    # ═══════════════════════════════════════════════════════════════════
    print("\n[1/5] Collecting IDE objects...")
    profiler.start("get_children(recursive)")
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    profiler.end("get_children(recursive)")
    profiler.environment["total_objects"] = len(all_ide_objects)
    print("  Found {} objects".format(len(all_ide_objects)))
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 2: Load Cache & Prepare Pass 1
    # ═══════════════════════════════════════════════════════════════════
    from codesys_utils import load_sync_cache, normalize_path
    cache_data = load_sync_cache(base_dir)
    cached_types = cache_data.get("types", {})
    cached_objects = cache_data.get("objects", {})
    cached_folders = cache_data.get("folders", {})
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 3: Process each IDE object (Optimized Pass 1)
    # ═══════════════════════════════════════════════════════════════════
    print("\n[3/5] Processing IDE objects (Optimized Pass 1)...")
    profiler.start("IDE comparison loop")
    
    ide_paths = {}
    ide_hashes = {}
    ide_metadata = {}
    property_accessors = {}
    processed_count = 0
    skipped_count = 0
    xml_count = 0
    st_count = 0
    active_count = 0
    compared_count = 0
    path_cache_hits = 0
    type_cache_hits = 0
    
    # Instantiate NativeManager once for XML comparison
    native_mgr = NativeManager()
    
    for obj in all_ide_objects:
        processed_count += 1
        obj_guid = safe_str(obj.guid)
        
        # Progress indicator every 100 objects
        if processed_count % 100 == 0:
            print("  Progress: {}/{} objects scanned".format(processed_count, len(all_ide_objects)))
        
        # ── Profile classify_object ──
        t_classify = time.time()
        if obj_guid in cached_types:
            type_info = cached_types[obj_guid]
            effective_type, is_xml = type_info[0], type_info[1]
            rel_path = type_info[2] if len(type_info) > 2 else None
            should_skip = False
            type_cache_hits += 1
        else:
            effective_type, is_xml, should_skip = classify_object(obj)
            rel_path = None
            
        classify_elapsed = time.time() - t_classify
        type_name = TYPE_NAMES.get(effective_type, effective_type[:8])
        profiler.track_object(type_name, "classify", classify_elapsed)
        
        if should_skip:
            skipped_count += 1
            continue

        active_count += 1
        profiler.count_object(type_name)
        
        # ── Profile Path Building ──
        t_path = time.time()
        if not rel_path:
            rel_path = build_expected_path(obj, effective_type, is_xml)
        else:
            path_cache_hits += 1
        path_elapsed = time.time() - t_path
        profiler.track_object(type_name, "path_building", path_elapsed)
        
        if not rel_path: continue
        
        norm_path = normalize_path(rel_path)
        ide_paths[rel_path] = obj
        ide_metadata[norm_path] = (effective_type, is_xml)

        # Optimization: Property accessors
        if effective_type == TYPE_GUIDS["property"]:
            try:
                if obj_guid not in property_accessors:
                    property_accessors[obj_guid] = {'get': None, 'set': None}
                for child in obj.get_children():
                    child_name = child.get_name().upper()
                    if child_name == "GET": property_accessors[obj_guid]['get'] = child
                    elif child_name == "SET": property_accessors[obj_guid]['set'] = child
            except:
                pass

        if is_xml: xml_count += 1
        else: st_count += 1
        
    profiler.end("IDE comparison loop")
    print("  Pass 1 complete ({} active, {} type hits, {} path hits)".format(
        active_count, type_cache_hits, path_cache_hits))

    # Merkle Tree Profile
    print("\n[3.5/5] Building Merkle Tree...")
    profiler.start("merkle_tree_building")
    from codesys_utils import build_folder_hashes
    # (Mocking object hashes for Merkle profile based on metadata)
    ide_folder_hashes = build_folder_hashes({p: "hash" for p in ide_metadata.keys()})
    profiler.end("merkle_tree_building")

    # ═══════════════════════════════════════════════════════════════════
    #  STEP 4: Compare (Pass 2 & Merkle Skip)
    # ═══════════════════════════════════════════════════════════════════
    print("\n[4/5] Second Pass: Comparison & Merkle Skip...")
    profiler.start("comparison_pass")
    
    for rel_path, obj in ide_paths.items():
        norm_path = normalize_path(rel_path)
        eff_type, is_xml = ide_metadata[norm_path]
        file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
        type_name = TYPE_NAMES.get(eff_type, eff_type[:8])
        
        # ── Fast path 1: Folder-level check (Merkle Skip) ──
        parent_folder = "/".join(norm_path.split("/")[:-1])
        if parent_folder and parent_folder in ide_folder_hashes and parent_folder in cached_folders:
            if ide_folder_hashes[parent_folder] == cached_folders[parent_folder]:
                # Merkle hit! (In reality we'd still check disk mtime, but for profiling we skip)
                continue

        # ── Full Comparison (if not skipped) ──
        if os.path.exists(file_path):
            t_compare = time.time()
            can_have_impl = eff_type in IMPLEMENTATION_TYPES
            ide_content = get_ide_content_profiling(
                obj, is_xml, property_accessors, projects_obj, can_have_impl, profiler
            )
            compare_elapsed = time.time() - t_compare
            profiler.track_object(type_name, "compare", compare_elapsed)
            compared_count += 1
    
    profiler.end("comparison_pass")
    print("  Pass 2 complete (compared {} objects)".format(compared_count))
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 4: Scan disk files
    # ═══════════════════════════════════════════════════════════════════
    print("\n[4/5] Scanning disk files...")
    profiler.start("scan_new_disk_files")
    
    from codesys_constants import RESERVED_FILES
    known_paths = set(ide_paths.keys())
    new_files_count = 0
    
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        
        for f in files:
            if f.endswith(".st") or f.endswith(".xml"):
                if f in RESERVED_FILES or f.startswith("."):
                    continue
                new_files_count += 1
    
    profiler.end("scan_new_disk_files")
    print("  Scanned {} files".format(new_files_count))
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 5: Generate and save report
    # ═══════════════════════════════════════════════════════════════════
    print("\n[5/5] Generating report...")
    
    profiler.print_report(processed_count, active_count)
    
    # Save reports (both JSON and TXT)
    report = profiler.get_report()
    report["summary"] = {
        "processed_count": processed_count,
        "active_count": active_count,
        "skipped_count": skipped_count,
        "xml_count": xml_count,
        "st_count": st_count,
        "compared_count": compared_count
    }
    
    # Save JSON report
    json_path = os.path.join(base_dir, "performance_report.json")
    try:
        with codecs.open(json_path, "w", "utf-8") as f:
            json.dump(report, f, indent=2)
        print("\nJSON report saved to: " + json_path)
    except Exception as e:
        print("\nWarning: Could not save JSON report: " + safe_str(e))
    
    # Save text report (full report including insights)
    txt_path = os.path.join(base_dir, "performance_report.txt")
    try:
        text_report = profiler.get_text_report(processed_count, active_count)
        insights_report = profiler.get_insights_text(processed_count, active_count)
        with codecs.open(txt_path, "w", "utf-8") as f:
            f.write(text_report)
            f.write(insights_report)
        print("Text report saved to: " + txt_path)
    except Exception as e:
        print("\nWarning: Could not save text report: " + safe_str(e))

    # Append to CSV history
    append_to_csv(base_dir, report, report["summary"])


def append_to_csv(base_dir, report, summary):
    """Append performance metrics to CSV history file."""
    import csv
    
    # Use centralized location for CSV
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "Performance_tests", "performance_history.csv")
    
    # Ensure directory exists
    csv_dir = os.path.dirname(csv_path)
    if not os.path.exists(csv_dir):
        try:
            os.makedirs(csv_dir)
        except:
            pass
    
    # Get git info
    git_commit = ""
    git_message = ""
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=script_dir
        ).decode().strip()
        git_message = subprocess.check_output(
            ["git", "log", "-1", "--format=%s"],
            cwd=script_dir
        ).decode().strip()
    except:
        pass
    
    # Extract key metrics
    env = report.get("environment", {})
    sections = report.get("sections", {})
    object_stats = report.get("object_stats", {})
    
    # Calculate breakdown totals
    classify_total = sum(s["total_sec"] for k, s in object_stats.items() if "classify" in k)
    extract_total = sum(s["total_sec"] for k, s in object_stats.items() if "extract" in k)
    xml_total = sum(s["total_sec"] for k, s in object_stats.items() if "XML export" in k)
    compare_total = sum(s["total_sec"] for k, s in object_stats.items() if "compare" in k)
    disk_total = sum(s["total_sec"] for k, s in object_stats.items() if "disk_read" in k)
    
    ide_loop_time = sections.get("IDE comparison loop", {}).get("elapsed_sec", 0)
    unaccounted = ide_loop_time - (classify_total + extract_total + xml_total + compare_total + disk_total)
    
    # Get GVL-specific stats
    gvl_stats = object_stats.get("gvl classify", {})
    gvl_avg = gvl_stats.get("avg_sec", 0)
    gvl_count = gvl_stats.get("count", 0)
    
    # Build row
    row = {
        "timestamp": env.get("timestamp", ""),
        "git_commit": git_commit,
        "git_message": git_message[:30] + "..." if len(git_message) > 30 else git_message,
        "pc_name": env.get("hostname", ""),
        "script_version": "v" + str(env.get("script_version", "")),
        "export_xml": str(env.get("export_xml", "")),
        "total_objects": env.get("total_objects", ""),
        "active_objects": summary.get("active_count", ""),
        "total_time_sec": report.get("total_time_sec", ""),
        "ide_loop_time_sec": sections.get("IDE comparison loop", {}).get("elapsed_sec", ""),
        "collect_property_sec": sections.get("collect_property_accessors", {}).get("elapsed_sec", ""),
        "classify_total_sec": classify_total,
        "extract_total_sec": extract_total,
        "xml_export_total_sec": xml_total,
        "compare_total_sec": compare_total,
        "disk_read_total_sec": disk_total,
        "unaccounted_sec": unaccounted,
        "gvl_classify_avg_sec": gvl_avg,
        "gvl_count": gvl_count,
        "notes": ""
    }
    
    # Write to CSV (create if not exists, append otherwise)
    file_exists = os.path.exists(csv_path)
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        print("\nCSV history updated: " + csv_path)
    except Exception as e:
        print("\nWarning: Could not write to CSV history: " + str(e))


def main():
    """Main entry point."""
    try:
        run_speed_analysis()
    except Exception as e:
        print("\nERROR: " + safe_str(e))
        import traceback
        traceback.print_exc()
        system.ui.error("Speed analysis failed: " + safe_str(e))


if __name__ == "__main__":
    main()
