"""Closed accepted T22 parent plus only Primary/provider-reuse fixture delta."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
ROOT=Path('C:/Develop/AI/Strata-data/build/deepseek-v41');HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t35';PARENT=BUILD/'provider-persistent-parent/source'
def row(path):
 p=Path(path).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(path,value):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def checked(records):
 for record in records:
  actual=row(record['path'])
  if any(actual[k]!=record[k]for k in('bytes','sha256')if k in record):raise ValueError('closed binding changed '+record['path'])
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def tools():return module('T35_existing_build_tools',ROOT/'Strata-extensions/tests/serve_provider/build_verify.py')
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def archive():
 path=BUILD/'approx-8g-r1/measurement-seal.json';seal=read(path);checked([r['snapshot']for r in seal['source_snapshots']]);backend=path.parent/'measurement-source/Strata-extensions/tests/backend';prior=sys.modules.get('eager_bench')
 try:
  sys.modules['eager_bench']=module('T35_persistent_archived_math',backend/'eager_bench.py');old=module('T35_persistent_archived_owner',backend/'build_verify.py')
 finally:
  if prior is None:sys.modules.pop('eager_bench',None)
  else:sys.modules['eager_bench']=prior
 return old,path,seal
def close_owner(owner,observe):
 result=dict(sample=None,observation_error=None,close_error=None)
 try:result['sample']=observe()
 except BaseException as error:result['observation_error']=str(error)
 finally:
  try:owner.close()
  except BaseException as error:result['close_error']=str(error)
 result.update(pid=owner.proc.pid,exit=owner.proc.poll());return result
def runtime_modules(path,bundle):
 actual=[Path(p).resolve()for p in Path(path).read_text(encoding='utf-8').splitlines()];result=[]
 for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'):
  matches=[p for p in actual if p.name.lower()==name]
  if len(matches)!=1 or str(matches[0]).lower()!=str((Path(bundle)/name).resolve()).lower():raise ValueError('actual owned runtime path '+name)
  got=row(matches[0]);expected=row(Path(bundle)/name)
  if got!=expected:raise ValueError('actual runtime body '+name)
  result.append(got)
 return result
def wrapper_cpu():
 class Process:
  pid=1
  def poll(self):return 0
 class Owner:
  def __init__(self,fail=False):self.proc=Process();self.closed=0;self.fail=fail
  def close(self):
   self.closed+=1
   if self.fail:raise RuntimeError('controlled close')
 def bad():raise RuntimeError('controlled observation')
 owner=Owner();result=close_owner(owner,bad)
 if owner.closed!=1 or not result['observation_error']or result['close_error']:raise AssertionError('observation must not bypass close')
 owner=Owner(True);result=close_owner(owner,bad)
 if owner.closed!=1 or not result['observation_error']or not result['close_error']:raise AssertionError('independent cleanup error')
 owner=Owner();result=close_owner(owner,lambda:dict(available_physical_bytes=None))
 if owner.closed!=1 or result['observation_error']or result['close_error']:raise AssertionError('unknown memory is diagnostic')
 return dict(observe_failure_close=True,close_failure_separate=True,unknown_memory_report_only=True,GPU_executed=False)
def prepare(destination,fixture,normal,qpath):
 destination=Path(destination).resolve();destination.mkdir(exist_ok=False);fixture=Path(fixture).resolve();normal=Path(normal).resolve();qpath=Path(qpath).resolve();f=read(fixture);n=read(normal);q=read(qpath)
 if f['normal']or not n['normal']or not f['both_arch']or not n['both_arch']:raise ValueError('closed build roles')
 for value in(f,n):
  checked(value['consumed']+[value['declared']]+[r['snapshot']for r in value['overlay']])
  for cpu in value['CPU']:
   expected=83 if cpu['flag']=='--construction-policy-test'else 68 if cpu['flag']=='--host'else None
   if cpu['exit']!=0 or cpu['stderr']:raise ValueError('CPU build failure')
   payload=json.loads(cpu['stdout'])
   if expected is not None and payload['assertions'if expected==83 else'host_assertions']!=expected:raise ValueError('actual CPU count')
   if cpu['flag']=='--identity'and payload['source_set_sha256']!=value['compiled_source_id']:raise ValueError('normal compiled identity')
   if cpu['flag']=='--host'and payload['source_id']!=value['compiled_source_id']:raise ValueError('fixture compiled identity')
 primary=ROOT/'Strata-extensions/native/cache/primary_supply.hip'
 for value in(f,n):
  found=[r['snapshot']for r in value['overlay']if Path(r['original']['path']).name=='primary_supply.hip']
  if len(found)!=1 or found[0]['sha256']!=row(primary)['sha256']:raise ValueError('same current Primary production delta')
 old,owner_path,owner=archive();old.runtime_snapshot(owner['input']);reference=module('T35_persistent_reference',HERE/'reference.py');synthetic=reference.synthetic(q,destination/'synthetic');save(destination/'CPU.json',dict(schedules=reference.cpu(),strict=synthetic,wrapper=wrapper_cpu()))
 current=[p for p in HERE.iterdir()if p.is_file()]+[primary];mapping=[]
 for path in current:
  original=row(path);target=destination/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
  if row(path)!=original or row(target)['sha256']!=original['sha256']:raise ValueError('current source snapshot changed')
  mapping.append(dict(original=original,snapshot=row(target)))
 save(destination/'source-map.json',mapping)
 records=[r[k]for r in mapping for k in('original','snapshot')]+[row(fixture),row(normal),row(qpath),row(owner_path),row(destination/'CPU.json'),row(destination/'source-map.json')]
 records += [row(ROOT/'Strata-extensions/tests'/p/'build_verify.py')for p in('serve_provider','core','cache','native')]
 records += f['consumed']+n['consumed']+[f['declared'],n['declared']]+[r['snapshot']for r in f['overlay']+n['overlay']]+q['inputs']+q['outputs']+[q['accepted_manifest'],q['accepted_guard']]+[r['snapshot']for r in owner['source_snapshots']]
 exe=fixture.parent/'cmake/bundle/t35-provider.exe';checked(records)
 save(destination/'seal.json',dict(schema='T35-persistent-provider-execution/v1',records=records,fixture=row(fixture),normal=row(normal),Q=row(qpath),exe=row(exe),owner_seal=row(owner_path),compiled_source_id=f['compiled_source_id'],logical_batch=3,waves=[2,1],DRAM_report_only=True,normal_actual=False,production_performance_qualified=False))
 print(row(destination/'seal.json'))
def execute(destination):
 destination=Path(destination).resolve();seal_path=destination/'seal.json';seal=read(seal_path);checked(seal['records']+[seal['exe']]);q=read(seal['Q']['path']);reference=module('T35_persistent_actual_reference',HERE/'reference.py')
 if (destination/'execution.json').exists()or(destination/'owner-selection.json').exists():raise ValueError('preserve original attempts')
 old,_,owner_seal=archive();config=copy.deepcopy(owner_seal['input']);temporary=destination/'tmp';temporary.mkdir();config['environment']=dict(config['environment']);config['environment'].update(TMP=str(temporary),TEMP=str(temporary));env=dict(os.environ);env.update(config['environment'])
 session=None;driver=None;memory=[];failure=None;cleanup=None;output=destination/'output';runtime_before=old.runtime_snapshot(config)
 def observe(point,pid,birth=None):
  try:sample=old.physical_memory(pid,birth)
  except BaseException as error:sample=dict(error=str(error))
  memory.append(dict(point=point,sample=sample));save(destination/'memory.json',memory);return sample
 try:
  session,selection,first=old.select_owner(config,env,destination);birth=first['birth'];memory.append(dict(point='constructed-owner',sample=first));info_before=session.info();owner_runtime=old.runtime_snapshot(config,info_before)
  for field in('core_position','primary_logical_read','primary_h2d'):
   if info_before[field]!=0:raise ValueError('noGEN owner unexpectedly computed')
  checked(seal['records']+[seal['exe']]);observe('owner-before-fixture',session.proc.pid,birth);command=[seal['exe']['path'],str(Path(seal['Q']['path']).parent),str(output)];runtime_env=dict(env);runtime_env['PATH']=os.pathsep.join([str(Path(seal['exe']['path']).parent),'C:/Windows/System32','C:/Windows']);runtime_env['SystemRoot']='C:/Windows';start=time.perf_counter_ns();driver=subprocess.Popen(command,env=runtime_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  observe('fixture-start',driver.pid);stdout,stderr=driver.communicate();(destination/'stdout.json').write_bytes(stdout);(destination/'stderr.log').write_bytes(stderr);save(destination/'execution.json',dict(command=command,exit=driver.returncode,elapsed_seconds=(time.perf_counter_ns()-start)/1e9));observe('owner-after-fixture',session.proc.pid,birth)
  if driver.returncode!=0 or stderr:raise ValueError('actual finite fixture failed; original saved')
  native=json.loads(stdout)
  if native['source_id']!=seal['compiled_source_id']or native['checks']!=22:raise ValueError('native source/count')
  comparison=reference.validate(q,output);dll=runtime_modules(output/'loaded-modules.txt',Path(seal['exe']['path']).parent);info_after=session.info()
  for field in('core_position','primary_logical_read','primary_h2d'):
   if info_after[field]!=0:raise ValueError('noGEN owner unexpectedly computed')
  save(destination/'owner-info.json',dict(before=info_before,after=info_after,runtime_before=owner_runtime,runtime_after=old.runtime_snapshot(config,info_after),GEN_count=0,valid_model_payload_bytes=None));checked(seal['records']+[seal['exe']])
 except BaseException as error:failure=error;save(destination/'failure.json',dict(type=type(error).__name__,error=str(error)))
 finally:
  if driver is not None and driver.poll()is None:
   # This owned finite fixture has no interactive input; drain its bounded run.
   stdout,stderr=driver.communicate();(destination/'cleanup-stdout.log').write_bytes(stdout);(destination/'cleanup-stderr.log').write_bytes(stderr)
  if session is not None:cleanup=close_owner(session,lambda:old.physical_memory(session.proc.pid,birth))
  save(destination/'cleanup.json',cleanup);save(destination/'memory.json',memory)
 if failure is not None:raise failure
 if cleanup is None or cleanup['close_error']or cleanup['exit']!=0:raise ValueError('owner close failed; original records retained')
 checked(seal['records']+[seal['exe']]);runtime_after=old.runtime_snapshot(config)
 if runtime_before!=runtime_after:raise ValueError('original runtime/model identity changed')
 save(destination/'verification.json',dict(schema='T35-persistent-provider-actual/v1',seal=row(seal_path),comparison=comparison,native=native,loaded_runtime_modules=dll,execution=row(destination/'execution.json'),stdout=row(destination/'stdout.json'),stderr=row(destination/'stderr.log'),outputs=[row(p)for p in output.iterdir()if p.is_file()],owner_info=row(destination/'owner-info.json'),memory=row(destination/'memory.json'),cleanup=row(destination/'cleanup.json'),before_after_binding=True,normal_actual=False,DRAM_report_only=True,physical_io=None,model_performance_qualified=False))
 print(row(destination/'verification.json'))
def expectations(destination):
 reference=module('T35_provider_independent_reference',HERE/'reference.py');cpu=reference.cpu();q=reference.prepare(destination);save(Path(destination)/'CPU.json',cpu);print(row(Path(destination)/'manifest.json'));return q
def build(destination,normal=False):
 destination=Path(destination).resolve();destination.mkdir(exist_ok=False);source=destination/'source';shutil.copytree(PARENT,source)
 parent_quant=json.loads((PARENT.parent/'quant-parent.json').read_text(encoding='utf-8'))
 for r in parent_quant['records']:
  checked([dict(path=r['target'],bytes=r['bytes'],sha256=r['sha256'])])
 baseline=[row(p)for p in PARENT.rglob('*')if p.is_file()];mapping=[]
 overlay=[ROOT/'Strata-extensions/native/cache/primary_supply.hip']+[HERE/n for n in('fixture.hip','reference.py','build_verify.py','CMakeLists.txt')]
 for original in overlay:
  before=row(original);target=source/original.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
  if row(original)!=before or row(target)['sha256']!=before['sha256']:raise ValueError('overlay changed')
  mapping.append(dict(original=before,snapshot=row(target)))
 helper=tools();toolchain,env,sdk=helper.hip_tools();cmake=destination/'cmake';folder=source/'Strata-extensions/models/deepseek41'if normal else source/'Strata-extensions/tests/provider_reuse'
 commands=[[toolchain['cmake'],'--fresh','-S',folder,'-B',cmake,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={toolchain["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={toolchain["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={toolchain["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={toolchain["rc"].as_posix()}',f'-DCMAKE_MT={toolchain["mt"].as_posix()}',f'-DCMAKE_LINKER={toolchain["linker"].as_posix()}'],[toolchain['cmake'],'--build',cmake,'--target',*(['Strata-deepseek','t28-construction']if normal else['t35-provider']),'--verbose']]
 save(destination/'before.json',dict(parent=baseline,overlay=mapping,old_quant=parent_quant,normal=normal,live_quant_consumed=False,T46_live_consumed=False,GPU_executed=False))
 for i,command in enumerate(commands):
  result=subprocess.run(list(map(str,command)),cwd=source,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace');save(destination/f'build-{i}.json',dict(command=list(map(str,command)),exit=result.returncode,stdout=result.stdout,stderr=result.stderr));print('persistent build',normal,i,result.returncode,flush=True);result.check_returncode()
 bundle=cmake/'bundle'
 for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):shutil.copyfile(sdk/'bin'/name,bundle/name)
 deps=subprocess.run([str(toolchain['ninja']),'-C',str(cmake),'-t','deps'],env=env,capture_output=True,text=True,encoding='utf-8');deps.check_returncode();(destination/'deps.txt').write_text(deps.stdout,encoding='utf-8')
 consumed=[];seen=set()
 for line in deps.stdout.splitlines():
  if not line.startswith('    '):continue
  path=Path(line.strip()).resolve()
  if not path.is_file()or str(path).lower()in seen:continue
  if path== (ROOT/'Strata-extensions/native/quant/quant.hip').resolve():raise ValueError('live quant mixed into independent candidate')
  seen.add(str(path).lower());consumed.append(row(path))
 for name in('Strata-deepseek.exe','t28-construction.exe')if normal else('t35-provider.exe',):consumed.append(row(bundle/name))
 consumed += [row(bundle/name)for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')]
 declared=cmake/'declared-sources.tsv';source_id=hashlib.sha256(declared.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
 checked(baseline);checked([r['original']for r in mapping]);checked(consumed)
 flags=[('--identity','Strata-deepseek.exe'),('--construction-policy-test','t28-construction.exe')]if normal else[('--host','t35-provider.exe')]
 cpu=[]
 for flag,exe in flags:
  result=subprocess.run([str(bundle/exe),flag],env=helper.runtime_env(bundle),capture_output=True,text=True,encoding='utf-8');cpu.append(dict(exe=row(bundle/exe),flag=flag,exit=result.returncode,stdout=result.stdout,stderr=result.stderr));result.check_returncode()
  if result.stderr:raise ValueError('unexpected CPU stderr')
 save(destination/'build.json',dict(parent=baseline,overlay=mapping,consumed=consumed,declared=row(declared),compiled_source_id=source_id,source_id_material='UTF-8 LF; raw declared file separately bound',both_arch=True,CPU=cpu,GPU_executed=False,normal=normal,live_quant_consumed=False,T46_live_consumed=False))
 print(row(destination/'build.json'))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--expectations',type=Path);parser.add_argument('--build',type=Path);parser.add_argument('--normal',action='store_true');parser.add_argument('--prepare',type=Path);parser.add_argument('--execute',type=Path);parser.add_argument('--fixture',type=Path);parser.add_argument('--normal-build',type=Path);parser.add_argument('--Q',type=Path);parser.add_argument('--CPU',action='store_true');args=parser.parse_args()
 if args.expectations:expectations(args.expectations)
 elif args.build:build(args.build,args.normal)
 elif args.prepare:prepare(args.prepare,args.fixture,args.normal_build,args.Q)
 elif args.execute:execute(args.execute)
 elif args.CPU:print(json.dumps(wrapper_cpu()))
 else:raise ValueError('explicit command required')
