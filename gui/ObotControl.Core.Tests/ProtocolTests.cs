using System.Text.Json;
using ObotControl.Core;
using ObotControl.Core.Protocol;
using Xunit;

namespace ObotControl.Core.Tests;

/// <summary>Protocol envelope + event payload round-trips against captured wire shapes.</summary>
public class ProtocolTests
{
    [Fact]
    public void CallMessage_SerializesWireShape()
    {
        var call = new CallMessage { Id = 7, Method = "session_start",
            Params = new { backend = "scripted", controller = "virtual" } };
        var json = ObotJson.Serialize(call);

        Assert.Contains("\"type\":\"call\"", json);
        Assert.Contains("\"id\":7", json);
        Assert.Contains("\"method\":\"session_start\"", json);
        // "params" must survive as the literal wire key despite being a C# keyword.
        Assert.Contains("\"params\":", json);
        Assert.Contains("\"backend\":\"scripted\"", json);
    }

    [Fact]
    public void ResultMessage_ParsesSuccessAndError()
    {
        var ok = ObotJson.Deserialize<ResultMessage>(
            """{"type":"result","id":3,"ok":true,"data":{"session":true}}""")!;
        Assert.True(ok.Ok);
        Assert.Equal(3, ok.Id);
        Assert.True(ok.Data.GetProperty("session").GetBoolean());

        var err = ObotJson.Deserialize<ResultMessage>(
            """{"type":"result","id":4,"ok":false,"error":"no active session"}""")!;
        Assert.False(err.Ok);
        Assert.Equal("no active session", err.Error);
    }

    [Fact]
    public void StateEvent_ParsesAndClassifies()
    {
        var evt = ObotJson.Deserialize<StateEvent>("""{"state":"speaking"}""")!;
        Assert.Equal(BotState.Speaking, evt.Parsed);
        Assert.Equal(BotState.Idle, ObotJson.Deserialize<StateEvent>("""{"state":"idle"}""")!.Parsed);
    }

    [Fact]
    public void SpeechEvent_ParsesSentenceAndEngine()
    {
        var evt = ObotJson.Deserialize<SpeechEvent>(
            """{"text":"Hello there.","event":"spoken","engine":null}""")!;
        Assert.Equal("Hello there.", evt.Text);
        Assert.Equal("spoken", evt.Event);
        Assert.Null(evt.Engine);

        var cut = ObotJson.Deserialize<SpeechEvent>(
            """{"text":null,"event":"cutoff","engine":"piper"}""")!;
        Assert.Equal("cutoff", cut.Event);
        Assert.Equal("piper", cut.Engine);
    }

    [Fact]
    public void JointsEvent_ParsesToNamedPositions()
    {
        var evt = ObotJson.Deserialize<JointsEvent>(
            """{"HeadNod":5.2,"HeadTurn":4.8,"TopLip":6.1,"BottomLip":6.9,"EyeTurn":5.0,"LidBlink":5.0,"EyeTilt":5.0}""")!;
        Assert.Equal(5.2, evt.Get("HeadNod"), 3);
        Assert.Equal(6.1, evt.Get("TopLip"), 3);
        Assert.Equal(5.0, evt.Get("Missing"), 3); // default rest
    }

    [Fact]
    public void MicLevelAndTranscript_Parse()
    {
        var mic = ObotJson.Deserialize<MicLevelEvent>("""{"level":812.5,"peak":1400.0}""")!;
        Assert.Equal(812.5, mic.Level, 3);
        Assert.Equal(1400.0, mic.Peak, 3);

        var t = ObotJson.Deserialize<TranscriptEvent>("""{"role":"user","text":"hello bot"}""")!;
        Assert.Equal("user", t.Role);
        Assert.Equal("hello bot", t.Text);
    }
}
