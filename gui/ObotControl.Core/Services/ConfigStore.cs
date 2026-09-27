using ObotControl.Core.Models;

namespace ObotControl.Core.Services;

/// <summary>
/// Holds the single source-of-truth config (the engine owns the file; the GUI never
/// writes config.json directly). Setup and Configuration both read <see cref="Current"/>,
/// apply their section, and <see cref="SaveAsync"/> the whole thing back via set_config,
/// which returns the canonical config the store then re-publishes.
/// </summary>
public sealed class ConfigStore
{
    private readonly EngineApi _api;

    public ConfigStore(EngineApi api) => _api = api;

    public ObotConfig Current { get; private set; } = new();

    /// <summary>Raised after Current changes (initial load or a save), so pages re-bind.</summary>
    public event EventHandler? Changed;

    // No ConfigureAwait(false) here: Changed handlers repopulate UI-bound
    // properties, so these continuations must resume on the caller's (UI) thread.
    public async Task LoadAsync()
    {
        Current = await _api.GetConfigAsync();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public async Task<ObotConfig> SaveAsync(ObotConfig config)
    {
        Current = await _api.SetConfigAsync(config);
        Changed?.Invoke(this, EventArgs.Empty);
        return Current;
    }
}
