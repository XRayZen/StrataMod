"""Task-local T44 qualification orchestration; no normal startup gate."""
from pathlib import Path
import hashlib,json,subprocess,sys
import reference
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/'build-deepseek-t44'
def row(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def expectations():
 result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).with_name('test_policy.py'))],capture_output=True,text=True,encoding='utf-8')
 save(BUILD/'policy-green.json',dict(command=result.args,exit=result.returncode,stdout=result.stdout,stderr=result.stderr,GPU=False));result.check_returncode()
 expected=reference.fixed_reference(ROOT/'build-deepseek-t20/full-core-attempt-1/captured-Q-manifest.json');save(BUILD/'expected-Q.json',expected)
 save(BUILD/'Q-seal.json',dict(reference=row(Path(reference.__file__)),tests=row(Path(__file__).with_name('test_policy.py')),contract=row(Path(__file__).with_name('contract.json')),source_schema=row(Path(__file__).with_name('source-schema.json')),Q=row(BUILD/'expected-Q.json'),policy=row(BUILD/'policy-green.json'),recipe=row(__file__),GPU_executed=False,expectation_from_candidate=False,scope='independent numeric/route and original-source cache/capacity expectation; fixture controls separately bound'))
 print('T44 EXPECTATIONS SEALED',row(BUILD/'Q-seal.json')['sha256'])
