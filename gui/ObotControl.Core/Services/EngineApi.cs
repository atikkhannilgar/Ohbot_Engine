using ObotControl.Core.Models;

namespace ObotControl.Core.Services;

/// <summary>
/// Typed, discoverable wrappers over <see cref="EngineClient.CallAsync"/> for every RPC
/// method in the protocol. View-models call these instead of stringly-typed method names.
/// </summary>
public sealed class EngineApi
{
    private readonly EngineClient _client;

    public EngineApi(EngineClient client) => _client = client;

    public EngineClient Client => _client;

    public async Task<ObotConfig> GetConfigAsync() =>
        (await _client.CallAsync<ObotConfig>("get_config").ConfigureAwait(false))!;

    public async Task<ObotConfig> SetConfigAsync(ObotConfig config) =>
        (await _client.CallAsync<ObotConfig>("set_config", new { config }).ConfigureAwait(false))!;

    public async Task<List<MicDevice>> ListMicsAsync() =>
        (await _client.CallAsync<MicList>("list_mics").ConfigureAwait(false))!.Mics;

    public async Task<MicTestResult> TestMicAsync(int? index, double durationS = 3.0) =>
        (await _client.CallAsync<MicTestResult>("test_mic",
            new { index, duration_s = durationS },
            timeout: TimeSpan.FromSeconds(durationS + 10)).ConfigureAwait(false))!;

    public async Task<List<string>> ListGeminiModelsAsync(string? apiKey = null) =>
        (await _client.CallAsync<ModelList>("list_gemini_models",
            apiKey is null ? null : new { api_key = apiKey }).ConfigureAwait(false))!.Models;

    public async Task<List<string>> ListOllamaModelsAsync() =>
        (await _client.CallAsync<ModelList>("list_ollama_models",
            timeout: TimeSpan.FromSeconds(30)).ConfigureAwait(false))!.Models;

    public async Task<VoiceList> ListTtsVoicesAsync() =>
        (await _client.CallAsync<VoiceList>("list_tts_voices").ConfigureAwait(false))!;

    public async Task<string> SpeakTestAsync(string engine, string voice, string text) =>
        (await _client.CallAsync<SpeakTestResult>("speak_test",
            new { engine, voice, text },
            timeout: TimeSpan.FromSeconds(60)).ConfigureAwait(false))!.Engine;

    public async Task<SessionState> StartSessionAsync(string backend, string model, string controller) =>
        (await _client.CallAsync<SessionState>("session_start",
            new { backend, model, controller },
            timeout: TimeSpan.FromSeconds(60)).ConfigureAwait(false))!;

    public async Task<SessionState> StopSessionAsync() =>
        (await _client.CallAsync<SessionState>("session_stop").ConfigureAwait(false))!;

    public Task SendTextAsync(string text) => _client.CallAsync("send_text", new { text });

    public Task InterruptAsync() => _client.CallAsync("interrupt");

    public Task SetMicModeAsync(string mode) => _client.CallAsync("set_mic_mode", new { mode });

    public Task TriggerPttAsync() => _client.CallAsync("trigger_ptt");

    /// <summary>Hold one joint (by name, e.g. "HeadNod") at an absolute position (0..10).</summary>
    public Task SetJointAsync(string joint, double position) =>
        _client.CallAsync("set_joint", new { joint, position });

    /// <summary>Release a single manually-held joint back to ambient/automatic control.</summary>
    public Task ReleaseJointAsync(string joint) => _client.CallAsync("release_joint", new { joint });

    /// <summary>Release every manually-held joint at once.</summary>
    public Task ReleaseAllJointsAsync() => _client.CallAsync("release_all_joints");

    /// <summary>Names of every emotion with a default pose (e.g. "Happy", "Sad"), Neutral first.</summary>
    public async Task<List<string>> ListEmotionsAsync() =>
        (await _client.CallAsync<EmotionList>("list_emotions").ConfigureAwait(false))!.Emotions;

