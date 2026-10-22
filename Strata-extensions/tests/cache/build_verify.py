"""T16 fixed local-sidecar proof; only explicit execute initializes HIP."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
BUILD=ROOT/'build-deepseek-t16'
HERE=Path(__file__).resolve().parent
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
SHARED=Path('C:/Develop/AI/StrataMod')
SDK=SHARED/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
COMPILED=['Strata-extensions/native/cache/lease_queue.hpp','Strata-extensions/native/cache/lease_queue.cpp',
          'Strata-extensions/tests/cache/ledger_fixture.cpp','Strata-extensions/tests/cache/hip_lease_fixture.hip']
RECIPES=['Strata-extensions/native/cache/CMakeLists.txt','Strata-extensions/tests/cache/declared-set.json','Strata-extensions/tests/cache/build_verify.py']
DEPS=['Strata-extensions/native/stats/measurement.hpp','Strata-extensions/native/stats/measurement.cpp',
      'include/strata/core/device.hpp','src/core/device.cu','include/strata/core/pinned_ring.hpp',
      'include/strata/hip_compat/cuda_runtime.h','include/strata/hip_compat/cuda_runtime_api.h',
      'include/strata/hip_compat/intrinsics.hpp',
      'build-deepseek-t07/bundle/manifest.json','build-deepseek-t08/bundle/manifest.json',
      'build-deepseek-t09/bundle/manifest.json','build-deepseek-t09/verification.json',
      'build-deepseek-t34/bundle/manifest.json','build-deepseek-t34/bundle/verification.json']
MANIFEST=BUILD/'bundle/manifest.json'

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def row(p):return {'path':str(p),'bytes':Path(p).stat().st_size,'sha256':sha(p)}
def rows(paths):return [{'path':p,'sha256':sha(ROOT/p)} for p in paths]
def aggregate(items):return hashlib.sha256(''.join(f"{r['path']}|{r['sha256']}\n" for r in items).encode()).hexdigest()
def save(p,obj):Path(p).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def run(cmd,env,check=True,timeout=180):
    r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if check and r.returncode:raise RuntimeError(f'exit {r.returncode}: {cmd}\n{r.stdout}\n{r.stderr}')
    return r
def environment():
    vc=SHARED/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=SHARED/'.vision-toolchain/winsdk'
    inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
    tools={'clang':SDK/'lib/llvm/bin/clang++.exe','cmake':SHARED/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',
           'ninja':SHARED/'.vision-venv-10.1/Scripts/ninja.exe','linker':vc/'bin/Hostx64/x64/link.exe','dumpbin':vc/'bin/Hostx64/x64/dumpbin.exe',
           'rc':wb/'rc.exe','mt':wb/'mt.exe','objdump':SDK/'lib/llvm/bin/llvm-objdump.exe'}
    env=os.environ.copy();temporary=BUILD/'tmp';temporary.mkdir(parents=True,exist_ok=True);env['TMP']=env['TEMP']=str(temporary)
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']))
    env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',SDK/'lib']))
    env['PATH']=os.pathsep.join(map(str,[SDK/'bin',SDK/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')]))
    env['HIP_PATH']=env['ROCM_PATH']=str(SDK);env['HIP_PLATFORM']='amd'
    return tools,env
def check_files(items):
    for item in items:
        if row(item['path'])!=item:raise ValueError('fixed file changed: '+item['path'])
def binding(m):
    if m['compiled']!=rows(COMPILED) or m['recipes']!=rows(RECIPES) or m['dependencies']!=rows(DEPS) or m['source_id']!=aggregate(rows(COMPILED)):raise ValueError('source/recipe/dependency binding')
    check_files(m['bundle_files']);check_files(list(m['tools'].values()))
    _,env=environment()
    if run(['git','rev-parse','HEAD'],env).stdout.strip()!=BASE or run(['git','diff',BASE,'--name-only','--','.',':(exclude)Strata-extensions'],env).stdout.strip():raise ValueError('upstream tracked source changed')

def build():
    tools,env=environment();before=shutil.disk_usage(BUILD).free
    cmake=[tools['cmake'],'--fresh','-S',ROOT/'Strata-extensions/native/cache','-B',BUILD,'-G','Ninja','-DT16_HIP=ON',
           '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',
           f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}',
           '-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',
           f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
    commands=[cmake,[tools['cmake'],'--build',BUILD,'--clean-first','--verbose']]
    for i,cmd in enumerate(commands):
        r=run(cmd,env,check=False);(BUILD/f'build-{i}.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(f'build step{i} failed; see saved log')
    origins=[]
    for name in ['amdhip64_7.dll','amd_comgr.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
        src=SDK/'bin'/name;dst=MANIFEST.parent/name;shutil.copyfile(src,dst);origins.append({'source':str(src),'file':row(dst)})
    notices=MANIFEST.parent/'licenses';notices.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'LICENSE',notices/'Strata-LICENSE')
    for component in ['amd_comgr','rocm-core']:
        for src in (SDK/'share/doc'/component).rglob('*'):
            if src.is_file() and any(s in src.name.lower() for s in ['license','notice','copying']):shutil.copyfile(src,notices/f'{component}-{src.name}')
    for name,command in [('offloading',[tools['objdump'],'--offloading',MANIFEST.parent/'t16-hip.exe']),
                         ('host-imports',[tools['dumpbin'],'/dependents',MANIFEST.parent/'t16-host.exe']),
                         ('hip-imports',[tools['dumpbin'],'/dependents',MANIFEST.parent/'t16-hip.exe'])]:
        r=run(command,env);(BUILD/f'{name}.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    versions={}
    for name,path in tools.items():
        r=run([path,'--version' if name in ['clang','cmake','ninja','objdump'] else '/?'],env,check=False)
        versions[name]=[s for s in (r.stdout+r.stderr).splitlines() if s.strip()][:3]
    m={'schema':'t16-fixed-trial/v2','source_id':aggregate(rows(COMPILED)),'compiled':rows(COMPILED),'recipes':rows(RECIPES),'dependencies':rows(DEPS),
       'bundle_files':[row(p) for p in sorted(MANIFEST.parent.rglob('*')) if p.is_file() and p!=MANIFEST],
       'tools':{n:row(p) for n,p in tools.items()},'tool_versions':versions,'dll_origins':origins,'commands':[list(map(str,c)) for c in commands],
       'scope':'owner-local lease/credit metadata, synthetic finite declared set, separate small primary actual owner/event fixture',
       'upstream_base':BASE,'patches':[],'no_gpu_executed':True,'storage':{'free_before_build':before,'free_after_build':shutil.disk_usage(BUILD).free,'generated_file_bytes':sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file())}}
    save(MANIFEST,m);binding(m);print(json.dumps({'manifest':row(MANIFEST),'gpu_exe':row(MANIFEST.parent/'t16-hip.exe'),'source_id':m['source_id'],'gpu_executed':False}))

def host():
    m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);_,env=environment();env['PATH']=str(MANIFEST.parent)+os.pathsep+env['PATH']
    r=run([MANIFEST.parent/'t16-host.exe'],env);(BUILD/'host.stdout.json').write_text(r.stdout,encoding='utf-8');(BUILD/'host.stderr.txt').write_text(r.stderr,encoding='utf-8')
    receipt=json.loads(r.stdout);contract=read(HERE/'declared-set.json')
    if receipt['source_id']!=m['source_id'] or receipt['assertions']!=contract['host_expected_assertions'] or not receipt['synthetic_declared_set'] or receipt['hardware_completion_claim']:raise ValueError('host coverage/identity')
    binding(m)
    if sha(MANIFEST)!=fixed:raise ValueError('manifest changed during host tests')
    save(BUILD/'host-verification.json',{'manifest_sha256':fixed,'receipt':receipt,'stdout':row(BUILD/'host.stdout.json'),'binding_before_after':True,'GPU_executed':False})
    print(json.dumps(receipt))

def execute(pageable=False):
    m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);_,env=environment();env['PATH']=str(MANIFEST.parent)+os.pathsep+env['PATH']
    if pageable:env['STRATA_TEST_PAGEABLE']='1'
    else:env.pop('STRATA_TEST_PAGEABLE',None)
    label='pageable' if pageable else 'primary';prefix=BUILD/label
    if prefix.with_suffix('.stdout.json').exists():raise ValueError('preserve prior attempt before retry')
    fixture_sha=sha(HERE/'declared-set.json');identity={'fixture_sha256':fixture_sha,'asset_sha256':fixture_sha,'bundle_sha256':fixed,'request_id':'T16-fixture-'+label,'epoch':1}
    cmd=[MANIFEST.parent/'t16-hip.exe','--probe','0000:07:00.0',fixture_sha,fixture_sha,fixed,identity['request_id'],'1']
    r=run(cmd,env,check=False);prefix.with_suffix('.stdout.json').write_text(r.stdout,encoding='utf-8');prefix.with_suffix('.stderr.txt').write_text(r.stderr,encoding='utf-8')
    record={'manifest_sha256':fixed,'gpu_exe':row(MANIFEST.parent/'t16-hip.exe'),'exit':r.returncode,'stderr':r.stderr,'test_only_pageable_override':pageable,'status':'not_passed'}
    save(BUILD/f'{label}-verification.json',record);binding(m)
    if sha(MANIFEST)!=fixed:raise ValueError('manifest changed during GPU fixture')
    if r.returncode:raise RuntimeError('GPU fixture failed; logs retained; no blind retry')
    receipt=json.loads(r.stdout)
    if receipt['pci']!='0000:07:00.0' or receipt['source_id']!=m['source_id'] or receipt['caller_identity']!=identity or not receipt['owner_drained_before_free']:raise ValueError('GPU owner/source/identity/drain')
    if not receipt['stream'] or not receipt['dma_event'] or not receipt['kernel_event']:raise ValueError('actual event binding absent')
    for observation in receipt['stage_observations']:
        if not observation['query_attempted']:
            if observation['query_status'] is not None or observation['memory_type'] is not None:raise ValueError('unattempted stage query shown as measured')
        elif observation['query_status']!=0 and observation['memory_type'] is not None:raise ValueError('failed stage query shown as measured')
    if receipt['observed_pinned']:
        stages=receipt['stage_observations']
        if pageable or receipt['operations']!=16 or receipt['pinned_subset']!=262144 or receipt['owned_host']!=393216 or receipt['owned_device']!=135168 or len({s['address'] for s in stages})!=4 or any(not s['query_attempted'] or s['query_status']!=0 or s['memory_type']!=1 or s['capacity']!=65536 for s in stages):raise ValueError('pinned physical stage/capacity/operation qualification')
        status='pinned_lease_pass'
    else:
        if not receipt['pageable_fallback'] or receipt['operations']!=0 or receipt['pinned_subset'] is not None or receipt['owned_host'] is not None:raise ValueError('unknown pinned scope/fallback')
        status='pageable_fallback_pass_pinned_lifetime_unverified'
    loaded=[]
    for p in receipt['loaded_modules']:
        if Path(p).name.lower() in ['amdhip64_7.dll','amd_comgr.dll']:
            if Path(p).resolve().parent!=MANIFEST.parent.resolve():raise ValueError('HIP loaded outside fixed bundle')
            loaded.append(row(p))
    if len(loaded)!=2:raise ValueError('actual HIP/comgr load proof missing')
    binding(m)
    if sha(MANIFEST)!=fixed:raise ValueError('manifest changed after receipt validation')
    record.update(status=status,receipt=receipt,loaded_hip=loaded,binding_before_after=True,normal_runtime_changes=False)
    save(BUILD/f'{label}-verification.json',record);print(json.dumps({k:v for k,v in record.items() if k not in ['receipt','loaded_hip']}))

def negatives():
    m=read(MANIFEST);binding(m);count=0
    for name in ['source_id','compiled','recipes','dependencies']:
        bad=copy.deepcopy(m)
        if name=='source_id':bad[name]='0'*64
        else:bad[name][0]['sha256']='0'*64
        try:binding(bad)
        except ValueError:count+=1
        else:raise AssertionError('mutated fixed binding accepted')
    tmp=BUILD/'tampered-same-source.exe';shutil.copyfile(MANIFEST.parent/'t16-hip.exe',tmp)
    with tmp.open('r+b') as f:f.seek(-1,2);b=f.read(1);f.seek(-1,2);f.write(bytes([b[0]^1]))
    bad=copy.deepcopy(m)
    original=next(r for r in bad['bundle_files'] if Path(r['path']).name=='t16-hip.exe');original['path']=str(tmp)
    try:binding(bad)
    except ValueError:count+=1
    else:raise AssertionError('same-identity modified artifact accepted')
    _,env=environment();env['PATH']=str(MANIFEST.parent)+os.pathsep+env['PATH']
    formatted=json.loads(run([MANIFEST.parent/'t16-hip.exe','--stage-format-selftest'],env).stdout)
    failed=formatted['failed_nonzero_type'];missing=formatted['not_attempted_nonzero_type'];success=formatted['successful_host']
    if formatted['GPU_context_created'] or failed['query_status'] in [0,None] or failed['memory_type'] is not None or missing['query_status'] is not None or missing['memory_type'] is not None or success['query_status']!=0 or success['memory_type']!=1:raise AssertionError('query failure/unknown formatting')
    save(BUILD/'stage-format-selftest.json',formatted);count+=2
    save(BUILD/'binding-negatives.json',{'passed':count,'GPU_executed':False});print(f'{count} binding negatives passed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['build','host','execute','negatives']);p.add_argument('--pageable',action='store_true');a=p.parse_args()
    BUILD.mkdir(parents=True,exist_ok=True)
    if a.mode=='execute':execute(a.pageable)
    else:globals()[a.mode]()
