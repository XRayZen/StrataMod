"""Explicit T14 fixed N/Q/G qualification, not a runtime startup gate."""
import argparse,hashlib,importlib.util,json,subprocess,sys,os,shutil,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).resolve().parent;BUILD=ROOT/'build-deepseek-t14'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def record(p):return dict(path=str(p),bytes=Path(p).stat().st_size,sha256=sha(p))
def load(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def prepare():
 q=load('kv_independent_q',HERE/'reference.py');a=load('kv_local_raw',HERE/'acquire_fixtures.py');receipt=json.loads((HERE/'fixture-receipts.json').read_text());a.verify_receipt(receipt);contract=json.loads((HERE/'contract.json').read_text())
 if contract['N']!=q.decimal_literals():raise ValueError('independent literal origin')
 root=BUILD/'q';root.mkdir(exist_ok=True)
 if (root/'manifest.json').exists():raise ValueError('preserve frozen Q trial')
 def write(folder,name,array):
  x=np.asarray(array);shape=list(x.shape)
  if x.ndim==1:x=x.reshape(1,-1)
  if x.ndim!=2:raise ValueError('trace matrix shape')
  path=folder/(name+'.bin');x.astype(x.dtype.newbyteorder('<')).tofile(path);return dict(name=name,**record(path),dtype=x.dtype.str,shape=list(x.shape),allow_empty=x.size==0,compare='ulp2' if name.endswith(('__inv','__frequencies')) else 'bits')
 projected=q.learned_projection(receipt);jobs=[]
 for batch in (1,2,4,8):
  for phase in (0,4):
   name=f'projection-B{batch}-phase{phase}';folder=root/name;folder.mkdir();indices=(np.arange(batch)+phase)%8;inputrow=write(folder,'native-input',q.fixed_inputs()[indices]);outputs=[]
   for role,parts in projected.items():
    for key,array in sorted(parts.items()):
     if key=='norm_weight':continue
     outputs.append(write(folder,role+'__'+key,array[indices]))
   jobs.append(dict(name=name,kind='projection',batch=batch,phase=phase,input=inputrow,outputs=outputs))
 for length in (1,2,3,127,128,129):
  for phase in (0,4):
   name=f'temporal-L{length}-phase{phase}';folder=root/name;folder.mkdir();trace=q.temporal_projection(projected,length,phase);trace['shared_events']=q.shared_events(length);outputs=[write(folder,key,value) for key,value in sorted(trace.items())];jobs.append(dict(name=name,kind='temporal',batch=1,length=length,phase=phase,outputs=outputs))
 for batch in (2,4,8):
  for phase in (0,4):
   name=f'temporal-B{batch}-L3-phase{phase}';folder=root/name;folder.mkdir();outputs=[]
   for context in range(batch):
    trace=q.temporal_projection(projected,3,(phase+context)%8);trace['shared_events']=q.shared_events(3)
    outputs.extend(write(folder,'c'+str(context)+'__'+key,value) for key,value in sorted(trace.items()))
   jobs.append(dict(name=name,kind='temporal_batch',batch=batch,length=3,phase=phase,outputs=outputs))
 controls=[]
 for name,parts in q.controls().items():
  folder=root/('controlled-'+name);folder.mkdir();inputs=[];outputs=[]
  for key,value in sorted(parts.items()):
   row=write(folder,key,value)
   if key in ('input','kv','score','positions'):inputs.append(row)
   else:outputs.append(row)
  controls.append(dict(name=name,inputs=inputs,outputs=outputs))
 manifest=dict(schema='strata-t14-fixed-q/v1',G_executed=False,full_source_qualified=False,references=[record(HERE/'reference.py'),record(HERE/'contract.json'),record(HERE/'fixture-receipts.json'),record(EXT/'tests/quant/q_reference.py'),record(EXT/'models/deepseek41/reference-config.json')],jobs=jobs,controlled=controls,scope='8 distinct real input projections; temporal periodic8 composition; packed/state controls, not fullmodel/resident or129uniqueprojection qualification')
 save(root/'manifest.json',manifest);print(json.dumps(dict(Q_frozen=sha(root/'manifest.json'),jobs=len(jobs),controlled=len(controls))))

def environment():
 shared=Path('C:/Develop/AI/StrataMod');sdk=shared/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel';vc=shared/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=shared/'.vision-toolchain/winsdk';inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
 tools=dict(clang=sdk/'lib/llvm/bin/clang++.exe',cmake=shared/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',ninja=shared/'.vision-venv-10.1/Scripts/ninja.exe',linker=vc/'bin/Hostx64/x64/link.exe',dumpbin=vc/'bin/Hostx64/x64/dumpbin.exe',rc=wb/'rc.exe',mt=wb/'mt.exe',objdump=sdk/'lib/llvm/bin/llvm-objdump.exe')
 env=os.environ.copy();temp=BUILD/'tmp';temp.mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(temp);env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']));env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',sdk/'lib']));env['PATH']=os.pathsep.join(map(str,[sdk/'bin',sdk/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')]));env['HIP_PATH']=env['ROCM_PATH']=str(sdk);env['HIP_PLATFORM']='amd';return sdk,tools,env

BUNDLE=BUILD/'bundle-r7';EXE=BUNDLE/'t14-kv.exe'
COMPILED=[EXT/'models/deepseek41'/n for n in ('kv.hpp','kv.hip')]+[HERE/'kv_fixture.cpp']
RECIPES=[HERE/n for n in ('CMakeLists.txt','reference.py','contract.json','acquire_fixtures.py','fixture-receipts.json','build_verify.py')]
DEPS=[EXT/'native/quant'/n for n in ('quant.hpp','quant.hip')]+[EXT/'native/stats'/n for n in ('measurement.hpp','measurement.cpp')]+[EXT/'native/artifact'/n for n in ('native_reader.hpp','native_reader.cpp','full_acquire.py','acquire.py','gguf.py')]+[EXT/'models/deepseek41'/n for n in ('artifact.hpp','artifact.cpp','reference-config.json')]+[ROOT/'include/strata/artifact'/n for n in ('dequant.hpp','gguf_reader.hpp','gguf_split.hpp','model_family.hpp')]+[ROOT/'include/strata/core/geometry.hpp',EXT/'tests/quant/q_reference.py',EXT/'tests/numerics/reference.py']
def records(paths):return [record(p) for p in paths]
def aggregate(rows):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n' for r in rows).encode()).hexdigest()
def run(args,env=None,check=True):
 r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=900)
 if check and r.returncode:raise RuntimeError(r.stdout+r.stderr)
 return r

Q_SHA='4212aef63428a4b29f09875c939304df0ddd6ef75bf63ab31c8e169af0b599e8'
def strict_int(v,minimum=0):
 if type(v)is not int or v<minimum:raise ValueError('strict integer')
 return v
def q_binding():
 path=BUILD/'q/manifest.json'
 if sha(path)!=Q_SHA:raise ValueError('frozen G-before Q manifest')
 m=json.loads(path.read_text());a=load('kv_raw_preflight',HERE/'acquire_fixtures.py');a.verify_receipt(json.loads((HERE/'fixture-receipts.json').read_text()))
 if m['schema']!='strata-t14-fixed-q/v1' or m['G_executed']is not False or m['full_source_qualified']is not False:raise ValueError('Q origin')
 for row in m['references']:
  if record(row['path'])!=row:raise ValueError('Q reference changed')
 if len(m['jobs'])!=26 or len({j['name'] for j in m['jobs']})!=26 or len(m['controlled'])!=16:raise ValueError('Q coverage')
 for job in m['jobs']+m['controlled']:
  names=set()
  for row in job.get('inputs',[])+([job['input']]if'input'in job else[])+job['outputs']:
   shape=row['shape'];dtype=row['dtype']
   if not isinstance(shape,list) or len(shape)!=2 or any(type(v)is not int or v<0 for v in shape) or shape[1]<1 or dtype not in ('<f4','|u1','<i4','<i8'):raise ValueError('Q strict geometry')
   if type(row['allow_empty'])is not bool or row['allow_empty']!=(shape[0]==0) or row['bytes']!=int(np.prod(shape))*np.dtype(dtype).itemsize or record(row['path'])!={k:row[k] for k in ('path','bytes','sha256')}:raise ValueError('Q exact bytes')
   if row['name']in names:raise ValueError('Q duplicate stage')
   names.add(row['name'])
 return m
def compare(actual,row):
 raw=Path(actual).read_bytes();expected=Path(row['path']).read_bytes()
 if len(raw)!=row['bytes'] or len(expected)!=row['bytes']:raise ValueError('exact output bytes')
 if not raw:
  if row['allow_empty']is not True or row['shape'][0]!=0:raise ValueError('unapproved empty stage')
  return 0
 if row['dtype']=='<f4':
  av=np.frombuffer(raw,'<f4');ev=np.frombuffer(expected,'<f4')
  if not np.isfinite(av).all() or not np.isfinite(ev).all():raise ValueError('nonfinite stage')
 else:av=np.frombuffer(raw,row['dtype']);ev=np.frombuffer(expected,row['dtype'])
 if row['compare']=='bits':
  if raw!=expected:raise ValueError('exact stage mismatch '+row['name'])
 elif row['compare']=='ulp2'and row['dtype']=='<f4':
  ab=av.view(np.uint32);eb=ev.view(np.uint32)
  if np.any((ev==0)&(ab!=eb)):raise ValueError('signedzero mismatch')
  ai=np.where(ab&0x80000000,~ab,ab|0x80000000).astype(np.int64);ei=np.where(eb&0x80000000,~eb,eb|0x80000000).astype(np.int64)
  if np.any(np.abs(ai-ei)>2):raise ValueError('exceeds fixed2ULP '+row['name'])
 else:raise ValueError('comparison policy')
 return len(av)
def decode_indices_expected(length):
 rows=np.full((length,128),-1,dtype='<i4');rows[0,0]=0
 for p in range(1,length):
  oldest=p%128+1;slots=(oldest+np.arange(128))%128;rows[p]=np.where(slots>p,-1,slots)
 return rows.tobytes()
def state_expectations(qm):
 # Alias only already fixed canonical expectations. No candidate output reads.
 append=[]
 for length,phase in ((1,0),(2,0),(3,4),(127,0),(128,0),(129,0)):
  target=next(j for j in qm['jobs']if j['name']==f'temporal-L{length}-phase{phase}')
  decode=decode_indices_expected(length);path=BUILD/f'state-decode-L{length}.bin';extra=dict(name='append_decode_indices',path=str(path),bytes=len(decode),sha256=hashlib.sha256(decode).hexdigest(),dtype='<i4',shape=[length,128],allow_empty=False,compare='bits');append.append(dict(name=f'append-L{length}-phase{phase}',kind='append',length=length,phase=phase,batch=1,canonical=target['name'],outputs=target['outputs']+[extra]))
 return dict(schema='strata-t14-state-expectations/v1',Q_sha256=Q_SHA,append=append,view_kinds=['prefill_chunk129','decode_ring128'],required_native_state_assertions=700,scope='incremental kernels vs fixed canonical prefill; reset/cancel/exact active-prefix/epoch/source aliases; no real attention or asynchronous device lease')
def expected_jobs(qm):
 state=json.loads((BUILD/'state-expectations-v2.json').read_text())
 if state!=state_expectations(qm):raise ValueError('G-before state expectations changed')
 return qm['jobs']+state['append']+[dict(name='controlled-'+j['name'],outputs=j['outputs'])for j in qm['controlled']]
def bundle_binding(m,fixed):
 recipes=records(RECIPES);snapshot=BUILD/'capture-runner-r1.py'
 for index,row in enumerate(m['recipes']):
  if Path(row['path'])==HERE/'build_verify.py'and recipes[index]!=row:
   if not snapshot.exists()or sha(snapshot)!=row['sha256']or snapshot.stat().st_size!=row['bytes']:raise ValueError('original capture runner missing')
   recipes[index]=row
 if sha(BUNDLE/'manifest.json')!=fixed or m['compiled']!=records(COMPILED) or m['recipes']!=recipes or m['dependencies']!=records(DEPS) or m['compiled_id']!=aggregate(records(COMPILED)):raise ValueError('bundle source/manifest changed')
 for group in ('compiled','recipes','dependencies','inputs','tools','bundle','dll_sources'):
  for row in m[group]:
   if group=='recipes'and Path(row['path'])==HERE/'build_verify.py'and record(row['path'])!=row:
    if sha(snapshot)!=row['sha256']or snapshot.stat().st_size!=row['bytes']:raise ValueError('capture recipe changed')
    continue
   if record(row['path'])!=row:raise ValueError('bound file changed '+row['path'])
 if m['artifact']!=record(EXE) or json.loads(run([EXE,'--identity'],minimal_env()).stdout)['source_id']!=m['compiled_id']:raise ValueError('EXE identity')
 if run(['git','rev-parse','HEAD']).stdout.strip()!='477ac13cbe8e582c20484871ce459d20d82df09d'or run(['git','diff','--name-only','HEAD']).stdout.strip():raise ValueError('upstream tracked changed')
 q_binding();expected_jobs(q_binding())
def minimal_env():
 env=os.environ.copy();env['TMP']=env['TEMP']=str(BUILD/'tmp');env['PATH']=str(BUNDLE)+os.pathsep+os.environ.get('SystemRoot','C:/Windows')+'/System32';env.pop('HIP_PATH',None);env.pop('ROCM_PATH',None);env['HIP_PLATFORM']='amd';return env
def build():
 qm=q_binding();sdk,tools,env=environment();BUNDLE.mkdir(exist_ok=True)
 if (BUNDLE/'manifest.json').exists():raise ValueError('preserve frozen bundle')
 state=BUILD/'state-expectations-v2.json';expect=state_expectations(qm)
 if state.exists()and json.loads(state.read_text())!=expect:raise ValueError('preserve prior state expectations')
 if not state.exists():
  for j in expect['append']:
   path=BUILD/f'state-decode-L{j["length"]}.bin';raw=decode_indices_expected(j['length'])
   if path.exists()and path.read_bytes()!=raw:raise ValueError('preserve prior decode oracle')
   if not path.exists():path.write_bytes(raw)
  save(state,expect)
 identity=aggregate(records(COMPILED));native=BUILD/'cmake-native'
 commands=[[tools['cmake'],'--fresh','-S',HERE,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}',f'-DT14_SOURCE_ID={identity}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,command in enumerate(commands):
  r=run(command,env,False);(BUILD/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise ValueError('build failed '+str(i))
 shutil.copy2(native/'bundle/t14-kv.exe',EXE)
 dlls=('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')
 for name in dlls:shutil.copy2(sdk/'bin'/name,BUNDLE/name)
 licenses=BUNDLE/'licenses';licenses.mkdir(exist_ok=True)
 for source,name in [(ROOT/'LICENSE','Strata-LICENSE'),(ROOT/'third_party/ggml/LICENSE','ggml-LICENSE'),(ROOT/'build-deepseek-t10/bundle-offline-r7/DeepSeek-LICENSE.txt','DeepSeek-LICENSE')]:shutil.copy2(source,licenses/name)
 for component in ('amd_comgr','rocm-core'):
  for source in (sdk/'share/doc'/component).rglob('*'):
   if source.is_file()and any(t in source.name.lower()for t in ('license','notice','copying')):
    dest=licenses/component/source.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(source,dest)
 inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text());receipt=json.loads((HERE/'fixture-receipts.json').read_text());prefixes=BUILD/'prefixes.tsv';prefixes.write_text(''.join(str(r['bytes'])+'\t'+r['prefix_path']+'\n'for r in inventory['shards']),encoding='utf-8');sources=BUILD/'sources.tsv';shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',sources)
 weights=BUILD/'weights.tsv';weights.write_text(''.join('\t'.join(map(str,[r['tensor'],r['absolute_offset'],r['bytes'],r['fixture_path']]))+'\n'for r in receipt['fixtures']),encoding='utf-8')
 input8=BUILD/'input8.bin';load('kv_fixed_inputs',HERE/'reference.py').fixed_inputs().astype('<f4').tofile(input8)
 jobs=BUILD/'jobs.tsv';jobs.write_text(''.join('\t'.join(map(str,[j['name'],j['kind'],j['batch'],j['phase'],j.get('length',0),j.get('input',{}).get('path','unused')]))+'\n'for j in qm['jobs']+expect['append']),encoding='utf-8')
 controlled=BUILD/'controlled.tsv';controlled.write_text(''.join(j['name']+'\t'+str(Path(j['inputs'][0]['path']).parent)+'\n'for j in qm['controlled']),encoding='utf-8')
 inputs=[Path(j['outputs'][-1]['path'])for j in expect['append']]+[prefixes,sources,weights,jobs,controlled,input8,state,BUILD/'q/manifest.json',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json']+[Path(r['prefix_path'])for r in inventory['shards']]+[Path(r['fixture_path'])for r in receipt['fixtures']]+[Path(row['path'])for j in qm['jobs']+qm['controlled']for row in j.get('inputs',[])+([j['input']]if'input'in j else[])+j['outputs']]
 (BUILD/'imports.log').write_text(run([tools['dumpbin'],'/DEPENDENTS',EXE],env).stdout,encoding='utf-8');offload=run([tools['objdump'],'--offloading',EXE],env).stdout;(BUILD/'offload.log').write_text(offload,encoding='utf-8')
 if not all(a in offload for a in ('gfx1100','gfx1201')):raise ValueError('architecture images')
 numpy_paths=sorted({Path(mod.__file__)for name,mod in sys.modules.items()if name.startswith('numpy')and getattr(mod,'__file__',None)and Path(mod.__file__).is_file()})
 m=dict(schema='strata-t14-fixed-bundle/v1',compiled=records(COMPILED),compiled_id=identity,recipes=records(RECIPES),dependencies=records(DEPS),artifact=record(EXE),inputs=records(inputs),tools=records(list(tools.values())+[Path(sys.executable)]+numpy_paths),bundle=records(sorted(p for p in BUNDLE.rglob('*')if p.is_file())),dll_sources=records([sdk/'bin'/n for n in dlls]),source_qualified=False,patches=[])
 save(BUNDLE/'manifest.json',m);fixed=sha(BUNDLE/'manifest.json');bundle_binding(m,fixed);state_result=json.loads(run([EXE,'--state'],minimal_env()).stdout)
 if strict_int(state_result['state_assertions'])<expect['required_native_state_assertions']:raise ValueError('native state coverage')
 bundle_binding(m,fixed);save(BUILD/'cpu-verification.json',dict(manifest_sha256=fixed,compiled_id=identity,state=state_result,GPU_used=False,before_after_binding=True));print(json.dumps(dict(native_ready=fixed,exe_sha256=sha(EXE),state=state_result)))
def expected_peaks(job):
 # Bytes are derived from the fixed kernel/wrapper allocations, not observed
 # high-water values. Functions synchronize and release before the next one.
 name=job['name'];kind=job.get('kind')
 if name.startswith('controlled-'):
  c=name.removeprefix('controlled-')
  scratch=10240 if c.startswith('pool-')else 6148 if c.startswith('norm-')else 20648 if c.startswith('rope')else 4625 if c.startswith('window-')else 4896
  return dict(primitive_peak=0,scratch_peak=scratch)
 if kind=='projection':
  b=strict_int(job['batch'],1)
  return dict(primitive_peak=2785280+b*(5120+512)*4,scratch_peak=max(b*40960,b*46240+1,b*4100+2048))
 if kind=='append':return dict(primitive_peak=0,scratch_peak=6148 if job['length']==1 else 10240)
 if kind in ('temporal','temporal_batch'):
  n=strict_int(job['length'],1);half=n//2
  return dict(primitive_peak=0,scratch_peak=max(n*4104+128,n*4624+1,half*10240,n*4100+2048,n*4896,128))
 raise ValueError('unqualified bytes fixture')
def native_schema(n,m,qm,pci):
 if n['source_id']!=m['compiled_id']or n['pci']!=pci or n['source_qualified']is not False or strict_int(n['state_assertions'])<state_expectations(qm)['required_native_state_assertions']:raise ValueError('native identity/state')
 expected={j['name']for j in expected_jobs(qm)}
 if len(n['jobs'])!=len(expected)or {j['name']for j in n['jobs']}!=expected:raise ValueError('native job coverage')
 for job in n['jobs']:
  for key in ('stages','primitive_peak','scratch_peak'):strict_int(job[key])
  declared=next(j for j in expected_jobs(qm)if j['name']==job['name'])
  for key,value in expected_peaks(declared).items():
   if job[key]!=value:raise ValueError('actual allocation/lifetime mismatch '+job['name']+' '+key)
  if job['cleanup_unknown']is not False:raise ValueError('cleanup unknown')
 for side in ('before','after'):
  status=strict_int(n[side+'_status'])
  if status==0:
   total=strict_int(n[side+'_total'],1);free=strict_int(n[side+'_free'])
   if free>total:raise ValueError('HIP memory observation')
  elif n[side+'_total']is not None or n[side+'_free']is not None:raise ValueError('unknown is not zero')
def verify_outputs(m,fixed,qm,n,out,pci):
 native_schema(n,m,qm,pci);values_count=0;outputs=[];summaries={j['name']:j for j in n['jobs']}
 for job in expected_jobs(qm):
  folder=out/job['name'];rows=[]
  for line in (folder/'stages.tsv').read_text().splitlines():
   r=line.split('\t')
   if len(r)!=5:raise ValueError('stage index')
   rows.append((r[0],r[1],[int(r[2]),int(r[3])],int(r[4])))
  expected=job['outputs']
  if len(rows)!=len(expected)or len({r[0]for r in rows})!=len(rows)or {r[0]for r in rows}!={r['name']for r in expected}:raise ValueError('all-stage coverage')
  index={r[0]:r for r in rows}
  if summaries[job['name']]['stages']!=len(expected):raise ValueError('observed stage count')
  for e in expected:
   name,dtype,shape,size=index[e['name']]
   if dtype!=e['dtype']or shape!=e['shape']or size!=e['bytes']:raise ValueError('exact stage descriptor')
   actual=folder/(name+'.bin');values_count+=compare(actual,e);outputs.append(record(actual))
 loaded=[]
 for path in n['loaded_modules']:
  if not isinstance(path,str):raise ValueError('loaded path')
  if Path(path).name.lower()in ('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'):loaded.append(record(path))
 if len(loaded)!=3 or {Path(r['path']).name.lower()for r in loaded}!={'amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'}or any(Path(r['path']).resolve().parent!=BUNDLE.resolve()or r['sha256']!=sha(BUNDLE/Path(r['path']).name)for r in loaded):raise ValueError('owned actual HIP DLL identity')
 bundle_binding(m,fixed);return dict(jobs=len(n['jobs']),values=values_count,outputs=outputs,loaded=loaded,state_assertions=n['state_assertions'])
def negative_observed(n,m,qm,pci):
 import copy
 mutations=[lambda x:x.update(state_assertions=True),lambda x:x.update(source_qualified=True),lambda x:x.update(pci='wrong'),lambda x:x.update(jobs=x['jobs'][:-1]),lambda x:x['jobs'][0].update(stages=True),lambda x:x['jobs'][0].update(cleanup_unknown=True),lambda x:x.update(before_status=1,before_free=0,before_total=0),lambda x:x.update(after_free=-1),lambda x:x['jobs'][0].update(primitive_peak=0),lambda x:x['jobs'][0].update(scratch_peak=0),lambda x:x['jobs'][0].update(primitive_peak=x['jobs'][0]['primitive_peak']-1),lambda x:x['jobs'][0].update(scratch_peak=x['jobs'][0]['scratch_peak']-1),lambda x:x['jobs'][0].update(primitive_peak=x['jobs'][0]['primitive_peak']+1),lambda x:x['jobs'][0].update(scratch_peak=x['jobs'][0]['scratch_peak']+1),lambda x:x['jobs'][0].update(primitive_peak=True),lambda x:x['jobs'][0].update(scratch_peak=True),lambda x:x['jobs'][0].update(primitive_peak=2785280+8*(5120+512)*4)]
 for change in mutations:
  bad=copy.deepcopy(n);change(bad)
  try:native_schema(bad,m,qm,pci)
  except ValueError:pass
  else:raise ValueError('observed mutation passed')
 return len(mutations)
def execute(pci,role):
 qm=q_binding();fixed=sha(BUNDLE/'manifest.json');m=json.loads((BUNDLE/'manifest.json').read_text());bundle_binding(m,fixed);out=BUILD/(role+'-outputs-r1')
 if m['recipes']!=records(RECIPES):raise ValueError('capture runner frozen; explicit CPU revalidation only')
 if out.exists():raise ValueError('preserve previous GPU trial')
 args=[EXE,'--run',pci,BUILD/'weights.tsv',BUILD/'sources.tsv',BUILD/'prefixes.tsv',BUILD/'jobs.tsv',BUILD/'controlled.tsv',BUILD/'input8.bin',out]
 r=run(args,minimal_env(),False);save(BUILD/(role+'-exit-r1.json'),dict(returncode=r.returncode));(BUILD/(role+'-stdout-r1.json')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'-stderr-r1.log')).write_text(r.stderr,encoding='utf-8')
 if r.returncode or r.stderr:raise ValueError('native execution failed '+r.stderr)
 n=json.loads(r.stdout);result=verify_outputs(m,fixed,qm,n,out,pci);neg=negative_observed(n,m,qm,pci);bundle_binding(m,fixed);save(BUILD/(role+'-verification-r1.json'),dict(manifest_sha256=fixed,compiled_id=m['compiled_id'],exe_sha256=sha(EXE),Q_sha256=Q_SHA,native=n,result=result,observed_negatives=neg,source_qualified=False,runtime_environment={k:minimal_env().get(k)for k in ('PATH','TMP','TEMP','HIP_PATH','ROCM_PATH','HIP_PLATFORM')},before_after_binding=True));print(json.dumps(dict(jobs=result['jobs'],values=result['values'],verification=sha(BUILD/(role+'-verification-r1.json')))))
def verify_only(role):
 proof=json.loads((BUILD/(role+'-verification-r1.json')).read_text());qm=q_binding();m=json.loads((BUNDLE/'manifest.json').read_text());fixed=proof['manifest_sha256'];bundle_binding(m,fixed)
 if proof['compiled_id']!=m['compiled_id']or proof['exe_sha256']!=sha(EXE)or proof['Q_sha256']!=Q_SHA:raise ValueError('proof origin')
 result=verify_outputs(m,fixed,qm,proof['native'],BUILD/(role+'-outputs-r1'),proof['native']['pci'])
 if result!=proof['result']:raise ValueError('original capture output mismatch')
 neg=negative_observed(proof['native'],m,qm,proof['native']['pci']);bundle_binding(m,fixed)
 return dict(CPU_replay=True,jobs=result['jobs'],values=result['values'],GPU_used=False,manifest_sha256=fixed,EXE=record(EXE),native_capture=record(BUILD/(role+'-verification-r1.json')),capture_runner=record(BUILD/'capture-runner-r1.py'),validator=record(HERE/'build_verify.py'),result=result,observed_negatives=neg,allocation_expectations={j['name']:expected_peaks(j)for j in expected_jobs(qm)},before_after_binding=True)
def revalidate(role):
 result=verify_only(role);path=BUILD/(role+'-cpu-validation-r2.json')
 if path.exists():raise ValueError('preserve frozen CPU validation')
 save(path,result);print(json.dumps(dict(CPU_replay=True,jobs=result['jobs'],values=result['values'],observed_negatives=result['observed_negatives'],validation=sha(path))))
def main():
 BUILD.mkdir(exist_ok=True);p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--build',action='store_true');p.add_argument('--execute',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--revalidate',action='store_true');p.add_argument('--pci',default='0000:07:00.0');p.add_argument('--role',default='primary');args=p.parse_args()
 if sum((args.prepare,args.build,args.execute,args.verify_only,args.revalidate))!=1:raise ValueError('one explicit action')
 if args.prepare:prepare()
 elif args.build:build()
 elif args.execute:execute(args.pci,args.role)
 elif args.revalidate:revalidate(args.role)
 else:
  result=verify_only(args.role);path=BUILD/(args.role+'-cpu-validation-r2.json')
  if not path.exists()or json.loads(path.read_text())!=result:raise ValueError('CPU validation fixed binding')
  print(json.dumps(dict(CPU_replay=True,jobs=result['jobs'],values=result['values'],observed_negatives=result['observed_negatives'],GPU_used=False)))
if __name__=='__main__':main()

