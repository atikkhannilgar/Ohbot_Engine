namespace ObotControl.Core;

/// <summary>Lifecycle of the WebSocket link to the engine, surfaced to the UI.</summary>
public enum ConnectionState
{
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Faulted,
}

/// <summary>Thrown when the engine returns <c>ok:false</c> for an RPC call.</summary>
public sealed class EngineException : Exception
{
    public EngineException(string message) : base(message) { }
}
