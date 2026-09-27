using System.Collections.Concurrent;
using ObotControl.Core;
using ObotControl.Core.Protocol;
using ObotControl.Core.Services;
using Xunit;

namespace ObotControl.Core.Tests;

/// <summary>
/// End-to-end: drive the real C# <see cref="EngineClient"/> against a real
/// <c>python -m obot --serve</c> process  the client mirror of the Python smoke test.
/// Proves the whole GUI transport stack (WebSocket, RPC correlation, event fan-out)
/// works against the live engine. Skips cleanly on a machine without the venv Python.
/// </summary>
public class EngineIntegrationTests
{
    private static int FreePort()
    {
        var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    [Fact]
    public async Task FullSessionFlow_AgainstRealEngine()
    {
        var repoRoot = EngineProcess.LocateRepoRoot();
        Assert.NotNull(repoRoot);
        var python = EngineProcess.VenvPython(repoRoot!);
        if (python is null)
        {
            // No bundled interpreter on this machine  nothing to integrate against.
            return; // treated as passing/skipped
        }

        var port = FreePort();
        using var engine = new EngineProcess(new EngineLaunchOptions
        {
            RepoRoot = repoRoot!,
            PythonPath = python,
            Port = port,
        });
        engine.Start();

        await using var client = new EngineClient();
        var events = new ConcurrentQueue<EngineEvent>();
        var byTopic = new ConcurrentDictionary<string, int>();
        client.EngineEventReceived += (_, e) =>
        {
            events.Enqueue(e);
            byTopic.AddOrUpdate(e.Topic, 1, (_, n) => n + 1);
        };

        var connected = new TaskCompletionSource();
        client.StateChanged += (_, s) =>
        {
            if (s == ConnectionState.Connected) connected.TrySetResult();
        };
        client.Connect(new Uri($"ws://127.0.0.1:{port}"));

        // Server takes a moment to import the engine and open the socket.
        await WaitOrTimeout(connected.Task, TimeSpan.FromSeconds(40), "connect");

        var api = new EngineApi(client);

        var config = await api.GetConfigAsync();
        Assert.NotNull(config.Speech);
        Assert.NotNull(config.Motion);

        // Save round-trip (writes back identical values, so config.json is untouched):
        // proves EngineApi.SetConfigAsync serializes and persists correctly end-to-end.
        var saved = await api.SetConfigAsync(config);
        Assert.Equal(config.OhbotPort, saved.OhbotPort);
        Assert.Equal(config.Speech.Mouth.Gate, saved.Speech.Mouth.Gate, 3);
        Assert.Equal(config.Speech.Tts.Engine, saved.Speech.Tts.Engine);

        var mics = await api.ListMicsAsync();
        Assert.NotNull(mics); // may be empty on a mic-less box

        var voices = await api.ListTtsVoicesAsync();
        Assert.NotEmpty(voices.Gemini);

        var started = await api.StartSessionAsync("scripted", "", "virtual");
        Assert.True(started.Session);
        Assert.Equal("virtual", started.Controller);

        // Ambient behaviors move joints as soon as a virtual session runs.
        await WaitFor(() => byTopic.ContainsKey(Topics.Joints), TimeSpan.FromSeconds(10), "joints");

        // Emotions: the manual control panel's ListEmotionsAsync/SetEmotionAsync wrappers
        // round-trip and get_state reflects the applied emotion.
        var emotionNames = await api.ListEmotionsAsync();
        Assert.Contains("Sad", emotionNames);
        Assert.Contains("Neutral", emotionNames);
        await api.SetEmotionAsync("Sad");
        var stateAfterSad = await api.GetStateAsync();
        Assert.Equal("Sad", stateAfterSad.Emotion);
        await api.SetEmotionAsync("Neutral");

        await api.SendTextAsync("Hello there [Nod] (Happy) I am Ms Mimic. "
                                + "This is a long enough sentence to interrupt. And another one.");
        await WaitFor(() => byTopic.ContainsKey(Topics.Transcript), TimeSpan.FromSeconds(5), "transcript");
        await WaitFor(() => byTopic.ContainsKey(Topics.Speech), TimeSpan.FromSeconds(10), "speech");

        await Task.Delay(400);
        events.Clear(); // Require a new idle event after this interrupt request.
        await api.InterruptAsync();

        var backToIdle = await WaitForState(events, "idle", TimeSpan.FromSeconds(15));
        Assert.True(backToIdle, "session did not return to idle after interrupt");

        var stopped = await api.StopSessionAsync();
        Assert.False(stopped.Session);
    }

    private static async Task WaitOrTimeout(Task task, TimeSpan timeout, string what)
    {
        var done = await Task.WhenAny(task, Task.Delay(timeout));
        if (done != task) throw new TimeoutException($"timed out waiting to {what}.");
        await task;
    }

    private static async Task WaitFor(Func<bool> condition, TimeSpan timeout, string what)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (condition()) return;
            await Task.Delay(100);
        }
        throw new TimeoutException($"timed out waiting for {what}.");
    }

    private static async Task<bool> WaitForState(ConcurrentQueue<EngineEvent> events, string target, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            foreach (var e in events)
            {
                if (e.Topic == Topics.State && e.Data.TryGetProperty("state", out var st)
                    && st.GetString() == target)
                {
                    return true;
                }
            }
            await Task.Delay(100);
        }
        return false;
    }
}
