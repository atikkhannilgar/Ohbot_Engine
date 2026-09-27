using System.Text.Json;
using System.Text.Json.Serialization;

namespace ObotControl.Core.Models;

// DTOs mirroring src/obot/config.py Config.to_dict(). Property names map to the
// engine's snake_case keys via ObotJson.Options (SnakeCaseLower). Every class keeps a
// [JsonExtensionData] bag so a newer engine schema round-trips through set_config
// without losing unknown fields. Defaults match the Python dataclass defaults.

public sealed class OllamaSshConfig
{
    public string Host { get; set; } = "";
    public int Port { get; set; } = 22;
    public string User { get; set; } = "";
    public string KeyPath { get; set; } = "";
    public string RemoteOllamaHost { get; set; } = "localhost";
    public int RemoteOllamaPort { get; set; } = 11434;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class AudioConfig
{
    public int? InputDeviceIndex { get; set; }
    public string SttEngine { get; set; } = "";
    public string VoskModelPath { get; set; } = "";

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class GeminiTtsConfig
{
    public string Model { get; set; } = "gemini-2.5-flash-preview-tts";
    public string Voice { get; set; } = "Kore";
    public string Style { get; set; } = "";

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class PiperTtsConfig
{
    public string Voice { get; set; } = "en_GB-cori-high";
    public string ModelPath { get; set; } = "";
    public bool AutoDownload { get; set; } = true;
    public bool WarmUp { get; set; } = true;
    public double LengthScale { get; set; } = 1.0;
    public double Volume { get; set; } = 1.0;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class LocalTtsConfig
{
    public string Voice { get; set; } = "zira";
    public int RateWpm { get; set; } = 175;
    public double Volume { get; set; } = 1.0;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class EdgeTtsConfig
{
    public string Voice { get; set; } = "en-GB-SoniaNeural";
    public string Rate { get; set; } = "+0%";
    public string Volume { get; set; } = "+0%";
    public string Pitch { get; set; } = "+0Hz";

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class KokoroTtsConfig
{
    public string Voice { get; set; } = "bf_emma";
    public double Speed { get; set; } = 1.0;
    public string Lang { get; set; } = "en-us";
    public string ModelPath { get; set; } = "";
    public string VoicesPath { get; set; } = "";
    public bool AutoDownload { get; set; } = true;
    public bool WarmUp { get; set; } = true;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class GttsConfig
{
    public string Lang { get; set; } = "en";
    public string Tld { get; set; } = "co.uk";
    public bool Slow { get; set; }

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class TtsConfig
{
    public string Engine { get; set; } = "auto";
    public GeminiTtsConfig Gemini { get; set; } = new();
    public PiperTtsConfig Piper { get; set; } = new();
    public LocalTtsConfig Local { get; set; } = new();
    public EdgeTtsConfig Edge { get; set; } = new();
    public KokoroTtsConfig Kokoro { get; set; } = new();
    public GttsConfig Gtts { get; set; } = new();

    [JsonPropertyName("failure_cooldown_s")]
    public double FailureCooldownS { get; set; } = 90.0;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class MouthConfig
{
    public double Fps { get; set; } = 25.0;
    public double Gate { get; set; } = 0.06;
    public double Gamma { get; set; } = 0.65;
    public double Attack { get; set; } = 0.65;
    public double Release { get; set; } = 0.4;
    public double TopGain { get; set; } = 3.5;
    public double BottomGain { get; set; } = 4.5;
    public double TopMaxDelta { get; set; } = 5.0;
    public double BottomMaxDelta { get; set; } = 5.0;

    [JsonPropertyName("sync_offset_s")]
    public double SyncOffsetS { get; set; }

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

/// <summary>Mirrors AIGestureSettings (speech/config.py): the audio-driven gesture model
/// that drives the servos straight from the speech waveform. Edited by the ML Control page.</summary>
public sealed class GestureConfig
{
    public bool Enabled { get; set; }
    public string CheckpointPath { get; set; } = "";

    [JsonPropertyName("control_hz")]
    public double ControlHz { get; set; } = 20.0;

    public string Device { get; set; } = "cpu";
    public double Intensity { get; set; } = 1.0;

    /// <summary>True = the model drives head/eyes/lids but the lips stay on the scripted
    /// RMS-envelope mouth track (which usually lip-syncs better than the model does).</summary>
    public bool ScriptedMouth { get; set; }

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class SpeechConfig
{
    public TtsConfig Tts { get; set; } = new();
    public MouthConfig Mouth { get; set; } = new();
    public GestureConfig Gesture { get; set; } = new();
    public int? OutputDeviceIndex { get; set; }

    [JsonPropertyName("word_stop_pad_s")]
    public double WordStopPadS { get; set; } = 0.06;

    [JsonPropertyName("estimate_wpm")]
    public double EstimateWpm { get; set; } = 160.0;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class MotionConfig
{
    [JsonPropertyName("tick_s")] public double TickS { get; set; } = 0.05;
    public double RateLimit { get; set; } = 30.0;
    public double LipRateLimit { get; set; } = 200.0;
    public double WriteEpsilon { get; set; } = 0.05;
    public int MoveSpeed { get; set; } = 10;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class ModuleConfig
{
    public bool Enabled { get; set; } = true;

    [JsonPropertyName("min_interval_s")] public double MinIntervalS { get; set; } = 2.0;
    [JsonPropertyName("max_interval_s")] public double MaxIntervalS { get; set; } = 6.0;
    public double Intensity { get; set; } = 1.0;

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class BehaviorsConfig
{
    public ModuleConfig AutoBlink { get; set; } = new();
    public ModuleConfig ListeningNod { get; set; } = new() { MinIntervalS = 2.5, Intensity = 0.6 };
    public ModuleConfig SpeakingSway { get; set; } = new() { MinIntervalS = 1.2, MaxIntervalS = 2.8, Intensity = 0.6 };
    public ModuleConfig IdleWander { get; set; } = new() { MinIntervalS = 3.0, MaxIntervalS = 8.0 };

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }

    public IEnumerable<(string Name, ModuleConfig Module)> Modules()
    {
        yield return ("auto_blink", AutoBlink);
        yield return ("listening_nod", ListeningNod);
        yield return ("speaking_sway", SpeakingSway);
        yield return ("idle_wander", IdleWander);
    }
}

/// <summary>One named checkpoint in the ML model library (config.json's <c>ml.models</c>).
/// Paths are repo-root-relative when the file lives inside the checkout, so a config
/// stays portable  the engine resolves them (see ml/registry.py).</summary>
public sealed class MlModelEntry
{
    public string Name { get; set; } = "";
    public string Path { get; set; } = "";
    public string Notes { get; set; } = "";

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

/// <summary>Mirrors MLSettings (ml/config.py): the gesture-model library the ML Control
/// page manages. The model actually driving speech is picked in <see cref="GestureConfig"/>.</summary>
public sealed class MlConfig
{
    public List<MlModelEntry> Models { get; set; } = new();
    public List<string> ScanDirs { get; set; } = new();
    public string PreviewWav { get; set; } = "mlBehaviour/sample_clip.wav";
    public string DatasetManifest { get; set; } = "";

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class ObotConfig
{
    public string GeminiApiKey { get; set; } = "";
    public OllamaSshConfig OllamaSsh { get; set; } = new();
    public AudioConfig Audio { get; set; } = new();
    public List<string> RecentGeminiModels { get; set; } = new();
    public List<string> RecentOllamaModels { get; set; } = new();
    public string OhbotPort { get; set; } = "COM7";
    public SpeechConfig Speech { get; set; } = new();
    public MotionConfig Motion { get; set; } = new();
    public BehaviorsConfig Behaviors { get; set; } = new();
    public MlConfig Ml { get; set; } = new();

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }

    public ObotConfig Clone() =>
        ObotJson.Deserialize<ObotConfig>(ObotJson.Serialize(this))!;
}
