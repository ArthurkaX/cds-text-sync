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
                var name = disk.Path.Last();
                string saved;
                try
                {
                    saved = _work.Settling
                        ? ConflictTool.Resolve(_work.Folder, name, "Disk (its edit)", Settled(disk, hasBody), "IDE -> Disk: edit, save, close", Settled(ide, hasBody))
                        : ConflictTool.Resolve(_work.Folder, name, "IDE (its edit)", Settled(ide, hasBody), "Disk -> IDE: edit, save, close", Settled(disk, hasBody));
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
                    TypeGuid = disk.TypeGuid, Settings = disk.Settings, Folder = disk.Folder,
                };
            }

            // One side's text of an object as a person settles it: the
            // declaration, then the marker line and the body when a side has one.
            static string Settled(StViewObject item, bool hasBody) => hasBody
                ? StripPragma(item.Declaration) + "\n" + StPragma.ImplementationMarker + "\n" + NormalizePart(item.Implementation)
                : StripPragma(item.Declaration);
        }
    }
}
