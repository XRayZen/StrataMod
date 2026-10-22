"""Bounded CPU/input/build driver; GPU execution needs a separate sealed window."""
import argparse,copy,hashlib,importlib.util,json,os,shutil,subprocess,sys,time,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BUILD=ROOT/'build-deepseek-t35/quant-block-scale'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
Q=load('t35_independent_q',HERE/'q_reference.py')
def row(p):
 p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n',encoding='utf8')
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def checked(rows):
 for r in rows:
  if row(r['path'])!=r:raise ValueError('changed source '+r['path'])
def fresh(prefix):
 index=1
 while(BUILD/f'{prefix}-{index}').exists():index+=1
 return BUILD/f'{prefix}-{index}'
def projection_q(decoded,x,rows,k,batch):
 w=decoded.reshape(rows,k);x=x.reshape(batch,k)
 if np.isfinite(w).all()and np.isfinite(x).all():
  try:return Q.ordered(w,x).reshape(-1)
  except ValueError:pass
 # Independent diagnostic path preserves operation order, including special values.
 out=np.empty((batch,rows),np.float32)
 with np.errstate(all='ignore'):
  for b in range(batch):
   for r in range(rows):
    acc=np.float32(0)
    for j in range(k):acc=np.float32(acc+np.float32(w[r,j]*x[b,j]))
    out[b,r]=acc
 return out.reshape(-1)
def compare_q(actual,expected):
 a=np.frombuffer(actual,dtype='<f4');q=np.frombuffer(expected,dtype='<f4')
 if a.shape!=q.shape or not np.array_equal(np.isnan(a),np.isnan(q)):raise ValueError('Q shape/NaN class')
 mask=~np.isnan(q)
 if not np.array_equal(a.view('<u4')[mask],q.view('<u4')[mask]):raise ValueError('Q exact finite/infinity bits')
 return dict(values=len(q),nan_values=int(np.isnan(q).sum()),non_nan_bits_exact=True)
def shape(kind,rows,k,batch,stride):
 if any(type(v)is not int for v in (kind,rows,k,batch,stride))or kind not in Q.BLOCKS or not 0<rows<=65536 or not 0<k<=5120 or batch not in (1,2,4,8)or not rows<=stride<=rows+3 or kind!=0 and k%32:raise ValueError('shape')
 return rows*k//Q.BLOCKS[kind][0]*Q.BLOCKS[kind][1]
def finite_raw(kind,rows,k):
 n=rows*k
 if kind==0:return ((np.arange(n,dtype=np.int32)%31-15)/16).astype('<f4').tobytes()
 width=Q.BLOCKS[kind][1];blocks=n//32;data=np.empty((blocks,width),np.uint8)
 for b in range(blocks):
  if kind==8:
   data[b,:2]=np.frombuffer(np.array([.5,-1.,2.,2.**-14][b%4],dtype='<f2').tobytes(),dtype=np.uint8);data[b,2:]=(np.arange(32,dtype=np.uint16)*7+b*3).astype(np.uint8)
  else:
   data[b,0]=120+b%12;data[b,1:]=(np.arange(width-1,dtype=np.uint16)*11+b*3).astype(np.uint8)
   if kind==43:data[b,1:][(data[b,1:]&127)==127]=126
 return data.tobytes()
