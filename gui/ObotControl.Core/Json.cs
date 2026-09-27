using System.Text.Json;
using System.Text.Json.Serialization;

namespace ObotControl.Core;

/// <summary>
/// One <see cref="JsonSerializerOptions"/> shared by the whole client. The Python
/// engine speaks snake_case for both the config (<c>gemini_api_key</c>, <c>input_device_index</c>)
/// and the protocol envelope keys (which are already lowercase), so a single
/// snake_case policy round-trips everything. Unknown fields are preserved on the
/// config DTOs via <c>[JsonExtensionData]</c>, so a newer engine schema is never
/// silently dropped on a set_config round-trip.
/// </summary>
public static class ObotJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        WriteIndented = false,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };

    public static string Serialize<T>(T value) => JsonSerializer.Serialize(value, Options);

    public static T? Deserialize<T>(string json) => JsonSerializer.Deserialize<T>(json, Options);

    public static T? Deserialize<T>(JsonElement element) =>
        element.Deserialize<T>(Options);
}
