# -*- coding: utf-8 -*-
"""
Project_speed_measure.py - Performance Analyzer for cds-text-sync (Anonymous)

Measures execution time of key methods in compare engine to identify
performance bottlenecks, especially for large projects (500+ objects).

⚠ IMPORTANT: This script generates ANONYMOUS reports only.
No object names, paths, or project-specific data is included.
Reports can be safely shared for performance analysis.

Usage: Run this script to get a detailed performance breakdown of:
- IDE object collection
- Property accessor collection  
- Per-object comparison (get_ide_content, contents_are_equal)
- Disk scanning

Output files in sync folder:
• performance_report.txt - Human-readable text report (full)
• performance_report.json - Machine-readable JSON report

Report structure:
• SLOWEST ACTIONS (Performance Bottlenecks): Sections sorted by time
• SLOWEST OBJECT TYPES: Object types sorted by average processing time
• PERFORMANCE INSIGHTS: Analysis and recommendations
"""
import os
import sys
import time
import imp
import json
import codecs
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

from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, IMPLEMENTATION_TYPES, TYPE_NAMES
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_error, log_warning,
    resolve_projects, clean_filename, get_project_prop
)
from codesys_managers import (
    collect_property_accessors, classify_object, build_expected_path, export_object_content,
    format_st_content, format_property_content
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
        
    def start(self, name):
        """Start timing a section."""
        self.timings[name] = {"start": time.time()}
        
    def end(self, name):
        """End timing a section."""
        if name in self.timings:
            self.timings[name]["elapsed"] = time.time() - self.timings[name]["start"]
            self.counters[name] += 1
            
    def track_object(self, rel_path, obj_type, elapsed):
        """Track individual object processing time (anonymous - no paths stored)."""
        self.per_type_stats[obj_type]["total"] += elapsed
        self.per_type_stats[obj_type]["count"] += 1
        if elapsed > self.per_type_stats[obj_type]["max"]:
            self.per_type_stats[obj_type]["max"] = elapsed
        if elapsed > 0.05:  # Track objects that take >50ms for percentile analysis
            self.per_type_stats[obj_type]["slow_times"].append(elapsed)
            
    def get_report(self):
        """Generate performance report (anonymous - no object paths)."""
        total_time = sum(t.get("elapsed", 0) for t in self.timings.values())
        
        report = {
            "total_time_sec": total_time,
            "sections": {},
            "object_stats": {}
        }
        
        # Section timings - focus on SLOWEST ACTIONS
        for name, data in self.timings.items():
            if "elapsed" in data:
                pct = (data["elapsed"] / total_time * 100) if total_time > 0 else 0
                report["sections"][name] = {
                    "elapsed_sec": data["elapsed"],
                    "percent": pct
                }
        
        # Per-type statistics
        for obj_type, stats in self.per_type_stats.items():
            avg = stats["total"] / stats["count"] if stats["count"] > 0 else 0
            stats_data = {
                "count": stats["count"],
                "total_sec": stats["total"],
                "avg_sec": avg,
                "max_sec": stats["max"]
            }
            # Add percentile if we have enough slow samples
            if stats["slow_times"] and len(stats["slow_times"]) >= 5:
                sorted_slow = sorted(stats["slow_times"])
                p90_idx = int(len(sorted_slow) * 0.9)
                stats_data["p90_sec"] = sorted_slow[p90_idx]
            report["object_stats"][obj_type] = stats_data
        
        return report
    
    def get_text_report(self, processed_count=0):
        """Generate formatted text report as string (anonymous - focuses on slowest actions)."""
        report = self.get_report()
        total = report["total_time_sec"]
        
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("PERFORMANCE ANALYSIS REPORT (Anonymous)")
        lines.append("=" * 70)
        lines.append("Total Time: {:.2f}s ({:.0f}m {:.1f}s)".format(total, total // 60, total % 60))
        lines.append("=" * 70)
        
        # SECTION BREAKDOWN - FOCUS ON SLOWEST ACTIONS
        lines.append("\nSLOWEST ACTIONS (Performance Bottlenecks):")
        lines.append("-" * 70)
        for i, (name, data) in enumerate(sorted(report["sections"].items(),
                                              key=lambda x: x[1]["elapsed_sec"],
                                              reverse=True), 1):
            bar_len = int(data["percent"] / 2)
            bar = "█" * bar_len
            lines.append("  {:2d}. {:35s} {:6.2f}s ({:5.1f}%) {}".format(
                i, name[:35], data["elapsed_sec"], data["percent"], bar))
        
        # OBJECT TYPE STATISTICS - Sort by avg time (slowest types first)
        lines.append("\nSLOWEST OBJECT TYPES (by average processing time):")
        lines.append("-" * 70)
        lines.append("  Type                     Count    Total     Avg      Max     P90")
        lines.append("  " + "-" * 70)
        sorted_types = sorted(report["object_stats"].items(),
                           key=lambda x: x[1]["avg_sec"],
                           reverse=True)
        for obj_type, stats in sorted_types:
            p90_str = "{:5.3f}s".format(stats.get("p90_sec", 0)) if "p90_sec" in stats else " N/A  "
            lines.append("  {:25s} {:5d}  {:6.2f}s  {:5.3f}s  {:5.2f}s  {}".format(
                obj_type[:25],
                stats["count"],
                stats["total_sec"],
                stats["avg_sec"],
                stats["max_sec"],
                p90_str
            ))
        
        return "\n".join(lines) + "\n"
    
    def get_insights_text(self, processed_count=0):
        """Generate insights section as string."""
        report = self.get_report()
        total = report["total_time_sec"]
        
        lines = []
        lines.append("=" * 70)
        lines.append("PERFORMANCE INSIGHTS (Bottleneck Analysis):")
        lines.append("=" * 70)
        
        # Find SLOWEST SECTION
        sorted_sections = sorted(report["sections"].items(),
                              key=lambda x: x[1]["elapsed_sec"],
                              reverse=True)
        if sorted_sections:
            slowest_name, slowest_data = sorted_sections[0]
            slowest_pct = slowest_data["percent"]
            lines.append("⚠ MAIN BOTTLENECK: '{}' - {:.1f}% of total time ({:.2f}s)".format(
                slowest_name, slowest_pct, slowest_data["elapsed_sec"]))
            
            # Specific insights for different bottlenecks
            if "IDE comparison loop" in slowest_name:
                lines.append("  • This is a critical performance issue")
                lines.append("  • Recommendation: Implement cache-based fast mode")
                lines.append("  • With cache: Compare will skip unchanged objects")
            
            if "XML export" in slowest_name:
                xml_stats = report["object_stats"].get("XML export_native", {})
                if xml_stats.get("total_sec", 0) > 10:
                    lines.append("  • XML export is particularly slow")
                    lines.append("  • Recommendation: Consider disabling export_xml for non-essential XMLs")
                    lines.append("  • Or use cache to skip re-exporting unchanged XMLs")
            
            # Secondary bottlenecks (>10% of time)
            if len(sorted_sections) > 1 and sorted_sections[1][1]["percent"] > 10:
                lines.append("\n⚠ SECONDARY BOTTLENECK: '{}' - {:.1f}%".format(
                    sorted_sections[1][0], sorted_sections[1][1]["percent"]))
        
        # Average processing time
        if processed_count > 0:
            ide_loop_time = report["sections"].get("IDE comparison loop", {}).get("elapsed_sec", 0)
            avg_per_object = ide_loop_time / processed_count if ide_loop_time > 0 else 0
            lines.append("\n• Average time per object: {:.3f}s ({} objects processed)".format(
                avg_per_object, processed_count))
            lines.append("• Projected time for 1000 objects: {:.1f}s ({:.0f}m {:.1f}s)".format(
                avg_per_object * 1000,
                (avg_per_object * 1000) // 60,
                (avg_per_object * 1000) % 60))
        
        # Slowest object type
        sorted_types = sorted(report["object_stats"].items(),
                           key=lambda x: x[1]["avg_sec"],
                           reverse=True)
        if sorted_types:
            slowest_type, slowest_type_data = sorted_types[0]
            if slowest_type_data["avg_sec"] > 0.02:  # Slower than 20ms average
                lines.append("\n• Slowest object type: '{}' - {:.3f}s avg ({:.2f}s total, {} objects)".format(
                    slowest_type,
                    slowest_type_data["avg_sec"],
                    slowest_type_data["total_sec"],
                    slowest_type_data["count"]))
        
        lines.append("\n" + "=" * 70)
        lines.append("This report is anonymous - no object names or paths included")
        lines.append("Feel free to share this for performance analysis!")
        lines.append("=" * 70)
        
        return "\n".join(lines) + "\n"
    
    def print_report(self):
        """Print formatted report to console (anonymous - focuses on slowest actions)."""
        print(self.get_text_report())
        print(self.get_insights_text())


# ═══════════════════════════════════════════════════════════════════
#  CONTENT EXTRACTION (copied from compare_engine for profiling)
# ═══════════════════════════════════════════════════════════════════

import tempfile

def get_ide_content_profiling(obj, is_xml, property_accessors, projects_obj, 
                              can_have_impl=False, profiler=None):
    """Extract content from IDE object for comparison (with profiling)."""
    
    obj_name = obj.get_name() if obj else "Unknown"
    
    if is_xml:
        clean_name = clean_filename(obj_name)
        tmp_path = os.path.join(tempfile.gettempdir(), "cds_comp_" + clean_name + ".xml")
        start = time.time()
        try:
            monolithic_types = [
                TYPE_GUIDS["task_config"], TYPE_GUIDS["alarm_config"], 
                TYPE_GUIDS["visu_manager"], TYPE_GUIDS["softmotion_pool"]
            ]
            obj_type = safe_str(obj.type)
            recursive = obj_type in monolithic_types
            
            if obj_type == TYPE_GUIDS["device"]:
                from codesys_utils import is_container_device
                recursive = not is_container_device(obj)
            
            projects_obj.primary.export_native([obj], tmp_path, recursive=recursive)
            export_time = time.time() - start
            
            if profiler:
                profiler.track_object(obj_name, "XML export_native", export_time)
            
            content = read_file(tmp_path)
            os.remove(tmp_path)
            return content
        except:
            return ""
    
    # ST content
    obj_guid = safe_str(obj.guid)
    obj_type = safe_str(obj.type)
    obj_type_name = TYPE_NAMES.get(obj_type, obj_type[:8])
    
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
        profiler.track_object(obj_name, obj_type_name + " ST", st_extract_time)
    
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
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 1: Collect all IDE objects
    # ═══════════════════════════════════════════════════════════════════
    print("\n[1/5] Collecting IDE objects...")
    profiler.start("get_children(recursive)")
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    profiler.end("get_children(recursive)")
    print("  Found {} objects".format(len(all_ide_objects)))
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 2: Collect property accessors
    # ═══════════════════════════════════════════════════════════════════
    print("\n[2/5] Collecting property accessors...")
    profiler.start("collect_property_accessors")
    property_accessors = collect_property_accessors(all_ide_objects)
    profiler.end("collect_property_accessors")
    print("  Collected {} property accessors".format(len(property_accessors)))
    
    # ═══════════════════════════════════════════════════════════════════
    #  STEP 3: Process each IDE object (THE SLOW PART!)
    # ═══════════════════════════════════════════════════════════════════
    print("\n[3/5] Processing IDE objects (this may take a while)...")
    profiler.start("IDE comparison loop")
    
    ide_paths = {}
    processed_count = 0
    skipped_count = 0
    xml_count = 0
    st_count = 0
    
    for obj in all_ide_objects:
        processed_count += 1
        
        # Progress indicator every 50 objects
        if processed_count % 50 == 0:
            print("  Progress: {}/{} objects processed".format(processed_count, len(all_ide_objects)))
        
        effective_type, is_xml, should_skip = classify_object(obj)
        if should_skip:
            skipped_count += 1
            continue

        # XML gate
        if is_xml and effective_type in XML_TYPES:
            always_exported = effective_type in [
                TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]
            ]
            if not always_exported and not export_xml:
                skipped_count += 1
                continue
            xml_count += 1
        else:
            st_count += 1

        rel_path = build_expected_path(obj, effective_type, is_xml)
        ide_paths[rel_path] = obj
        file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
        type_name = TYPE_NAMES.get(effective_type, effective_type[:8])

        if os.path.exists(file_path):
            can_have_impl = effective_type in IMPLEMENTATION_TYPES
            ide_content = get_ide_content_profiling(
                obj, is_xml, property_accessors, projects_obj, can_have_impl, profiler
            )
            disk_content = read_file(file_path)
            
            # Note: We're NOT actually comparing here, just measuring extraction time
        else:
            # File doesn't exist on disk - still track the IDE extraction time
            can_have_impl = effective_type in IMPLEMENTATION_TYPES
            ide_content = get_ide_content_profiling(
                obj, is_xml, property_accessors, projects_obj, can_have_impl, profiler
            )
    
    profiler.end("IDE comparison loop")
    print("  Processed {} objects (XML: {}, ST: {}, Skipped: {})".format(
        processed_count, xml_count, st_count, skipped_count))
    
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
    
    profiler.print_report()
    
    # Save reports (both JSON and TXT)
    report = profiler.get_report()
    
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
        text_report = profiler.get_text_report(processed_count)
        insights_report = profiler.get_insights_text(processed_count)
        with codecs.open(txt_path, "w", "utf-8") as f:
            f.write(text_report)
            f.write(insights_report)
        print("Text report saved to: " + txt_path)
    except Exception as e:
        print("\nWarning: Could not save text report: " + safe_str(e))
    
    # Performance insights - Focus on BOTTLENECKS
    print("\n" + "=" * 70)
    print("PERFORMANCE INSIGHTS (Bottleneck Analysis):")
    print("=" * 70)
    
    total = report["total_time_sec"]
    
    # Find the SLOWEST SECTION
    sorted_sections = sorted(report["sections"].items(),
                          key=lambda x: x[1]["elapsed_sec"],
                          reverse=True)
    if sorted_sections:
        slowest_name, slowest_data = sorted_sections[0]
        slowest_pct = slowest_data["percent"]
        print("⚠ MAIN BOTTLENECK: '{}' - {:.1f}% of total time ({:.2f}s)".format(
            slowest_name, slowest_pct, slowest_data["elapsed_sec"]))
        
        # Specific insights for different bottlenecks
        if "IDE comparison loop" in slowest_name:
            print("  • This is the critical performance issue")
            print("  • Recommendation: Implement cache-based fast mode")
            print("  • With cache: Compare will skip unchanged objects")
        
        if "XML export" in slowest_name:
            xml_stats = report["object_stats"].get("XML export_native", {})
            if xml_stats.get("total_sec", 0) > 10:
                print("  • XML export is particularly slow")
                print("  • Recommendation: Consider disabling export_xml for non-essential XMLs")
                print("  • Or use cache to skip re-exporting unchanged XMLs")
        
        # Secondary bottlenecks (>10% of time)
        if len(sorted_sections) > 1 and sorted_sections[1][1]["percent"] > 10:
            print("\n⚠ SECONDARY BOTTLENECK: '{}' - {:.1f}%".format(
                sorted_sections[1][0], sorted_sections[1][1]["percent"]))
    
    # Average processing time
    if processed_count > 0:
        ide_loop_time = report["sections"].get("IDE comparison loop", {}).get("elapsed_sec", 0)
        avg_per_object = ide_loop_time / processed_count if ide_loop_time > 0 else 0
        print("\n• Average time per object: {:.3f}s ({} objects processed)".format(
            avg_per_object, processed_count))
        print("• Projected time for 1000 objects: {:.1f}s ({:.0f}m {:.1f}s)".format(
            avg_per_object * 1000,
            (avg_per_object * 1000) // 60,
            (avg_per_object * 1000) % 60))
    
    # Slowest object type
    sorted_types = sorted(report["object_stats"].items(),
                       key=lambda x: x[1]["avg_sec"],
                       reverse=True)
    if sorted_types:
        slowest_type, slowest_type_data = sorted_types[0]
        if slowest_type_data["avg_sec"] > 0.02:  # Slower than 20ms average
            print("\n• Slowest object type: '{}' - {:.3f}s avg ({:.2f}s total, {} objects)".format(
                slowest_type,
                slowest_type_data["avg_sec"],
                slowest_type_data["total_sec"],
                slowest_type_data["count"]))
    
    print("\n" + "=" * 70)
    print("This report is anonymous - no object names or paths included")
    print("Feel free to share this for performance analysis!")
    print("=" * 70)


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
