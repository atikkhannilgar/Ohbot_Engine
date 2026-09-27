using System.Text.Json.Serialization;

namespace ObotControl.Core.Models;

public sealed record MicDevice
{
    public int Index { get; init; }
    public string Name { get; init; } = "";
    public override string ToString() => Name;
}

public sealed record MicList
{
    public List<MicDevice> Mics { get; init; } = new();
}

public sealed record VoiceList
{
    public List<string> Gemini { get; init; } = new();
    public List<string> Piper { get; init; } = new();
    public List<string> Local { get; init; } = new();
    public List<string> Edge { get; init; } = new();
    public List<string> Kokoro { get; init; } = new();
    public List<string> Gtts { get; init; } = new();
}

public sealed record ModelList
{
    public List<string> Models { get; init; } = new();
}

public sealed record EmotionList
{
    public List<string> Emotions { get; init; } = new();
}

public sealed record SpeakTestResult
{
    public string Engine { get; init; } = "";
}

public sealed record MicTestResult
{
    public double Peak { get; init; }
    public bool Ok { get; init; }
}

/// <summary>One row of the engine's gesture-model library (ml/registry.py describe()).</summary>
public sealed record MlModelInfo
{
    public string Name { get; init; } = "";

    /// <summary>Repo-relative path when the checkpoint is inside the checkout; this is the
    /// value written back into config.json.</summary>
    public string Path { get; init; } = "";

    [JsonPropertyName("abs_path")] public string AbsPath { get; init; } = "";
    public string Notes { get; init; } = "";

    /// <summary>"registry" = a named entry in config.json, "discovered" = found by the
    /// checkpoint scan, "configured" = in use but neither registered nor discoverable.</summary>
    public string Source { get; init; } = "discovered";

    public bool Exists { get; init; }
    [JsonPropertyName("size_bytes")] public long SizeBytes { get; init; }

    /// <summary>Last-modified time, ISO-8601 UTC; null when the file is missing.</summary>
    public string? Modified { get; init; }

    /// <summary>True for the checkpoint <c>speech.gesture.checkpoint_path</c> points at.</summary>
    public bool Selected { get; init; }
}

public sealed record MlModelList
{
    public List<MlModelInfo> Models { get; init; } = new();
    [JsonPropertyName("selected_path")] public string SelectedPath { get; init; } = "";
    [JsonPropertyName("scan_dirs")] public List<string> ScanDirs { get; init; } = new();
    [JsonPropertyName("default_scan_dirs")] public List<string> DefaultScanDirs { get; init; } = new();
}

/// <summary>What a train.py checkpoint contains (ml/registry.py inspect_checkpoint()).</summary>
public sealed record MlCheckpointInfo
{
    public string Path { get; init; } = "";
    [JsonPropertyName("run_name")] public string RunName { get; init; } = "";

    /// <summary>Output axes the model drives: 8 normally, 7 when the training data was
    /// converted with --exclude-head-tilt.</summary>
    [JsonPropertyName("n_axes")] public int NAxes { get; init; }
    [JsonPropertyName("axis_names")] public List<string> AxisNames { get; init; } = new();

    [JsonPropertyName("n_mels")] public int NMels { get; init; }
    public int ConvChannels { get; init; }
    public int GruHidden { get; init; }
    public long Parameters { get; init; }

    /// <summary>Epoch reached; null for a best_model.pt (which carries no epoch counter).</summary>
    public int? Epoch { get; init; }
    [JsonPropertyName("epochs_planned")] public int? EpochsPlanned { get; init; }
    [JsonPropertyName("best_val")] public double? BestVal { get; init; }
    [JsonPropertyName("learning_rate")] public double? LearningRate { get; init; }
    public int? BatchSize { get; init; }
    public string DataDir { get; init; } = "";
    [JsonPropertyName("size_bytes")] public long SizeBytes { get; init; }
    [JsonPropertyName("has_optimizer_state")] public bool HasOptimizerState { get; init; }
}

/// <summary>One thing the gesture model needs on the engine host: a pip-installable module,
/// or a file of the training pipeline that inference is loaded from.</summary>
public sealed record MlRequirementItem
{
    public string Name { get; init; } = "";

    /// <summary>"module" (pip can install it) or "file" (part of the checkout).</summary>
    public string Kind { get; init; } = "module";

    /// <summary>Why the gesture model needs it, in one phrase.</summary>
    public string Purpose { get; init; } = "";

    public bool Available { get; init; }

    /// <summary>Installed version for a present module, or why a missing item is missing.</summary>
    public string Detail { get; init; } = "";
}

/// <summary>Whether the engine host can run a gesture model at all, item by item
/// (ml/registry.py requirements_status()). Drives the ML Control page's install card.</summary>
public sealed record MlRequirements
{
    public bool Ready { get; init; }
    public List<string> Missing { get; init; } = new();

