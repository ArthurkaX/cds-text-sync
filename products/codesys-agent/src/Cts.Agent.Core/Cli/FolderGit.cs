using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // Where the sync folder's repository is, for `cts status`.
    public static class FolderGit
    {
        // {branch, commit, uncommitted}; {repository: null} without one;
        // {error} when git fails or refuses the repository. The open
        // project's own file is not counted as uncommitted: every save
        // changes it, and the view is what a checkout carries.
        public static Dictionary<string, object> Position(string folder, string project)
        {
            if (!Directory.Exists(folder)) return None();
            GitRun top;
            try { top = GitRun.In(folder, "rev-parse --show-cdup"); }
            catch (InvalidOperationException error) { return Failed(error.Message); }
            if (top.ExitCode != 0)
            {
                var message = top.Message;
                return message.Length == 0 || message.Contains("not a git repository")
                    ? None()
                    : Failed("git refuses the repository at " + folder + ": " + message);
            }
            var root = GitRepository.RootOf(folder, top.Output);
            var position = GitRepository.Position(root);
            var status = GitRun.In(root, "status --porcelain=v1 -z");
            if (status.ExitCode != 0) return Failed("git status failed: " + status.Message);
            var answer = new Dictionary<string, object>
            {
                { "branch", position["branch"] },
                { "commit", position["commit"] },
                { "uncommitted", (long)Uncommitted(root, status.Output, project).Count },
            };
            if (Changed(status.Output).Any(path => Same(Path.Combine(root, path), project))) answer["project_file_changed"] = true;
            return answer;
        }

        // The uncommitted paths of the repository at *root*; refused when git
        // cannot tell. The open *project*'s own file does not count.
        internal static IList<string> Uncommitted(string root, string project)
        {
            var status = GitRun.In(root, "status --porcelain=v1 -z");
            if (status.ExitCode != 0) throw new InvalidOperationException("git status failed: " + status.Message);
            return Uncommitted(root, status.Output, project);
        }

        static IList<string> Uncommitted(string root, string porcelain, string project) =>
            Changed(porcelain).Where(path => !Same(Path.Combine(root, path), project)).ToList();

        // The paths of `git status --porcelain=v1 -z`; a rename's source,
        // the entry after it, is not one.
        static IEnumerable<string> Changed(string porcelain)
        {
            var entries = porcelain.Split('\0');
            for (var i = 0; i < entries.Length; i++)
            {
                if (entries[i].Length < 4) continue;
                yield return entries[i].Substring(3);
                if (entries[i][0] == 'R' || entries[i][0] == 'C') i++;
            }
        }

        static bool Same(string path, string project)
        {
            if (string.IsNullOrEmpty(project)) return false;
            try { return string.Equals(Path.GetFullPath(path), Path.GetFullPath(project), StringComparison.OrdinalIgnoreCase); }
            catch (Exception e) when (e is ArgumentException || e is NotSupportedException) { return false; }
        }

        static Dictionary<string, object> None() => new Dictionary<string, object> { { "repository", null } };

        static Dictionary<string, object> Failed(string error) => new Dictionary<string, object> { { "error", error } };
    }
}
