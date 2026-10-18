using System;
using System.Linq;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        sealed partial class ImportPlanner
        {
            // An object whose edits overlap, settled by hand in the merge
            // program: the side carried on the right, saved there for both.
            // Null leaves it a conflict.
            StViewObject SideBySide(StViewObject disk, StViewObject ide)
            {
                if (_work.ToolNote != null) return null;
                var hasBody = disk.Implementation != null || ide.Implementation != null;
                string text(StViewObject item) => hasBody
                    ? StripPragma(item.Declaration) + "\n" + StPragma.ImplementationMarker + "\n" + NormalizePart(item.Implementation)
                    : StripPragma(item.Declaration);
                var name = disk.Path.Last();
                string saved;
                try
                {
                    saved = _work.Settling
                        ? ConflictTool.Resolve(_work.Folder, name, "Disk (its edit)", text(disk), "IDE -> Disk: edit, save, close", text(ide))
                        : ConflictTool.Resolve(_work.Folder, name, "IDE (its edit)", text(ide), "Disk -> IDE: edit, save, close", text(disk));
                }
                catch (InvalidOperationException error)
                {
                    _work.ToolNote = error.Message;
                    return null;
                }
                if (saved == null) return null;
                var lines = NormalizePart(saved).Split('\n');
                var markers = Enumerable.Range(0, lines.Length).Where(index => lines[index].Trim() == StPragma.ImplementationMarker).ToList();
                if (hasBody && markers.Count != 1)
                {
                    _work.ToolNote = name + " was saved without its one " + StPragma.ImplementationMarker + " line, so it was left as it is";
                    return null;
                }
                var declaration = hasBody ? string.Join("\n", lines.Take(markers[0])).Trim('\n') : string.Join("\n", lines);
                var pragma = PragmaLine(disk.Declaration);
                return new StViewObject
                {
                    File = disk.File, Path = disk.Path, Kind = disk.Kind,
                    Declaration = pragma == null ? declaration : pragma + "\n" + declaration,
                    Implementation = hasBody ? string.Join("\n", lines.Skip(markers[0] + 1)) : null,
                    TypeGuid = disk.TypeGuid, Settings = disk.Settings,
                };
            }

        }
    }
}
