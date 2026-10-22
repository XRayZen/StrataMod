"""Explicit T12 qualification; never a normal startup gate."""
import argparse,hashlib,importlib.util,json,subprocess,sys,os,shutil,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).resolve().parent;BUILD=ROOT/'build-deepseek-t12'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def record(p):return dict(path=str(p),bytes=Path(p).stat().st_size,sha256=sha(p))
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def prepare():
 q=load('mhc_independent_q',HERE/'reference.py');a=load('mhc_local_raw',HERE/'acquire_fixtures.py');receipt=json.loads((HERE/'fixture-receipts.json').read_text());a.verify_receipt(receipt)
 directory=BUILD/'q';directory.mkdir(exist_ok=True)
 if (directory/'manifest.json').exists():raise ValueError('expected trial already fixed')
 contract=json.loads((HERE/'contract.json').read_text())
 if contract['N']!=q.decimal_literals():raise ValueError('independent N literal changed')
 weights=q.learned_weights(receipt);jobs=[]
 def write(root,name,array):
  array=np.asarray(array);array=array.reshape(len(array),-1);path=root/(name+'.bin');array.astype(array.dtype.newbyteorder('<')).tofile(path);return dict(name=name,**record(path),dtype=array.dtype.str,shape=list(array.shape),compare='ulp2' if name.endswith('_rsqrt') else 'bits')
 for batch,variant in [(b,v) for b in (1,2,4,8) for v in ('A','B')]+[(1,'zero'),(1,'tiny')]:
  name=f'B{batch}-{variant}';root=directory/name;root.mkdir();x=q.fixed_inputs(batch,variant);inputrow=write(root,'native-input',x);print(json.dumps(dict(event='Q',job=name)),flush=True);trace=q.expected_staggered(x,weights);outputs=[write(root,key,value) for key,value in sorted(trace.items())];jobs.append(dict(name=name,batch=batch,variant=variant,input=inputrow,outputs=outputs))
 controlled=[]
 for case in contract['N']['sinkhorn']:
  values=np.array([case['input']],np.float32);root=directory/('controlled-'+case['name']);root.mkdir();inputrow=write(root,'mixes',values);trace=q.split_sinkhorn(values,np.ones(3,np.float32),np.zeros(24,np.float32));outputs={k:trace[k].reshape(1,-1) for k in ('pre','post','logits','centered','exp','comb')}
  for n,(row,col) in enumerate(trace['rounds']):outputs['row'+str(n)]=row.reshape(1,16);outputs['col'+str(n)]=col.reshape(1,16)
  controlled.append(dict(name=case['name'],input=inputrow,outputs=[write(root,k,v) for k,v in sorted(outputs.items())]))
 root=directory/'controlled-large';root.mkdir();values=np.resize(np.array([-1000,0,1000,1],np.float32),24).reshape(1,24);inputrow=write(root,'mixes',values);trace=q.split_sinkhorn(values,np.ones(3,np.float32),np.zeros(24,np.float32));outputs={k:trace[k].reshape(1,-1) for k in ('pre','post','logits','centered','exp','comb')}
 for n,(row,col) in enumerate(trace['rounds']):outputs['row'+str(n)]=row.reshape(1,16);outputs['col'+str(n)]=col.reshape(1,16)
 controlled.append(dict(name='large',input=inputrow,outputs=[write(root,k,v) for k,v in sorted(outputs.items())]))
 manifest=dict(schema='strata-t12-fixed-q/v1',source_qualified=False,G_executed=False,references=[record(HERE/'reference.py'),record(HERE/'contract.json'),record(HERE/'fixture-receipts.json'),record(EXT/'tests/quant/q_reference.py')],jobs=jobs,controlled=controlled)
 save(directory/'manifest.json',manifest);print(json.dumps(dict(Q_manifest_sha256=sha(directory/'manifest.json'),jobs=len(jobs),controlled=len(controlled))))
