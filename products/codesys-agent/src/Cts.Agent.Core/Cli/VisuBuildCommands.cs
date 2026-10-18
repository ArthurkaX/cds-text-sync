using System;
using Cts.Agent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Analysis;
using Cts.Visu;

namespace Cts.Cli
{
    internal static class VisuBuildCommands
    {
        internal static readonly CliCommand FromSvg = new CliCommand
        {
            Name = "visu",
            Sub = "from-svg",
            Summary = "Compile an SVG sketch to CODESYS screen XML",
            Description = "Writes the screen's .xml into project-view (--create-screen for a new one, --screen to rebuild one), the variables its bindings need (--gvl) and its fixed texts as GlobalTextList rows. Files only: cts import brings them into the IDE. --folder is the place in the project tree, as cts project-tree prints it.",
            Options = new[]
            {
                CliOption.Needed("--svg", "svg", "FILE", "SVG sketch"),
                CliOption.Text("--screen", "screen", "NAME", "Existing screen to rebuild, by its name alone (or its .xml path)"),
                CliOption.Switch("--create-screen", "create_screen", "Create a screen from the sketch"),
                CliOption.Text("--screen-name", "screen_name", "NAME", "Name for --create-screen"),
                CliOption.Switch("--replace", "replace", "Rebuild the screen while keeping its Guid"),
                CliOption.Text("--folder", "folder", "PATH", "Where --create-screen puts the new screen, as cts project-tree lists the folders; with --screen only when two screens share the name"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder or project-view"),
                CliOption.Text("--theme", "theme", "NAME", "Style preset (default flat-style)"),
                CliOption.Text("--out", "out", "FILE", "Output screen XML path"),
                CliOption.Text("--gvl", "gvl", "NAME", "GVL name"),
                CliOption.Text("--gvl-file", "gvl_file", "FILE", "Explicit GVL .st path"),
                CliOption.Text("--background", "background", "COLOR", "Screen background"),
                CliOption.Choice("--scheme", "scheme", "Colour scheme", "light", "dark"),
                CliOption.Switch("--no-preview", "no_preview", "Skip preview"),
                CliOption.Switch("--strict", "strict", "Treat every lint finding as fatal"),
            },
            LocalExecute = Execute,
            Build = Build,
        };

        static IDictionary<string, object> Execute(CliOptions options, IAgentHost host, string work)
        {
            var svgPath = Path.GetFullPath(options.Text("svg", ""));
            if (!File.Exists(svgPath)) throw Refused("SVG file not found: " + svgPath);
            string view;
            try { view = AnalyzeWorkspace.Resolve(options.Text("sync_folder", ""), null, work).View; }
            catch (AnalyzeException error) { throw new CliFailure("visu-from-svg", "refused", error.Message, "cts visu from-svg --help", 2); }
            Sketch sketch;
            try
            {
                sketch = Sketch.Parse(File.ReadAllText(svgPath, Encoding.UTF8), view, EmptyToNull(options.Text("background", "")),
                    EmptyToNull(options.Text("scheme", "")), options.Text("theme", "flat-style"));
            }
            catch (VisuException error) { throw Refused(error.Message); }
            var findings = SketchLinter.BuildLines(sketch, out var errors, out var hasFindings);
            var log = new List<string>();
            if (hasFindings) log.AddRange(findings);
            if (errors || options.Params.ContainsKey("strict") && hasFindings)
                throw Refused(errors ? "Sketch has errors" : "Refusing to compile (--strict)");

            var create = options.Params.ContainsKey("create_screen");
            var folder = options.Text("folder", "");
            var screen = options.Text(create ? "screen_name" : "screen", "");
            if (string.IsNullOrWhiteSpace(screen)) throw Refused(create ? "--screen-name is required when --create-screen is used" : "--screen is required unless --create-screen is used");
            string screenPath;
            if (create)
            {
                var existed = false;
                try
                {
                    var target = ViewPlace.ExistingFolder(view, folder);
                    existed = File.Exists(Path.Combine(target, screen + ".xml"));
                    screenPath = ScreenBuilder.Create(view, target, screen, sketch.Width, sketch.Height, false,
                        options.Params.ContainsKey("replace"), sketch.Background);
                }
                catch (VisuException error) { throw Refused(error.Message); }
                log.Add("[OK] " + (existed ? "Replaced" : "Created") + " screen " + screen + " at " + screenPath);
            }
            else
            {
                try { screenPath = ViewPlace.Screen(view, screen, folder); }
                catch (VisuException error) { throw Refused(error.Message); }
            }
            if (!File.Exists(screenPath)) throw Refused("Screen file not found: " + screenPath);

            var xml = File.ReadAllText(screenPath, Encoding.UTF8);
            try
            {
                var root = ScreenXml.Parse(xml);
                var size = ScreenXml.Size(root);
                if (size.Width != sketch.Width || size.Height != sketch.Height)
                {
                    log.Add("[OK] Screen size (" + size.Width + "x" + size.Height + ") differs from canvas ("
                        + sketch.Width + "x" + sketch.Height + "); resizing");
                    xml = ScreenText.Resize(xml, sketch.Width, sketch.Height);
                }
                if (!create && !string.IsNullOrEmpty(sketch.Background)) xml = ScreenText.SetBackground(xml, sketch.Background);
                var oldCount = ScreenXml.Elements(root).Count;
                if (!create && oldCount > 0)
                {
                    xml = ScreenText.ClearElements(xml);
                    log.Add("[OK] Replacing " + oldCount + " existing element(s) in " + screen);
                }
            }
            catch (VisuException error) { throw Refused(error.Message); }

            foreach (var element in sketch.Elements)
            {
                var parameters = new Dictionary<string, object>(element.SpecParams, StringComparer.Ordinal);
                // The radius a sketch records serves the preview; the built element keeps its catalog default.
                parameters.Remove("corner_radius");
                var text = JsonMap.Text(parameters, "text");
                if (text.Length > 0 && JsonMap.Text(parameters, "text_id").Length == 0)
                    parameters["text_id"] = TextListWriter.Allocate(view, text, warning => log.Add("[WARN] " + warning));
                try
                {
                    if (element.Type == "frame")
                    {
                        var frame = FrameBuilder.Load(view, JsonMap.Text(parameters, "visu"));
                        xml = ElementTemplates.Append(xml, frame.Catalog, parameters, frame.Template, sketch.Theme, sketch.Scheme).Xml;
                    }
                    else xml = ElementTemplates.Append(xml, VisuCatalog.Load(element.Type), parameters, null, sketch.Theme, sketch.Scheme).Xml;
                }
                catch (VisuException error) { throw Refused(error.Message); }
            }
            var output = options.Text("out", "");
            if (output.Length == 0) output = screenPath;
            else output = Path.GetFullPath(output);
            var outputDirectory = Path.GetDirectoryName(output);
            if (!string.IsNullOrEmpty(outputDirectory)) Directory.CreateDirectory(outputDirectory);
            File.WriteAllText(output, xml, new UTF8Encoding(false));
            var gvlName = options.Text("gvl", "");
            var gvlFile = options.Text("gvl_file", "");
            if (gvlName.Length > 0 || gvlFile.Length > 0)
            {
                var gvl = GvlWriter.Ensure(view, sketch.Elements.ToList(), gvlName.Length > 0 ? gvlName : "VisuVars", gvlFile);
                foreach (var warning in gvl.Warnings) log.Add("[WARN] Not declared: " + warning);
                if (gvl.Path != null)
                    log.Add(gvl.Written ? "[OK] Updated GVL: " + gvl.Path : "[OK] All runtime variables already declared; GVL not modified");
                else if (!gvl.HasVariables) log.Add("[OK] No runtime variables detected; GVL not generated");
            }
            else if (sketch.Elements.Any(element => JsonMap.Text(element.SpecParams, "var").Length > 0 || JsonMap.Text(element.SpecParams, "text_var").Length > 0
                || JsonMap.Text(element.SpecParams, "tap_var").Length > 0 || JsonMap.Text(element.SpecParams, "toggle_var").Length > 0
                || element.SpecParams.ContainsKey("input_actions") || element.SpecParams.ContainsKey("configured_inputs")))
                log.Add("[HINT] SVG contains runtime variable references. Use --gvl to auto-generate GVL declarations.");
            if (!options.Params.ContainsKey("no_preview"))
            {
                var preview = VisuRenderCommands.RenderPreview(svgPath, options.Text("theme", "flat-style"), "",
                    options.Text("background", ""), 0, true, EmptyToNull(options.Text("scheme", "")), view);
                log.AddRange((IList<string>)preview["log"]);
            }
            log.Add("[OK] Compiled " + sketch.Elements.Count + " element(s) from SVG to " + output);
            return new Dictionary<string, object> { ["path"] = output, ["log"] = log };
        }


        static CliFailure Refused(string message) => new CliFailure("visu-from-svg", "refused", message, "cts visu from-svg --help", 1);

        static string EmptyToNull(string text) => string.IsNullOrEmpty(text) ? null : text;

        static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("screen", data["path"]);
            foreach (var line in (IList<string>)data["log"]) answer.Detail(line);
            answer.Detail(data["path"]);
            return answer.Whole();
        }
    }
}
