using System.Collections.Generic;

namespace Cts.Cli
{
    internal sealed class CompareRecord
    {
        internal string Name;
        internal string Path;
        internal string Category;
        internal string Reason;
        internal IList<string> Parts;
        internal string Guid;
        internal bool HasGuid;
        internal bool IdeChanged;
        internal bool Merges;
        internal byte[] MergedXml;
        internal string ObjectPath;
        internal long? Timestamp;
        internal string Kind;
        internal string ParentGuid;
        internal string ParentKey;

        internal IDictionary<string, object> Answer()
        {
            var answer = new Dictionary<string, object> { { "name", Name }, { "path", Path } };
            if (Reason != null) answer["reason"] = Reason;
            if (IdeChanged) answer["ide_changed"] = true;
            if (Merges) answer["merges"] = true;
            if (Guid != null) answer["guid"] = Guid;
            if (Parts != null && Parts.Count > 0) answer["parts"] = Parts;
            return answer;
        }
    }

    internal sealed class ComparePlan
    {
        internal IDictionary<string, object> Payload;
        internal IDictionary<string, object> Summary;
        internal IDictionary<string, byte[]> IdeFiles;
        internal IList<Cts.Sync.StViewObject> IdeObjects;
        internal IList<Cts.Sync.StViewObject> BaseObjects;
        internal IList<CompareRecord> Records;
    }
}
