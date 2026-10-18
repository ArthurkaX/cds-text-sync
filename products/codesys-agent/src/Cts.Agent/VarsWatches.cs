using System;
using System.Globalization;

namespace Cts.Agent
{
    // VarsService's watch resolution: an expression to the IDE's watch, its type and its application.
    internal sealed partial class VarsService
    {
        Watch GetWatch(Guid guid, string expression)
        {
            var key = VarCache.Key(guid.ToString(), expression);
            object cached;
            if (_cache.TryGet(key, out cached)) return (Watch)cached;

            object varRef;
            try { varRef = GetVarReference(guid, expression); }
            catch (Exception e) { throw Unwrap(e, "GetVarReference(" + expression + ")"); }
            if (varRef == null)
                throw new ProtocolException(Vars.Codes.NotExported,
                    "Invalid expression: '" + expression + "' did not resolve to a variable");

            object watchRef;
            try
            {
                var create = DevReflection.ResolveMethod(_ide.OnlineManagerType, false, "CreateWatch",
                    new object[] { varRef });
                watchRef = create.Invoke(_ide.OnlineManager, new object[] { varRef });
            }
            catch (Exception e) { throw Unwrap(e, "CreateWatch(" + expression + ")"); }
            if (watchRef == null)
                throw new ProtocolException(Vars.Codes.NotExported,
                    "Invalid expression: '" + expression + "' has no online watch");

            var watch = new Watch { VarRef = varRef, OnlineVarRef = watchRef };
            ResolveType(watch);
            _cache.GetOrAdd(key, () => watch);
            return watch;
        }

        // The IEC type of the watched expression, once per watch: the var ref's
        // WatchExpression carries the compiled type, whose ToString() is the IEC
        // name ("WORD") and whose Class is the TypeClass.  Best effort -- a read
        // still works without it, only not spelled the IDE's way.
        void ResolveType(Watch watch)
        {
            try
            {
                var varRefIface = Ide.FindType("_3S.CoDeSys.Core.LanguageModel.IVarRef");
                var expression = Ide.Prop(varRefIface, watch.VarRef, "WatchExpression");
                if (expression == null) return;
                var expressionIface = Ide.FindType("_3S.CoDeSys.Core.LanguageModel.IExpression");
                var type = Ide.Prop(expressionIface, expression, "Type");
                if (type == null) return;
                watch.IecType = Convert.ToString(type, CultureInfo.InvariantCulture);
                watch.TypeClass = Ide.Prop(Ide.FindType("_3S.CoDeSys.Core.LanguageModel.IType"), type, "Class");
            }
            catch (Exception e)
            {
                _log.Write("vars: no IEC type for a watch: " + e.Message);
            }
        }

        // The application the call targets: the named/GUID one, or the project's
        // ActiveApplication.  Never logs in -- a read/write only uses a session
        // the user already opened.
        object ResolveApplication(string appSpec, out Guid guid)
        {
            if (string.IsNullOrEmpty(appSpec))
            {
                guid = _ide.ActiveApplication();
            }
            else
            {
                Guid parsed;
                if (Guid.TryParse(appSpec, out parsed)) guid = parsed;
                else guid = ApplicationGuidByName(appSpec);
            }
            if (guid == Guid.Empty) return null;
            try { return _ide.ApplicationOf(guid); }
            catch (Exception e) { throw Unwrap(e, "GetApplication"); }
        }

        Guid ApplicationGuidByName(string name)
        {
            var lmm = LanguageModelManager();
            var method = _languageModelManagerType.GetMethod("GetApplicationGuidByName", new[] { typeof(string) });
            if (method == null) return Guid.Empty;
            try
            {
                var value = method.Invoke(lmm, new object[] { name });
                return value is Guid ? (Guid)value : Guid.Empty;
            }
            catch (Exception e) { throw Unwrap(e, "GetApplicationGuidByName"); }
        }

        object GetVarReference(Guid guid, string expression)
        {
            var lmm = LanguageModelManager();
            var method = _languageModelManagerType.GetMethod("GetVarReference",
                new[] { typeof(Guid), typeof(string) });
            if (method == null)
                throw new ProtocolException(ErrorCodes.Unavailable,
                    "ILanguageModelManager.GetVarReference(Guid, string) is not present in this IDE");
            return method.Invoke(lmm, new object[] { guid, expression });
        }

        object LanguageModelManager()
        {
            if (_languageModelManager != null) return _languageModelManager;
            _languageModelManagerType = Ide.FindType("_3S.CoDeSys.Core.LanguageModel.ILanguageModelManager");
            _languageModelManager = Ide.SystemInstance("_3S.CoDeSys.Core.LanguageModel.ILanguageModelManager");
            return _languageModelManager;
        }

        void WriteVariables(object application, Watch[] watches)
        {
            var method = DevReflection.ResolveMethod(_ide.OnlineApplicationType, false, "WriteVariables",
                new object[] { watches[0].OnlineVarRef });
            var array = Array.CreateInstance(method.GetParameters()[0].ParameterType.GetElementType(), watches.Length);
            for (var i = 0; i < watches.Length; i++) array.SetValue(watches[i].OnlineVarRef, i);
            try { method.Invoke(application, new object[] { array }); }
            catch (Exception e) { throw Unwrap(e, "WriteVariables"); }
        }

        bool IsLoggedIn(object application)
        {
            try { return (bool)Ide.Prop(_ide.OnlineApplicationType, application, "IsLoggedIn"); }
            catch (Exception) { return false; }
        }
    }
}
