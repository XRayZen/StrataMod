"""Independent scalar expectation. Never a production fallback."""
import hashlib,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t19'
try:import numpy as np
except ModuleNotFoundError:
 sys.path.append('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages');import numpy as np
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def row(p):
 p=Path(p)
 with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h)
def prepare():
 out=BUILD/'q';out.mkdir(exist_ok=True)
 if (out/'manifest.json').exists():raise ValueError('Q already fixed')
 raw=json.loads((ROOT/'build-deepseek-t13/raw-receipt.json').read_text(encoding='utf-8'));old=json.loads((ROOT/'build-deepseek-t13/gather-q-manifest.json').read_text(encoding='utf-8'))
 for x in old['files']:
  if row(x['path'])!=x:raise ValueError('fixed T13 input changed')
 q=load('T19_independent_T04_scalar',ROOT/'Strata-extensions/tests/quant/q_reference.py');bf=load('T19_prior_bf16',ROOT/'Strata-extensions/tests/engram/reference.py')
 rows=[];values=[];bits=[]
 for i,x in enumerate(raw['rows']):
  if row(x['path'])!={k:x[k] for k in ['path','bytes','sha256']}:raise ValueError('raw SHA changed')
  a=q.decode(43,Path(x['path']).read_bytes());b=bf.bf16(a);values.append(a);bits.append(b);rows.append(x)
 np.concatenate(values).astype('<f4').tofile(out/'all-fp32.bin');np.concatenate(bits).astype('<u2').tofile(out/'all-bf16.bin')
 manifest=dict(schema='T19-independent-Q/v1',G_executed=False,rows=rows,expected=[row(out/'all-fp32.bin'),row(out/'all-bf16.bin')],references=[row(HERE/'reference.py'),row(HERE/'contract.json'),row(ROOT/'Strata-extensions/tests/quant/q_reference.py'),row(ROOT/'Strata-extensions/tests/engram/reference.py'),row(ROOT/'build-deepseek-t13/gather-q-manifest.json'),row(ROOT/'build-deepseek-t13/nq-manifest.json')],numpy=np.__version__,counter_trace=json.loads((HERE/'contract.json').read_text())['trace'])
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');return manifest
if __name__=='__main__':prepare()