def micro_expectations():
 import importlib.util,shutil
 fixed=ROOT/'build-deepseek-t20/full-independent-source'
 source=fixed/'Strata-extensions/tests/numerics/t25/reference.py'
 if row(source)['sha256']!='f3bc0e942ee9d523e20b4269d70cf3bc7a553b8089d738d1f19227d16d1b69bc':raise ValueError('independent accepted Oracle')
 spec=importlib.util.spec_from_file_location('t44_micro_independent',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 q=json.loads((BUILD/'expected-Q.json').read_text());input_record=next(x for x in q['expected_stages']if x['position']==0 and x['layer']==0 and x['name']=='block_ffn_input');base=module.np.frombuffer(reference.checked(input_record),'<f4').copy().reshape(1,5120)
 oracle=module.ActualOracle(fixed);np=module.np;expected=[]
 for n in (1,2,8):
  path=BUILD/'input'/('b'+str(n));path.mkdir(parents=True,exist_ok=True)
  for file in ('sources.tsv','prefixes.tsv'):shutil.copy2(ROOT/'build-deepseek-t20/full-input'/file,path/file)
  x=np.repeat(base,n,axis=0);route=np.array([.25+i/16 for i in range(n)],np.float32).reshape(n,1);x.tofile(path/'micro-input.bin');route.tofile(path/'micro-route.bin')
  outputs=[]
  for expert in (38,155):
   prefix='blk.0.';gate=module.bf16(oracle.linear(prefix+'ffn_gate_exps.weight',x,True,matrix=expert));up=module.bf16(oracle.linear(prefix+'ffn_up_exps.weight',x,True,matrix=expert));hidden=oracle.ffn.swiglu(gate,up,route)[0];down=module.bf16(oracle.linear(prefix+'ffn_down_exps.weight',hidden,True,matrix=expert));p=path/('expert-'+str(expert)+'-Q.bin');down.tofile(p);outputs.append(dict(expert=expert,shape=[n,5120],**row(p)))
  expected.append(dict(batch=n,input=row(path/'micro-input.bin'),route=row(path/'micro-route.bin'),outputs=outputs))
 save(BUILD/'micro-Q.json',dict(independent_source=row(source),fixed_source_map=row(fixed/'source-map.json'),input_original=input_record,cases=expected,original_reads=oracle.reads,FP64_diagnostics=oracle.diagnostics,GPU_used=False,source_math_changed=False))
 print('MICRO Q SEALED',row(BUILD/'micro-Q.json')['sha256'],flush=True)
def seal():
 import shutil,importlib.util,validate
 source=ROOT/'Strata-extensions/tests/serve_provider/build_verify.py';sp=importlib.util.spec_from_file_location('t44_seal_tools',source);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);m.BUILD=BUILD/'fixture-dev';tools,env,sdk=m.hip_tools()
 attempt=BUILD/'fixed-r8'
 if attempt.exists():raise ValueError('immutable fixed-r8 already exists')
 bundle=attempt/'bundle';bundle.mkdir(parents=True)
 bindings=[];mapping=[]
 def snapshot(p,target=None):
  p=Path(p).resolve();before=row(p)
  if target is None:target=attempt/'source'/p.relative_to(ROOT)
  target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  if row(p)!=before or row(target)['sha256']!=before['sha256']:raise ValueError('source changed during snapshot')
  bindings.append(row(target));mapping.append(dict(original=before,snapshot=row(target)))
 snapshot(BUILD/'fixture-dev/cmake-dev/bundle/t44-expert.exe',bundle/'t44-expert.exe')
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:snapshot(sdk/'bin'/name,bundle/name)
 declared=BUILD/'fixture-dev/cmake-dev/declared-sources.tsv'
 for line in declared.read_text(encoding='utf-8').splitlines():
  relative,digest=line.split('|');p=ROOT/relative
  if row(p)['sha256']!=digest:raise ValueError('compile source changed '+relative)
  snapshot(p)
 deps=subprocess.run([str(tools['ninja']),'-C',str(BUILD/'fixture-dev/cmake-dev'),'-t','deps'],env=env,capture_output=True,text=True);save(attempt/'ninja-deps.json',dict(exit=deps.returncode,stdout=deps.stdout,stderr=deps.stderr));deps.check_returncode()
 seen={x['original']['path']for x in mapping}
 for line in deps.stdout.splitlines():
  if not line.startswith('    '):continue
  p=Path(line.strip())
  if not p.is_file()or str(p.resolve())in seen:continue
  p=p.resolve();seen.add(str(p))
  if p.is_relative_to(ROOT):snapshot(p)
  else:bindings.append(row(p))
 for p in Path(__file__).parent.iterdir():
  if p.is_file()and str(p.resolve())not in {x['original']['path']for x in mapping}:snapshot(p)
 for p in (ROOT/'Strata-extensions/models/deepseek41/CMakeLists.txt',declared,BUILD/'Q-seal.json',BUILD/'expected-Q.json',BUILD/'micro-Q.json',BUILD/'policy-green.json',BUILD/'fixture-dev/build-0.json',BUILD/'fixture-dev/build-1.json'):
  if str(p.resolve())not in {x['original']['path']for x in mapping}:snapshot(p)
 for case in json.loads((BUILD/'micro-Q.json').read_text())['cases']:
  for record in [case['input'],case['route'],*case['outputs']]:bindings.append(record)
 for p in tools.values():
  if Path(p).is_file():bindings.append(row(p))
 save(attempt/'source-map.json',mapping);bindings.append(row(attempt/'source-map.json'))
 control=dict(micro=dict(native_rejections=15,positive_cases=8,outputs=7,transfer_records=23,directions=dict(input=8,route=8,down=7),main_jobs=[1,5,5,3],fresh_jobs=[0,1,1,0]),full=dict(primary_jobs=365,secondary_jobs=355,adopted=720,transfer_records=1065,slots=2,max_batch=8),actual_requested=dict(primary_jobs=655424,secondary_workspace=1900608,secondary_weights=4194816,bounce_host=327680),normal_capacity_limit=False,GPU_used=False)
 save(attempt/'control-expected.json',control);bindings.append(row(attempt/'control-expected.json'))
 save(attempt/'CPU-validator.json',validate.self_test());bindings.append(row(attempt/'CPU-validator.json'))
 for x in bindings:
  if row(x['path'])!={k:x[k]for k in ('path','bytes','sha256')}:raise ValueError('fixed closure changed '+x['path'])
 runtime=m.runtime_env(bundle)
 for k in list(runtime):
  if k.upper().startswith(('HIP','ROCM'))or k.upper()in('INCLUDE','LIB'):runtime.pop(k,None)
 host=subprocess.run([str(bundle/'t44-expert.exe'),'--host'],env=runtime,capture_output=True,text=True,encoding='utf-8');save(attempt/'host.json',dict(command=host.args,exit=host.returncode,stdout=host.stdout,stderr=host.stderr,GPU=False));host.check_returncode();bindings.append(row(attempt/'host.json'))
 save(attempt/'manifest.json',dict(schema='strata-t44-fixed/v1',source_id=hashlib.sha256(declared.read_bytes()).hexdigest(),bindings=bindings,source_map=row(attempt/'source-map.json'),expectations=row(BUILD/'Q-seal.json'),micro=row(BUILD/'micro-Q.json'),control=row(attempt/'control-expected.json'),CPU=row(attempt/'CPU-validator.json'),build_both_arch=True,GPU_executed=False,normal_installed_bundle_modified=False))
 print('T44 FIXED',row(attempt/'manifest.json')['sha256'],flush=True)

def build():
 import importlib.util
 source=ROOT/'Strata-extensions/tests/serve_provider/build_verify.py';sp=importlib.util.spec_from_file_location('t44_toolchain',source);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);m.BUILD=BUILD/'fixture-dev';m.BUILD.mkdir(exist_ok=True)
 tools,env,sdk=m.hip_tools();out=m.BUILD/'cmake-dev'
 command=[tools['cmake'],'--fresh','-S',Path(__file__).parent,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 for index,cmd in enumerate((command,[tools['cmake'],'--build',out,'--verbose'])):
  run=subprocess.run(list(map(str,cmd)),env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace');save(m.BUILD/('build-'+str(index)+'.json'),dict(command=list(map(str,cmd)),exit=run.returncode,stdout=run.stdout,stderr=run.stderr));print('T44 BUILD',index,run.returncode,flush=True);run.check_returncode()
if __name__=='__main__':
 if sys.argv[1:]==['--expectations']:expectations()
 elif sys.argv[1:]==['--micro-q']:micro_expectations()
 elif sys.argv[1:]==['--build']:build()
 elif sys.argv[1:]==['--seal']:seal()
 else:raise SystemExit('use --expectations / --micro-q / --build')
