using System.Text.Json;
using System.Text.Json.Serialization;

namespace ObotControl.Core.Protocol;

/// <summary>Wire message type discriminators used by the control server.</summary>
public static class MessageTypes
{
    public const string Call = "call";
    public const string Result = "result";
    public const string Event = "event";
}

/// <summary>A request sent to the engine: <c>{"type":"call","id":1,"method":"...","params":{...}}</c>.</summary>
public sealed class CallMessage
{
    [JsonPropertyName("type")] public string Type => MessageTypes.Call;
    [JsonPropertyName("id")] public int Id { get; set; }
    [JsonPropertyName("method")] public string Method { get; set; } = "";

    // "params" is a C# keyword; the wire key must stay literally "params".
    [JsonPropertyName("params")] public object? Params { get; set; }
}

/// <summary>A reply: <c>{"type":"result","id":1,"ok":true,"data":{...}}</c> or ok:false + error.</summary>
public sealed class ResultMessage
{
    [JsonPropertyName("type")] public string Type { get; set; } = "";
    [JsonPropertyName("id")] public int? Id { get; set; }
    [JsonPropertyName("ok")] public bool Ok { get; set; }
    [JsonPropertyName("data")] public JsonElement Data { get; set; }
    [JsonPropertyName("error")] public string? Error { get; set; }
}

/// <summary>A server-pushed event: <c>{"type":"event","topic":"state|...","data":{...}}</c>.</summary>
public sealed class EventMessage
{
    [JsonPropertyName("type")] public string Type { get; set; } = "";
    [JsonPropertyName("topic")] public string Topic { get; set; } = "";
    [JsonPropertyName("data")] public JsonElement Data { get; set; }
}

/// <summary>Raised to the UI for every server event; deserialize <see cref="Data"/> by <see cref="Topic"/>.</summary>
public sealed record EngineEvent(string Topic, JsonElement Data);
