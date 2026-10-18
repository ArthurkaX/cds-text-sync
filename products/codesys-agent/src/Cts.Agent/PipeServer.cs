using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;

namespace Cts.Agent
{
    // Named-pipe server: \\.\pipe\<name>, one thread per connection, each connection
    // is a Session. Only the user that runs the IDE can connect.
    internal sealed class PipeServer
    {
        const int MaxInstances = 16;
        static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);

        readonly string _name;
        readonly Router _router;
        readonly EventBus _bus;
        readonly FileLog _log;
        readonly object _lock = new object();
        readonly List<NamedPipeServerStream> _open = new List<NamedPipeServerStream>();
        volatile bool _stop;
        Thread _accept;
        //: Since the last connection closed (each cts command is one).
        readonly Stopwatch _sinceClosed = Stopwatch.StartNew();

        public PipeServer(string name, Router router, EventBus bus, FileLog log)
        {
            _name = name;
            _router = router;
            _bus = bus;
            _log = log;
        }

        public void Start()
        {
            // Create the first instance here so a name clash is reported to the caller
            // of Start instead of dying on a background thread.
            var first = Create();
            _accept = new Thread(() => AcceptLoop(first)) { IsBackground = true, Name = "cts-agent-accept" };
            _accept.Start();
        }

        // How long no cts command has been connected: 0 while one is.
        public long QuietMs
        {
            get { lock (_lock) { return _open.Count > 0 ? 0 : _sinceClosed.ElapsedMilliseconds; } }
        }

        public void Stop()
        {
            if (_stop) return;
            _stop = true;
            // Wake the accept thread blocked in WaitForConnection.
            try
            {
                using (var c = new NamedPipeClientStream(".", _name, PipeDirection.InOut))
                    c.Connect(500);
            }
            catch { }
            NamedPipeServerStream[] open;
            lock (_lock) { open = _open.ToArray(); }
            foreach (var p in open)
            {
                try { p.Dispose(); } catch { }
            }
        }

        NamedPipeServerStream Create()
        {
            var security = new PipeSecurity();
            security.AddAccessRule(new PipeAccessRule(WindowsIdentity.GetCurrent().User,
                PipeAccessRights.FullControl, AccessControlType.Allow));
            // Asynchronous (overlapped) on purpose. On a handle opened the plain way Windows
            // serialises I/O: while the session thread waits in ReadLine for the next request,
            // the event pump's write waits behind that read, and a client that only listens
            // never gets an event (seen live: events arrived only when the client sent
            // a request). Overlapped I/O lets a read and a write be in flight at once.
            return new NamedPipeServerStream(_name, PipeDirection.InOut, MaxInstances,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 0, 0, security);
        }

        void AcceptLoop(NamedPipeServerStream server)
        {
            while (!_stop)
            {
                try
                {
                    if (server == null) server = Create();
                    server.WaitForConnection();
                    if (_stop) { server.Dispose(); break; }
                    var connection = server;
                    server = null;
                    lock (_lock) { _open.Add(connection); }
                    new Thread(() => Serve(connection)) { IsBackground = true, Name = "cts-agent-session" }.Start();
                }
                catch (Exception e)
                {
                    if (server != null) { try { server.Dispose(); } catch { } server = null; }
                    if (_stop) break;
                    _log.Write("accept failed: " + e.Message);
                    Thread.Sleep(500);
                }
            }
        }

        void Serve(NamedPipeServerStream pipe)
        {
            try
            {
                var reader = new StreamReader(pipe, Utf8);
                var writer = new StreamWriter(pipe, Utf8) { AutoFlush = true, NewLine = "\n" };
                new Session(reader, writer, _router, _bus).Run();
            }
            catch (Exception e)
            {
                _log.Write("session failed: " + e.Message);
            }
            finally
            {
                lock (_lock) { _open.Remove(pipe); _sinceClosed.Restart(); }
                try { if (pipe.IsConnected) pipe.Disconnect(); } catch { }
                try { pipe.Dispose(); } catch { }
            }
        }
    }
}
