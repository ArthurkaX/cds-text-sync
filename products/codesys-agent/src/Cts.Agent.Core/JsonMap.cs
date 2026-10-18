using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Agent
{
    // Readers of the JSON-shaped maps the agent and the commands pass around:
    // a missing map, key or list reads as nothing, never as an exception.
    internal static class JsonMap
    {
        internal static object Value(IDictionary<string, object> data, string key)
            => data != null && data.TryGetValue(key, out var value) ? value : null;

        internal static string Text(IDictionary<string, object> data, string key)
            => Convert.ToString(Value(data, key), CultureInfo.InvariantCulture) ?? "";

        // The value at key as text; fallback when it is missing or null.
        internal static string Text(IDictionary<string, object> data, string key, string fallback)
            => Value(data, key) is object value ? Convert.ToString(value, CultureInfo.InvariantCulture) ?? fallback : fallback;

        // A number, or a string that reads as one; fallback for anything else.
        internal static double Number(IDictionary<string, object> data, string key, double fallback = 0)
            => double.TryParse(Convert.ToString(Value(data, key), CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed) ? parsed : fallback;

        // A whole number, 0 when the key is missing or null.
        internal static int Int(IDictionary<string, object> data, string key)
            => Value(data, key) is object value ? Convert.ToInt32(value, CultureInfo.InvariantCulture) : 0;

        internal static IEnumerable<object> Items(IDictionary<string, object> data, string key)
            => Value(data, key) is IEnumerable items && !(items is string) ? items.Cast<object>() : Enumerable.Empty<object>();

        internal static IEnumerable<IDictionary<string, object>> Maps(IDictionary<string, object> data, string key)
            => Items(data, key).OfType<IDictionary<string, object>>();
    }
}
