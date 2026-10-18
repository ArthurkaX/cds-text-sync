// The quick widget's window, drawn by hand: a dark card without a frame, with
// rounded corners and a shadow, over the IDE.  No effects: it is there at once.  The header names the work
// branch and the connection, each row has its digit in a badge and the cts
// command it runs, and the footer shows the run: a spinner with the seconds
// and the stage cts reached, then a check or a cross and the verdict line.
//
// Keys: the digit runs its row, ↑↓ select and Enter does the same, → opens
// the page a row leads to, ← and Esc go back up a page (Esc on the menu
// closes); Space allows or blocks a permission.  A click elsewhere closes
// it unless a run is going.  The branch list and the settings replace the rows
// in the same window, a page below them (a program to choose, the permission
// groups and their permissions) one level further down.  A row that asks (Commit, a new branch, a setting) opens a
// line in the footer, filled with the value it has now: Enter runs the row
// with what was typed, Esc puts the hint back.  The sync folder row opens the
// folder dialog instead.  A question (Disk → IDE or IDE → Disk would
// overwrite edits) is a page too: its rows are the answers, the footer says
// what is at stake, Esc answers "neither".  A failure shown has a Copy link
// at the footer's right (Ctrl+C does the same): the controller puts a report
// with the run's whole output on the clipboard.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed partial class WidgetView : Form
    {
        static readonly Color Edge = Color.FromArgb(58, 64, 72);
        static readonly Color Rule = Color.FromArgb(44, 49, 56);
        static readonly Color Hover = Color.FromArgb(43, 49, 57);
        static readonly Color Badge = Color.FromArgb(52, 58, 66);
        static readonly Color Accent = Color.FromArgb(59, 130, 246);
        static readonly Color Warn = Color.FromArgb(210, 153, 34);

        const int Width0 = 460;
        const int HeaderHeight = 64;
        const int RowHeight = 44;
        const int Radius = 12;
        const int Side = 16;
        const int AnswerHeight = 44;
        const int BrowseWidth = 36;
        //: The footer shows at most this many lines of text; the wheel scrolls the rest.
        const int FooterLines = 14;
        const string IdleHint = "digit or ↑↓ Enter: run   → open   Esc close";

        readonly Font _title = new Font("Segoe UI Semibold", 11.5f);
        readonly Font _body = new Font("Segoe UI", 10.5f);
        readonly Font _small = new Font("Segoe UI", 8.75f);
        readonly Font _key = new Font("Segoe UI Semibold", 10f);
        readonly Font _mono = new Font("Consolas", 9f);

        string _branch;
        //: The last commit's subject and time, after the branch; null without one.
        string _commit;
        //: What changed since the last sync; "" until the compare answers.
        string _state = "";
        WidgetTone _tone;
        readonly bool _online;

        // Whether the PLC was online when the window opened.
        internal bool Online => _online;
        //: The line under the title: the sync folder, or why there is none.
        readonly string _place;
        readonly List<WidgetItem> _menu;
        List<WidgetItem> _items;
        bool _inList;
        //: How deep the page shown is: 1 under the menu, 2 below that, ...
        int _level;
        //: What goes back up from each level below the first.
        readonly Dictionary<int, Action> _up = new Dictionary<int, Action>();
        //: The row each level opened a page below it from, selected again on the way back.
        readonly Dictionary<int, string> _opened = new Dictionary<int, string>();
        //: The page showing next is one the person went back up to.
        bool _returning;
        string _listHint;
        //: The folder dialog is open: the window stays though it lost the focus.
        bool _picking;
        readonly Timer _tick = new Timer { Interval = 40 };
        readonly Stopwatch _clock = new Stopwatch();
        int _selected;
        //: Where the mouse was: only a real move selects the row under it, so
        //: a pointer resting over the window does not undo the keyboard.
        Point _mouse;
        int _footerHeight;
        //: The footer text's full height and how much of it shows, in pixels.
        int _footerText;
        int _footerShown;
        //: How far the footer text is scrolled up, and which text that was for.
        int _footerScroll;
        string _scrolled;
        string _footer = IdleHint;
        Color _footerColor = Faint;
        bool? _ok;
        //: How long the last run of the running command's kind took; null when none ran this session.
        long? _last;
        //: What runs ("cts compare"), above the stage it reached.
        string _running;
        //: The row whose question the footer's line answers; null when none is asked.
        WidgetItem _asking;
        //: The keys pressed while a page chosen is still read (the branches
        //: come from git), pressed on it once it shows; null when no page is awaited.
        List<Action> _ahead;
        readonly TextBox _answer;

        //: Raised for a row the person chose that can run, with the cts
        //: arguments it runs (null for a page of the agent's own).
        public event Action<WidgetItem, string[]> Chosen;

        //: Raised by the Copy link of a failure shown, or Ctrl+C on it.
        public event Action CopyAsked;

        //: The rows chosen since the menu, "5 Branches", "2 feature-x": the report's trail.
        readonly List<string> _trail = new List<string>();
        //: The failure shown went to the clipboard.
        bool _copied;

        public IList<string> Trail => _trail.ToList();

        //: The footer's text: the line the last run showed, or a hint.
        public string Footer => _footer;

        // The footer shows a failure: the Copy link is there.
        bool CopyShown => !Running && _ok == false;

        // What the header shows, for the report: the branch line, the last
        // commit, the state and the sync folder line.
        public IList<KeyValuePair<string, string>> Facts => new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("branch", _branch + (_commit != null ? "  " + _commit : "")),
            new KeyValuePair<string, string>("state", _state),
            new KeyValuePair<string, string>("sync folder", _place),
            new KeyValuePair<string, string>("plc", _online ? "online" : "offline"),
        };

        public bool Running { get; private set; }

        //: WidgetMenu.Busy while a compare of the folder runs, else null.
        string _busy;

        public WidgetView(string branch, bool online, string place, List<WidgetItem> items)
        {
            _branch = branch;
            _online = online;
            _place = place;
            _menu = items;
            _items = items;
            _selected = Math.Max(0, items.FindIndex(item => item.Disabled == null));
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            KeyPreview = true;
            BackColor = Back;
            DoubleBuffered = true;
            Text = "cts";
            _answer = new TextBox { BorderStyle = BorderStyle.None, BackColor = Badge, ForeColor = Ink, Font = _mono, Visible = false };
            Controls.Add(_answer);
            Relayout();
            _tick.Tick += (s, e) =>
            {
                if (Running) Invalidate(FooterRect());
                else _tick.Stop();
            };
            Shown += (s, e) => _mouse = PointToClient(Cursor.Position);
            Deactivate += (s, e) => { if (!Running && !_picking) Close(); };
            FormClosed += (s, e) => _tick.Dispose();
        }

        protected override CreateParams CreateParams
        {
            get
            {
                const int CS_DROPSHADOW = 0x20000;
                var create = base.CreateParams;
                create.ClassStyle |= CS_DROPSHADOW;
                return create;
            }
        }

        // The branch arrives after the window shows: git is a process, and the
        // window must not wait for one.
        public void ShowBranch(string branch, string commit)
        {
            _branch = branch;
            _commit = commit;
            Invalidate(new Rectangle(0, 0, Width0, HeaderHeight));
        }

        // The state line arrives later too: it is a `cts compare`.
        public void ShowState(string state, WidgetTone tone)
        {
            _state = state;
            _tone = tone;
            Invalidate(new Rectangle(0, 0, Width0, HeaderHeight));
        }

        // A page (the branches, the settings) in place of the menu, with its
        // *hint* in the footer; *note* replaces the hint (the last run's line,
        // kept while the page is read again).  *level* is how deep it is,
        // *up* what shows the page above it (kept from the last page of that
        // level when null).  A permission switched stays selected.
        public void ShowList(List<WidgetItem> items, string hint, string note, int level = 1, Action up = null)
        {
            var box = _inList && _selected < _items.Count ? _items[_selected].Toggles : null;
            _items = items;
            _inList = true;
            _listHint = hint;
            _level = level;
            if (up != null) _up[level] = up;
            var same = box != null ? items.FindIndex(item => item.Toggles == box) : -1;
            if (same < 0 && _returning) same = Opened(items, level);
            _returning = false;
            _selected = same >= 0 ? same : Math.Max(0, items.FindIndex(item => item.Disabled == null));
            if (note == null) { _ok = null; _footer = hint; _footerColor = Faint; }
            Relayout();
            PressAhead();
        }

        // The keys typed ahead of the page, now on it.
        void PressAhead()
        {
            var ahead = _ahead;
            _ahead = null;
            if (ahead == null) return;
            foreach (var press in ahead) press();
        }

        // A key while a page is awaited waits for it: true when kept.
        bool Later(Action press)
        {
            if (_ahead == null) return false;
            _ahead.Add(press);
            return true;
        }

        // A question in place of the menu: *items* are the answers, *question*
        // stays in the footer until one runs; *hint* says what Esc keeps.
        public void ShowChoice(List<WidgetItem> items, string question, string hint)
        {
            _ahead = null;
            Running = false;
            _clock.Stop();
            _items = items;
            _inList = true;
            _level = 1;
            _listHint = hint;
            _selected = Math.Max(0, items.FindIndex(item => item.Disabled == null));
            _ok = null;
            _footer = question;
            _footerColor = Warn;
            Relayout();
        }

        // ← and Esc: the page above, the menu from a page of the first level;
        // false on the menu itself.
        bool Up()
        {
            Action up;
            if (_level > 1 && _up.TryGetValue(_level, out up)) { _returning = true; up(); return true; }
            if (!_inList) return false;
            BackToMenu();
            return true;
        }

        void BackToMenu()
        {
            _trail.Clear();
            _items = _menu;
            _inList = false;
            _level = 0;
            var opened = Opened(_items, 0);
            _selected = opened >= 0 ? opened : Math.Max(0, _items.FindIndex(item => item.Disabled == null));
            Idle();
        }

        void Idle()
        {
            _ok = null;
            _footer = _inList ? _listHint : IdleHint;
            _footerColor = Faint;
            Relayout();
        }

        void Ask(WidgetItem item)
        {
            _asking = item;
            _ok = null;
            _footer = item.Asks + ":   Enter runs cts " + string.Join(" ", item.Args.Take(2))
                + (item.Picks != null ? ", F4 or ... picks a folder" : "") + ", Esc cancels";
            _footerColor = Muted;
            _answer.Text = item.Initial ?? "";
            _answer.Visible = true;
            Relayout();
            _answer.Focus();
            _answer.SelectAll();
        }

        void Pick(WidgetItem item)
        {
            _picking = true;
            string picked;
            try { picked = FolderPicker.Pick(this, item.Picks, item.Initial); }
            finally { _picking = false; }
            Activate();
            if (picked != null) Chosen?.Invoke(item, WidgetMenu.Answered(item, picked));
        }

        // The folder dialog over the line: the folder chosen replaces what is
        // typed, for Enter to run.  It opens where the line points when that
        // is a full path, else where the row suggested.
        void Browse()
        {
            var typed = _answer.Text.Trim();
            var initial = typed.Length > 0 && System.IO.Path.IsPathRooted(typed) ? typed : _asking.Initial;
            _picking = true;
            string picked;
            try { picked = FolderPicker.Pick(this, _asking.Picks, initial); }
            finally { _picking = false; }
            Activate();
            if (picked == null) { _answer.Focus(); return; }
            _answer.Text = picked;
            _answer.Focus();
            _answer.SelectionStart = picked.Length;
        }

        // The typed line runs the row; with nothing typed the line stays.
        void Answer()
        {
            var args = WidgetMenu.Answered(_asking, _answer.Text);
            if (args == null) return;
            var item = _asking;
            StopAsking();
            Chosen?.Invoke(item, args);
        }

        void StopAsking()
        {
            _asking = null;
            _answer.Visible = false;
            Focus();
        }

        // Why *item* cannot run now; null when it can.
        string Blocked(WidgetItem item)
        {
            return item.Disabled ?? (_busy != null && WidgetMenu.WaitsForCompare(item) ? _busy : null);
        }

        // A row that cannot run says why in the footer, in the warning colour.
        void Explain(string reason)
        {
            _ok = null;
            _footer = reason;
            _footerColor = Warn;
            Relayout();
        }

        // The row of *items* that opened the page below *level*, -1 when none did.
        int Opened(List<WidgetItem> items, int level)
        {
            string label;
            return _opened.TryGetValue(level, out label) ? items.FindIndex(item => item.Label == label) : -1;
        }

        // *forced*: Shift with the digit or the click, the row's Forced run.
        void Choose(WidgetItem item, bool forced = false)
        {
            if (item == null || Running) return;
            forced = forced && item.Forced != null;
            _selected = _items.IndexOf(item);
            if (item.Opens != WidgetPage.None) _opened[_inList ? _level : 0] = item.Label;
            if (_asking != null) StopAsking();
            var blocked = Blocked(item);
            if (blocked != null) { Explain(blocked); return; }
            _trail.Add((item.Key == '\0' ? "" : (forced ? "Shift+" : "") + item.Key + " ") + item.Label);
            if (item.Asks != null) { Ask(item); return; }
            if (item.Picks != null) { Pick(item); return; }
            // A page may show at once or after git answers: keys wait for it.
            if (item.Opens != WidgetPage.None) _ahead = new List<Action>();
            Chosen?.Invoke(item, forced ? item.Forced : item.Args);
            Invalidate();
        }

        Rectangle FooterRect()
        {
            return new Rectangle(0, HeaderHeight + _items.Count * RowHeight, Width, _footerHeight);
        }

        // The answer's box, at the bottom of the footer.
        Rectangle AnswerRect()
        {
            var area = FooterRect();
            return new Rectangle(Side, area.Bottom - AnswerHeight, Width0 - 2 * Side, AnswerHeight - 12);
        }

        // The "..." at the right end of the answer's box, for a row that also
        // picks: a click opens the folder dialog.
        Rectangle BrowseRect()
        {
            var line = AnswerRect();
            return new Rectangle(line.Right - BrowseWidth, line.Top, BrowseWidth, line.Height);
        }

        // The Copy link at the footer's right, level with its first line.
        Rectangle CopyRect()
        {
            var area = FooterRect();
            var width = CopyWidth();
            return new Rectangle(Width0 - Side - width, area.Top + 10, width, 24);
        }

        int CopyWidth()
        {
            return TextRenderer.MeasureText("Copied", _small, Size.Empty, TextFormatFlags.NoPadding).Width + 16;
        }

        // The room at the footer's right the text keeps clear of: the seconds
        // while a run goes, the Copy link under a failure.
        int Reserved()
        {
            return Running ? ClockWidth() : CopyShown ? CopyWidth() + 8 : 0;
        }

        void Relayout()
        {
            var text = TextRenderer.MeasureText(_footer, _mono, new Size(Width0 - 2 * Side - 28 - Reserved(), 0),
                TextFormatFlags.WordBreak | TextFormatFlags.NoPadding);
            if (_scrolled != _footer) { _footerScroll = 0; _scrolled = _footer; }
            _footerText = text.Height;
            _footerShown = Math.Min(text.Height, FooterRoom());
            _footerScroll = Math.Max(0, Math.Min(_footerScroll, _footerText - _footerShown));
            _footerHeight = Math.Max(44, _footerShown + 24) + (_asking != null ? AnswerHeight : 0);
            ClientSize = new Size(Width0, HeaderHeight + _items.Count * RowHeight + _footerHeight);
            var line = AnswerRect();
            line.Inflate(-10, -7);
            if (_asking != null && _asking.Picks != null) line.Width -= BrowseWidth;
            _answer.Bounds = line;
            using (var path = Rounded(new Rectangle(0, 0, Width, Height), Radius))
                Region = new Region(path);
            Invalidate();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _title.Dispose();
                _body.Dispose();
                _small.Dispose();
                _key.Dispose();
                _mono.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
