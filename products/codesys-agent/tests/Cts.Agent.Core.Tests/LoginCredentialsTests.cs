using System;
using Xunit;

namespace Cts.Agent.Tests
{
    public class LoginCredentialsTests
    {
        public interface IArgs
        {
            int SupportedCredentialTypes { get; }
            object Credentials { get; set; }
            void Cancel(Exception ex);
        }

        public sealed class Args : IArgs
        {
            public int SupportedCredentialTypes { get; set; } = 1;
            public object Credentials { get; set; }
            public Exception Cancelled { get; private set; }
            public void Cancel(Exception ex) { Cancelled = ex; }
        }

        public sealed class UserPassword
        {
            public string Username { get; set; }
            public string Password { get; set; }
        }

        static LoginCredentials Set(string user = "admin", string password = "pw")
        {
            var credentials = new LoginCredentials();
            credentials.Set(typeof(IArgs), typeof(UserPassword), user, password);
            return credentials;
        }

        [Fact]
        public void AnswersWithTheUserNameAndPassword()
        {
            var args = new Args();
            Set().Provide(args);
            var given = Assert.IsType<UserPassword>(args.Credentials);
            Assert.Equal("admin", given.Username);
            Assert.Equal("pw", given.Password);
            Assert.Null(args.Cancelled);
        }

        [Fact]
        public void LeavesAnAskForOtherCredentialKindsAlone()
        {
            var args = new Args { SupportedCredentialTypes = 0 };
            Set().Provide(args);
            Assert.Null(args.Credentials);
            Assert.Null(args.Cancelled);
        }

        [Fact]
        public void CancelsOnceTheDeviceKeepsAsking()
        {
            var credentials = Set();
            for (var i = 0; i < 3; i++)
            {
                var args = new Args();
                credentials.Provide(args);
                Assert.Null(args.Cancelled);
            }
            var refused = new Args();
            credentials.Provide(refused);
            Assert.Null(refused.Credentials);
            Assert.Contains("refused", refused.Cancelled.Message);
        }

        [Fact]
        public void NewCredentialsStartTheCountAgain()
        {
            var credentials = Set();
            for (var i = 0; i < 4; i++) credentials.Provide(new Args());
            credentials.Set(typeof(IArgs), typeof(UserPassword), "other", "pw2");
            var args = new Args();
            credentials.Provide(args);
            Assert.Equal("other", Assert.IsType<UserPassword>(args.Credentials).Username);
        }
    }
}
