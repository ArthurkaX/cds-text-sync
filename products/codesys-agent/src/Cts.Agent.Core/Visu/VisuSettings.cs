using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;

namespace Cts.Visu
{
    // An application's Visualization Manager and its clients (WebVisu,
    // TargetVisu) as the project view holds them.  The IDE makes the manager
    // with the first screen of an application and starts the clients at that
    // screen, with CurrentVisuGlobal off and anisotropic scaling: settings a
    // screen set usually needs changed, kept apart from the screens' XML.
    internal sealed class VisuSettings
    {
        const string ManagerType = "4d3fdb8f-ab50-4c35-9d3a-d4bb9bb9a628";
        const string WebType = "0fdbf158-1ae0-47d9-9269-cd84be308e9d";
        const string TargetType = "bc63f5fa-d286-4786-994e-7b27e4f97bd5";
        const string ScreenType = "f18bec89-9fef-401d-9953-2f11739a6808";
        static readonly Regex CurrentVisuWrite = new Regex(@"\bCurrentVisu\s*:=");

        internal string ManagerFile, AppFolder;
        internal List<string> Clients;

        // Every manager below *folder*.
        internal static List<VisuSettings> Below(string folder) =>
            Directory.GetFiles(folder, "*.xml", SearchOption.AllDirectories).Where(file => TypeOf(file) == ManagerType)
                .OrderBy(file => file, StringComparer.OrdinalIgnoreCase).Select(Of).ToList();

        // The manager of the application *screen* belongs to, or null; the search ends at the project view.
        internal static VisuSettings Around(string screen)
        {
            for (var folder = Path.GetDirectoryName(Path.GetFullPath(screen)); folder != null; folder = Path.GetDirectoryName(folder))
            {
                var manager = Directory.GetFiles(folder, "*.xml")
                    .Concat(Directory.GetDirectories(folder).Select(child => Path.Combine(child, ".cds-object.xml")).Where(File.Exists))
                    .FirstOrDefault(file => TypeOf(file) == ManagerType);
                if (manager != null) return Of(manager);
                if (Path.GetFileName(folder).Equals("project-view", StringComparison.OrdinalIgnoreCase)) break;
            }
            return null;
        }

        static VisuSettings Of(string manager)
        {
            var own = Path.GetFileName(manager).Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase) ? Path.GetDirectoryName(manager) : null;
            return new VisuSettings
            {
                ManagerFile = manager,
                AppFolder = Path.GetDirectoryName(own ?? manager),
                Clients = own == null ? new List<string>() : Directory.GetFiles(own, "*.xml")
                    .Where(file => TypeOf(file) == WebType || TypeOf(file) == TargetType).OrderBy(file => file, StringComparer.OrdinalIgnoreCase).ToList(),
            };
        }

        internal bool CurrentVisuGlobal => Value(File.ReadAllText(ManagerFile), "CurrentVisuGlobal") == "True";

        internal static string Kind(string client) => TypeOf(client) == WebType ? "WebVisu" : "TargetVisu";

        internal static string Value(string xml, string member)
        {
            var match = Regex.Match(xml, "<Single Name=\"" + member + "\" Type=\"[^\"]*\"(?: />|>([^<]*)</Single>)");
            return match.Success ? WebUtility.HtmlDecode(match.Groups[1].Value) : null;
        }

        // *member* of *file* set to *value*; false when it held it already.
        internal static bool Set(string file, string member, string value)
        {
            var xml = File.ReadAllText(file);
            var pattern = new Regex("<Single Name=\"" + member + "\" Type=\"([^\"]*)\"(?: />|>[^<]*</Single>)");
            var matches = pattern.Matches(xml);
            if (matches.Count != 1) throw new VisuException(file + " holds " + matches.Count + " " + member + " members, not one: set it in the IDE");
            var text = pattern.Replace(xml, match => "<Single Name=\"" + member + "\" Type=\"" + match.Groups[1].Value + "\">" + WebUtility.HtmlEncode(value) + "</Single>");
            if (text == xml) return false;
            File.WriteAllText(file, text, new UTF8Encoding(false));
            return true;
        }

        // The screens of the application, by name.
        internal List<string> Screens() => Directory.GetFiles(AppFolder, "*.xml", SearchOption.AllDirectories)
            .Where(file => TypeOf(file) == ScreenType).Select(file => Value(Head(file), "Name")).ToList();

        // What makes the shown screen differ from what the application asks:
        // a client starting at no screen, code writing CurrentVisu that the
        // manager does not follow.
        internal List<string> Problems(string view)
        {
            var problems = new List<string>();
            var screens = Screens();
            foreach (var client in Clients)
            {
                var start = Value(File.ReadAllText(client), "StartVisu") ?? "";
                if (!screens.Contains(start, StringComparer.OrdinalIgnoreCase))
                    problems.Add(Relative(view, client) + ": StartVisu '" + start + "' is no screen of the application; cts visu settings --start-visu NAME");
            }
            if (CurrentVisuGlobal) return problems;
            var writer = Directory.GetFiles(AppFolder, "*.*", SearchOption.AllDirectories)
                .Where(file => file.EndsWith(".st", StringComparison.OrdinalIgnoreCase) || file.EndsWith(".xml", StringComparison.OrdinalIgnoreCase))
                .OrderBy(file => file, StringComparer.OrdinalIgnoreCase).FirstOrDefault(file => CurrentVisuWrite.IsMatch(File.ReadAllText(file)));
            if (writer != null)
                problems.Add(Relative(view, writer) + " writes CurrentVisu, but CurrentVisuGlobal is False in " + Relative(view, ManagerFile)
                    + ": the shown screen does not follow it; cts visu settings --current-visu on");
            return problems;
        }

        internal static string Relative(string view, string file) => file.StartsWith(view, StringComparison.OrdinalIgnoreCase)
            ? file.Substring(view.Length).Replace('\\', '/').TrimStart('/') : file;

        // The object's own type and name come first in its file.
        static string Head(string file)
        {
            using (var reader = new StreamReader(file, Encoding.UTF8))
            {
                var buffer = new char[16384];
                return new string(buffer, 0, reader.ReadBlock(buffer, 0, buffer.Length));
            }
        }

        static string TypeOf(string file) => (Value(Head(file), "TypeGuid") ?? "").Trim('{', '}').ToLowerInvariant();
    }
}
