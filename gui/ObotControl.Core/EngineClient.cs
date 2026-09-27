using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using ObotControl.Core.Protocol;

namespace ObotControl.Core;

/// <summary>
/// The thin transport to the Python engine: one WebSocket carrying request/result
/// pairs and server-pushed events. Handles a connect/reconnect loop, correlates
/// results to <see cref="CallAsync"/> callers by id, and fans events out to the UI.
///
/// Threading: the receive loop runs on a background task. All public events are
/// raised through the dispatcher supplied to <see cref="UseDispatcher"/> (a no-op
/// passthrough by default), so a UI can safely touch bound properties from a handler
/// without marshaling itself.
/// </summary>
public sealed class EngineClient : IAsyncDisposable
{
    private readonly ConcurrentDictionary<int, TaskCompletionSource<ResultMessage>> _pending = new();
    private readonly SemaphoreSlim _sendLock = new(1, 1);

    private ClientWebSocket? _ws;
    private CancellationTokenSource? _cts;
    private Task? _connectionTask;
    private int _nextId;
    private Action<Action> _post = a => a();

    public Uri? Endpoint { get; private set; }
    public ConnectionState State { get; private set; } = ConnectionState.Disconnected;

    public event EventHandler<ConnectionState>? StateChanged;
    public event EventHandler<EngineEvent>? EngineEventReceived;

    /// <summary>Supply a marshaller (e.g. DispatcherQueue.TryEnqueue) so events land on the UI thread.</summary>
    public void UseDispatcher(Action<Action> post) => _post = post;

    public bool IsConnected => State == ConnectionState.Connected;

    // -- connection lifecycle ---------------------------------------------------------

    /// <summary>Start (or restart) the connect/reconnect loop targeting <paramref name="uri"/>.</summary>
    public void Connect(Uri uri, bool autoReconnect = true)
    {
        _ = DisconnectAsync();
        Endpoint = uri;
        _cts = new CancellationTokenSource();
        _connectionTask = Task.Run(() => RunConnectionAsync(uri, autoReconnect, _cts.Token));
    }

