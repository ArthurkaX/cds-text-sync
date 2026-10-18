// The answer to the IDE's credentials callback (`project.credentials`): the
// user name and password set last, as the IDE's UserPasswordCredentials, and
// a cancel once a device keeps asking -- it refuses them, and answering again
// would loop.  The IDE types come in as arguments, so the logic is tested
// against stand-ins.
using System;
using System.Collections.Generic;
using System.Diagnostics;

namespace Cts.Agent
{
    public sealed class LoginCredentials
    {
        //: More asks than this within AskWindowMs: the device refuses them.
        const int MaxAsks = 3;
        const int AskWindowMs = 10000;

        //: CredentialsType.UserPassword, a flag of SupportedCredentialTypes.
        const int UserPassword = 1;

        readonly object _lock = new object();
        readonly Queue<long> _asks = new Queue<long>();
        readonly Stopwatch _clock = Stopwatch.StartNew();
        Type _argsIface, _credentialsType;
        string _username, _password;

        public void Set(Type argsIface, Type credentialsType, string username, string password)
        {
            lock (_lock)
            {
                _argsIface = argsIface;
                _credentialsType = credentialsType;
                _username = username;
                _password = password;
                _asks.Clear();
            }
        }

        public void Provide(object args)
        {
            Type argsIface, credentialsType;
            string username, password;
            bool refused;
            lock (_lock)
            {
                argsIface = _argsIface;
                credentialsType = _credentialsType;
                username = _username;
                password = _password;
                var now = _clock.ElapsedMilliseconds;
                _asks.Enqueue(now);
                while (_asks.Count > 0 && now - _asks.Peek() > AskWindowMs) _asks.Dequeue();
                refused = _asks.Count > MaxAsks;
            }
            if ((Convert.ToInt32(argsIface.GetProperty("SupportedCredentialTypes").GetValue(args, null)) & UserPassword) == 0) return;
            try
            {
                if (refused)
                    throw new InvalidOperationException("the device refused the user name and password from cts project set-credentials");
                var credentials = Activator.CreateInstance(credentialsType);
                credentialsType.GetProperty("Username").SetValue(credentials, username, null);
                credentialsType.GetProperty("Password").SetValue(credentials, password, null);
                argsIface.GetProperty("Credentials").SetValue(args, credentials, null);
            }
            catch (Exception e)
            {
                argsIface.GetMethod("Cancel").Invoke(args, new object[] { Invocation.Cause(e) });
            }
        }
    }
}
