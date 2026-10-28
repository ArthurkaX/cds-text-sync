using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security;
using System.Text;
using System.Text.RegularExpressions;

namespace Cts.Trend
{
    // The cts trend of one application in the sync folder: the TrendRecording
    // CtsTrend below the application's Trend Recording Manager, recording a
    // fixed number of slots in a task's cycle while GVL_CtsTrend.xRecord is
    // TRUE (FALSE from a download on).  The slots stay as many whatever they record (a free one records
    // xRecord): the IDE takes new variables in them as an online change, and
    // asks a full download only when their count changes.
    internal sealed class TrendFiles
    {
        internal const string Name = "CtsTrend";
        internal const string Gvl = "GVL_CtsTrend";
        internal const string Gate = Gvl + ".xRecord";
        internal const int DefaultSlots = 10;
        internal const int DefaultLimitMb = 16;
        // How often the PLC writes its buffer into the file: what a pull waits
        // for after pausing the recording.
        internal const int StoreMs = 1000;
        const string ApplicationType = "639b491f-5557-464c-af91-1471bac9f549";
        const string TaskConfigurationType = "ae1de277-a207-4a28-9efb-456c06bd52f3";
        const string TaskType = "98a2708a-9b18-4f31-82ed-a1465b24fa2d";
        const string ManagerType = "49395b8d-29d2-40db-a655-eae6a5627611";
        const string RecordingType = "abf325da-edef-4010-9b49-0de4ec1bb653";
        const string StorageCall = "VisuTrendStorageAccess.GlobalInstances.g_TrendRecordingManager.CyclicCall";
        // Off after a download or a restart: a recording starts when someone
        // asks for it (cts trend on, or a write of TRUE in the IDE).
        const string GvlText = "VAR_GLOBAL\n\txRecord : BOOL;\t// cts trend records while TRUE: cts trend on/off, or write it in the IDE\nEND_VAR\n";

        internal string View, App, AppFolder, RecordingFile;
        internal List<TrendTask> Tasks;

        // The application *app* names (its folder's name), else the one with a
        // cts trend, else the only one besides cts test's; null with *problem* saying why not.
        internal static TrendFiles Of(string view, string app, out string problem)
        {
            problem = null;
            var apps = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .Where(file => TypeOf(File.ReadAllText(file)) == ApplicationType)
                .Select(file => Path.GetDirectoryName(file)).OrderBy(folder => folder, StringComparer.OrdinalIgnoreCase).ToList();
            var names = string.Join(", ", apps.Select(Path.GetFileName));
            List<string> picked;
            if (app != null) picked = apps.Where(folder => Path.GetFileName(folder).Equals(app, StringComparison.OrdinalIgnoreCase)).ToList();
            else
            {
                picked = apps.Where(folder => RecordingIn(folder) != null).ToList();
                // The application cts test runs its tests in records nothing.
                if (picked.Count == 0) picked = apps.Where(folder => Path.GetFileName(folder) != Agent.AppTests.DefaultApplication).ToList();
            }
            if (picked.Count != 1)
            {
                problem = apps.Count == 0 ? "the sync folder holds no application"
                    : app != null ? "no application " + app + "; the applications are " + names
                    : "several applications: pick one with --app (" + names + ")";
                return null;
            }
            var trend = new TrendFiles { View = view, AppFolder = picked[0], App = Path.GetFileName(picked[0]) };
            trend.RecordingFile = RecordingIn(trend.AppFolder);
            trend.Tasks = Directory.GetFiles(trend.AppFolder, "*.xml", SearchOption.AllDirectories)
                .Select(file => new { file, text = File.ReadAllText(file) }).Where(item => TypeOf(item.text) == TaskType)
                .Select(item => TrendTask.Read(item.text)).ToList();
            return trend;
        }

        // What the recording holds now; null when the application has none.
        internal TrendSettings Settings() => RecordingFile == null ? null : TrendSettings.Read(File.ReadAllText(RecordingFile));

        // The recording with *settings* on disk, with the objects it needs
        // that the application lacks: the manager, its task, the gate's GVL
        // and the storage library.  The files written, view-relative.
        internal List<string> Write(TrendSettings settings)
        {
            var written = new List<string>();
            var text = RecordingFile == null ? NewRecording(written) : File.ReadAllText(RecordingFile);
            Save(RecordingFile, settings.Apply(text), written);
            if (!Directory.GetFiles(AppFolder, Gvl + ".st", SearchOption.AllDirectories).Any())
                Save(Path.Combine(AppFolder, Gvl + ".st"), GvlText, written);
            var libraries = Path.Combine(AppFolder, "Library Manager.xml");
            if (File.Exists(libraries) && Cli.LibCommand.ReferenceSystem(libraries, View, "VisuTrendStorageAccess", "VisuTrendStorageAccess", "System"))
                written.Add(Relative(libraries));
            return written;
        }

