"""Evidence probes for the supplied snapshot; no hardware or cloud services.
Run: python reproduce_checks.py /path/to/engine-root
Requires Python >=3.12 and NumPy. Does not modify the source checkout.
Failures recorded here are known limitations, not expected functionality.
"""
import ast
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'src'))
sys.dont_write_bytecode = True
from obot.core.processor import StreamProcessor
from obot.core.orchestrator import RobotPipeline
from obot.core.interrupt import InterruptController
from obot.speech.timeline import build_timeline, envelope
import numpy as np

files = sorted(p for folder in ('src', 'scripts', 'tests', 'checks', 'mlBehaviour')
               for p in (root / folder).rglob('*.py')
               if '__pycache__' not in p.parts)
syntax_errors = []
for p in files:
    try:
        ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p.relative_to(root)))
    except Exception as e:
        syntax_errors.append([str(p.relative_to(root)), str(e)])

def parse(chunks):
    p = StreamProcessor()
    result = []
    for chunk in chunks:
        result.extend(p.feed(chunk))
    result.extend(p.flush())
    return [e.to_dict() for e in result]

async def interruption_probe():
    interrupt = InterruptController()
    class Source:
        async def stream_response(self, prompt):
            yield 'First sentence has several words. Second sentence.'
        def register_interruption(self, spoken, unspoken):
            self.registered = {'spoken': spoken, 'unspoken': unspoken}
    class Speaker:
        emitted = []
        def prepare_sentence(self, sentence): pass
        def turn_finished(self): pass
        async def stop_speaking(self): pass
        async def set_emotion(self, emotion): pass
        async def speak_sentence(self, sentence, markers, on_marker):
            self.emitted.append(sentence.split()[0])
            interrupt.trigger('keyboard')
            await interrupt.wait()
    source, speaker = Source(), Speaker()
    result = await RobotPipeline(source, speaker).run('', interrupt)
    return {'fake_speaker_emitted': speaker.emitted, 'pipeline_result': asdict(result)}

env_results = {}
for n in [0,100,320]:
    try:
        e = envelope(np.zeros(n, dtype=np.int16), 16000, 50)
        env_results[str(n)] = {'result': e.tolist()}
    except Exception as e:
        env_results[str(n)] = {'exception': type(e).__name__, 'message': str(e)}
timeline = build_timeline('hello world', np.ones(16000, dtype=np.int16), 16000)
command = [sys.executable, '-B', '-m', 'obot', '--console', '--text',
           'Hello [Nod] (Happy) friend. Goodbye [Blink].']
env = dict(os.environ, PYTHONPATH=str(root/'src'), PYTHONDONTWRITEBYTECODE='1')
run = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
report = {
    'python': platform.python_version(), 'platform': platform.platform(),
    'numpy': np.__version__,
    'source_files':len(files),'syntax_errors':syntax_errors,
    'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    'console': {'exit_code':run.returncode, 'stdout':run.stdout, 'stderr':run.stderr},
    'running_example_events':parse(['Hello [Nod] (Happy) friend. Goodbye [Blink].']),
    'delay_single_chunk':parse(['Hello !Delay500 world.']),
    'delay_split_chunk':parse(['Hello !','Delay500 world.']),
    'delay_at_eof':parse(['Hello !Delay500']),
    'interruption':asyncio.run(interruption_probe()),
    'timeline':{'words':[asdict(w) for w in timeline.words],
                'insertion_position_5_maps_to_seconds':timeline.time_for_char(5)},
    'envelope_samples':env_results,
    'not_tested':['hardware','GUI','actual audio output','microphone','cloud backends','model inference','server suite'],
}
print(json.dumps(report,indent=2))
