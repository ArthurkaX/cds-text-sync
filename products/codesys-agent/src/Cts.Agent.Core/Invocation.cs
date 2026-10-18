// What a reflective call really threw: MethodInfo.Invoke wraps the IDE's own
// exception in a TargetInvocationException, whose message says nothing.
using System;
using System.Reflection;

namespace Cts.Agent
{
    public static class Invocation
    {
        public static Exception Cause(Exception e)
        {
            var invocation = e as TargetInvocationException;
            return invocation != null && invocation.InnerException != null ? invocation.InnerException : e;
        }
    }
}
