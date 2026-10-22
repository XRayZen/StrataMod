"""Compile a frozen-parent T36 fixture; never launches GPU. --validate needs actual saved output."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,shutil,subprocess,struct,math,tempfile
ROOT=Path('C:/Develop/AI/Strata-data/build/deepseek-v41');HERE=Path(__file__).resolve().parent
PARENT=ROOT/'build-deepseek-t36/producer-parent-r3/source'
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def row(path):
 p=Path(path).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def checked(records):
 for r in records:
  actual=row(r['path'])
  if any(actual[k]!=r[k]for k in('bytes','sha256')if k in r):raise ValueError('closed binding changed '+r['path'])
def tools():return module('T36_existing_tools',ROOT/'Strata-extensions/tests/serve_provider/build_verify.py')

def build(destination,normal=False):
 destination=Path(destination).resolve();destination.mkdir(exist_ok=False);source=destination/'source';shutil.copytree(PARENT,source)
 parent_quant=json.loads((PARENT.parent/'quant-parent.json').read_text(encoding='utf-8'))
 for r in parent_quant['records']:
  checked([dict(path=r['target'],bytes=r['bytes'],sha256=r['sha256'])])
 baseline=[row(p)for p in PARENT.rglob('*')if p.is_file()];mapping=[]
 overlay=[HERE/n for n in('fixture.hip','reference.py','test_policy.py','build_verify.py','CMakeLists.txt','contract.json')]
 for original in overlay:
  before=row(original);target=source/original.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
  if row(original)!=before or row(target)['sha256']!=before['sha256']:raise ValueError('overlay changed')
  mapping.append(dict(original=before,snapshot=row(target)))
 helper=tools();toolchain,env,sdk=helper.hip_tools();cmake=destination/'cmake';folder=source/'Strata-extensions/models/deepseek41'if normal else source/'Strata-extensions/tests/prefix_reuse'
 commands=[[toolchain['cmake'],'--fresh','-S',folder,'-B',cmake,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={toolchain["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={toolchain["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={toolchain["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={toolchain["rc"].as_posix()}',f'-DCMAKE_MT={toolchain["mt"].as_posix()}',f'-DCMAKE_LINKER={toolchain["linker"].as_posix()}'],[toolchain['cmake'],'--build',cmake,'--target',*(['Strata-deepseek','t28-construction']if normal else['t36-prefix']),'--verbose']]
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
 for name in('Strata-deepseek.exe','t28-construction.exe')if normal else('t36-prefix.exe',):consumed.append(row(bundle/name))
 consumed += [row(bundle/name)for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')]
 declared=cmake/'declared-sources.tsv';source_id=hashlib.sha256(declared.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
 checked(baseline);checked([r['original']for r in mapping]);checked(consumed)
 flags=[('--identity','Strata-deepseek.exe'),('--construction-policy-test','t28-construction.exe')]if normal else[('--policy','t36-prefix.exe')]
 cpu=[]
 for flag,exe in flags:
  result=subprocess.run([str(bundle/exe),flag],env=helper.runtime_env(bundle),capture_output=True,text=True,encoding='utf-8');cpu.append(dict(exe=row(bundle/exe),flag=flag,exit=result.returncode,stdout=result.stdout,stderr=result.stderr));result.check_returncode()
  if result.stderr:raise ValueError('unexpected CPU stderr')
 save(destination/'build.json',dict(parent=baseline,overlay=mapping,consumed=consumed,declared=row(declared),compiled_source_id=source_id,source_id_material='UTF-8 LF; raw declared file separately bound',both_arch=True,CPU=cpu,GPU_executed=False,normal=normal,live_quant_consumed=False,T46_live_consumed=False))
 print(row(destination/'build.json'))


EXPECTED_EVENTS=[('reject','primary-demand','T36-owner-old','1'),('adopt','primary-demand-retired','T36-adopt-0','1'),('reject','primary-prefetch','T36-adopt-0','1'),('adopt','prefetch-retired','T36-adopt-1','1'),('reject','row-queued','T36-adopt-1','1'),('adopt','row-queued-retired','T36-adopt-2','1'),('reject','row-ready','T36-adopt-2','1'),('reject','row-borrowed','T36-adopt-2','1'),('reject','row-return-pending','T36-adopt-2','1'),('reject','row-done-untaken','T36-adopt-2','1'),('adopt','row-returned-taken','T36-adopt-3','1'),('terminal','all-raw-logits-equal','T36-adopt-3','2')]
def validate(directory):
 p=Path(directory);events=[tuple(line.split('\t'))for line in(p/'owner-events.tsv').read_text(encoding='utf-8').splitlines()]
 if events!=EXPECTED_EVENTS:raise ValueError('literal owner/cursor/retirement/terminal trace differs')
 raw={}
 for name in('fresh2-logits.bin','candidate1-logits.bin','continued2-logits.bin'):
  data=(p/name).read_bytes()
  if len(data)!=129280*4 or not all(math.isfinite(x)for x in struct.unpack('<129280f',data)):raise ValueError('raw finite full logit shape')
  raw[name]=data
 if raw['fresh2-logits.bin']!=raw['continued2-logits.bin']:raise ValueError('allbits raw next logits differ')
 return dict(values=129280,events=12,rejections=7,adoptions=4,full_state_payload_verified=False,actual_execution_proven_by_validator_alone=False)
def selftest():
 with tempfile.TemporaryDirectory(prefix='T36-owner-comparator-')as folder:
  p=Path(folder);trace='\n'.join('\t'.join(r)for r in EXPECTED_EVENTS)+'\n';payload=struct.pack('<f',.5)*129280
  for name in('fresh2-logits.bin','candidate1-logits.bin','continued2-logits.bin'):(p/name).write_bytes(payload)
  (p/'owner-events.tsv').write_text(trace,encoding='utf-8');validate(p);rejects=0
  cases=[('owner-events.tsv',trace.replace('T36-adopt-3','T36-adopt-4').encode()),('owner-events.tsv',trace.replace('row-return-pending','row-returned').encode()),('owner-events.tsv','\n'.join(trace.splitlines()[:-1]).encode()),('continued2-logits.bin',payload[:-1]),('continued2-logits.bin',struct.pack('<f',.25)+payload[4:]),('fresh2-logits.bin',struct.pack('<f',float('nan'))+payload[4:]),('candidate1-logits.bin',b'')]
  for name,data in cases:
   target=p/name;before=target.read_bytes();target.write_bytes(data)
   try:validate(p)
   except(ValueError,FileNotFoundError):rejects+=1
   else:raise ValueError('negative mutation accepted '+name)
   finally:target.write_bytes(before)
  return dict(synthetic_comparator_only=True,mutations_rejected=rejects,GPU_executed=False)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--build',type=Path);parser.add_argument('--parent',type=Path);parser.add_argument('--validate',type=Path);parser.add_argument('--CPU',action='store_true');args=parser.parse_args()
 if args.parent:PARENT=args.parent.resolve()
 if args.build:build(args.build,normal=False)
 elif args.validate:print(json.dumps(validate(args.validate)))
 elif args.CPU:print(json.dumps(selftest()))
 else:parser.error('explicit --build, --validate or --CPU required; no GPU launch operation')
