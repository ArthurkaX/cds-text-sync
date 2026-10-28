using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

namespace Cts.Trend
{
    // SQLite through the winsqlite3.dll every Windows 10 and later carries,
    // so cts ships no database library of its own.
    internal sealed class Sqlite : IDisposable
    {
        internal const string Library = "winsqlite3";
        const int Ok = 0, Row = 100, Done = 101;
        const int ReadOnly = 1, ReadWrite = 2, Create = 4;
        const int Integer = 1, Float = 2, Text = 3, Null = 5;
        static readonly IntPtr Transient = new IntPtr(-1);

        IntPtr _db;

        Sqlite(IntPtr db) { _db = db; }

        internal static Sqlite Open(string file, bool write)
        {
            var code = sqlite3_open_v2(Utf8(file), out var db, write ? ReadWrite | Create : ReadOnly, IntPtr.Zero);
            var sqlite = new Sqlite(db);
            if (code != Ok)
            {
                var message = sqlite.Error();
                sqlite.Dispose();
                throw new InvalidOperationException(file + ": " + message);
            }
            return sqlite;
        }

        public void Dispose()
        {
            if (_db != IntPtr.Zero) sqlite3_close_v2(_db);
            _db = IntPtr.Zero;
        }

        // One statement with *args* bound to its ? in order.
        internal void Run(string sql, params object[] args)
        {
            using (var statement = Prepare(sql)) statement.Run(args);
        }

        // The rows of one statement, at most *limit* of them; *more* says
        // whether there were others.
        internal List<object[]> Rows(string sql, int limit, out string[] columns, out bool more, params object[] args)
        {
            using (var statement = Prepare(sql))
            {
                statement.Bind(args);
                columns = statement.Columns();
                var rows = new List<object[]>();
                more = false;
                while (statement.Step())
                {
                    if (rows.Count == limit) { more = true; break; }
                    rows.Add(statement.Values());
                }
                return rows;
            }
        }

        internal List<object[]> Rows(string sql, params object[] args) => Rows(sql, int.MaxValue, out _, out _, args);

        // One statement only: what follows it is refused, not left unrun.
        internal Statement Prepare(string sql)
        {
            var text = Utf8(sql);
            var buffer = Marshal.AllocHGlobal(text.Length);
            try
            {
                Marshal.Copy(text, 0, buffer, text.Length);
                if (sqlite3_prepare_v2(_db, buffer, text.Length, out var statement, out var tail) != Ok) throw new InvalidOperationException(Error());
                var rest = text.Length - 1 - (int)(tail.ToInt64() - buffer.ToInt64());
                if (rest > 0 && Encoding.UTF8.GetString(text, text.Length - 1 - rest, rest).Trim().TrimStart(';').Trim().Length > 0)
                {
                    sqlite3_finalize(statement);
                    throw new InvalidOperationException("one statement at a time");
                }
                if (statement == IntPtr.Zero) throw new InvalidOperationException("no statement");
                return new Statement(this, statement);
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        string Error() => FromUtf8(sqlite3_errmsg(_db)) ?? "SQLite error";

        static byte[] Utf8(string text) => Encoding.UTF8.GetBytes(text + "\0");

        static string FromUtf8(IntPtr text)
        {
            if (text == IntPtr.Zero) return null;
            var length = 0;
            while (Marshal.ReadByte(text, length) != 0) length++;
            var bytes = new byte[length];
            Marshal.Copy(text, bytes, 0, length);
            return Encoding.UTF8.GetString(bytes);
        }

        internal sealed class Statement : IDisposable
        {
            readonly Sqlite _owner;
            IntPtr _statement;

            internal Statement(Sqlite owner, IntPtr statement) { _owner = owner; _statement = statement; }

            public void Dispose()
            {
                if (_statement != IntPtr.Zero) sqlite3_finalize(_statement);
                _statement = IntPtr.Zero;
            }

            // Bound to *args*, run to its end, ready to run again.
            internal void Run(params object[] args)
            {
                Bind(args);
                while (Step()) { }
                sqlite3_reset(_statement);
            }

            internal void Bind(object[] args)
            {
                sqlite3_reset(_statement);
                for (var i = 0; i < args.Length; i++)
                {
                    var at = i + 1;
                    var code = args[i] == null ? sqlite3_bind_null(_statement, at)
                        : args[i] is string text ? BindText(at, text)
                        : args[i] is double || args[i] is float ? sqlite3_bind_double(_statement, at, Convert.ToDouble(args[i], CultureInfo.InvariantCulture))
                        : sqlite3_bind_int64(_statement, at, Convert.ToInt64(args[i], CultureInfo.InvariantCulture));
                    if (code != Ok) throw new InvalidOperationException(_owner.Error());
                }
            }

            int BindText(int at, string text)
            {
                var bytes = Encoding.UTF8.GetBytes(text);
                return sqlite3_bind_text(_statement, at, bytes, bytes.Length, Transient);
            }

            internal bool Step()
            {
                var code = sqlite3_step(_statement);
                if (code == Row) return true;
                if (code == Done) return false;
                throw new InvalidOperationException(_owner.Error());
            }

            internal string[] Columns()
            {
                var names = new string[sqlite3_column_count(_statement)];
                for (var i = 0; i < names.Length; i++) names[i] = FromUtf8(sqlite3_column_name(_statement, i));
                return names;
            }

            internal object[] Values()
            {
                var values = new object[sqlite3_column_count(_statement)];
                for (var i = 0; i < values.Length; i++)
                    switch (sqlite3_column_type(_statement, i))
                    {
                        case Integer: values[i] = sqlite3_column_int64(_statement, i); break;
                        case Float: values[i] = sqlite3_column_double(_statement, i); break;
                        case Null: values[i] = null; break;
                        case Text: values[i] = FromUtf8(sqlite3_column_text(_statement, i)); break;
                        default: values[i] = "(" + sqlite3_column_bytes(_statement, i) + " bytes)"; break;
                    }
                return values;
            }
        }

        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_open_v2(byte[] filename, out IntPtr db, int flags, IntPtr vfs);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_close_v2(IntPtr db);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern IntPtr sqlite3_errmsg(IntPtr db);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_prepare_v2(IntPtr db, IntPtr sql, int bytes, out IntPtr statement, out IntPtr tail);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_step(IntPtr statement);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_reset(IntPtr statement);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_finalize(IntPtr statement);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_bind_null(IntPtr statement, int index);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_bind_int64(IntPtr statement, int index, long value);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_bind_double(IntPtr statement, int index, double value);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_bind_text(IntPtr statement, int index, byte[] text, int bytes, IntPtr destructor);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_column_count(IntPtr statement);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern IntPtr sqlite3_column_name(IntPtr statement, int index);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_column_type(IntPtr statement, int index);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern long sqlite3_column_int64(IntPtr statement, int index);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern double sqlite3_column_double(IntPtr statement, int index);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern IntPtr sqlite3_column_text(IntPtr statement, int index);
        [DllImport(Library, CallingConvention = CallingConvention.StdCall)] static extern int sqlite3_column_bytes(IntPtr statement, int index);
    }
}
