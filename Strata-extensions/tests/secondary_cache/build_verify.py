"""T22 local build, independent expectations and immutable consumed-source seal."""
from pathlib import Path
import hashlib,importlib.util,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[3]
BUILD=ROOT/'build-deepseek-t22'
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def row(path):
 p=Path(path).resolve();data=p.read_bytes();return dict(path=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())

def checked_records(records):
 for item in records:
  if row(item['path'])!={key:item[key]for key in('path','bytes','sha256')}:raise ValueError('changed fixed dependency '+item['path'])
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def tools_module():return module('t22_existing_tools',ROOT/'Strata-extensions/tests/serve_provider/build_verify.py')
def native_cpu(build_path,normal_build=None):
 import re
 source=(ROOT/'Strata-extensions/native/cache/primary_supply.hip').read_text(encoding='utf-8')
 if 'structRamSlot{std::vector<uint8_t>bytes;std::stringkey;boolvalid=false,busy=false;};'not in re.sub(r'\s+','',source):raise ValueError('Primary RAM metadata source layout changed')
 build_path=Path(build_path);bundle=build_path/'cmake/bundle';m=tools_module();_,_,sdk=m.hip_tools()
 for dll in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):shutil.copy2(sdk/'bin'/dll,bundle/dll)
 results=[]
 for flag,key,count in(('--host','host_assertions',68),('--policy','policy_checks',26)):
  result=subprocess.run([str(bundle/'t22-cache.exe'),flag],env=m.runtime_env(bundle),capture_output=True,text=True,encoding='utf-8');record=dict(command=result.args,exit=result.returncode,stdout=result.stdout,stderr=result.stderr);results.append(record);result.check_returncode();value=json.loads(result.stdout)
  if value[key]!=count or result.stderr:raise ValueError('native CPU assertions')
  if flag=='--policy'and value['ram_slot_metadata_bytes']!=64:raise ValueError('fixed Win64 ABI RAM slot metadata')
 save(BUILD/'native-CPU.json',dict(binary=row(bundle/'t22-cache.exe'),results=results,GPU_executed=False,model_kernel_executed=False,actual_driver_fault=False))
 if normal_build is not None:
  normal=Path(normal_build)/'cmake/bundle'
  for dll in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):shutil.copy2(sdk/'bin'/dll,normal/dll)
  result=subprocess.run([str(normal/'t28-construction.exe'),'--construction-policy-test'],env=m.runtime_env(normal),capture_output=True,text=True,encoding='utf-8');save(BUILD/'normal-policy-last-execution.json',dict(binary=row(normal/'t28-construction.exe'),command=result.args,exit=result.returncode,stdout=result.stdout,stderr=result.stderr,GPU_executed=False));result.check_returncode();value=json.loads(result.stdout)
  if value['assertions']!=83 or result.stderr:raise ValueError('same production OOM/unknown classification checks')
  save(BUILD/'normal-policy-CPU.json',dict(binary=row(normal/'t28-construction.exe'),command=result.args,exit=result.returncode,stdout=result.stdout,stderr=result.stderr,GPU_executed=False,actual_allocation_failure=False))
