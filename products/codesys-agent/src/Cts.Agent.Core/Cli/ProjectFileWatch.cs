using System;
using System.Collections.Generic;
using System.IO;

namespace Cts.Cli
{
    // Whether the IDE saved the open project while a command ran: CODESYS can
    // save it on its own during a download (and an older project is then
    // converted to the IDE's version), which cts never asked for.
    internal sealed class ProjectFileWatch
    {
        readonly string _path;
        readonly DateTime _written;

        ProjectFileWatch(string path, DateTime written)
        {
            _path = path;
            _written = written;
        }

        internal static ProjectFileWatch Start(string path) => new ProjectFileWatch(path, Written(path));

        // Adds saved_by_ide to *data* when the project file changed since Start.
        internal void Report(IDictionary<string, object> data)
        {
            if (_written != DateTime.MinValue && Written(_path) != _written) data["saved_by_ide"] = true;
        }

        static DateTime Written(string path)
        {
            try { return !string.IsNullOrEmpty(path) && File.Exists(path) ? File.GetLastWriteTimeUtc(path) : DateTime.MinValue; }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is ArgumentException) { return DateTime.MinValue; }
        }
    }
}
