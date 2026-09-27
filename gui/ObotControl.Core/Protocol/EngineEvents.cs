using System.Text.Json.Serialization;

namespace ObotControl.Core.Protocol;

/// <summary>Canonical event topic names  must match <c>src/obot/core/events.py</c>.</summary>
public static class Topics
{
    public const string State = "state";
    public const string Transcript = "transcript";
    public const string Speech = "speech";
    public const string Action = "action";
    public const string Emotion = "emotion";
    public const string Joints = "joints";
    public const string MicLevel = "miclevel";
    public const string Log = "log";
    public const string Error = "error";
}

/// <summary>Robot conversational state (drives the dashboard indicator).</summary>
public enum BotState { Idle, Listening, Speaking }

public sealed record StateEvent
{
    [JsonPropertyName("state")] public string State { get; init; } = "idle";

    public BotState Parsed => State switch
    {
        "speaking" => BotState.Speaking,
        "listening" => BotState.Listening,
        _ => BotState.Idle,
    };
}

public sealed record TranscriptEvent
{
    [JsonPropertyName("role")] public string Role { get; init; } = "user";
    [JsonPropertyName("text")] public string Text { get; init; } = "";

    /// <summary>True = interim/live text while the user is still speaking; false = final.</summary>
    [JsonPropertyName("partial")] public bool Partial { get; init; }
}

/// <summary>A spoken sentence / cut-off marker plus the active TTS engine when known.</summary>
public sealed record SpeechEvent
{
    [JsonPropertyName("text")] public string? Text { get; init; }

    // "spoken" | "done" | "cutoff" | "interrupted"
    [JsonPropertyName("event")] public string Event { get; init; } = "spoken";
    [JsonPropertyName("engine")] public string? Engine { get; init; }
}

public sealed record ActionEvent
{
    [JsonPropertyName("name")] public string Name { get; init; } = "";
}

public sealed record EmotionEvent
{
    [JsonPropertyName("name")] public string Name { get; init; } = "";
}

public sealed record MicLevelEvent
{
    [JsonPropertyName("level")] public double Level { get; init; }
    [JsonPropertyName("peak")] public double Peak { get; init; }
}

public sealed record LogEvent
{
    [JsonPropertyName("level")] public string Level { get; init; } = "info";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
}

public sealed record ErrorEvent
{
    [JsonPropertyName("where")] public string Where { get; init; } = "";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
}

/// <summary>
/// A joint-position frame (joint name → position 0..10), streamed ~15 Hz for the
/// face preview. Modeled as a dictionary because the server sends the joint set by
/// name (HeadNod, HeadTurn, EyeTurn, LidBlink, TopLip, BottomLip, EyeTilt, HeadTilt).
/// </summary>
public sealed class JointsEvent : Dictionary<string, double>
{
    public double Get(string joint) => TryGetValue(joint, out var v) ? v : 5.0;
}
