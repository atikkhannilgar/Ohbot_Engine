namespace ObotControl.Core;

/// <summary>
/// Centralized help strings, so the hover tooltips and the Help overlay always say the
/// same thing. Referenced from XAML via <c>{x:Static core:HelpText.Xxx}</c>.
/// </summary>
public static class HelpText
{
    // -- engine / connection bar -------------------------------------------------------
    public const string LaunchEngine =
        "Start the Python engine (python -m obot --serve) as a child process from the repo " +
        "root and connect to it. Use this if the engine isn't already running.";
    public const string Attach =
        "Connect to an engine you started yourself (or one on another machine). Set Host/Port first.";
    public const string Disconnect =
        "Disconnect from the engine and stop the engine process if this app launched it.";
    public const string Host = "Address of the control server. 127.0.0.1 for an engine on this machine.";
    public const string Port = "TCP port of the control server (default 8765).";
    public const string LaunchController =
        "Default robot target when launching the engine: 'virtual' = full motion + audio, no " +
        "window (this app draws the face); 'sim' = the engine's own face window; 'console' = no motion/audio.";
    public const string Help = "Show a guide to every page and control.";

    // -- dashboard ---------------------------------------------------------------------
    public const string Backend =
        "Where replies come from: 'scripted' echoes what you type (no key/network needed), " +
        "'gemini' uses Google's API, 'ollama' a remote Ollama over SSH.";
    public const string Model = "Which model of the selected backend to use. Click ↻ to fetch the live list.";
    public const string RefreshModels = "Fetch the available models for the selected backend.";
    public const string Controller =
        "What the session drives: 'virtual' (headless motion + audio), 'sim' (engine face window), " +
        "'console' (prints only), or 'hardware' (real servos over the serial port).";
    public const string StartSession = "Start a conversation session with the chosen backend/model/controller.";
    public const string StopSession = "End the current session.";
    public const string SwitchSession = "Restart the session to apply a new backend or model without a manual stop/start.";
    public const string MicMode =
        "Microphone: 'muted' ignores it, 'vad' listens continuously (just talk  it also " +
        "interrupts the bot), 'ptt' (push-to-talk) stays parked until you click Talk or press " +
        "the hotkey, then captures one phrase.";
    public const string PttTalk =
        "Capture one phrase now. Speak after clicking; it records until you pause. Also bound to " +
        "the hotkey shown below (works while the window is focused).";
    public const string PttHotkey =
        "Set the push-to-talk key: click Set…, then press the key you want (e.g. Space). Press it " +
        "any time (window focused) to talk. Typing in the message box is never intercepted.";
    public const string Send = "Send the typed message as one conversation turn.";
    public const string Interrupt =
        "Cut the robot off at the next word boundary  same as talking over it or pressing SPACE in the console.";
    public const string StateIndicator = "What the robot is doing right now: idle, listening, or speaking.";
    public const string ActiveEngine = "Which TTS voice actually produced the last speech (gemini / piper / local).";
    public const string FacePreview =
        "Live mirror of the robot's face  head pose, eyes, blinks and lips  from the engine's joint stream.";

    // -- setup -------------------------------------------------------------------------
    public const string PythonSetupIntro =
        "Guarantees a working Python 3.12 environment before you launch the engine  no " +
        "terminal needed. Prefers an existing venv (or a system Python 3.12) already on " +
        "this machine; 'Set up automatically' downloads a private Python and builds one " +
        "for you if nothing usable is found.";
    public const string PythonCandidatePick =
        "Every venv found under the repo root, any system Python 3.12 found, and 'Set up " +
        "automatically' as a fallback. Picking one prepares it (installs the project's " +
        "dependencies) if it isn't ready yet, and is remembered for next time.";
    public const string PythonRefresh = "Re-scan for venvs/system Pythons (e.g. after creating one outside the GUI).";
    public const string PythonPrepare =
        "Install/update the project's dependencies into the selected environment. Also " +
        "how you re-run setup after requirements.txt changes.";
    public const string RefreshDevices = "Re-query the engine host for microphones and installed TTS voices.";
    public const string ComPort =
        "Serial port the physical OhBot is on (e.g. COM7 on Windows, /dev/ttyACM0 on Linux). Only used by " +
        "the 'hardware' controller. On Linux your user must be in the 'dialout' group to open it " +
        "(sudo usermod -aG dialout $USER, then log out and back in).";
    public const string ApiKey = "Google AI Studio key for the Gemini backend and Gemini TTS. Stored in config.json on the engine.";
    public const string SshFields = "Connection details for a remote machine running Ollama, reached over an SSH tunnel.";
    public const string MicPick =
        "Leave on System default to use the OS input device, or pick a specific microphone. " +
        "Use Test to confirm it works.";
    public const string TestMic = "Record ~3 seconds from the selected mic; the bar shows the live level.";
    public const string SttEngine = "Speech-to-text: 'google' (online, accurate) or 'vosk' (offline, needs a model folder).";
    public const string VoskModel = "Folder of an unzipped Vosk model (contains am/, conf/, graph/). Only needed for offline STT.";
    public const string VoskAutoSetup =
        "Download the selected Vosk model from alphacephei.com and unzip it into ohbotData/vosk/, " +
        "then fill in the STT engine and model path above automatically  no manual download needed.";
    public const string TtsEngine =
        "Which voice to speak with. 'auto' chains the best available (edge → kokoro → piper → " +
        "local), falling through on failure. Or pin one: edge (online, best), kokoro (offline, " +
        "best local), gtts/gemini (online), piper (offline), local (robotic last resort).";
    public const string TestVoice = "Speak the test sentence with this engine/voice on the engine host so you can hear it.";
    public const string Save = "Write these settings to config.json on the engine (the same file the terminal app reads).";
    public const string Reload = "Discard edits and reload the settings currently saved on the engine.";

