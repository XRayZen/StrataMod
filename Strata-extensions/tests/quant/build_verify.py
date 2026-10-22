"""T09 development proof. acquire/prepare/build never initialize a HIP context.

execute is explicit, after Main's public status check. Fixed Q and trial bundle
are checked before/after execution. No candidate-output based oracle tuning.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import numpy as np
import q_reference as q

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
BUILD=ROOT/'build-deepseek-t09'
RAW=Path('C:/Develop/AI/Strata-data/records/deepseek-v41/t09-20261021/fixtures')
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
SHARED=Path('C:/Develop/AI/StrataMod')
SDK=SHARED/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
EXE=BUILD/'bundle/t09-quant.exe'
COMPILED=['Strata-extensions/native/quant/quant.hpp','Strata-extensions/native/quant/quant.hip','Strata-extensions/tests/quant/native_fixture.cpp']
RECIPES=['Strata-extensions/native/quant/CMakeLists.txt','Strata-extensions/tests/quant/build_verify.py',
         'Strata-extensions/tests/quant/q_reference.py','Strata-extensions/tests/quant/test_q_reference.py',
         'Strata-extensions/tests/quant/parity-contract.json','Strata-extensions/tests/quant/fixture-receipts.json']
DEPS=['Strata-extensions/native/artifact/native_reader.hpp','Strata-extensions/native/artifact/native_reader.cpp',
      'include/strata/artifact/dequant.hpp','include/strata/artifact/gguf_reader.hpp',
      'include/strata/artifact/gguf_split.hpp','include/strata/core/geometry.hpp','include/strata/artifact/model_family.hpp',
      'Strata-extensions/native/artifact/acquire.py','Strata-extensions/tests/artifact/fixture-receipts.json',
      'Strata-extensions/tests/artifact/header-inventory.json','Strata-extensions/tests/artifact/source-files.json',
      'Strata-extensions/tests/numerics/reference.py','Strata-extensions/tests/numerics/known-vectors.json',
      'Strata-extensions/tests/numerics/reference-contract.json']
FROZEN=['Strata-extensions/native/CMakeLists.txt','Strata-extensions/native/include/strata_ext/provenance.hpp',
        'Strata-extensions/native/provenance.cpp','Strata-extensions/tests/native/host_fixture.cpp','Strata-extensions/tests/native/build_verify.py',
        'Strata-extensions/native/hip/CMakeLists.txt','Strata-extensions/native/hip/runtime.hpp','Strata-extensions/tests/hip/backend_fixture.hip',
        'Strata-extensions/tests/hip/build_verify.py','Strata-extensions/tests/artifact/native/reader_main.cpp',
        'Strata-extensions/tests/artifact/native/CMakeLists.txt','Strata-extensions/tests/artifact/native/build_verify.py',
        'build-deepseek-t06/bundle/manifest.json','build-deepseek-t06/verification.json',
        'build-deepseek-t07/bundle/manifest.json','build-deepseek-t07/verification.json',
        'build-deepseek-t08/bundle/manifest.json','build-deepseek-t08/bundle/verification.json']

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def row(p):return {'path':str(p),'bytes':Path(p).stat().st_size,'sha256':sha(p)}
def rows(paths):return [{'path':p,'sha256':sha(ROOT/p)} for p in paths]
def aggregate(items):return hashlib.sha256(''.join(f"{r['path']}|{r['sha256']}\n" for r in items).encode()).hexdigest()
def run(cmd,env=None,timeout=180,check=True):
    r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if check and r.returncode:raise RuntimeError(f'exit {r.returncode}: {cmd}\n{r.stdout}\n{r.stderr}')
    return r
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def acquire():
    original=read(HERE.parent/'artifact/fixture-receipts.json')
    fetch=module('t03_acquire',ROOT/'Strata-extensions/native/artifact/acquire.py').fetch_range
    RAW.mkdir(parents=True,exist_ok=True)
    records=[];before=shutil.disk_usage(RAW).free
    for src in original['fixtures'][:3]:
        for expert in range(1,6):
            r=copy.deepcopy(src)
            r.update(index=expert,selection='expert'+str(expert),absolute_offset=src['absolute_offset']+expert*src['bytes'])
            path=RAW/f"{src['tensor']}.expert{expert:02d}.bin"
            url=f"https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF/resolve/{src['revision']}/{src['filename']}"
            if path.exists():raise ValueError('new acquisition refuses to overwrite existing raw')
            try:data,http=fetch(url,r['absolute_offset'],r['bytes'],r['file_bytes'],src['http']['etag'])
            except Exception as e:raise RuntimeError('bounded acquisition failed: '+type(e).__name__) from None
            path.write_bytes(data)
            r.update(http=http,fixture_path=str(path),fixture_sha256=sha(path),
                     qualification='real bounded source bytes; full shard hash not verified; T09 Q/G pending')
            r.pop('nonzero_scale_or_scalar_count',None)
            records.append(r)
            save(BUILD/'acquisition-progress.json',{'fixtures':records})
            print(f'acquired {src["tensor"]} expert{expert}: {len(data)} bytes',flush=True)
    if len(records)!=15 or sum(r['bytes'] for r in records)!=94003200:raise ValueError('coverage/size')
    save(HERE/'fixture-receipts.json',{'revision':original['revision'],'original_receipt_sha256':sha(HERE.parent/'artifact/fixture-receipts.json'),
          'additional_fixture_bytes':94003200,'top6_matrix_fixture_bytes':112803840,'fixtures':records,
          'full_file_sha_verified':False,'disk_free_before':before,'disk_free_after':shutil.disk_usage(RAW).free})

def validate_added(original_receipt,added):
    if added['original_receipt_sha256']!=sha(HERE.parent/'artifact/fixture-receipts.json'):raise ValueError('original receipt changed')
    if added['revision']!=original_receipt['revision'] or added['additional_fixture_bytes']!=94003200 or added['top6_matrix_fixture_bytes']!=112803840 or added['full_file_sha_verified'] is not False:raise ValueError('additional source summary')
    originals={r['tensor']:r for r in original_receipt['fixtures'][:3]}
    inventory=read(HERE.parent/'artifact/header-inventory.json')
    source=read(HERE.parent/'artifact/source-files.json')
    if inventory['revision']!=source['revision'] or source['revision']!=original_receipt['revision']:raise ValueError('fixed metadata revision')
    required={(tensor,e) for tensor in originals for e in range(1,6)}
    candidates=added['fixtures']
    if len(candidates)!=15 or {(r['tensor'],r['index']) for r in candidates}!=required:raise ValueError('additional distinct expert coverage')
    identities=['revision','shard_index','filename','file_bytes','file_lfs_sha256','tensor','type_id','layout','dims_ggml','row_bytes','bytes','full_file_sha_verified']
    for r in candidates:
        src=originals[r['tensor']];expert=r['index']
        if type(expert) is not int or not 1<=expert<=5:raise ValueError('additional expert index')
        if any(r[k]!=src[k] for k in identities):raise ValueError('additional fixed source identity/layout')
        header=next(h for h in inventory['shards'] if h['index']==src['shard_index'])
        file=next(f for f in source['files'] if f['index']==src['shard_index'])
        tensor=next(t for t in header['tensors'] if t['name']==src['tensor'])
        for key,sourcekey in [('filename','filename'),('file_bytes','bytes'),('file_lfs_sha256','lfs_sha256')]:
            if src[key]!=file[sourcekey] or src[key]!=header[sourcekey]:raise ValueError('T03 file metadata identity')
        if any(src[k]!=tensor[k] for k in ['type_id','layout','dims_ggml','row_bytes']):raise ValueError('T03 tensor header identity')
        expert_bytes=tensor['row_bytes']*tensor['dims_ggml'][1]
        if tensor['dims_ggml'][0]%32 or tensor['bytes']!=expert_bytes*tensor['dims_ggml'][2] or src['bytes']!=expert_bytes or src['absolute_offset']!=tensor['absolute_offset']:raise ValueError('T03 full tensor/expert geometry')
        expected=tensor['absolute_offset']+expert*expert_bytes
        if r['absolute_offset']!=expected or r['selection']!='expert'+str(expert):raise ValueError('additional logical expert offset/index')
        etags={h['etag'] for h in header['http_ranges']}
        if etags!={src['http']['etag']}:raise ValueError('T03 header/source ETag')
        http={'status':206,'start':expected,'end':expected+expert_bytes-1,'total':file['bytes'],'etag':src['http']['etag']}
        if r['http']!=http:raise ValueError('additional bounded HTTP source span')
        path=RAW/f"{src['tensor']}.expert{expert:02d}.bin"
        if Path(r['fixture_path']).resolve()!=path.resolve() or not re.fullmatch('[0-9a-f]{64}',r['fixture_sha256']):raise ValueError('additional owned raw path/hash')

def fixture_set():
    original_receipt=read(HERE.parent/'artifact/fixture-receipts.json')
    original=original_receipt['fixtures'];added=read(HERE/'fixture-receipts.json')
    validate_added(original_receipt,added)
    records=original+added['fixtures']
    matrix=[r for r in records if r['type_id']==39]
    keys={(r['tensor'],r['index']) for r in matrix}
    required={(f'blk.0.ffn_{m}_exps.weight',e) for m in ['gate','up','down'] for e in range(6)}
    if len(matrix)!=18 or keys!=required or len(records)!=21:raise ValueError('incomplete distinct real fixture coverage')
    for r in records:
        if Path(r['fixture_path']).stat().st_size!=r['bytes'] or sha(r['fixture_path'])!=r['fixture_sha256']:raise ValueError('raw fixture identity')
        if r['type_id']==39:
            shape=[2304,5120,384] if 'down' in r['tensor'] else [5120,2304,384]
            if r['dims_ggml']!=shape or r['bytes']!=6266880 or r['row_bytes']*shape[1]!=r['bytes']:raise ValueError('matrix shape')
    return records

def numpy_identity():
    root=Path(np.__file__).parent
    paths=[Path(sys.executable),root/'__init__.py',Path(np._core._multiarray_umath.__file__)]
    paths+=list((root.parent/'numpy.libs').glob('*.dll'))
    return {'python':sys.version,'numpy':np.__version__,'files':[row(p) for p in paths]}

def loaded_numpy():
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.K32EnumProcessModules.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.HMODULE),wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetModuleFileNameW.argtypes=[wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD]
    mods=(wintypes.HMODULE*1024)();needed=wintypes.DWORD()
    if not kernel.K32EnumProcessModules(kernel.GetCurrentProcess(),mods,ctypes.sizeof(mods),ctypes.byref(needed)) or needed.value>ctypes.sizeof(mods):raise ValueError('CPU loaded module inventory')
    result=[]
    for handle in mods[:needed.value//ctypes.sizeof(wintypes.HMODULE)]:
        text=ctypes.create_unicode_buffer(32768)
        if not kernel.GetModuleFileNameW(handle,text,len(text)):raise ValueError('CPU module path')
        p=Path(text.value)
        if any(part.lower() in ['numpy','numpy.libs'] for part in p.parts):result.append(row(p))
    if not any('openblas' in r['path'].lower() for r in result) or not any('_multiarray_umath' in r['path'] for r in result):raise ValueError('NumPy loaded native identity missing')
    return result

def prepare():
    run([sys.executable,'-B',HERE/'test_q_reference.py'])
    records=fixture_set();expected_dir=BUILD/'q';expected_dir.mkdir(parents=True,exist_ok=True)
    if (expected_dir/'manifest.json').exists():raise ValueError('Q already frozen; preserve old trial before explicit new prepare')
    jobs=[];files=[];diagnostics=[]
    def job(mode,r,rows,k,b,xpath,expected,name,category):
        target=expected_dir/name
        np.asarray(expected,dtype='<f4').tofile(target)
        entry={'mode':mode,'raw':r['fixture_path'],'source_absolute_offset':r['absolute_offset'],'raw_bytes':r['bytes'],
               'type_id':r['type_id'],'rows':rows,'k':k,'batch':b,'input':str(xpath or '-'),
               'output':name,'expected':row(target),'category':category,'tensor':r['tensor'],'expert':r.get('index')}
        jobs.append(entry);files.append(row(target))
    for n,r in enumerate(records):
        raw=Path(r['fixture_path']).read_bytes();decoded=q.decode(r['type_id'],raw)
        k=r['dims_ggml'][0];nr=len(decoded)//k
        if not np.isfinite(decoded).all():raise ValueError('nonfinite real decode')
        job('decode',r,nr,k,0,None,decoded,f'{n:02d}-decode.bin','real_decode')
        w=decoded.reshape(nr,k)
        for family in ['dense_dyadic','cancellation']:
            rng=np.random.default_rng(20261021+k)
            x=(rng.integers(-8192,8193,(8,k)).astype(np.float32)/8192).astype(np.float32)
            if family=='cancellation':x[:,1::2]=-x[:,::2][:,:x[:,1::2].shape[1]]
            for b in [1,2,4,8]:
                xp=expected_dir/f'x-{family}-K{k}-B{b}.bin'
                if not xp.exists():x[:b].astype('<f4').tofile(xp)
                if not any(f['path']==str(xp) for f in files):files.append(row(xp))
                out=q.ordered(w,x[:b]);d=q.diagnostic(w,x[:b],out)
                diagnostics.append({'tensor':r['tensor'],'expert':r['index'],'family':family,'batch':b,**d})
                job('project',r,nr,k,b,xp,out,f'{n:02d}-{family}-B{b}.bin','real_projection')
        print(f'Q fixed {r["tensor"]} expert{r["index"]}',flush=True)
    # All T04 literal storage vectors are also GPU decoded, independent Q classification.
    for n,v in enumerate(read(HERE.parent/'numerics/known-vectors.json')['decode']):
        raw=bytes.fromhex(v['hex']);p=expected_dir/f'literal-decode-{n}.raw';p.write_bytes(raw);files.append(row(p))
        decoded=q.decode(v['type_id'],raw)
        r={'fixture_path':str(p),'absolute_offset':0,'bytes':len(raw),'type_id':v['type_id'],'tensor':v['name']}
        job('decode',r,1,len(decoded),0,None,decoded,f'literal-decode-{n}.bin','literal_decode')
    for n,c in enumerate(q.boundaries()):
        w,x=c['weights'],c['inputs'];p=expected_dir/f'boundary-{n}.raw';w.astype('<f4').tofile(p);files.append(row(p))
        xp=expected_dir/f'boundary-{n}.x';x.astype('<f4').tofile(xp);files.append(row(xp))
        r={'fixture_path':str(p),'absolute_offset':0,'bytes':w.size*4,'type_id':0,'tensor':c['name']}
        expected=q.ordered(w,x)
        if int(expected.view(np.uint32)[0,0])!=c['expected_bits']:raise ValueError('boundary literal')
        job('project',r,1,w.shape[1],1,xp,expected,f'boundary-{n}.bin','runtime_boundary_common_projection')
    fields=['mode','raw','source_absolute_offset','raw_bytes','type_id','rows','k','batch','input','output']
    tsv=BUILD/'jobs.tsv';tsv.write_text(''.join('\t'.join(str(j[f]) for f in fields)+'\n' for j in jobs),encoding='utf-8');files.append(row(tsv))
    manifest={'schema':'t09-independent-Q/v2','numpy':numpy_identity(),'q_sources':rows(RECIPES[2:]),'dependencies':rows(DEPS),
              'raw_fixtures':[row(r['fixture_path']) for r in records],'jobs':jobs,'files':files,'diagnostics':diagnostics,
              'projection_cases':168,'real_decode_cases':21,'literal_decode_cases':18,'runtime_boundary_cases':6,
              'fixed_before_gpu':True,'normal_runtime_constraints_added':False}
    validate_coverage(manifest)
    save(expected_dir/'manifest.json',manifest)
    print(json.dumps({'Q_manifest_sha256':sha(expected_dir/'manifest.json'),'jobs':len(jobs),'Q_bytes':sum(r['bytes'] for r in files)}))

def validate_coverage(m):
    jobs=m['jobs']
    real=[j for j in jobs if j['category']=='real_projection']
    fixtures=[(f'blk.0.ffn_{t}_exps.weight',e) for t in ['gate','up','down'] for e in range(6)]
    fixtures += [('per_layer_token_embd.weight',1),('token_embd.weight',0),('output_norm.weight',0)]
    expected={(t,e,f,b) for t,e in fixtures for f in ['dense_dyadic','cancellation'] for b in [1,2,4,8]}
    actual={(j['tensor'],j['expert'],j['output'].split('-')[1],j['batch']) for j in real}
    if len(real)!=168 or actual!=expected:raise ValueError('shortened projection coverage')
    counts={'real_decode':21,'literal_decode':18,'runtime_boundary_common_projection':6}
    for c,n in counts.items():
        if sum(j['category']==c for j in jobs)!=n:raise ValueError('shortened decode/boundary coverage')
    if len(jobs)!=213 or len({j['output'] for j in jobs})!=213:raise ValueError('job uniqueness/count')

def environment():
    vc=SHARED/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=SHARED/'.vision-toolchain/winsdk'
    inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c'
    wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
    tools={'clang':SDK/'lib/llvm/bin/clang++.exe','cmake':SHARED/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',
           'ninja':SHARED/'.vision-venv-10.1/Scripts/ninja.exe','linker':vc/'bin/Hostx64/x64/link.exe',
           'dumpbin':vc/'bin/Hostx64/x64/dumpbin.exe','rc':wb/'rc.exe','mt':wb/'mt.exe','objdump':SDK/'lib/llvm/bin/llvm-objdump.exe'}
    env=os.environ.copy();tmp=BUILD/'tmp';tmp.mkdir(parents=True,exist_ok=True);env['TMP']=env['TEMP']=str(tmp)
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']))
    env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',SDK/'lib']))
    env['PATH']=os.pathsep.join(map(str,[SDK/'bin',SDK/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')]))
    env['HIP_PATH']=env['ROCM_PATH']=str(SDK);env['HIP_PLATFORM']='amd'
    return tools,env

def check_files(records):
    for r in records:
        if sha(r['path'])!=r['sha256'] or Path(r['path']).stat().st_size!=r['bytes']:raise ValueError('fixed file changed: '+r['path'])
def q_binding(m):
    validate_coverage(m)
    if m['q_sources']!=rows(RECIPES[2:]) or m['dependencies']!=rows(DEPS) or m['numpy']!=numpy_identity():raise ValueError('Q/dependency/module identity')
    check_files(m['files']);check_files(m['raw_fixtures']);fixture_set()

def build():
    qm=read(BUILD/'q/manifest.json');q_binding(qm)
    tools,env=environment();free_before=shutil.disk_usage(BUILD).free;head=run(['git','rev-parse','HEAD']).stdout.strip()
    diff=run(['git','diff',BASE,'--name-only','--','.',':(exclude)Strata-extensions']).stdout.splitlines()
    if head!=BASE or diff:raise ValueError('upstream tracked source changed')
    commands=[[tools['cmake'],'--fresh','-S',ROOT/'Strata-extensions/native/quant','-B',BUILD,'-G','Ninja',
               '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',
               f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',
               f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}',
               '-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',
               f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],
              [tools['cmake'],'--build',BUILD,'--clean-first','--verbose']]
    for i,c in enumerate(commands):
        r=run(c,env,check=False);(BUILD/f'build-{i}.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(f'build step{i} failed; see build-{i}.txt')
    origins=[]
    for name in ['amdhip64_7.dll','amd_comgr.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:
        src=SDK/'bin'/name;shutil.copyfile(src,EXE.parent/name);origins.append({'source':str(src),**row(EXE.parent/name)})
    for component in ['amd_comgr','rocm-core']:
        for src in (SDK/'share/doc'/component).rglob('*'):
            if src.is_file() and any(t in src.name.lower() for t in ['license','notice','copying']):
                dest=EXE.parent/'licenses'/component/src.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    for src,name in [(ROOT/'LICENSE','Strata-LICENSE'),(ROOT/'third_party/ggml/LICENSE','ggml-LICENSE'),
                     (ROOT/'Strata-extensions/native/artifact/NOTICE.md','T08-NOTICE.md')]:
        shutil.copyfile(src,EXE.parent/'licenses'/name)
    for label,cmd in [('offloading',[tools['objdump'],'--offloading',EXE]),('imports',[tools['dumpbin'],'/dependents',EXE])]:
        r=run(cmd,env);(BUILD/f'{label}.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    versions={}
    for name,path in tools.items():
        flag='--version' if name in ['clang','cmake','ninja','objdump'] else '/?'
        r=run([path,flag],env,check=False)
        versions[name]=[s for s in (r.stdout+r.stderr).splitlines() if s.strip()][:4]
    imports=re.findall(r'^\s+([\w.-]+\.dll)\s*$',(BUILD/'imports.txt').read_text(encoding='utf-8'),re.M|re.I)
    system=[]
    for name in imports:
        candidate=Path(os.environ['SystemRoot'])/'System32'/name
        if not (EXE.parent/name).exists():system.append({'name':name,'resolution':row(candidate) if candidate.is_file() else 'unknown/API-set; full closure not qualified'})
    manifest={'schema':'t09-fixed-native-trial/v2','compiled_sources':rows(COMPILED),'compiled_id':aggregate(rows(COMPILED)),
              'recipes':rows(RECIPES),'dependencies':rows(DEPS),'frozen_prior_tasks':rows(FROZEN),'q_manifest':row(BUILD/'q/manifest.json'),
              'upstream_reference':{'base':BASE,'head':head,'tracked_diff':diff},'patches':[],
              'consumed_external_sources':['Strata-extensions/native/artifact/native_reader.cpp','Strata-extensions/native/artifact/native_reader.hpp','include/strata/artifact/dequant.hpp','include/strata/artifact/gguf_reader.hpp','include/strata/artifact/gguf_split.hpp','include/strata/core/geometry.hpp','include/strata/artifact/model_family.hpp'],
              'artifact':row(EXE),'bundle_files':[row(p) for p in sorted(EXE.parent.rglob('*')) if p.is_file() and p.name!='manifest.json'],
              'tools':{n:row(p) for n,p in tools.items()},'dll_origins':origins,'commands':[list(map(str,c)) for c in commands],
              'tool_versions':versions,'actual_loaded_numpy_modules':loaded_numpy(),'direct_imports':imports,'system_direct_import_candidates':system,
              'storage':{'raw_additional_bytes':94003200,'build_total_file_bytes':sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file()),'free_before_build':free_before,'free_after_build':shutil.disk_usage(BUILD).free},
              'architectures':['gfx1100','gfx1201'],'no_gpu_executed':True,'scope':'native packed dequant/projection parity fixture; no model integration'}
    save(EXE.parent/'manifest.json',manifest);binding(manifest)
    print(json.dumps({'manifest_sha256':sha(EXE.parent/'manifest.json'),'exe_sha256':sha(EXE),'q_sha256':sha(BUILD/'q/manifest.json'),'status':'ready_no_gpu_executed'}))

def binding(m):
    if m['compiled_sources']!=rows(COMPILED) or m['recipes']!=rows(RECIPES) or m['dependencies']!=rows(DEPS) or m['compiled_id']!=aggregate(rows(COMPILED)) or m['frozen_prior_tasks']!=rows(FROZEN):raise ValueError('source/recipe/frozen prior task binding')
    check_files([m['artifact'],m['q_manifest']]+m['bundle_files']);q_binding(read(m['q_manifest']['path']))
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE or run(['git','diff',BASE,'--name-only','--','.',':(exclude)Strata-extensions']).stdout.strip():raise ValueError('upstream tracked reference changed')

def equal_output(actual,expected,classification=False):
    actual_bytes,expected_bytes=Path(actual).stat().st_size,Path(expected).stat().st_size
    if actual_bytes!=expected_bytes or actual_bytes%4 or not actual_bytes:raise ValueError('output byte count/alignment mismatch')
    a=np.fromfile(actual,dtype='<f4');e=np.fromfile(expected,dtype='<f4')
    if a.shape!=e.shape:raise ValueError('short output count')
    finite=np.isfinite(e)
    if not np.array_equal(a.view(np.uint32)[finite],e.view(np.uint32)[finite]):raise ValueError('finite output bit mismatch')
    if not classification and not finite.all():raise ValueError('unexpected nonfinite expectation')
    if not np.array_equal(np.isnan(a),np.isnan(e)) or not np.array_equal(np.isposinf(a),np.isposinf(e)) or not np.array_equal(np.isneginf(a),np.isneginf(e)):raise ValueError('nonfinite classification mismatch')
    return int(e.size)

def execute(role):
    m=read(EXE.parent/'manifest.json');fixed=sha(EXE.parent/'manifest.json');binding(m)
    tools,env=environment();env['PATH']=str(EXE.parent)+os.pathsep+env['PATH']
    pci='0000:07:00.0' if role=='primary' else '0000:03:00.0'
    out=BUILD/f'{role}-outputs'
    if out.exists():raise ValueError('preserve previous device outputs before retry')
    before=shutil.disk_usage(BUILD).free;t=time.monotonic()
    r=run([EXE,'--run',pci,BUILD/'jobs.tsv',out],env,timeout=1800,check=False)
    (BUILD/f'{role}.stdout.json').write_text(r.stdout,encoding='utf-8');(BUILD/f'{role}.stderr.txt').write_text(r.stderr,encoding='utf-8')
    binding(m)
    if fixed!=sha(EXE.parent/'manifest.json'):raise ValueError('trial manifest changed during execution')
    record={'role':role,'pci':pci,'exit':r.returncode,'manifest_sha256':fixed,'q_sha256':m['q_manifest']['sha256'],
            'exe_sha256':m['artifact']['sha256'],'seconds':time.monotonic()-t,'stderr':r.stderr,
            'disk_free_before':before,'disk_free_after':shutil.disk_usage(BUILD).free,'status':'not_passed'}
    save(BUILD/f'{role}-verification.json',record)
    if r.returncode:raise RuntimeError('GPU fixture failed; original logs retained, no blind retry')
    receipt=json.loads(r.stdout);qm=read(BUILD/'q/manifest.json');validate_coverage(qm)
    if receipt['pci']!=pci or receipt['source_id']!=m['compiled_id'] or receipt['completed']!=len(qm['jobs']) or r.stderr:raise ValueError('device/compiled/count/diagnostic mismatch')
    counts={};outputs=[]
    for j in qm['jobs']:
        actual=out/j['output'];n=equal_output(actual,j['expected']['path'],j['category']=='literal_decode')
        counts[j['category']]=counts.get(j['category'],0)+n;outputs.append(row(actual))
    loaded=[row(p) for p in receipt['loaded_modules'] if Path(p).name.lower() in {'amdhip64_7.dll','amd_comgr.dll'}]
    if {Path(x['path']).name.lower() for x in loaded}!={'amdhip64_7.dll','amd_comgr.dll'}:raise ValueError('HIP loaded modules missing')
    for x in loaded:
        if Path(x['path']).resolve().parent!=EXE.parent.resolve() or sha(EXE.parent/Path(x['path']).name)!=x['sha256']:raise ValueError('loaded DLL outside fixed bundle')
    binding(m)
    if fixed!=sha(EXE.parent/'manifest.json'):raise ValueError('post-parity manifest changed')
    record.update(status='pass',receipt=receipt,compared_values=counts,outputs=outputs,loaded_hip=loaded,
                  before_after_binding=True,normal_runtime_constraints_added=False)
    save(BUILD/f'{role}-verification.json',record);print(json.dumps({k:v for k,v in record.items() if k not in ['receipt','outputs']}))

def selftest():
    m=read(BUILD/'q/manifest.json');q_binding(m);count=0
    for category in ['real_decode','real_projection','literal_decode','runtime_boundary_common_projection']:
        broken=copy.deepcopy(m);broken['jobs'].remove(next(j for j in broken['jobs'] if j['category']==category))
        try:validate_coverage(broken)
        except ValueError:count+=1
        else:raise AssertionError('coverage negative accepted')
    tmp=BUILD/'negative';tmp.mkdir(exist_ok=True);e=tmp/'expected.bin';a=tmp/'actual.bin'
    np.array([0,1,-0.],'<f4').tofile(e)
    for values in [[0,1],[0,2,-0.],[0,1,0.],[0,np.nan,-0.]]:
        np.array(values,'<f4').tofile(a)
        try:equal_output(a,e)
        except ValueError:count+=1
        else:raise AssertionError('output negative accepted')
    if (EXE.parent/'manifest.json').exists():
        original=read(EXE.parent/'manifest.json');binding(original)
        tampered=tmp/'same-identity-modified.exe';shutil.copyfile(EXE,tampered)
        with tampered.open('r+b') as f:
            f.seek(-1,2);v=f.read(1);f.seek(-1,2);f.write(bytes([v[0]^1]))
        changed=copy.deepcopy(original);changed['artifact']['path']=str(tampered)
        for candidate in [changed]:
            try:binding(candidate)
            except ValueError:count+=1
            else:raise AssertionError('same-identity replacement accepted')
        for field in ['compiled_id','recipes','q_manifest']:
            candidate=copy.deepcopy(original)
            if field=='compiled_id':candidate[field]='0'*64
            elif field=='recipes':candidate[field][0]['sha256']='0'*64
            else:candidate[field]['sha256']='0'*64
            try:binding(candidate)
            except ValueError:count+=1
            else:raise AssertionError('binding change accepted')
        for key in ['files','raw_fixtures']:
            changed=copy.deepcopy(m);changed[key][0]['sha256']='0'*64
            try:q_binding(changed)
            except ValueError:count+=1
            else:raise AssertionError('Q expectation/raw mutation accepted')
    data=e.read_bytes()
    for malformed in [data+b'x',data+b'xy',data+b'xyz',data[:-1]]:
        a.write_bytes(malformed)
        try:equal_output(a,e)
        except ValueError:count+=1
        else:raise AssertionError('unaligned output body accepted')
    original_receipt=read(HERE.parent/'artifact/fixture-receipts.json');added=read(HERE/'fixture-receipts.json')
    for field,value in [('absolute_offset',1600),('index',0),('file_lfs_sha256','0'*64),('filename','wrong.gguf'),
                        ('revision','0'*40),('type_id',43),('row_bytes',1),('selection','expert0')]:
        bad=copy.deepcopy(added);bad['fixtures'][0][field]=value
        try:validate_added(original_receipt,bad)
        except ValueError:count+=1
        else:raise AssertionError('altered additional source identity/span accepted')
    for field,value in [('start',1600),('end',1601),('total',1),('etag','wrong'),('status',200)]:
        bad=copy.deepcopy(added);bad['fixtures'][0]['http'][field]=value
        try:validate_added(original_receipt,bad)
        except ValueError:count+=1
        else:raise AssertionError('altered additional HTTP provenance accepted')
    tools,env=environment();env['PATH']=str(EXE.parent)+os.pathsep+env['PATH']
    native=run([EXE,'--shape-selftest'],env)
    shapes=json.loads(native.stdout)
    if shapes!={'quant_rows32_K1_rejected':3,'F32_K1_K2_K3_valid':3,'gpu_context_created':False}:raise AssertionError('native rowshape validation')
    save(BUILD/'native-shape-selftest.json',shapes)
    count+=3
    save(BUILD/'negative-selftest.json',{'passed':count,'native_shapes':shapes,'scope':'missing coverage, output bytes/values, binding and native rowshape rejected; no GPU initialization'})
    print(f'{count} negative cases passed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['acquire','prepare','build','execute','selftest']);p.add_argument('--role',choices=['primary','secondary'],default='primary');a=p.parse_args()
    BUILD.mkdir(parents=True,exist_ok=True)
    if a.mode=='execute':execute(a.role)
    else:globals()[a.mode]()
