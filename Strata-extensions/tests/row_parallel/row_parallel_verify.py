"""Small isolated CPU/build closure. No command runs a GPU executable."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUILD = ROOT / 'build-deepseek-t35/row-parallel'
NAMES = ('row_parallel_fixture.hip', 'row_parallel_contract.json', 'row_parallel_verify.py')

def row(path):
    p = Path(path)
    with p.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return dict(path=str(p.resolve()), bytes=p.stat().st_size, sha256=digest)

def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf8')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

def checked(records):
    for r in records:
        if row(r['path']) != r:
            raise ValueError('closure changed: ' + r['path'])

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def fresh():
    BUILD.mkdir(parents=True, exist_ok=True)
    n = 1
    while (BUILD / f'attempt-{n}').exists():
        n += 1
    p = BUILD / f'attempt-{n}'
    p.mkdir()
    return p

def raw_values(q, kind, rows, k):
    if kind == 0:
        return ((np.arange(rows*k, dtype=np.int32) % 31 - 15) / 16).astype('<f4').tobytes()
    width = q.BLOCKS[kind][1]
    blocks = rows*k//32
    d = np.empty((blocks, width), np.uint8)
    for b in range(blocks):
        if kind == 8:
            d[b,:2] = np.frombuffer(np.array([.5,-1.,2.,2.**-14][b%4], dtype='<f2').tobytes(), np.uint8)
            d[b,2:] = (np.arange(32, dtype=np.uint16)*7+(b*3)%256).astype(np.uint8)
        else:
            d[b,0] = 120+b%12
            d[b,1:] = (np.arange(width-1, dtype=np.uint16)*11+(b*3)%256).astype(np.uint8)
            if kind == 43:
                d[b,1:][(d[b,1:] & 127) == 127] = 126
    return d.tobytes()

def ordered(q, w, x):
    if np.isfinite(w).all() and np.isfinite(x).all():
        try:
            return q.ordered(w, x)
        except ValueError:
            pass
    out = np.zeros((len(x), len(w)), np.float32)
    with np.errstate(all='ignore'):
        for b in range(len(x)):
            for j in range(w.shape[1]):
                product = np.multiply(w[:,j], x[b,j], dtype=np.float32)
                out[b] = np.add(out[b], product, dtype=np.float32)
    return out

def compare(a, b):
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    if a.shape != b.shape or not np.array_equal(np.isnan(a), np.isnan(b)):
        raise ValueError('Q shape/NaN class')
    mask = ~np.isnan(b)
    if not np.array_equal(a.view(np.uint32)[mask], b.view(np.uint32)[mask]):
        raise ValueError('Q non-NaN bits')

def two_mapping(rows, batch):
    pairs = (rows+1)//2
    result = []
    for i in range(pairs*batch):
        b, pair = divmod(i, pairs)
        r = pair*2
        result.append((b,r))
        if r+1 < rows:
            result.append((b,r+1))
    return result

def validate_mapping(mapping, rows, batch):
    expected = {(b,r) for b in range(batch) for r in range(rows)}
    if len(mapping) != rows*batch or set(mapping) != expected:
        raise ValueError('row/batch ownership')

def two_cpu(w, x):
    # Models the candidate's two distinct row lanes and shared x, independently
    # from the Q cumulative-sum implementation; no native candidate is loaded.
    rows, k = w.shape
    out = np.empty((len(x),rows),np.float32)
    with np.errstate(all='ignore'):
        for b in range(len(x)):
            acc0 = np.zeros((rows+1)//2,np.float32)
            acc1 = np.zeros(rows//2,np.float32)
            for first in range(0,k,32):
                for lane in range(min(32,k-first)):
                    j = first+lane
                    activation = x[b,j]
                    p0 = np.multiply(w[::2,j], activation, dtype=np.float32)
                    acc0 = np.add(acc0,p0,dtype=np.float32)
                    p1 = np.multiply(w[1::2,j], activation, dtype=np.float32)
                    acc1 = np.add(acc1,p1,dtype=np.float32)
            out[b,::2],out[b,1::2] = acc0,acc1
    return out

def grouped_mapping(rows,batch,g,wave):
    if g not in (8,32) or wave not in (32,64) or wave%g:
        raise ValueError('subgroup width')
    groups_per_block=256//g
    blocks=(rows*batch+groups_per_block-1)//groups_per_block
    emitted=[];dummy_lanes=0
    for block in range(blocks):
        for physical_wave in range(0,256,wave):
            for subgroup in range(0,wave,g):
                tid=physical_wave+subgroup
                logical=block*groups_per_block+tid//g
                # Every subgroup source remains in this physical wave. All
                # lanes (including invalid groups) execute the same gathers.
                for source in range(g):
                    if (tid+source)//wave!=tid//wave:raise ValueError('cross-wave source')
                if logical<rows*batch:emitted.append(divmod(logical,rows))
                else:dummy_lanes+=g
    validate_mapping(emitted,rows,batch)
    return dict(g=g,wave=wave,blocks=blocks,dummy_lanes=dummy_lanes)

def gather_order(g):
    return [q*g+source for q in range(32//g) for source in range(g)]

def validate_order(order):
    if order!=list(range(32)):raise ValueError('nonascending/missing K product')

def grouped_cpu(w,x,g):
    rows,k=w.shape
    out=np.empty((len(x),rows),np.float32)
    with np.errstate(all='ignore'):
        for b in range(len(x)):
            acc=np.zeros(rows,np.float32)
            for first in range(0,k,32):
                # Build products by lane distribution first; consume by one
                # scalar dependency chain per row, q then source, no sums.
                n=min(32,k-first);products=np.empty((rows,n),np.float32)
                for lane in range(g):
                    offsets=np.arange(lane,n,g)
                    products[:,offsets]=np.multiply(w[:,first+offsets],x[b,first+offsets],dtype=np.float32)
                for source in gather_order(g):
                    if source<n:acc=np.add(acc,products[:,source],dtype=np.float32)
            out[b]=acc
    return out

def prepare():
    folder = fresh()
    source = folder/'source'
    (source/'baseline').mkdir(parents=True)
    (folder/'input').mkdir()
    c = read(HERE/NAMES[1])
    if row(ROOT/c['parent_report']['path'])['sha256']!=c['parent_report']['sha256']:
        raise ValueError('immutable two-row parent report changed')
    origin = ROOT/'Strata-extensions/native/quant'
    if row(origin/'quant.hip')['sha256'] != c['accepted_quant_sha256']:
        raise ValueError('accepted block32 baseline changed')
    sources=[]
    pairs=[(origin/n,source/'baseline'/n) for n in ('quant.hip','quant.hpp')]
    pairs += [(HERE/n,source/n) for n in NAMES]
    pairs += [(HERE.parent/'quant'/n,source/n) for n in ('q_reference.py','build_verify.py')]
    for src,dst in pairs:
        before=row(src);shutil.copyfile(src,dst)
        if row(src)!=before or row(dst)['sha256']!=before['sha256']:
            raise ValueError('snapshot copy changed')
        sources.append(dict(original=before,snapshot=row(dst)))
    q=module('row_parallel_Q',source/'q_reference.py')
    jobs=[];files=[]
    def add(name,kind,rows,k,batch,stride,raw=None,x=None):
        if not 0<rows<=1713 or not 0<k<=5120 or batch not in (1,2,4,8) or not rows<=stride<=rows+3 or kind not in q.BLOCKS or kind and k%32:
            raise ValueError('bounded input shape')
        raw=raw_values(q,kind,rows,k) if raw is None else raw
        if len(raw)!=rows*k//q.BLOCKS[kind][0]*q.BLOCKS[kind][1]:
            raise ValueError('packed bytes')
        x=((np.arange(batch*k,dtype=np.int32)%23-11)/32).astype('<f4').reshape(batch,k) if x is None else np.asarray(x,dtype='<f4').reshape(batch,k)
        w=q.decode(kind,raw).reshape(rows,k)
        expected=ordered(q,w,x)
        paths=[folder/'input'/(name+suffix) for suffix in ('.raw','.x','.Q')]
        for p,data in zip(paths,(raw,x.tobytes(),expected.astype('<f4').tobytes())):
            p.write_bytes(data);files.append(row(p))
        jobs.append(dict(name=name,type=kind,rows=rows,k=k,batch=batch,stride=stride,raw=row(paths[0]),input=row(paths[1]),Q=row(paths[2])))
    for kind in c['types']:
        for n,shape in enumerate(c['shapes']):
            add(f't{kind}-s{n}',kind,*shape)
    for n,shape in enumerate(c['type39_large_shapes']):
        add(f't39-large{n}',39,*shape)
    for case in q.boundaries():
        add('boundary-'+case['name'],0,1,case['weights'].shape[1],1,4,case['weights'].astype('<f4').tobytes(),case['inputs'])
    for kind,scales in ((8,[0,1,0x8000,0x3c00,0x7bff,0x7c00,0x7e00,0xfc00]),(39,[0,1,126,127,128,253,254,255]),(43,[0,1,126,127,128,253,254,255])):
        width=q.BLOCKS[kind][1];raw=bytearray(raw_values(q,kind,len(scales),32))
        for r,s in enumerate(scales):
            raw[r*width]=s&255
            if kind==8:raw[r*width+1]=s>>8
        if kind==43:raw[1]=127;raw[2]=255  # both FP8 NaN signs
        add(f't{kind}-special',kind,len(scales),32,2,len(scales)+3,bytes(raw),np.tile(np.array([1,-1,.5,-.5]*8,np.float32),2))
    tsv=folder/'jobs.tsv'
    tsv.write_text(''.join('\t'.join(map(str,[j['name'],j['type'],j['rows'],j['k'],j['batch'],j['stride'],j['raw']['path'],j['input']['path']]))+'\n' for j in jobs),encoding='utf8')
    payload=sum(r['bytes'] for r in files)
    if payload>c['maximum_generated_payload_bytes']:
        raise ValueError('input payload budget')
    checked([s['original'] for s in sources])
    proof=dict(schema='T35-row-parallel-input/v2',parent_report=row(ROOT/c['parent_report']['path']),sources=sources,files=files,tsv=row(tsv),jobs=jobs,payload_bytes=payload,original_model_read_bytes=0,GPU=False)
    save(folder/'input.json',proof)
    print(json.dumps(row(folder/'input.json')))

def closure(folder):
    folder=Path(folder).resolve();m=read(folder/'input.json')
    checked([s['snapshot'] for s in m['sources']]+m['files']+[m['tsv'],m['parent_report']])
    return folder,m

def cpu(folder):
    folder,m=closure(folder);q=module('row_parallel_frozen_Q',folder/'source/q_reference.py')
    # Reduction before NumPy uint16 addition avoids NumPy2's strict scalar
    # overflow while preserving the original final-byte modulo, not clipping.
    seed_cases=[]
    for b in list(range(32))+[21845,21846,123359]:
        for width,factor in ((16,11),(32,11),(32,7)):
            narrow=(np.arange(width,dtype=np.uint16)*factor+(b*3)%256).astype(np.uint8)
            wide=(np.arange(width,dtype=np.uint64)*factor+b*3).astype(np.uint8)
            if not np.array_equal(narrow,wide):raise ValueError('synthetic modulo changed')
            seed_cases.append([b,width,factor])
    results=[]
    for j in m['jobs']:
        r,k,b=j['rows'],j['k'],j['batch']
        validate_mapping(two_mapping(r,b),r,b)
        w=q.decode(j['type'],Path(j['raw']['path']).read_bytes()).reshape(r,k)
        x=np.frombuffer(Path(j['input']['path']).read_bytes(),'<f4').reshape(b,k)
        expected=np.frombuffer(Path(j['Q']['path']).read_bytes(),'<f4').reshape(b,r)
        compare(ordered(q,w,x),expected);compare(two_cpu(w,x),expected)
        mapping=[]
        for g in (8,32):
            validate_order(gather_order(g))
            for wave in (32,64):mapping.append(grouped_mapping(r,b,g,wave))
            # Native type0 explicitly falls back to baseline; its existing
            # small numeric boundaries still exercise this ordered CPU model.
            compare(grouped_cpu(w,x,g),expected)
        results.append(dict(name=j['name'],rows_once=True,independent_Q=True,two_row_CPU=True,grouped_CPU=[8,32],mapping=mapping,values=r*b))
    negatives=[]
    def reject(name,func):
        try:func()
        except (ValueError,AssertionError):negatives.append(name);return
        raise AssertionError('negative accepted: '+name)
    reject('drop-odd-tail',lambda:validate_mapping(two_mapping(17,2)[:-1],17,2))
    reject('duplicate-row',lambda:validate_mapping(two_mapping(3,2)+[(0,0)],3,2))
    wrong=two_mapping(3,2);wrong[-1]=(0,2)
    reject('cross-batch-alias',lambda:validate_mapping(wrong,3,2))
    reject('changed-finite-output',lambda:compare(np.array([1],np.float32),np.array([2],np.float32)))
    reject('changed-signed-zero',lambda:compare(np.array([-0.],np.float32),np.array([0.],np.float32)))
    reject('changed-NaN-class',lambda:compare(np.array([0.],np.float32),np.array([np.nan],np.float32)))
    reject('partial-native-block',lambda:q.decode(39,b'\0'*16))
    boundary=next(c for c in q.boundaries() if c['name']=='ordered')
    answer=q.ordered(boundary['weights'],boundary['inputs'])
    # A split/tree order (a+c)+b must differ from ascending fullK.
    w=boundary['weights'][0];split=np.array([[np.float32(np.float32(w[0]+w[2])+w[1])]],np.float32)
    reject('tree-or-partial-sum',lambda:compare(split,answer))
    reject('fused-product-add',lambda:compare(np.array([[-2.**-46]],np.float32),q.ordered(q.boundaries()[0]['weights'],q.boundaries()[0]['inputs'])))
    fake=dict(m['files'][0],sha256='0'*64)
    reject('changed-closure',lambda:checked([fake]))
    reject('wrong-subgroup-width',lambda:grouped_mapping(17,2,16,32))
    reject('unsupported-wave',lambda:grouped_mapping(17,2,32,16))
    reject('reversed-lane-gather',lambda:validate_order(list(reversed(gather_order(8)))))
    reject('lane-major-gather',lambda:validate_order([q*8+lane for lane in range(8) for q in range(4)]))
    reject('dropped-product',lambda:validate_order(gather_order(32)[:-1]))
    reject('duplicated-product',lambda:validate_order(gather_order(32)+[31]))
    mock_cases=acquisition_mocks()
    for case in q.boundaries():
        bits=int(q.ordered(case['weights'],case['inputs']).view(np.uint32)[0,0])
        if bits!=case['expected_bits']:raise ValueError('independent boundary bits')
    closure(folder)
    import numpy._core._multiarray_umath as native_numpy
    proof=dict(schema='T35-row-parallel-CPU/v3',input=row(folder/'input.json'),runner=row(__file__),Q=row(folder/'source/q_reference.py'),python=row(sys.executable),numpy_version=np.__version__,numpy_native=row(native_numpy.__file__),jobs=results,negative_cases=negatives,negative_count=len(negatives),boundary_count=len(q.boundaries()),synthetic_modulo_equal_cases=seed_cases,acquisition_mock_cases=mock_cases,GPU=False,native_kernel_executed=False,qualification='CPU mapping wave32/64, Q and acquisition mocks only; HIP parity and performance unrun')
    save(folder/'cpu.json',proof);print(json.dumps(row(folder/'cpu.json')))

def build(folder):
    folder,m=closure(folder)
    if not (folder/'cpu.json').is_file():raise ValueError('CPU proof required')
    cpu_proof=read(folder/'cpu.json')
    checked([cpu_proof['input'],cpu_proof['runner'],cpu_proof['Q']])
    # This existing helper only locates a local compiler environment. Freeze its
    # imported Q, and never invoke its execution/acquisition/build entry points.
    q=module('q_reference',folder/'source/q_reference.py');sys.modules['q_reference']=q
    helper=module('row_parallel_toolchain',folder/'source/build_verify.py')
    helper.BUILD=folder
    tools,env=helper.environment();sdk=helper.SDK
    cmake='cmake_minimum_required(VERSION 3.24)\nproject(t35_rows LANGUAGES CXX HIP)\nfind_package(hip CONFIG REQUIRED)\nadd_executable(t35-rows source/row_parallel_fixture.hip)\ntarget_include_directories(t35-rows PRIVATE source)\nset_target_properties(t35-rows PROPERTIES HIP_STANDARD 17 HIP_STANDARD_REQUIRED YES)\ntarget_compile_options(t35-rows PRIVATE -fno-fast-math -ffp-contract=off -fdenormal-fp-math=ieee -Rpass-analysis=kernel-resource-usage)\ntarget_link_libraries(t35-rows PRIVATE hip::host)\n'
    (folder/'CMakeLists.txt').write_text(cmake,encoding='utf8')
    command=[str(tools['cmake']),'-S',str(folder),'-B',str(folder/'native'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
    commands=[]
    for n,cmd in enumerate((command,[str(tools['cmake']),'--build',str(folder/'native'),'--verbose','--parallel','1'])):
        result=subprocess.run(cmd,env=env,capture_output=True)
        log=folder/f'build-{n}.log';log.write_bytes(result.stdout+result.stderr)
        commands.append(dict(argv=cmd,exit=result.returncode,log=row(log)))
        if result.returncode:
            save(folder/'build-failure.json',dict(commands=commands));raise ValueError('compile failed; see logs')
    exe=folder/'native/t35-rows.exe'
    offload=subprocess.run([str(tools['objdump']),'--offloading',str(exe)],env=env,capture_output=True)
    (folder/'offloading.txt').write_bytes(offload.stdout+offload.stderr)
    if offload.returncode or not all(a.encode() in offload.stdout for a in ('gfx1100','gfx1201')):raise ValueError('both code objects required')
    deps=subprocess.run([str(tools['ninja']),'-C',str(folder/'native'),'-t','deps'],env=env,capture_output=True)
    (folder/'dependencies.txt').write_bytes(deps.stdout+deps.stderr)
    if deps.returncode:raise ValueError('dependencies listing')
    paths=sorted({Path(s.strip()).resolve() for s in deps.stdout.decode('utf8').splitlines() if s.startswith('    ') and Path(s.strip()).is_file()})
    quant={p for p in paths if p.name in ('quant.hip','quant.hpp')}
    allowed={s['snapshot']['path'] for s in m['sources'][:2]}
    if {str(p) for p in quant}!=allowed:raise ValueError('quant dependencies escaped frozen snapshot')
    closure(folder)
    remarks=(folder/'build-1.log').read_text(encoding='utf8',errors='replace')
    resource_lines=[line for line in remarks.splitlines() if any(token in line.lower() for token in ('kernel info','sgpr','vgpr','spill','scratch','lds','occupancy'))]
    save(folder/'compiler-resources.json',dict(source_log=row(folder/'build-1.log'),lines=resource_lines,qualification='compiler remarks only; hardware occupancy not observed',GPU=False))
    proof=dict(schema='T35-row-parallel-build/v2',input=row(folder/'input.json'),CPU=row(folder/'cpu.json'),runner=row(__file__),sources=[s['snapshot'] for s in m['sources']],commands=commands,recipe=row(folder/'CMakeLists.txt'),tools=[row(p) for p in tools.values()],dependencies=[row(p) for p in paths],dependency_listing=row(folder/'dependencies.txt'),offloading=row(folder/'offloading.txt'),compiler_resources=row(folder/'compiler-resources.json'),exe=row(exe),GPU=False,native_kernel_executed=False,qualification='compile only, two architectures; HIP correctness/performance unrun')
    save(folder/'build.json',proof);print(json.dumps(row(folder/'build.json')))

def analyze(folder,output):
    # Offline only: consume previously captured files, never launch native code.
    folder,m=closure(folder);output=Path(output);results=[]
    for j in m['jobs']:
        r,b,s=j['rows'],j['batch'],j['stride']
        a=np.frombuffer((output/(j['name']+'.baseline.bin')).read_bytes(),'<u4').reshape(b,s)
        expected=np.frombuffer(Path(j['Q']['path']).read_bytes(),'<f4').reshape(b,r)
        for arm in ('two-row','g8','g32'):
            z=np.frombuffer((output/(j['name']+'.'+arm+'.bin')).read_bytes(),'<u4').reshape(b,s)
            if not np.array_equal(a,z) or not np.all(z[:,r:]==0xa5a5a5a5):raise ValueError('native exact bits/padding')
            compare(z[:,:r].copy().view('<f4'),expected)
        results.append(j['name'])
    return dict(offline_jobs=results,qualification='files only; capture provenance separately required')

DLL_NAMES=('amdhip64_7.dll','amd_comgr.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')
ENV_KEYS=('SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PATH','TMP','TEMP','HIP_PATH','ROCM_PATH','HIP_PLATFORM','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES','GPU_DEVICE_ORDINAL')
PARENT=BUILD/'attempt-6'
REPAIR_PLAN=BUILD/'runtime-closure-repair-plan-r1.md'
REPAIR_PLAN_SHA='2118625b4970d9c806acf1fd913abe4947dbb290edda1d38d81c7fe4a6ae4b87'
OLD_NINE=(
 ('source/row_parallel_verify.py','4266309df23c8a807eeb6d159d345cd36971d597a7324952c7a3a82778ec1b74'),
 ('native/t35-rows.exe','6343288d49f87820d95bc42c4b05f829111dac0a5621c9b669e088abdfd887cc'),
 ('build.json','cc477a0e8d57527f8e2b1622d6128059b37a5214cd911e75a1bec1c1d2da59a5'),
 ('input.json','6b4d4747c173a193851fdd62ea3150243a5813193efe49fad3342ae7a710760b'),
 ('cpu.json','d768dfc412ee04919aa5c62ed293df0ffcbac8f016699a95ea15a95cd481de95'),
 ('gpu-seal-1/seal.json','00a8e12177ca56670134ec7b194c5571c8d9957ee0cce03b9b04d4b902078df6'),
 ('gpu-seal-1/acquisition.json','32b2bd64e9f5ed1e824d658b3f8fa0e8bd73f36f06368675da22038c487950f4'),
 ('gpu-seal-1/diagnostic-r4.json','c44d8ce6ae46e0d6d08f0d7af1f62cba2e1201f03ccba775aae108b2111ec04a'),
 ('gpu-seal-1/common-DLL-evidence-index.json','555d77d3562877ecf6f3a7e47f9c5d10d08886ad52f2c7cebd92bd414d4cba4a'))

def immutable_parent():
    records=[]
    for relative,expected in OLD_NINE:
        record=row(PARENT/relative)
        if record['sha256']!=expected:raise ValueError('immutable parent changed: '+relative)
        records.append(record)
    if row(REPAIR_PLAN)['sha256']!=REPAIR_PLAN_SHA:raise ValueError('accepted repair plan changed')
    return records

def validate_runtime_bundle(bundle):
    import re
    if not isinstance(bundle,dict) or bundle.get('schema')!='T35-row-runtime-bundle/v1':raise ValueError('runtime bundle schema')
    for field in ('selection_provenance','prediction_limits'):
        if not isinstance(bundle.get(field),str) or not bundle[field].strip():raise ValueError('runtime expectation provenance/limits')
    members=bundle.get('members')
    if not isinstance(members,list) or len(members)!=len(DLL_NAMES) or any(not isinstance(r,dict) for r in members) or {r.get('name') for r in members}!=set(DLL_NAMES):raise ValueError('explicit five runtime members required')
    for r in members:
        if not isinstance(r.get('path'),str) or not Path(r['path']).is_absolute() or Path(r['path']).name.lower()!=r['name']:raise ValueError('absolute named runtime file required')
        if type(r.get('bytes'))is not int or r['bytes']<=0 or not isinstance(r.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',r['sha256']):raise ValueError('runtime file size/SHA')
        if type(r.get('required_loaded'))is not bool or r['required_loaded']!=(r['name']=='amdhip64_7.dll'):raise ValueError('required HIP/optional policy')
    environment=bundle.get('child_environment')
    if not isinstance(environment,dict) or any(not isinstance(k,str) or not isinstance(v,str) or k.upper() not in ENV_KEYS or '\x00' in k+v for k,v in environment.items()):raise ValueError('trial child environment whitelist')
    if len({k.upper() for k in environment})!=len(environment):raise ValueError('ambiguous environment key case')
    return bundle

def runtime_environment(bundle):
    validate_runtime_bundle(bundle)
    return dict(bundle['child_environment'])

def runtime_rows(bundle):
    return [dict(path=str(Path(r['path']).resolve()),bytes=r['bytes'],sha256=r['sha256']) for r in bundle['members']]

def require_fresh_acquisition(directory,output):
    if Path(output).exists() or (Path(directory)/'acquisition.json').exists() or (Path(directory)/'observation.json').exists():raise ValueError('fresh acquisition only')

def persist_observation(stdout,directory):
    """Store emitted metadata before any schema/device/runtime acceptance."""
    observation=dict(schema='T35-row-parallel-observation/v1',raw_stdout_sha256=hashlib.sha256(stdout).hexdigest(),raw_stdout_bytes=len(stdout),status='unobserved_no_complete_summary',observed_device=None,observed_modules=None,provided_device_fields=[],file_observations=[],parse_error=None,accepted=False)
    captured=None
    try:
        captured=json.loads(stdout.decode('utf8'))
        if not isinstance(captured,dict):raise ValueError('native summary is not an object')
    except (ValueError,UnicodeError) as error:
        observation['parse_error']=dict(type=type(error).__name__,message=str(error))
    else:
        fields=('device','pci','architecture','device_name','warp_size')
        observation.update(status='observed_unaccepted',observed_device={k:captured[k] for k in fields if k in captured},provided_device_fields=[k for k in fields if k in captured],observed_modules=captured.get('modules'),modules_field_provided='modules' in captured)
        if isinstance(captured.get('modules'),list):
            for entry in captured['modules']:
                record=dict(raw=entry,file=None,error=None)
                if isinstance(entry,dict) and isinstance(entry.get('path'),str):
                    try:record['file']=row(entry['path'])
                    except (OSError,ValueError) as error:record['error']=dict(type=type(error).__name__,message=str(error))
                observation['file_observations'].append(record)
    # Exclusive creation prevents even this new path from overwriting history.
    with (Path(directory)/'observation.json').open('x',encoding='utf8') as stream:
        stream.write(json.dumps(observation,indent=2,allow_nan=False)+'\n')
    return observation

def timer(value):
    valid=type(value) in (int,float) and math.isfinite(value) and value>=0
    # repr preserves invalid numeric diagnostics while keeping JSON standard.
    return dict(raw=value if isinstance(value,str) or type(value) in (int,float) and math.isfinite(value) else repr(value),value=value if valid else None,status='observed_nonnegative' if valid else 'invalid')

def validate_seal_digest(actual,expected):
    if not expected or actual!=expected:raise ValueError('externally approved seal SHA mismatch')

def device_match(actual,expected):
    if actual.get('pci')!=expected['pci'] or actual.get('architecture','').split(':')[0]!=expected['architecture']:
        raise ValueError('actual selected device identity')
    if actual.get('warp_size') not in (32,64) or not actual.get('device_name'):
        raise ValueError('actual device description')

def validate_command(seal):
    expected=[seal['exe']['path'],seal['expected_device']['pci'],seal['input_tsv']['path'],seal['output_directory']]
    if seal['command']!=expected or seal['expected_device']['architecture'] not in ('gfx1100','gfx1201'):
        raise ValueError('sealed command/device selection')
    if seal.get('schema')=='T35-row-parallel-preG/v2' and seal['environment']!=runtime_environment(seal['runtime_expected_bundle']):raise ValueError('sealed trial environment differs from explicit bundle')

def validate_completion(value,jobs):
    expected=dict(checked_buffer_releases=jobs*4,checked_event_destroys=jobs*24,kernel_launch_calls=jobs*64)
    if any(type(value.get(k)) is not int or value[k]!=v for k,v in expected.items()):raise ValueError('explicit checked HIP cleanup/call counts')
    return expected

def validate_modules(observed,manifest,fingerprint=row):
    if 'runtime_expected_bundle' in manifest:
        validate_runtime_bundle(manifest['runtime_expected_bundle'])
        declared={r['name']:r for r in manifest['runtime_expected_bundle']['members']}
        required={r['name'] for r in declared.values() if r['required_loaded']}
    else:
        # Historical v1 validation/readback only; new execution requires v2.
        declared={Path(r['path']).name.lower():r for r in manifest['configured_DLLs']}
        required=set(manifest['required_loaded_DLLs'])
    if not isinstance(observed,list) or len(observed)!=len(DLL_NAMES) or {v.get('name') for v in observed}!=set(DLL_NAMES):raise ValueError('observed DLL set')
    modules=[]
    for entry in observed:
        name,path=entry['name'],entry['path']
        if path is None:
            if name in required:raise ValueError('required HIP DLL unobserved')
            modules.append(dict(name=name,observed=None));continue
        actual=fingerprint(path);expected=declared[name]
        if actual['sha256']!=expected['sha256'] or actual['bytes']!=expected['bytes'] or os.path.normcase(actual['path'])!=os.path.normcase(expected['path']):raise ValueError('loaded DLL does not match configured source')
        modules.append(dict(name=name,observed=actual))
    return modules

def original_birth(process):
    # Query the original open process handle, never reopen by a recyclable PID.
    import ctypes
    from ctypes import wintypes
    creation,exit_time,kernel,user=(wintypes.FILETIME() for _ in range(4))
    api=ctypes.WinDLL('kernel32',use_last_error=True).GetProcessTimes
    api.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    api.restype=wintypes.BOOL
    if not api(wintypes.HANDLE(int(process._handle)),*[ctypes.byref(x) for x in (creation,exit_time,kernel,user)]):
        raise OSError(ctypes.get_last_error(),'GetProcessTimes original handle')
    return (creation.dwHighDateTime<<32)|creation.dwLowDateTime

def communicate_owned(process):
    # On an interruption only this child is terminated through its own handle.
    # No PID lookup, process-tree discovery, runtime owner or foreign kill.
    interrupted=None
    try:
        stdout,stderr=process.communicate()
    except BaseException as error:
        interrupted=type(error).__name__
        if process.poll() is None:process.terminate()
        stdout,stderr=process.communicate()
    finally:
        if process.returncode is None:process.wait()
        process._handle.Close()
    return stdout,stderr,dict(exit=process.returncode,waited=True,original_handle_closed=bool(process._handle.closed),interrupted=interrupted)

def acquisition_mocks():
    cases=[]
    def reject(name,call):
        try:call()
        except ValueError:cases.append(name);return
        raise AssertionError('acquisition mock accepted '+name)
    example=dict(exe=dict(path='fixture.exe'),expected_device=dict(pci='0000:07:00.0',architecture='gfx1201'),input_tsv=dict(path='jobs.tsv'),output_directory='output',command=['fixture.exe','0000:07:00.0','jobs.tsv','output'])
    validate_command(example);cases.append('exact-command')
    bad=dict(example,command=['fixture.exe','0000:07:00.0','other.tsv','output'])
    reject('changed-command',lambda:validate_command(bad))
    bad=dict(example,expected_device=dict(pci='0000:03:00.0',architecture='gfx1201'))
    reject('changed-selected-PCI',lambda:validate_command(bad))
    good=dict(pci='0000:07:00.0',architecture='gfx1201:sramecc-',warp_size=32,device_name='mock')
    device_match(good,example['expected_device']);cases.append('device-suffix-match')
    reject('actual-device-mismatch',lambda:device_match(dict(good,pci='0000:03:00.0'),example['expected_device']))
    reject('actual-arch-mismatch',lambda:device_match(dict(good,architecture='gfx1100'),example['expected_device']))
    validate_seal_digest('a'*64,'a'*64);cases.append('external-seal-SHA-match')
    reject('seal-tamper',lambda:validate_seal_digest('b'*64,'a'*64))
    reject('seal-SHA-required',lambda:validate_seal_digest('a'*64,None))
    mock_dlls=[dict(path=name,bytes=1,sha256='a'*64) for name in DLL_NAMES]
    dll_manifest=dict(configured_DLLs=mock_dlls,required_loaded_DLLs=['amdhip64_7.dll'])
    observed=[dict(name=name,path=name if n==0 else None) for n,name in enumerate(DLL_NAMES)]
    fingerprint=lambda path:next(r for r in mock_dlls if r['path']==path)
    validated=validate_modules(observed,dll_manifest,fingerprint)
    if any(v['observed'] is not None for v in validated[1:]):raise AssertionError('optional DLL inferred loaded')
    cases.append('unused-optional-DLLs-null')
    missing=[dict(v,path=None) for v in observed]
    reject('required-HIP-DLL-null',lambda:validate_modules(missing,dll_manifest,fingerprint))
    reject('changed-loaded-DLL',lambda:validate_modules(observed,dll_manifest,lambda path:dict(fingerprint(path),sha256='b'*64)))
    completion=dict(checked_buffer_releases=4,checked_event_destroys=24,kernel_launch_calls=64)
    validate_completion(completion,1);cases.append('explicit-HIP-release-success')
    reject('HIP-buffer-release-failure',lambda:validate_completion(dict(completion,checked_buffer_releases=3),1))
    reject('HIP-event-release-failure',lambda:validate_completion(dict(completion,checked_event_destroys=23),1))
    reject('exit-alone-not-HIP-cleanup',lambda:validate_completion({},1))
    for value in (-.01,float('nan'),float('inf'),'nan','+inf','-inf'):
        result=timer(value)
        if result['status']!='invalid' or result['value'] is not None:raise AssertionError('invalid timer')
    cases.append('invalid-timers-preserved-no-gate')
    if timer(0.)['value']!=0.:raise AssertionError('zero timer')
    cases.append('zero-timer-valid')
    class Handle:
        closed=False
        def Close(self):self.closed=True
    class Process:
        def __init__(self,interrupt=False):self._handle=Handle();self.returncode=None;self.interrupt=interrupt;self.terminated=False
        def communicate(self):
            if self.interrupt:self.interrupt=False;raise KeyboardInterrupt()
            self.returncode=-1 if self.terminated else 0;return b'raw stdout',b'raw stderr'
        def poll(self):return self.returncode
        def terminate(self):self.terminated=True
        def wait(self):self.returncode=0
    for interrupted in (False,True):
        process=Process(interrupted);out,err,result=communicate_owned(process)
        if not result['waited'] or not result['original_handle_closed'] or process.terminated!=interrupted or out!=b'raw stdout':raise AssertionError('original handle cleanup')
        cases.append('interrupted-own-child-cleanup' if interrupted else 'fast-exit-original-handle-close')
    return cases

def seal_execution(folder,pci,architecture,bundle_path,controller_proof_path):
    # This command hashes local files only. It does not query a device or spawn
    # the fixture; a separate coordinator resource window authorizes execute.
    import re
    if not bundle_path or not controller_proof_path:raise ValueError('explicit runtime bundle and controller CPU proof required')
    if not re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]',pci):raise ValueError('exact PCI syntax')
    if architecture not in ('gfx1100','gfx1201'):raise ValueError('architecture')
    if Path(folder).resolve()!=PARENT.resolve():raise ValueError('fixed accepted parent required for this repair')
    old_parent=immutable_parent()
    folder,m=closure(folder);build_proof=read(folder/'build.json')
    checked([build_proof['input'],build_proof['CPU'],build_proof['exe'],build_proof['compiler_resources']]+build_proof['sources'])
    bundle_record=row(bundle_path);bundle=validate_runtime_bundle(read(bundle_path))
    checked(runtime_rows(bundle))
    proof_record=row(controller_proof_path);proof=read(controller_proof_path)
    if proof.get('passed')is not True or proof.get('GPU')is not False or proof.get('native_executed')is not False or proof.get('controller')!=row(__file__) or proof.get('contract')!=row(HERE/'row_parallel_contract.json'):raise ValueError('latest controller CPU proof identity')
    checked(proof['old_parent_after'])
    env=runtime_environment(bundle)
    n=1
    while (BUILD/f'runtime-closure-repair-seal-{n}').exists():n+=1
    destination=BUILD/f'runtime-closure-repair-seal-{n}';destination.mkdir()
    code=[row(folder/'native'/('t35-rows.exe.0.hip-amdgcn-amd-amdhsa--'+a)) for a in ('gfx1100','gfx1201')]
    cpu_proof=read(folder/'cpu.json')
    records=[row(folder/n) for n in ('input.json','cpu.json','build.json','compiler-resources.json','offloading.txt')]+[row(__file__),row(HERE/'row_parallel_contract.json'),row(sys.executable),cpu_proof['numpy_native'],bundle_record,proof_record]+code+runtime_rows(bundle)+old_parent
    sdk_reference=read(PARENT/'gpu-seal-1/seal.json')['configured_DLLs']
    provenance=dict(native_build=row(folder/'build.json'),accepted_parent_EXE=build_proof['exe'],sdk_reference_DLLs=sdk_reference,sdk_reference_provenance=row(PARENT/'gpu-seal-1/seal.json'),qualification='Archived SDK reference rows, not a runtime selection or assertion DLLs were compiler-consumed; actual import-library dependencies remain in build proof')
    manifest=dict(schema='T35-row-parallel-preG/v2',attempt=str(folder),records=records,build_provenance=provenance,runtime_bundle_input=bundle_record,runtime_expected_bundle=bundle,controller_CPU_proof=proof_record,exe=build_proof['exe'],input_tsv=m['tsv'],expected_device=dict(pci=pci,architecture=architecture),required_loaded_DLLs=['amdhip64_7.dll'],optional_DLLs=list(DLL_NAMES[1:]),interpreter=row(sys.executable),controller=row(__file__),environment=env,absent_environment_keys=[key for key in ENV_KEYS if key not in {k.upper() for k in env}],output_directory=str(destination/'output'),command=[build_proof['exe']['path'],pci,m['tsv']['path'],str(destination/'output')],GPU_executed=False,window_authorization='separate coordinator approval required; seal is not authorization',timeout=None)
    validate_command(manifest);checked(records);save(destination/'seal.json',manifest)
    print(json.dumps(row(destination/'seal.json')))

def validate_capture(value,manifest,input_manifest):
    if not isinstance(value,dict):raise ValueError('native summary object required')
    device_match(value,manifest['expected_device'])
    if value.get('schema')!='T35-row-parallel-G/v3' or value.get('model_generation') is not False:raise ValueError('capture schema')
    modules=validate_modules(value.get('modules'),manifest)
    jobs=value.get('jobs')
    if not isinstance(jobs,list) or [j.get('name') for j in jobs]!=[j['name'] for j in input_manifest['jobs']]:raise ValueError('actual ordered job set')
    timings=[]
    for job in jobs:
        candidates=job.get('candidates',[])
        if [c.get('arm') for c in candidates]!=['two-row','g8','g32']:raise ValueError('actual candidate set')
        for candidate in candidates:
            arms=candidate.get('envelopes',[])
            if candidate.get('exact_bits') is not True or [a.get('arm') for a in arms]!=list('ABBA') or any(a.get('launches')!=5 for a in arms):raise ValueError('actual event/call structure')
            timings.append(dict(job=job['name'],candidate=candidate['arm'],arms=[dict(arm=a['arm'],launches=5,event_ms=timer(a.get('raw_event_ms')),host_seconds=timer(a.get('host_seconds'))) for a in arms]))
    completion=validate_completion(value,len(input_manifest['jobs']))
    return dict(device={k:value[k] for k in ('device','pci','architecture','device_name','warp_size')},modules=modules,timings=timings,completion=completion)

def collect_owned_process(command,cwd,environment,process_factory=subprocess.Popen,birth_reader=original_birth):
    """Small injectable acquisition boundary for CPU cleanup regressions."""
    process=None;stdout=b'';stderr=b'';failure=None;metadata=None
    try:
        process=process_factory(command,cwd=cwd,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        metadata=dict(pid=process.pid,original_handle=int(process._handle),creation_FILETIME=None)
        metadata['creation_FILETIME']=birth_reader(process)
        stdout,stderr,cleanup=communicate_owned(process);metadata.update(cleanup)
    except BaseException as error:
        failure=error
    finally:
        if process is not None and not process._handle.closed:
            if process.poll() is None:process.terminate()
            stdout,stderr,cleanup=communicate_owned(process)
            metadata.update(cleanup)
    return stdout,stderr,metadata,failure

def execute(seal_path,expected_seal_sha):
    # Only a separately approved window may invoke this explicit entry point.
    seal_path=Path(seal_path).resolve();validate_seal_digest(row(seal_path)['sha256'],expected_seal_sha);manifest=read(seal_path)
    if manifest.get('schema')!='T35-row-parallel-preG/v2':raise ValueError('explicit-runtime repair seal v2 required; historical records are not migrated')
    validate_command(manifest);checked(manifest['records']+[manifest['exe'],manifest['input_tsv'],manifest['interpreter'],manifest['controller']])
    if row(__file__)!=manifest['controller'] or row(sys.executable)!=manifest['interpreter']:raise ValueError('controller/interpreter identity')
    if Path(manifest['attempt']).resolve()!=PARENT.resolve():raise ValueError('fixed accepted parent required')
    directory=seal_path.parent;output=Path(manifest['output_directory'])
    if directory.parent!=BUILD.resolve() or not directory.name.startswith('runtime-closure-repair-seal-') or output.resolve()!=directory/'output':raise ValueError('new isolated repair acquisition directory required')
    folder,m=closure(manifest['attempt']);immutable_parent();require_fresh_acquisition(directory,output)
    acquisition=dict(schema='T35-row-parallel-acquisition/v2',seal=row(seal_path),GPU_attempted=False,complete=False,process=None,validation=None,observed_device=None,observed_modules=None,observation_status='unobserved_no_complete_summary')
    stdout,stderr,metadata,failure=collect_owned_process(manifest['command'],folder/'native',manifest['environment'])
    acquisition['process']=metadata;acquisition['GPU_attempted']=metadata is not None
    (directory/'stdout.bin').write_bytes(stdout);(directory/'stderr.bin').write_bytes(stderr)
    acquisition['stdout']=row(directory/'stdout.bin');acquisition['stderr']=row(directory/'stderr.bin')
    try:
        # This happens for complete nonzero-exit/birth-failure summaries too.
        observation=persist_observation(stdout,directory)
        acquisition.update(observed_device=observation['observed_device'],observed_modules=observation['observed_modules'],observation_status=observation['status'],observation_record=row(directory/'observation.json'))
        if failure is not None:raise failure
        if metadata is None or metadata['interrupted'] or metadata['exit']!=0:raise ValueError('fixture interrupted/nonzero exit')
        if observation['status']!='observed_unaccepted':raise ValueError('native complete summary unobserved')
        captured=json.loads(stdout.decode('utf8'))
        acquisition['validation']=validate_capture(captured,manifest,m)
        acquisition['outputs']=analyze(folder,output)
        acquisition['output_files']=[row(p) for p in sorted(output.glob('*.bin'))]
        checked(manifest['records']);closure(folder);immutable_parent()
        acquisition['observation_status']='observed_accepted';acquisition['complete']=True
    except BaseException as error:
        failure=error;acquisition['failure']=dict(type=type(error).__name__,message=str(error))
    save(directory/'acquisition.json',acquisition)
    print(json.dumps(row(seal_path.parent/'acquisition.json')))
    if failure is not None:raise failure

def runtime_repair_mocks(destination):
    """CPU RED/GREEN cases; no subprocess, native process or device query."""
    cases=[]
    runtime=destination/'mock-runtime';runtime.mkdir()
    members=[]
    for name in DLL_NAMES:
        path=runtime/name;path.write_bytes(('mock-runtime:'+name).encode())
        members.append(dict(name=name,**row(path),required_loaded=name=='amdhip64_7.dll'))
    bundle=dict(schema='T35-row-runtime-bundle/v1',selection_provenance='CPU MOCK ONLY, not a selected device runtime',members=members,child_environment={'SYSTEMROOT':'C:\\Windows','PATH':'mock-child-path','TMP':str(destination),'TEMP':str(destination),'HIP_PLATFORM':'amd'},prediction_limits='Mock expected files; no actual process observation')
    validate_runtime_bundle(bundle)
    cases.append('explicit-runtime-bundle-valid')
    configured=[dict(path=str(destination/'other-build-source'/r['name']),bytes=999,sha256='b'*64) for r in members]
    observed=[dict(name=r['name'],path=r['path'] if r['required_loaded'] else None) for r in members]
    manifest=dict(runtime_expected_bundle=bundle,build_provenance=dict(sdk_reference_DLLs=configured),required_loaded_DLLs=['amdhip64_7.dll'],expected_device=dict(pci='0000:07:00.0',architecture='gfx1201'))
    validate_modules(observed,manifest);cases.append('explicit-build-runtime-difference-legitimate')
    def reject(name,call):
        try:call()
        except (ValueError,OSError):cases.append(name);return
        raise AssertionError('runtime repair negative accepted: '+name)
    reject('runtime-file-wrong-SHA',lambda:validate_modules(observed,manifest,lambda path:dict(row(path),sha256='b'*64)))
    reject('runtime-file-wrong-size',lambda:validate_modules(observed,manifest,lambda path:dict(row(path),bytes=1)))
    reject('runtime-file-wrong-path',lambda:validate_modules(observed,manifest,lambda path:dict(row(path),path=str(destination/'wrong'/DLL_NAMES[0]))))
    reject('runtime-file-unreadable',lambda:validate_modules(observed,manifest,lambda path:row(destination/'missing.dll')))
    reject('missing-required-HIP',lambda:validate_modules([dict(r,path=None) for r in observed],manifest))
    extra=dict(bundle,child_environment=dict(bundle['child_environment'],SECRET_TOKEN='never copy'))
    reject('credential-env-not-whitelisted',lambda:validate_runtime_bundle(extra))
    duplicate=dict(bundle,members=members[:-1]+[members[0]])
    reject('duplicate-runtime-member',lambda:validate_runtime_bundle(duplicate))
    bad_policy=dict(bundle,members=[dict(r,required_loaded=False) for r in members])
    reject('required-HIP-policy-unchanged',lambda:validate_runtime_bundle(bad_policy))
    if bundle['child_environment']!=runtime_environment(bundle):raise AssertionError('trial environment changed')
    if any('VISIBLE' in key for key in runtime_environment(bundle)):raise AssertionError('absent visibility inferred')
    cases.append('explicit-env-exact-no-inherited-credentials-or-mask')
    full=dict(schema='mock-wrong-schema',device=1,pci='0000:07:00.0',architecture='gfx1201',device_name='mock',warp_size=32,modules=observed)
    for label,data in (('complete-exit0',json.dumps(full).encode()),('complete-nonzero-exit',json.dumps(full).encode()),('birth-failure-complete-summary',json.dumps(full).encode())):
        out=destination/label;out.mkdir();obs=persist_observation(data,out)
        if obs['status']!='observed_unaccepted' or obs['observed_device']['pci']!=full['pci'] or obs['observed_modules']!=observed:raise AssertionError('raw observation lost')
        reject(label+'-reject-keeps-observed',lambda:validate_capture(full,manifest,dict(jobs=[])))
        if read(out/'observation.json')['observed_modules']!=observed:raise AssertionError('validator erased persisted observations')
    for label,data in (('early-AV-empty',b''),('incomplete-JSON',b'{'),('invalid-UTF8',b'\xff')):
        out=destination/label;out.mkdir();obs=persist_observation(data,out)
        if obs['status']!='unobserved_no_complete_summary' or obs['observed_device'] is not None or obs['observed_modules'] is not None:raise AssertionError('invented raw observation')
        cases.append(label+'-unobserved')
    out=destination/'DLL-mismatch';out.mkdir();obs=persist_observation(json.dumps(full).encode(),out)
    reject('DLL-failure-retains-raw',lambda:validate_modules(observed,manifest,lambda path:dict(row(path),sha256='b'*64)))
    if read(out/'observation.json')['observed_modules']!=observed:raise AssertionError('DLL failure erased metadata')
    occupied=destination/'already-used';occupied.mkdir();(occupied/'acquisition.json').write_text('historical',encoding='utf8')
    reject('old-acquisition-no-overwrite',lambda:require_fresh_acquisition(occupied,occupied/'output'))
    occupied=destination/'already-output';occupied.mkdir();(occupied/'output').mkdir()
    reject('old-output-no-reuse',lambda:require_fresh_acquisition(occupied,occupied/'output'))
    reject('actual-execute-refuses-historical-acquisition',lambda:execute(PARENT/'gpu-seal-1/seal.json',OLD_NINE[5][1]))
    cases.extend(execute_repair_mocks(destination,bundle))
    return cases

def execute_repair_mocks(destination,bundle):
    """Exercise actual execute() with an injected owned CPU fake process."""
    import copy
    cases=[];original_build=BUILD;original_collect=collect_owned_process
    capture=read(PARENT/'gpu-seal-1/stdout.bin')
    original_outputs=PARENT/'gpu-seal-1/output'
    controller=row(__file__);interpreter=row(sys.executable)
    class Handle:
        def __init__(self):self.closed=False
        def __int__(self):return 724
        def Close(self):self.closed=True
    class Process:
        def __init__(self,raw,exit_code,output,create_outputs):
            self.pid=999999;self._handle=Handle();self.returncode=exit_code
            self.raw=raw;self.output=output;self.create_outputs=create_outputs
        def poll(self):return self.returncode
        def communicate(self):
            if self.create_outputs:
                self.output.mkdir()
                for path in original_outputs.glob('*.bin'):shutil.copyfile(path,self.output/path.name)
                self.create_outputs=False
            return self.raw,b''
        def terminate(self):self.returncode=-1
        def wait(self):return self.returncode
    try:
        globals()['BUILD']=destination
        for label in ('success','DLL-mismatch','schema-failure','nonzero-complete','birth-failure','creation-failure','early-AV','unreadable-loaded'):
            directory=destination/('runtime-closure-repair-seal-mock-'+label);directory.mkdir();output=directory/'output'
            value=copy.deepcopy(capture)
            value['modules']=[dict(name=r['name'],path=r['path'] if r['required_loaded'] else None) for r in bundle['members']]
            if label=='DLL-mismatch':value['modules'][0]['path']=str(destination/'wrong'/DLL_NAMES[0])
            if label=='unreadable-loaded':value['modules'][0]['path']=str(destination/'unreadable'/DLL_NAMES[0])
            if label=='schema-failure':value['schema']='bad'
            raw=b'' if label in ('early-AV','creation-failure') else json.dumps(value).encode()
            code=3221225477 if label=='early-AV' else 7 if label=='nonzero-complete' else 0
            manifest=dict(schema='T35-row-parallel-preG/v2',attempt=str(PARENT),records=runtime_rows(bundle),runtime_expected_bundle=bundle,exe=row(PARENT/'native/t35-rows.exe'),input_tsv=row(PARENT/'jobs.tsv'),expected_device=dict(pci='0000:07:00.0',architecture='gfx1201'),required_loaded_DLLs=['amdhip64_7.dll'],interpreter=interpreter,controller=controller,environment=runtime_environment(bundle),output_directory=str(output))
            manifest['command']=[manifest['exe']['path'],manifest['expected_device']['pci'],manifest['input_tsv']['path'],str(output)]
            save(directory/'seal.json',manifest)
            process=Process(raw,code,output,label=='success')
            def factory(command,**options):
                if command!=manifest['command'] or options['env']!=bundle['child_environment']:raise AssertionError('mock exact command/env')
                if label=='creation-failure':raise OSError('mock process creation failure')
                return process
            def birth(child):
                if label=='birth-failure':raise OSError('mock GetProcessTimes failure')
                return 123
            globals()['collect_owned_process']=lambda command,cwd,environment:original_collect(command,cwd,environment,process_factory=factory,birth_reader=birth)
            raised=None
            try:execute(directory/'seal.json',row(directory/'seal.json')['sha256'])
            except (ValueError,OSError) as error:raised=error
            result=read(directory/'acquisition.json')
            if label=='success':
                if raised or not result['complete'] or result['observation_status']!='observed_accepted':raise AssertionError('explicit runtime success')
            else:
                if raised is None or result['complete'] or result['validation'] is not None:raise AssertionError('mock failure accepted')
                observed=label not in ('early-AV','creation-failure')
                if result['observation_status']!=('observed_unaccepted' if observed else 'unobserved_no_complete_summary'):raise AssertionError('actual execute observation status')
                if observed and result['observed_modules']!=value['modules']:raise AssertionError('actual execute raw modules lost')
                if not observed and (result['observed_device'] is not None or result['observed_modules'] is not None):raise AssertionError('expected metadata invented')
            if label!='creation-failure' and (not result['process']['original_handle_closed'] or result['process']['exit']!=code):raise AssertionError('actual execute owned-handle cleanup')
            if (directory/'stdout.bin').read_bytes()!=raw:raise AssertionError('actual execute raw body changed')
            if label=='unreadable-loaded' and not read(directory/'observation.json')['file_observations'][0]['error']:raise AssertionError('unreadable fingerprint observation lost')
            cases.append('actual-execute-mock-'+label)
    finally:
        globals()['BUILD']=original_build;globals()['collect_owned_process']=original_collect
    return cases

def cpu_controller(destination):
    destination=Path(destination).resolve()
    if destination.parent!=BUILD.resolve() or not destination.name.startswith('runtime-closure-repair-') or destination.exists():raise ValueError('new isolated repair proof directory required')
    destination.mkdir()
    old_before=immutable_parent()
    try:
        legacy_cases=acquisition_mocks()
        cases=runtime_repair_mocks(destination)
        old_after=immutable_parent()
        if old_before!=old_after:raise AssertionError('immutable old nine changed')
        result=dict(passed=True,cases=cases,legacy_acquisition_cases=legacy_cases,old_parent_before=old_before,old_parent_after=old_after,GPU=False,native_executed=False)
    except BaseException as error:
        save(destination/'controller-cpu.json',dict(passed=False,stage='CPU RED/GREEN',failure=dict(type=type(error).__name__,message=str(error)),controller=row(__file__),GPU=False,native_executed=False))
        raise
    source=destination/'source';source.mkdir()
    for name in ('row_parallel_verify.py','row_parallel_contract.json'):shutil.copyfile(HERE/name,source/name)
    result.update(controller=row(__file__),contract=row(HERE/'row_parallel_contract.json'),accepted_plan=row(REPAIR_PLAN),python=row(sys.executable),source_snapshots=[row(source/name) for name in ('row_parallel_verify.py','row_parallel_contract.json')],parent_numeric_proof=row(PARENT/'cpu.json'),parent_build_proof=row(PARENT/'build.json'),parent_EXE=row(PARENT/'native/t35-rows.exe'),qualification='Controller CPU mocks and saved-output replay only; old native math qualification referenced, not rerun on GPU; no build/native process/device query')
    save(destination/'controller-cpu.json',result)
    print(json.dumps(row(destination/'controller-cpu.json')))

if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--cpu');g.add_argument('--build');g.add_argument('--analyze',nargs=2,metavar=('ATTEMPT','OUTPUT'));g.add_argument('--seal');g.add_argument('--execute');g.add_argument('--cpu-controller');p.add_argument('--pci');p.add_argument('--arch',choices=('gfx1100','gfx1201'));p.add_argument('--seal-sha');p.add_argument('--runtime-bundle');p.add_argument('--controller-proof')
    a=p.parse_args()
    if a.prepare:prepare()
    elif a.cpu:cpu(a.cpu)
    elif a.build:build(a.build)
    elif a.cpu_controller:cpu_controller(a.cpu_controller)
    elif a.seal:seal_execution(a.seal,a.pci or '',a.arch,a.runtime_bundle,a.controller_proof)
    elif a.execute:execute(a.execute,a.seal_sha)
    else:print(json.dumps(analyze(*a.analyze)))
