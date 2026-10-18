// Request parsing for `objects.texts`, kept out of the IDE-facing file so the
// shape rules are unit-tested without a CODESYS process.
//
//   objects.texts {"guids"?: ["<guid>", ...], "start_timeout_ms"?: <int>}
//
// Without `guids` the call walks the whole primary project; with it, only the
// named objects.

namespace Cts.Agent
{
    public static class TextsParams
    {
        // The requested guids, or null when the call walks the whole project.
        // Every entry must be a non-empty string; the caller validates it as a
        // GUID when it opens the object, the way `objects.text` does.
        public static string[] Guids(Request req)
        {
            return req.Strings("guids");
        }
    }
}