    private async Task RunConnectionAsync(Uri uri, bool autoReconnect, CancellationToken ct)
    {
        var backoff = TimeSpan.FromMilliseconds(500);
        while (!ct.IsCancellationRequested)
        {
            SetState(ConnectionState.Connecting);
            var ws = new ClientWebSocket();
            try
            {
                await ws.ConnectAsync(uri, ct).ConfigureAwait(false);
                _ws = ws;
                SetState(ConnectionState.Connected);
                backoff = TimeSpan.FromMilliseconds(500);
                await ReceiveLoopAsync(ws, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch
            {
                // Fall through to the reconnect delay below.
            }
            finally
            {
                FailAllPending("connection lost");
                ws.Dispose();
                if (_ws == ws) _ws = null;
            }

            if (ct.IsCancellationRequested || !autoReconnect)
            {
                break;
            }
            SetState(ConnectionState.Reconnecting);
            try { await Task.Delay(backoff, ct).ConfigureAwait(false); }
            catch (OperationCanceledException) { break; }
            backoff = TimeSpan.FromMilliseconds(Math.Min(backoff.TotalMilliseconds * 1.7, 5000));
        }
        SetState(ConnectionState.Disconnected);
    }

    private async Task ReceiveLoopAsync(ClientWebSocket ws, CancellationToken ct)
    {
        var buffer = new byte[64 * 1024];
        using var message = new MemoryStream();
        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            message.SetLength(0);
            WebSocketReceiveResult result;
            do
            {
                result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct).ConfigureAwait(false);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    return;
                }
                message.Write(buffer, 0, result.Count);
            }
            while (!result.EndOfMessage);

            Dispatch(Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length));
        }
    }

    private void Dispatch(string json)
    {
        JsonElement root;
        try
        {
            using var doc = JsonDocument.Parse(json);
            root = doc.RootElement.Clone();
        }
        catch (JsonException)
        {
            return;
        }

        if (!root.TryGetProperty("type", out var typeProp))
        {
            return;
        }
        var type = typeProp.GetString();

        if (type == MessageTypes.Result)
        {
            var msg = ObotJson.Deserialize<ResultMessage>(root)!;
            if (msg.Id is int id && _pending.TryRemove(id, out var tcs))
            {
                tcs.TrySetResult(msg);
            }
        }
        else if (type == MessageTypes.Event)
        {
            var topic = root.TryGetProperty("topic", out var t) ? t.GetString() ?? "" : "";
            var data = root.TryGetProperty("data", out var d) ? d.Clone() : default;
            var evt = new EngineEvent(topic, data);
            _post(() => EngineEventReceived?.Invoke(this, evt));
        }
    }

    // -- RPC --------------------------------------------------------------------------

    /// <summary>Invoke an engine method and await its result payload.</summary>
    public async Task<JsonElement> CallAsync(string method, object? @params = null,
        TimeSpan? timeout = null, CancellationToken ct = default)
    {
        var ws = _ws;
        if (ws is null || State != ConnectionState.Connected)
        {
            throw new InvalidOperationException("not connected to the engine.");
        }

        var id = Interlocked.Increment(ref _nextId);
        var tcs = new TaskCompletionSource<ResultMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
        _pending[id] = tcs;

        var call = new CallMessage { Id = id, Method = method, Params = @params };
        var bytes = Encoding.UTF8.GetBytes(ObotJson.Serialize(call));

        await _sendLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            await ws.SendAsync(bytes, WebSocketMessageType.Text, true, ct).ConfigureAwait(false);
        }
        catch
        {
            _pending.TryRemove(id, out _);
            throw;
        }
        finally
        {
            _sendLock.Release();
        }

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeoutCts.CancelAfter(timeout ?? TimeSpan.FromSeconds(30));
        var registration = timeoutCts.Token.Register(() =>
        {
            if (_pending.TryRemove(id, out var pending))
            {
                pending.TrySetException(new TimeoutException($"'{method}' timed out."));
            }
        });
        try
        {
            var reply = await tcs.Task.ConfigureAwait(false);
            if (!reply.Ok)
            {
                throw new EngineException(reply.Error ?? $"'{method}' failed.");
            }
            return reply.Data;
        }
        finally
        {
            await registration.DisposeAsync().ConfigureAwait(false);
        }
    }

    /// <summary>Invoke a method and deserialize its result payload to <typeparamref name="T"/>.</summary>
    public async Task<T?> CallAsync<T>(string method, object? @params = null,
        TimeSpan? timeout = null, CancellationToken ct = default)
    {
        var data = await CallAsync(method, @params, timeout, ct).ConfigureAwait(false);
        return ObotJson.Deserialize<T>(data);
    }

    // -- shutdown ---------------------------------------------------------------------

    public async Task DisconnectAsync()
    {
        var cts = _cts;
        _cts = null;
        if (cts is not null)
        {
            cts.Cancel();
        }
        var task = _connectionTask;
        _connectionTask = null;
        if (task is not null)
        {
            try { await task.ConfigureAwait(false); } catch { /* best effort */ }
        }
        cts?.Dispose();
        FailAllPending("disconnected");
    }

    public async ValueTask DisposeAsync()
    {
        await DisconnectAsync().ConfigureAwait(false);
        _sendLock.Dispose();
    }

    private void FailAllPending(string reason)
    {
        foreach (var id in _pending.Keys.ToArray())
        {
            if (_pending.TryRemove(id, out var tcs))
            {
                tcs.TrySetException(new EngineException(reason));
            }
        }
    }

    private void SetState(ConnectionState state)
    {
        if (State == state) return;
        State = state;
        _post(() => StateChanged?.Invoke(this, state));
    }
}