def prepare():
 folder=fresh('input');folder.mkdir(parents=True,exist_ok=False);contract=read(HERE/'block_scale_contract.json');jobs=[];records=[]
 def add(name,mode,kind,rows,k,batch,stride,raw,activation=None):
  if len(raw)!=shape(kind,rows,k,batch,stride):raise ValueError('packed size')
  x=((np.arange(batch*k,dtype=np.int32)%23-11)/32).astype('<f4')if activation is None else np.asarray(activation,dtype='<f4').reshape(-1)
  if x.size!=batch*k:raise ValueError('activation shape')
  rawpath=folder/(name+'.raw');xpath=folder/(name+'.x');rawpath.write_bytes(raw);xpath.write_bytes(x.tobytes());decoded=Q.decode(kind,raw)
  q=decoded if mode=='decode'else projection_q(decoded,x,rows,k,batch)
  expected=folder/(name+'.Q');expected.write_bytes(q.astype('<f4').tobytes());records.extend([row(rawpath),row(xpath),row(expected)])
  jobs.append(dict(name=name,mode=mode,type=kind,rows=rows,k=k,batch=batch,stride=stride,raw=row(rawpath),input=row(xpath),Q=row(expected)))
 for kind in (0,8,39,43):
  for i,(rows,k,batch,stride)in enumerate(contract['projection_shapes']):add(f'p{kind}-{i}','project',kind,rows,k,batch,stride,finite_raw(kind,rows,k))
  if kind!=0:
   for k in contract['block_boundaries']:add(f'p{kind}-edge{k}','project',kind,3,k,1,6,finite_raw(kind,3,k))
 for case in Q.boundaries():
  w=case['weights'];x=case['inputs'];add('f32-'+case['name'],'project',0,1,w.shape[1],1,2,w.astype('<f4').tobytes(),x)
 # Exercise scale boundaries through projection's candidate block arithmetic,
 # separately from the exhaustive decode controls. No model source is read.
 for kind,scales in ((8,[0,1,0x8000,0x3c00,0x7bff,0x7c00,0x7e00,0xfc00]),(39,[0,1,126,127,128,253,254,255]),(43,[0,1,126,127,128,253,254,255])):
  width=Q.BLOCKS[kind][1];raw=bytearray(finite_raw(kind,len(scales),32))
  for r,s in enumerate(scales):
   raw[r*width]=s&255
   if kind==8:raw[r*width+1]=s>>8
  add(f'p{kind}-scale-special','project',kind,len(scales),32,2,len(scales)+1,bytes(raw),np.tile(np.array([1,-1,.5,-.5]*8,np.float32),2))
 d=np.empty((65536,34),np.uint8)
 for h in range(65536):d[h,:2]=[h&255,h>>8];d[h,2:]=(np.arange(32,dtype=np.uint32)+h).astype(np.uint8)
 add('d8','decode',8,65536,32,1,65536,d.tobytes())
 d=np.empty((256,17),np.uint8)
 for e in range(256):d[e,0]=e;d[e,1:]=np.arange(16,dtype=np.uint8)|((15-np.arange(16,dtype=np.uint8))<<4)
 add('d39','decode',39,256,32,1,256,d.tobytes())
 d=np.empty((2048,33),np.uint8)
 for b in range(2048):d[b,0]=b//8;d[b,1:]=np.arange(32,dtype=np.uint16)+(b%8)*32
 add('d43','decode',43,2048,32,1,2048,d.tobytes())
 raw=np.array([0,0x80000000,1,0x80000001,0x3f800000,0x7f800000,0xff800000,0x7fc00000]*4,dtype='<u4').tobytes();add('d0','decode',0,1,32,1,1,raw)
 tsv=folder/'jobs.tsv';tsv.write_text(''.join('\t'.join(map(str,[j['name'],j['mode'],j['type'],j['rows'],j['k'],j['batch'],j['stride'],j['raw']['path'],j['input']['path']]))+'\n'for j in jobs),encoding='utf8')
 sources=[row(HERE/p)for p in ('block_scale_verify.py','block_scale_contract.json','block_scale_fixture.hip','q_reference.py')]
 value=dict(schema='T35-block-scale-input/v1',contract=row(HERE/'block_scale_contract.json'),sources=sources,jobs=jobs,tsv=row(tsv),files=records,generated_bytes=sum(r['bytes']for r in records),original_model_read_bytes=0,GPU=0)
 save(folder/'input.json',value);print(row(folder/'input.json'))