def build(destination,normal=False):
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);tools,env,sdk=tools_module().hip_tools();out=destination/'cmake';source=ROOT/'Strata-extensions/models/deepseek41'if normal else Path(__file__).parent
 commands=[[tools['cmake'],'--fresh','-S',source,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],[tools['cmake'],'--build',out,'--target',*(['Strata-deepseek','t28-construction']if normal else['t22-cache']),'--verbose']]
 for i,command in enumerate(commands):
  result=subprocess.run(list(map(str,command)),env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace');save(destination/f'build-{i}.json',dict(command=list(map(str,command)),exit=result.returncode,stdout=result.stdout,stderr=result.stderr));print('T22 build',normal,i,result.returncode,flush=True);result.check_returncode()
 return out
def expectations():
 import reference,validate
 test=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).with_name('test_policy.py'))],capture_output=True,text=True,encoding='utf-8');save(BUILD/'policy-green-latest.json',dict(command=test.args,exit=test.returncode,stdout=test.stdout,stderr=test.stderr,GPU_executed=False));test.check_returncode()
 q=reference.unit_expected(ROOT,BUILD/'unit-Q-fixed');save(BUILD/'CPU-validator-latest.json',dict(capacity1=validate.self_test(q,BUILD/'synthetic-cap1',1),capacity2=validate.self_test(q,BUILD/'synthetic-cap2',2),controlled_unknown=validate.unknown_self_test(q,BUILD/'synthetic-unknown')))
 save(BUILD/'Q-seal.json',dict(Q=row(BUILD/'unit-Q-fixed/manifest.json'),reference=row(Path(reference.__file__)),validator=row(Path(validate.__file__)),tests=row(Path(__file__).with_name('test_policy.py')),policy=row(BUILD/'policy-green-latest.json'),CPU=row(BUILD/'CPU-validator-latest.json'),native_CPU=row(BUILD/'native-CPU.json'),normal_policy_CPU=row(BUILD/'normal-policy-CPU.json'),contract=row(Path(__file__).with_name('contract.json')),recipe=row(__file__),DRAM_plan=row(BUILD/'dram-condition-v3.md'),normal_Q=row(ROOT/'build-deepseek-t28/normal/q/manifest.json'),candidate_output_used=False,GPU_executed=False))
