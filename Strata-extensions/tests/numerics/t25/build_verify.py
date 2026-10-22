"""Explicit T25 fixed helper qualification; never a normal start gate."""
import argparse,copy,hashlib,importlib.util,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
import reference as q
import acquire_fixtures as acq
np=q.np;HERE=Path(__file__).parent;ROOT=HERE.parents[3];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t25';BUNDLE=BUILD/'bundle';EXE=BUNDLE/'t25-engram.exe';Q=BUILD/'q';INPUT=BUILD/'input'
OWN=[HERE/n for n in ['CMakeLists.txt','fixture.hip','reference.py','contract.json','acquire_fixtures.py','fixture-receipts.json','build_verify.py','test_reference.py']]
sha=acq.sha;record=acq.record;read=acq.read;save=acq.save
def run(cmd,env=None,timeout=900,check=True):
 r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
 if check and r.returncode:raise RuntimeError(f'exit{r.returncode}: {cmd}\n{r.stdout}{r.stderr}')
 return r
def aggregate(rows):return hashlib.sha256(''.join(x['path']+'|'+x['sha256']+'\n' for x in rows).encode()).hexdigest()
def verify(rows):
 for x in rows:
  if record(x['path'])!={k:x[k] for k in ['path','bytes','sha256']}:raise ValueError('fixed file changed '+x['path'])
def array(p,x):np.asarray(x).tofile(p);return dict(**record(p),dtype=np.asarray(x).dtype.str,shape=list(np.asarray(x).shape))
def fixture_binding(receipt=None):
 r=read(HERE/'fixture-receipts.json') if receipt is None else receipt;c=read(HERE/'contract.json');inv=read(EXT/'tests/artifact/header-inventory.json');tensors={t['name']:(s,t) for s in inv['shards'] for t in s['tensors']};nq=read(ROOT/'build-deepseek-t13/nq.json');eg=acq.module('t25_hash_oracle',EXT/'tests/engram/reference.py');hashes=eg.hashes(c['tokens'],c['mask'],nq['token_map'],nq['multipliers'],nq['primes'],nq['offsets'])
 verify([r['T13_NQ']]+r['reference_sources'])
 if sha(EXT/'tests/artifact/source-files.json')!='3c226d451f4b3a0b6b12b69fab492e559226bc23c6d02fcf926964bf33178ec6' or sha(EXT/'tests/artifact/header-inventory.json')!='08583c5cff84627962517db22ec877a69fd1aed3a811eb010d2f2f3e2f84366b':raise ValueError('fixed T03 source inputs')
 fixed=read(EXT/'tests/artifact/source-files.json');source_rows={int(x[0]):x for x in [line.split('\t') for line in (ROOT/'build-deepseek-t10/sources.tsv').read_text(encoding='utf-8').splitlines()]};full=acq.module('t25_SourceFile',EXT/'native/artifact/full_acquire.py')
 expected_sources={s['index']:[str(s['index']),str(s['bytes']),s['lfs_sha256'],inv['revision'],str(full.DESTINATION/Path(s['filename']).name)] for s in fixed['files']}
 if source_rows!=expected_sources:raise ValueError('T10 SourceFile differs from fixed T03 planned source')
 if r['row_file']!=expected_sources[8]:raise ValueError('row SourceFile before any source access')
 for x in r['official']:
  spec=next(s for s in c['official_files'] if s['layer']==x['source']['layer']);role=x['tensor'].split('.')[-1];offset=spec['q_start']+(40960 if role=='k_weight' else 0)
  if role not in ['q_weight','k_weight'] or x['tensor']!=f'layers.{spec["layer"]}.engram.{role}' or x['source']!=spec or x['absolute_offset']!=offset or x['revision']!=acq.REV or x['bytes']!=40960 or x['whole_source_sha_verified'] is not False:raise ValueError('official tuple')
  tr=x['transport'];expected=f'bytes {spec["q_start"]}-{spec["q_start"]+81919}/{spec["bytes"]}'
  # Existing transport helper returns its own field schema; validate exact range below.
  if tr.get('start')!=spec['q_start'] or tr.get('end')!=spec['q_start']+81919 or tr.get('total')!=spec['bytes'] or tr.get('etag')!=spec['etag'] or tr.get('status')!=206:raise ValueError('official HTTP tuple')
  verify([{k:x[k] for k in ['path','bytes','sha256']}])
 for x in r['gguf_gates']:
  s,t=tensors[x['tensor']]
  if x['source_file']!=expected_sources[9] or x['source']!=t or s['index']!=9 or x['bytes']!=81920 or x['file_stat']!=acq.stat(x['source_file'][4]):raise ValueError('native gate original SourceFile/span')
  verify([{k:x[k] for k in ['path','bytes','sha256']}])
 full=acq.module('t25_final_identity',EXT/'native/artifact/full_acquire.py')
 proofs=r['individual_final_proofs']
 if len(proofs)!=2 or any(type(p.get('index')) is not int for p in proofs) or sorted(p['index'] for p in proofs)!=[8,9]:raise ValueError('exact individual final observation coverage')
 for proof in r['individual_final_proofs']:
  i=proof['index'];expected=expected_sources[i];path=expected[4];observation=ROOT/'build-deepseek-t05-worker7/before.json' if i==8 else EXT/'tests/ffn/fixture-receipts.json';observed=read(observation);expected_identity=observed['eight_identity'] if i==8 else observed['fixtures'][0]['source']['file_identity'];checkpoint=Path(path+'.part.json')
  if proof['recorded_observation']!=record(observation) or proof['checkpoint']!=record(checkpoint) or proof['current_identity']!=expected_identity or full.stat_identity(path)!=expected_identity:raise ValueError('individual finalized observation/source correspondence')
  state=read(checkpoint)
  if state['committed']!=int(expected[1]) or state['prefix_sha256']!=expected[2] or state['source']['lfs_sha256']!=expected[2] or state['source']['revision']!=expected[3]:raise ValueError('individual checkpoint fullSHA/SourceFile')
 if len(r['rows'])!=384 or r['row_file']!=expected_sources[8] or r['row_source']!=tensors['per_layer_token_embd.weight'][1]:raise ValueError('row count/original SourceFile/span')
 table=tensors['per_layer_token_embd.weight'][1]
 for i,x in enumerate(r['rows']):
  layer=1 if i<192 else 14;pos=(i%192)//24;head=i%24;global_row=hashes[pos][(0 if layer==1 else 24)+head];offset=table['absolute_offset']+global_row*264
  if (x['layer'],x['position'],x['head'],x['global_row'],x['absolute_offset'],x['bytes'])!=(layer,pos,head,global_row,offset,264) or x['file_stat']!=acq.stat(r['row_file'][4]):raise ValueError('row source/hash/head tuple')
  verify([{k:x[k] for k in ['path','bytes','sha256']}])
 return r
