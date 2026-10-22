"""T18 independent Q preparation, not a runtime fallback."""
import importlib.util,json,hashlib,sys
from pathlib import Path
try:import numpy as np
except ModuleNotFoundError:
 sys.path.append('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages');import numpy as np
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t18'
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def record(p):return dict(path=str(p),bytes=Path(p).stat().st_size,sha256=sha(p))
def prepare():
 q=load('t18_independent_ordered_q',ROOT/'Strata-extensions/tests/quant/q_reference.py');a=load('t18_final_binding',ROOT/'Strata-extensions/tests/ffn/acquire_fixtures.py')
 contract=json.loads((HERE/'contract.json').read_text(encoding='utf-8'));receipt=json.loads((ROOT/'Strata-extensions/tests/ffn/fixture-receipts.json').read_text(encoding='utf-8'))
 a.verify_receipt(receipt,receipt['selected_experts'])
 for i in (2,9):a.finalized(i)
 out=BUILD/'q';out.mkdir(exist_ok=True)
 if (out/'manifest.json').exists():raise ValueError('preserve already frozen Q')
 jobs=[];matrices=[]
 for idx,select in enumerate(contract['matrix_selection']):
  row=next(x for x in receipt['fixtures'] if x['tensor']==select['tensor'] and x['index']==select['expert']);matrices.append(row)
  raw=Path(row['fixture_path']).read_bytes();k,rows=row['dims_ggml'][:2];weights=q.decode(row['type_id'],raw).reshape(rows,k)
  for batch in contract['batches']:
   x=(((np.arange(batch*k,dtype=np.int64)*17)%255-127).astype(np.float32)/np.float32(8192)).reshape(batch,k)
   expected=q.ordered(weights,x);ip=out/f'm{idx}-B{batch}-input.bin';op=out/f'm{idx}-B{batch}-expected.bin';x.astype('<f4').tofile(ip);expected.astype('<f4').tofile(op)
   jobs.append(dict(matrix=idx,batch=batch,input=record(ip),expected=record(op),rows=rows,k=k));print(f'Q m{idx} B{batch}',flush=True)
 manifest=dict(schema='t18-Q/v1',G_executed=False,contract=record(HERE/'contract.json'),references=[record(HERE/'reference.py'),record(ROOT/'Strata-extensions/tests/quant/q_reference.py')],matrices=matrices,jobs=jobs,numpy_version=np.__version__,inputs_FP32=True,BF16_exact=False)
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
 if not any(m['index']==38 and m['absolute_offset']==5051106880 for m in matrices):raise ValueError('expert38 >4GiB provenance')
 return manifest
if __name__=='__main__':prepare()
