using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Analysis;
using Cts.Visu;

namespace Cts.Cli
{
    // Offline SVG authoring commands. Their element model lives in Cts.Visu
    // so later render and import commands can share the parser.
    internal static partial class VisuSketchCommands
    {
        const int FixPasses = 5;
        static readonly string[] Attributes = { "data-var", "data-text-var", "data-cds-tap", "data-cds-action", "data-color", "data-color-var" };

        internal static IList<CliCommand> Commands => new[] { Command("lint"), Command("new"), Command("bind") };

        static CliCommand Command(string action)
        {
            var command = new CliCommand { Name = "visu", Sub = action };
            if (action == "new")
            {
                command.Summary = "Create an editable SVG sketch";
                command.Description = "Writes a laid-out starter sketch with the canvas and the colour scheme set: a header, value cards, lamps, buttons and an alarm banner, bound to placeholder VisuVars.* variables. Replace the labels and bindings with the real ones and delete what the screen does not need. cts guide visu-svg describes what a sketch may hold.";
                command.Options = new[] { CliOption.Text("--name", "name", "NAME", "Screen title"),
                                          CliOption.Int("--width", "width", "Canvas width (default 800)"),
                                          CliOption.Int("--height", "height", "Canvas height (default 480)"),
                                          CliOption.Int("--w", "w", "Canvas width"),
                                          CliOption.Int("--h", "h", "Canvas height"),
                                          CliOption.Text("--out", "out", "FILE", "Output SVG path (default .visu/<name>.svg)"),
                                          CliOption.Choice("--scheme", "scheme", "Colour scheme", "light", "dark") };
            }
            else if (action == "bind")
            {
                command.Summary = "Attach or clear one SVG element binding";
                command.Description = "Binds one element of a sketch (its index as cts visu lint numbers it) to a variable: a lamp's colour, a text field's or a shape's value, a shape's colour, a button's tap or toggle.";
                command.Options = new[] { CliOption.Needed("--svg", "svg", "FILE", "Sketch SVG"),
                                          CliOption.Int("--elem", "elem", "Zero-based element index"),
                                          CliOption.Text("--var", "var", "NAME", "Bind lamp variable"),
                                          CliOption.Text("--text-var", "text_var", "NAME", "Bind the variable a textfield or a shape shows"),
                                          CliOption.Text("--color-var", "color_var", "NAME", "Bind the BOOL that turns a shape to its data-on- colours"),
                                          CliOption.Text("--tap", "tap", "NAME", "Bind button tap"),
                                          CliOption.Text("--toggle", "toggle", "NAME", "Bind button toggle"),
                                          CliOption.Text("--color", "color", "ROLE", "Lamp colour role"),
                                          CliOption.Text("--action", "action", "TEXT", "Append raw action clause"),
                                          CliOption.Switch("--clear", "clear", "Clear every binding") };
            }
            else
            {
                command.Summary = "Check an SVG sketch for design problems";
                command.Description = "Lints a sketch the way from-svg will compile it: overlaps, off-grid geometry, unbound controls, text that overflows its box. --fix rewrites what is mechanical and repeats until the sketch stops changing.";
                command.Options = new[] { CliOption.Needed("--svg", "svg", "FILE", "Sketch SVG"),
                                          CliOption.Switch("--fix", "fix", "Rewrite mechanically fixable findings"),
                                          CliOption.Switch("--strict", "strict", "Treat all findings as fatal"),
                                          CliOption.Text("--theme", "theme", "NAME", "Theme preset"),
                                          CliOption.Text("--sync-folder", "sync_folder", "PATH", "Project sync folder"),
                                          CliOption.Text("--background", "background", "COLOR", "Canvas background"),
                                          CliOption.Choice("--scheme", "scheme", "Colour scheme", "light", "dark") };
            }
            command.LocalExecute = (options, host, work) => Execute(action, options, work);
            command.Build = data => Build(action, data);
            return command;
        }

