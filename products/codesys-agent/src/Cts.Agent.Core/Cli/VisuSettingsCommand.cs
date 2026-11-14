using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Visu;

namespace Cts.Cli
{
    // `cts visu settings`: the start screen, scaling and CurrentVisu use of an
    // application's visualization, shown and set in the project view's XML.
    internal static class VisuSettingsCommand
    {
        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "visu", Sub = "settings", Summary = "Show or set the start screen, scaling and CurrentVisu use",
            Description = "Reads the Visualization Manager and its WebVisu/TargetVisu in the project view: StartVisu, BestFit, ScaleTypeIsotropic, CurrentVisuGlobal, "
                + "and what keeps a screen from showing (a StartVisu naming no screen, code writing CurrentVisu while CurrentVisuGlobal is False). "
                + "The options write the files; cts import brings them into the IDE. Exit 1 when a problem is left.",
            Options = new[]
            {
                CliOption.Text("--start-visu", "start_visu", "SCREEN", "The screen every client starts at"),
                CliOption.Choice("--isotropic", "isotropic", "Scale the screen keeping its aspect ratio (ScaleTypeIsotropic of every client)", "on", "off"),
                CliOption.Choice("--current-visu", "current_visu", "Show the screen VisuElems.CurrentVisu names (CurrentVisuGlobal)", "on", "off"),
                CliOption.Text("--folder", "folder", "PATH", "The application, as cts project-tree lists it, when the project has several"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "The sync folder or its project-view (default: the one around the current folder)"),
            },
            LocalExecute = Execute, Build = Build,
        };

        static IDictionary<string, object> Execute(CliOptions options, IAgentHost host, string work)
        {
            var view = VisuScreenCommands.View(options, work, "settings");
            var folder = options.Text("folder", "");
            List<VisuSettings> managers;
            try
            {
                managers = VisuSettings.Below(folder.Length == 0 ? view : ViewPlace.ExistingFolder(view, folder));
            }
            catch (VisuException error)
            {
                throw Refused(error.Message);
            }
            if (managers.Count == 0)
                throw Refused("No Visualization Manager in " + (folder.Length == 0 ? "the project view" : folder)
                    + ": the IDE makes one with an application's first screen; cts import the screen, then cts sync");
            var start = options.Text("start_visu", "");
            var isotropic = options.Text("isotropic", "");
            var currentVisu = options.Text("current_visu", "");
            var changed = new List<object>();
            if (start.Length + isotropic.Length + currentVisu.Length > 0)
            {
                if (managers.Count > 1)
                    throw Refused("Several applications have a visualization: pick one with --folder ("
                        + string.Join(", ", managers.Select(manager => VisuSettings.Relative(view, manager.AppFolder))) + ")");
                var manager = managers[0];
                if (start.Length > 0 && !manager.Screens().Contains(start, StringComparer.OrdinalIgnoreCase))
                    throw Refused("No screen " + start + " in " + VisuSettings.Relative(view, manager.AppFolder) + "; its screens: " + string.Join(", ", manager.Screens()));
                if ((start.Length > 0 || isotropic.Length > 0) && manager.Clients.Count == 0)
                    throw Refused(VisuSettings.Relative(view, manager.ManagerFile) + " has no WebVisu or TargetVisu; add one in the IDE, then cts sync");
                try
                {
                    foreach (var client in manager.Clients)
                    {
                        if (start.Length > 0 && VisuSettings.Set(client, "StartVisu", start)) changed.Add(VisuSettings.Relative(view, client));
                        if (isotropic.Length > 0 && VisuSettings.Set(client, "ScaleTypeIsotropic", isotropic == "on" ? "True" : "False")) changed.Add(VisuSettings.Relative(view, client));
                    }
                    if (currentVisu.Length > 0 && VisuSettings.Set(manager.ManagerFile, "CurrentVisuGlobal", currentVisu == "on" ? "True" : "False"))
                        changed.Add(VisuSettings.Relative(view, manager.ManagerFile));
                }
                catch (VisuException error)
                {
                    throw Refused(error.Message);
                }
            }
            var lines = new List<object>();
            foreach (var manager in managers)
            {
                lines.Add(VisuSettings.Relative(view, manager.ManagerFile) + ": CurrentVisuGlobal=" + (manager.CurrentVisuGlobal ? "True" : "False"));
                foreach (var client in manager.Clients)
                {
                    var xml = File.ReadAllText(client);
                    lines.Add("  " + VisuSettings.Kind(client) + " " + VisuSettings.Relative(view, client) + ": StartVisu=" + VisuSettings.Value(xml, "StartVisu")
                        + " BestFit=" + VisuSettings.Value(xml, "BestFit") + " ScaleTypeIsotropic=" + VisuSettings.Value(xml, "ScaleTypeIsotropic"));
                }
            }
            return new Dictionary<string, object>
            {
                ["lines"] = lines,
                ["changed"] = changed.Distinct().ToList(),
                ["problems"] = managers.SelectMany(manager => manager.Problems(view)).Cast<object>().ToList(),
            };
        }

        static Answer Build(IDictionary<string, object> data)
        {
            var changed = (IList<object>)data["changed"];
            var problems = (IList<object>)data["problems"];
            var answer = new Answer().Add("changed", changed.Count).Add("problems", problems.Count);
            foreach (var line in (IList<object>)data["lines"]) answer.Detail(line);
            foreach (var file in changed) answer.Detail("written " + file + "; cts import brings it into the IDE");
            foreach (var problem in problems) answer.Detail(problem);
            return problems.Count == 0 ? answer.Whole() : answer.Whole().Failed().WithExitCode(1);
        }

        static CliFailure Refused(string message) => new CliFailure("visu-settings", "refused", message, "cts visu settings --help", 1);
    }
}
