// `project.credentials {username, password}` (`cts project set-credentials`):
// the user name and password every later login of this IDE session gives a
// device whose runtime has user management, instead of the IDE's login
// dialog.  IOnlineManager4.SetProvideCredentialsHandler takes a callback the
// online manager asks for credentials; it answers UserPasswordCredentials.
// The values live in the agent's memory only -- never in the project or a log
// -- and a new call replaces them.  A device that refuses them asks again:
// after a few asks in a row the callback cancels the login instead of
// looping.  The deny list key is `set_credentials`.
using System.Collections.Generic;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        readonly LoginCredentials _credentials = new LoginCredentials();

        public Dictionary<string, object> SetCredentials(string username, string password)
        {
            if (string.IsNullOrEmpty(username))
                throw new ProtocolException(ErrorCodes.BadParams, "set-credentials needs a username");
            RequireKey(DenyRules.SetCredentials);
            var manager = FindType("_3S.CoDeSys.Core.Online.IOnlineManager4");
            var handlerType = FindType("_3S.CoDeSys.Core.Online.ProvideCredentialsHandler");
            var register = NeedMethod(manager, "SetProvideCredentialsHandler", new[] { handlerType, typeof(bool) },
                "IOnlineManager4.SetProvideCredentialsHandler is not present in this IDE");
            _credentials.Set(FindType("_3S.CoDeSys.Core.Online.IProvideCredentialsArgs"),
                FindType("_3S.CoDeSys.Core.Online.UserPasswordCredentials"), username, password ?? "");
            // Registered on every call: another plugin may have replaced the
            // handler since, which `true` (overwritable) allows.
            register.Invoke(OnlineManager, new object[] { Handler(handlerType, _credentials, "Provide", 1), true });
            return new Dictionary<string, object> { { "username", username }, { "credentials_set", true } };
        }
    }
}
