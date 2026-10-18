using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Sync
{
    // The view files Git's ignore rules match (.gitignore, .git/info/exclude,
    // the global excludes file), tracked ones too: an engineer who leaves the
    // task configuration, the alarms or the devices to the project's owner
    // lists them there. Export neither writes nor removes such a file, import
    // does not apply it, and compare does not report it. A folder object's
    // file is <folder>/.cds-object.xml, so a pattern ending in / takes the
    // folder with everything below it.
    internal static class ViewIgnore
    {
        const string ApplicationType = "639b491f-5557-464c-af91-1471bac9f549";
        const int Named = 5;

        // The ones of *paths* (relative to the view) the rules match; none
        // outside a work tree.
        internal static ISet<string> Match(string folder, string relativeView, IEnumerable<string> paths)
        {
            var ignored = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var list = paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            if (list.Count == 0) return ignored;
            var prefix = relativeView == "." ? "" : relativeView.TrimEnd('/') + "/";
            using (var process = GitRun.Start(folder, "check-ignore --no-index -z --stdin", null, true, true, true))
            {
                var error = process.StandardError.ReadToEndAsync();
                var output = process.StandardOutput.ReadToEndAsync();
                // Outside a work tree git exits before it reads the paths: its exit code says so.
                try
                {
                    using (var stream = process.StandardInput.BaseStream)
                    {
                        var bytes = new UTF8Encoding(false).GetBytes(string.Concat(list.Select(path => prefix + path + "\0")));
                        stream.Write(bytes, 0, bytes.Length);
                    }
                }
                catch (IOException) { }
                process.WaitForExit();
                error.Wait();
                // 0: some match, 1: none does; anything else (128: not a work tree) has no rules to apply.
                if (process.ExitCode != 0) return ignored;
                foreach (var path in output.Result.Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries))
                    if (path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) ignored.Add(path.Substring(prefix.Length));
            }
            return ignored;
        }

        // A rule over an application, or over a folder object but not
        // everything below it, would leave a hole in the tree: refused before
        // anything is written. *read* gives a folder object's file.
        internal static void Refuse(ISet<string> ignored, IEnumerable<string> paths, Func<string, byte[]> read)
        {
            var folders = ignored.Where(path => path.EndsWith("/.cds-object.xml", StringComparison.OrdinalIgnoreCase) || path.Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase))
                .Select(path => path.Substring(0, path.Length - ".cds-object.xml".Length)).OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList();
            foreach (var folder in folders)
            {
                var bytes = read(folder + ".cds-object.xml");
                if (bytes != null && new UTF8Encoding(false).GetString(bytes).Contains("<Single Name=\"TypeGuid\" Type=\"System.Guid\">" + ApplicationType + "<"))
                    throw new InvalidOperationException("Git's ignore rules cover the application " + folder + "; nothing was done. Ignore folders inside it instead (" + folder + "Task Configuration/, ...).");
            }
            var below = paths.Where(path => !ignored.Contains(path) && folders.Any(folder => path.StartsWith(folder, StringComparison.OrdinalIgnoreCase)))
                .Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList();
            if (below.Count == 0) return;
            throw new InvalidOperationException("Git's ignore rules leave out a folder object but not what is below it: " + string.Join(", ", below.Take(Named))
                + (below.Count > Named ? " and " + (below.Count - Named) + " more" : "") + "; nothing was done. Ignore the whole folder (a pattern ending in /).");
        }

        internal static string Note(int count) => "Git's ignore rules match " + count + " file(s) of the view; cts leaves them as they are and does not compare them";
    }

    // *inner* without what Git's ignore rules match; with *instead*, an
    // ignored path is that view's file, so a comparison shows it unchanged.
    internal sealed class IgnoredViewFiles : IViewFiles
    {
        readonly IViewFiles inner;
        readonly IViewFiles instead;
        readonly ISet<string> ignored;

        internal IgnoredViewFiles(IViewFiles inner, ISet<string> ignored, IViewFiles instead = null)
        {
            this.inner = inner;
            this.ignored = ignored;
            this.instead = instead;
        }

        public IEnumerable<string> Paths => inner.Paths.Where(path => !ignored.Contains(path))
            .Concat(instead == null ? Enumerable.Empty<string>() : instead.Paths.Where(ignored.Contains)).ToList();

        public byte[] Read(string path) => !ignored.Contains(path) ? inner.Read(path) : instead?.Read(path);

        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
        {
            var list = paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            var read = new Dictionary<string, byte[]>(inner.ReadMany(list.Where(path => !ignored.Contains(path))), StringComparer.OrdinalIgnoreCase);
            foreach (var path in list.Where(ignored.Contains)) read[path] = instead?.Read(path);
            return read;
        }

        public string BlobId(string path) => !ignored.Contains(path) ? inner.BlobId(path) : instead?.BlobId(path);
    }
}
