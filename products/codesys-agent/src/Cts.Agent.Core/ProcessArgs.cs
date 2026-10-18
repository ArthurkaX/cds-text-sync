using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace Cts.Agent
{
    // Arguments as one Windows command line, each read back whole by the C
    // runtime's rules (.NET on Linux reads them the same way).
    public static class ProcessArgs
    {
        // *args* joined by blanks, each quoted as Quote does.
        public static string Join(IEnumerable<string> args)
        {
            return string.Join(" ", args.Select(Quote));
        }

        // *arg* quoted when it has a blank or a quote or is empty, a quote
        // escaped, the backslashes before one doubled; other backslashes stay
        // single, so a Windows path arrives as written. An argument that needs
        // none stays bare: WinMerge takes a quoted "/e" for a file named e,
        // not for its option.
        public static string Quote(string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return arg;
            var quoted = new StringBuilder("\"");
            var slashes = 0;
            foreach (var c in arg)
            {
                if (c == '\\') { slashes++; continue; }
                quoted.Append('\\', c == '"' ? slashes * 2 + 1 : slashes).Append(c);
                slashes = 0;
            }
            return quoted.Append('\\', slashes * 2).Append('"').ToString();
        }
    }
}
