"""Run hardware-free review checks and save reproducible evidence.

Run from any directory with Python >=3.12 and NumPy installed. This runner uses
source in this checkout and never launches hardware, a GUI, or a live model.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'revision_support' / 'reproduced',
                        help='Evidence directory; default preserves the bundled records.')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error('Use Python 3.12 or newer.')
    try:
        import numpy
    except ImportError:
        parser.error('NumPy is required; use the console setup profile first.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'src') + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    checks = []
    for name, filename, expected, logfile in [
        ('existing_regression', 'test_regressions.py', 20, 'regression.log'),
        ('installation', 'test_installation.py', 4, 'installation.log'),
        ('additional_revision', 'test_revision_validation.py', 10, 'revision_validation.log'),
    ]:
        command = ['-m', 'unittest', 'discover', '-s', 'tests', '-p', filename, '-v']
        result = subprocess.run([sys.executable, *command], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (output / logfile).write_text(result.stdout, encoding='utf-8')
        match = re.search(r'Ran (\d+) tests? in ', result.stdout)
        count = int(match.group(1)) if match else 0
        passed = result.returncode == 0 and count == expected
        checks.append({'name': name, 'command': ['python', *command], 'log': logfile,
                       'tests': count, 'expected_tests': expected, 'returncode': result.returncode, 'passed': passed})
        print(f'{name}: {count}/{expected} tests; {"PASS" if passed else "FAIL"}', flush=True)
    record_path = output / 'scripted_record.json'
    command = ['scripts/capture_demo.py', '--output', str(record_path)]
    result = subprocess.run([sys.executable, *command], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (output / 'scripted_record.log').write_text(result.stdout, encoding='utf-8')
    demo = {'returncode': result.returncode, 'passed': False}
    if result.returncode == 0 and record_path.exists():
        record = json.loads(record_path.read_text(encoding='utf-8'))
        counts = Counter(e['topic'] for e in record['events'])
        speech = Counter(e['data'].get('event') for e in record['events'] if e['topic'] == 'speech')
        demo.update(status=record['status'], turns=len(record['turns']), events=dict(counts), speech_events=dict(speech))
        demo['passed'] = (record['status'] == 'completed' and not record['live_model']
                          and record['controller'] == 'console' and len(record['turns']) == 2
                          and speech['spoken'] == 3 and speech['done'] == 3
                          and counts['action'] == 3 and counts['emotion'] == 2)
    all_passed = all(c['passed'] for c in checks) and demo['passed']
    paths = ['src/obot/core/processor.py', 'src/obot/core/orchestrator.py',
             'src/obot/robot/controller.py', 'src/obot/speech/engine.py', 'src/obot/speech/timeline.py',
             'tests/test_regressions.py', 'tests/test_installation.py', 'tests/test_revision_validation.py',
             'scripts/run_revision_checks.py', 'scripts/capture_demo.py', 'system_prompt.txt',
             'examples/demo-inputs.json', 'examples/config.reference.json']
    report = {
        'verification_date': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'numpy': numpy.__version__, 'platform': platform.platform(),
        'scope': 'Hardware-free software checks using synthetic PCM, a controlled playback clock and a controlled mixer tick. No live LLM, physical robot, microphone, desktop GUI or acoustic timing measurement. No fresh dependency installation.',
        'results': {**{c['name']: c['tests'] for c in checks}, 'all_passed': all_passed},
        'checks': checks, 'scripted_demo': demo,
        'hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths},
    }
    (output / 'validation_manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'Scripted console demo: {"PASS" if demo["passed"] else "FAIL"}', flush=True)
    print('All checks passed.' if all_passed else 'Checks failed; inspect the saved logs.', flush=True)
    return 0 if all_passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
