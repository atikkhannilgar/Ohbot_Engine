using ObotControl.Core.Services;
using Xunit;

namespace ObotControl.Core.Tests;

/// <summary>
/// Covers the deterministic, local-only pieces of Python environment provisioning 
/// venv discovery/version parsing and status gating  against temp-directory fixtures.
/// Nothing here downloads or runs the real installer (too slow/networked for the suite;
/// that pipeline is exercised manually per docs/gui-plan.md's verification steps).
/// </summary>
public sealed class PythonEnvironmentServiceTests : IDisposable
{
    private readonly string _repoRoot;
    private readonly PythonEnvironmentService _service = new();

    public PythonEnvironmentServiceTests()
    {
        _repoRoot = Path.Combine(Path.GetTempPath(), "obot-pyenv-test-" + Guid.NewGuid());
        Directory.CreateDirectory(_repoRoot);
    }

    public void Dispose()
    {
        try { Directory.Delete(_repoRoot, recursive: true); } catch { /* best effort */ }
    }

    private string CreateFakeVenv(string name, string version)
    {
        // Mirrors the platform's real venv layout (Scripts\python.exe vs bin/python), which is what ScanVenvDirs looks for.
        var dir = Path.Combine(_repoRoot, name);
        var exe = Path.Combine(dir, PythonEnvironmentService.VenvRelativePythonPath);
        Directory.CreateDirectory(Path.GetDirectoryName(exe)!);
        File.WriteAllText(exe, "not a real executable");
        File.WriteAllText(Path.Combine(dir, "pyvenv.cfg"), $"home = /fake\nversion = {version}\ninclude-system-site-packages = false\n");
        return exe;
    }

    [Fact]
    public void CheckStatus_NoRepoNoRemembered_ReportsNotReady()
    {
        var status = _service.CheckStatus(null, null);
        Assert.False(status.IsReady);
    }

    [Fact]
    public void CheckStatus_FindsMatchingVenvUnderRepoRoot()
    {
        var exe = CreateFakeVenv("OhBots", "3.12.10");

        var status = _service.CheckStatus(_repoRoot, null);

        Assert.False(status.IsReady); // A venv path alone does not establish installed dependencies.
        Assert.Equal(exe, status.Active?.PythonExePath);
        Assert.Equal("3.12.10", status.Active?.Version);
    }

    [Fact]
    public void CheckStatus_IgnoresWrongPythonVersion()
    {
        CreateFakeVenv("OldVenv", "3.11.5");

        var status = _service.CheckStatus(_repoRoot, null);

        Assert.False(status.IsReady);
    }

    [Fact]
    public void CheckStatus_PrefersRememberedPathWhenStillValid()
    {
        CreateFakeVenv("OhBots", "3.12.10");
        var remembered = CreateFakeVenv("Other", "3.12.4");

        var status = _service.CheckStatus(_repoRoot, remembered);

        Assert.False(status.IsReady); // A venv path alone does not establish installed dependencies.
        Assert.Equal(remembered, status.Active?.PythonExePath);
    }

    [Fact]
    public void CheckStatus_FallsBackWhenRememberedPathIsGone()
    {
        var exe = CreateFakeVenv("OhBots", "3.12.10");
        var missing = Path.Combine(_repoRoot, "Deleted", PythonEnvironmentService.VenvRelativePythonPath);

        var status = _service.CheckStatus(_repoRoot, missing);

        Assert.False(status.IsReady); // A venv path alone does not establish installed dependencies.
        Assert.Equal(exe, status.Active?.PythonExePath);
    }

    [Fact]
    public async Task DiscoverCandidatesAsync_ListsEveryVenvAndEndsWithAutoInstall()
    {
        var ohbots = CreateFakeVenv("OhBots", "3.12.10");
        var custom = CreateFakeVenv("my-custom-env", "3.11.0");

        var found = await _service.DiscoverCandidatesAsync(_repoRoot);

        Assert.Contains(found, c => c.Kind == PythonCandidateKind.ExistingVenv && c.PythonExePath == ohbots && c.Version == "3.12.10");
        Assert.Contains(found, c => c.Kind == PythonCandidateKind.ExistingVenv && c.PythonExePath == custom && c.Version == "3.11.0");
        Assert.Equal(PythonCandidateKind.ManagedAutoInstall, found[^1].Kind);
    }

