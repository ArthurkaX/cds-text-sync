# -*- coding: utf-8 -*-
"""
Project_Analyze_Resources.py - Analyze project objects by size/complexity.

Helps identify "bloat" in the project by measuring source code length 
and XML export size for graphical objects.
"""
import os
import sys
import tempfile
import codecs

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, DataGridView, DataGridViewTextBoxColumn, DataGridViewAutoSizeColumnsMode,
        DialogResult, FormBorderStyle, FormStartPosition, Button, Label, Panel,
        ScrollBars, BorderStyle, DataGridViewCellStyle, DataGridViewContentAlignment,
        SortOrder, DataGridViewSelectionMode
    )
    from System.Drawing import Size, Point, Font, FontStyle, Color
    HAS_UI = True
except:
    HAS_UI = False

from Project_bootstrap import load_hidden_modules

load_hidden_modules([
    "codesys_constants",
    "codesys_utils",
    "codesys_managers",
], script_file=__file__)

from codesys_constants import TYPE_NAMES
from codesys_utils import safe_str, resolve_projects, format_st_content, format_property_content
from codesys_managers import classify_object, export_object_content, collect_property_accessors
from codesys_type_system import can_have_implementation_kind


class ResourcesResultsForm(Form):
    """WinForms dialog showing resource analysis results in a sortable grid."""
    
    def __init__(self, data, total_code, total_xml):
        self.Text = "Project Resource Analysis"
        self.Size = Size(620, 520)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        
        y = 12
        
        lbl_hint = Label()
        lbl_hint.Text = "Click column headers to sort. Larger objects may indicate code bloat."
        lbl_hint.Location = Point(12, y)
        lbl_hint.AutoSize = True
        self.Controls.Add(lbl_hint)
        y += 25
        
        grid = DataGridView()
        grid.Location = Point(12, y)
        grid.Size = Size(580, 370)
        grid.AllowUserToAddRows = False
        grid.AllowUserToDeleteRows = False
        grid.ReadOnly = True
        grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        grid.MultiSelect = False
        grid.BorderStyle = BorderStyle.FixedSingle
        grid.BackgroundColor = Color.White
        grid.AllowUserToResizeColumns = True
        grid.AllowUserToResizeRows = False
        grid.RowHeadersVisible = False
        
        col_name = DataGridViewTextBoxColumn()
        col_name.HeaderText = "Object Name"
        col_name.Name = "name"
        col_name.FillWeight = 45
        grid.Columns.Add(col_name)
        
        col_type = DataGridViewTextBoxColumn()
        col_type.HeaderText = "Type"
        col_type.Name = "type"
        col_type.FillWeight = 25
        grid.Columns.Add(col_type)
        
        col_size = DataGridViewTextBoxColumn()
        col_size.HeaderText = "Size (bytes)"
        col_size.Name = "size"
        col_size.FillWeight = 15
        col_size.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight
        grid.Columns.Add(col_size)
        
        col_category = DataGridViewTextBoxColumn()
        col_category.HeaderText = "Category"
        col_category.Name = "category"
        col_category.FillWeight = 15
        grid.Columns.Add(col_category)
        
        for item in data:
            idx = grid.Rows.Add()
            grid.Rows[idx].Cells["name"].Value = item["name"]
            grid.Rows[idx].Cells["type"].Value = item["type"]
            grid.Rows[idx].Cells["size"].Value = "{:,}".format(item["size"])
            grid.Rows[idx].Cells["category"].Value = "XML" if item["is_xml"] else "Code"
            grid.Rows[idx].Tag = item["size"]
        
        grid.SortCompare += self._on_sort_compare
        
        self.Controls.Add(grid)
        self.grid = grid
        y += 378
        
        pnl_summary = Panel()
        pnl_summary.Location = Point(12, y)
        pnl_summary.Size = Size(580, 50)
        pnl_summary.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(pnl_summary)
        
        lbl_code = Label()
        lbl_code.Text = "Total Code: {:,} bytes".format(total_code)
        lbl_code.Location = Point(10, 5)
        lbl_code.AutoSize = True
        pnl_summary.Controls.Add(lbl_code)
        
        lbl_xml = Label()
        lbl_xml.Text = "Total XML: {:,} bytes".format(total_xml)
        lbl_xml.Location = Point(10, 22)
        lbl_xml.AutoSize = True
        pnl_summary.Controls.Add(lbl_xml)
        
        lbl_count = Label()
        lbl_count.Text = "Objects: {}".format(len(data))
        lbl_count.Location = Point(280, 12)
        lbl_count.AutoSize = True
        lbl_count.Font = Font("Segoe UI", 9, FontStyle.Bold)
        pnl_summary.Controls.Add(lbl_count)
        
        y += 58
        
        btn_close = Button()
        btn_close.Text = "Close"
        btn_close.DialogResult = DialogResult.Cancel
        btn_close.Location = Point(500, y)
        btn_close.Size = Size(90, 28)
        self.Controls.Add(btn_close)
        self.CancelButton = btn_close
        
        self.Size = Size(620, y + 65)
    
    def _on_sort_compare(self, sender, e):
        if e.Column.Name == "size":
            row1 = sender.Rows[e.RowIndex1]
            row2 = sender.Rows[e.RowIndex2]
            val1 = row1.Tag if row1.Tag else 0
            val2 = row2.Tag if row2.Tag else 0
            if val1 < val2:
                e.SortResult = -1
            elif val1 > val2:
                e.SortResult = 1
            else:
                e.SortResult = 0
            e.Handled = True


