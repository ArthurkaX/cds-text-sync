using System;

namespace Cts.Agent
{
    // An editor of the IDE keeps the edit of the line the caret is on to itself
    // until the caret leaves that line: until then the object holds the text
    // without it.  Before a method that reads, writes or compiles the objects
    // the agent has every open editor give its text to its object, so a read
    // sees what the user sees and a write is not undone when the editor gives
    // its text later.
    public static class OpenEditors
    {
        public static bool CommitFirst(string method)
        {
            return method.StartsWith("objects.", StringComparison.Ordinal)
                || method.StartsWith("journal.", StringComparison.Ordinal)
                || method == "project.export" || method == "project.save"
                || method == "app.build" || method == "app.download" || method == "app.login";
        }
    }
}
