"""T21 owned build, pre-G byte oracle, captures and exact CPU verification."""
import argparse,copy,hashlib,importlib.util,json,os,shutil,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t21';BUNDLE=BUILD/'bundle';EXE=BUNDLE/'t21-device.exe';MANIFEST=BUILD/'manifest.json'
COMPILED=[EXT/p for p in ['native/device/roles.hpp','native/device/roles.hip','tests/device/fixture.hip']];RECIPES=[HERE/n for n in ['CMakeLists.txt','reference.py','contract.json','build_verify.py']]
SDK=Path('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel')
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
 m=load('T21_existing_readonly_toolchain_recipe',EXT/'tests/cache/build_verify.py');m.BUILD=BUILD;return m.environment()
def runtime():
 _,env=environment();windows=Path(os.environ['SystemRoot']);env['PATH']=os.pathsep.join(map(str,[BUNDLE,windows/'System32',windows]))
 for name in ['HIP_PATH','ROCM_PATH','HIP_PLATFORM','INCLUDE','LIB']:env.pop(name,None)
 env['PYTHONDONTWRITEBYTECODE']='1';return env
def check_rows(rows):
 for x in rows:
  if row(x['path'])!=x:raise ValueError('fixed disk binding: '+x['path'])
def compiled_id():return hashlib.sha256(''.join(p.relative_to(ROOT).as_posix()+'|'+sha(p)+'\n' for p in COMPILED).encode()).hexdigest()
def q_binding():
 q=read(BUILD/'q/manifest.json')
 if q['G_executed'] is not False:raise ValueError('not pre-G Q')
 check_rows([q['contract'],q['reference'],q['expected']]);return q
def binding(m):
 if m['compiled_id']!=compiled_id() or m['compiled']!=list(map(row,COMPILED)) or m['recipes']!=list(map(row,RECIPES)):raise ValueError('source/recipe binding')
 for key in ['dependencies','inputs','bundle_files','tools']:check_rows(m[key])
 q_binding()
 if run(['git','rev-parse','HEAD']).stdout.strip()!=m['base'] or run(['git','diff','HEAD','--name-only']).stdout.strip():raise ValueError('upstream changed')
def prepare():
 q=load('T21_independent_oracle',HERE/'reference.py').prepare();print('pre-G expected',q['expected'])
