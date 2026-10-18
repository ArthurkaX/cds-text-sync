using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Cts.Analysis;
using Cts.Visu;

namespace Cts.Cli
{
    internal static class VisuRenderCommands
    {
        internal static IList<CliCommand> Commands => new[] { ToSvg, PreviewCommand };

        static readonly CliCommand ToSvg = new CliCommand
        {
            Name = "visu", Sub = "to-svg", Summary = "Decompile a CODESYS screen to SVG",
            Description = "Read an exported visualization XML screen and write its SVG sketch beside it or at --out.",
            Options = new[]
            {
                CliOption.Needed("--screen", "screen", "NAME", "Screen name or XML path"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder or project-view directory"),
                CliOption.Text("--folder", "folder", "PATH", "Folder of the screen as cts project-tree lists it"),
                CliOption.Text("--out", "out", "FILE", "Output SVG path"),
                CliOption.Choice("--scheme", "scheme", "Colour scheme", "light", "dark"),
            },
            LocalExecute = (options, host, work) => Export(options, work),
            Build = data => new Answer().Add("out", data["path"]),
        };

        static readonly CliCommand PreviewCommand = new CliCommand
        {
            Name = "visu", Sub = "preview", Summary = "Render an SVG sketch to a viewable SVG and PNG",
            Description = "Resolve the sketch palette, write a preview SVG, and rasterize it when headless Chrome or Edge is available.",
            Options = new[]
            {
                CliOption.Needed("--svg", "svg", "FILE", "SVG sketch"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder or project-view directory"),
                CliOption.Text("--theme", "theme", "NAME", "Style preset (default flat-style)"),
                CliOption.Text("--out", "out", "FILE", "Output SVG or PNG path"),
                CliOption.Text("--background", "background", "COLOR", "Canvas background"),
                CliOption.Choice("--scheme", "scheme", "Colour scheme", "light", "dark"),
                CliOption.Int("--grid", "grid", "Grid spacing in pixels"),
                CliOption.Switch("--no-png", "no_png", "Write only the preview SVG"),
            },
            LocalExecute = (options, host, work) => PreviewFile(options, work),
            Build = data => BuildPreview(data),
        };

        static IDictionary<string, object> Export(CliOptions options, string work)
        {
            var screen = options.Text("screen", "");
            if (string.IsNullOrWhiteSpace(screen)) throw Refused("No screen given: pass --screen <name> to target an existing screen");
            var folder = ProjectView(options.Text("sync_folder", ""), work);
            string xmlPath;
            try { xmlPath = ViewPlace.Screen(folder, screen, options.Text("folder", "")); }
            catch (VisuException error) { throw Refused(error.Message); }
            if (!File.Exists(xmlPath)) throw Refused("Screen file not found: " + xmlPath);
            string svg;
            try
            {
                svg = SvgExport.ScreenToSvg(File.ReadAllText(xmlPath, new UTF8Encoding(false, true)), EmptyToNull(options.Text("scheme", "")));
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is VisuException)
            {
                throw Refused(error.Message);
            }
            var output = options.Text("out", "");
            if (string.IsNullOrEmpty(output)) output = Path.ChangeExtension(xmlPath, ".svg");
            else output = Path.GetFullPath(output);
            Write(output, svg);
            return new Dictionary<string, object> { ["path"] = output };
        }

        static IDictionary<string, object> PreviewFile(CliOptions options, string work)
        {
            var project = ProjectView(options.Text("sync_folder", ""), work, true);
            var result = RenderPreview(options.Text("svg", ""), options.Text("theme", "flat-style"), options.Text("out", ""),
                options.Text("background", ""), options.Number("grid", 0), !options.Params.ContainsKey("no_png"),
                EmptyToNull(options.Text("scheme", "")), project);
            return result;
        }

        internal static IDictionary<string, object> RenderPreview(string svgPath, string theme, string output, string background,
            int grid, bool png, string scheme, string projectView)
        {
            if (string.IsNullOrWhiteSpace(svgPath)) throw Refused("--svg is required");
            svgPath = Path.GetFullPath(svgPath);
            if (!File.Exists(svgPath)) throw Refused("SVG file not found: " + svgPath);
            Sketch sketch;
            try
            {
                sketch = Sketch.Parse(File.ReadAllText(svgPath, new UTF8Encoding(false, true)), projectView,
                    EmptyToNull(background), scheme, EmptyToNull(theme));
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is VisuException)
            {
                throw Refused(error.Message);
            }
            var basePath = string.IsNullOrEmpty(output) ? Path.ChangeExtension(svgPath, ".preview.svg") : Path.GetFullPath(output);
            var svgOutput = basePath.EndsWith(".png", StringComparison.OrdinalIgnoreCase)
                ? Path.ChangeExtension(basePath, ".svg") : basePath;
            var pngOutput = basePath.EndsWith(".png", StringComparison.OrdinalIgnoreCase)
                ? basePath : Path.ChangeExtension(basePath, ".png");
            var rendered = Preview.Render(sketch, grid);
            try { Write(svgOutput, rendered); }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
            {
                throw Refused(error.Message);
            }
            string written = null;
            if (png) written = Browser.Rasterize(svgOutput, pngOutput, sketch.Width, sketch.Height);
            var log = new List<string> { "[OK] Preview SVG: " + svgOutput };
            if (png && written != null) log.Add("[OK] Preview PNG: " + written);
            else if (png) log.Add("[OK] No headless Chrome/Edge found; open the SVG above, or set CHROME_PATH to rasterise.");
            return new Dictionary<string, object> { ["svg"] = svgOutput, ["png"] = written, ["log"] = log };
        }

        static Answer BuildPreview(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("svg", data["svg"]).Add("png", data["png"]);
            foreach (var line in (IList<string>)data["log"]) answer.Detail(line);
            return answer.Whole();
        }

        static string ProjectView(string path, string work, bool optional = false)
        {
            try { return AnalyzeWorkspace.Resolve(string.IsNullOrWhiteSpace(path) ? null : path, null, work).View; }
            catch (AnalyzeException error)
            {
                if (optional && string.IsNullOrWhiteSpace(path)) return null;
                throw Refused(error.Message);
            }
        }


        static void Write(string path, string text)
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            File.WriteAllText(path, text, new UTF8Encoding(false));
        }

        static string EmptyToNull(string value) => string.IsNullOrEmpty(value) ? null : value;

        static CliFailure Refused(string message) => new CliFailure("visu", "refused", message, "cts guide visu-svg", 1);
    }
}