def build():
 index=1
 while(BUILD/f'build-{index}').exists():index+=1
 folder=BUILD/f'build-{index}';folder.mkdir(parents=True);old=load('t35_quant_tools',HERE/'build_verify.py');old.BUILD=folder;tools,env=old.environment()
 baseline=ROOT/'build-deepseek-t35/quant-block-scale-source/before';candidate=ROOT/'Strata-extensions/native/quant';sources=[]
 for label,origin in [('baseline',baseline),('candidate',candidate)]:
  for name in ('quant.hip','quant.hpp'):
   path=origin/name;dest=folder/'source'/label/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest);sources.append(dict(original=row(path),snapshot=row(dest)))
 for name in ('block_scale_fixture.hip','block_scale_verify.py','block_scale_contract.json'):
  dest=folder/'source'/name;shutil.copyfile(HERE/name,dest);sources.append(dict(original=row(HERE/name),snapshot=row(dest)))
 cmake='cmake_minimum_required(VERSION 3.24)\nproject(t35_block LANGUAGES CXX HIP)\nfind_package(hip CONFIG REQUIRED)\nadd_executable(t35-block source/block_scale_fixture.hip)\ntarget_include_directories(t35-block PRIVATE source)\nset_target_properties(t35-block PROPERTIES HIP_STANDARD 17 HIP_STANDARD_REQUIRED YES)\ntarget_compile_options(t35-block PRIVATE -fno-fast-math -ffp-contract=off -fdenormal-fp-math=ieee)\ntarget_link_libraries(t35-block PRIVATE hip::host)\n'
 (folder/'CMakeLists.txt').write_text(cmake,encoding='utf8');sdk=old.SDK
 cmd=[str(tools['cmake']),'-S',str(folder),'-B',str(folder/'native'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 results=[]
 for i,command in enumerate((cmd,[str(tools['cmake']),'--build',str(folder/'native'),'--verbose'])):
  run=subprocess.run(command,env=env,capture_output=True);(folder/f'build-{i}.log').write_bytes(run.stdout+run.stderr);results.append(dict(command=command,exit=run.returncode,log=row(folder/f'build-{i}.log')))
  if run.returncode:save(folder/'failure.json',dict(results=results,sources=sources));raise ValueError('build failed; original logs retained')
 dlls=[]
 for name in ('amdhip64_7.dll','amd_comgr.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):
  origin=sdk/'bin'/name;dest=folder/'native'/name;shutil.copyfile(origin,dest);dlls.append(dict(original=row(origin),copy=row(dest)))
 notices=[]
 for origin in (sdk/'share/doc/amd_comgr/LICENSE.txt',sdk/'share/doc/rocm-core/LICENSE.md',ROOT/'LICENSE',ROOT/'third_party/ggml/LICENSE',ROOT/'Strata-extensions/native/artifact/NOTICE.md'):
  dest=folder/'native/licenses'/origin.parent.name/origin.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,dest);notices.append(dict(original=row(origin),copy=row(dest)))
 offload=subprocess.run([str(tools['objdump']),'--offloading',str(folder/'native/t35-block.exe')],capture_output=True,env=env);(folder/'offloading.txt').write_bytes(offload.stdout+offload.stderr)
 if offload.returncode or not all(arch.encode()in offload.stdout for arch in ('gfx1100','gfx1201')):raise ValueError('both architecture code objects')
 deps=subprocess.run([str(tools['ninja']),'-C',str(folder/'native'),'-t','deps'],capture_output=True,env=env);(folder/'ninja-deps.txt').write_bytes(deps.stdout+deps.stderr)
 if deps.returncode:raise ValueError('dependency listing failed')
 # The only project quant headers/bodies must be the two copied namespaces.
 dependency_lines=deps.stdout.decode('utf8').splitlines()
 quant_deps=[Path(line.strip())for line in dependency_lines if line.strip().lower().endswith(('quant.hip','quant.hpp'))]
 allowed={Path(r['snapshot']['path']).resolve()for r in sources[:4]}
 if {p.resolve()for p in quant_deps}!=allowed:raise ValueError('project quant dependency closure')
 dependencies=sorted({str(Path(line.strip()).resolve())for line in dependency_lines if line.startswith('    ')and Path(line.strip()).is_file()})
 checked([r['original']for r in sources]);proof=dict(schema='T35-block-scale-build/v1',sources=sources,commands=results,recipe=row(folder/'CMakeLists.txt'),tools=[row(p)for p in tools.values()if Path(p).is_file()],toolchain_helper=row(HERE/'build_verify.py'),dependency_listing=row(folder/'ninja-deps.txt'),dependencies=[row(p)for p in dependencies],project_quant_dependencies=[row(p)for p in quant_deps],offloading=row(folder/'offloading.txt'),dlls=dlls,notices=notices,environment={k:env[k]for k in ('PATH','TMP','TEMP','HIP_PATH','ROCM_PATH','HIP_PLATFORM')},exe=row(folder/'native/t35-block.exe'),GPU=0,actual=False)
 save(folder/'build.json',proof);print(row(folder/'build.json'))
def owner_archive():
 path=ROOT/'build-deepseek-t35/approx-8g-r1/measurement-seal.json';seal=read(path)
 records=[row(path)]+[r['snapshot']for r in seal['source_snapshots']]
 for r in records:
  actual=row(r['path'])
  if any(actual[k]!=v for k,v in r.items()):raise ValueError('accepted owner snapshot changed')
 backend=path.parent/'measurement-source/Strata-extensions/tests/backend';prior=sys.modules.get('eager_bench')
 try:
  b=load('quant_accepted_owner_math',backend/'eager_bench.py');sys.modules['eager_bench']=b
  old=load('quant_accepted_owner_recipe',backend/'build_verify.py')
 finally:
  if prior is None:sys.modules.pop('eager_bench',None)
  else:sys.modules['eager_bench']=prior
 return old,seal,records
def build_records(build):
 return [r['snapshot']for r in build['sources']]+[build['recipe'],build['exe'],build['toolchain_helper'],build['dependency_listing'],build['offloading']]+build['tools']+build['dependencies']+[r[k]for r in build['dlls']+build['notices']for k in ('original','copy')]
def input_records(value):return value['sources']+value['files']+[value['tsv'],value['contract']]
def module_bindings(paths,declared):
 allowed={str(Path(r['copy']['path']).resolve()).lower():r['copy']for r in declared};observed=[];names=set()
 for p in paths:
  key=str(Path(p).resolve()).lower()
  if key not in allowed:raise ValueError('foreign runtime module '+str(p))
  record=allowed[key];checked([record]);observed.append(record);names.add(Path(p).name.lower())
 if not {'amdhip64_7.dll','amd_comgr.dll'}<=names:raise ValueError('HIP runtime module not observed')
 return observed
def analyze(value,inputs,out):
 if value.get('schema')!='T35-block-scale-G/v1'or value.get('old_new_exact')is not True or value.get('model_generation')is not False:raise ValueError('native result contract')
 rows=value.get('jobs');jobs=inputs['jobs']
 if not isinstance(rows,list)or[j.get('name')for j in rows]!=[j['name']for j in jobs]:raise ValueError('finite job identity/order')
 result=[]
 for actual,job in zip(rows,jobs):
  a=(out/(job['name']+'.old.bin')).read_bytes();b=(out/(job['name']+'.new.bin')).read_bytes()
  expected_n=job['rows']*job['k']if job['mode']=='decode'else job['batch']*job['stride']
  if len(a)!=4*expected_n or a!=b or actual.get('exact_bits')is not True:raise ValueError('old/new exact result')
  payload=b
  if job['mode']=='project':
   output=np.frombuffer(b,dtype='<u4').reshape(job['batch'],job['stride'])
   if not np.all(output[:,job['rows']:]==0xa5a5a5a5):raise ValueError('padding guard')
   payload=output[:,:job['rows']].copy().tobytes()
  q=compare_q(payload,Path(job['Q']['path']).read_bytes())
  arms=actual.get('event_envelopes_ms')
  if not isinstance(arms,list)or[x.get('arm')for x in arms]!=list('ABBA'):raise ValueError('arm schedule')
  for arm in arms:
   if arm.get('launches')!=5 or any(type(arm.get(key))not in(int,float)or not np.isfinite(arm[key])for key in ('ms','host_seconds'))or arm['host_seconds']<0:raise ValueError('clock observation')
  reported_arms=[dict(arm,raw_event_ms=arm['ms'],ms=arm['ms']if arm['ms']>=0 else None,event_status='observed_nonnegative'if arm['ms']>=0 else 'negative_event_invalid')for arm in arms]
  expected_bytes=job['raw']['bytes']+job['input']['bytes']+8*expected_n
  if type(actual.get('requested_device_bytes'))is not int or actual['requested_device_bytes']!=expected_bytes:raise ValueError('requested device byte accounting')
  result.append(dict(name=job['name'],comparison=q,old=row(out/(job['name']+'.old.bin')),new=row(out/(job['name']+'.new.bin')),event_envelopes_ms=reported_arms,requested_device_bytes=expected_bytes))
 return result
def seal_execution(build_path,input_path,destination):
 build_path=Path(build_path).resolve();input_path=Path(input_path).resolve();destination=Path(destination).resolve();build=read(build_path);inputs=read(input_path)
 records=build_records(build)+input_records(inputs)+[row(build_path),row(input_path),row(Path(__file__)),row(Path(sys.executable)),row(Path(np.__file__))]
 checked(records)
 # Current production candidate must be exactly the compiled snapshot. Neither
 # the accepted old parent nor unrelated live Core/producer is re-consumed.
 checked([r['original']for r in build['sources']])
 if next(r['original']['sha256']for r in build['sources']if Path(r['original']['path'])==Path(__file__))!=row(Path(__file__))['sha256']:raise ValueError('build recipe version')
 old,owner,owner_records=owner_archive();old.runtime_snapshot(owner['input']);records+=owner_records
 # Owner records use the accepted older path+SHA schema; normalize once.
 records=[row(r['path'])for r in records]
 destination.mkdir(parents=True,exist_ok=False)
 save(destination/'seal.json',dict(schema='T35-block-scale-seal/v1',build=row(build_path),input=row(input_path),records=records,owner_seal=row(ROOT/'build-deepseek-t35/approx-8g-r1/measurement-seal.json'),devices=['0000:07:00.0','0000:03:00.0'],DRAM_report_only=True,model_GEN_count=0,normal_profile_modified=False,normal_native_qualified=False))
 print(row(destination/'seal.json'))
def execute(destination):
 destination=Path(destination).resolve();sealed=read(destination/'seal.json');checked(sealed['records']);build=read(sealed['build']['path']);inputs=read(sealed['input']['path'])
 if(destination/'execution.json').exists()or(destination/'owner-selection.json').exists():raise ValueError('preserve original run')
 old,owner,_=owner_archive();config=copy.deepcopy(owner['input']);temporary=destination/'tmp';temporary.mkdir();config['environment'].update(TMP=str(temporary),TEMP=str(temporary));env=dict(os.environ);env.update(config['environment'])
 session=None;failure=None;memory=[];runs=[];cleanup=None;owner_info=None
 try:
  session,selection,first=old.select_owner(config,env,destination);birth=first['birth'];memory.append(dict(point='constructed',sample=first))
  owner_info=session.info();before=old.runtime_snapshot(config,owner_info)
  if any(owner_info[k]!=0 for k in ('core_position','primary_logical_read','primary_h2d')):raise ValueError('noGEN owner performed model work')
  for pci in sealed['devices']:
   out=destination/('pci-'+pci.replace(':','-').replace('.','-'));out.mkdir();memory.append(dict(point=pci+'-before',sample=old.physical_memory(session.proc.pid,birth)))
   run_env=dict(os.environ);run_env.update(build['environment']);run_env.update(TMP=str(temporary),TEMP=str(temporary));command=[build['exe']['path'],pci,inputs['tsv']['path'],str(out)]
   start=time.perf_counter_ns();run=subprocess.run(command,env=run_env,capture_output=True);(out/'stdout.json').write_bytes(run.stdout);(out/'stderr.log').write_bytes(run.stderr)
   entry=dict(pci=pci,command=command,exit=run.returncode,host_seconds=(time.perf_counter_ns()-start)/1e9,stdout=row(out/'stdout.json'),stderr=row(out/'stderr.log'));runs.append(entry);save(destination/'execution.json',runs)
   memory.append(dict(point=pci+'-after',sample=old.physical_memory(session.proc.pid,birth)))
   if run.returncode or run.stderr:raise ValueError('finite kernel fixture failed; raw retained')
   actual=read(out/'stdout.json');entry['loaded_modules']=module_bindings(actual['loaded_modules'],build['dlls']);entry['analysis']=analyze(actual,inputs,out);save(destination/'execution.json',runs)
  after_info=session.info();after=old.runtime_snapshot(config,after_info)
  if any(after_info[k]!=0 for k in ('core_position','primary_logical_read','primary_h2d')):raise ValueError('noGEN owner received model work')
  save(destination/'owner-info.json',dict(before=owner_info,after=after_info,runtime_before=before,runtime_after=after,model_GEN_count=0,valid_model_payload_bytes=None))
  checked(sealed['records'])
 except BaseException as error:
  failure=error;save(destination/'failure.json',dict(type=type(error).__name__,error=str(error)))
 finally:
  if session is not None:
   observation_error=None;last=None
   try:last=old.physical_memory(session.proc.pid,birth)
   except Exception as error:observation_error=str(error)
   try:
    # close waits on this Popen's original process handle, rather than inferring
    # absence from a failed memory query or a later PID lookup.
    session.close();post=old.physical_memory(session.proc.pid,birth);gone=session.proc.returncode is not None
    cleanup=dict(pid=session.proc.pid,birth=birth,exit=session.proc.returncode,sample=last,post=post,observation_error=observation_error,gone=gone,process_handle_exit_observed=gone)
   except BaseException as error:
    cleanup=dict(pid=session.proc.pid,birth=birth,exit=session.proc.poll(),error=str(error))
    if failure is None:failure=error
  save(destination/'memory.json',memory);save(destination/'cleanup.json',cleanup)
 if failure is not None:raise failure
 if cleanup is None or cleanup['exit']!=0 or cleanup['gone']is not True:raise ValueError('owner cleanup unconfirmed')
 checked(sealed['records'])
 save(destination/'verification.json',dict(schema='T35-block-scale-actual/v1',seal=row(destination/'seal.json'),execution=row(destination/'execution.json'),owner_info=row(destination/'owner-info.json'),memory=row(destination/'memory.json'),cleanup=row(destination/'cleanup.json'),old_new_Q_exact=True,DRAM_report_only=True,model_GEN_count=0,original_model_read_bytes=0,normal_native_qualified=False,model_speed_qualified=False,clock='same-device HIP event envelope includes dispatch/queue gaps'))
 print(row(destination/'verification.json'))
def post_failed_first_device(prior,destination):
 prior=Path(prior).resolve();destination=Path(destination).resolve();sealed=read(prior/'seal.json');build=read(sealed['build']['path']);inputs=read(sealed['input']['path'])
 old_recipe=next(r for r in build['sources']if Path(r['original']['path'])==Path(__file__))
 checked([old_recipe['snapshot']])
 history=[];resolved=[]
 for r in sealed['records']:
  if Path(r['path'])==Path(__file__):
   if r['sha256']!=old_recipe['snapshot']['sha256']:raise ValueError('unexpected old recipe version')
   resolved.append(old_recipe['snapshot']);history.append(dict(original=r,resolved=old_recipe['snapshot']))
  else:checked([r]);resolved.append(r)
 runs=read(prior/'execution.json');cleanup=read(prior/'cleanup.json')
 if len(runs)!=1 or runs[0]['pci']!=sealed['devices'][0]or runs[0]['exit']!=0 or cleanup['exit']!=0 or cleanup.get('process_handle_exit_observed')is not True:raise ValueError('original bounded first-device run/close')
 out=prior/('pci-'+runs[0]['pci'].replace(':','-').replace('.','-'));actual=read(out/'stdout.json')
 if(out/'stderr.log').read_bytes():raise ValueError('original fixture stderr')
 dlls=module_bindings(actual['loaded_modules'],build['dlls']);analysis=analyze(actual,inputs,out)
 destination.mkdir(parents=True,exist_ok=False)
 original=[row(prior/name)for name in ('seal.json','preflight.json','execution.json','failure.json','cleanup.json','memory.json','owner-selection.json')]+[row(out/'stdout.json'),row(out/'stderr.log')]
 for j in analysis:original += [j['old'],j['new']]
 save(destination/'verification.json',dict(schema='T35-block-scale-post-CPU/v1',prior=original,old_recipe=old_recipe,historical_resolution=history,new_CPU_recipe=row(Path(__file__)),analysis=analysis,loaded_modules=dlls,numeric_scope='first PCI 39 jobs only',first_device=runs[0]['pci'],remaining_devices=sealed['devices'][1:],original_native_exit=0,original_controller_exit=1,clock_failure_preserved=True,normal_native_qualified=False,model_speed_qualified=False,new_GPU_runs=0))
 # The remaining PCI uses exactly the original executable and generated bytes.
 # Only the controller's invalid-event reporting changed; the first capture is
 # not replayed on a GPU and the original failure is never overwritten.
 continuation=destination/'remaining';continuation.mkdir()
 records=resolved+original+[row(destination/'verification.json'),row(Path(__file__))]
 save(continuation/'seal.json',dict(schema='T35-block-scale-seal/v1',build=sealed['build'],input=sealed['input'],records=records,prior_seal=row(prior/'seal.json'),historical_resolution=history,new_CPU_recipe=row(Path(__file__)),owner_seal=sealed['owner_seal'],devices=sealed['devices'][1:],DRAM_report_only=True,model_GEN_count=0,normal_profile_modified=False,normal_native_qualified=False))
 print(row(destination/'verification.json'));print(row(continuation/'seal.json'))
def cpu_proof():
 folder=fresh('CPU');folder.mkdir(parents=True);paths=[HERE/p for p in ('block_scale_verify.py','block_scale_contract.json','block_scale_fixture.hip','q_reference.py')]
 paths+=[ROOT/'Strata-extensions/native/quant'/p for p in ('quant.hip','quant.hpp')]
 paths+=[ROOT/'build-deepseek-t35/quant-block-scale-source/before'/p for p in ('quant.hip','quant.hpp')]
 before=[row(p)for p in paths];snapshots=[]
 for p in paths:
  dest=folder/'source'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);snapshots.append(dict(original=row(p),snapshot=row(dest)))
 command=[sys.executable,'-B','-X','utf8',str(Path(__file__))];run=subprocess.run(command,capture_output=True);(folder/'CPU.log').write_bytes(run.stdout+run.stderr);checked(before)
 save(folder/'verification.json',dict(schema='T35-block-scale-CPU/v1',sources=snapshots,command=command,exit=run.returncode,log=row(folder/'CPU.log'),original_model_read_bytes=0,actual_GPU=0,normal_numeric_qualified=False))
 if run.returncode:raise ValueError('CPU failed; retained original log')
 print(row(folder/'verification.json'))
class CPU(unittest.TestCase):
 def test_analyzer_rejects_corrupt_output_and_schedule(self):
  import tempfile
  with tempfile.TemporaryDirectory()as temp:
   folder=Path(temp);expected=folder/'Q';expected.write_bytes(np.array([1],dtype='<f4').tobytes());payload=np.array([0x3f800000,0xa5a5a5a5],dtype='<u4').tobytes()
   for suffix in ('old','new'):(folder/('one.'+suffix+'.bin')).write_bytes(payload)
   job=dict(name='one',mode='project',rows=1,k=1,batch=1,stride=2,raw=dict(bytes=4),input=dict(bytes=4),Q=row(expected))
   native=dict(schema='T35-block-scale-G/v1',old_new_exact=True,model_generation=False,jobs=[dict(name='one',exact_bits=True,requested_device_bytes=24,event_envelopes_ms=[dict(arm=a,launches=5,ms=.01,host_seconds=.01)for a in 'ABBA'])])
   self.assertEqual(analyze(native,dict(jobs=[job]),folder)[0]['comparison']['values'],1)
   bad=copy.deepcopy(native);bad['jobs'][0]['event_envelopes_ms'][0]['arm']='B'
   with self.assertRaises(ValueError):analyze(bad,dict(jobs=[job]),folder)
   bad=copy.deepcopy(native);bad['jobs'][0]['requested_device_bytes']+=1
   with self.assertRaises(ValueError):analyze(bad,dict(jobs=[job]),folder)
   bad=copy.deepcopy(native);bad['jobs'][0]['event_envelopes_ms'][0]['ms']=-.01
   observed=analyze(bad,dict(jobs=[job]),folder)[0]['event_envelopes_ms'][0]
   self.assertIsNone(observed['ms']);self.assertEqual(observed['raw_event_ms'],-.01);self.assertEqual(observed['event_status'],'negative_event_invalid')
   (folder/'one.new.bin').write_bytes(payload[:-4]+bytes(4))
   with self.assertRaises(ValueError):analyze(native,dict(jobs=[job]),folder)
 def test_foreign_DLL_rejected(self):
  with self.assertRaisesRegex(ValueError,'foreign runtime'):module_bindings(['C:/unowned/amdhip64_7.dll'],[])
  with self.assertRaisesRegex(ValueError,'not observed'):module_bindings([],[])
 def test_production_scalar_checked_API_unchanged(self):
  before=(ROOT/'build-deepseek-t35/quant-block-scale-source/before/quant.hip').read_text(encoding='utf8');after=(ROOT/'Strata-extensions/native/quant/quant.hip').read_text(encoding='utf8')
  self.assertEqual(before[:before.index('__global__ void projection_kernel')],after[:after.index('// Projection-only block context.')])
  self.assertEqual(before[before.index('size_t plus('):],after[after.index('size_t plus('):])
 def test_Q_special_value_policy(self):
  a=np.array([0,0x80000000,0x7f800000,0x7fc00001],dtype='<u4').tobytes()
  b=np.array([0,0x80000000,0x7f800000,0x7fc00002],dtype='<u4').tobytes()
  self.assertEqual(compare_q(a,b)['nan_values'],1)
  with self.assertRaises(ValueError):compare_q(a,np.array([0,0,0x7f800000,0x7fc00002],dtype='<u4').tobytes())
  with self.assertRaises(ValueError):compare_q(a,b[:-4])
 def test_ordered_boundary_bits(self):
  for c in Q.boundaries():
   result=projection_q(c['weights'].reshape(-1),c['inputs'],1,c['weights'].shape[1],1)
   self.assertEqual(int(result.view('<u4')[0]),c['expected_bits'])
 def test_fullK_shape_and_domain(self):
  self.assertEqual(shape(39,17,5120,8,20),46240)
  for args in ((39,1,31,1,1),(39,1,32,True,1),(39,1,32,3,1),(39,0,32,1,1),(39,2,32,1,1)):
   with self.assertRaises(ValueError):shape(*args)
 def test_independent_native_layout(self):
  for kind in (0,8,39,43):
   raw=finite_raw(kind,3,64);self.assertEqual(len(raw),shape(kind,3,64,1,3));self.assertTrue(np.isfinite(Q.decode(kind,raw)).all())
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--cpu',action='store_true');parser.add_argument('--prepare',action='store_true');parser.add_argument('--build',action='store_true');parser.add_argument('--seal',nargs=3,metavar=('BUILD','INPUT','DESTINATION'));parser.add_argument('--execute',type=Path);parser.add_argument('--post-first-device',nargs=2,metavar=('PRIOR','DESTINATION'));args=parser.parse_args()
 if args.prepare:prepare()
 elif args.build:build()
 elif args.seal:seal_execution(*args.seal)
 elif args.execute:execute(args.execute)
 elif args.cpu:cpu_proof()
 elif args.post_first_device:post_failed_first_device(*args.post_first_device)
 else:unittest.main(argv=[sys.argv[0]],verbosity=2)
