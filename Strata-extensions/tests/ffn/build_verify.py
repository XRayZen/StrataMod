"""T11 staged expectation preparation/build/parity, never normal runtime gate."""
import argparse,hashlib,importlib.util,json,subprocess,sys
import copy,os,re,shutil,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t11';HERE=Path(__file__).resolve().parent

def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def prepare():
 q=load('t11_independent_q',HERE/'reference.py');a=load('t11_extract_binding',HERE/'acquire_fixtures.py');contract=json.loads((HERE/'contract.json').read_text());receipt=json.loads((HERE/'fixture-receipts.json').read_text());a.verify_receipt(receipt,contract['selected_experts'])
 expected=BUILD/'q';expected.mkdir(exist_ok=True)
 if (expected/'manifest.json').exists():raise ValueError('Q expected manifest already frozen; preserve prior trial before changing it')
 cache={}
 for row in range(2):
  for mask in (False,True):
   print(json.dumps(dict(event='Q row',input=row,image_bias=mask)),flush=True);cache[(row,mask)]=q.expected_row(row,mask,receipt)
 jobs=[]
 for batch in (1,2,4,8):
  for mask in (False,True):
   starts=range(2) if batch==1 else (0,)
   for start in starts:
    rows=[(start+i)%2 for i in range(batch)];masks=[mask]*batch;name=f'B{batch}-start{start}-vl{int(mask)}';directory=expected/name;directory.mkdir(exist_ok=True);traces=q.assemble_batch(rows,masks,cache);outputs=[]
    for key,array in sorted(traces.items()):
     path=directory/(key+'.bin');array.astype(array.dtype.newbyteorder('<')).tofile(path)
     compare='ulp2' if key.endswith('_silu') or key=='scores' else 'bits'
     outputs.append(dict(name=key,path=str(path),sha256=sha(path),bytes=path.stat().st_size,dtype=array.dtype.str,shape=list(array.shape),compare=compare))
    jobs.append(dict(name=name,batch=batch,input_rows=rows,image_bias=masks,outputs=outputs))
 manifest=dict(schema='strata-t11-q-expectations/v1',scope='independent Q native operator stage expectations; no G source/output used',contract=dict(path=str(HERE/'contract.json'),sha256=sha(HERE/'contract.json')),receipt=dict(path=str(HERE/'fixture-receipts.json'),sha256=sha(HERE/'fixture-receipts.json')),references=[dict(path=str(p),sha256=sha(p)) for p in [HERE/'reference.py',EXT/'tests/quant/q_reference.py',EXT/'tests/numerics/reference.py']],jobs=jobs,G_executed=False)
 save(expected/'manifest.json',manifest);print(json.dumps(dict(event='Q frozen',jobs=len(jobs),manifest_sha256=sha(expected/'manifest.json'))),flush=True)
