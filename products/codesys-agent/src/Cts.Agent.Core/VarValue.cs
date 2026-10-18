// Values that cross the wire for `vars.read` / `vars.write`.
//
// A PLC variable's value is whatever .NET object the IDE hands back: an unsigned
// word is a UInt32, a REAL is a Single, and a struct or an array is some vendor
// object with no useful JSON shape at all.  The protocol carries JSON, so a read
// value is turned into a JSON scalar (bool, integer, real number, string) or, for
// anything that is not a scalar, into its text plus the .NET type name, which the
// caller can show but not round-trip.
//
// A write goes the other way.  A JSON string is handed to the IDE as it is: the
// IDE parses it as an ST literal for the variable's type (`5`, `WORD#5`,
// `E_Mode.Run`, `T#2s`), which is what the CLI sends, the user's own text.  A
// bool or a number is turned into the CLR type the variable actually has; a
// value that type cannot hold is refused with `bad_params` rather than coerced
// silently, and a JSON shape that is not a scalar (null, array, object) is
// refused before the IDE is touched.
using System;
using System.Collections;
using System.Globalization;

namespace Cts.Agent
{
    public static class VarValue
    {
        // ---- read: a CLR value as something JSON can carry

        // The .NET type name of a value, for the result's `type` field.  The IEC
        // type (WORD, REAL, ...) is the variable's declaration, not the value's
        // runtime type, and is not resolved here.
        public static string TypeName(object value)
        {
            return value == null ? null : value.GetType().FullName;
        }

        // A JSON-able value and its .NET type name.  A scalar maps to a JSON
        // scalar; anything else maps to its text, with `isScalar` false so the
        // caller can say so.
        public static object ToJson(object value, out string typeName, out bool isScalar)
        {
            typeName = TypeName(value);
            if (value == null) { isScalar = false; return null; }
            if (value is bool) { isScalar = true; return (bool)value; }
            if (value is string) { isScalar = true; return (string)value; }
            if (value is char) { isScalar = true; return value.ToString(); }
            if (value is float || value is double || value is decimal)
            { isScalar = true; return Convert.ToDouble(value, CultureInfo.InvariantCulture); }
            if (value is sbyte || value is byte || value is short || value is ushort
                || value is int || value is uint || value is long)
            { isScalar = true; return Convert.ToInt64(value, CultureInfo.InvariantCulture); }
            if (value is ulong)
            {
                var u = (ulong)value;
                isScalar = true;
                if (u <= long.MaxValue) return (long)u;
                // Beyond Int64 a number still fits JSON's range only as a real.
                return (double)u;
            }
            if (value is Enum) { isScalar = true; return value.ToString(); }
            if (value is Guid) { isScalar = true; return value.ToString(); }
            if (value is DateTime)
            {
                isScalar = true;
                return ((DateTime)value).ToUniversalTime()
                    .ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);
            }
            // A struct, an array, a vendor object: text is all that crosses
            // honestly.  Never its IEnumerable shape -- iterating a live IDE
            // object here would be a second, unguarded IDE call.
            isScalar = false;
            return Describe(value);
        }

        static string Describe(object value)
        {
            try
            {
                var text = Convert.ToString(value, CultureInfo.InvariantCulture);
                return text ?? "";
            }
            catch (Exception) { return ""; }
        }

        // ---- write: a JSON scalar as the CLR value the variable holds

        // True when the JSON shape is one `vars.write` accepts at all.
        public static bool IsWritableShape(object json)
        {
            return json is bool || json is string || json is long || json is double;
        }

        // The JSON value as an instance of `target`, or a `bad_params` refusal.
        //
        // A string goes to the IDE unchanged, for it to parse (see the header).
        // `target` is the variable's CLR type when the agent knows it (from an
        // earlier read of the same watch); when it is null the value is passed as
        // the natural CLR type of the JSON scalar, which is what a live probe
        // proved works (an Int64 for a WORD variable).
        public static object FromJson(object json, Type target, string what)
        {
            if (json == null)
                throw new ProtocolException(ErrorCodes.BadParams, what + ": null is not a value");
            if (json is IDictionary || json is IList)
                throw new ProtocolException(ErrorCodes.BadParams,
                    what + ": a value must be a bool, a number or a string, not an array or an object");
            if (!IsWritableShape(json))
                throw new ProtocolException(ErrorCodes.BadParams,
                    what + ": a value must be a bool, a number or a string");

            if (target == null || json is string) return json;

            var want = Nullable.GetUnderlyingType(target) ?? target;

            if (json is bool)
            {
                if (want == typeof(bool)) return json;
                Refuse(json, want, what);
            }

            // A number: integral JSON goes to integral targets, a real to any
            // numeric target.  A value out of the target's range is refused, not
            // wrapped around.
            if (json is long)
            {
                if (want == typeof(double)) return (double)(long)json;
                if (want == typeof(float)) return (float)(long)json;
                if (want == typeof(decimal)) return (decimal)(long)json;
                return ConvertIntegral((long)json, want, what);
            }
            var d = (double)json;
            if (want == typeof(double)) return d;
            if (want == typeof(float)) return (float)d;
            if (want == typeof(decimal)) return (decimal)d;
            throw new ProtocolException(ErrorCodes.BadParams,
                what + ": " + want.Name + " is not a real number type; write an integer");
        }

        static object ConvertIntegral(long value, Type want, string what)
        {
            try
            {
                if (want == typeof(sbyte)) return checked((sbyte)value);
                if (want == typeof(byte)) return checked((byte)value);
                if (want == typeof(short)) return checked((short)value);
                if (want == typeof(ushort)) return checked((ushort)value);
                if (want == typeof(int)) return checked((int)value);
                if (want == typeof(uint)) return checked((uint)value);
                if (want == typeof(long)) return value;
                if (want == typeof(ulong)) return checked((ulong)value);
            }
            catch (OverflowException)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    what + ": " + value.ToString(CultureInfo.InvariantCulture)
                    + " does not fit in " + want.Name);
            }
            throw new ProtocolException(ErrorCodes.BadParams,
                what + ": " + want.FullName + " is not an integer type");
        }

        static void Refuse(object value, Type want, string what)
        {
            throw new ProtocolException(ErrorCodes.BadParams,
                what + ": a " + value.GetType().Name + " value cannot be written to a "
                + want.Name + " variable");
        }
    }
}
