"""T45 task-local development build; no runtime qualification from compile."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/'build-deepseek-t45'
def save(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def build():
 import importlib.util
 source=ROOT/'Strata-extensions/tests/serve_provider/build_verify.py';sp=importlib.util.spec_from_file_location('t44_toolchain',source);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);m.BUILD=BUILD/'core-dev';m.BUILD.mkdir(exist_ok=True)
 tools,env,sdk=m.hip_tools();out=m.BUILD/'cmake-dev'
 command=[tools['cmake'],'--fresh','-S',Path(__file__).parent,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 for index,cmd in enumerate((command,[tools['cmake'],'--build',out,'--verbose'])):
  run=subprocess.run(list(map(str,cmd)),env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace');save(m.BUILD/('build-'+str(index)+'.json'),dict(command=list(map(str,cmd)),exit=run.returncode,stdout=run.stdout,stderr=run.stderr));print('T45 BUILD',index,run.returncode,flush=True);run.check_returncode()



def row(path):
 import hashlib
 p=Path(path).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def tools_module():
 import importlib.util
 p=ROOT/'Strata-extensions/tests/serve_provider/build_verify.py';sp=importlib.util.spec_from_file_location('t45_owned_tools',p);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);m.BUILD=BUILD/'core-dev';return m

def expectations():
 import reference,validate
 run=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).with_name('test_policy.py'))],capture_output=True,text=True,encoding='utf-8');save(BUILD/'policy-green.json',dict(command=run.args,exit=run.returncode,stdout=run.stdout,stderr=run.stderr,GPU=False));run.check_returncode()
 q=reference.seal_reference(ROOT/'build-deepseek-t20/full-core-attempt-1/captured-Q-manifest.json',BUILD/'q',ROOT/'build-deepseek-t20/full-independent-source');q.update(reference.small_reference(BUILD/'small-Q'));save(BUILD/'q/manifest.json',q)
 save(BUILD/'CPU-validator.json',dict(full=validate.self_test(q,BUILD/'validator-synthetic-positive'),small=validate.small_self_test(q,BUILD/'small-validator-positive')))
 save(BUILD/'Q-seal.json',dict(Q=row(BUILD/'q/manifest.json'),reference=row(Path(reference.__file__)),validator=row(Path(validate.__file__)),tests=row(Path(__file__).with_name('test_policy.py')),policy=row(BUILD/'policy-green.json'),CPU=row(BUILD/'CPU-validator.json'),contract=row(Path(__file__).with_name('contract.json')),source_schema=row(Path(__file__).with_name('source-schema.json')),recipe=row(__file__),GPU_used=False,candidate_output_used=False,scope='immutable accepted Q plus independent controlled boundary/cache/allocation/metadata; not a G qualification'))
 print('T45 Q SEAL',row(BUILD/'Q-seal.json')['sha256'],flush=True)

def original_sources():
 receipt=ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json';proof=ROOT/'build-deepseek-t10/bundle-offline-r7/full-source-verification.json';qualified=json.loads(proof.read_text(encoding='utf-8'));full=json.loads(receipt.read_text(encoding='utf-8'))
 if not qualified['full_source_qualified']or not full['complete']or row(receipt)['sha256']!=qualified['receipt']['sha256']:raise ValueError('accepted original full-source proof')
 rows=[line.split('\t')for line in (ROOT/'build-deepseek-t10/sources.tsv').read_text(encoding='utf-8').splitlines()];identities={str(Path(x['path']).resolve()):x for x in qualified['sources']};expected={x['index']:x for x in full['files']}
 if len(rows)!=9 or set(expected)!=set(range(1,10)):raise ValueError('all nine original sources')
 result=[]
 for r in rows:
  index,size,lfs,revision,path=r;p=Path(path).resolve();st=p.stat();identity=dict(device=st.st_dev,file_id=st.st_ino,bytes=st.st_size,mtime_ns=st.st_mtime_ns);old=identities[str(p)];e=expected[int(index)]
  if identity!=old['file_identity']or int(size)!=st.st_size or e['bytes']!=st.st_size or e['sha256']!=lfs or e['sha256']!=old['sha256_acquisition']or revision!=full['revision']or str(Path(e['path']).resolve())!=str(p):raise ValueError('changed original SourceFile tuple/current identity')
  result.append(dict(source=r,current_identity=identity))
 return dict(accepted_receipt=row(receipt),accepted_T10=row(proof),sources=result,whole_model_rehashed_now=False)

def seal():
 import shutil,hashlib,validate
 m=tools_module();tools,env,sdk=m.hip_tools();fixed=BUILD/'fixed-r3'
 if fixed.exists():raise ValueError('immutable fixed-r3 exists')
 bundle=fixed/'bundle';bundle.mkdir(parents=True);binding=[];mapping=[];seen=set()
 def snapshot(p,target=None):
  p=Path(p).resolve();before=row(p)
  if str(p)in seen:return
  seen.add(str(p));target=target or fixed/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  if row(p)!=before or row(target)['sha256']!=before['sha256']:raise ValueError('source changed during snapshot')
  binding.append(row(target));mapping.append(dict(original=before,snapshot=row(target)))
 snapshot(BUILD/'core-dev/cmake-dev/bundle/t45-layer.exe',bundle/'t45-layer.exe')
 for name in ('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):snapshot(sdk/'bin'/name,bundle/name)
 declared=BUILD/'core-dev/cmake-dev/declared-sources.tsv'
 for line in declared.read_text(encoding='utf-8').splitlines():
  path,digest=line.split('|');p=ROOT/path
  if row(p)['sha256']!=digest:raise ValueError('declared build source changed '+path)
  snapshot(p)
 deps=subprocess.run([str(tools['ninja']),'-C',str(BUILD/'core-dev/cmake-dev'),'-t','deps'],env=env,capture_output=True,text=True);save(fixed/'ninja-deps.json',dict(exit=deps.returncode,stdout=deps.stdout,stderr=deps.stderr));deps.check_returncode()
 for line in deps.stdout.splitlines():
  if not line.startswith('    '):continue
  p=Path(line.strip())
  if not p.is_file()or str(p.resolve())in seen:continue
  p=p.resolve()
  if p.is_relative_to(ROOT):snapshot(p)
  else:seen.add(str(p));binding.append(row(p))
 for p in Path(__file__).parent.iterdir():
  if p.is_file():snapshot(p)
 for p in (ROOT/'Strata-extensions/models/deepseek41/CMakeLists.txt',declared,BUILD/'Q-seal.json',BUILD/'q/manifest.json',BUILD/'policy-green.json',BUILD/'CPU-validator.json',BUILD/'core-dev/build-0.json',BUILD/'core-dev/build-1.json'):snapshot(p)
 q=json.loads((BUILD/'q/manifest.json').read_text(encoding='utf-8'))
 for record in [*[x for f in q['frames']for x in f['stages']],*q['outputs'],*q['boundaries'],*q['small_outputs'].values(),q['tap']]:
  r={k:record[k]for k in ('path','bytes','sha256')}
  if row(r['path'])!=r:raise ValueError('independent Q binding')
  binding.append(r)
 for p in tools.values():
  if Path(p).is_file():binding.append(row(p))
 source_qualification=original_sources();save(fixed/'original-sources.json',source_qualification);binding.append(row(fixed/'original-sources.json'));binding.extend([source_qualification['accepted_receipt'],source_qualification['accepted_T10']])
 for name in ('sources.tsv','prefixes.tsv'):snapshot(ROOT/'build-deepseek-t20/full-input'/name)
 save(fixed/'source-map.json',mapping);binding.append(row(fixed/'source-map.json'));runtime=m.runtime_env(bundle)
 for k in list(runtime):
  if k.upper().startswith(('HIP','ROCM'))or k.upper()in('INCLUDE','LIB'):runtime.pop(k,None)
 host=subprocess.run([str(bundle/'t45-layer.exe'),'--host'],env=runtime,capture_output=True,text=True,encoding='utf-8');save(fixed/'host.json',dict(command=host.args,exit=host.returncode,stdout=host.stdout,stderr=host.stderr,GPU_used=False));host.check_returncode()
 if host.stderr:raise ValueError('unexpected host stderr')
 binding.append(row(fixed/'host.json'))
 for item in binding:
  if row(item['path'])!={k:item[k]for k in ('path','bytes','sha256')}:raise ValueError('closure changed')
 save(fixed/'manifest.json',dict(schema='T45-fixed-v1',bindings=binding,source_map=row(fixed/'source-map.json'),Q_seal=row(BUILD/'Q-seal.json'),EXE=row(bundle/'t45-layer.exe'),declared_raw_sha256=row(declared)['sha256'],compiled_source_id=hashlib.sha256(declared.read_text(encoding='utf-8').encode()).hexdigest(),build_both_arch=True,GPU_executed=False,normal_installed_modified=False,fixture_only_test_macro='STRATA_T45_TEST; host boundary-publication allocation failure and final already-computed head guard; no normal ENV/API'))
 print('T45 FIXED',row(fixed/'manifest.json')['sha256'],len(binding),flush=True)

if __name__=='__main__':
 if sys.argv[1:]==['--build']:build()
 elif sys.argv[1:]==['--expectations']:expectations()
 elif sys.argv[1:]==['--seal']:seal()
 else:raise SystemExit('use --build|--expectations|--seal')
