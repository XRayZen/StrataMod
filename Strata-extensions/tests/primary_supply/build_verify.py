"""Owned T18 build/receipts. Explicit execute alone creates GPU contexts."""
import argparse,copy,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t18';BUNDLE=BUILD/'bundle';EXE=BUNDLE/'t18-supply.exe';MANIFEST=BUILD/'manifest.json'
SDK=Path('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel')
COMPILED=[EXT/p for p in ['native/quant/quant.hpp','native/quant/quant.hip','native/cache/lease_queue.hpp','native/cache/lease_queue.cpp','native/cache/primary_supply.hpp','native/cache/primary_supply.hip','tests/primary_supply/fixture.hip']]
RECIPES=[HERE/n for n in ['CMakeLists.txt','reference.py','contract.json','build_verify.py']]
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def row(p):return dict(path=str(p),bytes=Path(p).stat().st_size,sha256=sha(p))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def run(cmd,env=None,check=True,timeout=600):
 r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
 if check and r.returncode:raise RuntimeError(str(cmd)+'\n'+r.stdout+r.stderr)
 return r
def environment():
 m=load('t18_shared_readonly_env_recipe',EXT/'tests/cache/build_verify.py');m.BUILD=BUILD;return m.environment()
def runtime():
 _,env=environment();windows=Path(os.environ['SystemRoot']);env['PATH']=os.pathsep.join(map(str,[BUNDLE,windows/'System32',windows]))
 for name in ['HIP_PATH','ROCM_PATH','HIP_PLATFORM','INCLUDE','LIB']:env.pop(name,None)
 env['PYTHONDONTWRITEBYTECODE']='1';return env
def compiled_id():return hashlib.sha256(''.join(p.relative_to(ROOT).as_posix()+'|'+sha(p)+'\n' for p in COMPILED).encode()).hexdigest()
def check_rows(rows):
 for r in rows:
  if row(r['path'])!=r:raise ValueError('fixed bytes changed: '+r['path'])
def q_binding():
 q=read(BUILD/'q/manifest.json')
 if q['G_executed'] is not False or q['contract']!=row(HERE/'contract.json'):raise ValueError('Q contract origin')
 check_rows(q['references'])
 for j in q['jobs']:check_rows([j['input'],j['expected']])
 a=load('t18_individual_final_receipt',EXT/'tests/ffn/acquire_fixtures.py');receipt=read(EXT/'tests/ffn/fixture-receipts.json');a.verify_receipt(receipt,receipt['selected_experts'])
 for i in (2,9):a.finalized(i)
 for x in q['matrices']:
  if x not in receipt['fixtures']:raise ValueError('matrix raw/source identity changed')
 return q
def binding(m):
 if m['compiled']!=list(map(row,COMPILED)) or m['recipes']!=list(map(row,RECIPES)) or m['compiled_id']!=compiled_id():raise ValueError('compiled/recipe identity')
 for k in ['dependencies','inputs','bundle_files','tools']:check_rows(m[k])
 q_binding()
 if run(['git','rev-parse','HEAD']).stdout.strip()!=m['upstream_base'] or run(['git','diff','HEAD','--name-only']).stdout.strip():raise ValueError('upstream tracked source changed')