        // A new recording below the application's manager, which is made too
        // when there is none, and the storage task when no task calls it.
        string NewRecording(List<string> written)
        {
            var managerFile = Containers(AppFolder).FirstOrDefault(file => TypeOf(File.ReadAllText(file)) == ManagerType);
            if (managerFile != null && !Path.GetFileName(managerFile).Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException(Relative(managerFile) + " is a Trend Recording Manager with no recording: delete it in the project (or its file, then cts import), so cts trend set makes one");
            if (managerFile == null)
            {
                managerFile = Path.Combine(AppFolder, "Trend Recording Manager", ".cds-object.xml");
                Save(managerFile, Instantiate("Manager.xml", Path.Combine(AppFolder, ".cds-object.xml"), null), written);
            }
            if (!Tasks.Any(task => task.Calls.Contains(StorageCall)))
            {
                var configuration = Containers(AppFolder).FirstOrDefault(file => TypeOf(File.ReadAllText(file)) == TaskConfigurationType)
                    ?? throw new InvalidOperationException("the application " + App + " has no Task Configuration");
                Save(Path.Combine(Path.GetDirectoryName(configuration), "TrendRecordingTask.xml"), Instantiate("Task.xml", configuration, null), written);
            }
            RecordingFile = Path.Combine(Path.GetDirectoryName(managerFile), Name + ".xml");
            return Instantiate("Recording.xml", managerFile, Name);
        }

        // A template as an object below the one *parentFile* holds: its own
        // GUIDs new, its parent's and its path that object's.
        static string Instantiate(string template, string parentFile, string name)
        {
            var fresh = new Dictionary<string, string>();
            var text = Regex.Replace(Template(template), "(<Single Name=\"(?!TypeGuid\")[^\"]*\" Type=\"System.Guid\">)([0-9a-fA-F-]{36})(</Single>)", match =>
            {
                var old = match.Groups[2].Value;
                if (old == Guid.Empty.ToString("D")) return match.Value;
                if (!fresh.TryGetValue(old, out var guid)) fresh[old] = guid = Guid.NewGuid().ToString("D");
                return match.Groups[1].Value + guid + match.Groups[3].Value;
            });
            // The parent's file holds its name and path escaped, as they go in.
            var parent = File.ReadAllText(parentFile);
            var parentPath = Regex.Matches(Regex.Match(parent, "<Array Name=\"Path\" Type=\"string\">(.*?)</Array>", RegexOptions.Singleline).Groups[1].Value,
                "<Single Type=\"string\">([^<]*)</Single>").Cast<Match>().Select(match => match.Groups[1].Value).Concat(new[] { Meta(parent, "Name") });
            text = text.Replace("{{PARENT}}", Meta(parent, "Guid"))
                .Replace("{{PATH}}", string.Join("\n", parentPath.Select(part => "        <Single Type=\"string\">" + part + "</Single>")));
            return name == null ? text : text.Replace("{{NAME}}", name);
        }

        internal static string Template(string name)
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Cts.Trend.Templates." + name))
            using (var reader = new StreamReader(stream, Encoding.UTF8))
                return reader.ReadToEnd().Replace("\r\n", "\n");
        }

        static string RecordingIn(string appFolder) => Directory.GetFiles(appFolder, Name + ".xml", SearchOption.AllDirectories)
            .FirstOrDefault(file => TypeOf(File.ReadAllText(file)) == RecordingType);

        // The files of the objects in *folder*: a container's .cds-object.xml, else the object's own .xml.
        static IEnumerable<string> Containers(string folder) => Directory.GetFiles(folder, "*.xml", SearchOption.AllDirectories)
            .OrderBy(file => file.Count(ch => ch == Path.DirectorySeparatorChar));

        void Save(string file, string text, List<string> written)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            var old = File.Exists(file) ? File.ReadAllText(file) : null;
            if (old == text) return;
            File.WriteAllText(file, text, new UTF8Encoding(false));
            written.Add(Relative(file));
        }

        internal string Relative(string file) => file.Substring(View.Length).TrimStart(Path.DirectorySeparatorChar, '/').Replace('\\', '/');

        internal static string TypeOf(string xml) => Meta(xml, "TypeGuid").Trim('{', '}').ToLowerInvariant();

