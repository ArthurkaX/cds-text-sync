// The PLC runtime's log (CmpLog), read through the online device's logger
// service -- what the device editor's Log page shows -- and not as a file: a
// runtime may keep its log file outside the directory the file services reach
// (a Linux runtime writes /var/log), but every runtime answers this service.
//
//   `plc.loggers` (`cts plc-log`): the names of the runtime's loggers.
//   `plc.log {logger?}` (`cts plc-log --tail/--cts/--output`): the entries
//     one logger holds, oldest first, read batch after batch; the runtime's
//     first logger -- its standard one -- by default.
//
// Both go through IOnlineDevice3.CreateLoggerServiceHandler ->
// ILoggerServiceHandler, begun and ended on the UI thread with the wait off
// it, like the file services, and like them connected for the run without
// logging in. The deny list key is `plc_log`.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        //: How long one request to the logger service may take: a runtime can
        //: hold many thousands of entries.
        const int PlcLogMs = 120000;

        //: LogSeverity as the runtime's ClassId, the number its log file
        //: writes: LOG_INFO 1, LOG_WARNING 2, LOG_ERROR 4, LOG_EXCEPTION 8,
        //: LOG_DEBUG 16.
        static readonly Dictionary<string, int> LogClasses = new Dictionary<string, int>
        {
            { "Informations", 1 },
            { "Warnings", 2 },
            { "Errors", 4 },
            { "Exceptions", 8 },
            { "DebugMessages", 16 },
        };

        internal Dictionary<string, object> PlcLoggers(int startMs)
        {
            return Connected(DenyRules.PlcLog, "plc.log", startMs,
                online => new Dictionary<string, object> { { "loggers", LoggerNames(online, startMs, out _).ToList<object>() } });
        }

        internal Dictionary<string, object> PlcLog(string logger, int startMs)
        {
            return Connected(DenyRules.PlcLog, "plc.log", startMs, online => Entries(online, logger, startMs));
        }

        Dictionary<string, object> Entries(object online, string logger, int startMs)
        {
            object handler;
            var names = LoggerNames(online, startMs, out handler);
            if (string.IsNullOrEmpty(logger))
            {
                if (names.Length == 0)
                    throw new ProtocolException(ErrorCodes.Unavailable, "The PLC reports no logger.");
                logger = names[0];
            }
            else if (!names.Contains(logger))
                throw new ProtocolException(ErrorCodes.BadParams,
                    "No logger '" + logger + "' on the PLC; it has: " + string.Join(", ", names) + ".");

            var handlerIface = LoggerHandlerType;
            var begin = handlerIface.GetMethod("BeginGetLoggerEntries",
                new[] { typeof(AsyncCallback), typeof(object), typeof(uint), typeof(DateTime), typeof(string) });
            var entryIface = FindType("_3S.CoDeSys.Core.Online.ILoggerEntries");
            var entries = new List<object>();
            var seen = new HashSet<uint>();
            uint after = 0;
            var since = DateTime.MinValue;
            // The service answers one batch of entries; the next batch starts at the
            // handle and time of the last entry read, until a batch brings nothing new.
            while (true)
            {
                var got = (Array)OnDevice("plc.log", startMs, PlcLogMs, "read logger '" + logger + "'",
                    () => (IAsyncResult)begin.Invoke(handler, new object[] { null, null, after, since, logger }),
                    pending => Ended(() => handlerIface.GetMethod("EndGetLoggerEntries").Invoke(handler, new object[] { pending }),
                        "Cannot read logger '" + logger + "' from the PLC: "));
                object last = null;
                if (got != null)
                    foreach (var item in got)
                    {
                        if (!seen.Add((uint)entryIface.GetProperty("EntryHandle").GetValue(item, null))) continue;
                        entries.Add(LogEntry(entryIface, item));
                        last = item;
                    }
                if (last == null) break;
                after = (uint)entryIface.GetProperty("EntryHandle").GetValue(last, null);
                since = (DateTime)entryIface.GetProperty("TimeStamp").GetValue(last, null);
            }
            return new Dictionary<string, object>
            {
                { "logger", logger },
                { "entries", entries },
                { "count", entries.Count },
            };
        }

        static Type LoggerHandlerType
        {
            get { return FindType("_3S.CoDeSys.Core.Online.ILoggerServiceHandler"); }
        }

        // The logger names, and the handler that read them for the caller's
        // next request.
        string[] LoggerNames(object online, int startMs, out object handler)
        {
            var handlerIface = LoggerHandlerType;
            object service = null;
            var names = (string[])OnDevice("plc.log", startMs, PlcLogMs, "list its loggers", () =>
            {
                service = NeedMethod(FindType("_3S.CoDeSys.Core.Online.IOnlineDevice3"), "CreateLoggerServiceHandler", Type.EmptyTypes,
                    "IOnlineDevice3.CreateLoggerServiceHandler is not present in this IDE").Invoke(online, null);
                return (IAsyncResult)handlerIface.GetMethod("BeginGetLoggerNames").Invoke(service, new object[] { null, null });
            }, pending => Ended(() => handlerIface.GetMethod("EndGetLoggerNames").Invoke(service, new object[] { pending }),
                "Cannot list the PLC's loggers: "));
            handler = service;
            return names ?? new string[0];
        }

        // One entry with the fields of a runtime log file line: time (UTC),
        // component id, class, error id, info id, text.
        static Dictionary<string, object> LogEntry(Type entryIface, object item)
        {
            Func<string, object> get = name => entryIface.GetProperty(name).GetValue(item, null);
            int logClass;
            LogClasses.TryGetValue(Convert.ToString(entryIface.GetMethod("GetSeverity").Invoke(item, null), CultureInfo.InvariantCulture), out logClass);
            return new Dictionary<string, object>
            {
                { "time", ((DateTime)get("TimeStamp")).ToString("yyyy-MM-ddTHH:mm:ss.fffZ", CultureInfo.InvariantCulture) },
                { "cmp_id", (long)(uint)get("CmpID") },
                { "class", logClass },
                { "error_id", (long)(uint)get("ErrorID") },
                { "info_id", (long)(uint)get("InfoID") },
                { "info", (string)get("Info") ?? "" },
            };
        }

        static object Ended(Func<object> end, string failure)
        {
            try { return end(); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, failure + Invocation.Cause(e).Message); }
        }
    }
}