def build():
 q=q_binding();tools,env=environment();BUNDLE.mkdir(exist_ok=True)
 if MANIFEST.exists():raise ValueError('preserve fixed trial before changing source')
 shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',BUILD/'sources.tsv');shutil.copy2(ROOT/'build-deepseek-t10/nine-prefixes.tsv',BUILD/'prefixes.tsv')
 (BUILD/'raw-paths.tsv').write_text(''.join(x['fixture_path']+'\n' for x in q['matrices']),encoding='utf-8');(BUILD/'raw-path.bin').write_bytes(q['matrices'][0]['fixture_path'].encode())
 for j in q['jobs']:shutil.copy2(j['input']['path'],BUILD/Path(j['input']['path']).name)
 out=BUILD/'cmake';cmd=[tools['cmake'],'--fresh','-S',HERE,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 commands=[cmd,[tools['cmake'],'--build',out,'--verbose']]
 for i,command in enumerate(commands):
  r=run(command,env,False);(BUILD/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise RuntimeError('build failed; log saved')
 shutil.copy2(out/'bundle/t18-supply.exe',EXE);origins=[]
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
  src=SDK/'bin'/name;dst=BUNDLE/name;shutil.copy2(src,dst);origins.append(dict(source=row(src),target=row(dst)))
 licenses=BUNDLE/'licenses';licenses.mkdir(exist_ok=True);shutil.copy2(ROOT/'LICENSE',licenses/'Strata-LICENSE')
 for src in (ROOT/'build-deepseek-t13/bundle/licenses').rglob('*'):
  if src.is_file():shutil.copy2(src,licenses/src.name)
 for name,command in [('imports',[tools['dumpbin'],'/DEPENDENTS',EXE]),('offloading',[tools['objdump'],'--offloading',EXE])]:
  r=run(command,env);(BUILD/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
  if name=='offloading' and not all(x in r.stdout for x in ['gfx1100','gfx1201']):raise ValueError('both code objects missing')
 # CMake dependencies from its exact consumed translation units, including HIP shim.
 dep_paths=set()
 deps=run([tools['ninja'],'-C',out,'-t','deps'],env).stdout;(BUILD/'compiler-deps.log').write_text(deps,encoding='utf-8')
 for line in deps.splitlines():
  if line.startswith('    '):
   p=Path(line.strip());p=p if p.is_absolute() else out/p
   if p.is_file() and p.resolve().is_relative_to(ROOT.resolve()) and p.resolve() not in {x.resolve() for x in COMPILED}:dep_paths.add(p.resolve())
 for p in [EXT/'tests/ffn/acquire_fixtures.py',EXT/'tests/ffn/fixture-receipts.json',EXT/'tests/quant/q_reference.py',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json']:dep_paths.add(p)
 inputs=[BUILD/'before.json',BUILD/'capacity-start.json',BUILD/'q/manifest.json',BUILD/'sources.tsv',BUILD/'prefixes.tsv',BUILD/'raw-paths.tsv',BUILD/'raw-path.bin']+list(BUILD.glob('m*-input.bin'))
 inputs += [Path(x['fixture_path']) for x in q['matrices']]+[Path(o[k]['path']) for o in q['jobs'] for k in ['input','expected']]
 inputs += [Path(line.split('\t')[1]) for line in (BUILD/'prefixes.tsv').read_text(encoding='utf-8').splitlines()]
 inputs += [Path(x['snapshot']) for x in read(BUILD/'before.json')['source']]
 m=dict(schema='t18-fixed-trial/v1',compiled=list(map(row,COMPILED)),recipes=list(map(row,RECIPES)),compiled_id=compiled_id(),dependencies=list(map(row,sorted(dep_paths))),inputs=list(map(row,inputs)),bundle_files=[row(p) for p in sorted(BUNDLE.rglob('*')) if p.is_file()],tools=list(map(row,list(tools.values())+[Path(sys.executable)])),dll_origins=origins,upstream_base=run(['git','rev-parse','HEAD']).stdout.strip(),patches=[],full_source_qualified=False,scope='offline primary cache/borrowed device supply; full T05/T10/T19/T20/T21 pending',commands=[list(map(str,c)) for c in commands],OS_context_physical=None)
 save(MANIFEST,m);binding(m);identity=json.loads(run([EXE,'--identity'],runtime()).stdout)
 if identity['source_id']!=m['compiled_id']:raise ValueError('compiled source aggregate mismatch')
 print(dict(manifest=row(MANIFEST),exe=row(EXE),Q=row(BUILD/'q/manifest.json')))
def host():
 m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);out=BUILD/'host-output'
 if out.exists():raise ValueError('preserve prior host output')
 r=run([EXE,'--host',BUILD,out,fixed],runtime(),False);(BUILD/'host.stdout').write_text(r.stdout,encoding='utf-8');(BUILD/'host.stderr').write_text(r.stderr,encoding='utf-8')
 save(BUILD/'host-attempt.json',dict(exit=r.returncode,manifest_sha256=fixed,stdout=row(BUILD/'host.stdout'),stderr=row(BUILD/'host.stderr')))
 if r.returncode or r.stderr:raise RuntimeError('host failed; logs retained')
 receipt=json.loads(r.stdout);q=q_binding()
 if receipt['source_id']!=m['compiled_id'] or receipt['GPU_used'] is not False or (out/'expert38-read.bin').read_bytes()!=Path(q['matrices'][0]['fixture_path']).read_bytes():raise ValueError('host exact source proof')
 binding(m)
 if sha(MANIFEST)!=fixed:raise ValueError('manifest changed')
 save(BUILD/'host-verification.json',dict(manifest_sha256=fixed,receipt=receipt,outputs=[row(out/'expert38-read.bin')],before_after_binding=True,GPU_used=False));print(receipt)
def validate_receipt(receipt,q,role):
 def integer(value):return type(value) is int and value>=0
 if receipt.get('context_physical') is not None or type(receipt.get('cache_tested')) is not bool:raise ValueError('receipt scope/type')
 if role=='secondary':
  if receipt['cache_tested'] or receipt.get('cycle_receipts')!=[] or receipt.get('capacity_receipts')!=[] or receipt.get('pipeline_receipts')!=[]:raise ValueError('secondary device-only scope')
  return
 if not receipt['cache_tested']:raise ValueError('cache not exercised')
 cycles=receipt.get('cycle_receipts',[]);expected={(slots,j['matrix'],j['batch'],cycle) for slots in (1,2) for j in q['jobs'] for cycle in range(4)};seen=set()
 if len(cycles)!=len(expected):raise ValueError('cycle coverage')
 for x in cycles:
  keys=('slots','matrix','batch','cycle','weight_read_delta','weight_h2d_delta','input_h2d_delta','output_d2h_delta')
  if set(x)!=set(keys) or any(not integer(x[k]) for k in keys):raise ValueError('cycle typed fields')
  key=tuple(x[k] for k in ('slots','matrix','batch','cycle'))
  if key not in expected or key in seen:raise ValueError('cycle identity/duplicate')
  seen.add(key);j=next(j for j in q['jobs'] if j['matrix']==x['matrix'] and j['batch']==x['batch']);raw=q['matrices'][x['matrix']]['bytes'];c=x['cycle']
  if x['weight_read_delta']!=(raw if c in (0,3) else 0) or x['weight_h2d_delta']!=(0 if c==1 else raw) or x['input_h2d_delta']!=j['batch']*j['k']*4 or x['output_d2h_delta']!=j['batch']*j['rows']*4:raise ValueError('actual cold/hot/RAM/refill transfer delta')
 capacities=receipt.get('capacity_receipts',[])
 if len(capacities)!=2 or {x.get('slots') for x in capacities}!={1,2}:raise ValueError('capacity configuration coverage')
 readback=read(BUILD/'host-verification.json')['receipt']['readback_capacity_expected']
 for x in capacities:
  if any(not integer(x.get(k)) for k in ['slots','device_owned','host_owned_pools_plus_retained_readback','stage_owned','event_not_ready_observations','readback_owner_capacity']):raise ValueError('typed capacity fields')
  if x['stage_owned'] not in [i*12533760 for i in range(5)] or x['readback_owner_capacity']!=readback or x['device_owned']!=x['slots']*12533760+327680 or x['host_owned_pools_plus_retained_readback']!=25067520+131072+x['stage_owned']+readback or x.get('full_host_peak') is not None:raise ValueError('actual allocation/alias/readback arithmetic')
  if x['pinned_subset'] is not None and (not integer(x['pinned_subset']) or x['pinned_subset']>x['stage_owned']):raise ValueError('pinned subset observation')
 pipeline=receipt.get('pipeline_receipts',[])
 cases=[x.get('case') for x in pipeline]
 if sorted(cases)!=sorted(['overlap','resident_pair','resident_pair','cancel_read','cancel_dma','prefetch_error','demand_preempt','ready_reservation']):raise ValueError('pipeline coverage')
 def live_pair(x,writer):
  nums=['consumer_slot','fill_slot','consumer_generation','fill_generation','consumer_readers','consumer_address','fill_address','consumer_stream','producer_stream','consumer_event','fill_event','issued_read_bytes']
  if any(not integer(x.get(k)) for k in nums) or x.get('consumer_kernel') is not True or x['consumer_readers']!=1 or x.get('fill_writer') is not writer:raise ValueError('pipeline live lease typed state')
  if x['consumer_slot']==x['fill_slot'] or x['consumer_address']==x['fill_address'] or x['consumer_stream']==x['producer_stream'] or any(x[k]==0 for k in nums if k not in ['consumer_slot','fill_slot']):raise ValueError('pipeline distinct physical ownership')
 def same_pair(a,b):
  if any(a[k]!=b[k] for k in ['consumer_slot','fill_slot','consumer_generation','fill_generation','consumer_address','fill_address','consumer_stream','producer_stream','consumer_event','fill_event']):raise ValueError('pipeline original lease identity')
 for x in pipeline:
  case=x['case']
  if case=='overlap':
   a,b=x['issued'],x['completed'];live_pair(a,True);live_pair(b,False);same_pair(a,b)
   if b.get('fill_done') is not True or x.get('fill_event_status')!=0 or any(type(x.get(k)) is not int for k in ['consumer_event_status_before','consumer_event_status_after']):raise ValueError('pipeline actual event evidence')
   if any(type(x.get(k)) is not int or x[k]!=q['matrices'][1]['bytes'] for k in ['weight_read_delta','weight_h2d_delta']):raise ValueError('parallel fill exact bytes')
  elif case=='ready_reservation':
   a,b=x['issued'],x['completed']
   for y,writer in [(a,True),(b,False)]:
    if y.get('consumer_ready') is not True or y.get('consumer_kernel') is not False or y.get('consumer_readers')!=1 or type(y.get('consumer_readers')) is not int or y.get('fill_writer') is not writer or y.get('consumer_slot')==y.get('fill_slot') or not y.get('consumer_generation') or not y.get('fill_generation'):raise ValueError('Ready demand continuous reservation')
   same_pair(a,b)
   if b.get('fill_done') is not True or any(x.get(k) is not True for k in ['correct_A','next_request','ready_cancel_released']):raise ValueError('Ready demand output/cancel/next')
  elif case=='resident_pair':
   if type(x.get('matrix')) is not int or x['matrix'] not in (0,1) or any(type(x.get(k)) is not int or x[k]!=0 for k in ['weight_read_delta','weight_h2d_delta']):raise ValueError('distinct GPU resident hit')
  elif case in ['cancel_read','cancel_dma']:
   live_pair(x['original'],True);live_pair(x['drained'],False);same_pair(x['original'],x['drained'])
   if x.get('not_published') is not True or x.get('next_request') is not True:raise ValueError('cancel/drain/next request')
  else:
   if x.get('not_published') is not True or x.get('next_request') is not True or (case=='prefetch_error' and x.get('consumer_retained') is not True):raise ValueError('error/preempt finite next request')
 if {x['matrix'] for x in pipeline if x['case']=='resident_pair'}!={0,1}:raise ValueError('two distinct resident hit coverage')
 last=next(x for x in capacities if x['slots']==1)
 for key,expected_value in [('device_owned',last['device_owned']),('host_owned',last['host_owned_pools_plus_retained_readback']),('pinned_subset',last['pinned_subset']),('gpu_hits',12),('ram_hits',12),('ssd_misses',29)]:
  if receipt.get(key)!=expected_value or (expected_value is not None and not integer(receipt[key])):raise ValueError('aggregate allocation/hit identity')
 raw_total=sum(q['matrices'][j['matrix']]['bytes'] for j in q['jobs']);first=q['matrices'][0];input_total=sum(j['batch']*j['k']*4 for j in q['jobs']);output_total=sum(j['batch']*j['rows']*4 for j in q['jobs'])
 exact={'weight_h2d':3*raw_total+3*first['bytes'],'input_h2d':4*input_total+2*first['dims_ggml'][0]*4,'output_d2h':4*output_total+first['dims_ggml'][1]*4}
 for key,value in exact.items():
  if not integer(receipt.get(key)) or receipt[key]!=value:raise ValueError('aggregate exact transfer arithmetic')
 minimum_read=2*raw_total+3*first['bytes']
 if not integer(receipt.get('weight_read')) or not minimum_read<=receipt['weight_read']<=minimum_read+131072:raise ValueError('aggregate SSD logical bytes with bounded issued-cancel window')
 stages=receipt.get('stages',[])
 if len(stages)!=4:raise ValueError('actual stage inventory')
 for x in stages:
  if type(x.get('query_attempted')) is not bool or not integer(x.get('address')) or not integer(x.get('capacity')):raise ValueError('stage observation types')
  if not x['query_attempted']:
   if x.get('status') is not None or x.get('type') is not None:raise ValueError('unattempted stage unknown')
  elif type(x.get('status')) is not int or (x['status']!=0 and x.get('type') is not None):raise ValueError('failed stage unknown')
 if sum(x['capacity'] for x in stages)!=last['stage_owned']:raise ValueError('stage capacity aliases')
 if role=='pageable' and (receipt['pinned_observed'] is not False or any(x['address'] or x['capacity'] or x['query_attempted'] for x in stages)):raise ValueError('forced pageable is separate direct fallback')
 if receipt['pinned_observed']:
  if len({x['address'] for x in stages})!=4 or any(not x['query_attempted'] or x['status']!=0 or x['type']!=1 or x['capacity']!=12533760 for x in stages):raise ValueError('pinned success requires actual distinct stage properties')
def execute(role):
 m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);q=q_binding();pci='0000:07:00.0' if role!='secondary' else '0000:03:00.0';out=BUILD/(role+'-output')
 if out.exists():raise ValueError('preserve previous GPU attempt')
 env=runtime()
 if role=='pageable':env['STRATA_TEST_PAGEABLE']='1'
 else:env.pop('STRATA_TEST_PAGEABLE',None)
 save(BUILD/(role+'-process-environment.json'),{k:env.get(k) for k in ['PATH','HIP_PATH','ROCM_PATH','HIP_PLATFORM','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES','GPU_DEVICE_ORDINAL','HSA_OVERRIDE_GFX_VERSION']})
 start=time.monotonic();r=run([EXE,'--device' if role=='secondary' else '--gpu',pci,BUILD,out,fixed],env,False,600);(BUILD/(role+'.stdout')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'.stderr')).write_text(r.stderr,encoding='utf-8')
 proof=dict(manifest_sha256=fixed,artifact=row(EXE),exit=r.returncode,seconds=time.monotonic()-start,status='not_passed');save(BUILD/(role+'-verification.json'),proof)
 if r.returncode or r.stderr:raise RuntimeError('GPU failed; preserve attempt, no blind retry')
 receipt=json.loads(r.stdout);outputs=[];compared=0
 if receipt['source_id']!=m['compiled_id'] or receipt['pci']!=pci:raise ValueError('actual device/source binding')
 validate_receipt(receipt,q,role)
 for j in q['jobs']:
  expected=Path(j['expected']['path']).read_bytes();names=[f'direct-m{j["matrix"]}-B{j["batch"]}.bin']
  if role!='secondary':names += [f'cache-S{s}-m{j["matrix"]}-B{j["batch"]}-C{c}.bin' for s in (1,2) for c in range(4)]
  for name in names:
   p=out/name
   if p.read_bytes()!=expected or p.stat().st_size%4:raise ValueError('all ordered output bits/exact bytes: '+name)
   outputs.append(row(p));compared+=len(expected)//4
 if role!='secondary':
  for matrix,names in [(0,['overlap-m0.bin','pair-m0.bin','cancel-read-next.bin','cancel-dma-next.bin','error-consumer.bin','preempt-next.bin','ready-A.bin']),(1,['pair-m1.bin','error-next.bin','ready-next.bin'])]:
   j=next(j for j in q['jobs'] if j['matrix']==matrix and j['batch']==1);expected=Path(j['expected']['path']).read_bytes()
   for name in names:
    p=out/name
    if p.read_bytes()!=expected or p.stat().st_size%4:raise ValueError('pipeline exact output bits: '+name)
    outputs.append(row(p));compared+=len(expected)//4
 loaded=[row(p) for p in receipt['loaded_modules'] if Path(p).name.lower() in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']]
 if len(loaded)!=3 or any(Path(x['path']).resolve().parent!=BUNDLE.resolve() or x['sha256']!=sha(BUNDLE/Path(x['path']).name) for x in loaded):raise ValueError('actual loaded DLL binding')
 binding(m)
 if sha(MANIFEST)!=fixed:raise ValueError('manifest changed')
 proof.update(status='pass',receipt=receipt,loaded_DLL=loaded,outputs=outputs,compared_values=compared,before_after_binding=True,full_source_qualified=False);save(BUILD/(role+'-verification.json'),proof);print(dict(status='pass',role=role,values=compared,proof=row(BUILD/(role+'-verification.json'))))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['build','host','execute']);p.add_argument('--role',choices=['primary','secondary','pageable']);a=p.parse_args();BUILD.mkdir(exist_ok=True)
 if a.mode=='execute':execute(a.role)
 else:globals()[a.mode]()
