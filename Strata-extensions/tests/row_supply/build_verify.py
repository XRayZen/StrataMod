"""Owned T19 build/receipts. Explicit execute alone creates GPU contexts."""
import argparse,copy,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t19';BUNDLE=BUILD/'bundle';EXE=BUNDLE/'t19-rows.exe';MANIFEST=BUILD/'manifest.json'
SDK=Path('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel')
COMPILED=[EXT/p for p in ['native/cache/row_supply.hpp','native/cache/row_supply.hip','tests/row_supply/fixture.hip']]
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
def source_contract(q,source_lines=None,prefix_lines=None,row_lines=None):
 inventory=EXT/'tests/artifact/header-inventory.json';sources=EXT/'tests/artifact/source-files.json'
 for p,h in [(inventory,'08583c5cff84627962517db22ec877a69fd1aed3a811eb010d2f2f3e2f84366b'),(sources,'3c226d451f4b3a0b6b12b69fab492e559226bc23c6d02fcf926964bf33178ec6')]:
  if sha(p)!=h:raise ValueError('fixed T03 identity')
 inv=read(inventory);src=read(sources)
 source_lines=source_lines if source_lines is not None else (BUILD/'sources.tsv').read_text(encoding='utf-8').splitlines()
 prefix_lines=prefix_lines if prefix_lines is not None else (BUILD/'prefixes.tsv').read_text(encoding='utf-8').splitlines()
 row_lines=row_lines if row_lines is not None else (BUILD/'rows.tsv').read_text(encoding='utf-8').splitlines()
 if len(source_lines)!=9 or len(prefix_lines)!=9 or len(row_lines)!=96:raise ValueError('source/view coverage')
 for line,prefix,f,header in zip(source_lines,prefix_lines,src['files'],inv['shards']):
  i,size,lfs,revision,path=line.split('\t');logical,prefix_path=prefix.split('\t')
  if (int(i),int(size),lfs,revision,Path(path).name)!=(f['index'],f['bytes'],f['lfs_sha256'],src['revision'],Path(f['filename']).name):raise ValueError('source identity')
  if int(logical)!=f['bytes'] or Path(prefix_path)!=Path(header['prefix_path']) or row(prefix_path)['bytes']!=header['prefix_bytes'] or sha(prefix_path)!=header['prefix_sha256']:raise ValueError('strict prefix binding')
 for row_index,(line,x) in enumerate(zip(row_lines,q['rows'])):
  pos,layer,head,local,globalrow,offset,path=line.split('\t');t=x['tuple']
  if tuple(map(int,[pos,layer,head,local,globalrow,offset]))!=(row_index,t[1],(t[2]-2)*8+t[3],t[4],t[5],x['absolute_offset']) or Path(path)!=Path(x['path']):raise ValueError('row logical identity')
  if x['revision']!=src['revision'] or x['shard_index']!=8 or x['lfs_sha256']!=src['files'][7]['lfs_sha256'] or x['file_bytes']!=src['files'][7]['bytes'] or x['bytes']!=264 or x['row_bytes']!=264 or x['type_id']!=43 or x['dims_ggml']!=[256,768022850]:raise ValueError('row native source/layout')
  http=x['http']
  if (http['status'],http['start'],http['end'],http['total'],http['content_length'])!=(206,x['absolute_offset'],x['absolute_offset']+263,x['file_bytes'],264) or not http['etag']:raise ValueError('fixed bounded HTTP provenance')

def q_binding():
 q=read(BUILD/'q/manifest.json')
 if q['G_executed'] is not False:raise ValueError('Q not pre-G')
 check_rows(q['references']+q['expected'])
 for x in q['rows']:check_rows([{k:x[k] for k in ['path','bytes','sha256']}])
 source_contract(q)
 return q

def binding(m):
 if m['compiled']!=list(map(row,COMPILED)) or m['recipes']!=list(map(row,RECIPES)) or m['compiled_id']!=compiled_id():raise ValueError('source binding')
 for key in ['dependencies','inputs','bundle_files','tools']:check_rows(m[key])
 q_binding()
 if run(['git','rev-parse','HEAD']).stdout.strip()!=m['upstream_base'] or run(['git','diff','HEAD','--name-only']).stdout.strip():raise ValueError('upstream changed')