    /// <summary>Apply an emotion's default mouth/eyes/nod pose  the same path the LLM's
    /// (Emotion) markers use. Persists until the next call. Needs an active session.</summary>
    public Task SetEmotionAsync(string emotion) => _client.CallAsync("set_emotion", new { emotion });

    // -- ML gesture model ---------------------------------------------------------------
    //
    // The model library itself (config.json's "ml" section) is edited like any other
    // config section, through Get/SetConfigAsync. These calls cover what only the engine
    // host can answer  its filesystem, its checkpoints, its torch install  plus driving
    // a live session.

    /// <summary>Registered + auto-discovered gesture-model checkpoints on the engine host.</summary>
    public async Task<MlModelList> ListMlModelsAsync() =>
        (await _client.CallAsync<MlModelList>("list_ml_models",
            timeout: TimeSpan.FromSeconds(30)).ConfigureAwait(false))!;

    /// <summary>Open a checkpoint and report its shape/training metadata. Needs torch on
    /// the engine host, and pays its import on the first call  hence the long timeout.</summary>
    public async Task<MlCheckpointInfo> InspectMlModelAsync(string path) =>
        (await _client.CallAsync<MlCheckpointInfo>("inspect_ml_model", new { path },
            timeout: TimeSpan.FromSeconds(120)).ConfigureAwait(false))!;

    /// <summary>Runtime + live-session state of the gesture model. <paramref name="probe"/>
    /// imports torch on the host to answer the CUDA question; without it CudaAvailable is
    /// null ("not asked") and the call is cheap.</summary>
    public async Task<MlStatus> GetMlStatusAsync(bool probe = false) =>
        (await _client.CallAsync<MlStatus>("ml_status", new { probe },
            timeout: TimeSpan.FromSeconds(probe ? 120 : 30)).ConfigureAwait(false))!;

    /// <summary>Load the configured checkpoint into the running session (no restart).
    /// <paramref name="force"/> reloads the same path again  use it after re-training.</summary>
    public async Task<MlStatus> ReloadMlModelAsync(bool force = false) =>
        (await _client.CallAsync<MlStatus>("ml_reload_model", new { force },
            timeout: TimeSpan.FromSeconds(180)).ConfigureAwait(false))!;

    /// <summary>Play one audio file through a checkpoint on the running session's robot.
    /// Returns when playback ends (or StopMlPreviewAsync cuts it short), so the timeout
    /// has to cover a whole clip plus the model load.</summary>
    public async Task<MlPreviewResult> MlPreviewAsync(
        string checkpoint, string wav, double controlHz, double intensity, string device) =>
        (await _client.CallAsync<MlPreviewResult>("ml_preview",
            new { checkpoint, wav, control_hz = controlHz, intensity, device },
            timeout: TimeSpan.FromMinutes(10)).ConfigureAwait(false))!;

    /// <summary>Replay one recorded dataset clip (ground truth, not a prediction).</summary>
    public async Task<MlPreviewResult> MlReplayClipAsync(string path, double speed, bool playAudio) =>
        (await _client.CallAsync<MlPreviewResult>("ml_replay_clip",
            new { path, speed, play_audio = playAudio },
            timeout: TimeSpan.FromMinutes(10)).ConfigureAwait(false))!;

    /// <summary>Cut a running preview/replay short. Handled concurrently with the
    /// still-pending preview call, which then returns with Stopped = true.</summary>
    public Task StopMlPreviewAsync() => _client.CallAsync("ml_preview_stop");

    /// <summary>Clips of a converted BEAT2 dataset (beat2_to_ohbot.py's manifest.csv).</summary>
    public async Task<MlClipList> ListMlClipsAsync(string? manifest = null) =>
        (await _client.CallAsync<MlClipList>("list_ml_clips",
            manifest is null ? null : new { manifest },
            timeout: TimeSpan.FromSeconds(30)).ConfigureAwait(false))!;

    public async Task<SessionState> GetStateAsync() =>
        (await _client.CallAsync<SessionState>("get_state").ConfigureAwait(false))!;
}
