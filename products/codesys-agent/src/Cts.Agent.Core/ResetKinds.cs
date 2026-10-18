// `app.reset` (`cts reset`): the reset kinds, the IDE's ResetOption value each
// one is, and the deny list key it answers to.  An origin reset erases the
// application from the PLC, so it needs `force`, and its own key lets a deny
// list refuse it alone ("reset_plc" refuses every kind, as a prefix).

namespace Cts.Agent
{
    public static class ResetKinds
    {
        public const string DenyKey = "reset_plc";
        public const string OriginDenyKey = "reset_plc --kind origin";

        // ResetOption: Warm = 0, Cold = 1, Original = 2.
        public static int Option(string kind, bool force)
        {
            switch ((kind ?? "").Trim().ToLowerInvariant())
            {
                case "":
                case "warm": return 0;
                case "cold": return 1;
                case "origin":
                    if (!force)
                        throw new ProtocolException(ErrorCodes.BadParams,
                            "DANGEROUS: an origin reset erases the application from the PLC, "
                            + "restoring it to factory state. Pass --force to confirm.");
                    return 2;
            }
            throw new ProtocolException(ErrorCodes.BadParams, "Invalid reset kind: " + kind + ". Use warm, cold, or origin.");
        }

        public static string KeyOf(int option)
        {
            return option == 2 ? OriginDenyKey : DenyKey;
        }

        public static string NameOf(int option)
        {
            return option == 2 ? "origin" : option == 1 ? "cold" : "warm";
        }
    }
}