def prepare():
 r=fixture_binding();Q.mkdir(exist_ok=True);INPUT.mkdir(exist_ok=True);save(BUILD/'fusion-bridge.json',q.fusion(r));save(BUILD/'independent-N-literals.json',q.decimal_literals())
 test=run([sys.executable,HERE/'test_reference.py']);(BUILD/'tdd-green.log').write_text(test.stdout+test.stderr,encoding='utf-8')
 inv=read(EXT/'tests/artifact/header-inventory.json');shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',INPUT/'sources.tsv');(INPUT/'prefixes.tsv').write_text(''.join(str(s['bytes'])+'\t'+s['prefix_path']+'\n' for s in inv['shards']),encoding='utf-8');alljobs=[];lines=[]
 for layer in [1,14]:
  rows=[x for x in r['rows'] if x['layer']==layer];bank=b''.join(Path(x['path']).read_bytes() for x in rows);decoded=np.stack([q.decode_row(bank[i:i+264]) for i in range(0,len(bank),264)]).reshape(8,6144);embedding=q.bf16(decoded);gate=next(x for x in r['gguf_gates'] if x['tensor']==f'blk.{layer}.engram_gate.weight');weight=np.fromfile(gate['path'],dtype='<f4').reshape(4,5120);tensor=next(t for s in inv['shards'] for t in s['tensors'] if t['name']==f'blk.{layer}.engram_kv.weight');file=gate['source_file'][4]
  act,scales,codes=q.qdq(embedding);dot=np.empty((8,25600),np.float32);digest=hashlib.sha256();maxerr=0.;maxbound=0.
  with Path(file).open('rb') as f:
   f.seek(tensor['absolute_offset'])
   for start in range(0,25600,256):
    raw=f.read(256*6528)
    if len(raw)!=256*6528:raise ValueError('original KV short tile')
    digest.update(raw);w=q.decode_q8(raw).reshape(256,6144);value=q.ordered(w,act);dot[:,start:start+256]=value
    # independent FP64 plus conservative absolute FP32 gamma bound, not G tolerance
    gamma=(2*6144*2**-24)/(1-2*6144*2**-24)
    for b in range(8):
     product=w.astype(np.float64)*act[b].astype(np.float64);n=np.sum(product,axis=1,dtype=np.float64);ab=np.nextafter(np.sum(np.abs(product),axis=1,dtype=np.float64)*(1+6144*2**-52),np.inf);bound=gamma*ab+6144*2**-149;error=np.abs(value[b].astype(np.float64)-n)
     if np.any(error>bound):raise ValueError('Q ordered dot independent N bound')
     maxerr=max(maxerr,float(error.max()));maxbound=max(maxbound,float(bound.max()))
  save(BUILD/f'KV-L{layer}-N-diagnostic.json',dict(consumed_bytes=167116800,consumed_SHA256=digest.hexdigest(),max_absolute_error=maxerr,max_bound=maxbound,scope='FP64 on same native decoded weights, not original unquantized quality'))
  kv=q.bf16(dot)
  for hold in ['A','B']:
   for batch in [1,2,4,8]:
    name=f'L{layer}-{hold}-B{batch}';h=q.residual(batch,hold);mask=np.array(read(HERE/'contract.json')['mask'][:batch],dtype=np.uint8);trace=dict(row_fp32=decoded[:batch],row_bf16=(q.bf16(decoded[:batch]).view(np.uint32)>>16).astype('<u2'),embedding=embedding[:batch],act_qdq=act[:batch],act_scales=scales[:batch],act_codes=codes[:batch],kv_dot=dot[:batch],kv_bf16=kv[:batch]);trace.update(q.gate(h,kv[:batch],weight,mask));dest=Q/name;dest.mkdir(exist_ok=True);outputs={k:array(dest/(k+'.bin'),v) for k,v in trace.items()};h.tofile(INPUT/(name+'-h.bin'));mask.tofile(INPUT/(name+'-mask.bin'));bankpath=INPUT/(name+'-bank.bin');bankpath.write_bytes(bank[:batch*24*264]);lines.append('\t'.join(map(str,[name,'real',layer,batch,bankpath,gate['path'],'-'])));alljobs.append(dict(name=name,kind='real',layer=layer,batch=batch,outputs=outputs))
 for control in ['positivezero','negativezero','key1','key8','masked','tiny','zero-norm','asymmetric','product-order']:
  name='control-'+control;batch=1;h,kv,weight,mask=q.control_inputs(control)
  trace=dict(kv_bf16=kv,**q.gate(h,kv,weight,mask));dest=Q/name;dest.mkdir(exist_ok=True);outputs={k:array(dest/(k+'.bin'),v) for k,v in trace.items()};h.tofile(INPUT/(name+'-h.bin'));mask.tofile(INPUT/(name+'-mask.bin'));weight.tofile(INPUT/(name+'-gate.bin'));kv.tofile(INPUT/(name+'-kv.bin'));lines.append('\t'.join(map(str,[name,'control',1,1,'-',INPUT/(name+'-gate.bin'),INPUT/(name+'-kv.bin')])));alljobs.append(dict(name=name,kind='control',layer=1,batch=1,outputs=outputs))
 # Entire N checks below consume only pre-G inputs/Q and fixed original source.
 independent=[]
 for job in alljobs:
  name=job['name'];trace={k:np.fromfile(v['path'],dtype=v['dtype']).reshape(v['shape']) for k,v in job['outputs'].items()};h=np.fromfile(INPUT/(name+'-h.bin'),dtype='<f4').reshape(job['batch'],20480)
  if job['kind']=='control':
   control=name[len('control-'):];_,kv,w,mask=q.control_inputs(control);expected,n=q.decimal_full(h,kv,w,mask);q.compare_n_control(trace,expected);independent.append(dict(name=name,**n,all_canonical_traces_exact=True))
  else:
   g=next(x for x in r['gguf_gates'] if x['tensor']==f'blk.{job["layer"]}.engram_gate.weight');w=np.fromfile(g['path'],dtype='<f4').reshape(4,5120);n=q.real_gate_n(h,trace['kv_bf16'],w,trace);independent.append(dict(name=name,**n))
 save(BUILD/'independent-N-full-gate.json',dict(cases=independent,G_outputs_used=False,independent_source=record(HERE/'reference.py')))
 (INPUT/'jobs.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8');save(Q/'manifest.json',dict(jobs=alljobs,contract=record(HERE/'contract.json'),fixtures=record(HERE/'fixture-receipts.json'),oracle_sources=[record(HERE/'reference.py'),record(HERE/'test_reference.py')],inputs=[record(p) for p in sorted(INPUT.glob('*'))],N=[record(p) for p in [BUILD/'fusion-bridge.json',BUILD/'independent-N-literals.json',BUILD/'independent-N-full-gate.json',BUILD/'KV-L1-N-diagnostic.json',BUILD/'KV-L14-N-diagnostic.json']],GPU_executed=False));print(json.dumps(dict(jobs=len(alljobs),Q_SHA256=sha(Q/'manifest.json'),G0=True)))
