using System.Text.Json;
using System.Text.Json.Serialization;

namespace ObotControl.Core.Services;

/// <summary>GUI-local preferences  currently just which Python interpreter to launch the
/// engine with. Separate from <c>config.json</c>, which the engine owns and which requires
/// a live connection to write; this has to work before any connection exists.</summary>
public sealed class GuiSettings
{
    public string? SelectedPythonPath { get; set; }

    // Last-used Dashboard session selections, restored on the next launch.
    public string? DashboardBackend { get; set; }
    public string? DashboardController { get; set; }
    public string? DashboardGeminiModel { get; set; }
    public string? DashboardOllamaModel { get; set; }
}

public sealed class GuiSettingsStore
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private static readonly string FilePath = Path.Combine(
        Environment.GetEnvironmentVariable("OBOT_SETTINGS_DIR")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ObotControl"),
        "settings.json");

    public GuiSettings Load()
    {
        try
        {
            if (!File.Exists(FilePath)) return new GuiSettings();
            return JsonSerializer.Deserialize<GuiSettings>(File.ReadAllText(FilePath), Options) ?? new GuiSettings();
        }
        catch
        {
            return new GuiSettings();
        }
    }

    public void Save(GuiSettings settings)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
        File.WriteAllText(FilePath, JsonSerializer.Serialize(settings, Options));
    }
}