    // -- manual control ------------------------------------------------------------------
    public const string EmotionsPanel =
        "Trigger an emotion's default pose directly  the same mouth/eyes/nod bias the LLM's " +
        "(Emotion) tags apply. It persists (ambient behaviors and speech still layer on top) " +
        "until you pick another; 'Neutral' clears it back to plain rest. Needs a running session.";
    public const string EnableManualControl =
        "Freeze every motor at its current pose and hand the sliders control. Ambient " +
        "behaviors/speech no longer move a joint once you drag its slider. Needs a running session.";
    public const string ReleaseManualControl =
        "Hand every motor back to automatic control (ambient behaviors, lip-sync, actions).";
    public const string CenterAllJoints = "Send every slider back to 5 (rest/neutral) while manual control is active.";
    public const string ManualControlPanel =
        "One row per motor: 'now' is the live position reported by the engine, the slider is " +
        "the position you're commanding, and Center resets that one motor to rest.";

    // -- configuration -----------------------------------------------------------------
    public const string MouthTuning =
        "Lip-sync tuning. These apply LIVE while the robot talks (saved after ~¼ s) so you can dial it in by ear.";
    public const string Motion = "Servo mixer: how fast joints move and how often positions are written.";
    public const string Behaviors =
        "Ambient life: blinking, attentive nods while you talk, sway while speaking, idle eye wander. " +
        "Toggle each and set how often / how strongly it fires.";
    public const string DirtyFlag = "You have unsaved changes on this page.";