def prepare():
 for src,name in [(ROOT/'build-deepseek-t10/sources.tsv','sources.tsv'),(ROOT/'build-deepseek-t10/nine-prefixes.tsv','prefixes.tsv'),(ROOT/'build-deepseek-t13/rows.tsv','rows.tsv')]:shutil.copy2(src,BUILD/name)
 load('T19_preG_reference',HERE/'reference.py').prepare()
 print('Q fixed',row(BUILD/'q/manifest.json'))

def build():
 q=q_binding();tools,env=environment();BUNDLE.mkdir(exist_ok=True)
 a=load('T19_individual_final_provenance',EXT/'tests/ffn/acquire_fixtures.py');a.finalized(2);f=next(x for x in read(EXT/'tests/ffn/fixture-receipts.json')['fixtures'] if x['tensor']=='blk.0.ffn_up_exps.weight' and x['index']==38);
 if sha(f['fixture_path'])!=f['fixture_sha256']:raise ValueError('fixed expert raw SHA')
 (BUILD/'expert.tsv').write_text(f['source']['path']+'\t'+str(f['source']['bytes'])+'\t'+str(f['absolute_offset'])+'\t'+f['fixture_path']+'\n',encoding='utf-8')
 if MANIFEST.exists():raise ValueError('preserve prior fixed trial')
 out=BUILD/'cmake';cmd=[tools['cmake'],'--fresh','-S',HERE,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 commands=[cmd,[tools['cmake'],'--build',out,'--verbose']]
 for i,command in enumerate(commands):
  result=run(command,env,False);(BUILD/f'build-{i}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
  if result.returncode:raise RuntimeError('build failed; logs preserved')
 shutil.copy2(out/'bundle/t19-rows.exe',EXE);origins=[]
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
 for label,command in [('imports',[tools['dumpbin'],'/DEPENDENTS',EXE]),('offloading',[tools['objdump'],'--offloading',EXE])]:
  result=run(command,env);(BUILD/(label+'.log')).write_text(result.stdout,encoding='utf-8')
  if label=='offloading' and not all(x in result.stdout for x in ['gfx1100','gfx1201']):raise ValueError('code objects missing')
 inputs=[BUILD/'expert.tsv',ROOT/'Strata-extensions/tests/ffn/fixture-receipts.json']+[BUILD/n for n in ['capacity-start.json','sources.tsv','prefixes.tsv','rows.tsv','q/manifest.json']]+[Path(x['path']) for x in q['rows']+q['expected']]
 inputs += [Path(f['fixture_path']),EXT/'tests/ffn/acquire_fixtures.py',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json']
 inputs += [Path(line.split('\t')[1]) for line in (BUILD/'prefixes.tsv').read_text().splitlines()]
 m=dict(schema='T19-fixed-trial/v1',compiled=list(map(row,COMPILED)),recipes=list(map(row,RECIPES)),compiled_id=compiled_id(),dependencies=list(map(row,sorted(paths))),inputs=list(map(row,inputs)),bundle_files=[row(p) for p in sorted(BUNDLE.rglob('*')) if p.is_file()],tools=list(map(row,list(tools.values())+[Path(sys.executable)])),dll_origins=origins,upstream_base=run(['git','rev-parse','HEAD']).stdout.strip(),commands=[list(map(str,c)) for c in commands],patches=[],full_source_qualified=False)
 save(MANIFEST,m);binding(m)
 if json.loads(run([EXE,'--identity'],runtime()).stdout)['source_id']!=m['compiled_id']:raise ValueError('binary source ID')
 print(dict(manifest=row(MANIFEST),exe=row(EXE)))

def host():
 m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);out=BUILD/'host-output'
 if out.exists():raise ValueError('preserve prior host attempt')
 r=run([EXE,'--host',BUILD,out,fixed],runtime(),False);(BUILD/'host.stdout').write_text(r.stdout,encoding='utf-8');(BUILD/'host.stderr').write_text(r.stderr,encoding='utf-8')
 if r.returncode or r.stderr:raise RuntimeError('host failed; logs retained')
 receipt=json.loads(r.stdout);q=q_binding();expected=b''.join(Path(x['path']).read_bytes() for x in q['rows'])
 outputs=[]
 for i in range(3):
  p=out/f'rows-path{i}.bin'
  if p.read_bytes()!=expected:raise ValueError('native host exact row bytes')
  outputs.append(row(p))
 binding(m);assert sha(MANIFEST)==fixed
 save(BUILD/'host-verification.json',dict(manifest_sha256=fixed,receipt=receipt,outputs=outputs,before_after_binding=True,GPU_used=False));print(receipt)

def validate(receipt):
 for key in ['grant_zero_checked','Ready_protected','kernel_earlyreuse_rejected','all_cancel_drained','source_error_next']:
  if receipt.get(key) is not True:raise ValueError('native lifetime/grant case: '+key)
 if type(receipt.get('cancelled_waiter_storage_phases')) is not int or receipt['cancelled_waiter_storage_phases']!=3:raise ValueError('shared owned storage phases')
 expected={'coldA':(264,264),'GPU-A':(0,0),'coldB':(264,264),'GPU-ABA':(0,0),'RAM-A':(0,264),'SSD-A':(264,264)}
 rows=receipt['trace'];seen=set()
 for x in rows:
  if type(x['slots']) is not int or x['slots'] not in (1,2) or x['case'] not in expected or (x['slots']==1 and x['case'] in ['coldB','GPU-ABA']):raise ValueError('trace identity')
  key=(x['slots'],x['case'])
  if key in seen or any(type(x[k]) is not int or x[k]!=v for k,v in zip(['read','H2D'],expected[x['case']])):raise ValueError('manual exact trace')
  seen.add(key)
 if len(seen)!=10:raise ValueError('trace coverage')
 joint=receipt['joint']
 expected_joint={'order':['Expert','Row']*4,'logical':263200,'requested':294912,'received':279584,'weight_h2d':263200,'readback':263200,'host_pool':524288,'device_pool':131072,'remaining_jobs':0,'remaining_credits':0,'physical_path':None}
 for k,v in expected_joint.items():
  if joint.get(k)!=v or (type(v) is int and type(joint[k]) is not int):raise ValueError('joint fair real I/O/capacity: '+k)
 capacities=receipt['capacities']
 if len(capacities)!=3:raise ValueError('capacity coverage')
 host=read(BUILD/'host-verification.json')['receipt'];layout=host['layout']
 for slots,x in zip([8,2,1],capacities):
  for k,v in x.items():
   if k not in ['pinned_subset','pinned_observed','stages','physical_driver_peak'] and type(v) is not int:raise ValueError('integer capacity/counter: '+k)
  expected_device=((slots*264+255)//256)*256+2048
  if type(x['device_owned']) is not int or x['device_owned']!=expected_device:raise ValueError('actual device capacity')
  if x['stage_owned'] not in [0,65536,131072,196608,262144] or type(x['stage_owned']) is not int or x['host_payload']!=13952+x['stage_owned']:raise ValueError('payload/alignment/alias capacity')
  lookup,key=(8,8) if slots==8 else (4,2)
  if x['lookup_capacity']!=lookup or x['key_capacity']!=key or x['binding_heap']!=host['binding_heap'] or x['identity_heap']!=host['all_identity_heap' if slots==8 else 'shared_identity_heap']:raise ValueError('retained container/identity capacities')
  meta=layout[0]+slots*layout[1]+16*layout[2]+8*layout[3]+96*layout[4]+2*layout[5]+4*32+lookup*16+key*8+x['binding_heap']+x['identity_heap']
  if type(x['metadata_capacity']) is not int or x['metadata_capacity']!=meta:raise ValueError('metadata alias/heap/layout arithmetic')
  count=96 if slots==8 else 9 if slots==2 else 7
  expected_exact={'ssd_misses':count,'issued':count,'requested_read':count*4096,'received':count*264,'weight_h2d':(96 if slots==8 else 9 if slots==2 else 7)*264,'index_h2d':(96 if slots==8 else 16 if slots==2 else 10)*4,'output_d2h':(96 if slots==8 else 16 if slots==2 else 10)*1540,'ram_hits':0 if slots==8 else 1,'gpu_hits':0 if slots==8 else 7 if slots==2 else 3,'dedup':0 if slots==8 else 4}
  for k,v in expected_exact.items():
   if type(x.get(k)) is not int or x[k]!=v:raise ValueError('actual aggregate operation/lifetime: '+k)
  minimum=(96 if slots==8 else 8 if slots==2 else 6)*264
  if type(x['logical_read']) is not int or not minimum<=x['logical_read']<=minimum+(0 if slots==8 else 264):raise ValueError('cancel issued read logical window')
  if type(x['observed_host_payload_peak']) is not int or x['observed_host_payload_peak']!=x['host_payload']+(12288 if slots==8 else 4608) or type(x['observed_metadata_peak']) is not int or x['observed_metadata_peak']<x['metadata_capacity'] or x['active_io_wrapper_metadata']!=0:raise ValueError('observed lifetime peaks/steady no live fill')
  if x['physical_driver_peak'] is not None:raise ValueError('unknown physical peak')
  if type(x['pinned_observed']) is not bool or len(x['stages'])!=4:raise ValueError('stage observations/strict pinned bool')
  known=True;observed=True;subset=0;stage_sum=0;addresses=set()
  for address,capacity,status,kind in x['stages']:
   if type(address) is not int or type(capacity) is not int or address<0 or capacity<0 or capacity not in (0,65536):raise ValueError('stage address/capacity type')
   if capacity==0:
    if address!=0 or status is not None or kind is not None:raise ValueError('unattempted stage unknown')
    observed=False;continue
   if address==0 or address in addresses or type(status) is not int:raise ValueError('live distinct queried stage')
   addresses.add(address);stage_sum+=capacity
   if status==0:
    if type(kind) is not int or kind<0:raise ValueError('successful memory type')
    if kind==1:subset+=capacity
    else:observed=False
   else:
    if kind is not None:raise ValueError('failed stage query unknown')
    known=False;observed=False
  if stage_sum!=x['stage_owned'] or x['pinned_observed'] is not observed:raise ValueError('stage allocation/observed pinned derivation')
  if known:
   if type(x['pinned_subset']) is not int or x['pinned_subset']!=subset:raise ValueError('exact observed pinned subset')
  elif x['pinned_subset'] is not None:raise ValueError('unknown pinned subset')

def output_cases():
 cases={'all':list(range(96))}
 for slots in [1,2]:
  prefix=f'S{slots}-';cases.update({prefix+'coldA':[0,0,0],prefix+'GPU-A':[0],prefix+'RAM-A':[0],prefix+'SSD-A':[0],prefix+'next':[0]})
  for i in range(3):cases[prefix+f'shared-{i}']=[0]
 cases['source-error-next']=[1]
 cases.update({'S2-coldB':[1],'S2-GPU-ABA':[0,1,0],'S2-ready-A':[0],'S2-ready-C':[2]})
 return cases

def exact_output(path,expected):
 if Path(path).stat().st_size!=len(expected) or Path(path).read_bytes()!=expected:raise ValueError('ordered exact output bytes/bits: '+Path(path).name)

def capture_binding(m):
 # The native capture used the immutable pre-G recipe; current CPU validator is
 # separately bound. Never relabel a captured binary as built by this revision.
 mapping=read(BUILD/'historical-source-map.json');records=m['compiled']+m['recipes']+m['dependencies']
 if len(mapping['records'])!=len(records):raise ValueError('historical source coverage')
 for expected,entry in zip(records,mapping['records']):
  if entry['original']!=expected or entry['snapshot']['sha256']!=expected['sha256'] or entry['snapshot']['bytes']!=expected['bytes']:raise ValueError('historical source identity')
  check_rows([entry['snapshot']])
 if m['compiled']!=list(map(row,COMPILED)) or m['compiled_id']!=compiled_id():raise ValueError('native source changed')
 if mapping['manifest_sha256']!=sha(MANIFEST):raise ValueError('capture manifest')
 for key in ['inputs','bundle_files','tools']:check_rows(m[key])
 q_binding()
 if run(['git','rev-parse','HEAD']).stdout.strip()!=m['upstream_base'] or run(['git','diff','HEAD','--name-only']).stdout.strip():raise ValueError('upstream changed')

def revalidate():
 m=read(MANIFEST);capture_binding(m);q=q_binding();np=load('T19_CPU_r2',HERE/'reference.py').np
 fp=np.fromfile(q['expected'][0]['path'],dtype='<f4').reshape(96,256);bf=np.fromfile(q['expected'][1]['path'],dtype='<u2').reshape(96,256);roles=[]
 for role in ['primary','secondary','pageable']:
  path=BUILD/(role+'-verification.json');proof=read(path);receipt=json.loads((BUILD/(role+'.stdout')).read_text(encoding='utf-8'))
  if proof['receipt']!=receipt or proof['manifest_sha256']!=sha(MANIFEST) or proof['artifact']!=row(EXE):raise ValueError('fixed raw capture identity')
  validate(receipt);check_rows(proof['outputs']+proof['loaded_DLL'])
  for name,indices in output_cases().items():
   for suffix,expected in [('fp32',fp[indices].astype('<f4').tobytes()),('bf16',bf[indices].astype('<u2').tobytes())]:exact_output(BUILD/(role+'-output')/f'{name}-{suffix}.bin',expected)
  roles.append(row(path))
 capture_binding(m);save(BUILD/'r2-cpu-validation.json',dict(status='pass',capture_manifest=row(MANIFEST),artifact=row(EXE),captures=roles,validator=row(HERE/'build_verify.py'),historical_source_map=row(BUILD/'historical-source-map.json'),new_native_or_GPU_execution=False,before_after_capture_binding=True));print('CPU revalidated three fixed native captures')

def negatives():
 m=read(MANIFEST);capture_binding(m);q=q_binding();capture=read(BUILD/'primary-verification.json');base=capture['receipt'];validate(base);checks=[]
 def reject(name,fn):
  try:fn()
  except (ValueError,KeyError,TypeError,AssertionError,IndexError):checks.append(name);return
  raise AssertionError('negative accepted: '+name)
 for key in ['grant_zero_checked','Ready_protected','kernel_earlyreuse_rejected','all_cancel_drained','source_error_next']:
  x=copy.deepcopy(base);x[key]=False;reject(key,lambda x=x:validate(x))
 for k in ['logical','requested','received','weight_h2d','readback','host_pool','device_pool','remaining_jobs','remaining_credits']:
  for v in [0,-1,True,base['joint'][k]+1]:
   if type(v) is int and v==base['joint'][k]:continue
   x=copy.deepcopy(base);x['joint'][k]=v;reject('joint-'+k+'-'+str(v),lambda x=x:validate(x))
 for index in range(3):
  for k in ['device_owned','host_payload','stage_owned','metadata_capacity','binding_heap','identity_heap','lookup_capacity','key_capacity','ssd_misses','issued','requested_read','received','weight_h2d','index_h2d','output_d2h','ram_hits','gpu_hits','dedup','observed_host_payload_peak']:
   for v in [0,-1,True,base['capacities'][index][k]+1]:
    if type(v) is int and v==base['capacities'][index][k]:continue
    x=copy.deepcopy(base);x['capacities'][index][k]=v;reject('capacity-'+str(index)+'-'+k+'-'+str(v),lambda x=x:validate(x))
 for v in [0,-1,True,262143,262145]:
  x=copy.deepcopy(base);x['capacities'][0]['pinned_subset']=v;reject('pinned-subset-'+str(v),lambda x=x:validate(x))
 for v in [0,1,1.0,None,'true']:
  x=copy.deepcopy(base);x['capacities'][0]['pinned_observed']=v;reject('pinned-observed-type-'+str(v),lambda x=x:validate(x))
 for field,value in [(0,0),(0,True),(1,-1),(1,True),(2,False),(2,None),(3,True),(3,None)]:
  x=copy.deepcopy(base);x['capacities'][0]['stages'][0][field]=value;reject('stage-field-'+str(field)+'-'+str(value),lambda x=x:validate(x))
 x=copy.deepcopy(base);x['capacities'][0]['stages'][1][0]=x['capacities'][0]['stages'][0][0];reject('duplicate-stage',lambda:validate(x))
 # A failed query is unknown, not an additional success gate.
 x=copy.deepcopy(base);x['capacities'][0]['stages'][0][2:]=[1,None];x['capacities'][0]['pinned_subset']=None;x['capacities'][0]['pinned_observed']=False;validate(x)
 for mode in ['missing','duplicate','zero']:
  x=copy.deepcopy(base)
  if mode=='missing':x['trace'].pop()
  elif mode=='duplicate':x['trace'].append(copy.deepcopy(x['trace'][0]))
  else:x['trace'][0]['H2D']=0
  reject('trace-'+mode,lambda x=x:validate(x))
 lines=(BUILD/'rows.tsv').read_text(encoding='utf-8').splitlines()
 for col in [1,2,3,4,5,6]:
  changed=lines.copy();fields=changed[0].split('\t');fields[col]=str(int(fields[col])+1) if col!=6 else fields[col]+'.wrong';changed[0]='\t'.join(fields);reject('row-column-'+str(col),lambda changed=changed:source_contract(q,row_lines=changed))
 for kind in ['compiled','recipes','dependencies','inputs','bundle_files','tools']:
  x=copy.deepcopy(m);x[kind][0]['sha256']='0'*64;reject('binding-'+kind,lambda x=x:capture_binding(x))
 out=BUILD/'negative-files';out.mkdir(exist_ok=True);expected=Path(capture['outputs'][0]['path']).read_bytes();p=out/'actual.bin';exact_output(capture['outputs'][0]['path'],expected)
 for name,data in [('append',expected+b'X'),('truncate',expected[:-1]),('bitflip',bytes([expected[0]^1])+expected[1:])]:
  p.write_bytes(data);reject('actual-output-'+name,lambda:exact_output(p,expected))
 capture_binding(m);save(BUILD/'r2-negative-verification.json',dict(positive_failed_query_unknown=True,rejections=len(checks),positive_capture=True,checks=checks,manifest=row(MANIFEST),capture=row(BUILD/'primary-verification.json'),validator=row(HERE/'build_verify.py'),GPU_used=False));print('CPU negative rejects',len(checks))

def seal():
 m=read(MANIFEST);binding(m);h=read(BUILD/'host-verification.json')
 if h['manifest_sha256']!=sha(MANIFEST) or h['receipt']['source_id']!=m['compiled_id']:raise ValueError('host calibration binding')
 save(BUILD/'pre-G.json',dict(manifest=row(MANIFEST),host=row(BUILD/'host-verification.json'),Q=row(BUILD/'q/manifest.json'),recipe=row(HERE/'build_verify.py'),scope='fixed before native G; independent host ABI/capacity and Q'))
 print('pre-G calibration fixed',row(BUILD/'pre-G.json'))

def execute(role):
 m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);pre=read(BUILD/'pre-G.json');check_rows([pre[k] for k in ['manifest','host','Q','recipe']]);pre_sha=sha(BUILD/'pre-G.json');q=q_binding();pci='0000:03:00.0' if role=='secondary' else '0000:07:00.0';out=BUILD/(role+'-output')
 if out.exists():raise ValueError('preserve prior attempt')
 env=runtime()
 if role=='pageable':env['STRATA_TEST_PAGEABLE']='1'
 else:env.pop('STRATA_TEST_PAGEABLE',None)
 r=run([EXE,'--gpu',pci,BUILD,out,fixed],env,False,600);(BUILD/(role+'.stdout')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'.stderr')).write_text(r.stderr,encoding='utf-8');save(BUILD/(role+'-verification.json'),dict(exit=r.returncode,status='not_passed',manifest_sha256=fixed))
 if r.returncode or r.stderr:raise RuntimeError('native failed; no blind retry')
 receipt=json.loads(r.stdout)
 if receipt['source_id']!=m['compiled_id'] or receipt['pci']!=pci:raise ValueError('device/source identity')
 validate(receipt);outputs=[];values=0
 np=load("T19_fixed_numeric_loader",HERE/"reference.py").np
 fp=np.fromfile(q['expected'][0]['path'],dtype='<f4').reshape(96,256);bf=np.fromfile(q['expected'][1]['path'],dtype='<u2').reshape(96,256)
 cases=output_cases()
 for name,indices in cases.items():
  for suffix,expected in [('fp32',fp[indices].astype('<f4').tobytes()),('bf16',bf[indices].astype('<u2').tobytes())]:
   p=out/f'{name}-{suffix}.bin'
   exact_output(p,expected)
   outputs.append(row(p));values+=len(indices)*256
 loaded=[row(p) for p in receipt['loaded_modules'] if Path(p).name.lower() in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']]
 if len(loaded)!=3 or any(Path(x['path']).resolve().parent!=BUNDLE.resolve() or x['sha256']!=sha(BUNDLE/Path(x['path']).name) for x in loaded):raise ValueError('actual loaded runtime')
 binding(m);assert sha(MANIFEST)==fixed and sha(BUILD/'pre-G.json')==pre_sha;check_rows([pre[k] for k in ['manifest','host','Q','recipe']])
 save(BUILD/(role+'-verification.json'),dict(status='pass',manifest_sha256=fixed,preG=row(BUILD/'pre-G.json'),artifact=row(EXE),receipt=receipt,outputs=outputs,values=values,loaded_DLL=loaded,before_after_binding=True,full_source_qualified=False));print(dict(role=role,values=values,proof=row(BUILD/(role+'-verification.json'))))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','build','host','seal','execute','negatives','revalidate']);p.add_argument('--role',choices=['primary','secondary','pageable']);args=p.parse_args();BUILD.mkdir(exist_ok=True)
 if args.mode=='execute':execute(args.role)
 else:globals()[args.mode]()
