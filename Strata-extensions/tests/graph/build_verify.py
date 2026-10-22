"""Isolated T39 host contract build; module compile does not run HIP or a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import ctypes
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BUILD=ROOT/'build-deepseek-t39'
BASE=ROOT/'build-deepseek-t46/native-union-build-r4/source'
SHARED=Path('C:/Develop/AI/StrataMod')
SDK=SHARED/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'

def row(path):
    p=Path(path)
    with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=digest)

def environment(out):
    vc=SHARED/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207'
    sdk=SHARED/'.vision-toolchain/winsdk'
    inc=sdk/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0'
    lib=sdk/'microsoft.windows.sdk.cpp.x64/c'
    env=os.environ.copy()
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']))
    env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64']))
    env['PATH']=str(vc/'bin/Hostx64/x64')+os.pathsep+env.get('PATH','')
    temp=out/'tmp';temp.mkdir(exist_ok=True);env['TMP']=env['TEMP']=str(temp)
    return vc/'bin/Hostx64/x64/cl.exe',SDK/'lib/llvm/bin/clang++.exe',env

def run(cmd,env,out,name):
    p=subprocess.run(list(map(str,cmd)),env=env,cwd=out,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    (out/(name+'.stdout.txt')).write_text(p.stdout,encoding='utf-8')
    (out/(name+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
    return dict(command=list(map(str,cmd)),exit=p.returncode,stdout=p.stdout,stderr=p.stderr)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['host','compile','runtime-build','runtime-trace-build','runtime-run']);parser.add_argument('--attempt',required=True)
    parser.add_argument('--device',type=int);parser.add_argument('--prepared',type=Path)
    args=parser.parse_args()
    if args.mode=='runtime-run':return runtime_run(args)
    out=BUILD/args.attempt;out.mkdir(parents=True,exist_ok=False)
    # Copy only new graph/header and its immutable dependency closure. Never consume live T36.
    tree=out/'source';owned=ROOT/'Strata-extensions'
    baseline_files=[BASE/'Strata-extensions/native/quant/quant.hpp',BASE/'Strata-extensions/native/cache/lease_queue.hpp',BASE/'Strata-extensions/native/stats/measurement.hpp']
    if args.mode in ('runtime-build','runtime-trace-build'):baseline_files.append(BASE/'Strata-extensions/native/quant/quant.hip')
    new_files=[owned/'tests/graph/primary_projection_fixture.hip']
    for p in [owned/'native/graph/primary_projection.hpp',owned/'native/graph/primary_projection.hip']:
        if p.exists():new_files.append(p)
    bindings=[]
    for p in baseline_files+new_files:
        rel=p.relative_to(BASE if p in baseline_files else ROOT);dst=tree/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst);bindings.append(row(p))
    cl,clang,env=environment(out)
    if args.mode in ('runtime-build','runtime-trace-build'):
        return runtime_build(out,tree,bindings,clang,env,trace=args.mode=='runtime-trace-build')
    if args.mode=='host':
        fixture=tree/'Strata-extensions/tests/graph/primary_projection_fixture.hip'
        cmd=[cl,'/nologo','/std:c++17','/EHsc','/MT','/utf-8','/I'+str(tree/'Strata-extensions/native/stats'),'/TP',fixture,'/Fe:'+str(out/'contract.exe'),'/Fo:'+str(out/'contract.obj')]
    else:
        cmd=[clang,'-std=c++17','-O3','-fno-fast-math','-ffp-contract=off','-fdenormal-fp-math=ieee','-D__HIP_PLATFORM_AMD__=1','-D__HIP_ROCclr__=1',
             '--rocm-path='+str(SDK),'--rocm-device-lib-path='+str(SDK/'lib/llvm/amdgcn/bitcode'),'--offload-arch=gfx1100','--offload-arch=gfx1201',
             '-I'+str(SDK/'include'),'-I'+str(tree/'Strata-extensions/native/stats'),'-MD','-MF',out/'dependencies.d','-x','hip','-c',tree/'Strata-extensions/native/graph/primary_projection.hip','-o',out/'primary_projection.obj']
    result=run(cmd,env,out,'build')
    if args.mode=='host' and result['exit']==0:result['host']=run([out/'contract.exe'],env,out,'host')
    result.update(mode=args.mode,bindings=bindings,compiler=row(cl if args.mode=='host' else clang),GPU_executed=False,actual_application=False)
    result['recipe']=row(Path(__file__))
    artifact=out/('contract.exe' if args.mode=='host' else 'primary_projection.obj')
    if artifact.exists():result['artifact']=row(artifact)
    if args.mode=='compile':
        result['HIP_header']=row(SDK/'include/hip/hip_runtime_api.h')
        result['HIP_import_library']=row(SDK/'lib/amdhip64.lib')
        result['runtime']=row(ROOT/'build-deepseek-t46/native-union-build-r4/cmake/bundle/amdhip64_7.dll')
    for b in bindings:
        if row(b['path'])!=b:raise RuntimeError('source changed during build')
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(verification=row(out/'verification.json'),exit=result['exit'],host=result.get('host'))))
    raise SystemExit(result['exit'] or result.get('host',{}).get('exit',0))

def runtime_build(out,tree,bindings,clang,env,trace=False):
    flags=['-std=c++17','-O3','-fno-fast-math','-ffp-contract=off','-fdenormal-fp-math=ieee','-D__HIP_PLATFORM_AMD__=1','-D__HIP_ROCclr__=1',
           '-D_DLL','-D_MT','-Xclang','--dependent-lib=msvcrt','--rocm-path='+str(SDK),'--rocm-device-lib-path='+str(SDK/'lib/llvm/amdgcn/bitcode'),
           '--offload-arch=gfx1100','--offload-arch=gfx1201','-I'+str(SDK/'include'),'-I'+str(tree/'Strata-extensions/native/stats')]
    if trace:flags+=['-DSTRATA_T39_GRAPH_TRACE=1'] # diagnostic target only; original linker/payload unchanged
    sources=[tree/'Strata-extensions/native/quant/quant.hip',tree/'Strata-extensions/native/graph/primary_projection.hip',tree/'Strata-extensions/tests/graph/primary_projection_fixture.hip']
    results=[];objects=[]
    for n,source in enumerate(sources):
        obj=out/(str(n)+'.obj');objects.append(obj)
        cmd=[clang]+flags+['-DSTRATA_T39_RUNTIME=1','-MD','-MF',out/(str(n)+'.d'),'-x','hip','-c',source,'-o',obj]
        result=run(cmd,env,out,'compile-'+str(n));results.append(result)
        if result['exit']:break
    if all(r['exit']==0 for r in results) and len(results)==3:
        cmd=[clang,'--hip-link','--rocm-path='+str(SDK),'--rocm-device-lib-path='+str(SDK/'lib/llvm/amdgcn/bitcode'),'--offload-arch=gfx1100','--offload-arch=gfx1201',
             *objects,'-L'+str(SDK/'lib'),'-lamdhip64','-o',out/'runtime.exe']
        results.append(run(cmd,env,out,'link'))
    result=dict(schema='t39-runtime-build/v1',results=results,bindings=bindings,recipe=row(Path(__file__)),compiler=row(clang),
                HIP_header=row(SDK/'include/hip/hip_runtime_api.h'),HIP_import_library=row(SDK/'lib/amdhip64.lib'),GPU_executed=False,actual_application=False)
    if (out/'runtime.exe').exists():result['exe']=row(out/'runtime.exe')
    # Runtime copying is file I/O only, not DLL loading or an API probe.
    dlls=[]
    for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']:
        src=ROOT/'build-deepseek-t46/native-union-build-r4/cmake/bundle'/name
        shutil.copyfile(src,out/name);dlls.append(row(out/name))
    result['runtime_files']=dlls
    for b in bindings:
        if row(b['path'])!=b:raise RuntimeError('runtime source changed during build')
    proof=out/'verification.json';proof.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(verification=row(proof),exits=[r['exit'] for r in results],GPU_executed=False)))
    raise SystemExit(next((r['exit'] for r in results if r['exit']),0))

def runtime_run(args):
    # Explicit execution mode only AFTER independent review and coordinator window allocation.
    if args.prepared is None or args.device is None or args.device<0:raise ValueError('--prepared and explicit --device required')
    prepared=args.prepared.resolve();proof=prepared/'verification.json';fixed=row(proof);binding=json.loads(proof.read_text(encoding='utf-8'))
    if any(r['exit'] for r in binding['results']) or len(binding['results'])!=4:raise ValueError('build/link not complete')
    for b in binding['bindings']+[binding['recipe'],binding['exe']]+binding['runtime_files']:
        if row(b['path'])!=b:raise ValueError('fixed runtime input changed: '+b['path'])
    out=BUILD/args.attempt;out.mkdir(parents=True,exist_ok=False)
    command=[binding['exe']['path'],'--runtime',str(args.device)]
    start=time.monotonic_ns();child=subprocess.Popen(command,cwd=prepared,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    # Retain and query ORIGINAL Windows process handle, never a PID reopen.
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);handle=ctypes.c_void_p(int(child._handle))
    class FileTime(ctypes.Structure):_fields_=[('low',ctypes.c_uint32),('high',ctypes.c_uint32)]
    created,exited,system,user=FileTime(),FileTime(),FileTime(),FileTime()
    birth_ok=bool(kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(system),ctypes.byref(user)))
    length=ctypes.c_uint32(32768);image=ctypes.create_unicode_buffer(length.value)
    path_ok=bool(kernel.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(length)))
    timed_out=False
    try:stdout,stderr=child.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        timed_out=True;child.kill();stdout,stderr=child.communicate()
    waited=child.wait();exit_value=ctypes.c_uint32();exit_ok=bool(kernel.GetExitCodeProcess(handle,ctypes.byref(exit_value)))
    child._handle.Close()
    (out/'stdout.json').write_bytes(stdout);(out/'stderr.txt').write_bytes(stderr)
    result=dict(command=command,pid=child.pid,birth_filetime=(created.high<<32)|created.low if birth_ok else None,
                queried_original_handle_path=image.value if path_ok else None,original_handle_wait_exit=waited,
                original_handle_exit_code=exit_value.value if exit_ok else None,original_handle_closed=True,timed_out=timed_out,
                wall_ns=time.monotonic_ns()-start,build_proof=fixed,stdout=row(out/'stdout.json'),stderr=row(out/'stderr.txt'),GPU_executed=True,actual_Core_application=False)
    try:
        observed=json.loads(stdout.decode('utf-8'));result['observed']=observed
        result['graph_pass']=not timed_out and waited==0 and exit_ok and exit_value.value==0 and birth_ok and path_ok and Path(image.value).resolve()==Path(binding['exe']['path']).resolve() and observed['graph_pass'] is True and len(observed['cases'])==2
        for case in observed['cases']:
            result['graph_pass'] &= case['closed'] is True and case['captures']==1 and case['replays']>=2 and case['eager']==1 and case['capture_fallbacks']==0 and len(case['stages'])==4
            for stage in case['stages']:result['graph_pass'] &= stage['actual_bits']==stage['independent_expected_bits'] and len(stage['actual_bits'])==10
    except (ValueError,KeyError,TypeError):result['graph_pass']=False
    if row(proof)!=fixed:raise RuntimeError('build proof changed during runtime')
    path=out/'verification.json';path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(verification=row(path),exit=waited,graph_pass=result['graph_pass'],resource_returned='child handle waited/closed; coordinator checks external owner state')))
    raise SystemExit(0 if result['graph_pass'] else 1)

if __name__=='__main__':main()
