using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace Cts.Agent
{
    // The problem report (WidgetReport): what it holds is said first; made, it
    // goes onto the clipboard and into a text file, and the window offers
    // Notepad, a new GitHub issue and Discord.
    internal sealed partial class QuickWidget
    {
        //: The failure the Report link was under and the rows that led to it; null from the menu.
        string _reportShown;
        IList<string> _reportTrail;

        void AskReport(WidgetView view, string shown)
        {
            _reportShown = shown;
            _reportTrail = shown == null ? null : view.Trail;
            string question;
            view.ShowChoice(WidgetMenu.Reporting(out question), question, NotNow);
        }

        // `cts diag` on the sync folder, then the report with every name the
        // agent knows replaced: the project's objects (read here, on the UI
        // thread), its files and branches, the folder, the user and the PC.
        void MakeReport(WidgetView view, string folder)
        {
            var runs = _cts.Runs;
            var log = _log.Recent();
            var shown = _reportShown;
            var trail = _reportTrail;
            var names = new List<KeyValuePair<string, string>>();
            if (!_noProject)
            {
                try { names.AddRange(_ide.ObjectNames().Select(name => Named(name, "object"))); }
                catch (Exception e) { _log.Write("widget: the report knows no object names: " + e.Message); }
            }
            names.Add(Named(_project, "project"));
            view.Start("cts diag", null);
            _cts.Run(new[] { "diag" }, folder, (ok, said) =>
            {
                names.AddRange(FolderNames(folder));
                var report = WidgetReport.Build(DateTime.Now, said, trail, shown, runs, log, new Redaction(names));
                WindowThread.Later(view, () => SendReport(view, report));
            }, true, null, false);
        }

        // The sync folder's own names: its last two folders, its branches and
        // the files and folders git tracks there; the user's and the PC's.
        static IEnumerable<KeyValuePair<string, string>> FolderNames(string folder)
        {
            var names = new List<KeyValuePair<string, string>>
            {
                Named(Environment.UserName, "user"), Named(Environment.MachineName, "pc"), Named(Environment.UserDomainName, "pc"),
            };
            if (folder.Length == 0) return names;
            names.AddRange(folder.Split('\\', '/').Reverse().Take(2).Select(part => Named(part, "folder")));
            names.AddRange(SyncGit.BranchNames(folder).Select(name => Named(name, "branch")));
            foreach (var file in (SyncGit.Git(folder, "-c core.quotepath=false ls-files", true) ?? "").Split('\n'))
            {
                var parts = file.Trim().Split('/');
                names.AddRange(parts.Take(parts.Length - 1).Select(part => Named(part, "folder")));
                names.Add(Named(Path.GetFileNameWithoutExtension(parts[parts.Length - 1]), "object"));
            }
            return names;
        }

        static KeyValuePair<string, string> Named(string name, string kind) => new KeyValuePair<string, string>(name ?? "", kind);

        void SendReport(WidgetView view, string report)
        {
            var file = Path.Combine(Path.GetTempPath(), "cts-report-" + DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".txt");
            try
            {
                File.WriteAllText(file, report.Replace("\r\n", "\n").Replace("\n", "\r\n"), new UTF8Encoding(false));
                Clipboard.SetText(report);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is ExternalException)
            {
                _log.Write("widget: the report: " + e.Message);
                view.Finish(false, "the report was not made: " + e.Message);
                return;
            }
            string question;
            view.ShowChoice(WidgetMenu.Sending(file, out question), question, NotNow);
        }

        // A file or a web page in the program Windows has for it; the window
        // closes as that program takes the focus.
        void Launch(WidgetView view, string target)
        {
            try { Process.Start(new ProcessStartInfo(target) { UseShellExecute = true }); }
            catch (Win32Exception e)
            {
                _log.Write("widget: " + target + " did not open: " + e.Message);
                view.Finish(false, target + " did not open: " + e.Message);
            }
        }
    }
}
