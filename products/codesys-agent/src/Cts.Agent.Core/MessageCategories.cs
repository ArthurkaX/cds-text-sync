// `messages.read` (`cts read-log`): which of the IDE's message categories a
// request names, apart from the IDE that holds them.  A category is
// {guid, description}: the GUID its class declares and the text the Messages
// view shows for it.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    public static class MessageCategories
    {
        //: The compiler's category, the one the Messages view calls "Build".
        public static readonly Guid Build = new Guid("97f48d64-a2a3-4856-b640-75c046e37ea9");

        // The category the request names: by GUID (braces and case do not
        // matter) or by description; none named means Build.  An unknown one
        // is refused with the list of those there are.  Build is the one
        // exception: the IDE registers it with its first compile, so before
        // that it is answered with a category of its own, not in `available`,
        // that holds no messages.
        public static Dictionary<string, object> Pick(string requested, IList<Dictionary<string, object>> available)
        {
            var wanted = string.IsNullOrEmpty(requested) ? Build.ToString() : requested.Trim();
            Guid guid;
            var byGuid = Guid.TryParse(wanted, out guid);
            foreach (var category in available)
                if (byGuid && (string)category["guid"] == guid.ToString()) return category;
            foreach (var category in available)
                if (string.Equals((string)category["description"], wanted, StringComparison.OrdinalIgnoreCase)) return category;
            if ((byGuid && guid == Build) || string.Equals(wanted, "Build", StringComparison.OrdinalIgnoreCase))
                return new Dictionary<string, object> { { "guid", Build.ToString() }, { "description", "Build" } };
            throw new ProtocolException(ErrorCodes.BadParams,
                "Unknown message category '" + wanted + "'. Available categories: " + Describe(available));
        }

        // The newest `last` of the messages, oldest first; all of them for 0.
        public static List<string> Last(IList<string> messages, long last)
        {
            if (last < 0) throw new ProtocolException(ErrorCodes.BadParams, "last must not be negative");
            if (last == 0 || last >= messages.Count) return messages.ToList();
            return messages.Skip(messages.Count - (int)last).ToList();
        }

        static string Describe(IList<Dictionary<string, object>> available)
        {
            if (available.Count == 0) return "(the IDE listed none)";
            return string.Join(", ", available.Select(c => c["description"] + " (" + c["guid"] + ")"));
        }
    }
}