def build():
 q=q_binding();tools,env=environment();BUNDLE.mkdir(exist_ok=True)
 if MANIFEST.exists():raise ValueError('preserve previous fixed trial')
 out=BUILD/'cmake';cmd=[tools['cmake'],'--fresh','-S',HERE,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 commands=[cmd,[tools['cmake'],'--build',out,'--verbose']]
 for i,command in enumerate(commands):
  result=run(command,env,False);(BUILD/f'build-{i}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
  if result.returncode:raise RuntimeError('native build failed; log retained')
 shutil.copy2(out/'bundle/t21-device.exe',EXE);origins=[]
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
  src=SDK/'bin'/name;dst=BUNDLE/name;shutil.copy2(src,dst);origins.append(dict(source=row(src),target=row(dst)))
 licenses=BUNDLE/'licenses';licenses.mkdir(exist_ok=True)
 for src in (ROOT/'build-deepseek-t13/bundle/licenses').rglob('*'):
  if src.is_file():shutil.copy2(src,licenses/src.name)
 deps=run([tools['ninja'],'-C',out,'-t','deps'],env).stdout;(BUILD/'compiler-deps.log').write_text(deps,encoding='utf-8');paths=set()
 for line in deps.splitlines():
  if line.startswith('    '):
   p=Path(line.strip());p=p if p.is_absolute() else out/p
   if p.is_file() and p.resolve().is_relative_to(ROOT.resolve()) and p.resolve() not in {x.resolve() for x in COMPILED}:paths.add(p.resolve())
 paths.add(EXT/'tests/cache/build_verify.py')
 for label,command in [('imports',[tools['dumpbin'],'/DEPENDENTS',EXE]),('offloading',[tools['objdump'],'--offloading',EXE])]:
  text=run(command,env).stdout;(BUILD/(label+'.log')).write_text(text,encoding='utf-8')
  if label=='offloading' and not all(x in text for x in ['gfx1100','gfx1201']):raise ValueError('expected compile code objects')
 m=dict(schema='T21-native-capture/v1',compiled_id=compiled_id(),compiled=list(map(row,COMPILED)),recipes=list(map(row,RECIPES)),dependencies=list(map(row,sorted(paths))),inputs=list(map(row,[BUILD/'capacity-start.json',BUILD/'pre-v1.md',BUILD/'q/manifest.json',Path(q['expected']['path'])])),bundle_files=[row(p) for p in sorted(BUNDLE.rglob('*')) if p.is_file()],tools=list(map(row,list(tools.values())+[Path(sys.executable)])),dll_origins=origins,base=run(['git','rev-parse','HEAD']).stdout.strip(),commands=[list(map(str,c)) for c in commands],patches=[],normal_copy_audit_D2H=False)
 save(MANIFEST,m);binding(m)
 if json.loads(run([EXE,'--identity'],runtime()).stdout)['source_id']!=m['compiled_id']:raise ValueError('binary identity')
 print(dict(manifest=row(MANIFEST),exe=row(EXE)))
def host():
 m=read(MANIFEST);binding(m);r=run([EXE,'--host'],runtime());receipt=json.loads(r.stdout)
 if r.stderr or receipt['source_id']!=m['compiled_id'] or receipt['GPU_used'] is not False or receipt['assertions']<10:raise ValueError('host fixture')
 binding(m);save(BUILD/'host-verification.json',dict(receipt=receipt,manifest=row(MANIFEST),before_after_binding=True));print(receipt)
def seal():
 m=read(MANIFEST);binding(m);h=read(BUILD/'host-verification.json')
 if h['manifest']!=row(MANIFEST):raise ValueError('host calibration')
 save(BUILD/'pre-G.json',dict(manifest=row(MANIFEST),host=row(BUILD/'host-verification.json'),Q=row(BUILD/'q/manifest.json')));print(row(BUILD/'pre-G.json'))
def pinning(p):
 if len(p['stages'])!=4 or type(p['stage_bytes']) is not int:raise ValueError('stage capacity')
 total=0;pinned=0;known=True;addresses=set()
 for a,n,status,kind in p['stages']:
  if type(a) is not int or type(n) is not int or n not in (0,65536) or a<0:raise ValueError('stage types')
  if not n:
   if a or status is not None or kind is not None:raise ValueError('unattempted stage unknown')
  else:
   if not a or a in addresses or type(status) is not int:raise ValueError('distinct allocated stage')
   addresses.add(a);total+=n
   if status==0:
    if type(kind) is not int or kind<0:raise ValueError('memory type')
    if kind==1:pinned+=n
   elif kind is not None:raise ValueError('failure type unknown')
   else:known=False
 if total!=p['stage_bytes'] or (known and (type(p['pinned_subset']) is not int or p['pinned_subset']!=pinned)) or (not known and p['pinned_subset'] is not None):raise ValueError('exact observed pinned bytes')
def validate(receipt,pair):
 q=q_binding();n_devices=2 if pair else 1
 if len(receipt['pools'])!=n_devices or (receipt['secondary'] is None)==pair or receipt['cancel_drain_next'] is not True or receipt['late_completion_next'] is not True or receipt['Ready_cancel_last_use'] is not True or receipt['overlap_actual_bytes_checked'] is not True:raise ValueError('role/cancel coverage')
 if pair and receipt['primary']['pci']==receipt['secondary']['pci']:raise ValueError('role identity collision')
 if type(receipt['copy_metadata_bytes']) is not int or receipt['copy_metadata_bytes']!=read(BUILD/'host-verification.json')['receipt']['metadata_bytes']:raise ValueError('metadata ABI')
 roles=[receipt['primary']]+([receipt['secondary']] if pair else [])
 if pair and roles[0]['ordinal']==roles[1]['ordinal']:raise ValueError('duplicate role ordinal')
 for role in roles:
  if type(role['ordinal']) is not int or role['ordinal']<0 or not role['pci']:raise ValueError('physical role')
  if type(role['property_status']) is not int or (role['property_status']==0 and (not isinstance(role['name'],str) or not isinstance(role['arch'],str))) or (role['property_status']!=0 and (role['name'] is not None or role['arch'] is not None)):raise ValueError('property query unknown')
  for name in ['uuid','luid']:
   status=role[name+'_status']
   if type(status) is not int or (status==0 and not isinstance(role[name],str)) or (status!=0 and role[name] is not None):raise ValueError('identity query unknown')
 for role,p in zip(roles,receipt['pools']):
  if type(p['device']) is not int or p['device']!=role['ordinal'] or type(p['memory_status']) is not int or (p['memory_status']==0 and (type(p['free_bytes']) is not int or p['free_bytes']<0)) or (p['memory_status']!=0 and p['free_bytes'] is not None):raise ValueError('actual role/memory unknown')
  if type(p['device_bytes']) is not int or p['device_bytes']!=131072:raise ValueError('actual arena capacity')
  pinning(p)
 if type(receipt['bounce_pinned']) is not bool or receipt['bounce_bytes']!=(65536 if pair else 0) or type(receipt['bounce_bytes']) is not int or receipt['host_expected_readback']!=131072 or type(receipt['host_expected_readback']) is not int or receipt['physical_driver_peak'] is not None:raise ValueError('host/unknown accounting')
 if type(receipt['bounce_allocation_status']) is not int or receipt['bounce_pinned'] is not (receipt['bounce_allocation_status']==0):raise ValueError('bounce allocation pinning status')
 if receipt['bounce_query_status'] is None:
  if receipt['bounce_memory_type'] is not None:raise ValueError('bounce query unattempted unknown')
 elif type(receipt['bounce_query_status']) is not int or (receipt['bounce_query_status']==0 and type(receipt['bounce_memory_type']) is not int) or (receipt['bounce_query_status']!=0 and receipt['bounce_memory_type'] is not None):raise ValueError('bounce query type/unknown')
 directions=2 if pair else 1;policies=2 if pair else 1;expected={(d,p,n) for d in range(directions) for p in range(policies) for n in q['lengths']};seen=set()
 for x in receipt['cases']:
  for k in ['direction','policy','bytes','peer_bytes','local_d2d','bounce_d2h','bounce_h2d','capability_status','can_access','enable_status','peer_copy_status','disable_status','return_record_status','return_drain_status']:
   if type(x[k]) is not int:raise ValueError('typed transfer counter/status')
  key=(x['direction'],x['policy'],x['bytes']);n=x['bytes']
  if key not in expected or key in seen or x['name']!=f'd{key[0]}p{key[1]}n{n}':raise ValueError('direction/case coverage')
  seen.add(key);path=x['path'];counts=[x[k] for k in ['peer_bytes','local_d2d','bounce_d2h','bounce_h2d']]
  if not n:
   if path!='none' or counts!=[0,0,0,0] or any(x[k]!=-1 for k in ['capability_status','can_access','enable_status','peer_copy_status','disable_status','return_record_status','return_drain_status']):raise ValueError('zero copy traffic')
  elif not pair:
   if path!='local' or counts!=[0,n,0,0] or any(x[k]!=-1 for k in ['capability_status','can_access','enable_status','peer_copy_status','disable_status']):raise ValueError('single local/no peer')
  elif path=='host-bounce':
   if counts!=[0,0,n,n]:raise ValueError('exact two bounce legs')
   if key[1]==0:
    if x['capability_status']==-1:raise ValueError('auto capability was not queried')
    if x['capability_status']!=0 or x['can_access']==0:
     if x['can_access']!=(-1 if x['capability_status']!=0 else 0) or any(x[k]!=-1 for k in ['enable_status','peer_copy_status','disable_status']):raise ValueError('unattempted peer stages')
    elif x['can_access']==1:
     if x['enable_status'] in (0,704):
      if x['peer_copy_status'] in (-1,0) or x['disable_status']!=(0 if x['enable_status']==0 else -1):raise ValueError('failed peer before bounce/cleanup')
     elif x['peer_copy_status']!=-1 or x['disable_status']!=-1:raise ValueError('enable failed before copy')
    else:raise ValueError('capability result')
  elif path=='peer':
   if key[1]!=0 or counts!=[n,0,0,0] or x['capability_status']!=0 or x['can_access']!=1 or x['peer_copy_status']!=0:raise ValueError('actual peer path')
  else:raise ValueError('unqualified transfer path')
  if n and (x['return_record_status']!=0 or x['return_drain_status']!=-1):raise ValueError('actual last-use event status')
  if pair and key[1]==1 and n and (path!='host-bounce' or any(x[k]!=-1 for k in ['capability_status','can_access','enable_status','peer_copy_status','disable_status'])):raise ValueError('forced bounce has no peer API attempt')
  if path=='peer' and x['enable_status']==0 and x['disable_status']!=0:raise ValueError('owned peer enable cleanup')
  if path=='peer' and x['enable_status'] not in (0,704):raise ValueError('actual peer enable status')
 if seen!=expected:raise ValueError('missing transfer case')
 for k,v in dict(fixture_readback=q['per_direction_payload']*directions*policies,fixture_upload=q['fixture_H2D_per_direction']*directions*policies,control_fixture_upload=792,control_transfer_bytes=1056,control_bounce_d2h=792 if pair else 0,control_bounce_h2d=792 if pair else 0,control_local_d2d=264 if pair else 1056,control_readback=792).items():
  if type(receipt[k]) is not int or receipt[k]!=v:raise ValueError('fixture versus native traffic: '+k)
def execute(mode):
 m=read(MANIFEST);binding(m);pre=read(BUILD/'pre-G.json');check_rows(list(pre.values()));fixed=sha(MANIFEST);pair=mode!='single';env=runtime();env.pop('STRATA_TEST_PAGEABLE',None)
 if mode=='pageable':env['STRATA_TEST_PAGEABLE']='1'
 out=BUILD/(mode+'-output')
 if out.exists():raise ValueError('preserve prior native attempt')
 r=run([EXE,'--gpu','0000:07:00.0','0000:03:00.0' if pair else 'none',BUILD,out,fixed],env,False);(BUILD/(mode+'.stdout')).write_text(r.stdout,encoding='utf-8');(BUILD/(mode+'.stderr')).write_text(r.stderr,encoding='utf-8');save(BUILD/(mode+'-verification.json'),dict(status='not_passed',exit=r.returncode))
 if r.returncode or r.stderr:raise RuntimeError('native failed; evidence preserved')
 receipt=json.loads(r.stdout)
 if receipt['source_id']!=m['compiled_id'] or receipt['binding']!=fixed or receipt['primary']['pci']!='0000:07:00.0' or pair and receipt['secondary']['pci']!='0000:03:00.0':raise ValueError('actual identity/bundle')
 validate(receipt,pair);q=q_binding();expected=Path(q['expected']['path']).read_bytes();outputs=[]
 for x in receipt['cases']:
  p=out/(x['name']+'.bin')
  if p.read_bytes()!=expected[:x['bytes']]:raise ValueError('full destination byte arrival: '+p.name)
  outputs.append(row(p))
 loaded=[row(p) for p in receipt['loaded_modules'] if Path(p).name.lower() in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']]
 if len(loaded)!=3 or any(Path(x['path']).resolve().parent!=BUNDLE.resolve() or x['sha256']!=sha(BUNDLE/Path(x['path']).name) for x in loaded):raise ValueError('loaded runtime path/SHA')
 binding(m);check_rows(list(pre.values()));save(BUILD/(mode+'-verification.json'),dict(status='pass',manifest=row(MANIFEST),preG=row(BUILD/'pre-G.json'),artifact=row(EXE),receipt=receipt,outputs=outputs,loaded_DLL=loaded,before_after_binding=True,normal_audit_D2H=False));print(dict(mode=mode,cases=len(outputs),proof=row(BUILD/(mode+'-verification.json'))))
def negatives():
 m=read(MANIFEST);binding(m);proof=read(BUILD/'pair-verification.json');base=proof['receipt'];validate(base,True);checks=[]
 def reject(name,fn):
  try:fn()
  except (ValueError,KeyError,TypeError,AssertionError,IndexError):checks.append(name);return
  raise AssertionError('negative accepted: '+name)
 for flag in ['cancel_drain_next','late_completion_next','Ready_cancel_last_use','overlap_actual_bytes_checked']:
  x=copy.deepcopy(base);x[flag]=False;reject(flag,lambda x=x:validate(x,True))
 for i,case in enumerate(base['cases']):
  for key in ['bytes','peer_bytes','local_d2d','bounce_d2h','bounce_h2d']:
   for v in [0,-1,True,case[key]+1]:
    if type(v) is int and v==case[key]:continue
    x=copy.deepcopy(base);x['cases'][i][key]=v;reject(f'case{i}-{key}-{v}',lambda x=x:validate(x,True))
 for key in ['fixture_readback','fixture_upload','control_fixture_upload','control_transfer_bytes','control_readback','control_bounce_d2h','control_bounce_h2d','control_local_d2d','bounce_bytes','host_expected_readback','copy_metadata_bytes']:
  for v in [0,-1,True,base[key]+1]:
   if type(v) is int and v==base[key]:continue
   x=copy.deepcopy(base);x[key]=v;reject(key+str(v),lambda x=x:validate(x,True))
 for key in ['pinned_subset','stage_bytes','device_bytes']:
  for v in [0,-1,True,base['pools'][0][key]+1]:
   if type(v) is int and v==base['pools'][0][key]:continue
   x=copy.deepcopy(base);x['pools'][0][key]=v;reject(key+str(v),lambda x=x:validate(x,True))
 x=copy.deepcopy(base);x['cases'].pop();reject('missing case',lambda:validate(x,True));x=copy.deepcopy(base);x['cases'].append(copy.deepcopy(x['cases'][0]));reject('duplicate case',lambda:validate(x,True))
 for mode in ['single','pair']:
  native=read(BUILD/(mode+'-verification.json'))['receipt'];is_pair=mode=='pair'
  for i,item in enumerate(native['cases']):
   if item['bytes']==0 or not is_pair:
    fields=['capability_status','can_access','enable_status','peer_copy_status','disable_status'] if item['bytes']==0 else ['disable_status']
    for field in fields:
     x=copy.deepcopy(native);x['cases'][i][field]=0 if field!='can_access' else 1;reject(mode+'-unattempted-'+str(i)+'-'+field,lambda x=x,is_pair=is_pair:validate(x,is_pair))
 expected=Path(q_binding()['expected']['path']).read_bytes();out=BUILD/'negative-files';out.mkdir(exist_ok=True);p=out/'actual.bin'
 for name,data in [('append',expected+b'X'),('truncate',expected[:-1]),('bitflip',bytes([expected[0]^1])+expected[1:])]:
  p.write_bytes(data)
  def compare():
   if p.read_bytes()!=expected:raise ValueError('exact body bytes')
  reject(name,compare)
 binding(m);save(BUILD/'negative-verification.json',dict(rejections=len(checks),positive_capture=True,checks=checks,validator=row(HERE/'build_verify.py'),manifest=row(MANIFEST),GPU_used=False));print('CPU rejects',len(checks))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','build','host','seal','execute','negatives']);p.add_argument('--role',choices=['single','pair','pageable']);a=p.parse_args();BUILD.mkdir(exist_ok=True)
 if a.mode=='execute':execute(a.role)
 else:globals()[a.mode]()