def seal(name,fixture_build,normal_build):
 fixed=BUILD/name
 if fixed.exists():raise ValueError('preserve existing fixed bundle')
 fixed.mkdir();binding=[];mapping=[];seen=set();source_ids={};tools,env,sdk=tools_module().hip_tools()
 def snapshot(path,target=None):
  path=Path(path).resolve()
  if str(path)in seen:return
  seen.add(str(path));before=row(path);target=target or fixed/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
  if row(path)!=before or row(target)['sha256']!=before['sha256']:raise ValueError('changed during exact snapshot')
  binding.append(row(target));mapping.append(dict(original=before,snapshot=row(target)))
 for label,build_path,exe in [('fixture',Path(fixture_build),'t22-cache.exe'),('normal',Path(normal_build),'Strata-deepseek.exe')]:
  cmake=build_path/'cmake';snapshot(cmake/'bundle'/exe,fixed/label/exe)
  if label=='normal':snapshot(cmake/'bundle/t28-construction.exe',fixed/label/'t28-construction.exe')
  for dll in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):snapshot(sdk/'bin'/dll,fixed/label/dll)
  # Runtime copies are needed in both exe directories even when origin was seen.
  for dll in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):
   target=fixed/label/dll
   if not target.exists():shutil.copy2(sdk/'bin'/dll,target);binding.append(row(target))
  declared=cmake/'declared-sources.tsv';snapshot(declared);source_ids[label]=hashlib.sha256(declared.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
  for line in declared.read_text(encoding='utf-8').splitlines():
   relative,digest=line.split('|');path=ROOT/relative
   if row(path)['sha256']!=digest:raise ValueError('build source changed '+relative)
   snapshot(path)
  deps=subprocess.run([str(tools['ninja']),'-C',str(cmake),'-t','deps'],env=env,capture_output=True,text=True);save(fixed/f'{label}-deps.json',dict(exit=deps.returncode,stdout=deps.stdout,stderr=deps.stderr));deps.check_returncode();binding.append(row(fixed/f'{label}-deps.json'))
  for line in deps.stdout.splitlines():
   if not line.startswith('    '):continue
   path=Path(line.strip())
   if not path.is_file()or str(path.resolve())in seen:continue
   if path.resolve().is_relative_to(ROOT):snapshot(path)
   else:seen.add(str(path.resolve()));binding.append(row(path))
  for i in(0,1):snapshot(build_path/f'build-{i}.json')
 for path in Path(__file__).parent.iterdir():
  if path.is_file():snapshot(path)
 for relative in('models/deepseek41/CMakeLists.txt','models/deepseek41/server_hooks.py','control/providers/deepseek41.py'):snapshot(ROOT/'Strata-extensions'/relative)
 for relative in('tests/serve_provider/build_verify.py','tests/core/build_verify.py'):snapshot(ROOT/'Strata-extensions'/relative)
 for path in(BUILD/'Q-seal.json',BUILD/'unit-Q-fixed/manifest.json',BUILD/'policy-green-latest.json',BUILD/'CPU-validator-latest.json',BUILD/'native-CPU.json',BUILD/'normal-policy-CPU.json',BUILD/'normal-identity-CPU.json',BUILD/'pre-v1.md',BUILD/'dram-condition-v3.md',BUILD/'classification-diagnosis.json',BUILD/'wave-correction-v1.md'):snapshot(path)
 for record in json.loads((BUILD/'classification-diagnosis.json').read_text(encoding='utf-8'))['records']:
  checked_records([record]);snapshot(record['path'])
 q=json.loads((BUILD/'unit-Q-fixed/manifest.json').read_text(encoding='utf-8'))
 for item in [*q['outputs'],*q['unknown_outputs'],*q['inputs']]:
  if row(item['path'])!={k:item[k]for k in('path','bytes','sha256')}:raise ValueError('fixed independent input/Q')
  binding.append(row(item['path']))
 for path in tools.values():
  if Path(path).is_file():binding.append(row(path))
 source_recipe=ROOT/'Strata-extensions/tests/layer_split/build_verify.py';old=module('accepted_original_source_correspondence',source_recipe);sources=old.original_sources();save(fixed/'original-sources.json',sources);binding.extend([row(source_recipe),row(fixed/'original-sources.json'),sources['accepted_receipt'],sources['accepted_T10']])
 binding.append(row(ROOT/'build-deepseek-t28/normal/q/manifest.json'))
 save(fixed/'source-map.json',mapping);binding.append(row(fixed/'source-map.json'));save(fixed/'manifest.json',dict(schema='T22-fixed/v1',bindings=binding,Q=row(BUILD/'unit-Q-fixed/manifest.json'),Q_seal=row(BUILD/'Q-seal.json'),normal_Q=row(ROOT/'build-deepseek-t28/normal/q/manifest.json'),source_map=row(fixed/'source-map.json'),compiled_source_ids=source_ids,compiled_material_newlines='LF; raw declared TSV checksum separately bound',build_both_arch=True,GPU_executed=False,normal_installed=False,whole_task_qualified=False));print(row(fixed/'manifest.json'))

def execute_unit(fixed_path,destination,slots,policy,unknown=False):
 """One finite actual case. Caller supplies the exclusive resource-window ACK."""
 import reference,validate
 fixed_path=Path(fixed_path).resolve();destination=Path(destination).resolve()
 if destination.exists():raise ValueError('preserve original attempts')
 if type(slots)is not int or slots not in(1,2)or policy not in('auto','bounce'):raise ValueError('sealed unit case')
 destination.mkdir(parents=True)
 manifest_path=fixed_path/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'));checked_records(manifest['bindings'])
 source_recipe=module('T22_actual_original_source_check',ROOT/'Strata-extensions/tests/layer_split/build_verify.py')
 source_before=source_recipe.original_sources()
 if source_before!=json.loads((fixed_path/'original-sources.json').read_text(encoding='utf-8')):raise ValueError('actual original SourceFile identity changed')
 mapping=json.loads(Path(manifest['source_map']['path']).read_text(encoding='utf-8'));originals=[item['original']for item in mapping];checked_records(originals)
 q=json.loads(Path(manifest['Q']['path']).read_text(encoding='utf-8'));checked_records([*q['inputs'],*q['outputs'],*q['unknown_outputs']]);inputs=Path(q['inputs'][0]['path']).parent
 preseal=dict(manifest=row(manifest_path),recipe=row(__file__),slots=slots,policy=policy,controlled_unknown=unknown,Q=manifest['Q'],originals=originals,DRAM_report_only=True,normal_defaults_changed=False,GPU_executed=False)
 save(destination/'preseal.json',preseal)
 cli=subprocess.run(['C:/Develop/AI/Strata/.venv/Scripts/python.exe','-X','utf8','C:/Develop/AI/Strata-data/strata_cli.py','status'],capture_output=True,text=True,encoding='utf-8');save(destination/'CLI-before.json',dict(exit=cli.returncode,stdout=cli.stdout,stderr=cli.stderr));cli.check_returncode()
 bundle=fixed_path/'fixture';env=tools_module().runtime_env(bundle);exe=bundle/'t22-cache.exe';primary='0000:07:00.0';secondary='0000:03:00.0'
 def launch(label,payload,flag):
  output=destination/label;command=[str(exe),str(inputs),str(output),primary,secondary,str(slots),policy,str(payload),*([flag]if flag else [])]
  result=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8');save(destination/(label+'-execution.json'),dict(command=command,exit=result.returncode,stdout=result.stdout,stderr=result.stderr))
  result.check_returncode()
  if result.stderr:raise ValueError('unexpected native stderr')
  loaded=(output/'loaded-modules.txt').read_text(encoding='utf-8').splitlines()
  for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'):
   matching=[Path(path)for path in loaded if Path(path).name.lower()==name]
   if len(matching)!=1 or matching[0].resolve()!= (bundle/name).resolve():raise ValueError('actual owned runtime DLL '+name)
  value=json.loads(result.stdout)
  if value.get('source_id')!=manifest['compiled_source_ids']['fixture']:raise ValueError('actual compiled source material ID')
  return output,value
 # Measurement already includes its owners and mandatory workspace. Only future
 # RAM-slot metadata (fixed Win64 sizeof 64) is subtracted, once.
 minimum=131072;measure,_=launch('minimum',minimum,'--measure');memory=validate.validate_dram(q,measure,minimum,True)
 fields=(measure/'measurement.tsv').read_text(encoding='utf-8').strip().split('\t')
 if len(fields)!=6 or list(map(int,fields[:2]))!=[2,minimum]:raise ValueError('actual minimum RAM capacity')
 available=memory['physical_available_bytes']['owners-constructed'];selection=reference.dram_selection(available,minimum,minimum)
 initial_slots=selection['payload']//65536;future_metadata=max(0,initial_slots-2)*64
 selection=reference.dram_selection(available,minimum,minimum,future_metadata);payload=selection['payload']//65536*65536
 if not minimum<=payload<2**64:raise ValueError('checked actual RAM payload')
 save(destination/'selection.json',dict(minimum_observation=memory,minimum_owner_fields=fields,selection=selection,future_RAM_metadata_bytes=future_metadata,payload_bytes=payload,slots=payload//65536,metadata_unit_bytes=64,band_is_acceptance_gate=False))
 # This selection is sealed before computation. No band-based refusal or runtime
 # budget following: actual variation remains an independent observation.
 output,stdout=launch('actual',payload,'--unknown'if unknown else '')
 comparison=validate.validate_unknown(q,output,slots,1,0,payload,policy)if unknown else validate.validate_unit(q,output,slots,1,0,policy,payload)
 if not unknown:
  owned=(output/'stats.tsv').read_text(encoding='utf-8').splitlines()[-1].split('\t')
  expected_metadata=int(fields[3])+(payload//65536-2)*64
  if int(owned[13])!=expected_metadata:raise ValueError('actual RAM vector metadata delta versus fixed sizeof')
 memory=validate.validate_dram(dict(outputs=q['unknown_outputs'])if unknown else q,output,payload)
 checked_records(manifest['bindings']);checked_records(originals)
 source_after=source_recipe.original_sources()
 if source_after!=source_before:raise ValueError('original SourceFile changed during actual case')
 save(destination/'verification.json',dict(preseal=row(destination/'preseal.json'),selection=row(destination/'selection.json'),stdout=stdout,comparison=comparison,DRAM=memory,original_sources=source_after,outputs=[row(p)for p in sorted(output.iterdir())if p.is_file()],before_after_bindings=True,GPU_executed=True,physical_peak=None,performance_qualified=False,normal_route_qualified=False,whole_task_qualified=False))
 print(row(destination/'verification.json'))
if __name__=='__main__':
 if sys.argv[1]=='expectations':expectations()
 elif sys.argv[1]=='native-cpu':native_cpu(Path(sys.argv[2]),Path(sys.argv[3])if len(sys.argv)>3 else None)
 elif sys.argv[1]=='unit':execute_unit(Path(sys.argv[2]),Path(sys.argv[3]),int(sys.argv[4]),sys.argv[5],len(sys.argv)>6 and sys.argv[6]=='unknown')
 elif sys.argv[1]=='build':build(Path(sys.argv[2]),'--normal'in sys.argv[3:])
 elif sys.argv[1]=='seal':seal(*sys.argv[2:5])
 else:raise ValueError('command')
