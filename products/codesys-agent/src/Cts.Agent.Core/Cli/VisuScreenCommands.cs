using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml.Linq;
using Cts.Agent;
using Cts.Analysis;
using Cts.Visu;

namespace Cts.Cli
{
    // `cts visu types|describe|list|check|capture-frame`: the element catalog
    // and the screen XML of the project view, read offline.
    internal static class VisuScreenCommands
    {
        static readonly CliOption SyncFolder = CliOption.Text("--sync-folder", "sync_folder", "PATH", "The sync folder or its project-view (default: the one around the current folder)");
        static readonly CliOption Folder = CliOption.Text("--folder", "folder", "PATH", "Folder of the screen as cts project-tree lists it, e.g. PLC/Plc Logic/Application (default: search the project view)");

        internal static IList<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "visu", Sub = "create-screen", Summary = "Create an empty visualization screen",
                Description = "Writes a CODESYS screen XML file into an existing project-view folder.",
                Options = new[]
                {
                    CliOption.Needed("--name", "name", "NAME", "Screen name"),
                    CliOption.Int("--width", "width", "Screen width (default 800)"),
                    CliOption.Int("--height", "height", "Screen height (default 480)"),
                    CliOption.Switch("--start-visu", "start_visu", "Set as the start visualization"),
                    Folder,
                    SyncFolder,
                },
                LocalExecute = CreateScreen, Build = BuildCreateScreen,
            },
            new CliCommand
            {
                Name = "visu", Sub = "add", Summary = "Add an element to a visualization screen",
                Description = "Appends a catalog element to a CODESYS screen XML file in the project view.",
                Options = new[]
                {
                    CliOption.Needed("--screen", "screen", "NAME", "Screen name or XML path"),
                    CliOption.Needed("--type", "type", "NAME", "Element type from cts visu types"),
                    CliOption.Int("--x", "x", "X position"),
                    CliOption.Int("--y", "y", "Y position"),
                    CliOption.Int("--w", "w", "Width"),
                    CliOption.Int("--h", "h", "Height"),
                    CliOption.Text("--shape", "shape", "NAME", "Shape variant"),
                    CliOption.Text("--fill", "fill", "COLOR", "Fill color"),
                    CliOption.Text("--frame", "frame", "COLOR", "Frame color"),
                    CliOption.Int("--corner-radius", "corner_radius", "Corner radius"),
                    CliOption.Int("--border-width", "border_width", "Border width"),
                    CliOption.Int("--angle", "angle", "Rotation angle"),
                    CliOption.Text("--tooltip", "tooltip", "TEXT", "Tooltip text"),
                    Folder,
                    SyncFolder,
                },
                LocalExecute = Add, Build = BuildAdd,
            },
            VisuBuildCommands.FromSvg,
            new CliCommand
            {
                Name = "visu", Sub = "types", Summary = "List the visu element types",
                Description = "Every element type cts visu add and the SVG sketch can place, with what it is.",
                LocalExecute = (options, host, work) => Types(), Build = BuildTypes,
            },
            new CliCommand
            {
                Name = "visu", Sub = "describe", Summary = "Describe an element type, or one element of a screen",
                Description = "The type's settable properties with their defaults, its optional variable bindings and its invariants. "
                    + "With --screen and --elem also the members of that element of the screen.",
                Options = new[]
                {
                    CliOption.Needed("--type", "type", "NAME", "The element type (cts visu types lists them)"),
                    CliOption.Text("--screen", "screen", "NAME", "A screen name or XML path, for --elem"),
                    CliOption.Int("--elem", "elem", "The element index on --screen (cts visu list shows it)"),
                    Folder,
                    SyncFolder,
                },
                LocalExecute = Describe, Build = BuildDescribe,
            },
            new CliCommand
            {
                Name = "visu", Sub = "list", Summary = "List the elements of a screen",
                Description = "Index, type, identifier and geometry of every element of the screen.",
                Options = new[] { CliOption.Needed("--screen", "screen", "NAME", "The screen name or XML path"), Folder, SyncFolder },
                LocalExecute = List, Build = BuildList,
            },
            new CliCommand
            {
                Name = "visu", Sub = "check", Summary = "Check a screen's geometry and members",
                Description = "Each element inside the screen with a positive size and its centre at X+W/2, Y+H/2; every colour bound to a style name; "
                    + "every text with a Text ID; no colour with both an ExplicitColor and a live NamedColor; no two elements overlapping (lines, simple elements and nested ones aside). Exit 1 when a problem is found.",
                Options = new[] { CliOption.Needed("--screen", "screen", "NAME", "The screen name or XML path"), Folder, SyncFolder },
                LocalExecute = Check, Build = BuildCheck,
            },
            new CliCommand
            {
                Name = "visu", Sub = "capture-frame", Summary = "Capture a frame instance as a template cts visu add can place",
                Description = "Finds a VisuFbFrame showing --visu (the one that sets the fewest parameters), and writes .cds-visu/frames/<visu>.xml.tmpl "
                    + "and <visu>.json beside the project view: the frame with its geometry and identifiers as placeholders, and its parameters.",
                Options = new[]
                {
                    CliOption.Needed("--visu", "visu", "NAME", "The visualization the frame shows"),
                    CliOption.Text("--screen", "screen", "NAME", "Only look on this screen (default: every screen of the project view)"),
                    Folder,
                    SyncFolder,
                },
                LocalExecute = Capture, Build = BuildCapture,
            },
        };

        static IDictionary<string, object> CreateScreen(CliOptions options, IAgentHost host, string work)
        {
            var name = options.Text("name", "");
            if (string.IsNullOrWhiteSpace(name)) throw new CliFailure("visu-create-screen", "invalid_request", "--name is required", "cts visu create-screen --help", 1);
            var view = View(options, work, "create-screen");
            try
            {
                var path = Cts.Visu.ScreenBuilder.Create(view, ViewPlace.ExistingFolder(view, options.Text("folder", "")), name, options.Number("width", 800), options.Number("height", 480), options.Params.ContainsKey("start_visu"));
                return new Dictionary<string, object> { ["name"] = name, ["path"] = path, ["width"] = options.Number("width", 800), ["height"] = options.Number("height", 480) };
            }
            catch (VisuException error)
            {
                throw Refused("create-screen", error.Message);
            }
        }

        static IDictionary<string, object> Add(CliOptions options, IAgentHost host, string work)
        {
            var path = Screen(options, work, "add");
            var type = options.Text("type", "");
            var parameters = new Dictionary<string, object>(StringComparer.Ordinal);
            foreach (var key in new[] { "x", "y", "corner_radius", "border_width", "angle" })
                if (options.Params.TryGetValue(key, out var value)) parameters[key] = value;
            if (options.Params.TryGetValue("w", out var width)) parameters["width"] = width;
            if (options.Params.TryGetValue("h", out var height)) parameters["height"] = height;
            foreach (var key in new[] { "shape", "fill", "frame", "tooltip" })
            {
                var value = options.Text(key, "");
                if (value.Length > 0) parameters[key] = value;
            }
            try
            {
                var catalog = VisuCatalog.Load(type);
                var result = ElementTemplates.Append(File.ReadAllText(path, Encoding.UTF8), catalog, parameters);
                File.WriteAllText(path, result.Xml, new UTF8Encoding(false));
                return new Dictionary<string, object>
                {
                    ["path"] = path,
                    ["type"] = type,
                    ["identifier"] = result.Identifier,
                    ["geometry"] = result.Geometry,
                };
            }
            catch (VisuException error)
            {
                throw Refused("add", error.Message);
            }
        }

        static Answer BuildAdd(IDictionary<string, object> data)
        {
            var geometry = (IDictionary<string, object>)data["geometry"];
            var answer = new Answer().Add("screen", data["path"]).Add("identifier", data["identifier"]);
            answer.Detail("[OK] Added " + data["type"] + " '" + data["identifier"] + "' at X=" + geometry["x"]
                + " Y=" + geometry["y"] + " W=" + geometry["width"] + " H=" + geometry["height"]
                + " (Center " + geometry["center_x"] + "," + geometry["center_y"] + ")");
            return answer.Whole();
        }

        static Answer BuildCreateScreen(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("path", data["path"]);
            answer.Detail("[OK] Created screen " + data["name"] + " (" + data["width"] + "x" + data["height"] + ") at " + data["path"]);
            answer.Detail(data["path"]);
            return answer.Whole();
        }

        static CliFailure Refused(string sub, string message) => new CliFailure("visu-" + sub, "refused", message, "cts visu " + sub + " --help", 1);

        static IDictionary<string, object> Types()
        {
            var types = VisuCatalog.Types()
                .Select(type => (object)new Dictionary<string, object> { ["type"] = type, ["description"] = JsonMap.Value(VisuCatalog.Load(type), "description") ?? "" })
                .ToList();
            return new Dictionary<string, object> { ["types"] = types };
        }

        static Answer BuildTypes(IDictionary<string, object> data)
        {
            var types = (IList<object>)data["types"];
            var answer = new Answer().Add("types", types.Count);
            foreach (IDictionary<string, object> type in types) answer.Detail(type["type"] + " -- " + type["description"]);
            return answer.Whole();
        }

        static IDictionary<string, object> Describe(CliOptions options, IAgentHost host, string work)
        {
            var type = options.Text("type", "");
            IDictionary<string, object> catalog;
            try
            {
                catalog = VisuCatalog.Load(type);
            }
            catch (VisuException error)
            {
                throw Refused("describe", error.Message);
            }
            var lines = new List<string>();
            if (JsonMap.Value(catalog, "description") is string description && description.Length > 0) lines.Add(description);
            var variants = JsonMap.Value(catalog, "shape_variants") as IDictionary<string, object>;
            if (variants != null && variants.Count > 0)
                lines.Add("shapes: " + string.Join(", ", variants.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + " -> " + pair.Value)));
            lines.Add("Settable properties:");
            foreach (var pair in ((IDictionary<string, object>)catalog["params"]).OrderBy(pair => pair.Key, StringComparer.Ordinal))
                lines.Add("  " + Property(catalog, pair.Key, (IDictionary<string, object>)pair.Value));
            if (JsonMap.Value(catalog, "optional_bindings") is IDictionary<string, object> bindings && bindings.Count > 0)
            {
                lines.Add("Optional bindings (variable references):");
                foreach (var pair in bindings.OrderBy(pair => pair.Key, StringComparer.Ordinal))
                {
                    var binding = (IDictionary<string, object>)pair.Value;
                    lines.Add("  " + pair.Key + " member=" + JsonMap.Value(binding, "member_id") + " -- " + JsonMap.Value(binding, "doc"));
                }
            }
            if (JsonMap.Value(catalog, "invariants") is IList<object> invariants && invariants.Count > 0)
            {
                lines.Add("Invariants:");
                foreach (IDictionary<string, object> invariant in invariants)
                    lines.Add("  [" + (JsonMap.Value(invariant, "severity") ?? "?") + "] " + JsonMap.Value(invariant, "rule"));
            }
            var data = new Dictionary<string, object> { ["type"] = catalog["type"], ["element"] = catalog["visualElementTypeName"], ["lines"] = lines };
            if (!options.Params.TryGetValue("elem", out var elem)) return data;
            var path = Screen(options, work, "describe");
            var elements = Read(path, "describe", root => ScreenXml.Elements(root));
            var index = Convert.ToInt32(elem, CultureInfo.InvariantCulture);
            if (index < 0 || index >= elements.Count)
                throw Refused("describe", "Element index " + index + " out of range (0.." + (elements.Count - 1) + ")");
            var target = elements[index];
            lines.Add("Element #" + index + ": " + target.Identifier + " (" + target.Type + ")");
            foreach (var member in target.Members)
            {
                var shown = member.Value.Kind == "color" ? "color=" + member.Value.Color + " canonical=" + member.Value.CanonicalName
                    : member.Value.Kind == "list" ? "(list)"
                    : member.Value.Value;
                lines.Add("  " + member.Key.ToString(CultureInfo.InvariantCulture) + " " + shown);
            }
            data["screen"] = path;
            return data;
        }

        // "name kind=K default=V -- doc [geometry, requires=...]"
        static string Property(IDictionary<string, object> catalog, string name, IDictionary<string, object> property)
        {
            var flags = new List<string>();
            if (Equals(JsonMap.Value(property, "geometry"), true)) flags.Add("geometry");
            if (JsonMap.Value(property, "requires") is object requires) flags.Add("requires=" + Shown(requires));
            var line = name + " kind=" + JsonMap.Value(property, "kind") + " default=" + Shown(VisuCatalog.Default(catalog, property));
            if (JsonMap.Value(property, "doc") is string doc && doc.Length > 0) line += " -- " + doc;
            return flags.Count == 0 ? line : line + " [" + string.Join(", ", flags) + "]";
        }

        // A value as JSON writes it, so text and numbers stay apart.
        static string Shown(object value) => value is IList<object> list ? string.Join(",", list) : Json.Serialize(value);

        static Answer BuildDescribe(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("type", data["type"]).Add("element", data["element"]);
            if (data.TryGetValue("screen", out var screen)) answer.Add("screen", screen);
            foreach (var line in (IList<string>)data["lines"]) answer.Detail(line);
            return answer.Whole();
        }

        static IDictionary<string, object> List(CliOptions options, IAgentHost host, string work)
        {
            var path = Screen(options, work, "list");
            var rows = Read(path, "list", root => ScreenXml.Elements(root))
                .Select(element => (object)string.Format(CultureInfo.InvariantCulture, "{0,-3} {1,-16} {2,-16} {3,6} {4,6} {5,6} {6,6}",
                    element.Index, element.Type, element.Identifier,
                    Cell(element.Value(ScreenXml.X)), Cell(element.Value(ScreenXml.Y)), Cell(element.Value(ScreenXml.Width)), Cell(element.Value(ScreenXml.Height))))
                .ToList();
            return new Dictionary<string, object> { ["screen"] = path, ["rows"] = rows };
        }

        static string Cell(string value) => string.IsNullOrEmpty(value) ? "-" : value;

        static Answer BuildList(IDictionary<string, object> data)
        {
            var rows = (IList<object>)data["rows"];
            var answer = new Answer().Add("screen", data["screen"]).Add("elements", rows.Count);
            if (rows.Count > 0) answer.Detail(string.Format(CultureInfo.InvariantCulture, "{0,-3} {1,-16} {2,-16} {3,6} {4,6} {5,6} {6,6}", "Idx", "Type", "Identifier", "X", "Y", "W", "H"));
            foreach (var row in rows) answer.Detail(row);
            return answer.Whole();
        }

        static IDictionary<string, object> Check(CliOptions options, IAgentHost host, string work)
        {
            var path = Screen(options, work, "check");
            var (size, elements, colors) = Read(path, "check", root => (ScreenXml.Size(root), ScreenXml.Elements(root), ScreenCheck.ColorConflicts(root).ToList()));
            return new Dictionary<string, object> { ["screen"] = path, ["elements"] = elements.Count, ["problems"] = ScreenCheck.Problems(size.Width, size.Height, elements).Concat(colors).Cast<object>().ToList() };
        }

        static Answer BuildCheck(IDictionary<string, object> data)
        {
            var problems = (IList<object>)data["problems"];
            var answer = new Answer().Add("screen", data["screen"]).Add("elements", data["elements"]).Add("problems", problems.Count);
            foreach (var problem in problems) answer.Detail(problem);
            return problems.Count == 0 ? answer : answer.Whole().Failed().WithExitCode(1);
        }

        static IDictionary<string, object> Capture(CliOptions options, IAgentHost host, string work)
        {
            var visu = options.Text("visu", "");
            var view = View(options, work, "capture-frame");
            var warnings = new List<object>();
            var files = options.Text("screen", "").Length > 0
                ? new[] { Screen(options, work, "capture-frame") }
                : Directory.GetFiles(view, "*.xml", SearchOption.AllDirectories).OrderBy(file => file, StringComparer.Ordinal).ToArray();
            XElement best = null;
            var bestSet = int.MaxValue;
            foreach (var file in files.Where(File.Exists))
            {
                XElement root;
                try
                {
                    root = ScreenXml.Parse(File.ReadAllText(file, Encoding.UTF8));
                }
                catch (VisuException error)
                {
                    // One stray file must not hide a frame that is there.
                    warnings.Add("skipped " + file + ": " + error.Message);
                    continue;
                }
                foreach (var frame in FrameCapture.Frames(root, visu))
                {
                    var set = FrameCapture.SetParameters(frame);
                    if (set >= bestSet) continue;
                    best = frame;
                    bestSet = set;
                }
            }
            if (best == null) throw Refused("capture-frame", "No frame showing '" + visu + "' found in " + (files.Length == 1 ? files[0] : view));
            var parameters = FrameCapture.Parameters(best);
            var output = Path.Combine(view, ".cds-visu", "frames");
            Directory.CreateDirectory(output);
            var template = Path.Combine(output, visu + ".xml.tmpl");
            var catalog = Path.Combine(output, visu + ".json");
            var utf8 = new UTF8Encoding(false);
            File.WriteAllText(template, FrameCapture.Template(best, parameters.Select(parameter => parameter.MemberId).ToList()), utf8);
            File.WriteAllText(catalog, Json.Pretty(FrameCapture.Catalog(visu, parameters)), utf8);
            return new Dictionary<string, object>
            {
                ["visu"] = visu,
                ["template"] = template,
                ["catalog"] = catalog,
                ["params"] = parameters.Select(parameter => (object)parameter.Name).ToList(),
                ["warnings"] = warnings,
            };
        }

        static Answer BuildCapture(IDictionary<string, object> data)
        {
            var parameters = (IList<object>)data["params"];
            var answer = new Answer().Add("visu", data["visu"]).Add("template", data["template"]).Add("catalog", data["catalog"]).Add("params", parameters.Count);
            if (parameters.Count > 0) answer.Detail("params: " + string.Join(", ", parameters));
            foreach (var warning in (IList<object>)data["warnings"]) answer.Detail(warning);
            return answer;
        }

        static string View(CliOptions options, string work, string sub)
        {
            try
            {
                return AnalyzeWorkspace.Resolve(options.Text("sync_folder", ""), null, work).View;
            }
            catch (AnalyzeException error)
            {
                throw new CliFailure("visu-" + sub, "refused", error.Message, "cts visu " + sub + " --help", 2);
            }
        }

        static string Screen(CliOptions options, string work, string sub)
        {
            var screen = options.Text("screen", "");
            if (screen.Trim().Length == 0) throw new CliFailure("visu-" + sub, "invalid_request", "--screen is required: the screen name or XML path", "cts visu " + sub + " --help", 2);
            // A path needs no project view, so it works outside a sync folder.
            if (File.Exists(screen)) return Path.GetFullPath(screen);
            string path;
            try { path = ViewPlace.Screen(View(options, work, sub), screen, options.Text("folder", "")); }
            catch (VisuException error) { throw Refused(sub, error.Message); }
            if (!File.Exists(path)) throw Refused(sub, "Screen file not found: " + path);
            return path;
        }


        static T Read<T>(string path, string sub, Func<XElement, T> read)
        {
            try
            {
                return read(ScreenXml.Parse(File.ReadAllText(path, Encoding.UTF8)));
            }
            catch (VisuException error)
            {
                throw Refused(sub, error.Message + " (" + path + ")");
            }
        }
    }
}
