// `app.crc` (`cts plc-crc`): whether the PLC runs the code the IDE generated
// last.  Code and data are named by GUIDs on both sides -- the online
// application's CodeId / DataId, read at the login, and the language model's
// compiled ids -- whose first field is the checksum the code generator gave
// them (the compile context's CheckSumCode / CheckSumData), the rest zero;
// that number is what is compared and shown.  Every code generation (a
// download, a login, an online change, Build -> Generate code) gives new
// ids even for unchanged source, and a Compile gives none, so a match says
// the PLC runs that generation -- not that it holds the source as edited
// since.  Zero on a side means it has nothing to compare: no application on
// the PLC, or no code generated yet.
using System;
using System.Collections.Generic;
using System.Globalization;

namespace Cts.Agent
{
    public static class AppChecksums
    {
        public const string DenyKey = "plc_crc";

        public static uint OfId(Guid id)
        {
            return BitConverter.ToUInt32(id.ToByteArray(), 0);
        }

        public static Dictionary<string, object> Compare(string application, uint plcCode, uint plcData, uint ideCode, uint ideData)
        {
            var onPlc = plcCode != 0 || plcData != 0;
            var generated = ideCode != 0 || ideData != 0;
            var answer = new Dictionary<string, object>
            {
                { "application", application },
                { "plc", onPlc ? Pair(plcCode, plcData) : null },
                { "ide", generated ? Pair(ideCode, ideData) : null },
                { "match", onPlc && generated ? (object)(plcCode == ideCode && plcData == ideData) : null },
            };
            if (!onPlc)
                answer["note"] = "No application on the PLC: 'cts download' puts it there.";
            else if (!generated)
                answer["note"] = "The IDE has generated no code for the application since it started: 'cts download' does.";
            return answer;
        }

        static Dictionary<string, object> Pair(uint code, uint data)
        {
            return new Dictionary<string, object>
            {
                { "code", code.ToString("x8", CultureInfo.InvariantCulture) },
                { "data", data.ToString("x8", CultureInfo.InvariantCulture) },
            };
        }
    }
}
