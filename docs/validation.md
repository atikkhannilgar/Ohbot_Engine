# Technical validation and reproduction

The review revision checks software behavior without a physical OhBot, microphone, live model or speech service. It adds ten focused tests to the existing 20 regression and four installation tests. The installation suite binds a temporary loopback socket; an environment that prohibits local sockets cannot complete that test.

## Run all revision checks

From the repository root:

```sh
python3.12 scripts/setup.py --profile console
.venv/bin/python scripts/run_revision_checks.py --output revision_support/reproduced
```

On Windows, use `py -3.12 scripts/setup.py --profile console`, then `.venv\Scripts\python.exe scripts\run_revision_checks.py --output revision_support/reproduced`.

The runner imports this checkout through `PYTHONPATH`, runs the three unittest suites, and records a scripted console demonstration. It exits nonzero if a suite fails, the expected test count changes, or the demo does not complete with the expected events. The output folder contains logs, a demo record and a manifest with the environment, source hashes and results. The default output folder preserves the bundled evidence; choosing a previously used output folder replaces its corresponding evidence files.

The setup command is the supported installation route. The bundled revision checks used an existing Python environment with NumPy; their success does not demonstrate a fresh dependency installation or the desktop GUI.

## Individual commands

After an editable installation, the tests can also be run independently:

```sh
.venv/bin/python -m unittest discover -s tests -p test_regressions.py -v
.venv/bin/python -m unittest discover -s tests -p test_installation.py -v
.venv/bin/python -m unittest discover -s tests -p test_revision_validation.py -v
.venv/bin/python scripts/capture_demo.py --output revision_support/reproduced/scripted_record.json
```

Without an editable installation, set `PYTHONPATH=src` before the unittest commands, or use the runner, which sets it automatically. The recorder locates the checkout itself.

## What the added tests establish

| Check | Controlled input and expected behavior |
| --- | --- |
| Streaming parser | All 40 two-chunk splits of the 39-character tagged example produce one cleaned sentence, Happy at offset 0 and Nod at offset 10. |
| Motor arbitration (six tests) | One mixer tick verifies mean offsets, predicted-pose priority, subsequent expression bias, manual override priority, clamping and slew limiting. Hardware writes are collected in memory. |
| Synthetic speech timeline | A constructed PCM signal has an active interval from 0.2 to 1.2 seconds; word-length weights place the second word at 0.6 seconds. |
| Playback marker order | A controlled playback clock dispatches Nod before Blink. |
| Interruption | A stop request at controlled time 0.2 seconds selects the estimated 0.5-second boundary and suppresses the later marker. |

The two-turn console demonstration produces three sentences (each with a `spoken` and a `done` event), three action events and two expression events. These are software event counts, not gesture-recognition or physical-motion measurements.

## Limits

The synthetic timing result does not measure alignment against recorded speech. The interruption result does not measure wall-clock or physical stop latency, and it does not demonstrate cancellation of an already dispatched gesture. The tests do not validate LLM tag reliability, speech quality, GUI rendering, optional trained models, participant outcomes or transfer from virtual to physical embodiment. The original optional server/C# checks remain available but were not rerun as part of this evidence package.