    /// <summary>The missing items pip could fix  a missing mlBehaviour/ file cannot be
    /// installed, so it is reported but excluded here.</summary>
    public List<string> Installable { get; init; } = new();

    [JsonPropertyName("requirements_file")] public string RequirementsFile { get; init; } = "requirements/ml.txt";
    [JsonPropertyName("requirements_exists")] public bool RequirementsExists { get; init; }

    /// <summary>The engine's own interpreter (<c>sys.executable</c>). Installing into this
    /// is what guarantees the packages land where the engine will look for them.</summary>
    public string Python { get; init; } = "";

    [JsonPropertyName("python_version")] public string PythonVersion { get; init; } = "";

    public List<MlRequirementItem> Items { get; init; } = new();
}

/// <summary>Inference runtime + live-session view of the gesture model (ml_status).</summary>
public sealed record MlStatus
{
    [JsonPropertyName("torch_available")] public bool TorchAvailable { get; init; }
    [JsonPropertyName("torch_version")] public string? TorchVersion { get; init; }

    /// <summary>Null until someone probes: answering it costs a torch import on the host.</summary>
    [JsonPropertyName("cuda_available")] public bool? CudaAvailable { get; init; }
    [JsonPropertyName("cuda_devices")] public List<string> CudaDevices { get; init; } = new();
    public bool Probed { get; init; }

    public bool Enabled { get; init; }
    [JsonPropertyName("checkpoint_path")] public string CheckpointPath { get; init; } = "";
    [JsonPropertyName("checkpoint_exists")] public bool CheckpointExists { get; init; }
    [JsonPropertyName("control_hz")] public double ControlHz { get; init; } = 20.0;
    public double Intensity { get; init; } = 1.0;
    public string Device { get; init; } = "cpu";
    [JsonPropertyName("scripted_mouth")] public bool ScriptedMouth { get; init; }

    public bool Session { get; init; }
    public string? Controller { get; init; }

    /// <summary>False for a console session: no servos, so a preview is audio-only.</summary>
    [JsonPropertyName("pose_capable")] public bool PoseCapable { get; init; }

    [JsonPropertyName("gesture_loaded")] public bool GestureLoaded { get; init; }

    /// <summary>Checkpoint the running session actually holds in memory  it lags
    /// <see cref="CheckpointPath"/> until the model is reloaded.</summary>
    [JsonPropertyName("loaded_checkpoint")] public string? LoadedCheckpoint { get; init; }

    [JsonPropertyName("preview_active")] public bool PreviewActive { get; init; }
    [JsonPropertyName("preview_playing")] public string PreviewPlaying { get; init; } = "";

    /// <summary>Per-dependency report for the install card.</summary>
    public MlRequirements Requirements { get; init; } = new();
}

/// <summary>One recorded training clip from a converted BEAT2 dataset.</summary>
public sealed record MlClipInfo
{
    [JsonPropertyName("clip_id")] public string ClipId { get; init; } = "";
    public string Path { get; init; } = "";
    public bool Exists { get; init; }
    [JsonPropertyName("n_frames")] public int NFrames { get; init; }
    [JsonPropertyName("duration_s")] public double DurationS { get; init; }

    public override string ToString() => ClipId;
}

public sealed record MlClipList
{
    public string Manifest { get; init; } = "";
    public bool Exists { get; init; }
    public List<MlClipInfo> Clips { get; init; } = new();
}

/// <summary>Outcome of a finished ml_preview / ml_replay_clip playback.</summary>
public sealed record MlPreviewResult
{
    public string? Checkpoint { get; init; }
    public string? Wav { get; init; }
    public string? Clip { get; init; }

    /// <summary>Frames in the clip that was played (not necessarily the number of pose
    /// updates sent: playback follows wall-clock position, so it may skip frames).</summary>
    public int? Frames { get; init; }
    [JsonPropertyName("control_hz")] public double? ControlHz { get; init; }
    [JsonPropertyName("elapsed_s")] public double ElapsedS { get; init; }

    /// <summary>True when playback was cut short by Stop rather than reaching the end.</summary>
    public bool Stopped { get; init; }

    [JsonPropertyName("pose_capable")] public bool PoseCapable { get; init; }
}

/// <summary>Mirror of the engine's get_state / session_start payload.</summary>
public sealed record SessionState
{
    public bool Session { get; init; }
    public string? Backend { get; init; }
    public string? Model { get; init; }
    public string? Controller { get; init; }
    public string State { get; init; } = "idle";
    public string Emotion { get; init; } = "Neutral";

    [JsonPropertyName("mic_mode")] public string MicMode { get; init; } = "muted";
    [JsonPropertyName("mic_available")] public bool MicAvailable { get; init; }
    [JsonPropertyName("tts_engine_active")] public string? TtsEngineActive { get; init; }
}
