using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

namespace Cts.Cli
{
    // cts.exe: every cts command (CliCommands), talking to the in-IDE agent
    // over its named pipe.
    static class Program
    {
        static int Main(string[] args)
        {
            InputWithoutPreamble();
            var output = Writer(ConsoleText.Output, Console.OpenStandardOutput);
            var error = Writer(ConsoleText.Error, Console.OpenStandardError);
            Console.SetOut(output);
            Console.SetError(error);
            return CliRun.Run(CliCommands.Find(args), args, new PipeHost(), Environment.GetEnvironmentVariable("CTS_TARGET"),
                Environment.CurrentDirectory, output, error);
        }

        // UTF-8 to a pipe or a file, what git, the quick window and a script
        // read; a console window gets the text itself, which it shows whatever
        // its code page (the bytes of "·" would show there as "Â·" or "┬╖").
        static TextWriter Writer(int stream, Func<Stream> open)
        {
            return ConsoleText.For(stream) ?? (TextWriter)new StreamWriter(open(), new UTF8Encoding(false)) { AutoFlush = true };
        }

        // A process started with its input redirected gets a writer in the
        // console's input encoding, flushed at once: on a UTF-8 console
        // (chcp 65001) that puts a byte order mark before what cts writes to
        // git, which git refuses ("malformed index info").  The same code page
        // without the mark keeps the console as it was.
        static void InputWithoutPreamble()
        {
            try
            {
                if (Console.InputEncoding.CodePage == 65001 && Console.InputEncoding.GetPreamble().Length > 0)
                    Console.InputEncoding = new UTF8Encoding(false);
            }
            catch (IOException) { }   // no console to set: nothing to strip either
        }
    }

    // Text written to a console window with WriteConsoleW.
    sealed class ConsoleText : TextWriter
    {
        internal const int Output = -11, Error = -12;
        // Older consoles refuse one long write; a chunk ends before a surrogate pair is split.
        const int Chunk = 8192;

        readonly IntPtr _handle;

        ConsoleText(IntPtr handle)
        {
            _handle = handle;
        }

        // A writer for the standard stream when it is a console window, else null.
        internal static ConsoleText For(int stream)
        {
            var handle = GetStdHandle(stream);
            return handle != IntPtr.Zero && handle != new IntPtr(-1) && GetConsoleMode(handle, out _) ? new ConsoleText(handle) : null;
        }

        public override Encoding Encoding => Encoding.Unicode;

        public override void Write(char value) => Write(value.ToString());

        public override void Write(char[] buffer, int index, int count) => Write(new string(buffer, index, count));

        public override void Write(string value)
        {
            for (var at = 0; value != null && at < value.Length;)
            {
                var length = Math.Min(Chunk, value.Length - at);
                if (length < value.Length - at && char.IsHighSurrogate(value[at + length - 1])) length--;
                if (!WriteConsoleW(_handle, value.Substring(at, length), length, out _, IntPtr.Zero)) return;
                at += length;
            }
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr GetStdHandle(int stream);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetConsoleMode(IntPtr handle, out int mode);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool WriteConsoleW(IntPtr handle, string text, int length, out int written, IntPtr reserved);
    }

    // The agents of this PC: \\.\pipe\cts-agent-<pid>, one per IDE.
    sealed class PipeHost : IAgentHost
    {
        const int ConnectTimeoutMs = 3000;

        public IList<int> Pids()
        {
            var pids = PipeNames().Select(n => n.StartsWith("cts-agent-", StringComparison.Ordinal) && int.TryParse(n.Substring(10), out var pid) ? pid : 0)
                .Where(pid => pid > 0).Distinct().OrderBy(pid => pid).ToList();
            // The quick window sets it for the cts it runs: the command goes to
            // the IDE it was started from even with several open.
            var only = Environment.GetEnvironmentVariable("CTS_IDE_PID");
            return int.TryParse(only, out var one) ? pids.Where(pid => pid == one).ToList() : pids;
        }

        public AgentConnection Open(int pid)
        {
            var name = "cts-agent-" + pid;
            var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
            try { pipe.Connect(ConnectTimeoutMs); }
            catch (Exception e) when (e is TimeoutException || e is IOException)
            {
                pipe.Dispose();
                throw new AgentException("transport", "cannot open " + name + ": " + e.Message);
            }
            return new AgentConnection(pipe, name);
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct FindData
        {
            public uint Attributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
            public uint SizeHigh, SizeLow, Reserved0, Reserved1;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string FileName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)] public string AlternateName;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr FindFirstFileW(string pattern, out FindData data);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool FindNextFileW(IntPtr handle, out FindData data);

        [DllImport("kernel32.dll")]
        static extern bool FindClose(IntPtr handle);

        static IEnumerable<string> PipeNames()
        {
            var names = new List<string>();
            var handle = FindFirstFileW(@"\\.\pipe\*", out var data);
            if (handle == new IntPtr(-1)) return names;
            try
            {
                do names.Add(data.FileName); while (FindNextFileW(handle, out data));
            }
            finally { FindClose(handle); }
            return names;
        }
    }
}
