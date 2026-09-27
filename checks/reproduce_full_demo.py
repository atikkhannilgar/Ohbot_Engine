from pathlib import Path
from collections import Counter
import subprocess,sys,os,json,re,hashlib,time
repo=Path(sys.argv[1]).resolve()
out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
source=repo/'example_script.txt'
script=' '.join(line.strip() for line in source.read_text().splitlines() if line.strip() and not line.strip().startswith('#'))
env=os.environ.copy();env['PYTHONPATH']=str(repo/'src');env['PYTHONDONTWRITEBYTECODE']='1'
start=time.monotonic()
result=subprocess.run([sys.executable,'-m','obot','--console','--text',script],cwd=repo,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=300)
(out/'full-demo-console.txt').write_text(result.stdout)
(out/'full-demo-stderr.txt').write_text(result.stderr)
requested_actions=Counter(re.findall(r'\[([^\]]+)\]',script))
requested_emotions=Counter(re.findall(r'\(([^)]+)\)',script))
actions=Counter(re.findall(r'^\[action\]\[sim\] (.+)$',result.stdout,re.M))
emotions=Counter(re.findall(r'^\[emotion\]\[sim\] (.+)$',result.stdout,re.M))
record={'exit_code':result.returncode,'mode':'console only; no physical robot, microphone, generated audio or model inference','python':sys.version.split()[0],'script_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'requested_actions':dict(requested_actions),'requested_expressions':dict(requested_emotions),'printed_actions':dict(actions),'printed_expressions':dict(emotions),'printed_sentences':len(re.findall(r'^\[speech\]',result.stdout,re.M)),'unknown_actions':re.findall(r'^\[action\] unknown: (.+)$',result.stdout,re.M),'elapsed_wall_seconds':round(time.monotonic()-start,3),'elapsed_note':'Console pacing only; not a timing or robot-performance measurement'}
(out/'full-demo-check.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
