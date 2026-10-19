using System.Collections.Generic;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        // The data planned for one import and consumed by its apply phase.
        internal sealed class ImportWork
        {
            internal bool Syncing, Settling;
            internal IDictionary<string, object> Data;
            internal IDictionary<string, byte[]> IdeFiles;
            internal IList<StViewObject> IdeObjects;
            internal List<CompareRecord> Changed;
            internal string OtherProject, Folder, View;
            // The view's files before the planner read them, to tell a file changed meanwhile.
            internal ViewStamps Stamps;
            internal bool HasBase;
            internal string ToolNote;
            internal StViewResult Parsed;
            internal Dictionary<string, TreeObject> IdeNodes;
            internal Dictionary<string, string> IdeByPath;
            internal List<CompareRecord> ForceRecords, StRecords, FolderRecords, Deleted, NativeRecords, CsvRecords;
            internal List<IDictionary<string, object>> FieldReadBack, Conflicts;
            internal List<CompareRecord> NativeDeletes, NativeGone, NativeImports, NativeReplaces, NativeIdeTaken;
            internal List<TextListPlan> CsvPlans;
            internal List<AddedText> AddedItems;
            internal List<string> CreatedAccessorNames, Updated, ForcedDeletes, ForcedDeletedNames, CreatedFolders, ForcedCreated, CsvGone, Merged, IdeNewTextFiles;
            internal List<StViewObject> ForcedCreateItems, IdeNewTextObjects;
            internal List<TextWrite> Writes;
            internal List<MergeFileEdit> MergeFiles, IdeToDisk;
            internal List<RenameText> Renames;
            internal Dictionary<string, string> Created;
            // The IDE export of each native to replace before the write.
            internal Dictionary<string, IDictionary<string, object>> NativeBefore;
        }
    }
}
