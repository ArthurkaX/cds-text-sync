// The IDE's own IEC literal converters, for `vars.read` / `vars.write`.
//
//   ILanguageModelManager.GetConverterToIEC(...)   value -> "WORD#5", "TRUE", "'text'"
//   ILanguageModelManager.GetConverterFromIEC()    "16#FF", "T#2s", "REAL#1.5" -> value
//
// A read is shown, and a write is taken, in the spelling the IDE uses itself
// (its watch list, its scripting layer): asking the IDE is not a reproduction of
// its rules, it is the same code.  Both directions need the expression's
// TypeClass (WORD, REAL, STRING, ...), which the watch resolves once.
//
// Everything here runs on the UI thread, inside the vars call that needs it.
using System;
using System.Reflection;

namespace Cts.Agent
{
    sealed class IecLiterals
    {
        const string LanguageModel = "_3S.CoDeSys.Core.LanguageModel.";

        readonly Func<object> _languageModelManager;
        object _toIec;
        MethodInfo _literalText;
        object _fromIec;
        MethodInfo _literalValue;

        public IecLiterals(Func<object> languageModelManager)
        {
            _languageModelManager = languageModelManager;
        }

        // The literal a value reads as ("WORD#5", "REAL#0.5", "'text'").
        public string Text(object value, object typeClass)
        {
            if (_toIec == null)
            {
                var lmmType = Ide.FindType(LanguageModel + "ILanguageModelManager");
                var displayMode = Ide.FindType(LanguageModel + "DisplayMode");
                var get = lmmType.GetMethod("GetConverterToIEC", new[] { typeof(bool), typeof(bool), displayMode });
                if (get == null)
                    throw new ProtocolException(ErrorCodes.Unavailable, "ILanguageModelManager.GetConverterToIEC is not present in this IDE");
                // Full type prefixes ("WORD#5", not "5"), decimal digits: the
                // spelling the IDE's scripting `read_value` prints.
                var converter = get.Invoke(_languageModelManager(),
                    new object[] { false, false, Enum.Parse(displayMode, "Decimal") });
                _literalText = Ide.FindType(LanguageModel + "IConverterToIEC").GetMethod("GetLiteralText",
                    new[] { typeof(object), Ide.FindType(LanguageModel + "TypeClass") });
                _toIec = converter;
            }
            return (string)Call(_literalText, _toIec, new[] { value, typeClass });
        }

        // The value an IEC literal stands for, parsed for the expression's type.
        public object Value(string literal, object typeClass)
        {
            if (_fromIec == null)
            {
                var lmmType = Ide.FindType(LanguageModel + "ILanguageModelManager");
                var get = lmmType.GetMethod("GetConverterFromIEC", Type.EmptyTypes);
                if (get == null)
                    throw new ProtocolException(ErrorCodes.Unavailable, "ILanguageModelManager.GetConverterFromIEC is not present in this IDE");
                var typeClassType = Ide.FindType(LanguageModel + "TypeClass");
                _literalValue = Ide.FindType(LanguageModel + "IConverterFromIEC2").GetMethod("GetLiteralValue",
                    new[] { typeof(string), typeof(object).MakeByRefType(), typeClassType.MakeByRefType(), typeClassType });
                _fromIec = get.Invoke(_languageModelManager(), null);
            }
            var args = new[] { literal, null, null, typeClass };
            Call(_literalValue, _fromIec, args);
            return args[1];
        }

        static object Call(MethodInfo method, object target, object[] args)
        {
            try { return method.Invoke(target, args); }
            catch (TargetInvocationException e) { throw Invocation.Cause(e); }
        }
    }
}
