using ObotControl.Core.Services;
using Xunit;

namespace ObotControl.Core.Tests;

/// <summary>
/// Covers the "port already in use" detection that lets the shell tell a real engine
/// crash apart from "some other engine already owns this port, we attached to that one
/// instead"  see the traceback this was written for (WinError 10048 on a stray process).
/// </summary>
public class EngineProcessTests
{
    [Theory]
    [InlineData("OSError: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8765): [winerror 10048] only one usage of each socket address...")]
    [InlineData("OSError: [Errno 98] Address already in use")]
    [InlineData("OSError: [Errno 48] Address already in use")]
    public void LooksLikeAddressInUse_MatchesKnownBindFailurePhrasings(string line)
    {
        Assert.True(EngineProcess.LooksLikeAddressInUse(line));
    }

    [Theory]
    [InlineData("Traceback (most recent call last):")]
    [InlineData("ModuleNotFoundError: No module named 'obot'")]
    [InlineData("[serve] control server listening on ws://127.0.0.1:8765")]
    public void LooksLikeAddressInUse_DoesNotMatchUnrelatedLines(string line)
    {
        Assert.False(EngineProcess.LooksLikeAddressInUse(line));
    }
}
