"""Record a typed conversation through the engine; default is scripted console.

Use --provider gemini/ollama and an explicit --model for a live model run.
The JSON records software output, not what a person heard or a motor achieved.
"""
import argparse
import asyncio
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from obot.config import Config
from obot.core import events
from obot.core.interrupt import InterruptController
from obot.core.orchestrator import RobotPipeline
from obot.core.processor import StreamProcessor
from obot.llm.client import ScriptedLLMClient
from obot.robot.controller import ConsoleObotController, HardwareObotController, VirtualObotController


async def run(args):
    config_data = json.loads(args.config.read_text())
    cfg = Config.from_dict(config_data)
    # Keep this reference example attributable to reply labels.
    cfg.speech.gesture.enabled = False
    for value in vars(cfg.behaviors).values():
        if hasattr(value, 'enabled'):
            value.enabled = False
    prompt = (ROOT / 'system_prompt.txt').read_text()
    cases = json.loads(args.inputs.read_text())
    started = time.monotonic()
    lock = threading.Lock()
    log = []

    def record(topic, data):
        with lock:
            log.append({'t_s': time.monotonic() - started, 'topic': topic, 'data': data})

    report = {
        'status': 'running', 'provider': args.provider, 'model': args.model,
        'live_model': args.provider != 'scripted', 'controller': args.controller,
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'environment': {'python': platform.python_version(), 'os': platform.platform()},
        'system_prompt': prompt,
        'system_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'inputs_sha256': hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
        'settings': {'speech': cfg.speech.to_dict(), 'motion': cfg.motion.to_dict(),
                     'background_movements': False, 'manual_overrides': False},
        'scope': 'Typed input. No microphone or desktop UI. Events record software commands; attach audio/video to establish physical output.',
        'turns': [], 'events': log,
    }
    controller = None
    unsubscribers = [events.subscribe(topic, record) for topic in
                    (events.SPEECH, events.ACTION, events.EMOTION, events.JOINTS, events.LOG, events.ERROR)]
    try:
        with ExitStack() as stack:
            if args.provider == 'gemini':
                if not cfg.gemini_api_key or not args.model:
                    raise ValueError('Gemini requires an API key in the private config and --model.')
                from obot.llm.gemini import GeminiLLMClient
                client = GeminiLLMClient(cfg.gemini_api_key, args.model, prompt)
            elif args.provider == 'ollama':
                if not args.model:
                    raise ValueError('Ollama requires --model. Configure a local server or remote SSH access.')
                from obot.llm.ollama import OllamaLLMClient
                from obot.net.ssh_tunnel import open_ollama_tunnel
                port = stack.enter_context(open_ollama_tunnel(cfg.ollama_ssh))
                client = OllamaLLMClient(f'http://127.0.0.1:{port}', args.model, prompt)
            else:
                client = None

            if args.controller == 'console':
                controller = ConsoleObotController()
            elif args.controller == 'virtual':
                controller = VirtualObotController(speech_settings=cfg.speech,
                    motion_settings=cfg.motion, gemini_api_key=cfg.gemini_api_key)
            else:
                controller = HardwareObotController(port=cfg.ohbot_port,
                    speech_settings=cfg.speech, motion_settings=cfg.motion, gemini_api_key=cfg.gemini_api_key)

            for case in cases:
                source = client or ScriptedLLMClient(case['scripted_reply'], chunk_size=7)
                turn = {'input': case['input'], 'raw_chunks': [], 'parsed': []}

                class RecordedSource:
                    async def stream_response(self, user_input):
                        async for chunk in source.stream_response(user_input):
                            turn['raw_chunks'].append(chunk)
                            record('raw_text', chunk)
                            yield chunk

                    def register_interruption(self, spoken, unspoken):
                        source.register_interruption(spoken, unspoken)

                class RecordedProcessor(StreamProcessor):
                    def feed(self, text):
                        result = super().feed(text)
                        turn['parsed'].extend(event.to_dict() for event in result)
                        return result

                    def flush(self):
                        result = super().flush()
                        turn['parsed'].extend(event.to_dict() for event in result)
                        return result

                report['turns'].append(turn)
                interrupt = InterruptController()
                timer = None
                if args.stop_after is not None:
                    timer = asyncio.get_running_loop().call_later(args.stop_after, interrupt.trigger, 'keyboard')
                try:
                    result = await RobotPipeline(RecordedSource(), controller,
                        processor=RecordedProcessor()).run(case['input'], interrupt)
                    turn['result'] = asdict(result)
                finally:
                    if timer is not None:
                        timer.cancel()
            report['status'] = 'completed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error_type'] = type(exc).__name__
        # Do not persist provider error strings, which can contain request credentials.
        raise
    finally:
        if controller is not None:
            controller.close()
        for unsubscribe in unsubscribers:
            unsubscribe()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['scripted', 'gemini', 'ollama'], default='scripted')
    parser.add_argument('--model', default='')
    parser.add_argument('--controller', choices=['console', 'virtual', 'hardware'], default='console')
    parser.add_argument('--config', type=Path, default=ROOT / 'examples/config.reference.json')
    parser.add_argument('--inputs', type=Path, default=ROOT / 'examples/demo-inputs.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'demo-record.json')
    parser.add_argument('--stop-after', type=float, help='Request a stop this many seconds after each turn starts.')
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
