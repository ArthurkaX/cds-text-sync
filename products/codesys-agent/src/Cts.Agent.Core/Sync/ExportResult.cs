using System.Collections.Generic;

namespace Cts.Sync
{
    public sealed class NativeExport
    {
        public string Guid { get; internal set; }
        public long Timestamp { get; internal set; }
        public string Path { get; internal set; }
    }

    public sealed class ExportResult
    {
        public IList<string> KeptOrphans { get; private set; } = new List<string>();
        public IList<NativeExport> Natives { get; private set; } = new List<NativeExport>();
        internal IDictionary<string, IList<string>> GuidFiles { get; } = new Dictionary<string, IList<string>>(System.StringComparer.OrdinalIgnoreCase);
        public IList<string> PendingImport { get; internal set; } = new List<string>();
        // Library Managers and Project Settings this PC's IDE wrote differently, put back as they were (ProjectInfo.OwnerKeeps).
        public IList<string> OwnerKept { get; internal set; } = new List<string>();
        public string Base { get; internal set; }
        public bool BaseRecorded { get; internal set; } = true;
        // The view files Git's ignore rules match: not written, not removed (ViewIgnore).
        internal ISet<string> Ignored { get; set; } = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase);
        // The snapshot as read for the view, so a caller needs no second read.
        internal ProjectModel Model { get; set; }
    }

    internal sealed class ViewPatchResult
    {
        internal IViewFiles Files;
        internal IDictionary<string, IList<string>> GuidFiles;
        internal string FallbackReason;
    }
}