def environment():
 shared=Path('C:/Develop/AI/StrataMod');sdk=shared/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel';vc=shared/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=shared/'.vision-toolchain/winsdk';inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
 tools=dict(clang=sdk/'lib/llvm/bin/clang++.exe',cmake=shared/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',ninja=shared/'.vision-venv-10.1/Scripts/ninja.exe',linker=vc/'bin/Hostx64/x64/link.exe',dumpbin=vc/'bin/Hostx64/x64/dumpbin.exe',rc=wb/'rc.exe',mt=wb/'mt.exe',objdump=sdk/'lib/llvm/bin/llvm-objdump.exe')
 env=os.environ.copy();temp=BUILD/'tmp';temp.mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(temp);env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']));env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',sdk/'lib']));env['PATH']=os.pathsep.join(map(str,[sdk/'bin',sdk/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')]));env['HIP_PATH']=env['ROCM_PATH']=str(sdk);env['HIP_PLATFORM']='amd';return sdk,tools,env

BUNDLE=BUILD/'bundle-r2';EXE=BUNDLE/'t12-mhc.exe'
COMPILED=[EXT/'models/deepseek41'/n for n in ('mhc.hpp','mhc.hip')]+[HERE/'mhc_fixture.cpp']
RECIPES=[HERE/n for n in ('CMakeLists.txt','reference.py','contract.json','acquire_fixtures.py','fixture-receipts.json','build_verify.py')]
DEPS=[EXT/'native/quant'/n for n in ('quant.hpp','quant.hip')]+[EXT/'native/stats'/n for n in ('measurement.hpp','measurement.cpp')]+[EXT/'native/artifact'/n for n in ('native_reader.hpp','native_reader.cpp','full_acquire.py','acquire.py','gguf.py')]+[EXT/'models/deepseek41'/n for n in ('artifact.hpp','artifact.cpp','reference-config.json')]+[ROOT/'include/strata/artifact'/n for n in ('dequant.hpp','gguf_reader.hpp','gguf_split.hpp','model_family.hpp')]+[ROOT/'include/strata/core/geometry.hpp',EXT/'tests/quant/q_reference.py',EXT/'tests/numerics/reference.py']
def records(paths):return [record(p) for p in paths]
def aggregate(rows):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n' for r in rows).encode()).hexdigest()
def run(args,env=None,check=True):
 r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=900)
 if check and r.returncode:raise RuntimeError(r.stdout+r.stderr)
 return r

def q_binding():
 path=BUILD/'q/manifest.json';m=json.loads(path.read_text());a=load('mhc_raw_preflight',HERE/'acquire_fixtures.py');a.verify_receipt(json.loads((HERE/'fixture-receipts.json').read_text()))
 if m['source_qualified'] is not False or m['G_executed'] is not False or m['schema']!='strata-t12-fixed-q/v1':raise ValueError('Q origin')
 for row in m['references']:
  if record(row['path'])!=row:raise ValueError('Q reference changed')
 expected={(b,v) for b in (1,2,4,8) for v in ('A','B')}|{(1,'zero'),(1,'tiny')}
 if len(m['jobs'])!=10 or {(j['batch'],j['variant']) for j in m['jobs']}!=expected or {j['name'] for j in m['controlled']}!={'uniform','asymmetric','large'} or len(m['controlled'])!=3:raise ValueError('Q fixture coverage')
 for job in m['jobs']+m['controlled']:
  names=set()
  for row in [job['input']]+job['outputs']:
   if not isinstance(row['shape'],list) or len(row['shape'])!=2 or any(type(v) is not int or v<=0 for v in row['shape']) or row['dtype']!='<f4' or type(row['bytes']) is not int or row['bytes']!=int(np.prod(row['shape']))*4 or sha(row['path'])!=row['sha256'] or Path(row['path']).stat().st_size!=row['bytes']:raise ValueError('Q output geometry/identity')
   if row['name'] in names:raise ValueError('duplicate Q stage')
   names.add(row['name'])
  if len(job['outputs'])!=(217 if 'batch' in job else 46):raise ValueError('all stage/round coverage')
 return m

def bundle_binding(m,fixed):
 if sha(BUNDLE/'manifest.json')!=fixed or m['compiled']!=records(COMPILED) or m['recipes']!=records(RECIPES) or m['dependencies']!=records(DEPS) or m['compiled_id']!=aggregate(records(COMPILED)):raise ValueError('bundle fixed source/recipe')
 if run(['git','rev-parse','HEAD']).stdout.strip()!='477ac13cbe8e582c20484871ce459d20d82df09d' or run(['git','diff','--name-only','HEAD']).stdout.strip():raise ValueError('base tracked changed')
 for group in ('compiled','recipes','dependencies','inputs','tools','bundle'):
  for row in m[group]:
   if record(row['path'])!=row:raise ValueError('bound file changed: '+group)
 if m['artifact']!=record(EXE) or json.loads(run([EXE,'--identity']).stdout)['source_id']!=m['compiled_id']:raise ValueError('EXE identity')
 q_binding()

def compare(actual,expected,policy):
 a=Path(actual).read_bytes();e=Path(expected).read_bytes()
 if len(a)!=len(e) or not a or len(a)%4:raise ValueError('exact output length')
 av=np.frombuffer(a,'<f4');ev=np.frombuffer(e,'<f4')
 if not np.isfinite(av).all() or not np.isfinite(ev).all():raise ValueError('nonfinite stage')
 if policy=='bits':
  if a!=e:raise ValueError('exact stage mismatch')
 elif policy=='ulp2':
  ab=av.view(np.uint32);eb=ev.view(np.uint32)
  if np.any((ev==0)&(ab!=eb)):raise ValueError('signedzero mismatch')
  ai=np.where(ab&0x80000000,~ab,ab|0x80000000).astype(np.int64);ei=np.where(eb&0x80000000,~eb,eb|0x80000000).astype(np.int64)
  if np.any(np.abs(ai-ei)>2):raise ValueError('stage exceeds fixed2ULP')
 else:raise ValueError('comparison policy')
 return len(av)

def cpu_checks():
 q=load('mhc_cpu_preflight',HERE/'reference.py');c=json.loads((HERE/'contract.json').read_text());qm=q_binding();count=0
 if c['N']!=q.decimal_literals():raise ValueError('N literal changed')
 for case in c['N']['sinkhorn']:
  result=q.split_sinkhorn(np.array([case['input']],np.float32),np.ones(3,np.float32),np.zeros(24,np.float32))
  for key in ('pre','post'):
   if result[key].astype('<f4').tobytes()!=b''.join(bytes.fromhex(v) for v in case[key]):raise ValueError('N/Q coefficient literal')
  for n,(row,col) in enumerate(result['rounds']):
   for key,actual in [('row',row),('col',col)]:
    if actual.astype('<f4').tobytes()!=b''.join(bytes.fromhex(v) for v in case['rounds'][n][key]):raise ValueError('N/Q allround literal')
 dir=BUILD/'cpu-negative';dir.mkdir(exist_ok=True);expected=dir/'expected.bin';actual=dir/'actual.bin';expected.write_bytes(np.array([1.,-0.],'<f4').tobytes())
 for raw in (b'',expected.read_bytes()+b'x',np.array([np.nan,-0.],'<f4').tobytes(),np.array([1.,0.],'<f4').tobytes(),np.array([2.,-0.],'<f4').tobytes()):
  actual.write_bytes(raw)
  try:compare(actual,expected,'ulp2')
  except ValueError:count+=1
  else:raise ValueError('bad output passed')
 asym=c['N']['sinkhorn'][1]
 if asym['rounds'][9]['col']==asym['rounds'][19]['col']:raise ValueError('10vs20 not observable')
 qout={r['name']:r for r in qm['jobs'][0]['outputs']};input=np.fromfile(qout['input']['path'],'<f4').reshape(1,4,5120);post=np.fromfile(qout['block0_attn_post']['path'],'<f4').reshape(1,4);comb=np.fromfile(qout['block0_attn_comb']['path'],'<f4').reshape(1,4,4);injected=np.fromfile(qout['block0_attn_injected']['path'],'<f4').reshape(1,5120)
 if q.hc_post(injected,input,post,comb).tobytes()==q.hc_post(injected,input,post,comb.transpose(0,2,1)).tobytes():raise ValueError('transpose fault invisible')
 ownpre=np.fromfile(qout['block0_attn_pre']['path'],'<f4').reshape(1,4);incoming=np.array([[1,0,0,0]],np.float32)
 if q.hc_pre(input,incoming).tobytes()==q.hc_pre(input,ownpre).tobytes():raise ValueError('staggered shift invisible')
 return dict(output_negatives=count,round10_vs20=True,transpose=True,staggered_shift=True,N_literals=2)

def build():
 qm=q_binding();sdk,tools,env=environment();BUNDLE.mkdir(exist_ok=True)
 if (BUNDLE/'manifest.json').exists():raise ValueError('preserve frozen bundle')
 identity=aggregate(records(COMPILED));native=BUILD/'cmake-native'
 commands=[[tools['cmake'],'--fresh','-S',HERE,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}',f'-DT12_SOURCE_ID={identity}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,command in enumerate(commands):
  r=run(command,env,False);(BUILD/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise ValueError('build failed '+str(i))
 shutil.copy2(native/'bundle/t12-mhc.exe',EXE)
 for name in ('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):shutil.copy2(sdk/'bin'/name,BUNDLE/name)
 licenses=BUNDLE/'licenses';licenses.mkdir(exist_ok=True)
 for source,name in [(ROOT/'LICENSE','Strata-LICENSE'),(ROOT/'third_party/ggml/LICENSE','ggml-LICENSE'),(ROOT/'build-deepseek-t10/bundle-offline-r7/DeepSeek-LICENSE.txt','DeepSeek-LICENSE')]:shutil.copy2(source,licenses/name)
 for component in ('amd_comgr','rocm-core'):
  for source in (sdk/'share/doc'/component).rglob('*'):
   if source.is_file() and any(t in source.name.lower() for t in ('license','notice','copying')):
    dest=licenses/component/source.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(source,dest)
 inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text());receipt=json.loads((HERE/'fixture-receipts.json').read_text());prefixes=BUILD/'prefixes.tsv';prefixes.write_text(''.join(str(r['bytes'])+'\t'+r['prefix_path']+'\n' for r in inventory['shards']),encoding='utf-8');sources=BUILD/'sources.tsv';shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',sources)
 weights=BUILD/'weights.tsv';weights.write_text(''.join('\t'.join(map(str,[r['tensor'],r['absolute_offset'],r['bytes'],r['fixture_path']]))+'\n' for r in receipt['fixtures']),encoding='utf-8')
 jobs=BUILD/'jobs.tsv';jobs.write_text(''.join('\t'.join(map(str,[j['name'],j['batch'],j['input']['path'],Path(j['input']['path']).parent,j['input']['sha256']]))+'\n' for j in qm['jobs']),encoding='utf-8');controlled=BUILD/'controlled.tsv';controlled.write_text(''.join(j['name']+'\t'+j['input']['path']+'\n' for j in qm['controlled']),encoding='utf-8')
 inputs=[prefixes,sources,weights,jobs,controlled,BUILD/'q/manifest.json',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json']+[Path(r['prefix_path']) for r in inventory['shards']]+[Path(r['fixture_path']) for r in receipt['fixtures']]+[Path(row['path']) for j in qm['jobs']+qm['controlled'] for row in [j['input']]+j['outputs']]
 (BUILD/'imports.log').write_text(run([tools['dumpbin'],'/DEPENDENTS',EXE],env).stdout,encoding='utf-8');offload=run([tools['objdump'],'--offloading',EXE],env).stdout;(BUILD/'offload.log').write_text(offload,encoding='utf-8')
 if not all(a in offload for a in ('gfx1100','gfx1201')):raise ValueError('architecture images')
 # Imported NumPy implementation participates in the recorded oracle environment.
 numpy_paths=sorted({Path(mod.__file__) for name,mod in sys.modules.items() if name.startswith('numpy') and getattr(mod,'__file__',None) and Path(mod.__file__).is_file()})
 m=dict(schema='strata-t12-fixed-bundle/v1',compiled=records(COMPILED),compiled_id=identity,recipes=records(RECIPES),dependencies=records(DEPS),artifact=record(EXE),inputs=records(inputs),tools=records(list(tools.values())+[Path(sys.executable)]+numpy_paths),bundle=records(sorted(p for p in BUNDLE.rglob('*') if p.is_file())),source_qualified=False,patches=[])
 save(BUNDLE/'manifest.json',m);fixed=sha(BUNDLE/'manifest.json');bundle_binding(m,fixed);run([sys.executable,'-B',HERE/'reference.py']);cpu=cpu_checks();bundle_binding(m,fixed);save(BUILD/'cpu-verification.json',dict(manifest_sha256=fixed,cpu=cpu,GPU_used=False,before_after_binding=True));print(json.dumps(dict(native_ready=fixed,exe_sha256=sha(EXE))))

def native_schema(native,m,qm,pci):
 expected=[j['name'] for j in qm['jobs']]+['controlled-'+j['name'] for j in qm['controlled']]
 if native.get('source_id')!=m['compiled_id'] or native.get('pci')!=pci or native.get('source_qualified') is not False or not isinstance(native.get('jobs'),list) or len(native['jobs'])!=13 or [j.get('name') for j in native['jobs']]!=expected:raise ValueError('native identity/coverage')
 for when in ('before','after'):
  status=native.get(when+'_status');free=native.get(when+'_free');total=native.get(when+'_total')
  if type(status) is not int:raise ValueError('memory status type')
  if status==0:
   if type(free) is not int or type(total) is not int or not 0<=free<=total or total<=0:raise ValueError('memory observed schema')
  elif free is not None or total is not None:raise ValueError('unknown memory must be null')
 for observed in native['jobs']:
  if observed.get('cleanup_unknown') is not False or any(type(observed.get(k)) is not int or observed[k]<0 for k in ('stages','primitive_peak','scratch_peak')):raise ValueError('strict job stats')

def expected_atomic(job,receipt):
 rows={r['tensor']:r for r in receipt['fixtures']};batch=job['batch'];result=[]
 for kind in ('attn','ffn','attn','ffn'):
  r=rows['blk.0.hc_'+kind+'_fn.weight'];result.append([r['tensor'],Path(r['source']['path']).as_posix(),str(r['absolute_offset']),str(batch),str(r['bytes']),str(batch*20480*4),str(batch*24*4)])
 return result

def verify_outputs(m,fixed,qm,native,out,pci):
 native_schema(native,m,qm,pci);receipt=json.loads((HERE/'fixture-receipts.json').read_text());outputs=[];compared=0
 for job,observed in zip(qm['jobs']+qm['controlled'],native['jobs'],strict=True):
  name=job['name'] if 'batch' in job else 'controlled-'+job['name'];directory=out/name;rows=[line.split('\t') for line in (directory/'stages.tsv').read_text().splitlines()];metadata={r[0]:r for r in rows}
  if len(metadata)!=len(rows) or set(metadata)!={r['name'] for r in job['outputs']} or observed['stages']!=len(job['outputs']):raise ValueError('actual full stage/round coverage')
  for expected in job['outputs']:
   row=metadata[expected['name']]
   if len(row)!=4 or list(map(int,row[1:3]))!=expected['shape'] or int(row[3])!=expected['bytes']:raise ValueError('stage geometry')
   path=directory/(expected['name']+'.bin')
   try:compared+=compare(path,expected['path'],expected['compare'])
   except ValueError as e:raise ValueError(name+'/'+expected['name']+': '+str(e)) from e
   outputs.append(record(path))
  atomic=[line.split('\t') for line in (directory/'atomic.tsv').read_text().splitlines()]
  if 'batch' in job:
   if atomic!=expected_atomic(job,receipt) or observed['primitive_peak']!=1966080+job['batch']*82016 or observed['scratch_peak']!=job['batch']*184400:raise ValueError('source/primitive/lifetime accounting')
  elif atomic or observed['primitive_peak']!=0 or observed['scratch_peak']!=2988:raise ValueError('controlled accounting')
  outputs+=records([directory/'stages.tsv',directory/'atomic.tsv'])
 loaded=records([Path(p) for p in native['loaded_modules'] if Path(p).name.lower() in ('amdhip64_7.dll','amd_comgr.dll')])
 if {Path(r['path']).name.lower() for r in loaded}!={'amdhip64_7.dll','amd_comgr.dll'} or any(Path(r['path']).resolve().parent!=BUNDLE.resolve() or r['sha256']!=sha(BUNDLE/Path(r['path']).name) for r in loaded):raise ValueError('loaded HIP identity')
 bundle_binding(m,fixed);return outputs,compared,loaded

def negative_observed(native,m,qm,pci):
 import copy
 count=0
 for mutation in [lambda n:n.update(jobs=[]),lambda n:n.update(source_qualified=0),lambda n:n['jobs'][0].update(cleanup_unknown=0),lambda n:n['jobs'][0].update(stages=float(n['jobs'][0]['stages'])),lambda n:n.update(before_status=1,before_free=0),lambda n:n.update(after_free=float(n['after_free']))]:
  n=copy.deepcopy(native);mutation(n)
  try:native_schema(n,m,qm,pci)
  except ValueError:count+=1
  else:raise ValueError('observed mutation passed')
 receipt=json.loads((HERE/'fixture-receipts.json').read_text());correct=expected_atomic(qm['jobs'][0],receipt)
 for col in (1,2,4,5):
  bad=copy.deepcopy(correct);bad[0][col]+='bad'
  if bad==expected_atomic(qm['jobs'][0],receipt):raise ValueError('atomic mutation passed')
  count+=1
 altered=BUILD/'cpu-negative/altered-manifest.json';altered.write_bytes((BUNDLE/'manifest.json').read_bytes()+b' ')
 if sha(altered)==sha(BUNDLE/'manifest.json'):raise ValueError('manifest mutation not detectable')
 return count+1

def execute(pci,role):
 m=json.loads((BUNDLE/'manifest.json').read_text());fixed=sha(BUNDLE/'manifest.json');bundle_binding(m,fixed);qm=q_binding();out=BUILD/(role+'-r2-outputs')
 if out.exists():raise ValueError('preserve previous trial')
 sdk,tools,env=environment();env['PATH']=str(BUNDLE)+os.pathsep+env['PATH'];start=time.monotonic();r=run([EXE,'--run',pci,BUILD/'weights.tsv',BUILD/'sources.tsv',BUILD/'prefixes.tsv',BUILD/'jobs.tsv',BUILD/'controlled.tsv',out],env,False);(BUILD/(role+'-r2.stdout')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'-r2.stderr')).write_text(r.stderr,encoding='utf-8')
 proof=dict(manifest_sha256=fixed,Q_manifest_sha256=sha(BUILD/'q/manifest.json'),artifact_sha256=sha(EXE),status='not_passed',exit=r.returncode,seconds=time.monotonic()-start,pci=pci,source_qualified=False);path=BUILD/(role+'-r2-verification.json');save(path,proof)
 if r.returncode or r.stderr:raise ValueError('native failed; proof retained')
 native=json.loads(r.stdout);outputs,compared,loaded=verify_outputs(m,fixed,qm,native,out,pci);negative=negative_observed(native,m,qm,pci);bundle_binding(m,fixed)
 proof.update(status='pass',native=native,outputs=outputs,compared_values=compared,loaded=loaded,negative_observed=negative,before_after_binding=True,scope='offline two repeated blk0 weight blocks/staggered injected subblocks; no real attention/FFN or fullsource qualification',accounting='device primitive and scratch lifetimes do not overlap; explicit device peak=max; host vectors/audit trace/allocator/context/driver peak unknown')
 save(path,proof);print(json.dumps(dict(status='pass',compared_values=compared,jobs=13,manifest_sha256=fixed,proof_sha256=sha(path))))

def verify_only(role):
 path=BUILD/(role+'-r2-verification.json');proof=json.loads(path.read_text());m=json.loads((BUNDLE/'manifest.json').read_text());fixed=sha(BUNDLE/'manifest.json');bundle_binding(m,fixed);qm=q_binding();before=records([path,BUILD/(role+'-r2.stdout'),BUILD/(role+'-r2.stderr')])
 if proof.get('status')!='pass' or type(proof.get('exit')) is not int or proof['exit']!=0 or proof.get('manifest_sha256')!=fixed or proof.get('artifact_sha256')!=sha(EXE) or proof.get('Q_manifest_sha256')!=sha(BUILD/'q/manifest.json') or proof.get('source_qualified') is not False:raise ValueError('fixed proof binding')
 if (BUILD/(role+'-r2.stderr')).read_bytes():raise ValueError('saved stderr')
 native=json.loads((BUILD/(role+'-r2.stdout')).read_text())
 if native!=proof['native']:raise ValueError('saved native JSON')
 outputs,compared,loaded=verify_outputs(m,fixed,qm,native,BUILD/(role+'-r2-outputs'),proof['pci'])
 if outputs!=proof['outputs'] or compared!=proof['compared_values'] or loaded!=proof['loaded']:raise ValueError('saved results changed')
 cpu=cpu_checks();negative=negative_observed(native,m,qm,proof['pci']);bundle_binding(m,fixed)
 if before!=records([path,BUILD/(role+'-r2.stdout'),BUILD/(role+'-r2.stderr')]):raise ValueError('proof before/after binding')
 print(json.dumps(dict(status='pass',compared_values=compared,jobs=13,negative_observed=negative,CPU_checks=cpu,manifest_sha256=fixed,GPU_executed=False)))

def main():
 BUILD.mkdir(exist_ok=True);p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--build',action='store_true');p.add_argument('--execute');p.add_argument('--verify-only',action='store_true');p.add_argument('--role',choices=['primary','secondary']);args=p.parse_args()
 if args.prepare:prepare()
 elif args.build:build()
 elif args.execute and args.role:execute(args.execute,args.role)
 elif args.verify_only and args.role:verify_only(args.role)
 else:raise ValueError('explicit action required')
if __name__=='__main__':main()
