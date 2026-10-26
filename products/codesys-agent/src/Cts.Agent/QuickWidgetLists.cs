using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Cts.Agent
{
    // The lists the window shows (state, branches, comparisons, settings) and the side windows.
    internal sealed partial class QuickWidget
    {
        // The compare MirrorRefresh runs while nobody works: its cache of the
        // IDE's view is what the next compare reads.
        internal void Refresh(string folder)
        {
            _cts.Run(new[] { "compare" }, folder, (ok, line) => { }, false, null, false);
        }

        // What changed on each side since the last sync, into the header.
        void ReadState(WidgetView view, string folder)
        {
            _cts.Run(new[] { "compare" }, folder, (ok, line) => WindowThread.Later(view, () => ShowState(view, ok, line)));
        }

        void ShowState(WidgetView view, bool ok, string line)
        {
            WidgetTone tone;
            _both = WidgetMenu.Both(ok ? line : null);
            var state = WidgetMenu.State(ok ? line : null, out tone);
            view.ShowState(state, tone, WidgetMenu.IdeEdits(ok ? line : null));
        }

        // The header's branch, read off the UI thread.  With *fetch* the
        // branch's remote is fetched after it (at most once a minute per
        // folder) and the counts shown again when they moved: the team's new
        // commits show as ↓ before anyone pulls.
        void ReadWhere(WidgetView view, string folder, bool fetch)
        {
            Task.Run(() =>
            {
                string detached;
                var branch = SyncGit.Branch(folder, out detached);
                var counts = SyncGit.Tracking(folder, branch);
                var commit = SyncGit.LastCommit(folder);
                WindowThread.Later(view, () => view.ShowBranch(WidgetMenu.Where(branch, detached, counts), commit));
                if (!fetch || counts == null || !FetchDue(folder)) return;
                if (!SyncGit.Fetch(folder))
                {
                    _log.Write("widget: git fetch in " + folder + " failed or took over " + SyncGit.FetchWaitMs / 1000 + " s");
                    return;
                }
                var fetched = SyncGit.Tracking(folder, branch);
                if (fetched != counts) WindowThread.Later(view, () => view.ShowBranch(WidgetMenu.Where(branch, detached, fetched), commit));
            });
        }

        bool FetchDue(string folder)
        {
            lock (_fetched)
            {
                DateTime last;
                if (_fetched.TryGetValue(folder, out last) && DateTime.UtcNow - last < FetchEvery) return false;
                _fetched[folder] = DateTime.UtcNow;
                return true;
            }
        }

        // A command that failed on what the next one fixes: a push refused
        // for the team's commits pulls them first.
        static void OfferNext(WidgetView view, string line)
        {
            string question;
            var answers = WidgetMenu.Pulling(line, view.Online, out question);
            if (answers != null) view.ShowChoice(answers, question, PullsLater);
        }

        // After a commit, or a pull that left the branch ahead of its
        // upstream (*whenAhead*: this PC's commits merged with the team's),
        // whether the branch goes to the team now (`cts push`), asked when
        // the repository has a remote to push to.
        void OfferPush(WidgetView view, string folder, string line, bool whenAhead)
        {
            Task.Run(() =>
            {
                if (string.IsNullOrWhiteSpace(SyncGit.Git(folder, "remote", true))) return;
                string detached;
                if (whenAhead && WidgetMenu.Ahead(SyncGit.Tracking(folder, SyncGit.Branch(folder, out detached))) == 0) return;
                string question;
                var answers = WidgetMenu.Pushing(line, out question);
                WindowThread.Later(view, () => view.ShowChoice(answers, question, KeepsHere));
            });
        }

        // Once a session per folder, when git on this PC changes its line
        // endings: whether to keep its files as written.  Asked only while
        // the menu shows, idle.
        void OfferLineEndings(WidgetView view, string folder)
        {
            lock (_eolAsked) if (!_eolAsked.Add(folder)) return;
            Task.Run(() =>
            {
                if (!GitFolder.ConvertsLineEndings(folder)) return;
                string question;
                var answers = WidgetMenu.LineEndings(folder, out question);
                WindowThread.Later(view, () => { if (view.OnMenu) view.ShowChoice(answers, question, AsksNextSession); });
            });
        }

        // The local branches, most recent first, read off the UI thread.
        void ListBranches(WidgetView view, string folder, string note)
        {
            Task.Run(() =>
            {
                string detached;
                var current = SyncGit.Branch(folder, out detached);
                var counts = SyncGit.Tracking(folder, current);
                var items = WidgetMenu.Branches(SyncGit.BranchNames(folder), current, counts != null, view.Online);
                var where = WidgetMenu.Where(current, detached, counts);
                var commit = SyncGit.LastCommit(folder);
                WindowThread.Later(view, () =>
                {
                    view.ShowBranch(where, commit);
                    view.ShowList(items, items.Count > 1 ? BranchHint : "no local branch", note);
                });
            });
        }

        // The compare page: the disk, then the local branches, read off the UI thread.
        void ListComparisons(WidgetView view, string folder)
        {
            Task.Run(() =>
            {
                string detached;
                var items = WidgetMenu.Comparisons(SyncGit.BranchNames(folder), SyncGit.Branch(folder, out detached));
                WindowThread.Later(view, () => view.ShowList(items, CompareHint, null));
            });
        }

        // The settings as last read; read again when the window has none.
        void ListSettings(WidgetView view, string folder, string note)
        {
            var settings = _settings ?? (_settings = ReadSettings(folder));
            Action show = () => view.ShowList(
                WidgetMenu.Settings(folder, _suggested, _known, settings.Result.Tools, settings.Result.Config, _ide.DenyList(), _owner),
                SettingsHint, note ?? settings.Result.Error);
            if (settings.IsCompleted) show();
            else settings.ContinueWith(_ => WindowThread.Later(view, show));
        }

        // `cts tool --json` (on the sync folder when there is one) and `cts
        // config show --json`, side by side off the UI thread.
        Task<SettingsRead> ReadSettings(string folder)
        {
            var tools = _cts.Whole(new[] { "tool", "--json" }, folder);
            var config = _cts.Whole(new[] { "config", "show", "--json" }, folder);
            return Task.WhenAll(tools, config).ContinueWith(_ => new SettingsRead
            {
                Tools = tools.Result.Item1 ? tools.Result.Item2 : null,
                Config = config.Result.Item1 ? config.Result.Item2 : null,
                Error = config.Result.Item1 ? null : config.Result.Item2,
            });
        }

        // A compare of the state started (+1) or ended (-1): the open window
        // greys out the rows that wait for it while any runs.
        void Comparing(int step)
        {
            _ui.Post(_ =>
            {
                _comparing += step;
                (_form as WidgetView)?.ShowBusy(_comparing > 0 ? WidgetMenu.Busy : null);
            }, null);
        }

        // One activity window per IDE, brought forward when it is already open.
        void ShowActivity()
        {
            if (_activity != null) { _activity.Activate(); return; }
            var main = Process.GetCurrentProcess().MainWindowHandle;
            var path = Convert.ToString(_ide.ProjectStatus().TryGetValue("path", out var p) ? p : "");
            var title = "cts agent · ide-" + Process.GetCurrentProcess().Id + (path.Length > 0 ? " · " + System.IO.Path.GetFileNameWithoutExtension(path) : "");
            var view = new ActivityView(_log, _router, title);
            var area = Screen.FromHandle(main).WorkingArea;
            view.Location = new Point(area.Right - view.Width - 24, area.Bottom - view.Height - 24);
            view.FormClosed += (s, e) => _activity = null;
            _activity = view;
            view.Show(new Owner(main));
        }

        // One format window, one FSM window and one analysis window per IDE; they read the project themselves.
        internal void ShowFormat()
        {
            if (_format != null) { _format.Activate(); return; }
            _format = Open("cts fmt", (title, cts) => new FmtView(title, cts));
            _format.FormClosed += (s, e) => _format = null;
        }

        // The conflict window on what a dry run of 1 or 2 found; its runs move the state the next window shows.
        void ShowConflicts(List<ConflictItem> items, WidgetItem row)
        {
            _conflicts?.Close();
            _conflicts = Open("cts " + row.Args[0] + ": the same lines changed on both sides",
                (title, cts) => new ConflictView(title, items, row.Args[0], row.Forced, cts));
            _conflicts.FormClosed += (s, e) => _conflicts = null;
        }

        internal void ShowFsm()
        {
            if (_fsm != null) { _fsm.Activate(); return; }
            _fsm = Open("cts fsm", (title, cts) => new FsmView(title, cts));
            _fsm.FormClosed += (s, e) => _fsm = null;
        }

        internal void ShowAnalysis()
        {
            if (_analysis != null) { _analysis.Activate(); return; }
            _analysis = Open("cts analyze", (title, cts) => new AnalysisView(title, cts));
            _analysis.FormClosed += (s, e) => _analysis = null;
        }

        // The window *make* builds, centred on the IDE's screen and shown.
        Form Open(string name, Func<string, Action<string[], bool, Action<bool, string>>, Form> make)
        {
            var status = _ide.ProjectStatus();
            var folder = status.TryGetValue("sync_folder", out var synced) ? Convert.ToString(synced) : "";
            var path = status.TryGetValue("path", out var file) ? Convert.ToString(file) : "";
            var main = Process.GetCurrentProcess().MainWindowHandle;
            Form view = null;
            view = make(name + (path.Length > 0 ? " · " + Path.GetFileNameWithoutExtension(path) : ""),
                (args, whole, done) => _cts.Run(args, folder, done, whole, line =>
                {
                    var stage = WidgetMenu.Stage(line);
                    if (stage != null) (view as IStages)?.Stage(stage);
                }, timed: false));
            var area = Screen.FromHandle(main).WorkingArea;
            view.Location = new Point(area.Left + Math.Max(0, (area.Width - view.Width) / 2), area.Top + Math.Max(0, (area.Height - view.Height) / 2));
            view.Show(new Owner(main));
            return view;
        }
    }
}
