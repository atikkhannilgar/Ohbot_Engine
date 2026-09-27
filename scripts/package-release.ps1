<#
.SYNOPSIS
    Builds the downloadable OhBot Control release package.

.DESCRIPTION
    Produces one archive per runtime that a user can extract and run:

        OhBotControl-<version>-win-x64/
          OhBotControl.exe        single-file Avalonia GUI (framework-dependent, needs .NET 10)
          START-HERE.md           quick start for the downloaded package
          README.md               the project README
          config.json             seeded from config.example.json, no credentials
          src/ requirements/ ...  the Python engine the GUI launches

    The GUI finds the engine by walking up from its own folder looking for
    src/obot/__main__.py (EngineProcess.LocateRepoRoot), so the executable has to sit
    at the top of that tree, which is exactly the layout above.

    The Python payload comes from `git ls-files`, so nothing untracked can leak into a
    release: config.json (API keys), ohbotData/ (gigabytes of downloaded voice models),
    the venv and every __pycache__ are gitignored and therefore absent by construction.
    The GUI sources are dropped too, since the built executable replaces them.

.PARAMETER Version
    Version stamped into the folder and archive names. Defaults to <Version> in
    gui/Directory.Build.props.

.PARAMETER Runtime
    One or more .NET runtime identifiers to publish: win-x64, linux-x64, linux-arm64
    (Raspberry Pi OS 64-bit).

.PARAMETER OutDir
    Where the archives land. Default: <repo>/dist.

.EXAMPLE
    powershell -File scripts/package-release.ps1
    powershell -File scripts/package-release.ps1 -Version 1.0.0 -Runtime win-x64,linux-x64
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string[]]$Runtime = @('win-x64'),
    [string]$OutDir,
    [switch]$KeepStaging
)

$ErrorActionPreference = 'Stop'

# `powershell -File package-release.ps1 -Runtime win-x64,linux-x64` hands the list over as
# one string rather than an array, so split it back apart.
$Runtime = @($Runtime | ForEach-Object { $_ -split ',' } | Where-Object { $_ })

$repoRoot = Split-Path -Parent $PSScriptRoot
$appProject = Join-Path $repoRoot 'gui\ObotControl.App\ObotControl.App.csproj'
if (-not $OutDir) { $OutDir = Join-Path $repoRoot 'dist' }

# Tracked files with no business in a runnable download: the GUI sources (the
# executable replaces them), editor settings and the slide deck.
$excludePrefixes = @('gui/', '.vscode/', '.gitignore', 'docs/OhBot Behaviours Engine.pptx')

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

function Get-RepoVersion {
    $props = Join-Path $repoRoot 'gui\Directory.Build.props'
    $match = Select-String -Path $props -Pattern '<Version>(.+?)</Version>'
    if (-not $match) { throw "no <Version> found in $props" }
    return $match.Matches[0].Groups[1].Value
}

# Every tracked file except the exclusions. `git ls-files -s` also reports mode 160000
# entries (the uninitialised BEAT/BEAT2 dataset submodules); those are pointers, not
# files, so they are skipped.
function Get-PayloadFile {
    Push-Location $repoRoot
    try {
        $entries = & git ls-files -s
        if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed, is this a git checkout?' }
    }
    finally { Pop-Location }

    $files = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $entries) {
        $parts = $entry -split "`t", 2
        if ($parts.Count -ne 2) { continue }
        if ($parts[0].StartsWith('160000')) { continue }
        $path = $parts[1]
        $skip = $false
        foreach ($prefix in $excludePrefixes) {
            if ($path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { $skip = $true; break }
        }
        if (-not $skip) { $files.Add($path) }
    }
    return $files
}