    // -- ML control --------------------------------------------------------------------
    public const string MlIntro =
        "The AI gesture model: a BEAT2-trained network that drives head, eyes, lids and lips " +
        "straight from the speech waveform, instead of the scripted loudness-envelope mouth " +
        "track. Off by default  it needs torch installed on the engine host and a trained " +
        "checkpoint. Everything here writes config.json's speech.gesture / ml sections.";
    public const string MlEnabled =
        "Use the gesture model for speech instead of the scripted mouth track. The model is " +
        "loaded when a session starts, or immediately with 'Apply to session' below. If loading " +
        "or prediction ever fails, the engine falls back to the scripted track rather than going quiet.";
    public const string MlLibrary =
        "Every checkpoint the engine host can see: the ones named in config.json plus everything " +
        "found under mlBehaviour/runs/ and src/obot/ml/models/. 'Use' makes one drive speech, " +
        "'Inspect' opens it and reports axes/hyperparameters/training progress, and 'Keep' stores " +
        "a discovered checkpoint in config.json under a name you choose.";
    public const string MlAddModel =
        "Register a checkpoint by path  a train.py .pt file (best_model.pt or checkpoint.pt). " +
        "Paths inside the repo are stored repo-relative so the config stays portable; anything " +
        "else is stored absolute. The path is resolved on the engine host, which may not be this machine.";
    public const string MlInspect =
        "Open the checkpoint on the engine host and report what it contains: how many Ohbot axes " +
        "it drives, its mel/conv/GRU sizes, parameter count, epoch reached and best validation loss. " +
        "Needs torch installed there; the first call pays torch's import.";
    public const string MlDevice =
        "torch device for inference: 'cpu' works everywhere (this model is small enough for it), " +
        "'cuda' needs an NVIDIA GPU on the engine host  use Check runtime to confirm before selecting it.";
    public const string MlControlHz =
        "Pose predictions per second. This must match the --control-hz the checkpoint was trained " +
        "with (beat2_to_ohbot.py's conversion rate, normally 20) or the motion comes out time-warped.";
    public const string MlIntensity =
        "Scales predicted movement around the rest position: 1.0 is the model's raw output, above " +
        "that exaggerates the gestures, below that dampens them. Applies live while the robot talks.";
    public const string MlScriptedMouth =
        "Let the model drive head/eyes/lids but keep the lips on the scripted loudness-envelope " +
        "track, which usually lip-syncs better than an early-stage model does.";
    public const string MlRequirements =
        "What the gesture model needs on the engine host, item by item: the pip packages the " +
        "inference path imports (torch, numpy, scipy, soundfile) and the mlBehaviour/ training " +
        "files that inference is loaded from. The base setup leaves these out on purpose  torch " +
        "is a few hundred MB and the chat pipeline never needs it.";
    public const string MlInstall =
        "Runs 'pip install -r requirements/ml.txt' into the interpreter the engine itself is " +
        "running on (shown above), streaming pip's output to the Logs tab. Expect a few hundred " +
        "MB and several minutes. The engine imports torch lazily, so a running session picks the " +
        "new packages up without a restart  no need to disconnect first. Only available when the " +
        "engine is on this machine.";
    public const string MlRuntime =
        "Whether torch is installed on the engine host and which version. 'Check runtime' additionally " +
        "imports it there to report whether CUDA is usable  that costs a few seconds, so it is not automatic.";
    public const string MlLoaded =
        "Which checkpoint the running session actually holds in memory. It can lag the configured " +
        "one between a Save and an Apply, and stays empty until a session starts.";
    public const string MlApply =
        "Load the configured checkpoint into the running session without restarting the conversation. " +
        "Use it after re-training into the same path too  it reloads either way.";
    public const string MlPreview =
        "Play an audio file through the selected checkpoint on the running robot, so you can watch " +
        "the predicted motion before trusting it in a conversation. Needs an active session; on a " +
        "console session you only get the audio, since it has no servos.";
    public const string MlReplay =
        "Replay one clip of a converted BEAT2 dataset exactly as recorded  ground truth, not a " +
        "prediction. Watching this next to a preview is how you tell a weak model apart from a bad " +
        "data conversion. Needs a dataset built by beat2_to_ohbot.py on the engine host.";

    // -- pages (overview, used by the Help overlay) ------------------------------------
    public const string PageDashboard =
        "Run a conversation: choose the backend/model/controller, Start, then type or talk. " +
        "Watch the transcript, hit the big Interrupt button, switch the mic mode, and see the live state and face.";
    public const string PageSetup =
        "First-run setup: step 0 guarantees a working Python environment (no terminal needed) " +
        "before Launch engine works, then API key, serial port, remote-Ollama SSH, microphone " +
        "(with a level test), speech-to-text engine, and TTS voices with per-engine Test buttons. " +
        "Save writes config.json.";
    public const string PageConfiguration =
        "Fine-tuning: TTS engine + per-engine voice settings, mouth-tuning sliders that apply live while " +
        "talking, servo motion limits, and the ambient behavior modules. Save/Revert with a dirty indicator.";
    public const string PageManualControl =
        "Jog each motor directly and watch its live position  for testing/calibrating servos outside " +
        "a conversation. Enable to freeze every joint where it is, drag sliders to move one, Release to " +
        "hand control back to ambient behaviors and speech. The Emotions row above triggers a default " +
        "mouth/eyes/nod pose directly, the same one the LLM's (Emotion) tags apply. Needs a running session.";
    public const string PageMlControl =
        "The AI gesture model: pick which trained checkpoint drives head/eyes/lids/lips from the " +
        "speech waveform, register new ones by path, and inspect what a checkpoint contains. Tune " +
        "device, control rate and intensity (intensity applies live), preview a checkpoint on the " +
        "live robot with any audio file, and replay recorded training clips as ground truth to " +
        "compare against. Save also loads the model into a running session  no restart.";
    public const string PageLogs =
        "Everything the engine prints plus structured log/error events, with Info/Warning/Error filters.";
    public const string Intro =
        "OhBot Control talks to the Python engine over a local WebSocket  all the intelligence stays in " +
        "Python; this app is a thin client. Start by clicking Launch engine (or Attach to one you started), " +
        "then work left-to-right through the tabs. Hover any control for a one-line explanation.";
}
