# Software versions and links

This record describes declared version 1.0.0, dated 23 September 2026. Minimum requirements are distinct from versions actually installed.

## Project and recorded environment

| Component | Declared or recorded version | Source |
| --- | --- | --- |
| Engine and desktop | 1.0.0 (declared) | pyproject.toml; gui/Directory.Build.props |
| Python package requirement | >=3.12 | pyproject.toml |
| Setup script | Python 3.12 | scripts/setup.py |
| Recorded Python | 3.12.1 | checks/environment.json |
| Recorded OS | macOS 26.4.1, Arm64 | checks/environment.json |
| Recorded .NET SDK / runtime | 10.0.401 / 10.0.12 | Desktop test/build logs |
| Desktop target | net10.0 | Desktop project files |
| Avalonia | 11.2.3 | Desktop project file |
| GUI-managed Python download | 3.12.10; standalone build 20250409 where used | PythonEnvironmentService.cs |
| Project robot | OhBot 2.2, author-confirmed | Physical operation was not tested in this revision |

Official documentation: [Python 3.12](https://docs.python.org/3.12/), [.NET 10](https://dotnet.microsoft.com/en-us/download/dotnet/10.0), [Avalonia 11.2.3](https://www.nuget.org/packages/Avalonia/11.2.3), [Ohbot Python library](https://github.com/ohbot/ohbot-python). Source version 1.0.0 does not establish a published release. The managed Python download was not used for this check.

## Declared installation profiles

The base package requires `numpy>=1.26`. Optional extras are:

| Extra | Requirements from pyproject.toml |
| --- | --- |
| desktop | `websockets>=14`, `httpx>=0.27`, `sounddevice>=0.4.6`, `SpeechRecognition>=3.10` |
| voice | `pyttsx3>=2.90; sys_platform != 'darwin'`, `comtypes>=1.4; sys_platform == 'win32'` |
| ssh | `sshtunnel>=0.4`, `paramiko>=3.4,<4` |
| hardware | `ohbot>=4.0`, `pyserial>=3.5` |
| ml | `torch>=2.2`, `scipy>=1.11`, `soundfile>=0.12`, `matplotlib>=3.8` |

The default setup installs the desktop extra. The voice profile adds platform voice support; macOS uses its built-in `say` service. The full profile reads the platform requirements. The ML profile adds movement-model libraries without downloading a dataset or checkpoint.

### Platform and training files

These are declarations, not a claim that every optional package was exercised. Package documentation is available from each package's [PyPI project page](https://pypi.org/).

`requirements.txt`:

```text
-r requirements/desktop.txt
```

`requirements/desktop.txt`:

```text
-e .[desktop]
```

`requirements/windows.txt`:

```text
httpx>=0.27
sshtunnel>=0.4
paramiko>=3.4,<4
websockets>=14
pyttsx3>=2.90; sys_platform != "darwin"
comtypes>=1.4; sys_platform == "win32"
gTTS>=2.5
edge-tts>=7.0
miniaudio>=1.59
kokoro-onnx>=0.4
piper-tts>=1.4
sounddevice>=0.4.6
SpeechRecognition>=3.10
vosk>=0.3.45; sys_platform != "darwin"
vosk==0.3.44; sys_platform == "darwin"
ohbot>=4.0
pyserial>=3.5
numpy>=1.26
```

`requirements/macos.txt`:

```text
-r windows.txt
```

`requirements/linux.txt`:

```text
-r windows.txt
```

`requirements/pi.txt`:

```text
-r linux.txt
pigpio>=1.78
RPi.GPIO>=0.7.1
```

`requirements/ml.txt`:

```text
numpy>=1.26
torch>=2.2
scipy>=1.11
soundfile>=0.12
matplotlib>=3.8
```

Paramiko is kept below 4 because sshtunnel 0.4 uses its removed DSAKey API. The macOS full profile selects Vosk 0.3.44; other platforms retain the declared >=0.3.45 requirement. Optional neural voices, model inference and hardware drivers were not installed by the desktop-profile check.

## Installed Python packages

These versions were read from the new desktop environment. This is a record, not a cross-platform lockfile.

| Package | Installed version |
| --- | --- |
| anyio | 4.15.1 |
| certifi | 2026.7.22 |
| cffi | 2.1.1 |
| h11 | 0.16.0 |
| httpcore | 1.0.9 |
| httpx | 0.28.1 |
| idna | 3.20 |
| numpy | 2.5.3 |
| obot | 1.0.0 |
| pip | 23.2.1 |
| pycparser | 3.0 |
| sounddevice | 0.5.6 |
| SpeechRecognition | 3.17.0 |
| typing_extensions | 4.16.0 |
| websockets | 17.1 |

## Desktop package declarations

| Project | Package | Version |
| --- | --- | --- |
| ObotControl.App | Avalonia | 11.2.3 |
| ObotControl.App | Avalonia.Desktop | 11.2.3 |
| ObotControl.App | Avalonia.Themes.Fluent | 11.2.3 |
| ObotControl.App | Avalonia.Fonts.Inter | 11.2.3 |
| ObotControl.App | Avalonia.Diagnostics | 11.2.3 |
| ObotControl.App | Tmds.DBus.Protocol | 0.21.3 |
| ObotControl.Core | CommunityToolkit.Mvvm | 8.4.0 |
| ObotControl.Core.Tests | Microsoft.NET.Test.Sdk | 17.12.0 |
| ObotControl.Core.Tests | xunit | 2.9.2 |
| ObotControl.Core.Tests | xunit.runner.visualstudio | 2.8.2 |

## Models, voices, and data

These entries describe available options and supplied defaults. They do not identify the model used in a physical trial. Sources are `config.example.json`, `src/obot/speech/tts.py`, and `gui/ObotControl.Core/Services/VoskModelSetupService.cs`.

| Component | Supplied identifier or setting | Official link and meaning |
| --- | --- | --- |
| Gemini dialogue | Selected per session; no single model identifier fixed | [Gemini API documentation](https://ai.google.dev/gemini-api/docs) |
| Ollama dialogue | Selected per session; no single model tag fixed | [Ollama documentation](https://docs.ollama.com/) |
| Gemini speech | `gemini-2.5-flash-preview-tts`; voice `Kore` | [Gemini API documentation](https://ai.google.dev/gemini-api/docs); configured default, not a verified service call |
| Gemini speech API | `v1beta` | Version in the endpoint used by `GeminiTTS` |
| Kokoro model and voices | `kokoro-v1.0.onnx`; `voices-v1.0.bin`; release `model-files-v1.0` | [Model-file release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0); distinct from the `kokoro-onnx` library version |
| Kokoro voice | `bf_emma` | Voice identifier in the example settings |
| Piper voice | `en_GB-cori-high` | [Piper package](https://pypi.org/project/piper-tts/); configured voice name, without a pinned model-file revision |
| Edge voice | `en-GB-SoniaNeural` | [edge-tts package](https://pypi.org/project/edge-tts/); configured service voice name |
| gTTS | Language `en`, domain `co.uk`, `slow=false` | [gTTS package](https://pypi.org/project/gTTS/); no service model version fixed |
| Local speech | Example voice `zira`, 175 words per minute; setup clears the voice identifier to use an installed default | [pyttsx3 package](https://pypi.org/project/pyttsx3/); voice availability depends on the local system |
| Vosk English options in setup | `vosk-model-small-en-us-0.15`; `vosk-model-en-us-0.22` | [Vosk model catalogue](https://alphacephei.com/vosk/models) |
| Vosk German options in setup | `vosk-model-small-de-0.15`; `vosk-model-de-0.21` | [Vosk model catalogue](https://alphacephei.com/vosk/models) |
| BEAT2 recordings | BEAT2, introduced with EMAGE (2024) | [Official project](https://pantomatrix.github.io/EMAGE/); see the EMAGE bibliography entry in the paper |

The Vosk path is empty in the example settings, so the setup catalogue does not establish which model was used. Voice names are identifiers, not model release numbers. A run should record the selected dialogue model, local model tag or file hash, speech option and voice, recognizer model, configuration, and date. Automatic speech fallback can select a different option.

The review examples disable the optional movement model and background movements. Checkpoint paths, the model library and preview-audio paths are empty. The conversion, training and preview code is included; data, audio and saved models are excluded. Add your own checkpoint and record its hash for a movement-model run. The configured 20 updates per second is a playback rate, not an inference-speed result.

## Check scope and version history

Current checks are under `checks/`: a fresh desktop setup, 15 regression tests, four installation tests, 33 C# tests, the nine-scene console script, the custom action and the two-turn scripted recorder. Separate server and desktop-build logs record their outcomes. Source imports and pip dependency checks passed.

No live model, physical robot, captured microphone input or optional trained-model inference was tested in this revision. A previous installation-only branch was opened through the native macOS GUI; that observation is not labeled as a new interactive GUI run of the merged revision. An automated shell can fail to generate local macOS speech and fall back to simulated pacing; see the installation guide.

The earlier 2026-09-22-r1 records used Python 3.12.14 and NumPy 2.3.5. They remain in the archived paper/review package, separate from these new results. This draft leaves license and maintenance details for author completion. No repository URL or release DOI has been invented.
