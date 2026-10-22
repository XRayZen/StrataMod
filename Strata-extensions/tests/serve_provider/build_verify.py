"""T28 normal provider build/qualification (task-local outputs only)."""
from pathlib import Path
import argparse, importlib.util, json, subprocess
ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build-deepseek-t28/normal"
def host_sampling():
    BUILD.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("t06_tools", ROOT / "Strata-extensions/tests/native/build_verify.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    tools, env = mod.toolchain(BUILD)
    command = [str(tools["compiler"]), "/nologo", "/EHsc", "/std:c++17", "/MD", str(Path(__file__).with_name("test_sampling.cpp")), str(ROOT / "Strata-extensions/models/deepseek41/sampling.cpp"), str(ROOT/"Strata-extensions/native/protocol/generation.cpp"),"bcrypt.lib", "/Fo"+str(BUILD)+"/", "/Fe"+str(BUILD/"t28-sampling.exe")]
    def run(cmd, name):
        p = subprocess.run(cmd, env=env, capture_output=True, text=True)
        (BUILD/name).write_text(json.dumps({"command":cmd,"exit":p.returncode,"stdout":p.stdout,"stderr":p.stderr},indent=2), encoding="utf-8")
        print(p.stdout, p.stderr)
        p.check_returncode()
    run(command, "sampling-build.json")
    run([str(BUILD/"t28-sampling.exe")], "sampling-test.json")
def hip_build():
    BUILD.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location("t28_existing_hip_tools",ROOT/"Strata-extensions/tests/core/build_verify.py")
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.BUILD=BUILD
    tools,env=m.environment();sdk=m.SDK;out=BUILD/"cmake-dev"
    cmd=[tools['cmake'],'--fresh','-S',ROOT/'Strata-extensions/models/deepseek41','-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
    for i,command in enumerate([cmd,[tools['cmake'],'--build',out,'--verbose']]):
        r=subprocess.run(list(map(str,command)),env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (BUILD/f'normal-build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
        print('HIP stage',i,'exit',r.returncode,flush=True)
        if r.returncode:raise RuntimeError('normal build failed; original log retained')


def sha(path):
    import hashlib
    with Path(path).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def row(path):path=Path(path).resolve();return dict(path=str(path),bytes=path.stat().st_size,sha256=sha(path))
def prepare_server():
    import re,shutil
    source=ROOT/'serve/server.py';patch=ROOT/'Strata-extensions/patches/serve-family-hooks.patch'
    if sha(source)!='1d50a9ad02608254f391a73db96a23c49f9a1620200cbd92ea830275825e8816':raise ValueError('fixed server source changed')
    original=source.read_text(encoding='utf-8').splitlines(True);lines=patch.read_text(encoding='utf-8').splitlines(True)
    if lines[:2]!=['--- a/serve/server.py\n','+++ b/serve/server.py\n']:raise ValueError('patch target boundary')
    result=[];cursor=0;i=2
    while i<len(lines):
        match=re.fullmatch(r'@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@.*\n',lines[i])
        if not match:raise ValueError('invalid exact patch hunk')
        start=int(match[1])-1
        if start<cursor:raise ValueError('overlapping patch hunk')
        result.extend(original[cursor:start]);cursor=start;i+=1
        while i<len(lines)and not lines[i].startswith('@@ '):
            line=lines[i];i+=1
            if not line or line[0]not in ' +-':raise ValueError('unexpected patch body')
            if line[0]in ' -':
                if cursor>=len(original)or original[cursor]!=line[1:]:raise ValueError('exact patch context changed')
                cursor+=1
            if line[0]in ' +':result.append(line[1:])
    result.extend(original[cursor:]);text=''.join(result);compile(text,'prepared-server','exec')
    target=BUILD/'server/serve/server.py';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
    packaged=BUILD/'cmake-dev/bundle/server/serve/server.py';packaged.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,packaged)
    save(BUILD/'server-patch.json',dict(before=row(source),patch=row(patch),after=row(target),live_upstream_modified=False))
    return target

def hip_tools():
    spec=importlib.util.spec_from_file_location('t28_hip_readonly',ROOT/'Strata-extensions/tests/core/build_verify.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.BUILD=BUILD
    tools,env=m.environment();return tools,env,m.SDK

def runtime_env(bundle):
    import os
    _,env,_=hip_tools();env['PATH']=os.pathsep.join([str(bundle),'C:/Windows/System32','C:/Windows']);env['SystemRoot']='C:/Windows';env['PYTHONUTF8']='1'
    temporary=Path(bundle).parent/'runtime-tmp';temporary.mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(temporary)
    return env

def checked(cmd,env,out):
    result=subprocess.run(list(map(str,cmd)),env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    save(out,dict(command=list(map(str,cmd)),exit=result.returncode,stdout=result.stdout,stderr=result.stderr));result.check_returncode();return result

def verify_manifest(manifest):
    for record in manifest['bindings']:
        path=Path(record['path'])
        if path.stat().st_size!=record['bytes']or sha(path)!=record['sha256']:raise ValueError('fixed file changed: '+str(path))

def seal_construction():
    import shutil
    tools,env,sdk=hip_tools();prepare_server()
    attempt=BUILD/'construction-attempt-1'
    if attempt.exists():raise ValueError('preserve previous attempt; use a new fixed version')
    bundle=attempt/'bundle';bundle.mkdir(parents=True)
    bindings=[];copies=[]
    for name in ['Strata-deepseek.exe','t28-construction.exe']:
        source=BUILD/'cmake-dev/bundle'/name;target=bundle/name;shutil.copy2(source,target);bindings.append(row(target));copies.append(dict(origin=row(source),target=row(target)))
    for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
        source=sdk/'bin'/name;target=bundle/name;shutil.copy2(source,target);bindings.append(row(target));copies.append(dict(origin=row(source),target=row(target)))
    declared=(BUILD/'cmake-dev/declared-sources.tsv').read_text(encoding='utf-8')
    for line in declared.splitlines():
        relative,digest=line.split('|');source=ROOT/relative
        if sha(source)!=digest:raise ValueError('build source changed since configure: '+relative)
        target=attempt/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);bindings.append(row(target))
    for relative in ['Strata-extensions/models/deepseek41/CMakeLists.txt','Strata-extensions/tests/serve_provider/build_verify.py','Strata-extensions/tests/serve_provider/test_provider.py','Strata-extensions/tests/serve_provider/test_sampling.cpp','Strata-extensions/tests/serve_provider/q_reference.py','Strata-extensions/tests/serve_provider/contract.json','Strata-extensions/patches/serve-family-hooks.patch','Strata-extensions/models/deepseek41/server_hooks.py','Strata-extensions/models/deepseek41/serve_codec.py','Strata-extensions/control/deepseek_serve.py','Strata-extensions/control/generation_frames.py']:
        source=ROOT/relative;target=attempt/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);bindings.append(row(target))
    deps=checked([tools['ninja'],'-C',BUILD/'cmake-dev','-t','deps'],env,attempt/'ninja-deps.json')
    seen={x['path']for x in bindings}
    for line in deps.stdout.splitlines():
        if not line.startswith('    '):continue
        source=Path(line.strip())
        if not source.is_file():continue
        source=source.resolve()
        if str(source)in seen:continue
        seen.add(str(source))
        if source.is_relative_to(ROOT):
            target=attempt/'source'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);bindings.append(row(target))
        else:bindings.append(row(source))
    for path in [BUILD/'normal-build-0.log',BUILD/'normal-build-1.log',BUILD/'cmake-dev/declared-sources.tsv']:
        target=attempt/path.name;shutil.copy2(path,target);bindings.append(row(target))
    for path in tools.values():
        if Path(path).is_file():bindings.append(row(path))
    expected=dict(cases=[dict(point=owner+':'+point,fresh_device_owned=66048 if owner=='primary'else 2560)for owner in ('primary','row')for point in ('io-unregistered','io-registered','stream','event','ring-submit')],actual_driver_fault=False,normal_fault_api=False)
    expected_path=attempt/'expected.json';save(expected_path,expected);bindings.append(row(expected_path))
    manifest=dict(schema='strata-t28-construction/v1',scope='actual partial construction cleanup/fresh owner only; no model numeric qualification',copies=copies,bindings=bindings,declared_source_sha256=__import__('hashlib').sha256(declared.encode()).hexdigest())
    save(attempt/'manifest.json',manifest)
    verify_manifest(manifest);identity=json.loads(checked([bundle/'Strata-deepseek.exe','--identity'],runtime_env(bundle),attempt/'identity.json').stdout)
    if identity['source_set_sha256']!=manifest['declared_source_sha256']:raise ValueError('compiled source identity mismatch')
    if b'STRATA_T28_CTOR_FAULT'in(bundle/'Strata-deepseek.exe').read_bytes():raise ValueError('fault ENV present in ordinary binary')
    print('construction fixed manifest',sha(attempt/'manifest.json'),flush=True)

def validate_construction(captures,expected,bundle):
    import collections
    if len(captures)!=len(expected['cases']):raise ValueError('construction case coverage')
    for capture,case in zip(captures,expected['cases'],strict=True):
        value=capture['result']
        if(value.get('fault')!=case['point']or value.get('caught')is not True or value.get('fresh_closed')is not True or type(value.get('fresh_device_owned'))is not int or value['fresh_device_owned']!=case['fresh_device_owned']or value.get('actual_driver_fault')is not False or value.get('pure_unknown_control')is not True):raise ValueError('construction result mismatch')
        lines=capture['stderr'].splitlines();failed=lines.index('T28_PHASE failed');fresh=lines.index('T28_PHASE fresh');created=collections.Counter();freed=collections.Counter();streams=set();drained=set()
        for line in lines[failed+1:fresh]:
            parts=line.split()
            if len(parts)!=5 or parts[0]!='T28_CTOR':raise ValueError('construction trace shape')
            _,owner,action,kind,address=parts;key=(owner,'io'if kind=='unregistered-io'else kind,address)
            if action=='create':created[key]+=1
            elif action=='free':freed[key]+=1
            elif action=='drain':drained.add((owner,kind,address))
            elif action=='unknown':raise ValueError('real drain unknown')
            elif(action,kind)!=('release','ring'):raise ValueError('unknown resource action')
            if action=='create'and kind=='stream':streams.add((owner,kind,address))
        if not created or created!=freed or streams!=drained:raise ValueError('partial resources not exactly reclaimed')
        modules=value.get('loaded_runtime_modules')
        if type(modules)is not dict or set(modules)!={'amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'}:raise ValueError('actual runtime observations missing')
        for name,path in modules.items():
            if type(path)is not str or Path(path).resolve()!=(bundle/name).resolve():raise ValueError('actual runtime path outside fixed bundle')
    return dict(cases=len(captures),partial_real_failures=len(captures),fresh_real_owners=len(captures),actual_driver_fault=False,pure_unknown_control=True)

def execute_construction():
    import datetime,shutil
    attempt=BUILD/'construction-attempt-1';manifest=load(attempt/'manifest.json');expected=load(attempt/'expected.json');bundle=attempt/'bundle';env=runtime_env(bundle)
    verify_manifest(manifest);fingerprint=sha(attempt/'manifest.json')
    # Existing allocation/model acquisition is reflected in current free already.
    held=sum(p.stat().st_size for p in BUILD.rglob('*')if p.is_file());free=shutil.disk_usage(ROOT).free
    future={'T28_remaining_estimate':max(0,2*1024**3-held),'T37_generated':512*1024**2,'T20':64*1024**2,'T25':32*1024**2,'other_conservative':234881024,'metadata':16*1024**2}
    save(attempt/'capacity.json',dict(time=datetime.datetime.now().astimezone().isoformat(),free=free,normal_held_already_in_free=held,model_remaining=0,T37_acquisition_remaining=0,future=future,remaining_after_estimates=free-sum(future.values()),hardcap=False))
    status=checked([str(Path('C:/Windows/System32/cmd.exe')),'/d','/c',str(ROOT.parents[1]/'strata.cmd'),'status'],env,attempt/'cli-status.json')
    if '停止済み'not in status.stdout:raise RuntimeError('owned runtime not confirmed stopped; no GPU run')
    captures=[]
    source=load(ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json')['destination']
    args=['--artifact-root',source,'--primary-pci','0000:07:00.0','--context','16','--bundle-id',fingerprint,'--runtime-epoch','1']
    for case in expected['cases']:
        result=checked([bundle/'t28-construction.exe',*args,'--constructor-test',case['point']],env,attempt/(case['point'].replace(':','-')+'.json'))
        value=json.loads(result.stdout);captures.append(dict(result=value,stderr=result.stderr))
        validate_construction([captures[-1]],{'cases':[case]},bundle)
        print('construction actual',case['point'],'passed',flush=True)
    summary=validate_construction(captures,expected,bundle);verify_manifest(manifest)
    if sha(attempt/'manifest.json')!=fingerprint:raise ValueError('manifest changed')
    save(attempt/'verification.json',dict(status='pending independent review',manifest_sha256=fingerprint,captures=captures,summary=summary,before_after_binding=True,model_numeric_qualification=False))


def seal_prefill():
    import shutil
    attempt=BUILD/'prefill-control-attempt-1';attempt.mkdir()
    capture=BUILD/'construction-attempt-1';native=load(capture/'manifest.json');verify_manifest(native)
    q=load(BUILD/'q/manifest.json');expected=q['outputs'][1]
    if sha(expected['path'])!=expected['sha256']:raise ValueError('independent Q changed')
    recipe=attempt/'runner.py';shutil.copy2(Path(__file__),recipe)
    manifest=dict(schema='strata-t28-prefill-control/v1',native_manifest=row(capture/'manifest.json'),q_manifest=row(BUILD/'q/manifest.json'),expected=expected,runner=row(recipe),assertions=13,cancelled_processed=1,cancelled_position=1,cancelled_logits_d2h=0,fresh_processed=2,fresh_rows=1,fresh_logits_d2h=517120,normal_full_logits=False,GPU_executed=False)
    save(attempt/'manifest.json',manifest)
    print('prefill pre-G seal',sha(attempt/'manifest.json'),flush=True)

def execute_prefill():
    attempt=BUILD/'prefill-control-attempt-1';manifest=load(attempt/'manifest.json');fingerprint=sha(attempt/'manifest.json')
    for field in ('native_manifest','q_manifest','runner','expected'):
        record=manifest[field]
        if sha(record['path'])!=record['sha256']:raise ValueError('pre-G binding changed')
    native=load(manifest['native_manifest']['path']);verify_manifest(native);bundle=Path(manifest['native_manifest']['path']).parent/'bundle';env=runtime_env(bundle)
    status=checked([str(Path('C:/Windows/System32/cmd.exe')),'/d','/c',str(ROOT.parents[1]/'strata.cmd'),'status'],env,attempt/'cli-status.json')
    if '停止済み'not in status.stdout:raise RuntimeError('owned runtime not stopped')
    source=load(ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json')['destination'];output=attempt/'fresh-logits.bin'
    result=checked([bundle/'t28-construction.exe','--artifact-root',source,'--primary-pci','0000:07:00.0','--context','16','--bundle-id',fingerprint,'--runtime-epoch','1','--prefill-control-test',output],env,attempt/'capture.json')
    validate_prefill(attempt,manifest,fingerprint,native,result,output)

def validate_prefill(attempt,manifest,fingerprint,native,result,output):
    value=json.loads(result.stdout)
    for field in ('assertions','cancelled_processed','cancelled_position','cancelled_logits_d2h','fresh_processed','fresh_rows','fresh_logits_d2h'):
        if type(value.get(field))is not int or value[field]!=manifest[field]:raise ValueError('prefill strict field '+field)
    if value.get('normal_full_logits')is not False:raise ValueError('normal logits default')
    expected=Path(manifest['expected']['path'])
    if output.read_bytes()!=expected.read_bytes():raise ValueError('fresh actual logits differ from independent Q')
    for line in result.stderr.splitlines():
        fields=line.split()
        if len(fields)!=5 or fields[0]!='T28_CTOR'or fields[1]not in('primary','row')or fields[2]!='create'or fields[3]not in('io','stream','event')or not fields[4].isdigit():raise ValueError('unexpected test stderr')
    verify_manifest(native)
    save(attempt/'verification.json',dict(status='pending independent review',manifest_sha256=fingerprint,capture=value,output=row(output),values=129280,exact_bytes=517120,before_after_binding=True))
    print('prefill cancellation and fresh 129280 logits exact',flush=True)


def seal_http():
    import shutil
    attempt=BUILD/'http-attempt-1';attempt.mkdir();capture=BUILD/'construction-attempt-1';bundle=capture/'bundle';native=load(capture/'manifest.json');verify_manifest(native)
    source=load(ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json')['destination'];temporary=attempt/'tmp';temporary.mkdir()
    config=dict(family='deepseek41',artifact_root=source,primary_pci='0000:07:00.0',context=16,exe=str(bundle/'Strata-deepseek.exe'),runtime_epoch=1,bundle_id=sha(capture/'manifest.json'),cache_budget=dict(device_cache_payload_bytes=2097416,ram_cache_payload_bytes=2097416),env=dict(TMP=str(temporary),TEMP=str(temporary)),args=[],arch='deepseek41',backend='hip')
    save(attempt/'config.json',config)
    paths=[Path(__file__),Path(__file__).with_name('test_provider.py'),ROOT/'Strata-extensions/models/deepseek41/server_hooks.py',ROOT/'Strata-extensions/models/deepseek41/serve_codec.py',ROOT/'Strata-extensions/control/generation_frames.py',ROOT/'Strata-extensions/control/deepseek_serve.py',BUILD/'server/serve/server.py',BUILD/'server-patch.json',ROOT/'serve/server.py',ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json']
    bindings=[]
    for i,path in enumerate(paths):
        target=attempt/'source'/str(i)/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);bindings.append(dict(live=row(path),snapshot=row(target)))
    save(attempt/'manifest.json',dict(schema='strata-t28-actual-http/v1',native_manifest=row(capture/'manifest.json'),q_manifest=row(BUILD/'q/manifest.json'),config=row(attempt/'config.json'),bindings=bindings,fixture_context=16,fixture_explicit_budget=True,normal_defaults_qualification=False,GPU_executed=False))
    print('actual HTTP pre-G manifest',sha(attempt/'manifest.json'),flush=True)


def seal_normal(label):
    import shutil,re,hashlib
    if not re.fullmatch('[A-Za-z0-9-]+',label):raise ValueError('generated output label')
    attempt=BUILD/label;attempt.mkdir();bundle=attempt/'bundle';bundle.mkdir();tools,env,sdk=hip_tools();prepare_server();bindings=[];copies=[];seen=set()
    for name in ['Strata-deepseek.exe','t28-construction.exe','amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
        source=BUILD/'cmake-dev/bundle'/name if name.endswith('.exe')else sdk/'bin'/name;target=bundle/name;shutil.copy2(source,target);bindings.append(row(target));copies.append(dict(origin=row(source),target=row(target)))
    server=bundle/'server/serve/server.py';server.parent.mkdir(parents=True);shutil.copy2(BUILD/'server/serve/server.py',server);bindings.append(row(server))
    def bind_source(source):
        source=Path(source).resolve()
        if not source.is_file()or str(source).lower()in seen:return
        seen.add(str(source).lower())
        if source.is_relative_to(ROOT):
            target=attempt/'source'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);bindings.append(row(target))
        else:bindings.append(row(source))
    declared=(BUILD/'cmake-dev/declared-sources.tsv').read_text(encoding='utf-8')
    for line in declared.splitlines():
        relative,digest=line.split('|');source=ROOT/relative
        if sha(source)!=digest:raise ValueError('compiled source changed '+relative)
        bind_source(source)
    for relative in ['Strata-extensions/tests/serve_provider/build_verify.py','Strata-extensions/tests/serve_provider/test_provider.py','Strata-extensions/tests/serve_provider/q_reference.py','Strata-extensions/tests/serve_provider/contract.json','Strata-extensions/models/deepseek41/server_hooks.py','Strata-extensions/models/deepseek41/serve_codec.py','Strata-extensions/control/generation_frames.py','Strata-extensions/control/deepseek_serve.py','Strata-extensions/patches/serve-family-hooks.patch','Strata-extensions/control/providers/deepseek41.py','LICENSE']:
        bind_source(ROOT/relative)
    deps=checked([tools['ninja'],'-C',BUILD/'cmake-dev','-t','deps'],env,attempt/'ninja-deps.json')
    for line in deps.stdout.splitlines():
        if line.startswith('    '):bind_source(line.strip())
    for path in [BUILD/'normal-build-0.log',BUILD/'normal-build-1.log',BUILD/'cmake-dev/declared-sources.tsv',BUILD/'server-patch.json']:
        target=attempt/path.name;shutil.copy2(path,target);bindings.append(row(target))
    for path in tools.values():
        if Path(path).is_file():bind_source(path)
    manifest=dict(schema='strata-t28-fixed-normal/v1',copies=copies,bindings=bindings,declared_source_sha256=hashlib.sha256(declared.encode()).hexdigest(),Q=row(BUILD/'q/manifest.json'),normal_fault_api=False)
    save(attempt/'manifest.json',manifest);verify_manifest(manifest)
    identity=json.loads(checked([bundle/'Strata-deepseek.exe','--identity'],runtime_env(bundle),attempt/'identity.json').stdout)
    if identity['source_set_sha256']!=manifest['declared_source_sha256']:raise ValueError('compiled source identity')
    if b'STRATA_T28_CTOR_FAULT'in(bundle/'Strata-deepseek.exe').read_bytes():raise ValueError('ordinary fault ENV')
    print('normal fixed',label,sha(attempt/'manifest.json'),flush=True)

if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument('--hip-build',action='store_true');parser.add_argument('--prepare-server',action='store_true');parser.add_argument('--seal-construction',action='store_true');parser.add_argument('--execute-construction',action='store_true');parser.add_argument('--seal-normal');parser.add_argument('--seal-http',action='store_true');parser.add_argument('--seal-prefill',action='store_true');parser.add_argument('--execute-prefill',action='store_true');a=parser.parse_args()
    if a.seal_normal:seal_normal(a.seal_normal)
    elif a.seal_http:seal_http()
    elif a.seal_prefill:seal_prefill()
    elif a.execute_prefill:execute_prefill()
    elif a.hip_build:hip_build()
    elif a.prepare_server:prepare_server()
    elif a.seal_construction:seal_construction()
    elif a.execute_construction:execute_construction()
    else:host_sampling()