BUNDLE=BUILD/'bundle-r3'
EXE=BUNDLE/'t11-ffn.exe'
COMPILED=[EXT/'models/deepseek41'/n for n in ('ffn.hpp','ffn.hip')]+[HERE/'ffn_fixture.cpp']
RECIPES=[HERE/n for n in ('CMakeLists.txt','reference.py','contract.json','acquire_fixtures.py','fixture-receipts.json','build_verify.py')]
DEPS=[EXT/'native/quant'/n for n in ('quant.hpp','quant.hip')]+[EXT/'native/stats'/n for n in ('measurement.hpp','measurement.cpp')]+[EXT/'native/artifact'/n for n in ('native_reader.hpp','native_reader.cpp')]+[EXT/'models/deepseek41'/n for n in ('artifact.hpp','artifact.cpp','reference-config.json')]+[ROOT/'include/strata/artifact'/n for n in ('dequant.hpp','gguf_reader.hpp','gguf_split.hpp','model_family.hpp')]+[ROOT/'include/strata/core/geometry.hpp',EXT/'tests/quant/q_reference.py',EXT/'native/artifact/acquire.py',EXT/'native/artifact/gguf.py',EXT/'native/artifact/full_acquire.py']
def record(path):return dict(path=str(path),bytes=Path(path).stat().st_size,sha256=sha(path))
def records(paths):return [record(p) for p in paths]
def aggregate(items):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n' for r in items).encode()).hexdigest()
def run(command,env=None,check=True,timeout=600):
 r=subprocess.run(list(map(str,command)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
 if check and r.returncode:raise RuntimeError(str(command)+'\n'+r.stdout+r.stderr)
 return r

def q_binding():
 path=BUILD/'q/manifest.json';m=json.loads(path.read_text());contract=json.loads((HERE/'contract.json').read_text());receipt=json.loads((HERE/'fixture-receipts.json').read_text())
 if m.get('schema')!='strata-t11-q-expectations/v1' or m.get('G_executed') is not False or m['contract']!=dict(path=str(HERE/'contract.json'),sha256=sha(HERE/'contract.json')) or m['receipt']!=dict(path=str(HERE/'fixture-receipts.json'),sha256=sha(HERE/'fixture-receipts.json')):raise ValueError('Q origin binding')
 for row in m['references']:
  if sha(row['path'])!=row['sha256']:raise ValueError('Q reference changed')
 load('t11_local_raw_preflight',HERE/'acquire_fixtures.py').verify_receipt(receipt,contract['selected_experts'])
 expected_jobs={(b,start,mask) for b in (1,2,4,8) for mask in (False,True) for start in (range(2) if b==1 else (0,))};observed=set()
 for job in m['jobs']:
  batch=job['batch'];mask=job['image_bias'];rows=job['input_rows']
  if type(batch) is not int or any(type(x) is not bool for x in mask) or any(type(x) is not int for x in rows) or len(rows)!=batch or len(mask)!=batch or any(x!=mask[0] for x in mask):raise ValueError('Q job schema')
  key=(batch,rows[0],mask[0])
  if key in observed or rows!=[(rows[0]+i)%2 for i in range(batch)]:raise ValueError('Q duplicate/input selection')
  observed.add(key);names=set()
  for output in job['outputs']:
   name=output['name']
   if name in names:raise ValueError('duplicate Q stage')
   names.add(name)
   if not isinstance(output['shape'],list) or len(output['shape'])!=2 or any(type(x) is not int or x<=0 for x in output['shape']):raise ValueError('Q output shape')
   dtype=np.dtype(output['dtype']);size=int(np.prod(output['shape']))*dtype.itemsize
   if type(output['bytes']) is not int or output['bytes']!=size or Path(output['path']).stat().st_size!=size or sha(output['path'])!=output['sha256']:raise ValueError('Q output identity')
  if not {'input','logits','scores','corrected','ids','weights','routed','shared_hidden','combine','output'}<=names:raise ValueError('Q stage coverage')
 if observed!=expected_jobs:raise ValueError('Q job coverage')
 return m

def environment():
 shared=Path('C:/Develop/AI/StrataMod');sdk=shared/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel';vc=shared/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=shared/'.vision-toolchain/winsdk';inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
 tools=dict(clang=sdk/'lib/llvm/bin/clang++.exe',cmake=shared/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',ninja=shared/'.vision-venv-10.1/Scripts/ninja.exe',linker=vc/'bin/Hostx64/x64/link.exe',dumpbin=vc/'bin/Hostx64/x64/dumpbin.exe',rc=wb/'rc.exe',mt=wb/'mt.exe',objdump=sdk/'lib/llvm/bin/llvm-objdump.exe')
 env=os.environ.copy();temp=BUILD/'tmp';temp.mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(temp);env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']));env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',sdk/'lib']));env['PATH']=os.pathsep.join(map(str,[sdk/'bin',sdk/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')]));env['HIP_PATH']=env['ROCM_PATH']=str(sdk);env['HIP_PLATFORM']='amd';return sdk,tools,env

def numpy_files():
 return records(sorted({Path(m.__file__) for name,m in sys.modules.items() if name.startswith('numpy') and getattr(m,'__file__',None) and Path(m.__file__).is_file()}))
CAPTURE_RECIPE_SHA='c0d6b25197f5da30bc1c6ce3101ca804d459bdf9c1a808bb81156f3a2b429c4c'
REPLAY=False

def manifest_identity(path,expected):
 if sha(path)!=expected:raise ValueError('disk trial manifest changed')

def bundle_binding(m,manifest_sha):
 manifest_identity(BUNDLE/'manifest.json',manifest_sha)
 expected_recipes=records(RECIPES)
 if REPLAY:
  captured=next(r for r in m['recipes'] if Path(r['path'])==Path(__file__))
  if captured['sha256'] not in (CAPTURE_RECIPE_SHA,sha(Path(__file__))):raise ValueError('unexpected captured runner')
  expected_recipes=[captured if Path(r['path'])==Path(__file__) else r for r in expected_recipes]
 if m['compiled']!=records(COMPILED) or m['recipes']!=expected_recipes or m['dependencies']!=records(DEPS) or m['compiled_id']!=aggregate(records(COMPILED)):raise ValueError('trial source binding changed')
 if run(['git','rev-parse','HEAD']).stdout.strip()!='477ac13cbe8e582c20484871ce459d20d82df09d' or run(['git','diff','--name-only','HEAD']).stdout.strip():raise ValueError('fixed upstream changed')
 for key in ('compiled','recipes','dependencies','inputs','bundle_files','numpy','tools'):
  for row in m[key]:
   if REPLAY and key=='recipes' and Path(row['path'])==Path(__file__):continue
   if Path(row['path']).stat().st_size!=row['bytes'] or sha(row['path'])!=row['sha256']:raise ValueError('bound file changed: '+key)
 if record(EXE)!=m['artifact'] or json.loads(run([EXE,'--identity']).stdout)['source_id']!=m['compiled_id']:raise ValueError('compiled artifact identity')
 if record(BUILD/'q/manifest.json')!=m['q_manifest']:raise ValueError('Q manifest changed')
 q_binding()

def cpu_checks():
 q=load('t11_cpu_nq_checks',HERE/'reference.py');contract=json.loads((HERE/'contract.json').read_text());qm=q_binding();directory=BUILD/'cpu-negative';directory.mkdir(exist_ok=True);count=0
 values=np.array([[float(r['source']) for r in contract['N']]],np.float32)
 _,_,scores,_=q.router_scores(values,np.zeros(values.shape[1],np.float32));_,g,u,silu=q.swiglu(values,values)
 for field,actual,policy in [('sqrtsoftplus_fp32_le',scores,'ulp2'),('clamp_gate_fp32_le',g,'bits'),('clamp_up_fp32_le',u,'bits'),('silu_fp32_le',silu,'ulp2')]:
  expected=directory/(field+'-N.bin');observed=directory/(field+'-Q.bin');expected.write_bytes(b''.join(bytes.fromhex(r[field]) for r in contract['N']));actual.astype('<f4').tofile(observed);compare(observed,expected,'<f4',policy);count+=1
 e=directory/'finite-expected.bin';a=directory/'observed.bin';np.array([1.,-0.],'<f4').tofile(e)
 for raw in [e.read_bytes()+b'x',e.read_bytes()[:-1],np.array([np.inf,-0.],'<f4').tobytes(),np.array([1.,0.],'<f4').tobytes(),np.array([0.,-0.],'<f4').tobytes()]:
  a.write_bytes(raw)
  try:compare(a,e,'<f4','ulp2')
  except ValueError:count+=1
  else:raise ValueError('bad stage output accepted')
 observable={'route-after-cast':False,'double-route':False,'skip-down-QDQ':False}
 for job in qm['jobs'][:4]:
  outputs={o['name']:o for o in job['outputs']}
  def array(name):
   row=outputs[name];return np.fromfile(row['path'],row['dtype']).reshape(row['shape'])
  ids=array('ids')[0];weights=array('weights')[0]
  for slot,expert in enumerate(ids):
   name='e'+str(int(expert));silu=array(name+'_silu');up=array(name+'_clamp_up');correct=array(name+'_hidden');route=weights[slot]
   late=q.bf16(np.multiply(q.bf16(np.multiply(silu,up,dtype=np.float32)),route,dtype=np.float32))
   observable['route-after-cast']|=correct.tobytes()!=late.tobytes()
   observable['double-route']|=correct.tobytes()!=q.bf16(np.multiply(correct,route,dtype=np.float32)).tobytes()
   observable['skip-down-QDQ']|=correct.tobytes()!=array(name+'_down_qdq').tobytes()
 if not all(observable.values()):raise ValueError('real stage fixtures do not expose approved cast/QDQ faults')
 return dict(N_to_Q_literal_cases=4,comparison_negative_cases=count-4,semantic_fault_observability=observable)

def expected_atomic(job,receipt):
 lookup={(r['tensor'],r['index']):r for r in receipt['fixtures']};idsrow=next(o for o in job['outputs'] if o['name']=='ids');ids=np.fromfile(idsrow['path'],idsrow['dtype']).reshape(idsrow['shape']);result=[]
 def add(role,expert,batch):
  if role=='router':tensor='blk.0.ffn_gate_inp.weight';key=None
  elif role.startswith('shared_'):tensor='blk.0.ffn_'+role[7:]+'_shexp.weight';key=None
  else:tensor='blk.0.ffn_'+role+'_exps.weight';key=expert
  r=lookup[(tensor,key)];left=batch
  while left:
   chunk=8
   while chunk>left:chunk//=2
   rows,k=r['dims_ggml'][1],r['dims_ggml'][0];raw=r['bytes'];inp=chunk*k*4;out=chunk*rows*4
   result.append([role,str(expert),str(r['type_id']),str(rows),str(k),str(chunk),Path(r['source']['path']).as_posix(),str(r['absolute_offset']),str(raw),str(inp),str(out),str(raw+inp+out)]);left-=chunk
 add('router',0,job['batch'])
 for expert in sorted(set(ids.reshape(-1).tolist())):
  batch=int(np.sum(np.any(ids==expert,axis=1)))
  for role in ('gate','up','down'):add(role,expert,batch)
 for role in ('shared_gate','shared_up','shared_down'):add(role,0,job['batch'])
 return result

def prepare_boundaries():
 q=load('t11_boundary_independent_q',HERE/'reference.py');directory=BUILD/'boundary-q';directory.mkdir(exist_ok=True)
 if (directory/'manifest.json').exists():raise ValueError('preserve fixed boundary expectation')
 casts=np.resize(np.array([1+1/256,1+3/256,-1-1/256,-0.,2**-126,2**-133],np.float32),32).reshape(1,32)
 act=np.zeros((5,32),np.float32);act[0,1]=-0.;act[1]=np.float32(2**-25);act[1,0]=-np.float32(2**-30)
 act[2,:8]=[448,1.0625,1.1875,-1.0625,1/1024,3/1024,-1/1024,-3/1024];act[3,0]=224;act[4,0]=226
 logits=np.zeros((3,384),np.float32);logits[0,:12]=[-100,-20,-1,0,1,10,np.nextafter(np.float32(20),np.float32(-np.inf)),20,np.nextafter(np.float32(20),np.float32(np.inf)),21,80,100]
 # Exact all-equal rounded-score tie plus a one-FP32-ULP bias difference.
 bias=np.zeros(384,np.float32);bias_vl=np.zeros(384,np.float32);bias_vl[7]=np.spacing(np.float32(np.sqrt(np.float32(np.log(2)))))
 logits[2,:8]=[0,0,0,0,0,0,0,0];logits[2,8:]=-20
 values=np.array([-20,-10,-1,-0.,0.,1,9.9375,10,10.0625,20],np.float32);gate=np.resize(values,2304).reshape(1,2304);up=np.resize(values[::-1],2304).reshape(1,2304);route=np.array([[.3]],np.float32)
 inputs=dict(cast=casts,act=act,logits=logits,bias=bias,bias_vl=bias_vl,gate=gate,up=up,route=route)
 output={};output['cast']=q.bf16(casts);output['act_qdq'],output['act_scales'],output['act_codes']=q.act_qdq(act)
 # Independent literal bit/code facts qualify the helper oracle itself.
 if output['act_scales'].reshape(-1).tolist()!=[105,105,127,126,127] or output['act_codes'][2,:8].tolist()!=[126,56,58,184,0,2,128,130] or np.any(output['act_codes'][0,[0,2,3]]):raise ValueError('boundary literal FP8 oracle')
 ids=[];weights=[];scores=[];corrected=[]
 for i in range(3):
  a,b,c,d=q.router_scores(logits[i:i+1],bias_vl if i==1 else bias);ids.append(a);weights.append(b);scores.append(c);corrected.append(d)
 output.update(ids=np.concatenate(ids),weights=np.concatenate(weights),scores=np.concatenate(scores),corrected=np.concatenate(corrected))
 if output['ids'][1].tolist()!=[7,0,1,2,3,4] or output['ids'][2].tolist()!=list(range(6)):raise ValueError('boundary tie oracle')
 hidden,g,u,silu=q.swiglu(gate,up,route);output.update(boundary_clamp_gate=g,boundary_clamp_up=u,boundary_silu=silu,boundary_hidden=hidden)
 def write(name,array):
  path=directory/(name+'.bin');array.astype(array.dtype.newbyteorder('<')).tofile(path);return dict(name=name,**record(path),dtype=array.dtype.str,shape=list(array.shape))
 inrows=[write('input-'+name,a) for name,a in inputs.items()]
 # Native reads fixed names; use a separate input folder and bind those actual files.
 nativein=directory/'inputs';nativein.mkdir()
 for name,a in inputs.items():a.astype('<f4').tofile(nativein/(name+'.bin'))
 outs=[dict(write(name,a),compare='ulp2' if name in ('scores','boundary_silu') else 'bits') for name,a in output.items()]
 manifest=dict(schema='strata-t11-controlled-boundaries/v1',scope='synthetic boundary only, never learned-weight qualification',G_executed=False,reference=record(HERE/'reference.py'),literal_contract=record(HERE/'contract.json'),inputs=records(sorted(nativein.glob('*.bin'))),outputs=outs,literals=dict(scales=[105,105,127,126,127],midpoint_codes=[126,56,58,184,0,2,128,130],tie_ids=[7,0,1,2,3,4],near_tie_ids=list(range(6))))
 save(directory/'manifest.json',manifest);print(json.dumps(dict(boundary_Q_frozen=sha(directory/'manifest.json'))))

def boundary_binding():
 path=BUILD/'boundary-q/manifest.json';m=json.loads(path.read_text())
 if m['G_executed'] is not False or m['reference']!=record(HERE/'reference.py') or m['literal_contract']!=record(HERE/'contract.json'):raise ValueError('boundary origin')
 for row in m['inputs']+m['outputs']:
  if Path(row['path']).stat().st_size!=row['bytes'] or sha(row['path'])!=row['sha256']:raise ValueError('boundary fixed data changed')
 return m

def compare_boundaries(out,native,m):
 if native.get('source_id')!=m['compiled_id'] or type(native.get('stages')) is not int or native['stages']!=12 or type(native.get('actual_scratch_peak')) is not int or native['actual_scratch_peak']<=0 or native.get('cleanup_unknown') is not False or native.get('learned_weight_qualification') is not False:raise ValueError('boundary native metadata')
 expected=boundary_binding();metadata=[line.split('\t') for line in (out/'stages.tsv').read_text().splitlines()]
 if len(metadata)!=len(expected['outputs']) or {r[0] for r in metadata}!={r['name'] for r in expected['outputs']}:raise ValueError('boundary stage coverage')
 compared=0;files=[]
 for row in expected['outputs']:
  actual=next(x for x in metadata if x[0]==row['name'])
  if actual[1]!=row['dtype'] or list(map(int,actual[2:4]))!=row['shape'] or int(actual[4])!=row['bytes']:raise ValueError('boundary stage geometry')
  path=out/(row['name']+'.bin');compared+=compare(path,row['path'],row['dtype'],row['compare']);files.append(record(path))
 return dict(compared_values=compared,outputs=files,native=native)

def build():
 qm=q_binding();boundary_binding();sdk,tools,env=environment();BUNDLE.mkdir(exist_ok=True)
 if (BUNDLE/'manifest.json').exists():raise ValueError('fixed trial exists; preserve it before a new build wave')
 identity=aggregate(records(COMPILED));native=BUILD/'cmake-native'
 commands=[[tools['cmake'],'--fresh','-S',HERE,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}',f'-DT11_SOURCE_ID={identity}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,command in enumerate(commands):
  r=run(command,env,False);(BUILD/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise RuntimeError('build failed; see build-'+str(i)+'.log')
 shutil.copy2(native/'bundle/t11-ffn.exe',EXE)
 for name in ('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):shutil.copy2(sdk/'bin'/name,BUNDLE/name)
 notices=BUNDLE/'licenses';notices.mkdir(exist_ok=True)
 for src,name in [(ROOT/'LICENSE','Strata-LICENSE'),(ROOT/'third_party/ggml/LICENSE','ggml-LICENSE'),(EXT/'native/artifact/NOTICE.md','T08-NOTICE.md'),(ROOT/'build-deepseek-t10/bundle-offline-r7/DeepSeek-LICENSE.txt','DeepSeek-LICENSE')]:shutil.copy2(src,notices/name)
 for component in ('amd_comgr','rocm-core'):
  for src in (sdk/'share/doc'/component).rglob('*'):
   if src.is_file() and any(t in src.name.lower() for t in ('license','notice','copying')):
    destination=notices/component/src.name;destination.parent.mkdir(exist_ok=True);shutil.copy2(src,destination)
 inv=json.loads((EXT/'tests/artifact/header-inventory.json').read_text());receipt=json.loads((HERE/'fixture-receipts.json').read_text())
 prefixes=BUILD/'prefixes.tsv';prefixes.write_text(''.join(str(s['bytes'])+'\t'+s['prefix_path']+'\n' for s in inv['shards']),encoding='utf-8');sources=BUILD/'sources.tsv';shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',sources)
 weight_table=BUILD/'weights.tsv';weight_table.write_text(''.join('\t'.join(str(x) for x in [r['tensor'],-1 if r['index'] is None else r['index'],r['absolute_offset'],r['bytes'],r['type_id'],r['fixture_path']])+'\n' for r in receipt['fixtures']),encoding='utf-8')
 q=load('t11_fixed_inputs',HERE/'reference.py');jobs=[]
 for job in qm['jobs']:
  path=BUILD/(job['name']+'-input.bin');q.fixed_inputs()[job['input_rows']].astype('<f4').tofile(path);jobs.append('\t'.join(map(str,[job['name'],job['batch'],int(job['image_bias'][0]),path,sha(path)])))
 job_table=BUILD/'jobs.tsv';job_table.write_text('\n'.join(jobs)+'\n',encoding='utf-8')
 inputs=list((BUILD/'boundary-q').rglob('*.bin'))+[BUILD/'boundary-q/manifest.json']+[prefixes,sources,weight_table,job_table,BUILD/'q/manifest.json']+[Path(s['prefix_path']) for s in inv['shards']]+[Path(r['fixture_path']) for r in receipt['fixtures']]+[Path(o['path']) for job in qm['jobs'] for o in job['outputs']]+list(BUILD.glob('B*-input.bin'))+[EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json']
 imports=run([tools['dumpbin'],'/DEPENDENTS',EXE],env).stdout;(BUILD/'imports.log').write_text(imports,encoding='utf-8');offload=run([tools['objdump'],'--offloading',EXE],env).stdout;(BUILD/'offloading.log').write_text(offload,encoding='utf-8')
 if not all(arch in offload for arch in ('gfx1100','gfx1201')):raise ValueError('both compiled arch images required')
 manifest=dict(schema='strata-t11-fixed-native-trial/v1',compiled=records(COMPILED),compiled_id=identity,recipes=records(RECIPES),dependencies=records(DEPS),artifact=record(EXE),q_manifest=record(BUILD/'q/manifest.json'),inputs=records(inputs),bundle_files=records(sorted(p for p in BUNDLE.rglob('*') if p.is_file())),tools=records(list(tools.values())+[Path(sys.executable)]),numpy=numpy_files(),source_qualified=False,scope='offline operator fixture; engine lifetime/fullmodel unqualified',patches=[])
 save(BUNDLE/'manifest.json',manifest);fixed=sha(BUNDLE/'manifest.json');bundle_binding(manifest,fixed);shape=json.loads(run([EXE,'--shape-selftest'],env).stdout)
 if shape!={'shape_rejected':4,'GPU_used':False}:raise ValueError('native pre-G negative incomplete')
 run([sys.executable,'-B',HERE/'reference.py']);cpu=cpu_checks();bundle_binding(manifest,fixed);save(BUILD/'cpu-build-verification.json',dict(manifest_sha256=fixed,artifact=manifest['artifact'],shape=shape,CPU_checks=cpu,Q_manifest_sha256=manifest['q_manifest']['sha256'],before_after_binding=True,GPU_used=False));print(json.dumps(dict(event='native ready',manifest_sha256=fixed,exe_sha256=sha(EXE),GPU_used=False)))

def compare(actual,expected,dtype,policy):
 data=Path(actual).read_bytes();wanted=Path(expected).read_bytes()
 if len(data)!=len(wanted) or len(data)%np.dtype(dtype).itemsize:raise ValueError('output exact byte length')
 a=np.frombuffer(data,dtype);e=np.frombuffer(wanted,dtype)
 if policy=='bits':
  if data!=wanted:raise ValueError('exact stage mismatch')
 elif policy=='ulp2':
  if dtype!='<f4' or not np.isfinite(a).all() or not np.isfinite(e).all():raise ValueError('nonfinite/dtype nonlinear')
  ab=a.view(np.uint32);eb=e.view(np.uint32)
  if ((e==0)&(ab!=eb)).any():raise ValueError('nonlinear signed zero')
  ai=np.where((ab&0x80000000)!=0,~ab,ab|0x80000000).astype(np.int64);ei=np.where((eb&0x80000000)!=0,~eb,eb|0x80000000).astype(np.int64)
  if (np.abs(ai-ei)>2).any():raise ValueError('nonlinear exceeds fixed2ULP')
 else:raise ValueError('unknown comparison policy')
 return len(a)

def validate_native(native,m,qm,pci):
 if type(native.get('matrix_owned_peak')) is not int or type(native.get('actual_scratch_peak')) is not int or native['actual_scratch_peak']<=0:raise ValueError('strict native peak schema')
 if not isinstance(native.get('jobs'),list) or len(native['jobs'])!=len(qm['jobs']):raise ValueError('native job coverage')
 if native.get('source_id')!=m['compiled_id'] or native.get('pci')!=pci or native.get('source_qualified') is not False or native.get('allocator_context_physical') is not None:raise ValueError('native scope binding')
 for when in ('before','after'):
  status=native.get('hip_memory_'+when+'_status');free=native.get('hip_free_'+when);total=native.get('hip_total_'+when)
  if type(status) is not int:raise ValueError('HIP memory status type')
  if status==0:
   if type(free) is not int or type(total) is not int or free<0 or total<=0 or free>total:raise ValueError('HIP successful memory schema')
  elif free is not None or total is not None:raise ValueError('HIP unknown memory must remain null')
 for job,observed in zip(qm['jobs'],native['jobs'],strict=True):
  if job['name']!=observed.get('name') or type(observed.get('cleanup_unknown')) is not bool or observed['cleanup_unknown'] or any(type(observed.get(k)) is not int or observed[k]<0 for k in ('stages','matrix_owned_peak','actual_scratch_peak','host_matrix_scope_peak','trace_payload_bytes')):raise ValueError('strict job schema')

def check_atomic(atomic,job,receipt):
 if atomic!=expected_atomic(job,receipt):raise ValueError('source/matrix primitive/T34 byte metadata binding')

def verify_outputs(m,qm,native,out,pci):
 validate_native(native,m,qm,pci)
 receipt=json.loads((HERE/'fixture-receipts.json').read_text())
 if native['source_id']!=m['compiled_id'] or native['pci']!=pci or native['source_qualified'] is not False or len(native['jobs'])!=len(qm['jobs']):raise ValueError('native binding/scope')
 outputs=[];compared=0;max_matrix=0
 for job,observed in zip(qm['jobs'],native['jobs'],strict=True):
  if job['name']!=observed['name'] or type(observed.get('cleanup_unknown')) is not bool or observed['cleanup_unknown'] or any(type(observed.get(k)) is not int for k in ('stages','matrix_owned_peak','actual_scratch_peak','host_matrix_scope_peak','trace_payload_bytes')):raise ValueError('job order/cleanup unknown')
  directory=out/job['name'];stages=[line.split('\t') for line in (directory/'stages.tsv').read_text().splitlines()]
  metadata={row[0]:row for row in stages}
  if len(metadata)!=len(stages) or set(metadata)!={o['name'] for o in job['outputs']}:raise ValueError('actual stage coverage')
  for expected in job['outputs']:
   meta=metadata[expected['name']]
   if meta[1]!=expected['dtype'] or list(map(int,meta[2:4]))!=expected['shape'] or int(meta[4])!=expected['bytes']:raise ValueError('actual stage metadata')
   path=directory/(expected['name']+'.bin')
   try:compared+=compare(path,expected['path'],expected['dtype'],expected['compare'])
   except ValueError as e:raise ValueError(job['name']+'/'+expected['name']+': '+str(e)) from e
   outputs.append(record(path))
  atomic=[line.split('\t') for line in (directory/'atomic.tsv').read_text().splitlines()]
  peak=0
  check_atomic(atomic,job,receipt)
  for request in atomic:
   role_name,expert,kind,rows,k,batch=request[:6];kind,rows,k,batch=map(int,(kind,rows,k,batch));raw_bytes=int(request[8]);input_bytes=int(request[9]);output_bytes=int(request[10]);owned=int(request[11]);block_bytes={0:(1,4),8:(32,34),39:(32,17)}[kind];wanted=rows*k//block_bytes[0]*block_bytes[1]
   if raw_bytes!=wanted or input_bytes!=batch*k*4 or output_bytes!=batch*rows*4 or owned!=raw_bytes+input_bytes+output_bytes:raise ValueError('T34 primitive byte ledger mismatch')
   peak=max(peak,owned)
  if peak!=observed['matrix_owned_peak'] or observed['host_matrix_scope_peak']!=peak or observed['stages']!=len(job['outputs']) or not atomic:raise ValueError('matrix peak/coverage')
  max_matrix=max(max_matrix,peak)
 if max_matrix!=12771328 or native['matrix_owned_peak']!=max_matrix or native['actual_scratch_peak']!=491520:raise ValueError('atomic lower bound/scratch actual lifetime')
 loaded=[record(p) for p in native['loaded_modules'] if Path(p).name.lower() in ('amdhip64_7.dll','amd_comgr.dll')]
 if {Path(x['path']).name.lower() for x in loaded}!={'amdhip64_7.dll','amd_comgr.dll'} or any(Path(x['path']).resolve().parent!=BUNDLE.resolve() or x['sha256']!=sha(BUNDLE/Path(x['path']).name) for x in loaded):raise ValueError('loaded HIP module binding')
 return outputs,compared,loaded

def replay_negatives(native,m,qm,pci):
 count=0
 mutations=[lambda n:n.update(jobs=[]),lambda n:n.update(matrix_owned_peak=float(n['matrix_owned_peak'])),lambda n:n['jobs'][0].update(cleanup_unknown=0),lambda n:n.update(hip_memory_before_status=1,hip_free_before=0),lambda n:n.update(hip_free_after=float(n['hip_free_after']))]
 for mutation in mutations:
  n=copy.deepcopy(native);mutation(n)
  try:validate_native(n,m,qm,pci)
  except ValueError:count+=1
  else:raise ValueError('observed native metadata mutation accepted')
 receipt=json.loads((HERE/'fixture-receipts.json').read_text());atomic=expected_atomic(qm['jobs'][0],receipt)
 for index in (6,7,8,11):
  altered=copy.deepcopy(atomic);altered[0][index]+='-wrong'
  try:check_atomic(altered,qm['jobs'][0],receipt)
  except ValueError:count+=1
  else:raise ValueError('atomic source/bytes mutation accepted')
 altered=BUILD/'cpu-negative/manifest-mutated.json';altered.write_bytes((BUNDLE/'manifest.json').read_bytes()+b' ')
 try:manifest_identity(altered,sha(BUNDLE/'manifest.json'))
 except ValueError:count+=1
 else:raise ValueError('disk manifest mutation accepted')
 return count

def verify_only(role):
 role+='-r3'
 global REPLAY
 REPLAY=True
 original=BUILD/(role+'-verification.json');proof=json.loads(original.read_text());m=json.loads((BUNDLE/'manifest.json').read_text());fixed=sha(BUNDLE/'manifest.json');wrapper=record(Path(__file__));qm=q_binding()
 if proof.get('status')!='pass' or proof.get('manifest_sha256')!=fixed or proof.get('Q_manifest_sha256')!=m['q_manifest']['sha256'] or proof.get('artifact_sha256')!=m['artifact']['sha256'] or proof.get('exit')!=0:raise ValueError('capture proof binding')
 capture=[record(BUILD/(role+'-boundary.stdout')),record(BUILD/(role+'-boundary.stderr'))]+proof['boundary']['outputs']+[record(original),record(BUILD/(role+'.stdout')),record(BUILD/(role+'.stderr'))]+proof['outputs']
 # Freeze wrapper/captured-output binding before CPU comparison; retain the original G proof.
 replay_manifest=dict(schema='strata-t11-cpu-revalidation/v1',wrapper=wrapper,capture_manifest_sha256=fixed,captured_recipe_sha256=next(r['sha256'] for r in m['recipes'] if Path(r['path'])==Path(__file__)),capture=capture,GPU_executed=False)
 manifest_path=BUILD/(role+'-revalidation-manifest.json')
 if manifest_path.exists():
  if json.loads(manifest_path.read_text())!=replay_manifest:raise ValueError('frozen replay binding changed')
 else:save(manifest_path,replay_manifest)
 replay_sha=sha(manifest_path);bundle_binding(m,fixed)
 for row in capture:
  if record(row['path'])!=row:raise ValueError('saved capture changed')
 if (BUILD/(role+'.stderr')).read_bytes():raise ValueError('saved stderr')
 native=json.loads((BUILD/(role+'.stdout')).read_text())
 if native!=proof['native']:raise ValueError('capture native JSON binding')
 boundary=compare_boundaries(BUILD/(role+'-boundary-outputs'),json.loads((BUILD/(role+'-boundary.stdout')).read_text()),m)
 if boundary!=proof['boundary'] or (BUILD/(role+'-boundary.stderr')).read_bytes():raise ValueError('saved boundary mismatch')
 outputs,compared,loaded=verify_outputs(m,qm,native,BUILD/(role+'-outputs'),proof['pci']);cpu=cpu_checks();negative=replay_negatives(native,m,qm,proof['pci'])
 if outputs!=proof['outputs'] or compared!=proof['compared_values'] or loaded!=proof['loaded_hip']:raise ValueError('saved results changed')
 bundle_binding(m,fixed);manifest_identity(manifest_path,replay_sha)
 if wrapper!=record(Path(__file__)) or any(record(r['path'])!=r for r in capture):raise ValueError('revalidation before/after binding')
 result=dict(boundary_values=boundary['compared_values'],status='pass',revalidation_manifest_sha256=replay_sha,capture_manifest_sha256=fixed,artifact_sha256=m['artifact']['sha256'],Q_manifest_sha256=m['q_manifest']['sha256'],captured_proof_sha256=sha(original),compared_values=compared,jobs=len(qm['jobs']),metadata_negative_cases=negative,CPU_checks=cpu,before_after_binding=True,GPU_executed=False,source_qualified=False,device_explicit_atomic_peak=max(native['matrix_owned_peak'],native['actual_scratch_peak']),device_lifetime='T11 helper scratch synchronizes/copies before RAII release at return; projection begins after helper return, T09 project frees raw/input/output before return. These device lifetimes do not overlap; max, not sum. Driver/context/allocator overhead unknown.',host_scope='host matrix scope is a lower bound on explicit primitive buffers; audit trace and all live host vectors are separate, full host peak unknown')
 save(BUILD/(role+'-revalidation.json'),result);print(json.dumps(result))

def execute(pci,role):
 role+='-r3'
 m=json.loads((BUNDLE/'manifest.json').read_text());fixed=sha(BUNDLE/'manifest.json');bundle_binding(m,fixed);qm=q_binding();out=BUILD/(role+'-outputs')
 if out.exists():raise ValueError('preserve prior trial outputs; no blind rerun')
 sdk,tools,env=environment();env['PATH']=str(BUNDLE)+os.pathsep+env['PATH'];start=time.monotonic();
 boundary_out=BUILD/(role+'-boundary-outputs');br=run([EXE,'--boundaries',pci,BUILD/'boundary-q/inputs',boundary_out],env,False);(BUILD/(role+'-boundary.stdout')).write_text(br.stdout,encoding='utf-8');(BUILD/(role+'-boundary.stderr')).write_text(br.stderr,encoding='utf-8')
 if br.returncode or br.stderr:raise ValueError('native boundary failed')
 boundary=compare_boundaries(boundary_out,json.loads(br.stdout),m)
 r=run([EXE,'--run',pci,BUILD/'weights.tsv',BUILD/'sources.tsv',BUILD/'prefixes.tsv',BUILD/'jobs.tsv',out],env,False,1800);(BUILD/(role+'.stdout')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'.stderr')).write_text(r.stderr,encoding='utf-8')
 proof=dict(boundary=boundary,manifest_sha256=fixed,Q_manifest_sha256=m['q_manifest']['sha256'],artifact_sha256=m['artifact']['sha256'],pci=pci,exit=r.returncode,seconds=time.monotonic()-start,status='not_passed',source_qualified=False);save(BUILD/(role+'-verification.json'),proof)
 if r.returncode or r.stderr:raise RuntimeError('native trial failed; evidence retained')
 native=json.loads(r.stdout)
 outputs,compared,loaded=verify_outputs(m,qm,native,out,pci)
 bundle_binding(m,fixed);proof.update(status='pass',native=native,compared_values=compared,outputs=outputs,loaded_hip=loaded,before_after_binding=True,atomic_scope='successful fixed T09 explicit matrix allocations + directly observed T11 scratch; allocator/context/OS physical unknown; host matrix scope excludes audit trace/other process buffers');save(BUILD/(role+'-verification.json'),proof);print(json.dumps(dict(status='pass',jobs=len(qm['jobs']),compared_values=compared,manifest_sha256=fixed,proof_sha256=sha(BUILD/(role+'-verification.json')))))

def main():
 p=argparse.ArgumentParser();p.add_argument('--prepare-boundaries',action='store_true');p.add_argument('--prepare',action='store_true');p.add_argument('--build',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--execute');p.add_argument('--role',choices=['primary','secondary']);args=p.parse_args();BUILD.mkdir(exist_ok=True)
 if args.prepare_boundaries:prepare_boundaries()
 elif args.prepare:prepare()
 elif args.build:build()
 elif args.verify_only and args.role:verify_only(args.role)
 elif args.execute and args.role:execute(args.execute,args.role)
 else:raise ValueError('choose explicit prepare/build/execute role')
if __name__=='__main__':main()
