// Request parsing for `objects.export`, kept out of the IDE-facing file so the
// shape rules are unit-tested without a CODESYS process.
//
//   objects.export {"guids": ["<guid>", ...],
//                   "known"?: {"<guid>": <ticks>, ...}, "start_timeout_ms"?: <int>}
//
// `known` names the TimeStamp a client last saw an object with: an object the
// IDE has not restamped since is answered without its XML.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    public static class ExportParams
    {
        public static Dictionary<Guid, long> Known(Request req)
        {
            var known = new Dictionary<Guid, long>();
            object raw;
            if (!req.Params.TryGetValue("known", out raw) || raw == null) return known;
            var entries = raw as IDictionary<string, object>;
            if (entries == null)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'known' must be an object of guid: timestamp");
            foreach (var entry in entries)
            {
                Guid guid;
                if (!Guid.TryParse(entry.Key, out guid))
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'known' has a key that is not a guid: " + entry.Key);
                if (!(entry.Value is long))
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'known' must map " + entry.Key + " to an integer");
                known[guid] = (long)entry.Value;
            }
            return known;
        }
    }
}
