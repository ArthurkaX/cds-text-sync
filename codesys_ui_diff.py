# -*- coding: utf-8 -*-
"""
codesys_ui_diff.py - Side-by-side diff viewer for CODESYS scripts

Renders two columns showing IDE vs Disk text content with highlighted differences.
Uses WinForms RichTextBox for colored diff rendering.
"""
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Windows.Forms import (
    Form, Panel, RichTextBox, Label, Button, RichTextBoxScrollBars,
    FormBorderStyle, FormStartPosition, DialogResult,
    DockStyle, AnchorStyles, BorderStyle, Padding, Control, Keys
)
from System.Drawing import (
    Size, Point, Font, FontStyle, Color, ContentAlignment,
    SystemColors
)
import os
import codecs


# ─── Diff Algorithm ──────────────────────────────────────────────────────────

def _compute_lcs_matrix(lines_a, lines_b):
    """Compute Longest Common Subsequence matrix between two line lists."""
    m = len(lines_a)
    n = len(lines_b)
    # Use a flat list for memory efficiency
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if lines_a[i - 1] == lines_b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp


def compute_side_by_side_diff(text_left, text_right):
    """
    Compute a side-by-side diff between two texts.
    
    Returns list of tuples: (left_line, right_line, status)
    Status: 'equal', 'modified', 'added', 'removed'
    """
    lines_a = (text_left or "").splitlines()
    lines_b = (text_right or "").splitlines()
    
    dp = _compute_lcs_matrix(lines_a, lines_b)
    
    # Backtrack to find diff operations
    result = []
    i, j = len(lines_a), len(lines_b)
    
    ops = []
    while i > 0 and j > 0:
        if lines_a[i - 1] == lines_b[j - 1]:
            ops.append(('equal', i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            ops.append(('removed', i - 1, None))
            i -= 1
        else:
            ops.append(('added', None, j - 1))
            j -= 1
    
    while i > 0:
        ops.append(('removed', i - 1, None))
        i -= 1
    while j > 0:
        ops.append(('added', None, j - 1))
        j -= 1
    
    ops.reverse()
    
    # Build side-by-side output
    for op, idx_a, idx_b in ops:
        if op == 'equal':
            result.append((lines_a[idx_a], lines_b[idx_b], 'equal'))
        elif op == 'removed':
            result.append((lines_a[idx_a], "", 'removed'))
        elif op == 'added':
            result.append(("", lines_b[idx_b], 'added'))
    
    # Post-process: merge adjacent removed+added pairs into 'modified'
    merged = []
    i = 0
    while i < len(result):
        if (i + 1 < len(result) and 
            result[i][2] == 'removed' and result[i + 1][2] == 'added'):
            merged.append((result[i][0], result[i + 1][1], 'modified'))
            i += 2
        else:
            merged.append(result[i])
            i += 1
    
    return merged


# ─── Colors ───────────────────────────────────────────────────────────────────

CLR_BG_DARK       = Color.FromArgb(30, 30, 30)
CLR_BG_PANEL      = Color.FromArgb(37, 37, 38)
CLR_TEXT_NORMAL    = Color.FromArgb(212, 212, 212)
CLR_TEXT_LINE_NO   = Color.FromArgb(100, 100, 100)

CLR_ADDED_BG      = Color.FromArgb(35, 65, 35)
CLR_ADDED_TEXT     = Color.FromArgb(120, 220, 120)

CLR_REMOVED_BG    = Color.FromArgb(75, 30, 30)
CLR_REMOVED_TEXT   = Color.FromArgb(240, 120, 120)

CLR_MODIFIED_L_BG  = Color.FromArgb(75, 55, 20)
CLR_MODIFIED_L_TXT = Color.FromArgb(240, 200, 100)
CLR_MODIFIED_R_BG  = Color.FromArgb(30, 55, 75)
CLR_MODIFIED_R_TXT = Color.FromArgb(100, 200, 240)

CLR_HEADER_BG      = Color.FromArgb(45, 45, 48)
CLR_HEADER_TEXT     = Color.FromArgb(200, 200, 200)
CLR_BTN_BG         = Color.FromArgb(60, 60, 65)
CLR_BTN_TEXT       = Color.FromArgb(220, 220, 220)
CLR_SEPARATOR      = Color.FromArgb(60, 60, 65)


# ─── Diff Viewer Form ────────────────────────────────────────────────────────

class DiffViewerForm(Form):
    """Side-by-side diff viewer with dark theme and syntax-highlighted differences."""
    
    def __init__(self, left_text, right_text, left_title="IDE Content", right_title="Disk Content", object_name=""):
        self.Text = "Diff: " + object_name if object_name else "Diff Viewer"
        self.Size = Size(1100, 700)
        self.MinimumSize = Size(600, 400)
        self.StartPosition = FormStartPosition.CenterScreen
        self.BackColor = CLR_BG_DARK
        self.FormBorderStyle = FormBorderStyle.Sizable
        
        self._left_text = left_text or ""
        self._right_text = right_text or ""
        self._syncing_scroll = False
        self._change_positions = []   # char indices of each diff hunk in left RTB
        self._current_change = -1
        
        # ── Top bar (title + column headers in one panel) ─────────────
        top_bar = Panel()
        top_bar.Height = 60
        top_bar.Dock = DockStyle.Top
        top_bar.BackColor = CLR_HEADER_BG
        self.Controls.Add(top_bar)
        
        title_label = Label()
        title_label.Text = object_name if object_name else "Diff Viewer"
        title_label.ForeColor = CLR_HEADER_TEXT
        title_label.Font = Font("Segoe UI", 11, FontStyle.Bold)
        title_label.AutoSize = True
        title_label.Location = Point(12, 6)
        top_bar.Controls.Add(title_label)
        
        # Stats label (right side of title row)
        self._stats_label = Label()
        self._stats_label.ForeColor = CLR_TEXT_LINE_NO
        self._stats_label.Font = Font("Segoe UI", 9)
        self._stats_label.AutoSize = True
        self._stats_label.Location = Point(500, 8)
        top_bar.Controls.Add(self._stats_label)
        
        # Column labels (second row inside top bar)
        lbl_left = Label()
        lbl_left.Text = left_title
        lbl_left.ForeColor = CLR_ADDED_TEXT
        lbl_left.Font = Font("Segoe UI Semibold", 9)
        lbl_left.Location = Point(15, 36)
        lbl_left.AutoSize = True
        top_bar.Controls.Add(lbl_left)
        
        lbl_right = Label()
        lbl_right.Text = right_title
        lbl_right.ForeColor = Color.FromArgb(200, 160, 255)
        lbl_right.Font = Font("Segoe UI Semibold", 9)
        lbl_right.AutoSize = True
        top_bar.Controls.Add(lbl_right)
        self._lbl_right_header = lbl_right
        
        # ── Bottom bar ──────────
        bottom_bar = Panel()
        bottom_bar.Height = 45
        bottom_bar.Dock = DockStyle.Bottom
        bottom_bar.BackColor = CLR_HEADER_BG
        self.Controls.Add(bottom_bar)
        
        btn_close = Button()
        btn_close.Text = "Close"
        btn_close.Size = Size(90, 30)
        btn_close.Location = Point(10, 8)
        btn_close.BackColor = CLR_BTN_BG
        btn_close.ForeColor = CLR_BTN_TEXT
        btn_close.FlatStyle = 0  # Flat
        btn_close.DialogResult = DialogResult.Cancel
        bottom_bar.Controls.Add(btn_close)
        self.CancelButton = btn_close
        
        # Navigation buttons
        btn_prev = Button()
        btn_prev.Text = "<< Prev"
        btn_prev.Size = Size(80, 30)
        btn_prev.Location = Point(120, 8)
        btn_prev.BackColor = CLR_BTN_BG
        btn_prev.ForeColor = CLR_BTN_TEXT
        btn_prev.FlatStyle = 0
        btn_prev.Click += self._on_prev
        bottom_bar.Controls.Add(btn_prev)
        
        btn_next = Button()
        btn_next.Text = "Next >>"
        btn_next.Size = Size(80, 30)
        btn_next.Location = Point(205, 8)
        btn_next.BackColor = CLR_BTN_BG
        btn_next.ForeColor = CLR_BTN_TEXT
        btn_next.FlatStyle = 0
        btn_next.Click += self._on_next
        bottom_bar.Controls.Add(btn_next)
        
        self._nav_label = Label()
        self._nav_label.Text = ""
        self._nav_label.ForeColor = CLR_TEXT_LINE_NO
        self._nav_label.Font = Font("Segoe UI", 9)
        self._nav_label.AutoSize = True
        self._nav_label.Location = Point(295, 14)
        bottom_bar.Controls.Add(self._nav_label)
        
        # Save button (for Ctrl+Diff functionality inside the viewer)
        btn_save = Button()
        btn_save.Text = "Save to /.diff/"
        btn_save.Size = Size(100, 30)
        btn_save.Location = Point(self.Size.Width - 125, 8)
        btn_save.Anchor = getattr(AnchorStyles, "Top") | getattr(AnchorStyles, "Right")
        btn_save.BackColor = CLR_BTN_BG
        btn_save.ForeColor = Color.FromArgb(200, 255, 200) # Subtle green
        btn_save.FlatStyle = 0
        btn_save.Click += self._on_save_button_click
        bottom_bar.Controls.Add(btn_save)
        self._btn_save_internal = btn_save
        
        # ── Content panel (directly on form, no nesting) ──
        content_panel = Panel()
        content_panel.Dock = DockStyle.Fill
        content_panel.BackColor = CLR_BG_DARK
        content_panel.Padding = Padding(5, 5, 5, 5)
        self.Controls.Add(content_panel)
        # Fix docking order: Fill must be docked LAST (lowest z-index)
        # so it only takes the space remaining after Top/Bottom bars.
        content_panel.BringToFront()
        
        # Separator
        separator = Panel()
        separator.Width = 2
        separator.BackColor = CLR_SEPARATOR
        
        self._rtb_left = self._create_rtb()
        self._rtb_right = self._create_rtb()
        
        # Sync scrolling between the two panels
        self._rtb_left.VScroll += self._on_left_scroll
        self._rtb_right.VScroll += self._on_right_scroll
        
        # Add to content panel
        content_panel.Controls.Add(self._rtb_right)
        content_panel.Controls.Add(separator)
        content_panel.Controls.Add(self._rtb_left)
        
        self._content_panel = content_panel
        self._separator = separator
        
        # Handle resize
        self.Resize += self._on_resize
        
        # Populate diff
        self._populate_diff()
        
        # Initial layout
        self._trigger_layout()
    
    def _create_rtb(self):
        """Create a styled RichTextBox for diff display."""
        rtb = RichTextBox()
        rtb.ReadOnly = True
        rtb.BackColor = CLR_BG_PANEL
        rtb.ForeColor = CLR_TEXT_NORMAL
        rtb.Font = Font("Consolas", 10)
        rtb.BorderStyle = getattr(BorderStyle, "None")
        rtb.WordWrap = False
        rtb.ScrollBars = RichTextBoxScrollBars.Both
        rtb.DetectUrls = False
        return rtb
    
    def _on_left_scroll(self, sender, event):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            # Sync right panel to left panel scroll position
            pos = self._rtb_left.GetPositionFromCharIndex(0)
            char_idx = self._rtb_right.GetCharIndexFromPosition(pos)
            # Use SendMessage to sync - simpler approach: set first visible line
            first_line = self._rtb_left.GetLineFromCharIndex(self._rtb_left.GetCharIndexFromPosition(Point(0, 0)))
            first_char_right = self._rtb_right.GetFirstCharIndexFromLine(first_line)
            if first_char_right >= 0:
                self._rtb_right.Select(first_char_right, 0)
                self._rtb_right.ScrollToCaret()
        except:
            pass
        self._syncing_scroll = False
    
    def _on_right_scroll(self, sender, event):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            first_line = self._rtb_right.GetLineFromCharIndex(self._rtb_right.GetCharIndexFromPosition(Point(0, 0)))
            first_char_left = self._rtb_left.GetFirstCharIndexFromLine(first_line)
            if first_char_left >= 0:
                self._rtb_left.Select(first_char_left, 0)
                self._rtb_left.ScrollToCaret()
        except:
            pass
        self._syncing_scroll = False
    
    def _on_resize(self, sender, event):
        self._trigger_layout()
    
    def _trigger_layout(self):
        """Manually position panels side by side."""
        if not self._content_panel or not hasattr(self._content_panel, 'ClientSize'):
            return
        w = self._content_panel.ClientSize.Width
        h = self._content_panel.ClientSize.Height
        half = (w - 2) // 2
        
        self._rtb_left.Location = Point(0, 0)
        self._rtb_left.Size = Size(half, h)
        
        self._separator.Location = Point(half, 0)
        self._separator.Size = Size(2, h)
        
        self._rtb_right.Location = Point(half + 2, 0)
        self._rtb_right.Size = Size(w - half - 2, h)
        
        # Position right-column header label in top bar
        if self._lbl_right_header:
            total_w = self.ClientSize.Width
            self._lbl_right_header.Location = Point(total_w // 2 + 10, 36)
        
        # Position stats label in top bar
        if self._stats_label:
            self._stats_label.Location = Point(self.ClientSize.Width - 280, 8)
    
    def _populate_diff(self):
        """Compute diff and render into both RichTextBox panels."""
        diff_lines = compute_side_by_side_diff(self._left_text, self._right_text)
        
        # Stats
        added = sum(1 for _, _, s in diff_lines if s == 'added')
        removed = sum(1 for _, _, s in diff_lines if s == 'removed')
        modified = sum(1 for _, _, s in diff_lines if s == 'modified')
        equal = sum(1 for _, _, s in diff_lines if s == 'equal')
        self._stats_label.Text = "+{} -{} ~{} ={} lines".format(added, removed, modified, equal)
        
        # Render
        self._rtb_left.Clear()
        self._rtb_right.Clear()
        self._change_positions = []
        
        left_line_no = 0
        right_line_no = 0
        in_change = False
        
        for left_line, right_line, status in diff_lines:
            if status == 'equal':
                left_line_no += 1
                right_line_no += 1
                prefix_l = "{:>4}  ".format(left_line_no)
                prefix_r = "{:>4}  ".format(right_line_no)
                self._append_line(self._rtb_left, prefix_l, CLR_TEXT_LINE_NO, left_line, CLR_TEXT_NORMAL, None)
                self._append_line(self._rtb_right, prefix_r, CLR_TEXT_LINE_NO, right_line, CLR_TEXT_NORMAL, None)
                in_change = False
                
            elif status == 'removed':
                if not in_change:
                    self._change_positions.append(self._rtb_left.TextLength)
                    in_change = True
                left_line_no += 1
                prefix_l = "{:>4} -".format(left_line_no)
                self._append_line(self._rtb_left, prefix_l, CLR_REMOVED_TEXT, left_line, CLR_REMOVED_TEXT, CLR_REMOVED_BG)
                self._append_line(self._rtb_right, "      ", CLR_TEXT_LINE_NO, "", CLR_TEXT_NORMAL, None)
                
            elif status == 'added':
                if not in_change:
                    self._change_positions.append(self._rtb_left.TextLength)
                    in_change = True
                right_line_no += 1
                prefix_r = "{:>4} +".format(right_line_no)
                self._append_line(self._rtb_left, "      ", CLR_TEXT_LINE_NO, "", CLR_TEXT_NORMAL, None)
                self._append_line(self._rtb_right, prefix_r, CLR_ADDED_TEXT, right_line, CLR_ADDED_TEXT, CLR_ADDED_BG)
                
            elif status == 'modified':
                if not in_change:
                    self._change_positions.append(self._rtb_left.TextLength)
                    in_change = True
                left_line_no += 1
                right_line_no += 1
                prefix_l = "{:>4} ~".format(left_line_no)
                prefix_r = "{:>4} ~".format(right_line_no)
                self._append_line(self._rtb_left, prefix_l, CLR_MODIFIED_L_TXT, left_line, CLR_MODIFIED_L_TXT, CLR_MODIFIED_L_BG)
                self._append_line(self._rtb_right, prefix_r, CLR_MODIFIED_R_TXT, right_line, CLR_MODIFIED_R_TXT, CLR_MODIFIED_R_BG)
        
        # Update nav label
        total = len(self._change_positions)
        self._nav_label.Text = str(total) + " change" + ("s" if total != 1 else "")
        self._current_change = -1
        
        # Reset scroll to top – Select(0,0) alone sometimes leaves the
        # first few lines above the viewport.  Force position to line 0.
        for rtb in (self._rtb_left, self._rtb_right):
            rtb.SelectionStart = 0
            rtb.SelectionLength = 0
            rtb.ScrollToCaret()
            # Double-ensure: jump to the first char of line 0
            idx0 = rtb.GetFirstCharIndexFromLine(0)
            if idx0 >= 0:
                rtb.SelectionStart = idx0
                rtb.ScrollToCaret()
    
    def _on_prev(self, sender, event):
        """Navigate to previous change."""
        if not self._change_positions:
            return
        if self._current_change <= 0:
            self._current_change = len(self._change_positions) - 1
        else:
            self._current_change -= 1
        self._navigate_to_change(self._current_change)
    
    def _on_next(self, sender, event):
        """Navigate to next change."""
        if not self._change_positions:
            return
        if self._current_change >= len(self._change_positions) - 1:
            self._current_change = 0
        else:
            self._current_change += 1
        self._navigate_to_change(self._current_change)
    
    def _navigate_to_change(self, index):
        """Scroll both panels to the change at given index."""
        if index < 0 or index >= len(self._change_positions):
            return
        
        char_pos = self._change_positions[index]
        
        # Scroll left panel
        self._rtb_left.Select(char_pos, 0)
        self._rtb_left.ScrollToCaret()
        
        # Sync right panel to same line
        line_no = self._rtb_left.GetLineFromCharIndex(char_pos)
        right_char = self._rtb_right.GetFirstCharIndexFromLine(line_no)
        if right_char >= 0:
            self._rtb_right.Select(right_char, 0)
            self._rtb_right.ScrollToCaret()
        
        # Update label
        total = len(self._change_positions)
        self._nav_label.Text = "Change {}/{}" .format(index + 1, total)
        
    def _on_save_button_click(self, sender, event):
        """Save both versions displayed in the viewer to the /.diff/ folder."""
        from codesys_utils import load_base_dir, log_info
        
        base_dir, _ = load_base_dir()
        if not base_dir:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        diff_dir = os.path.join(base_dir, ".diff")
        if not os.path.exists(diff_dir):
            try: os.makedirs(diff_dir)
            except: pass
            
        safe_name = self.Text.replace("Diff: ", "").replace("/", "_").replace("\\", "_").replace(":", "_")
        # Default extension to .st if we don't know it
        ext = ".st" 
        
        try:
            # Note: in codesys_ui call, left=Disk Content, right=IDE Content
            path_left = os.path.join(diff_dir, "disk_{}_{}".format(safe_name, ext))
            path_right = os.path.join(diff_dir, "ide_{}_{}".format(safe_name, ext))
            
            with codecs.open(path_left, "w", "utf-8") as f:
                f.write(self._left_text)
            with codecs.open(path_right, "w", "utf-8") as f:
                f.write(self._right_text)
                
            from codesys_ui import show_toast
            show_toast("Saved to /.diff/", "Files saved for '{}' at {}".format(safe_name, diff_dir))
        except Exception as e:
            print("Failed to save from diff viewer: " + str(e))
    
    def _append_line(self, rtb, prefix, prefix_color, text, text_color, bg_color):
        """Append a styled line to a RichTextBox."""
        start = rtb.TextLength
        
        # Add prefix (line number)
        rtb.AppendText(prefix)
        rtb.Select(start, len(prefix))
        rtb.SelectionColor = prefix_color
        if bg_color:
            rtb.SelectionBackColor = bg_color
        
        # Add text content
        text_start = rtb.TextLength
        rtb.AppendText(text + "\n")
        rtb.Select(text_start, len(text))
        rtb.SelectionColor = text_color
        if bg_color:
            rtb.SelectionBackColor = bg_color


def show_diff_dialog(left_text, right_text, left_title="IDE Content", 
                     right_title="Disk Content", object_name=""):
    """
    Show a side-by-side diff dialog.
    """
    try:
        # Performance check: LCS is O(N*M). Large files will be slow.
        # If file > 100KB, warn the user.
        size_a = len(left_text or "")
        size_b = len(right_text or "")
        max_size = max(size_a, size_b)
        
        if max_size > 100 * 1024:
            from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon
            msg = ("The file '{}' is large ({:.1f} KB). \n"
                   "Comparing it line-by-line might take a long time and hang the UI.\n\n"
                   "Are you sure? \n(Hint: use Ctrl + Diff to save files and use an external editor)").format(
                object_name, max_size / 1024.0)
            res = MessageBox.Show(msg, "Large File Warning", MessageBoxButtons.YesNo, MessageBoxIcon.Warning)
            if res != DialogResult.Yes:
                return

        form = DiffViewerForm(left_text, right_text, left_title, right_title, object_name)
        form.ShowDialog()
    except Exception as e:
        print("Error showing diff dialog: " + str(e))