        static string Meta(string xml, string name) =>
            Regex.Match(xml, "<Single Name=\"" + name + "\" Type=\"[^\"]*\">([^<]*)</Single>").Groups[1].Value.Trim();
    }

    // A task of the application, as its file holds it.
    internal sealed class TrendTask
    {
        internal string Name, Kind;
        internal double IntervalMs;
        internal List<string> Calls;

        internal static TrendTask Read(string xml)
        {
            var interval = Regex.Match(xml, "<Single Name=\"Interval\"[^>]*>\\s*<Single Name=\"Time\" Type=\"string\">([^<]*)</Single>\\s*<Single Name=\"Unit\" Type=\"string\">([^<]*)</Single>");
            var ms = double.TryParse(interval.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var time)
                ? time * (interval.Groups[2].Value == "us" ? 0.001 : interval.Groups[2].Value == "s" ? 1000 : 1) : 0;
            return new TrendTask
            {
                Name = Regex.Match(xml, "<Single Name=\"Name\" Type=\"string\">([^<]*)</Single>").Groups[1].Value,
                Kind = Regex.Match(xml, "<Single Name=\"Kindoftask\" Type=\"[^\"]*\">([^<]*)</Single>").Groups[1].Value,
                IntervalMs = ms,
                Calls = Regex.Matches(Regex.Match(xml, "<List Name=\"PouList\".*?</List>", RegexOptions.Singleline).Value,
                    "<Single Name=\"Name\" Type=\"string\">([^<]*)</Single>").Cast<Match>().Select(match => match.Groups[1].Value).ToList(),
            };
        }

        // A cyclic task that runs the program, not only a visualization or a trend's storage.
        internal bool RunsProgram => Kind == "Cyclic" && IntervalMs > 0 && Calls.Any(call => !call.StartsWith("Visu", StringComparison.Ordinal));
    }

    // What a recording records: in which task, every how many cycles, in how
    // many slots and how big its file may grow.
    internal sealed class TrendSettings
    {
        internal string Task;
        internal int Every = 1, Slots = TrendFiles.DefaultSlots, LimitMb = TrendFiles.DefaultLimitMb;
        internal List<string> Variables = new List<string>();

        internal static TrendSettings Read(string xml)
        {
            var limit = Regex.Match(xml, "<Single Name=\"Limit\".*?<Single Name=\"Size\" Type=\"ulong\">([0-9]+)</Single>", RegexOptions.Singleline);
            return new TrendSettings
            {
                Task = Value(xml, "TaskName"),
                Every = int.TryParse(Value(xml, "EveryNCycles"), out var every) ? every : 1,
                Slots = Regex.Matches(xml, "<Single Name=\"VariableName\" Type=\"string\">").Count,
                LimitMb = int.TryParse(limit.Groups[1].Value, out var size) ? size : TrendFiles.DefaultLimitMb,
                Variables = Regex.Matches(xml, "<Single Name=\"VariableName\" Type=\"string\">([^<]*)</Single>").Cast<Match>()
                    .Select(match => match.Groups[1].Value).Where(name => name != TrendFiles.Gate).Select(Unescape).ToList(),
            };
        }

        // *xml* recording these settings, in the task's cycle, while the gate is TRUE.
        internal string Apply(string xml)
        {
            xml = Set(xml, "TaskName", SecurityElement.Escape(Task));
            xml = Set(xml, "EveryNCycles", Every.ToString(CultureInfo.InvariantCulture));
            xml = Set(xml, "Condition", TrendFiles.Gate);
            xml = Set(xml, "RecordingMode", "TaskSynchronous");
            xml = Set(xml, "MaxNumberOfVariables", Slots.ToString(CultureInfo.InvariantCulture));
            xml = Set(xml, "StoreEveryNMilliseconds", TrendFiles.StoreMs.ToString(CultureInfo.InvariantCulture));
            xml = Regex.Replace(xml, "(<Single Name=\"Limit\".*?<Single Name=\"Size\" Type=\"ulong\">)[0-9]+(</Single>\\s*<Single Name=\"Unit\" Type=\"[^\"]*\">)[^<]*",
                match => match.Groups[1].Value + LimitMb.ToString(CultureInfo.InvariantCulture) + match.Groups[2].Value + "MB", RegexOptions.Singleline);
            var entry = TrendFiles.Template("Variable.xml");
            var entries = Variables.Concat(Enumerable.Repeat(TrendFiles.Gate, Slots - Variables.Count))
                .Select(name => entry.Replace("{{VARIABLE}}", SecurityElement.Escape(name)));
            return Regex.Replace(xml, "(<List Name=\"TraceMgrVariables\" Type=\"System.Collections.ArrayList\")(?: />|>.*?\n( *)</List>)", match =>
                match.Groups[1].Value + ">\n" + string.Concat(entries) + "          </List>", RegexOptions.Singleline);
        }

        static string Value(string xml, string name) => Unescape(Regex.Match(xml, "<Single Name=\"" + name + "\" Type=\"[^\"]*\">([^<]*)</Single>").Groups[1].Value);

        // *xml* with the element *name* holding *value*, written as the export writes it.
        static string Set(string xml, string name, string value)
        {
            var pattern = new Regex("(<Single Name=\"" + name + "\" Type=\"[^\"]*\")(?: />|>[^<]*</Single>)");
            if (pattern.Matches(xml).Count != 1) throw new InvalidDataException("the recording has no single " + name);
            return pattern.Replace(xml, match => match.Groups[1].Value + ">" + value + "</Single>");
        }

        static string Unescape(string text) => text.Replace("&lt;", "<").Replace("&gt;", ">").Replace("&quot;", "\"").Replace("&apos;", "'").Replace("&amp;", "&");
    }
}