function Copy-Payload($files, $stage) {
    foreach ($file in $files) {
        $source = Join-Path $repoRoot $file
        if (-not (Test-Path -LiteralPath $source)) {
            Write-Warning "tracked but missing on disk, skipped: $file"
            continue
        }
        $target = Join-Path $stage $file
        $targetDir = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

# The engine starts from built-in defaults when config.json is missing, but those
# defaults leave the ML gesture model switched off. Seeding the file from the example
# gives a fresh download the intended demo setup (gesture model on, bundled checkpoint
# registered) and carries no credentials, since the example's key fields are empty.
function New-SeedConfig($stage) {
    $example = Join-Path $stage 'config.example.json'
    $target = Join-Path $stage 'config.json'
    Copy-Item -LiteralPath $example -Destination $target -Force

    $config = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
    if ($config.gemini_api_key -ne '') {
        throw 'config.example.json carries a Gemini API key, refusing to package it'
    }
    foreach ($field in 'host', 'user', 'key_path') {
        if ($config.ollama_ssh.$field -ne '') {
            throw "config.example.json carries an SSH $field, refusing to package it"
        }
    }
}

function New-StartHere($stage, $rid, $exeName, $version) {
    # Windows still enforces a 260-character path limit when loading the .pyd files in
    # the Python environment the app builds inside this folder, and Explorer's "Extract
    # All" adds a nesting level of its own.
    $pathNote = ''
    if ($rid.StartsWith('win')) {
        $pathNote = @'


   Keep the path short as well: `C:\OhBot` or your Desktop is ideal, five folders deep
   inside another `Downloads` folder is asking for trouble.
'@
    }

    if ($rid.StartsWith('win')) {
        $runStep = @'
2. **Run `OhBotControl.exe`.**
   Windows has not seen this executable before, so SmartScreen may warn about an
   unknown publisher: choose **More info** -> **Run anyway**.
'@
    }
    else {
        $runStep = @'
2. **Make the launcher executable and start it.**

   ```bash
   chmod +x ./__EXE__
   ./__EXE__
   ```

   Audio needs two system libraries once: `sudo apt install libportaudio2 espeak-ng`.
   For the physical robot also run `sudo usermod -aG dialout $USER` and log back in.
'@
    }
    $runStep = $runStep.Replace('__EXE__', $exeName)

    $template = @'
# OhBot Control __VERSION__ - start here

Everything needed to run the OhBot behaviour engine and its desktop GUI. The GUI is the
front door: it provisions Python for you, launches the engine and drives the robot.

## Requirements

- **.NET 10 Desktop Runtime** - the only thing you have to install yourself. Check with
  `dotnet --list-runtimes`; get it from <https://dotnet.microsoft.com/download/dotnet/10.0>.
- About 2 GB of free disk space for the Python environment the app builds on first run,
  and an internet connection for that first run.
- A physical OhBot is **optional**. The `virtual` controller runs the entire pipeline and
  draws the robot in the GUI's face panel.

## Three steps

1. **Extract this folder somewhere you can write to** (Documents, Desktop, a USB stick) -
   not `Program Files`, because the app installs a Python environment inside this folder.__PATHNOTE__
__RUNSTEP__
3. **Set up Python from the Setup tab.** It opens on *0. Python environment*. Press
   **Set up automatically**: it reuses a Python 3.12 already on the machine, or downloads
   a private one that touches neither PATH nor any existing install, and then installs the
   engine's dependencies. Allow a few minutes.

Then fill in your Gemini API key (or your Ollama SSH details) further down the Setup tab,
press **Save**, press **Launch engine**, and switch to the Dashboard: pick a backend, a
model and the `virtual` controller, press **Start**, and talk or type.

## Good to know

- **The first sentence is slow.** The default voice (Piper `en_GB-cori-high`, about
  114 MB) and any Kokoro or Vosk model download on first use into `ohbotData/` next to
  this file. After that everything runs offline except the LLM itself.
- **Settings live in `config.json`** beside the app, the same file the terminal app reads.
  It ships pre-filled with sensible defaults and no credentials.
- **The AI gesture model** (head, eyes and lids driven straight from the speech waveform)
  needs the optional ML extras. The GUI's *ML Control* page lists what is missing and
  installs `requirements/ml.txt` for you; the trained checkpoint is already in
  `src/obot/ml/models/`.
- **No GUI needed.** The engine also runs on its own: `python -m obot` for the terminal
  app, `python -m obot --serve` for the control server. See `docs/cli.md`.
- **Full documentation**: `README.md` and `docs/`.
'@

    $text = $template.Replace('__VERSION__', $version).
        Replace('__PATHNOTE__', $pathNote.TrimEnd()).
        Replace('__RUNSTEP__', $runStep)
    # Written without a BOM: Windows PowerShell's -Encoding utf8 adds one, and it shows up
    # as a stray character at the top of the file in some editors.
    [System.IO.File]::WriteAllText(
        (Join-Path $stage 'START-HERE.md'), $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Assert-CleanPayload($stage) {
    foreach ($name in 'ohbotData', 'OhBots', '.venv', 'venv', '.git', 'gui') {
        if (Test-Path -LiteralPath (Join-Path $stage $name)) {
            throw "package contains $name, which must not ship"
        }
    }
    $junk = Get-ChildItem -LiteralPath $stage -Recurse -Force |
        Where-Object { $_.Name -eq '__pycache__' -or $_.Extension -eq '.pyc' -or $_.Name.EndsWith('.egg-info') }
    if ($junk) { throw "package contains build junk: $($junk.FullName -join ', ')" }

    # The engine has to be findable from the executable's own folder.
    $entry = Join-Path $stage 'src\obot\__main__.py'
    if (-not (Test-Path -LiteralPath $entry)) {
        throw "package is missing $entry, so the GUI could not find the engine"
    }
}

function New-Archive($stage, $rid, $archiveName) {
    $stageParent = Split-Path -Parent $stage
    $folderName = Split-Path -Leaf $stage
    if ($rid.StartsWith('win')) {
        $archive = Join-Path $OutDir "$archiveName.zip"
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $stage, $archive, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    }
    else {
        # tar keeps the tree usable on Linux. Windows has no mode bits to preserve, so
        # the executable bit is restored by the chmod line in START-HERE.md.
        $archive = Join-Path $OutDir "$archiveName.tar.gz"
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
        & tar -czf $archive -C $stageParent $folderName
        if ($LASTEXITCODE -ne 0) { throw "tar failed for $archiveName" }
    }
    return $archive
}

if (-not $Version) { $Version = Get-RepoVersion }
$stagingRoot = Join-Path $OutDir 'staging'
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }

$payload = Get-PayloadFile
Write-Step "packaging OhBot Control $Version - $($payload.Count) engine files, runtimes: $($Runtime -join ', ')"

$results = @()
foreach ($rid in $Runtime) {
    $archiveName = "OhBotControl-$Version-$rid"
    # The extracted folder is deliberately short. Windows Explorer nests the archive's
    # own folder inside a second one named after the zip, and the Python environment the
    # app builds lands underneath both, where a long name can push .pyd files past the
    # 260-character cap that DLL loading still enforces.
    $stage = Join-Path (Join-Path $stagingRoot $rid) 'OhBotControl'
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    $exeName = 'OhBotControl'
    if ($rid.StartsWith('win')) { $exeName = 'OhBotControl.exe' }
    $publishDir = Join-Path $stagingRoot "publish-$rid"

    # Framework-dependent single file: one executable with every managed and native
    # dependency (Skia, HarfBuzz, ANGLE) bundled inside it. .NET 10 itself is expected
    # on the target machine.
    Write-Step "publishing the GUI for $rid"
    $publishArgs = @(
        'publish', $appProject,
        '--configuration', 'Release',
        '--runtime', $rid,
        '--self-contained', 'false',
        '-p:PublishSingleFile=true',
        '-p:IncludeNativeLibrariesForSelfExtract=true',
        '-p:DebugType=none',
        '--output', $publishDir,
        '--nologo'
    )
    & dotnet @publishArgs
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed for $rid" }

    $built = @(Get-ChildItem -LiteralPath $publishDir -File)
    Write-Host "    published $($built.Count) file(s): $(($built | ForEach-Object { $_.Name }) -join ', ')"
    $appHost = $built | Where-Object { $_.Name -like 'ObotControl.App*' -and $_.Extension -ne '.pdb' } | Select-Object -First 1
    if (-not $appHost) { throw "no executable found in $publishDir" }
    Copy-Item -LiteralPath $appHost.FullName -Destination (Join-Path $stage $exeName) -Force

    Write-Step "assembling the engine payload for $rid"
    Copy-Payload $payload $stage
    New-SeedConfig $stage
    New-StartHere $stage $rid $exeName $Version
    Assert-CleanPayload $stage

    Write-Step "compressing $archiveName"
    $archive = New-Archive $stage $rid $archiveName
    $sha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
    $sizeMb = [math]::Round((Get-Item -LiteralPath $archive).Length / 1MB, 1)
    $results += [pscustomobject]@{ Runtime = $rid; Archive = $archive; SizeMB = $sizeMb; SHA256 = $sha }
}

if (-not $KeepStaging) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }

Write-Step 'done'
$results | Format-List
# Merged rather than overwritten, so building one runtime at a time still ends with a
# checksum file covering every asset of this version.
$checksums = Join-Path $OutDir "SHA256SUMS-$Version.txt"
$sums = [ordered]@{}
if (Test-Path -LiteralPath $checksums) {
    foreach ($line in Get-Content -LiteralPath $checksums) {
        $parts = $line -split '\s+', 2
        if ($parts.Count -eq 2) { $sums[$parts[1].Trim()] = $parts[0] }
    }
}
foreach ($result in $results) { $sums[(Split-Path -Leaf $result.Archive)] = $result.SHA256 }
$lines = $sums.Keys | Sort-Object | ForEach-Object { "$($sums[$_])  $_" }
Set-Content -LiteralPath $checksums -Value $lines -Encoding ascii
Write-Host "checksums written to $checksums"
