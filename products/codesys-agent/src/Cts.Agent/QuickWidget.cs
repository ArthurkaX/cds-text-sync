// The quick widget: Alt+Q while the IDE has the focus opens a small window
// over it with the work branch and the numbered actions of WidgetMenu.  It
// shows at once; the branch (a git process) fills in when git answers, with
// how far it is from its upstream, and again after a quiet fetch.  A
// digit or a click runs that cts command in its own process -- the logic
// stays in cts, and a person sees the verdict line an agent reads -- and the
// window shows the line when it is done.  The header names what changed on
// each side since the last sync (a `cts compare` run as the window opens and
// after a command that moves it).  It is quick while the IDE's mirror is
// current, which MirrorRefresh sees to while nobody works (Refresh); a window
// opened while a compare runs greys the rows that wait for it.  A command's
// footer shows the stages cts names (CTS_PROGRESS).  Digits 1 and 2 carry one side's
// edits to the other, merging an object both changed and opening overlapping
// edits side by side; Shift with the digit makes one side the other
// (`--force`).  Digit 4 lists the sync folder's
// local branches in the same window; one chosen is `cts checkout --disk-only`:
// the disk moves, the IDE does not, so Compare and Disk → IDE come next.
// Its first row starts a new branch where the work is (`cts branch NAME`),
// and digit 5 commits (`cts commit -m`): with the IDE's edits, a person forks
// a branch, works and records it without leaving the IDE.  Digit 7 opens the
// sync folder in the person's git program, where branches are merged.  Digit
// 8 lists the settings: the sync folder, the programs, this window's key, the project's
// permissions (groups of keys, each allowed or blocked, switched by the agent itself), then the
// project settings `cts config show` reports, each changed by its own cts
// command.  Digit 0 opens what is used now and then: the format window, the
// activity, the line that points an AI agent at this IDE.
//
// The key is a keyboard hook on the IDE's UI thread only, not a global hotkey:
// other programs keep their Alt+Q, and with two IDEs open each one answers for
// its own project.  The user may choose another chord (QuickKey: quick_key in
// their defaults.json); the hook reads the file again when it changes, so a
// new key works at once (the run's CTS_IDE_PID names this IDE to cts).  The window
// is modeless and owned by the IDE's main window, so the commands it runs can
// still reach the IDE; while a dialog of the IDE is open it does not open.
// Each run is kept whole (WidgetRun): a failure's Copy link puts a report of
// it and the runs before it on the clipboard (WidgetReport).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal sealed partial class QuickWidget
    {
        const int WH_KEYBOARD = 2;
        const int VK_SHIFT = 0x10;
        const int VK_CONTROL = 0x11;
        const int VK_ESCAPE = 0x1B;

        readonly Ide _ide;
        readonly ModalState _modal;
        readonly FileLog _log;
        readonly Router _router;
        Win32.HookProc _proc;
        IntPtr _hook;
        Form _form;
        Form _activity;
        Form _format;
        Form _fsm;
        Form _analysis;
        //: The open project's name as the window last opened on it, "" when unsaved.
        string _project = "";
        //: The folder offered while the project has no sync folder here, and
        //: whether the project has an id (its folder is a clone elsewhere).
        string _suggested = "";
        bool _known;
        bool _owner;
        bool _noProject;
        IList<KnownProject> _knownProjects = new List<KnownProject>();
        //: The main menu as the window last opened, its open row named after the program.
        List<WidgetItem> _menu = new List<WidgetItem>();
        //: The user's defaults.json, where the chord is chosen.
        readonly string _defaults = UserDefaults.Path;
        QuickKey _key = QuickKey.Default;
        DateTime _keyRead = DateTime.MinValue;
        // When each sync folder's remote was last fetched for the header.
        readonly Dictionary<string, DateTime> _fetched = new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
        static readonly TimeSpan FetchEvery = TimeSpan.FromMinutes(1);
        SynchronizationContext _ui;
        //: The compares of the state running now, counted on the UI thread.
        int _comparing;
        //: The settings as cts reported them, read as the window opens and
        //: again after a command changes one: pages go back to them at once.
        Task<SettingsRead> _settings;
        readonly CtsRunner _cts;

        public QuickWidget(Ide ide, ModalState modal, FileLog log, Router router)
        {
            _ide = ide;
            _modal = modal;
            _log = log;
            _router = router;
            _cts = new CtsRunner(log, Comparing);
        }

        // Runs on the UI thread, like the loader that calls AgentHost.Start:
        // the hook belongs to the thread that sets it.
        public void Start()
        {
            _proc = OnKey;
            _hook = Win32.SetWindowsHookEx(WH_KEYBOARD, _proc, IntPtr.Zero, Win32.GetCurrentThreadId());
            ReadKey();
            _log.Write(_hook == IntPtr.Zero ? "widget: the keyboard hook was refused" : "widget: " + _key.Text + " opens it");
            _ui = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
        }

        public void Stop()
        {
            if (_hook != IntPtr.Zero) Win32.UnhookWindowsHookEx(_hook);
            _hook = IntPtr.Zero;
            foreach (var form in new[] { _form, _activity })
                if (form != null && form.IsHandleCreated) form.BeginInvoke(new Action(form.Close));
        }

        IntPtr OnKey(int code, IntPtr key, IntPtr flags)
        {
            var bits = flags.ToInt64();
            var down = (bits & (1L << 31)) == 0;
            // Esc goes to the window before the IDE sees it: the IDE takes it
            // for itself, activates its own window and the widget closes, so
            // Esc on a page would close instead of going back up.
            var view = _form as WidgetView;
            if (code == 0 && key.ToInt64() == VK_ESCAPE && view != null && Form.ActiveForm == view)
            {
                if (down) view.Escape();
                return (IntPtr)1;
            }
            var alt = (bits & (1L << 29)) != 0;
            var ctrl = Win32.GetKeyState(VK_CONTROL) < 0;
            var shift = Win32.GetKeyState(VK_SHIFT) < 0;
            if (code == 0 && down && (alt || ctrl || key.ToInt64() >= 0x70 && key.ToInt64() <= 0x7B) && ReadKey())
                _log.Write("widget: " + _key.Text + " opens it");
            if (code == 0 && down && _key.Matches((int)key.ToInt64(), ctrl, alt, shift) && !_modal.AnyOpen)
            {
                try { Toggle(); }
                catch (Exception e) { _log.Write("widget: " + e); }
                return (IntPtr)1;
            }
            return Win32.CallNextHookEx(_hook, code, key, flags);
        }

        // The chord from defaults.json when the file changed since it was read
        // (a missing one is Alt+Q); whether the chord is another now.  A key
        // pressed with a modifier asks, so the file is looked at only then.
        bool ReadKey()
        {
            try
            {
                var written = File.Exists(_defaults) ? File.GetLastWriteTimeUtc(_defaults) : DateTime.MinValue;
                if (written == _keyRead) return false;
                _keyRead = written;
                var key = written == DateTime.MinValue ? QuickKey.Default : QuickKey.FromDefaults(File.ReadAllText(_defaults));
                var changed = key.Text != _key.Text;
                _key = key;
                return changed;
            }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
        }

        const string BranchHint = "digit or ↑↓ Enter: switch the disk, pull the current   Esc back";
        const string CompareHint = "digit or ↑↓ Enter: open the IDE against it   Esc back";
        const string SettingsHint = "digit or ↑↓ Enter: change   → open   ← back";
        const string ChoicesHint = "digit or ↑↓ Enter: choose   ← back";
        const string GroupsHint = "digit or ↑↓ → Enter: open   ← back";
        const string BoxesHint = "Space or digit: allow / block   ← back";
        const string KeepsHere = "digit or ↑↓ Enter   Esc keeps it on this PC";
        const string PullsLater = "digit or ↑↓ Enter   Esc pulls later";

        void Toggle()
        {
            if (_form != null) _form.Close();
            else Open();
        }

        internal void ShowQuick()
        {
            if (_form != null)
            {
                _form.Activate();
                return;
            }
            Open();
        }

        WidgetView Open()
        {
            var status = _ide.ProjectStatus();
            var folder = status.ContainsKey("sync_folder") ? Convert.ToString(status["sync_folder"]) : "";
            var path = status.ContainsKey("path") ? Convert.ToString(status["path"]) : "";
            var plc = status.ContainsKey("plc") ? status["plc"] as Dictionary<string, object> : null;
            var online = plc != null && Equals(plc["online"], true);
            _project = path.Length > 0 ? Path.GetFileNameWithoutExtension(path) : "";
            _noProject = path.Length == 0;
            _knownProjects = _noProject ? ProjectInfo.Known() : new List<KnownProject>();
            _suggested = status.ContainsKey("suggested_sync_folder") ? Convert.ToString(status["suggested_sync_folder"]) : "";
            _known = status.ContainsKey("project_id");
            _owner = Equals(status.ContainsKey("owner") ? status["owner"] : null, true);
            _settings = ReadSettings(folder);
            var menu = _menu = _noProject
                ? WidgetMenu.NoProject(_knownProjects, KnownProjectFiles(_knownProjects.Take(WidgetMenu.KnownProjectRows)), Process.GetCurrentProcess().Id)
                : WidgetMenu.Items(online, folder, Process.GetCurrentProcess().Id, _project, _owner);
            var place = _noProject ? "open a project to sync it" : folder.Length > 0 ? folder : "no sync folder";
            var view = new WidgetView(_noProject ? "no project open" : folder.Length > 0 ? "…" : WidgetMenu.Unconnected(_known), online, place, menu);
            view.Chosen += (item, args) => Run(view, item, args, folder);
            view.CopyAsked += () => CopyReport(view, path);
            view.FormClosed += (s, e) => _form = null;
            var main = Process.GetCurrentProcess().MainWindowHandle;
            var area = Screen.FromHandle(main).WorkingArea;
            view.Location = new Point(area.Left + (area.Width - view.Width) / 2, area.Top + (area.Height - view.Height) / 3);
            _form = view;
            if (_comparing > 0) view.ShowBusy(WidgetMenu.Busy);
            view.Show(new Owner(main));
            view.Activate();
            if (_noProject) return view;
            NameOpener(view);
            if (folder.Length == 0)
            {
                ListSettings(view, folder, null);
                return view;
            }
            ReadWhere(view, folder, true);
            ReadState(view, folder);
            return view;
        }

        // The failure shown, with what led to it, onto the clipboard.
        void CopyReport(WidgetView view, string project)
        {
            IList<WidgetRun> runs = _cts.Runs;
            var facts = new List<KeyValuePair<string, string>>
            {
                new KeyValuePair<string, string>("project", project),
                new KeyValuePair<string, string>("agent", "built " + File.GetLastWriteTime(typeof(QuickWidget).Assembly.Location).ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture)
                    + ", CODESYS process " + Process.GetCurrentProcess().Id),
            };
            facts.AddRange(view.Facts);
            try
            {
                Clipboard.SetText(WidgetReport.Build(DateTime.Now, facts, view.Trail, runs, view.Footer));
                view.Copied();
            }
            catch (System.Runtime.InteropServices.ExternalException e) { _log.Write("widget: the clipboard refused the report: " + e.Message); }
        }

        static IDictionary<string, string> KnownProjectFiles(IEnumerable<KnownProject> projects)
        {
            var files = new Dictionary<string, string>();
            foreach (var project in projects)
            {
                try { files[project.Id] = ProjectInfo.ProjectFile(project.Folder); }
                catch (InvalidOperationException) { files[project.Id] = ""; }
            }
            return files;
        }

        void Run(WidgetView view, WidgetItem item, string[] args, string folder)
        {
            if (item.PicksProject)
            {
                PickProject(view);
                return;
            }
            if (item.OpensProject != null)
            {
                OpenProject(view, item.OpensProject);
                return;
            }
            if (item.WorkingFolder != null)
            {
                Execute(view, args, item.WorkingFolder);
                return;
            }
            if (item.Copies != null)
            {
                Clipboard.SetText(item.Copies);
                view.Finish(true, "Copied: " + item.Copies + "\nPaste it into the AI agent's chat.");
                return;
            }
            if (item.Toggles != null)
            {
                SwitchPermission(view, item.Toggles);
                return;
            }
            if (item.Opens == WidgetPage.Permissions)
            {
                if (item.Choices == null) ListPermissions(view, folder);
                else view.ShowList(item.Choices, BoxesHint, null, 3, () => ListPermissions(view, folder));
                return;
            }
            switch (item.Opens)
            {
                case WidgetPage.Activity:
                    view.Close();
                    ShowActivity();
                    return;
                case WidgetPage.More:
                    view.ShowList(item.Choices, ChoicesHint, null);
                    return;
                case WidgetPage.Format:
                    view.Close();
                    ShowFormat();
                    return;
                case WidgetPage.Fsm:
                    view.Close();
                    ShowFsm();
                    return;
                case WidgetPage.StaticAnalysis:
                    view.Close();
                    ShowAnalysis();
                    return;
                case WidgetPage.Branches:
                    ListBranches(view, folder, null);
                    return;
                case WidgetPage.Compare:
                    ListComparisons(view, folder);
                    return;
                case WidgetPage.Settings:
                    if (_noProject) ListNoProjectSettings(view, null);
                    else ListSettings(view, folder, null);
                    return;
                case WidgetPage.Choices:
                    view.ShowList(item.Choices, ChoicesHint, null, 2, () => ListSettings(view, folder, null));
                    return;
                case WidgetPage.None:
                    break;
            }
            Execute(view, args, folder);
        }

        void ListNoProjectSettings(WidgetView view, string note)
        {
            var settings = _settings ?? (_settings = ReadSettings(""));
            Action show = () => view.ShowList(WidgetMenu.NoProjectSettings(settings.Result.Tools, settings.Result.Config),
                SettingsHint, note ?? settings.Result.Error);
            if (settings.IsCompleted) show();
            else settings.ContinueWith(_ => WindowThread.Later(view, show));
        }

        void PickProject(WidgetView view)
        {
            using (var dialog = new OpenFileDialog
            {
                Filter = "CODESYS projects (*.project)|*.project",
                InitialDirectory = _knownProjects.FirstOrDefault()?.Folder ?? "",
                CheckFileExists = true,
                Multiselect = false,
            })
            {
                if (dialog.ShowDialog(new Owner(Process.GetCurrentProcess().MainWindowHandle)) == DialogResult.OK)
                    OpenProject(view, dialog.FileName);
            }
        }

        void OpenProject(WidgetView view, string path)
        {
            view.Close();
            try
            {
                // The quick window lives on the IDE's UI thread: OnUi would wait for the thread it holds.
                _ide.OpenProjectFile(path);
                Open();
            }
            catch (Exception error)
            {
                var reopened = Open();
                reopened.Finish(false, error.Message);
            }
        }

        // The permission groups, read again each time they show, under the settings.
        void ListPermissions(WidgetView view, string folder)
        {
            var deny = _ide.DenyList();
            if (deny == null) { view.Finish(false, "cds-text-sync.json is unreadable: fix the file"); return; }
            view.ShowList(WidgetMenu.PermissionGroups(deny), GroupsHint, null, 2, () => ListSettings(view, folder, null));
        }

        // A permission: the agent switches its key in the deny list and the
        // group's page shows the list now in force.
        void SwitchPermission(WidgetView view, string key)
        {
            List<string> deny;
            try { deny = _ide.TogglePermission(key); }
            catch (Exception e)
            {
                _log.Write("widget: permission " + key + ": " + e.Message);
                view.Finish(false, e.Message);
                return;
            }
            var line = (DenyRules.BlockedBy(deny, key) != null ? "blocked " : "allowed ") + key + " in cds-text-sync.json";
            _log.Write("widget: " + line);
            var group = WidgetMenu.PermissionGroups(deny).First(row => row.Choices.Any(box => box.Toggles == key));
            view.Finish(true, line);
            view.ShowList(group.Choices, BoxesHint, line, 3);
        }

        void Execute(WidgetView view, string[] args, string folder)
        {
            view.Start("cts " + ProcessArgs.Join(args), _cts.Took(args));
            _cts.Run(args, folder, (ok, line) => WindowThread.Later(view, () =>
            {
                // A new sync folder changes every row: the window opens again on it.
                if (args[0] == "set-sync-folder" && ok)
                {
                    view.Close();
                    Open().Finish(true, line);
                    return;
                }
                view.Finish(ok, line);
                if (!ok) OfferNext(view, line);
                if (WidgetMenu.MovesState(args)) ReadState(view, folder);
                // A commit moves the branch away from its upstream, a pull or a push towards it.
                if (args[0] == "commit" || args[0] == "project" || args[0] == "push") ReadWhere(view, folder, false);
                if (args[0] == "commit" && ok) OfferPush(view, folder, line, false);
                if (args[0] == "project" && args.Length > 1 && args[1] == "update" && ok) OfferPush(view, folder, line, true);
                // A checkout or a new branch moved the work: the header and the list follow.
                if (args[0] == "checkout" || args[0] == "branch") ListBranches(view, folder, line);
                if (args[0] == "config" || args[0] == "set-sync-folder" || args[0] == "tool")
                {
                    _settings = ReadSettings(folder);
                    ListSettings(view, folder, line);
                    NameOpener(view);
                }
            }), false, Stages(view));
        }

        // The open row says the program once `cts tool` named it.
        void NameOpener(WidgetView view)
        {
            var menu = _menu;
            _settings.ContinueWith(read => WindowThread.Later(view, () =>
            {
                if (WidgetMenu.NameOpener(menu, read.Result.Tools)) view.Invalidate();
            }));
        }

        // Each stage a run's stderr names, into the footer.
        static Action<string> Stages(WidgetView view)
        {
            return text =>
            {
                var stage = WidgetMenu.Stage(text);
                if (stage != null) WindowThread.Later(view, () => view.Progress(stage));
            };
        }

        // Whether a cts this window started still runs.
        internal bool Busy => _cts.Running;

        sealed class SettingsRead
        {
            public string Tools;
            public string Config;
            public string Error;
        }

        sealed class Owner : IWin32Window
        {
            public Owner(IntPtr handle) { Handle = handle; }
            public IntPtr Handle { get; private set; }
        }
    }

    // A window that shows the stage its cts run reached ("rule 12/90
    // CTS0013"); told from cts's reading thread.
    internal interface IStages
    {
        void Stage(string stage);
    }
}
