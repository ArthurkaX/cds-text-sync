using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using Cts.Agent;

namespace Cts.Cli
{
    // An error reply of the agent, or a transport failure (code `transport` or
    // `timeout`).
    public sealed class AgentException : Exception
    {
        public string Code { get; private set; }
        // The error reply's `data`, or null.
        public IDictionary<string, object> Detail { get; private set; }

        public AgentException(string code, string message, IDictionary<string, object> detail = null) : base(message)
        {
            Code = code;
            Detail = detail;
        }
    }

    // One connection to an in-IDE agent, the client side of Protocol: one
    // UTF-8 JSON object per line; a call waits for the reply with its id and
    // skips anything else (an event).
    public sealed class AgentConnection : IDisposable
    {
        static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);

        readonly Stream _stream;
        readonly string _name;
        readonly MemoryStream _pending = new MemoryStream();
        readonly byte[] _chunk = new byte[65536];
        long _nextId;
        bool _broken;

        public AgentConnection(Stream stream, string name)
        {
            _stream = stream;
            _name = name;
        }

        public object Call(string method, IDictionary<string, object> parameters, int timeoutMs)
        {
            if (_broken) throw new AgentException("transport", "the connection to " + _name + " is closed");
            var id = ++_nextId;
            var request = new Dictionary<string, object>
            {
                { "id", id },
                { "method", method },
                { "params", parameters ?? new Dictionary<string, object>() },
            };
            var bytes = Utf8.GetBytes(Json.Serialize(request) + "\n");
            try
            {
                _stream.Write(bytes, 0, bytes.Length);
                _stream.Flush();
            }
            catch (IOException e)
            {
                _broken = true;
                throw new AgentException("transport", "write to " + _name + " failed: " + e.Message);
            }
            var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            while (true)
            {
                var reply = Json.Parse(ReadLine(method, deadline, timeoutMs)) as IDictionary<string, object>;
                if (reply == null || !reply.TryGetValue("id", out var replyId) || !Equals(replyId, id)) continue;
                if (reply.TryGetValue("ok", out var ok) && ok is bool b && b)
                    return reply.TryGetValue("result", out var result) ? result : null;
                var error = (reply.TryGetValue("error", out var e) ? e : null) as IDictionary<string, object>;
                throw new AgentException(
                    Convert.ToString(error != null && error.TryGetValue("code", out var code) ? code : "internal"),
                    Convert.ToString(error != null && error.TryGetValue("message", out var message) ? message : "error reply without a message"),
                    error != null && error.TryGetValue("data", out var data) ? data as IDictionary<string, object> : null);
            }
        }

        string ReadLine(string method, DateTime deadline, int timeoutMs)
        {
            while (true)
            {
                var buffer = _pending.GetBuffer();
                var end = Array.IndexOf(buffer, (byte)'\n', 0, (int)_pending.Length);
                if (end >= 0)
                {
                    var line = Utf8.GetString(buffer, 0, end);
                    var rest = (int)_pending.Length - end - 1;
                    Buffer.BlockCopy(buffer, end + 1, buffer, 0, rest);
                    _pending.SetLength(rest);
                    if (line.Trim().Length > 0) return line;
                    continue;
                }
                var left = (int)Math.Max(0, (deadline - DateTime.UtcNow).TotalMilliseconds);
                Task<int> read;
                try { read = _stream.ReadAsync(_chunk, 0, _chunk.Length); }
                catch (IOException e) { _broken = true; throw new AgentException("transport", "read from " + _name + " failed: " + e.Message); }
                if (!read.Wait(left))
                {
                    // The IDE may still be running it: from here the outcome is unknown.
                    _broken = true;
                    throw new AgentException("timeout", "no reply to " + method + " from " + _name + " within "
                        + (timeoutMs / 1000.0).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture) + " s; the IDE may still be running it (the outcome is unknown)");
                }
                int count;
                try { count = read.Result; }
                catch (AggregateException e) { _broken = true; throw new AgentException("transport", "read from " + _name + " failed: " + e.InnerException.Message); }
                if (count == 0) { _broken = true; throw new AgentException("transport", _name + " closed the connection"); }
                _pending.Write(_chunk, 0, count);
            }
        }

        public void Dispose()
        {
            _broken = true;
            _stream.Dispose();
        }
    }
}