def show_results_dialog(data, total_code, total_xml):
    try:
        form = ResourcesResultsForm(data, total_code, total_xml)
        form.ShowDialog()
        return True
    except Exception as e:
        print("Error showing dialog: " + str(e))
        return False

def get_size_metrics():
    projects_obj = resolve_projects()
    if not projects_obj or not projects_obj.primary:
        print("No project open!")
        return

    proj = projects_obj.primary
    all_objects = proj.get_children(recursive=True)
    property_accessors = collect_property_accessors(all_objects)
    
    analysis_data = []
    total_code_size = 0
    total_xml_size = 0
    
    print("Analyzing project resources... (this may take a moment)")
    
    count = 0
    for obj in all_objects:
        try:
            resolution = classify_object(obj)
            if resolution.get("should_skip"):
                continue
            
            semantic_kind = resolution.get("semantic_kind", "")
            is_xml = resolution.get("is_xml", False)
            effective_type = resolution.get("effective_type", "")
            name = safe_str(obj.get_name())
            type_label = semantic_kind or TYPE_NAMES.get(effective_type, "Unknown")
            size = 0
            
            if is_xml:
                # Measure XML complexity
                tmp_path = os.path.join(tempfile.gettempdir(), "size_check.xml")
                try:
                    # Recursive export for monolithic types to get true size
                    monolithic_kinds = {"task_config", "alarm_config", "visu_manager", "softmotion_pool"}
                    recursive = semantic_kind in monolithic_kinds
                    
                    proj.export_native([obj], tmp_path, recursive=recursive)
                    if os.path.exists(tmp_path):
                        size = os.path.getsize(tmp_path)
                        os.remove(tmp_path)
                except:
                    pass
                total_xml_size += size
            else:
                # Measure Source Code
                if semantic_kind == "property" and safe_str(obj.guid) in property_accessors:
                    prop_data = property_accessors[safe_str(obj.guid)]
                    decl, _ = export_object_content(obj)
                    
                    get_impl = ""
                    if prop_data['get']:
                        g_decl, g_impl_raw = export_object_content(prop_data['get'])
                        get_impl = format_st_content(g_decl, g_impl_raw)
                        
                    set_impl = ""
                    if prop_data['set']:
                        s_decl, s_impl_raw = export_object_content(prop_data['set'])
                        set_impl = format_st_content(s_decl, s_impl_raw)
                        
                    content = format_property_content(decl, get_impl, set_impl)
                    size = len(content)
                else:
                    decl, impl = export_object_content(obj)
                    can_have_impl = can_have_implementation_kind(semantic_kind)
                    content = format_st_content(decl, impl, can_have_impl)
                    size = len(content)
                total_code_size += size
                
            analysis_data.append({
                "name": name,
                "type": type_label,
                "size": size,
                "is_xml": is_xml
            })
            
            count += 1
            if count % 20 == 0:
                sys.stdout.write(".")
                sys.stdout.flush()
                
        except Exception as e:
            # Just skip objects that throw errors during analysis
            continue
            
    print("\n")
    
    analysis_data.sort(key=lambda x: x['size'], reverse=True)
    
    if HAS_UI:
        shown = show_results_dialog(analysis_data, total_code_size, total_xml_size)
        if shown:
            return
    
    header = "{:<40} | {:<20} | {:>10}".format("Object Name", "Type", "Size (bytes)")
    separator = "-" * 75
    
    print(separator)
    print(header)
    print(separator)
    
    for item in analysis_data[:30]:
        size_str = "{:,}".format(item['size'])
        print("{:<40} | {:<20} | {:>12}".format(
            item['name'][:40], 
            item['type'], 
            size_str
        ))
        
    print(separator)
    print("Summary:")
    print("Total Source Code Volume: {:,} bytes".format(total_code_size))
    print("Total XML Metadata Volume: {:,} bytes".format(total_xml_size))
    print("Total Analyzed Objects: {}".format(len(analysis_data)))
    print(separator)

if __name__ == "__main__":
    get_size_metrics()