        static IDictionary<string, object> New(CliOptions options, string work)
        {
            var width = options.Number("w", options.Number("width", 800));
            var height = options.Number("h", options.Number("height", 480));
            var title = options.Text("name", "");
            var scheme = options.Text("scheme", "light");
            var path = options.Text("out");
            if (string.IsNullOrWhiteSpace(path))
                path = Path.Combine(work, ".visu", (string.IsNullOrWhiteSpace(title) ? "screen" : title.Trim().Replace(' ', '_')) + ".svg");
            path = Path.GetFullPath(path);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var text = SketchSkeleton.Compose(width, height, title, scheme);
            File.WriteAllText(path, text, new System.Text.UTF8Encoding(false));
            return new Dictionary<string, object> { ["path"] = path, ["width"] = width, ["height"] = height, ["scheme"] = scheme,
                                                    ["warnings"] = SketchSkeleton.CheckCanvas(width, height) };
        }

        static bool Has(CliOptions options, string key) => options.Params.ContainsKey(key);

        // The project view whose visu.css adds to the bundled stylesheet: the
        // one --sync-folder names, else the one around the current folder, if any.
        static string ProjectView(CliOptions options, string work, string action)
        {
            var folder = options.Text("sync_folder");
            try
            {
                return AnalyzeWorkspace.Resolve(folder, null, work).View;
            }
            catch (AnalyzeException error)
            {
                if (folder == null) return null;
                throw new CliFailure("visu " + action, "refused", error.Message, "cts visu " + action + " --help", 2);
            }
        }

        static IDictionary<string, object> Execute(string action, CliOptions options, string work)
        {
            if (action == "new") return New(options, work);
            var path = Path.GetFullPath(options.Text("svg"));
            string source;
            try
            {
                source = File.ReadAllText(path);
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is ArgumentException)
            {
                throw new CliFailure("visu " + action, "cannot read SVG", error.Message, null, 1);
            }
            Sketch sketch;
            try
            {
                sketch = Sketch.Parse(source, ProjectView(options, work, action), options.Text("background"), options.Text("scheme"),
                                      options.Text("theme"));
            }
            catch (Exception error) when (error is System.Xml.XmlException || error is VisuException)
            {
                throw new CliFailure("visu " + action, "invalid SVG", error.Message, null, 1);
            }
            if (action == "bind") return Bind(path, source, sketch, options);
            return Lint(path, source, sketch, options);
        }

        static Answer Build(string action, IDictionary<string, object> data)
        {
            var answer = new Answer();
            if (data.ContainsKey("exit_code")) return answer.WithExitCode(JsonMap.Int(data, "exit_code"));
            if (action == "new")
            {
                answer.Add("out", data["path"]).Add("size", data["width"] + "x" + data["height"]).Detail("Sketch created.");
                foreach (var warning in (IList<string>)data["warnings"])
                    answer.Detail("[WARN] " + warning);
                return answer;
            }
            if (action == "bind")
                return answer.Add("elem", data["index"])
                    .Add("type", data["type"])
                    .Add("out", data["path"])
                    .Detail(string.Join(", ", (IList<string>)data["changes"]));
            var findings = ((IList<object>)data["findings"]).Cast<SketchLinter.Finding>().ToList();
            if (Equals(data["fix_requested"], true))
            {
                if (JsonMap.Int(data, "fixed") > 0)
                    answer.Detail("Fixed " + data["fixed"] + " attribute(s) in " + data["path"]);
                else
                    answer.Detail("Nothing mechanically fixable");
                if (Equals(data["still_fixable"], true)) answer.Detail("Still fixable after 5 passes; please report this sketch.");
            }
            foreach (var finding in findings)
                answer.Detail("["
                              + (finding.Severity == "error"  ? "FAIL"
                                 : finding.Severity == "warn" ? "WARN"
                                                              : "INFO")
                              + "] " + finding.Rule.PadRight(13) + " #" + finding.Index.ToString(CultureInfo.InvariantCulture).PadRight(3) + " "
                              + finding.Message);
            if (findings.Count == 0 && !Equals(data["fix_requested"], true))
                answer.Detail("Sketch OK: no design problems found");
            else if (findings.Count > 0)
            {
                var counts = findings.GroupBy(finding => finding.Severity).ToDictionary(group => group.Key, group => group.Count());
                var summary = new[] { "error", "warn", "info" }.Where(counts.ContainsKey).Select(severity => counts[severity] + " " + severity);
                answer.Detail(findings.Count + " finding(s): " + string.Join(", ", summary));
            }
            if (JsonMap.Int(data, "errors") > 0 || Equals(data["strict"], true)) answer.Failed().WithExitCode(1);
            return answer;
        }
    }
}
