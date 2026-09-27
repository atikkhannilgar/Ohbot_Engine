using System.Text.Json;
using ObotControl.Core;
using ObotControl.Core.Models;
using ObotControl.Core.Services;
using Xunit;

namespace ObotControl.Core.Tests;

/// <summary>
/// The config DTOs are the contract the Configuration/Setup pages edit; if a key fails to
/// map to a typed property it silently lands in a [JsonExtensionData] bag and the slider
/// edits the default instead of the real value. These tests load the real
/// <c>config.example.json</c> and assert every key mapped (no leftover Extra) and that the
/// tricky trailing-<c>_s</c> / <c>_wpm</c> keys survive a round-trip.
/// </summary>
public class ConfigSerializationTests
{
    private static string RepoRoot =>
        EngineProcess.LocateRepoRoot()
        ?? throw new InvalidOperationException("could not locate repo root from the test host.");

    private static ObotConfig LoadExample()
    {
        var path = Path.Combine(RepoRoot, "config.example.json");
        return ObotJson.Deserialize<ObotConfig>(File.ReadAllText(path))!;
    }

    [Fact]
    public void Example_DeserializesWithNoUnmappedKeys()
    {
        var cfg = LoadExample();

        // Every section maps 1:1  nothing fell into an extension bag.
        Assert.True(cfg.Extra is null or { Count: 0 });
        Assert.True(cfg.OllamaSsh.Extra is null or { Count: 0 });
        Assert.True(cfg.Audio.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Gemini.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Piper.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Local.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Edge.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Kokoro.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Tts.Gtts.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Mouth.Extra is null or { Count: 0 });
        Assert.True(cfg.Speech.Gesture.Extra is null or { Count: 0 });
        Assert.True(cfg.Motion.Extra is null or { Count: 0 });
        Assert.True(cfg.Behaviors.Extra is null or { Count: 0 });
        Assert.True(cfg.Ml.Extra is null or { Count: 0 });
        foreach (var (_, module) in cfg.Behaviors.Modules())
        {
            Assert.True(module.Extra is null or { Count: 0 });
        }
        foreach (var entry in cfg.Ml.Models)
        {
            Assert.True(entry.Extra is null or { Count: 0 });
        }
    }

    [Fact]
    public void Example_MapsExpectedValues()
    {
        var cfg = LoadExample();

        Assert.Equal("COM7", cfg.OhbotPort);
        Assert.Equal("auto", cfg.Speech.Tts.Engine);
        Assert.Equal("Kore", cfg.Speech.Tts.Gemini.Voice);
        Assert.Equal("en_GB-cori-high", cfg.Speech.Tts.Piper.Voice);
        Assert.Equal(0.06, cfg.Speech.Mouth.Gate, 3);
        Assert.Equal(0.0, cfg.Speech.Mouth.SyncOffsetS, 3);
        Assert.Equal(90.0, cfg.Speech.Tts.FailureCooldownS, 3);
        Assert.Equal(175, cfg.Speech.Tts.Local.RateWpm);
        Assert.Equal(0.05, cfg.Motion.TickS, 3);
        Assert.Equal(200.0, cfg.Motion.LipRateLimit, 3);
        Assert.False(cfg.Behaviors.SpeakingSway.Enabled);
        Assert.Equal(0.6, cfg.Behaviors.SpeakingSway.Intensity, 3);

        // The ML Control page's contract: gesture settings plus the model library.
        Assert.False(cfg.Speech.Gesture.Enabled);
        Assert.Equal("", cfg.Speech.Gesture.CheckpointPath);
        Assert.Equal(20.0, cfg.Speech.Gesture.ControlHz, 3);
        Assert.Equal("cpu", cfg.Speech.Gesture.Device);
        Assert.False(cfg.Speech.Gesture.ScriptedMouth);
        Assert.Equal("", cfg.Ml.PreviewWav);
        Assert.Empty(cfg.Ml.Models);
    }

    [Fact]
    public void RoundTrip_PreservesTrickyKeys()
    {
        var cfg = LoadExample();
        cfg.Speech.Mouth.SyncOffsetS = -0.12;
        cfg.Speech.Tts.FailureCooldownS = 45.5;
        cfg.Motion.TickS = 0.02;
        cfg.Speech.Tts.Local.RateWpm = 190;

        var json = ObotJson.Serialize(cfg);

        // The wire keys must be exactly what the Python engine writes.
        Assert.Contains("\"sync_offset_s\":-0.12", json);
        Assert.Contains("\"failure_cooldown_s\":45.5", json);
        Assert.Contains("\"tick_s\":0.02", json);
        Assert.Contains("\"rate_wpm\":190", json);

        var back = ObotJson.Deserialize<ObotConfig>(json)!;
        Assert.Equal(-0.12, back.Speech.Mouth.SyncOffsetS, 3);
        Assert.Equal(45.5, back.Speech.Tts.FailureCooldownS, 3);
        Assert.Equal(0.02, back.Motion.TickS, 3);
        Assert.Equal(190, back.Speech.Tts.Local.RateWpm);
    }

    [Fact]
    public void RoundTrip_PreservesMlSection()
    {
        var cfg = LoadExample();
        cfg.Speech.Gesture.ScriptedMouth = true;
        cfg.Speech.Gesture.ControlHz = 25.0;
        // Exercise a populated model library without requiring bundled checkpoints.
        cfg.Ml.Models.Add(new MlModelEntry
        {
            Name = "run6", Path = "models/run6.pt", Notes = "baseline",
        });
        cfg.Ml.Models.Add(new MlModelEntry
        {
            Name = "run7", Path = "mlBehaviour/runs/run7/best_model.pt", Notes = "wider GRU",
        });
        cfg.Ml.ScanDirs.Add("D:/checkpoints");
        cfg.Ml.DatasetManifest = "mlBehaviour/ohbot_data/manifest.csv";

        var json = ObotJson.Serialize(cfg);

        // Wire keys the Python engine reads (ml/config.py, speech/config.py).
        Assert.Contains("\"scripted_mouth\":true", json);
        Assert.Contains("\"control_hz\":25", json);
        Assert.Contains("\"scan_dirs\":", json);
        Assert.Contains("\"preview_wav\":", json);
        Assert.Contains("\"dataset_manifest\":", json);

        var back = ObotJson.Deserialize<ObotConfig>(json)!;
        Assert.True(back.Speech.Gesture.ScriptedMouth);
        Assert.Equal(25.0, back.Speech.Gesture.ControlHz, 3);
        Assert.Equal(2, back.Ml.Models.Count);
        Assert.Equal("wider GRU", back.Ml.Models[1].Notes);
        Assert.Equal("D:/checkpoints", Assert.Single(back.Ml.ScanDirs));
    }

    [Fact]
    public void UnknownKeys_SurviveRoundTrip()
    {
        // A future engine adds a key the DTO doesn't know: it must not be dropped.
        const string json = """
        {"gemini_api_key":"","ohbot_port":"COM3","speech":{"mouth":{"gate":0.1,"future_knob":42}}}
        """;
        var cfg = ObotJson.Deserialize<ObotConfig>(json)!;
        var reserialized = ObotJson.Serialize(cfg);
        Assert.Contains("future_knob", reserialized);
        Assert.Equal("COM3", cfg.OhbotPort);
    }

    [Fact]
    public void Clone_IsDeepAndIndependent()
    {
        var cfg = LoadExample();
        var clone = cfg.Clone();
        clone.Speech.Mouth.Gate = 0.99;
        Assert.NotEqual(clone.Speech.Mouth.Gate, cfg.Speech.Mouth.Gate);
    }
}