    [Fact]
    public async Task DiscoverCandidatesAsync_EmptyRepo_OnlyOffersAutoInstall()
    {
        var found = await _service.DiscoverCandidatesAsync(_repoRoot);

        Assert.DoesNotContain(found, c => c.Kind == PythonCandidateKind.ExistingVenv);
        Assert.Single(found, c => c.Kind == PythonCandidateKind.ManagedAutoInstall);
    }

    [Fact]
    public void PythonCandidate_ToStringIsDisplayName()
    {
        var candidate = new PythonCandidate { Kind = PythonCandidateKind.ExistingVenv, DisplayName = "OhBots (existing venv, Python 3.12.10)" };
        Assert.Equal(candidate.DisplayName, candidate.ToString());
    }

    [Fact]
    public void ManagedPythonDir_IsScopedToThePinnedVersion()
    {
        Assert.EndsWith(Path.Combine("Python", PythonEnvironmentService.PythonVersion), PythonEnvironmentService.ManagedPythonDir);
        Assert.Equal("3.12.10", PythonEnvironmentService.PythonVersion);
    }

    [Fact]
    public void Service_IsSupportedOnDesktopPlatforms()
    {
        Assert.True(_service.IsSupported);
    }

    [Fact]
    public void RequirementsFileName_MatchesThePlatform()
    {
        var name = PythonEnvironmentService.RequirementsFileName;
        Assert.Equal("desktop.txt", name);
    }

    // -- InstallRequirementsAsync (the ML Control page's dependency installer) ------------
    //
    // The pip run itself isn't exercised here (a real torch download has no business in a
    // unit-test suite); what is covered is everything that decides *whether* pip runs and
    // against what, since those are the failures a user would otherwise see as a hang.

    [Fact]
    public async Task InstallRequirements_MissingInterpreter_FailsWithoutRunningPip()
    {
        var progress = new List<SetupProgress>();
        var result = await _service.InstallRequirementsAsync(
            Path.Combine(_repoRoot, "nope", "python.exe"), _repoRoot, "requirements/ml.txt",
            new Progress<SetupProgress>(progress.Add), CancellationToken.None);

        Assert.False(result.Ok);
        Assert.Contains("not found on this machine", result.Message);
    }

    [Fact]
    public async Task InstallRequirements_MissingRequirementsFile_FailsCleanly()
    {
        // A file that exists just enough to pass the interpreter check.
        var exe = CreateFakeVenv("OhBots", "3.12.10");

        var result = await _service.InstallRequirementsAsync(
            exe, _repoRoot, "requirements/ml.txt",
            new Progress<SetupProgress>(_ => { }), CancellationToken.None);

        Assert.False(result.Ok);
        Assert.Contains("requirements file not found", result.Message);
    }

    [Fact]
    public async Task InstallRequirements_ResolvesTheEngineReportedRelativePath()
    {
        var exe = CreateFakeVenv("OhBots", "3.12.10");
        // The engine reports POSIX-style relative paths; they must resolve on Windows too.
        var reqDir = Path.Combine(_repoRoot, "requirements");
        Directory.CreateDirectory(reqDir);
        File.WriteAllText(Path.Combine(reqDir, "ml.txt"), "# nothing to install\n");

        var result = await _service.InstallRequirementsAsync(
            exe, _repoRoot, "requirements/ml.txt",
            new Progress<SetupProgress>(_ => { }), CancellationToken.None);

        // The fake interpreter can't actually run, so this reaches the pip step and fails
        // there  proof the relative path resolved, rather than bailing out earlier. It must
        // come back as a result, not an unhandled exception.
        Assert.False(result.Ok);
        Assert.Contains("could not run", result.Message);
    }
}