def environment(runtime=False):
 shared=Path('C:/Develop/AI/StrataMod');sdk=shared/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel';vc=shared/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=shared/'.vision-toolchain/winsdk';inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
 tools=dict(clang=sdk/'lib/llvm/bin/clang++.exe',cmake=shared/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',ninja=shared/'.vision-venv-10.1/Scripts/ninja.exe',linker=vc/'bin/Hostx64/x64/link.exe',dumpbin=vc/'bin/Hostx64/x64/dumpbin.exe',rc=wb/'rc.exe',mt=wb/'mt.exe',objdump=sdk/'lib/llvm/bin/llvm-objdump.exe')
 env=os.environ.copy();temp=BUILD/'tmp';temp.mkdir(exist_ok=True);env.update(TMP=str(temp),TEMP=str(temp),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
 if runtime:
  for k in list(env):
   if k.startswith(('HIP','ROCM','ROCR','GPU_')) or k in ['INCLUDE','LIB']:env.pop(k)
  env['PATH']=os.pathsep.join(map(str,[BUNDLE,Path(env.get('SystemRoot','C:/Windows'))/'System32',Path(env.get('SystemRoot','C:/Windows'))]))
 else:
  env.update(INCLUDE=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um'])),LIB=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',sdk/'lib'])),PATH=os.pathsep.join(map(str,[sdk/'bin',sdk/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')])),HIP_PATH=str(sdk),ROCM_PATH=str(sdk),HIP_PLATFORM='amd')
 return sdk,tools,env
def numpy_runtime():
 import ctypes
 k=ctypes.WinDLL('kernel32');p=ctypes.WinDLL('psapi');k.GetCurrentProcess.restype=ctypes.c_void_p;process=k.GetCurrentProcess();h=(ctypes.c_void_p*2048)();n=ctypes.c_ulong();p.EnumProcessModules.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong)];k.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong]
 if not p.EnumProcessModules(process,h,ctypes.sizeof(h),ctypes.byref(n)) or n.value>ctypes.sizeof(h):raise ValueError('CPU module observation')
 loaded=[]
 for handle in h[:n.value//ctypes.sizeof(ctypes.c_void_p)]:
  b=ctypes.create_unicode_buffer(32768)
  if not k.GetModuleFileNameW(handle,b,len(b)):raise ValueError('CPU module path')
  if any(s in b.value.lower() for s in ['numpy','python312.dll','python3.dll']):loaded.append(record(b.value))
 return dict(version=np.__version__,interpreter=record(sys.executable),loaded=loaded,modules=[record(Path(m.__file__)) for n,m in sorted(sys.modules.items()) if n.startswith('numpy') and getattr(m,'__file__',None) and Path(m.__file__).is_file()])
def q_binding():
 qm=read(Q/'manifest.json');verify([qm['contract'],qm['fixtures']]+qm['oracle_sources']+qm['inputs']+qm['N']);fixture_binding()
 for j in qm['jobs']:verify(list(j['outputs'].values()))
 return qm
def binding():
 m=read(BUILD/'manifest.json');verify(m['binding']);q_binding()
 if json.loads(run([EXE,'--identity'],environment(True)[2]).stdout)!=dict(source_id=m['source_id']):raise ValueError('compiled identity')
 return m
def expected_capacity(job):
 b=job['batch'];base=81920+b*(81920+1+102400+16+81920+7*16)
 return base if job['kind']=='control' else base+4+256*6528+b*(24*264+24*4+6144*4+6144*2+6144*4+6144*4+25600*4+192+6144)
def build():
 qm=q_binding();BUNDLE.mkdir(exist_ok=True)
 if (BUILD/'manifest.json').exists():raise ValueError('frozen bundle exists: preserve before new build')
 snapshot=BUILD/'immutable-source';mapping=read(BUILD/'source-map.json');verify([dict(path=x['path'],bytes=x['bytes'],sha256=x['sha256']) for x in mapping]);owned=[]
 for p in OWN:
  target=snapshot/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);owned.append(record(target))
 identity=aggregate([dict(path=x['relative'],sha256=x['sha256']) for x in mapping]+[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in OWN if p.suffix=='.hip']);sdk,tools,env=environment();native=BUILD/'cmake-native';source=snapshot/HERE.relative_to(ROOT)
 commands=[[tools['cmake'],'--fresh','-S',source,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',f'-DT25_SNAPSHOT={snapshot.as_posix()}',f'-DT25_SOURCE_ID={identity}',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,cmd in enumerate(commands):
  r=run(cmd,env,check=False);(BUILD/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise ValueError('build failed see build-'+str(i)+'.log')
 shutil.copy2(native/'bundle/t25-engram.exe',EXE);origins=[]
 for n in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
  p=sdk/'bin'/n;shutil.copy2(p,BUNDLE/n);origins.append(dict(origin=record(p),target=record(BUNDLE/n)))
 notices=BUNDLE/'licenses';notices.mkdir(exist_ok=True)
 for p in (ROOT/'build-deepseek-t21/bundle/licenses').rglob('*'):
  if p.is_file():target=notices/p.relative_to(ROOT/'build-deepseek-t21/bundle/licenses');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 offload=run([tools['objdump'],'--offloading',EXE],env).stdout;(BUILD/'offloading.log').write_text(offload,encoding='utf-8')
 if not all(a in offload for a in ['gfx1100','gfx1201']):raise ValueError('both compiled arch images')
 (BUILD/'direct-imports.log').write_text(run([tools['dumpbin'],'/DEPENDENTS',EXE],env).stdout,encoding='utf-8');save(BUILD/'CPU-runtime.json',numpy_runtime());save(BUILD/'allocation-expectations.json',{j['name']:dict(device=expected_capacity(j),KV_read=167116800 if j['kind']=='real' else 0,weight_H2D=167116800 if j['kind']=='real' else 0,tiles=100 if j['kind']=='real' else 0) for j in qm['jobs']})
 oracle_deps=[EXT/'tests/engram/reference.py',EXT/'native/artifact/full_acquire.py',EXT/'native/artifact/acquire.py',EXT/'native/artifact/gguf.py',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json']
 files=list(snapshot.rglob('*'))+list(BUNDLE.rglob('*'))+list(INPUT.rglob('*'))+list(Q.rglob('*'))+list((BUILD/'reference-source').rglob('*'))+list((BUILD/'raw').glob('*.bin'))+OWN+oracle_deps+[BUILD/'CPU-runtime.json',BUILD/'source-map.json',BUILD/'allocation-expectations.json',BUILD/'fusion-bridge.json',BUILD/'independent-N-literals.json',BUILD/'KV-L1-N-diagnostic.json',BUILD/'KV-L14-N-diagnostic.json']+list(tools.values())+[Path(sys.executable)]
 rows=[record(p) for p in sorted(set(files)) if p.is_file()];save(BUILD/'manifest.json',dict(schema='T25-fixed-helper-trial/v1',source_id=identity,binding=rows,source_snapshot=record(BUILD/'source-map.json'),own_sources=owned,DLL_origins=origins,Q=record(Q/'manifest.json'),normal_audit_D2H=False,full_T25=False,actualstate='pending',patches=[]));binding();host();preflight();print(json.dumps(dict(manifest=record(BUILD/'manifest.json'),exe=record(EXE),G0=True)))
def host():
 fixed=sha(BUILD/'manifest.json');binding();r=run([EXE,'--host',INPUT,BUILD/'host-output'],environment(True)[2]);o=json.loads(r.stdout)
 if o!=dict(assertions=6,source_id=read(BUILD/'manifest.json')['source_id'],GPU_used=False) or fixed!=sha(BUILD/'manifest.json'):raise ValueError('host fixed source')
 save(BUILD/'host-verification.json',dict(receipt=o,stderr=r.stderr,before_after=True,manifest_sha256=fixed))
def compare(path,expected):
 p=Path(path);n=p.stat().st_size;e=expected['bytes'];dtype=np.dtype(expected['dtype'])
 if type(e) is not int or n!=e or n%dtype.itemsize:raise ValueError('exact output bytes')
 a=np.fromfile(p,dtype=dtype);b=np.fromfile(expected['path'],dtype=dtype)
 if a.size!=b.size or a.tobytes()!=b.tobytes():raise ValueError('canonical bits '+str(p))
 return record(p)
def validate(native,root,pci):
 m=read(BUILD/'manifest.json');qm=q_binding();expected=read(BUILD/'allocation-expectations.json')
 if native['source_id']!=m['source_id'] or native['PCI']!=pci or type(native['cases']) is not int or native['cases']!=len(qm['jobs']) or native['normal_audit_D2H'] is not False or native['whole_T25'] is not False:raise ValueError('native fixed identity/scope')
 if native['arch'].split(':')[0] not in ['gfx1100','gfx1201'] or type(native['ordinal']) is not int:raise ValueError('actual device observation')
 if type(native['meminfo_status']) is not int or (native['meminfo_status']==0 and (type(native['meminfo_free']) is not int or native['meminfo_free']<0)) or (native['meminfo_status']!=0 and native['meminfo_free'] is not None):raise ValueError('API status/unknown memory')
 if type(native['explicit_device_peak']) is not int or native['explicit_device_peak']!=max(x['device'] for x in expected.values()):raise ValueError('actual peak')
 rows=[]
 if len(native['jobs'])!=len(qm['jobs']):raise ValueError('job count')
 for actual,j in zip(native['jobs'],qm['jobs'],strict=True):
  e=expected[j['name']]
  if actual['name']!=j['name']:raise ValueError('job order')
  for field,key in [('actual_device_bytes','device'),('KV_read_bytes','KV_read'),('weight_H2D','weight_H2D'),('tiles','tiles')]:
   if type(actual[field]) is not int or actual[field]!=e[key]:raise ValueError('actual allocation/read/H2D/tiles '+field)
  for name,out in j['outputs'].items():rows.append(compare(Path(root)/j['name']/(name+'.bin'),out))
 loaded=[]
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']:
  found=[Path(p) for p in native['loaded_modules'] if Path(p).name.lower()==name]
  if len(found)!=1 or found[0].resolve()!= (BUNDLE/name).resolve() or sha(found[0])!=sha(BUNDLE/name):raise ValueError('actual owned runtime DLL binding')
  loaded.append(record(found[0]))
 return dict(files=rows,values=sum(x['bytes']//np.dtype(o['dtype']).itemsize for j in qm['jobs'] for o in j['outputs'].values() for x in [o]),loaded=loaded,jobs=len(qm['jobs']))
def execute(role,pci):
 if role not in ['primary','secondary'] or not pci:raise ValueError('explicit role/PCI')
 fixed=sha(BUILD/'manifest.json');binding();out=BUILD/(role+'-output')
 if out.exists():raise ValueError('old output attempt must be preserved')
 r=run([EXE,'--run',INPUT,out,pci],environment(True)[2],check=False);(BUILD/(role+'.stdout.json')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'.stderr.txt')).write_text(r.stderr,encoding='utf-8')
 if r.returncode:raise ValueError('native failure '+str(r.returncode))
 native=json.loads(r.stdout);result=validate(native,out,pci);binding()
 if sha(BUILD/'manifest.json')!=fixed:raise ValueError('trial changed during G')
 save(BUILD/(role+'-verification.json'),dict(result=result,native=record(BUILD/(role+'.stdout.json')),manifest_sha256=fixed,before_after=True,scope='helper-only offline, full task/state pending',global_resource_peak='unknown'))
 print(json.dumps(dict(role=role,**{k:v for k,v in result.items() if k!='files'})))
def replay(role):
 fixed=sha(BUILD/'manifest.json');binding();native=read(BUILD/(role+'.stdout.json'));result=validate(native,BUILD/(role+'-output'),native['PCI']);binding();save(BUILD/(role+'-CPU-replay.json'),dict(result=result,manifest_sha256=fixed,before_after=sha(BUILD/'manifest.json')==fixed))
def negatives(role,native=None,out=None):
 synthetic=native is not None;native=read(BUILD/(role+'.stdout.json')) if native is None else native;pci=native['PCI'];out=BUILD/(role+'-output') if out is None else out;cases=[]
 def rejects(label,change):
  bad=copy.deepcopy(native);change(bad)
  try:validate(bad,out,pci)
  except (ValueError,KeyError,TypeError,FileNotFoundError):cases.append(label);return
  raise ValueError('negative accepted '+label)
 for field in ['actual_device_bytes','KV_read_bytes','weight_H2D','tiles']:
  for value in [0,-1,True,1.0,None,native['jobs'][0][field]-1,native['jobs'][0][field]+1]:rejects(field+repr(value),lambda b,f=field,v=value:b['jobs'][0].__setitem__(f,v))
 for value in [0,-1,True,1.0,native['explicit_device_peak']+1]:rejects('peak'+repr(value),lambda b,v=value:b.__setitem__('explicit_device_peak',v))
 rejects('compiled',lambda b:b.__setitem__('source_id','0'*64));rejects('PCI',lambda b:b.__setitem__('PCI','different'));rejects('missingjob',lambda b:b['jobs'].pop());rejects('normalAudit',lambda b:b.__setitem__('normal_audit_D2H',True));rejects('DLL',lambda b:b.__setitem__('loaded_modules',[]))
 rejects('APIunknown',lambda b:b.__setitem__('meminfo_status',1));rejects('APIflagtype',lambda b:b.__setitem__('meminfo_status',True))
 for family,field,value in [('official','absolute_offset',0),('official','revision','changed'),('official','tensor','wrong'),('official','source',{}),('rows','head',23),('rows','global_row',0),('rows','absolute_offset',0),('rows','layer',14),('rows','position',7)]:
  bad=read(HERE/'fixture-receipts.json');bad[family][0][field]=value
  try:fixture_binding(bad)
  except (ValueError,KeyError,StopIteration):cases.append('fixture '+family+field);continue
  raise ValueError('fixture provenance mutation accepted')
 for family in ['gate','row']:
  for field in range(5):
   bad=read(HERE/'fixture-receipts.json');target=bad['gguf_gates'][0]['source_file'] if family=='gate' else bad['row_file'];target[field]='wrong'
   try:fixture_binding(bad)
   except (ValueError,KeyError,StopIteration):cases.append('SourceFile '+family+str(field));continue
   raise ValueError('SourceFile tuple mutation accepted')
 for kind in ['empty','missing','duplicate','unknown','identity','checkpoint','observation']:
  bad=read(HERE/'fixture-receipts.json');proofs=bad['individual_final_proofs']
  if kind=='empty':bad['individual_final_proofs']=[]
  elif kind=='missing':proofs.pop()
  elif kind=='duplicate':proofs[1]=copy.deepcopy(proofs[0])
  elif kind=='unknown':proofs[1]['index']=999
  elif kind=='identity':proofs[1]['current_identity']=copy.deepcopy(proofs[0]['current_identity'])
  elif kind=='checkpoint':proofs[1]['checkpoint']=copy.deepcopy(proofs[0]['checkpoint'])
  else:proofs[1]['recorded_observation']=copy.deepcopy(proofs[0]['recorded_observation'])
  try:fixture_binding(bad)
  except (ValueError,KeyError,StopIteration):cases.append('individual proof '+kind);continue
  raise ValueError('individual proof coverage mutation accepted')
 qm=q_binding();target=next(iter(qm['jobs'][0]['outputs'].values()));scratch=BUILD/'negative-output.bin';original=Path(target['path']).read_bytes()
 for name,data in [('append',original+b'!'),('truncate',original[:-1]),('bitflip',bytes([original[0]^1])+original[1:])]:
  scratch.write_bytes(data)
  try:compare(scratch,target)
  except ValueError:cases.append(name);continue
  raise ValueError('output mutation accepted')
 save(BUILD/(role+'-negatives.json'),dict(rejected=cases,count=len(cases),positive_capture=validate(native,out,pci)['jobs'],synthetic_preflight=synthetic,GPU_used=False))
def preflight():
 qm=q_binding();m=read(BUILD/'manifest.json');expected=read(BUILD/'allocation-expectations.json');native=dict(source_id=m['source_id'],PCI='preflight-not-device-observation',cases=len(qm['jobs']),normal_audit_D2H=False,whole_T25=False,arch='gfx1201',ordinal=0,meminfo_status=0,meminfo_free=0,explicit_device_peak=max(x['device'] for x in expected.values()),loaded_modules=[str(BUNDLE/n) for n in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']],jobs=[dict(name=j['name'],actual_device_bytes=expected[j['name']]['device'],KV_read_bytes=expected[j['name']]['KV_read'],weight_H2D=expected[j['name']]['weight_H2D'],tiles=expected[j['name']]['tiles']) for j in qm['jobs']]);negatives('preflight',native,Q)
def reseal():
 """R1/R2 CPU oracle/validator correction; native exact binary is retained."""
 if (BUILD/'manifest.json').exists():raise ValueError('existing fixed trial must be retained before reseal')
 old=read(BUILD/'attempt-G-r1/manifest.json');before=read(BUILD/'attempt-G-r1/q/manifest.json');qm=q_binding();byname={j['name']:j for j in qm['jobs']};checked=0
 for j in before['jobs']:
  for name,x in j['outputs'].items():
   y=byname[j['name']]['outputs'][name]
   if any(x[k]!=y[k] for k in ['bytes','sha256','dtype','shape']):raise ValueError('old Q data changed after G')
   checked+=1
 if sha(EXE)!=sha(BUILD/'attempt-G-r1/t25-engram.exe') or sha(BUILD/'source-map.json')!=old['source_snapshot']['sha256']:raise ValueError('native/snapshot changed')
 snapshot=BUILD/'immutable-source';native_sources=[HERE/'fixture.hip',HERE/'CMakeLists.txt']
 for p in native_sources:
  if sha(p)!=sha(BUILD/'attempt-G-r1/owned-source'/p.name):raise ValueError('native recipe changed: rebuild required')
 for p in OWN:shutil.copy2(p,snapshot/p.relative_to(ROOT))
 save(BUILD/'prior-Q-native-unchanged.json',dict(old_expected_files=checked,old_jobs=len(before['jobs']),old_Q_data_SHA_unchanged=True,original_Q_manifest=record(BUILD/'attempt-G-r1/q/manifest.json'),native_EXE=record(EXE),same_native_as_development=True,new_independent_N='fixed before new qualification G; no G output read by N/Q'))
 save(BUILD/'allocation-expectations.json',{j['name']:dict(device=expected_capacity(j),KV_read=167116800 if j['kind']=='real' else 0,weight_H2D=167116800 if j['kind']=='real' else 0,tiles=100 if j['kind']=='real' else 0) for j in qm['jobs']});save(BUILD/'CPU-runtime.json',numpy_runtime());_,tools,_=environment()
 files=list(snapshot.rglob('*'))+list(BUNDLE.rglob('*'))+list(INPUT.rglob('*'))+list(Q.rglob('*'))+list((BUILD/'reference-source').rglob('*'))+list((BUILD/'raw').glob('*.bin'))+OWN+[Path(x['path']) for x in old['binding'] if Path(x['path']).is_file()]+[BUILD/'independent-N-full-gate.json',BUILD/'prior-Q-native-unchanged.json']
 m=copy.deepcopy(old);m['binding']=[record(p) for p in sorted(set(files)) if p.is_file()];m['own_sources']=[record(snapshot/p.relative_to(ROOT)) for p in OWN];m['Q']=record(Q/'manifest.json');m['revision']='r2 CPU N/source tuple correction; native exact unchanged; new qualification G required';save(BUILD/'manifest.json',m);binding();host();preflight();print(json.dumps(dict(manifest=record(BUILD/'manifest.json'),exe=record(EXE),Q=record(Q/'manifest.json'),native_unchanged=True,G0_for_new_N=True)))
def actual_prepare():
 target=BUILD/'actual';target.mkdir(exist_ok=True);out=target/'q';inp=target/'input';out.mkdir(exist_ok=True);inp.mkdir(exist_ok=True);c=read(HERE/'contract.json')['actual'];full=acq.module('t25_full_sources',EXT/'native/artifact/full_acquire.py');receipt=read(EXT/'tests/artifact/full-model-receipt.json');full.validate_receipt(receipt,full.DESTINATION,read(EXT/'tests/artifact/source-files.json'),read(EXT/'tests/artifact/header-inventory.json'),read(EXT/'tests/artifact/fixture-receipts.json'));save(target/'source-qualification.json',dict(receipt=record(EXT/'tests/artifact/full-model-receipt.json'),explicit_validation=True,normal_start_new_gate=False,current_identities=[dict(index=x['index'],identity=full.stat_identity(x['path'])) for x in receipt['files']]))
 held=sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file());free=shutil.disk_usage(ROOT).free;future=6*2**30+128*2**20+3*32*2**20+64*2**20+2**30;save(target/'storage-start.json',dict(free=free,existing_T25_held_already_in_free=held,model_remaining_length=0,T20_future=6*2**30,new_actual_estimate=2**30,other_future=128*2**20+3*32*2**20+64*2**20,metadata=2**24,remaining_after=free-future-2**24,normal_cap=False))
 inv=read(EXT/'tests/artifact/header-inventory.json');(inp/'prefixes.tsv').write_text(''.join(str(s['bytes'])+'\t'+s['prefix_path']+'\n' for s in inv['shards']),encoding='utf-8');shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',inp/'sources.tsv');jobs=[];lines=[];allreads=[];alldiag=[]
 for first,end in c['ranges']:
  for hold,tokens in c['holdouts'].items():
   oracle=q.ActualOracle(ROOT);oracle.reset();name=f'R{first}-{end}-{hold}';frames=[];boundaries=[];pre=np.array(c['range0_pre'] if first==0 else c['other_pre'],np.float32).reshape(1,4)
   for position,token in enumerate(tokens):
    residual=q.residual(3,hold)[position:position+1].reshape(1,4,5120);hp=inp/f'{name}-P{position}-h.bin';pp=inp/f'{name}-P{position}-pre.bin';residual.tofile(hp);pre.tofile(pp);boundaries.append(dict(position=position,token=token,residual=record(hp),pre=record(pp)))
    result,nextpre,values=oracle.step(first,end,token,position,residual,pre);stepdir=out/name/f'P{position}';stepdir.mkdir(parents=True,exist_ok=True);saved=[]
    for frame in values:
     layerdir=stepdir/f'L{frame["layer"]}';layerdir.mkdir(exist_ok=True);stages={k:array(layerdir/(k+'.bin'),v) for k,v in frame['stages'].items()};saved.append(dict(position=position,layer=frame['layer'],stages=stages))
    frames.extend(saved);array(stepdir/'capture-residual.bin',result.reshape(1,20480));array(stepdir/'capture-pre.bin',nextpre);save(target/'Q-progress.json',dict(range=[first,end],holdout=hold,position_complete=position,frames_fixed=len(frames),G0=True))
   files=[record(p) for p in sorted((out/name).rglob('*.bin'))];jobs.append(dict(name=name,first=first,end=end,holdout=hold,tokens=tokens,boundaries=boundaries,frames=frames,files=files));lines.append('\t'.join(map(str,[name,first,end,hold,','.join(map(str,tokens)),name])));allreads.extend(oracle.reads);alldiag.extend(oracle.diagnostics)
   if hold=='A':lines.append('\t'.join(map(str,[name+'-replay',first,end,hold,','.join(map(str,tokens)),name])))
 (inp/'actual-jobs.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8');save(target/'N-source-spans.json',dict(reads=allreads,diagnostics=alldiag,G_outputs_used=False));save(out/'manifest.json',dict(schema='T25-actual-independent-Q/v1',jobs=jobs,contract=record(HERE/'contract.json'),source_qualification=record(target/'source-qualification.json'),oracle_sources=[record(p) for p in [HERE/'reference.py',HERE/'test_reference.py']+[EXT/f'tests/{d}/{n}' for d,n in [('quant','q_reference.py'),('mhc','reference.py'),('ffn','reference.py'),('engram','reference.py'),('kv','reference.py'),('attention','reference.py')]]],inputs=[record(p) for p in sorted(inp.iterdir())],N_spans=record(target/'N-source-spans.json'),GPU_executed=False,main_calls=18,replay_calls=9,full_T25=False));print(json.dumps(dict(actual_Q=record(out/'manifest.json'),G0=True)))
def actual_q_binding():
 t=BUILD/'actual';m=read(t/'q/manifest.json');verify([m['contract'],m['source_qualification'],m['N_spans']]+m['oracle_sources']+m['inputs'])
 if (m['main_calls'],m['replay_calls'],m['GPU_executed'])!=(18,9,False) or len(m['jobs'])!=6:raise ValueError('actual Q coverage')
 for job in m['jobs']:verify(job['files'])
 return m

def actual_build():
 t=BUILD/'actual';qm=actual_q_binding();snapshot=t/'immutable-source';mapping=read(t/'source-map.json');verify(mapping);bundle=t/'bundle';bundle.mkdir(exist_ok=True)
 if (t/'manifest.json').exists():raise ValueError('preserve fixed actual bundle first')
 for p in OWN:
  dst=snapshot/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
 identity=aggregate([dict(path=x['relative'],sha256=x['sha256']) for x in mapping]+[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in OWN if p.suffix=='.hip']);sdk,tools,env=environment();native=t/'cmake-native';source=snapshot/HERE.relative_to(ROOT)
 commands=[[tools['cmake'],'--fresh','-S',source,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',f'-DT25_SNAPSHOT={snapshot.as_posix()}',f'-DT25_SOURCE_ID={identity}',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,cmd in enumerate(commands):
  r=run(cmd,env,check=False);(t/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise ValueError('actual build failed '+str(i))
 exe=bundle/'t25-engram.exe';shutil.copy2(native/'bundle/t25-engram.exe',exe);origins=[]
 for n in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
  p=sdk/'bin'/n;shutil.copy2(p,bundle/n);origins.append(dict(origin=record(p),target=record(bundle/n)))
 shutil.copytree(BUNDLE/'licenses',bundle/'licenses',dirs_exist_ok=True);(t/'offloading.log').write_text(run([tools['objdump'],'--offloading',exe],env).stdout,encoding='utf-8');(t/'direct-imports.log').write_text(run([tools['dumpbin'],'/DEPENDENTS',exe],env).stdout,encoding='utf-8')
 save(t/'CPU-runtime.json',numpy_runtime());files=list(snapshot.rglob('*'))+list(bundle.rglob('*'))+list((t/'input').rglob('*'))+list((t/'q').rglob('*'))+OWN+list(tools.values())+[Path(sys.executable),t/'source-map.json',t/'N-source-spans.json',t/'source-qualification.json',t/'CPU-runtime.json',t/'expected-prepare-recipe.py',t/'expected-prepare-recipe.json']
 save(t/'manifest.json',dict(schema='T25-actual-fixed-trial/v1',source_id=identity,binding=[record(p) for p in sorted(set(files)) if p.is_file()],DLL_origins=origins,Q=record(t/'q/manifest.json'),normal_audit_D2H=False,full_T25=False,main_calls=18,replay_calls=9,total_calls=27,layers=81,patches=[]))
 env=actual_environment();r=run([exe,'--identity'],env);need=json.loads(r.stdout)
 if need!={'source_id':identity}:raise ValueError('actual identity')
 r=run([exe,'--host',t/'input',t/'host-output'],env);save(t/'host-verification.json',dict(receipt=json.loads(r.stdout),stderr=r.stderr));print(json.dumps(dict(manifest=record(t/'manifest.json'),exe=record(exe),G0=True)))

def actual_environment():
 env=environment(True)[2];t=BUILD/'actual';temp=t/'tmp';temp.mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(temp);env['PATH']=os.pathsep.join([str(t/'bundle'),env.get('SystemRoot','C:/Windows')+'/System32',env.get('SystemRoot','C:/Windows')]);return env

def actual_capacity():
 # Constructor allocations are simultaneously live, no aliases. Derive from
 # the immutable consumed declaration, independently of native receipt fields.
 t=BUILD/'actual';source=t/'immutable-source/Strata-extensions/models/deepseek41/core.hip';body=source.read_text(encoding='utf-8').split(' Impl(const Artifact&a')[1].split(' unsigned source_slot')[0];lines=body.splitlines();entries=[]
 def add(name,elements,width=4):entries.append(dict(name=name,bytes=elements*width))
 add('40 independent SWA rings',40*128*512)
 for writer,ratio in [(2,2),(8,2),(14,2),(20,1)]:add('compression/key state '+str(writer),2048+max(1,3//ratio)*640)
 add('candidate scores',3);add('two MHC workspaces',2*73)
 for line in lines:
  if not any(s in line for s in ['residual_a=','block.attention=','output_norm_inverse=','ffn.input_qdq=','attention.input_qdq=','compress_work.kv_dot=','index.key_dot=','engram_embedding=']):continue
  line=line.replace('(capacity+7)/8','1')
  for match in re.finditer(r'\b(alloc|bf)\((\d+),([^,)]+)(?:,DeviceScalar::(\w+))?\)',line):
   r=int(match[2]);c=eval(match[3],{'__builtins__':{}},{'capacity':3});width={'UInt8':1,'Int64':8}.get(match[4],4);add(match[0],r*c,width)
 core=sum(x['bytes'] for x in entries);weight=2*2**21+2*32768*4;row=((2*264+255)//256)*256+2048
 inv=read(EXT/'tests/artifact/header-inventory.json');tensors={x['name']:x for s in inv['shards'] for x in s['tensors']};jobs={}
 for first,end in [(0,2),(20,25),(2,4)]:
  names=set()
  for layer in range(first,end):
   p=f'blk.{layer}.';names.update(p+n for n in ['hc_attn_scale.weight','hc_attn_base.weight','attn_norm.weight','hc_ffn_scale.weight','hc_ffn_base.weight','ffn_norm.weight','attn_q_a_norm.weight','attn_kv_a_norm.weight','attn_sinks.weight','exp_probs_b.bias','exp_probs_b_vl.bias'])
   if layer in [1,14]:names.add(p+'engram_gate.weight')
   if layer in [2,8,14,20]:names.update(p+n for n in ['attn_compressor_norm.weight','indexer.k_norm.weight'])
  constants=sum(tensors[n]['bytes'] for n in names);jobs[f'R{first}-{end}']=dict(core_base=core,constants=constants,constant_names=sorted(names),weight_device=weight,row_device=row,device_peak=core+constants+weight+row,aliases_double_counted=0)
 return dict(constructor_entries=entries,jobs=jobs,driver_context_peak=None,host_physical_peak=None,source=record(source),capacity=3,normal_limit=False)

def actual_validate(native,out,pci):
 t=BUILD/'actual';m=read(t/'manifest.json');qm=actual_q_binding();capacity=read(t/'allocation-expectations.json');byname={j['name']:j for j in qm['jobs']};expected_names=[x.split('\t')[0] for x in (t/'input/actual-jobs.tsv').read_text().splitlines()]
 for k,v in {'cases':9,'calls':27,'frames':81,'rejections':54}.items():
  if type(native.get(k)) is not int or native[k]!=v:raise ValueError('actual total '+k)
 if native['source_id']!=m['source_id'] or native['PCI']!=pci or native['normal_audit_D2H'] is not False or native['whole_T25'] is not False or [j['name'] for j in native['jobs']]!=expected_names:raise ValueError('actual identity/order')
 if type(native.get('ordinal')) is not int or native['ordinal']<0 or type(native.get('arch')) is not str or not native['arch']:raise ValueError('actual observed device')
 status=native.get('meminfo_status');free=native.get('meminfo_free')
 if type(status) is not int or status<0 or (status==0 and (type(free) is not int or free<0)) or (status!=0 and free is not None):raise ValueError('actual memory status/unknown')
 trace=actual_counter_trace()['jobs']
 allfiles=[];peak=0;values=0
 for got in native['jobs']:
  name=got['name'];job=byname[name.removesuffix('-replay')];c=capacity['jobs'][f'R{job["first"]}-{job["end"]}'];peak=max(peak,c['device_peak']);expect={'calls':3,'frames':3*(job['end']-job['first']),'rejections':6,'device_owned':c['device_peak'],'weight_device_owned':c['weight_device'],'row_device_owned':c['row_device']}
  for k,v in expect.items():
   if type(got.get(k)) is not int or got[k]!=v:raise ValueError('actual capacity/coverage '+k)
  stages={(f['position'],f['layer'],n):v for f in job['frames'] for n,v in f['stages'].items()}
  if len(got['stages'])!=len(stages):raise ValueError('actual stage count')
  seen=set();audit=0
  for s in got['stages']:
   key=(s['position'],s['layer'],s['name'])
   if key not in stages or key in seen:raise ValueError('actual stage identity/duplicate')
   seen.add(key);e=stages[key];shape=e['shape'];rows=shape[0] if len(shape)==2 else int(np.prod(shape[:-1]));cols=shape[-1];dtype=np.dtype(e['dtype']);float_stages={'ffn_router_logits','ffn_router_weights','block_next_pre','engram_act_qdq','engram_kv_dot','engram_gates'};scalar=4 if dtype.str=='<u4' else 5 if dtype.str=='<i4' else 6 if dtype.str=='<i8' else 0 if key[2] in float_stages else 2
   # Bfloat16InFloat32 is enum 2; half-width Bfloat16 (enum 1) is distinct.
   cap=128*512*4 if key[2]=='attention_window' else 512*4 if key[2]=='index_selected' else 3*4 if key[2]=='index_score' else e['bytes']
   if any(type(s[k]) is not int for k in ['rows','columns','scalar','bytes','capacity']) or (s['rows'],s['columns'],s['scalar'],s['bytes'],s['capacity'])!=(rows,cols,scalar,e['bytes'],cap):raise ValueError('actual stage geometry/scalar')
   path=Path(out)/name/f'P{key[0]}'/f'L{key[1]}'/(key[2]+'.bin');allfiles.append(compare(path,e));audit+=e['bytes'];values+=int(np.prod(shape))
  if got['audit_D2H']!=audit or type(got['audit_D2H']) is not int:raise ValueError('actual audit bytes')
  for k in ['weight_read','weight_H2D','row_read','row_H2D']:
   if type(got.get(k)) is not int or got[k]<0:raise ValueError('actual counter type/sign')
  if got['weight_read']<=0 or got['weight_read']!=got['weight_H2D'] or got['row_read']!=got['row_H2D'] or (got['row_read']>0)!=(job['first']==0) or got['row_read']%264:raise ValueError('actual source transfer boundary')
  for k in ['weight_read','weight_H2D','row_read','row_H2D']:
   if got[k]!=trace[job['name']][k]:raise ValueError('actual exact source transfer '+k)
  for e in job['files']:
   if Path(e['path']).name.startswith('capture-'):
    relative=Path(e['path']).relative_to(t/'q'/job['name']);p=Path(out)/name/relative
    if p.stat().st_size!=e['bytes'] or sha(p)!=e['sha256']:raise ValueError('actual returned capture bytes')
    allfiles.append(record(p));values+=e['bytes']//4
  actual={p.relative_to(Path(out)/name).as_posix() for p in (Path(out)/name).rglob('*.bin')};wanted={Path(e['path']).relative_to(t/'q'/job['name']).as_posix() for e in job['files']}
  if actual!=wanted:raise ValueError('actual output file set')
 if type(native.get('explicit_device_peak')) is not int or native['explicit_device_peak']!=peak:raise ValueError('actual total peak')
 loaded=[]
 for n in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']:
  paths=[Path(p) for p in native['loaded_modules'] if Path(p).name.lower()==n]
  if len(paths)!=1 or paths[0].resolve()!=(t/'bundle'/n).resolve():raise ValueError('actual owned DLL')
  loaded.append(record(paths[0]))
 return dict(values=values,outputs=allfiles,loaded_DLL=loaded,exact=True,whole_T25=False)

def actual_seal():
 t=BUILD/'actual';actual_q_binding();m=read(t/'manifest.json');save(t/'allocation-expectations.json',actual_capacity())
 # No G has run. Keep the exact build invocation and bind the final validator
 # separately from the immutable fixture actually consumed by the compiler.
 for p in OWN:
  if p.suffix!='.hip':dst=t/'immutable-source'/p.relative_to(ROOT);shutil.copy2(p,dst)
 paths=[Path(x['path']) for x in m['binding']]+[t/'allocation-expectations.json',BUILD/'actual-state-pre-v2.md',t/'preflight.json',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/source-files.json',EXT/'tests/artifact/full-model-receipt.json']+[Path(s['prefix_path']) for s in read(EXT/'tests/artifact/header-inventory.json')['shards']]
 paths=[p for p in paths if p.is_file()];m['binding']=[record(p) for p in sorted(set(paths))];m['validator']=record(HERE/'build_verify.py');save(t/'manifest.json',m);verify(m['binding']);print(json.dumps(dict(manifest=record(t/'manifest.json'),Q=record(t/'q/manifest.json'),G0=True)))

def actual_run(pci):
 t=BUILD/'actual';fixed=sha(t/'manifest.json');m=read(t/'manifest.json');verify(m['binding']);actual_q_binding();full=acq.module('t25_actual_identity',EXT/'native/artifact/full_acquire.py');identities=read(t/'source-qualification.json')['current_identities'];receipt=read(EXT/'tests/artifact/full-model-receipt.json')
 if identities!=[dict(index=x['index'],identity=full.stat_identity(x['path'])) for x in receipt['files']]:raise ValueError('actual full source current identity')
 out=t/'G-primary';out.mkdir(exist_ok=False);r=run([t/'bundle/t25-engram.exe','--actual',t/'input',out,pci],actual_environment(),timeout=7200,check=False);(out/'stdout.json').write_text(r.stdout,encoding='utf-8');(out/'stderr.log').write_text(r.stderr,encoding='utf-8')
 if r.returncode:raise ValueError('actual native failed '+str(r.returncode))
 native=json.loads(r.stdout);proof=actual_validate(native,out,pci);verify(m['binding'])
 if sha(t/'manifest.json')!=fixed:raise ValueError('actual manifest changed')
 save(t/'verification.json',dict(manifest=record(t/'manifest.json'),exe=record(t/'bundle/t25-engram.exe'),Q=record(t/'q/manifest.json'),native=record(out/'stdout.json'),comparison=proof,before_after=True,scope='bounded explicit boundary real layer/state; full T25 pending'))

def actual_preflight():
 t=BUILD/'actual';qm=actual_q_binding();root=t/('preflight-'+str(time.time_ns()));root.mkdir();cap=actual_capacity();byname={j['name']:j for j in qm['jobs']};trace=actual_counter_trace()['jobs'];native=dict(source_id=read(t/'manifest.json')['source_id'],PCI='synthetic',ordinal=0,arch='synthetic',meminfo_status=0,meminfo_free=1234,cases=9,calls=27,frames=81,rejections=54,normal_audit_D2H=False,whole_T25=False,jobs=[],explicit_device_peak=max(c['device_peak'] for c in cap['jobs'].values()),loaded_modules=[str(t/'bundle'/n) for n in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']])
 for line in (t/'input/actual-jobs.tsv').read_text().splitlines():
  name=line.split('\t')[0];qj=byname[name.removesuffix('-replay')];dest=root/name;shutil.copytree(t/'q'/qj['name'],dest);c=cap['jobs'][f'R{qj["first"]}-{qj["end"]}'];stages=[]
  for frame in qj['frames']:
   for n,e in frame['stages'].items():
    shape=e['shape'];dtype=np.dtype(e['dtype']);scalar=4 if dtype.str=='<u4' else 5 if dtype.str=='<i4' else 0 if n in {'ffn_router_logits','ffn_router_weights','block_next_pre','engram_act_qdq','engram_kv_dot','engram_gates'} else 2;capacity=128*512*4 if n=='attention_window' else 2048 if n=='index_selected' else 12 if n=='index_score' else e['bytes'];stages.append(dict(position=frame['position'],layer=frame['layer'],name=n,rows=int(np.prod(shape[:-1])),columns=shape[-1],scalar=scalar,bytes=e['bytes'],capacity=capacity))
  native['jobs'].append(dict(name=name,calls=3,frames=len(qj['frames']),rejections=6,device_owned=c['device_peak'],weight_device_owned=c['weight_device'],row_device_owned=c['row_device'],**{k:trace[qj['name']][k] for k in ['weight_read','weight_H2D','row_read','row_H2D']},audit_D2H=sum(s['bytes'] for s in stages),stages=stages))
 actual_validate(native,root,'synthetic');rejected=[]
 def bad(label,mutate):
  x=copy.deepcopy(native);mutate(x)
  try:actual_validate(x,root,'synthetic')
  except (ValueError,KeyError,TypeError):rejected.append(label);return
  raise ValueError('actual mutant accepted '+label)
 for key in ['cases','calls','frames','rejections','explicit_device_peak']:
  for value in [0,-1,True,1.0]:bad(f'{key}-{value!r}',lambda x,k=key,v=value:x.__setitem__(k,v))
 for key in ['device_owned','weight_device_owned','row_device_owned','audit_D2H','frames','rejections']:
  for value in [0,-1,True,1.0]:bad(f'job-{key}-{value!r}',lambda x,k=key,v=value:x['jobs'][0].__setitem__(k,v))
 for key in ['rows','columns','bytes','capacity','scalar','layer','position']:
  bad('stage-'+key,lambda x,k=key:x['jobs'][0]['stages'][0].__setitem__(k,-1))
 bad('missing-stage',lambda x:x['jobs'][0]['stages'].pop());bad('duplicate-stage',lambda x:x['jobs'][0]['stages'].append(x['jobs'][0]['stages'][0]));bad('missing-case',lambda x:x['jobs'].pop());bad('wrong-DLL',lambda x:x['loaded_modules'].__setitem__(0,'C:/Windows/amdhip64_7.dll'))
 for k in ['weight_read','weight_H2D','row_read','row_H2D']:
  for v in [0,-1,True,1.0,native['jobs'][0][k]-1,native['jobs'][0][k]+1]:bad(k+'-'+repr(v),lambda x,k=k,v=v:x['jobs'][0].__setitem__(k,v))
 bad('memory-bool-status',lambda x:x.__setitem__('meminfo_status',True));bad('memory-bool-free',lambda x:x.__setitem__('meminfo_free',True));bad('memory-failed-observed-zero',lambda x:x.__setitem__('meminfo_status',1))
 unknown=copy.deepcopy(native);unknown['meminfo_status']=1;unknown['meminfo_free']=None;actual_validate(unknown,root,'synthetic')
 path=next(root.rglob('attention_output.bin'));original=path.read_bytes()
 for label,b in [('append',original+b'X'),('truncate',original[:-1]),('bitflip',bytes([original[0]^1])+original[1:])]:
  path.write_bytes(b)
  try:actual_validate(native,root,'synthetic')
  except ValueError:rejected.append(label)
  else:raise ValueError('actual output mutant accepted')
 path.write_bytes(original);actual_validate(native,root,'synthetic');post=(t/'capture-r1').exists();save(t/('post-preflight.json' if post else 'preflight.json'),dict(rejected=rejected,count=len(rejected),positive='synthetic Q-copy and failed-query null only; no G qualification',root=str(root),G0=not post));print(json.dumps(dict(rejected=len(rejected),G0=not post)))

def actual_counter_trace():
 t=BUILD/'actual';n=read(t/'N-source-spans.json');d=[x for x in n['diagnostics'] if 'tensor' in x];start=[i for i,x in enumerate(d) if x['tensor'] in ['blk.0.hc_attn_fn.weight','blk.20.hc_attn_fn.weight','blk.2.hc_attn_fn.weight']]+[len(d)]
 if len(start)!=19:raise ValueError('independent projection frame boundaries')
 tensors={x['name']:x for s in read(EXT/'tests/artifact/header-inventory.json')['shards'] for x in s['tensors']};jobs={}
 for i,j in enumerate(read(t/'q/manifest.json')['jobs']):
  gpu=[None,None];ram=[None,None];logical=0;h2d=0;hits=[];ramhits=[];cold=0
  for ci,c in enumerate(d[start[i*3]:start[i*3+3]]):
   v=tensors[c['tensor']];dims=v.get('dims_ggml',v.get('dims'));rb=v['row_bytes'];chunk=min(256,2097152//rb)
   if chunk<=0 or c['K']!=dims[0]:raise ValueError('source full-K finite tile')
   for off in range(0,c['count'],chunk):
    count=min(chunk,c['count']-off);absolute=v['absolute_offset']+(c['matrix']*dims[1]+c['first']+off)*rb;key=(c['tensor'],absolute,count,rb)
    if absolute<v['absolute_offset'] or count*rb>v['bytes']-(absolute-v['absolute_offset']):raise ValueError('counter original span')
    if key in gpu:hits.append(dict(call=ci,key=key,bytes=count*rb));continue
    if key in ram:ramhits.append(dict(call=ci,key=key,bytes=count*rb))
    else:logical+=count*rb;cold+=1;ram[ram.index(None) if None in ram else 0]=key
    h2d+=count*rb;gpu[gpu.index(None) if None in gpu else 0]=key
  jobs[j['name']]=dict(weight_read=logical,weight_H2D=h2d,gpu_hits=hits,ram_hits=ramhits,cold_tiles=cold,row_read=19008 if j['first']==0 else 0,row_H2D=19008 if j['first']==0 else 0)
 return dict(jobs=jobs,N=record(t/'N-source-spans.json'),derivation='sealed independent Q projection call order; full-K 2MiB/256row tiles; two GPU/RAM slots, empty first then eligible valid index0; 24 disjoint head rows x3 appends over two-slot row caches',G_outputs_used=False,recipe_created_after_initial_G_start=True)

def actual_capture_binding():
 t=BUILD/'actual';m=read(t/'manifest.json');rows=[]
 for row in m['binding']:
  x=dict(row)
  if Path(x['path'])==HERE/'build_verify.py':x['path']=str(t/'immutable-source'/Path(x['path']).relative_to(ROOT))
  rows.append(x)
 verify(rows);actual_q_binding();actual_current_sources();r=run([t/'bundle/t25-engram.exe','--identity'],actual_environment())
 if json.loads(r.stdout)!={'source_id':m['source_id']}:raise ValueError('historical capture compiled binding')
 return rows

def actual_current_sources():
 t=BUILD/'actual';full=acq.module('t25_actual_current',EXT/'native/artifact/full_acquire.py');receipt=read(EXT/'tests/artifact/full-model-receipt.json');observed=[dict(index=x['index'],identity=full.stat_identity(x['path'])) for x in receipt['files']]
 if observed!=read(t/'source-qualification.json')['current_identities']:raise ValueError('original qualified source identity changed since before G')
 return observed

def actual_revalidate():
 t=BUILD/'actual';rows=actual_capture_binding();old=read(t/'capture-r1/verification.json');verify([old[k] for k in ['manifest','exe','Q','native']]);trace=actual_counter_trace();save(t/'countertrace-final.json',trace)
 runtime=read(t/'CPU-runtime.json');runtime_rows=runtime['loaded']+runtime['modules']+[runtime['interpreter']];verify(runtime_rows);verify([read(HERE/'fixture-receipts.json')['T13_NQ']])
 deps=[EXT/'native/artifact'/n for n in ['full_acquire.py','acquire.py','gguf.py']]+[ROOT/'build-deepseek-t13/nq.json']
 fixed=[record(HERE/'build_verify.py'),record(t/'manifest.json'),record(t/'capture-r1/verification.json'),record(t/'capture-r1/own-map.json'),record(t/'G-primary/stdout.json'),record(t/'q/manifest.json'),record(t/'countertrace-final.json'),record(t/'GPU-before.json'),record(t/'shared-window.json')]+[record(p) for p in deps]+runtime_rows;save(t/'CPU-validator-manifest.json',dict(binding=fixed,capture_source_rows=rows,new_validator_only=True,native_rebuild=False,G_reexecuted=False));verify(fixed)
 actual_preflight();native=read(t/'G-primary/stdout.json');proof=actual_validate(native,t/'G-primary',native['PCI']);actual_capture_binding();verify(fixed)
 save(t/'CPU-verification.json',dict(validator=record(t/'CPU-validator-manifest.json'),capture_manifest=record(t/'manifest.json'),capture_EXE=record(t/'bundle/t25-engram.exe'),Q=record(t/'q/manifest.json'),comparison=proof,countertrace=record(t/'countertrace-final.json'),negatives=record(t/'post-preflight.json'),before_after=True,original_source_identities_same_as_before_G=actual_current_sources(),G_reexecuted=False,scope='27 explicit-boundary calls /81 actual layers; full T25/S5-2/all40/server unqualified',isolated_performance=False,physical_peak=None))
 save(t/'verification-final.json',dict(capture=record(t/'capture-r1/verification.json'),CPU_validation=record(t/'CPU-verification.json'),capture_manifest=record(t/'manifest.json'),source_snapshot=record(t/'source-map.json'),new_validator=record(HERE/'build_verify.py'),whole_T25=False));print(json.dumps(dict(final=record(t/'verification-final.json'),counter_exact=True,G_reexecuted=False)))

def restore_prepare():
 t=BUILD/'state-restore';inp=t/'input';out=t/'q';inp.mkdir(parents=True,exist_ok=True);out.mkdir(exist_ok=True)
 if (out/'manifest.json').exists():raise ValueError('preserve fixed restore Q')
 actual_current_sources();inputs,expected,spans,diagnostics=q.small_restore_expected(ROOT)
 for n,v in inputs.items():array(inp/(n+'.bin'),v)
 for n in ['sources.tsv','prefixes.tsv']:shutil.copy2(BUILD/'actual/input'/n,inp/n)
 outputs={}
 for name,values in expected.items():
  d=out/name;d.mkdir();outputs[name]={k:array(d/(k+'.bin'),v) for k,v in values.items()}
 save(t/'N-source-spans.json',dict(reads=spans,diagnostics=diagnostics,G_used=False));save(out/'manifest.json',dict(inputs=[record(p) for p in inp.iterdir()],outputs=outputs,N=record(t/'N-source-spans.json'),contract=record(HERE/'contract.json'),oracle_sources=[record(HERE/'reference.py')]+[record(EXT/f'tests/{d}/reference.py') for d in ['kv','attention','mhc','ffn','engram']]+[record(EXT/'tests/quant/q_reference.py')],source_qualification=record(BUILD/'actual/source-qualification.json'),GPU_executed=False,checkpoints=[1,2],snapshot_bytes=[4096,2048],capacity_pending=8192,capacity_cache=4096))
 print(json.dumps(dict(Q=record(out/'manifest.json'),G0=True)))

def restore_q_binding():
 t=BUILD/'state-restore';m=read(t/'q/manifest.json');verify(m['inputs']+m['oracle_sources']+[m[k] for k in ['N','contract','source_qualification']]);actual_current_sources()
 for outputs in m['outputs'].values():verify(list(outputs.values()))
 if m['GPU_executed'] is not False or m['checkpoints']!=[1,2] or m['snapshot_bytes']!=[4096,2048]:raise ValueError('restore Q contract')
 return m

def restore_build():
 t=BUILD/'state-restore';restore_q_binding();snapshot=t/'immutable-source';mapping=read(BUILD/'actual/source-map.json');verify(mapping)
 if (t/'manifest.json').exists():raise ValueError('preserve restore build')
 for row in mapping:
  dest=snapshot/row['relative'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(row['path'],dest)
 for p in OWN:
  dest=snapshot/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
 identity=aggregate([dict(path=x['relative'],sha256=x['sha256']) for x in mapping]+[record(p) for p in OWN]);sdk,tools,env=environment();native=t/'cmake-native';source=snapshot/HERE.relative_to(ROOT)
 commands=[[tools['cmake'],'--fresh','-S',source,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',f'-DT25_SNAPSHOT={snapshot.as_posix()}',f'-DT25_SOURCE_ID={identity}',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,cmd in enumerate(commands):
  r=run(cmd,env,timeout=900,check=False);(t/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise ValueError('restore build failed '+str(i))
 bundle=t/'bundle';bundle.mkdir(exist_ok=True);shutil.copy2(native/'bundle/t25-engram.exe',bundle/'t25-engram.exe');origins=[]
 for n in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
  p=sdk/'bin'/n;shutil.copy2(p,bundle/n);origins.append(dict(origin=record(p),target=record(bundle/n)))
 shutil.copytree(BUNDLE/'licenses',bundle/'licenses',dirs_exist_ok=True);save(t/'CPU-runtime.json',numpy_runtime())
 files=list(snapshot.rglob('*'))+list(bundle.rglob('*'))+list((t/'input').rglob('*'))+list((t/'q').rglob('*'))+OWN+list(tools.values())+[Path(sys.executable),t/'CPU-runtime.json',t/'N-source-spans.json',BUILD/'actual/source-map.json',BUILD/'actual/source-qualification.json']
 save(t/'manifest.json',dict(schema='T25-smallstate-fixed/v1',source_id=identity,binding=[record(p) for p in sorted(set(files)) if p.is_file()],Q=record(t/'q/manifest.json'),DLL_origins=origins,pending_capacity=8192,cache_capacity=4096,snapshot_bytes=[4096,2048],normal_snapshot_API_added=False))
 print(json.dumps(dict(manifest=record(t/'manifest.json'),exe=record(bundle/'t25-engram.exe'),G0=True)))

def restore_validate(native,folder):
 m=restore_q_binding();folder=Path(folder);checked=0;bytes_total=0
 if native['source_id']!=read(BUILD/'state-restore/manifest.json')['source_id'] or type(native['native_rejections']) is not int or native['native_rejections']!=68 or type(native['snapshot_total_bytes']) is not int or native['snapshot_total_bytes']!=6144:raise ValueError('restore native metadata')
 if len(native['cases'])!=2:raise ValueError('restore case coverage')
 inventory=read(EXT/'tests/artifact/header-inventory.json');tensors={x['name']:x for s in inventory['shards'] for x in s['tensors']};read_expected=23*sum(tensors['blk.2.attn_compressor_'+r+'.weight']['bytes'] for r in ['kv','gate'])
 if type(native['weight_read']) is not int or native['weight_read']!=read_expected:raise ValueError('restore actual weight bytes')
 # Every allocation below is simultaneously live, no aliases summed twice.
 expected_owned=20480+2048+2097152+7*2048+8+128+8192+4096
 if type(native['explicit_device_owned']) is not int or native['explicit_device_owned']!=expected_owned:raise ValueError('restore allocation')
 for i,c in enumerate([1,2]):
  n=native['cases'][i]
  if any(type(n.get(k)) is not bool for k in ['live_mutated','metadata_only_differs','branch_differs','restored_equal']) or type(n.get('checkpoint')) is not int or type(n.get('saved_bytes')) is not int:raise ValueError('restore case strict types')
  if n!=dict(checkpoint=c,saved_bytes=4096 if c==1 else 2048,live_mutated=True,metadata_only_differs=True,branch_differs=True,restored_equal=True):raise ValueError('restore case metadata')
  for branch,tag in [('A','direct'),('B','branch'),('A','restored')]:
   for key,e in m['outputs'][f'cp{c}-{branch}'].items():
    expected=np.fromfile(e['path'],dtype=e['dtype']).reshape(e['shape']);expected=expected if key=='cache' else expected[c//2:]
    p=folder/f'cp{c}'/tag/(key+'.bin');actual=p.read_bytes()
    if actual!=expected.tobytes():raise ValueError('restore bytes '+str(p))
    checked+=expected.size;bytes_total+=len(actual)
  for key,e in m['outputs'][f'snapshot{c}'].items():
   filename={'pending_kv':'kv','pending_score':'score','cache':'cache'}[key]
   if (folder/f'cp{c}'/f'snapshot-{filename}.bin').read_bytes()!=Path(e['path']).read_bytes():raise ValueError('deep snapshot bytes')
  inactive=['cache'] if c==1 else ['kv','score']
  if any((folder/f'cp{c}'/f'snapshot-{key}.bin').read_bytes()!=b'' for key in inactive):raise ValueError('inactive snapshot payload')
  if (folder/f'cp{c}'/'metadata-only/cache.bin').read_bytes()==(folder/f'cp{c}'/'direct/cache.bin').read_bytes():raise ValueError('metadata-only false success')
 return dict(values=checked,bytes=bytes_total,device_owned=expected_owned,restored=True)

def restore_negatives(folder=None):
 t=BUILD/'state-restore';folder=Path(folder or t/'G-primary');n=read(folder/'stdout.json');passed=[]
 for field in ['source_id','native_rejections','snapshot_total_bytes','weight_read','explicit_device_owned']:
  for val in [0,-1,True,1.0,None]+([float(n[field])] if type(n[field]) is int else []):
   altered=copy.deepcopy(n);altered[field]=val
   try:restore_validate(altered,folder)
   except (ValueError,TypeError):passed.append(field+repr(val));continue
   raise ValueError('restore metadata mutant accepted '+field)
 for c in [0,1]:
  for field in ['saved_bytes','checkpoint','live_mutated','metadata_only_differs','branch_differs','restored_equal']:
   altered=copy.deepcopy(n);altered['cases'][c][field]=0
   try:restore_validate(altered,folder)
   except ValueError:passed.append(str(c)+field);continue
   raise ValueError('restore case mutant accepted')
 import tempfile
 with tempfile.TemporaryDirectory(prefix='negative-',dir=t) as d:
  d=Path(d);shutil.copytree(folder,d,dirs_exist_ok=True);p=d/'cp2/restored/cache.bin';old=p.read_bytes()
  for tag,value in [('append',old+b'\0'),('truncate',old[:-1]),('bitflip',bytes([old[0]^1])+old[1:]),('omitted_restore',(folder/'cp2/metadata-only/cache.bin').read_bytes())]:
   p.write_bytes(value)
   try:restore_validate(n,d)
   except ValueError:passed.append(tag);continue
   raise ValueError('restore output mutant accepted')
 save(t/'negatives.json',dict(rejected=len(passed),cases=passed,positive=restore_validate(n,folder)));return len(passed)

def restore_run(pci):
 t=BUILD/'state-restore';m=read(t/'manifest.json');verify(m['binding']);restore_q_binding();env=actual_environment();(t/'tmp').mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(t/'tmp');env['PATH']=os.pathsep.join([str(t/'bundle'),env.get('SystemRoot','C:/Windows')+'/System32',env.get('SystemRoot','C:/Windows')]);out=t/'G-primary'
 if out.exists():raise ValueError('preserve restore G')
 r=run([t/'bundle/t25-engram.exe','--restore',t/'input',out,pci],env,timeout=900,check=False);out.mkdir(exist_ok=True);(out/'stderr.log').write_text(r.stderr,encoding='utf-8');(out/'stdout.json').write_text(r.stdout,encoding='utf-8')
 if r.returncode:raise ValueError('restore native failed '+str(r.returncode))
 n=json.loads(r.stdout);result=restore_validate(n,out);negative_count=restore_negatives(out);loaded=[]
 for d in m['DLL_origins'][:3]:
  matches=[Path(x) for x in n['loaded_modules'] if Path(x).name.lower()==Path(d['target']['path']).name.lower()]
  if len(matches)!=1 or record(matches[0])!=d['target']:raise ValueError('restore loaded DLL')
  loaded.append(record(matches[0]))
 verify(m['binding']);save(t/'verification.json',dict(manifest=record(t/'manifest.json'),exe=record(t/'bundle/t25-engram.exe'),Q=m['Q'],native=record(out/'stdout.json'),comparison=result,negative_count=negative_count,negatives=record(t/'negatives.json'),loaded=loaded,before_after=True,whole_T25=False,scope='small source2 ratio2 deep state snapshot/restore only',physical_peak=None))
 print(json.dumps(dict(verification=record(t/'verification.json'),**result)))

def restore_selftest():
 """Pure comparator controls; synthetic captures never grant GPU qualification."""
 t=BUILD/'state-restore';m=restore_q_binding();out=t/'CPU-synthetic';out.mkdir(exist_ok=True);inventory=read(EXT/'tests/artifact/header-inventory.json');tensors={x['name']:x for s in inventory['shards'] for x in s['tensors']}
 native=dict(source_id=read(t/'manifest.json')['source_id'],native_rejections=68,snapshot_total_bytes=6144,weight_read=23*sum(tensors['blk.2.attn_compressor_'+r+'.weight']['bytes'] for r in ['kv','gate']),explicit_device_owned=20480+2048+2097152+7*2048+8+128+8192+4096,cases=[])
 for c in [1,2]:
  native['cases'].append(dict(checkpoint=c,saved_bytes=4096 if c==1 else 2048,live_mutated=True,metadata_only_differs=True,branch_differs=True,restored_equal=True))
  for branch,tag in [('A','direct'),('B','branch'),('A','restored'),('A','metadata-only')]:
   d=out/f'cp{c}'/tag;d.mkdir(parents=True,exist_ok=True)
   for key,e in m['outputs'][f'cp{c}-{branch}'].items():
    x=np.fromfile(e['path'],dtype=e['dtype']).reshape(e['shape']);x=x if key=='cache' else x[c//2:];body=x.tobytes()
    if tag=='metadata-only' and key=='cache':body=bytes([body[0]^1])+body[1:]
    (d/(key+'.bin')).write_bytes(body)
  for key in ['kv','score','cache']:(out/f'cp{c}'/f'snapshot-{key}.bin').write_bytes(b'')
  for key,e in m['outputs'][f'snapshot{c}'].items():(out/f'cp{c}'/('snapshot-'+{'pending_kv':'kv','pending_score':'score','cache':'cache'}[key]+'.bin')).write_bytes(Path(e['path']).read_bytes())
 save(out/'stdout.json',native);n=restore_negatives(out);save(t/'CPU-before-G.json',dict(negative_count=n,comparison=restore_validate(native,out),synthetic_only=True,GPU_executed=False));print(json.dumps(dict(CPU_only=True,rejections=n)))

def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','build','reseal','host','run','replay','negatives','actual-prepare','actual-build','actual-seal','actual-run','actual-preflight','actual-revalidate','restore-prepare','restore-build','restore-run','restore-selftest']);p.add_argument('--role');p.add_argument('--pci');a=p.parse_args()
 if a.mode=='prepare':prepare()
 elif a.mode=='build':build()
 elif a.mode=='reseal':reseal()
 elif a.mode=='actual-prepare':actual_prepare()
 elif a.mode=='actual-build':actual_build()
 elif a.mode=='actual-seal':actual_seal()
 elif a.mode=='actual-run':actual_run(a.pci)
 elif a.mode=='actual-preflight':actual_preflight()
 elif a.mode=='actual-revalidate':actual_revalidate()
 elif a.mode=='restore-prepare':restore_prepare()
 elif a.mode=='restore-build':restore_build()
 elif a.mode=='restore-run':restore_run(a.pci)
 elif a.mode=='restore-selftest':restore_selftest()
 elif a.mode=='host':host()
 elif a.mode=='run':execute(a.role,a.pci)
 elif a.mode=='replay':replay(a.role)
 else:negatives(a.role)
if __name__=='__main__':main()
