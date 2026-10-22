"""T13 explicit offline preparation; no model/full-source qualification."""
import argparse,copy,hashlib,importlib.util,json,os,re,shutil,struct,subprocess,sys,time,urllib.request,venv
from pathlib import Path
sys.dont_write_bytecode=True
try:import numpy as np
except ModuleNotFoundError:
    sys.path.append('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages')
    import numpy as np
import reference as q
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).parent
BUILD=ROOT/'build-deepseek-t13';RAW=BUILD/'raw';EXE=BUILD/'bundle/t13-engram.exe'
SHARED=Path('C:/Develop/AI/StrataMod');SDK=SHARED/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
BASE='477ac13cbe8e582c20484871ce459d20d82df09d';REF='1bae0e1088993b9b82de08f59de5be5a34e42170'
OWN=[EXT/'models/deepseek41'/n for n in ['engram.hpp','engram.cpp','engram.hip']]+[HERE/n for n in ['engram_fixture.cpp','CMakeLists.txt','reference.py','build_verify.py','contract.json','NOTICE.md']]
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def row(p):p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,o):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def module(name,path):s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def run(cmd,env=None,check=True,timeout=180):
    r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if check and r.returncode:raise RuntimeError(f'exit{r.returncode}: {cmd}\n{r.stdout}{r.stderr}')
    return r
def get(url):return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Strata-T13-fixed-source'}),timeout=60)
def download(url,path,size=None,expected=None,blob=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with get(url) as response:data=response.read((size or 1048576)+1)
        if size is not None and len(data)!=size:raise ValueError('bounded source length')
        if blob and hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()!=blob:raise ValueError('Git blob source mismatch')
        path.write_bytes(data)
    if size is not None and path.stat().st_size!=size:raise ValueError('source length')
    if expected and sha(path)!=expected:raise ValueError('source checksum')
    return dict(url=url,**row(path))
def header():
    inv=read(EXT/'tests/artifact/header-inventory.json')
    for h in inv['shards']:
        if sha(h['prefix_path'])!=h['prefix_sha256']:raise ValueError('T03 prefix changed')
    g=module('t13_gguf',EXT/'native/artifact/gguf.py');h=inv['shards'][0]
    return inv,g.parse_header(Path(h['prefix_path']).read_bytes(),h['bytes'])['metadata']
def check_rows(rows):
    for r in rows:
        if row(r['path'])!=r:raise ValueError('fixed file changed: '+r['path'])
def oracle_runtime():
    import ctypes,tokenizers
    kernel=ctypes.WinDLL('kernel32');psapi=ctypes.WinDLL('psapi');kernel.GetCurrentProcess.restype=ctypes.c_void_p;process=kernel.GetCurrentProcess();handles=(ctypes.c_void_p*2048)();needed=ctypes.c_ulong()
    psapi.EnumProcessModules.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong)]
    if not psapi.EnumProcessModules(process,handles,ctypes.sizeof(handles),ctypes.byref(needed)) or needed.value>ctypes.sizeof(handles):raise ValueError('oracle module observation')
    kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong];loaded=[]
    for handle in handles[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
        text=ctypes.create_unicode_buffer(32768);length=kernel.GetModuleFileNameW(handle,text,len(text))
        if not length or length==len(text):raise ValueError('oracle loaded path')
        if any(k in text.value.lower() for k in ['numpy','tokenizers','python312.dll','python3.dll']):loaded.append(row(text.value))
    save(BUILD/'oracle-runtime.json',dict(tokenizers_version=tokenizers.__version__,numpy_version=np.__version__,interpreter=row(sys.executable),loaded=loaded,scope='actual CPU oracle process modules; no GPU'))
def oracle():
    BUILD.mkdir(exist_ok=True);save(BUILD/'storage-start.json',dict(free=shutil.disk_usage(BUILD).free,work_estimate=536870912,existing_assets_counted_in_free=True,T05_remaining='Main maintains concurrent transfer accounting; not a full future build guarantee'))
    if q.selftest()!=7:raise ValueError('independent literal selftest')
    # A missing native implementation is the initial meaningful RED.
    if not EXE.exists():save(BUILD/'tdd-red.json',dict(native_artifact_absent=True,oracle_literal_tests=7))
    records=[];src=BUILD/'source'
    hf=f'https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/{REF}/'
    records.append(download(hf+'tokenizer.json',src/'tokenizer.json',6367257,blob='6a15814dd25c934028034531da744c689f87ff21'))
    for name,size,expected in [('inference/engram.py',8138,'11f35ecbead8150c35aa002b3d180ef290b05a25afe883a11884f94d476d3897'),('config.json',3311,'8be45ce0476004a3f529fd896115a4a2e800a129ad2d3ec05b16050f52e21879'),('LICENSE',1084,'f2c6c602815669d292889e5be8c802f2ed950653b77999b1584e8e6aed25d040')]:records.append(download(hf+name,src/name,size,expected))
    refs=[('deepseek-ai/DeepInfer','774ce244b87cc0eb8d4b94ab9f5de2ab22049f01','deepinfer/model_executor/models/v4_modules/engram_metadata.py'),('deepseek-ai/DeepInfer','774ce244b87cc0eb8d4b94ab9f5de2ab22049f01','LICENSE'),('mw00/project-maya','8d9a9b5d705049a87da853717cdc59440252de30','tools/ds4/engram_hash.py'),('mw00/project-maya','8d9a9b5d705049a87da853717cdc59440252de30','src/ds4/ds4_engram_io.hpp'),('mw00/project-maya','8d9a9b5d705049a87da853717cdc59440252de30','LICENSE')]
    for repo,ref,name in refs:records.append(download(f'https://raw.githubusercontent.com/{repo}/{ref}/{name}',src/repo.split('/')[-1]/name))
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',PYTHONUTF8='1',PIP_CACHE_DIR=str(BUILD/'pip-cache'),TMP=str(BUILD/'tmp'),TEMP=str(BUILD/'tmp'));(BUILD/'tmp').mkdir(exist_ok=True)
    v=BUILD/'oracle-venv'
    if not (v/'Scripts/python.exe').exists():venv.EnvBuilder(with_pip=True).create(v)
    python=v/'Scripts/python.exe';wheels=BUILD/'downloads';wheels.mkdir(exist_ok=True)
    if not (BUILD/'python-dependencies.json').exists():
        r=run([python,'-m','pip','download','--only-binary=:all:','--dest',wheels,'tokenizers==0.23.2'],env);(BUILD/'pip-download.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
        import zipfile
        proofs=[]
        for p in wheels.glob('*.whl'):
            with zipfile.ZipFile(p) as z:metadata=z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))).decode()
            fields=dict(l.split(': ',1) for l in metadata.splitlines() if l.startswith(('Name: ','Version: ')))
            with get(f'https://pypi.org/pypi/{fields["Name"]}/{fields["Version"]}/json') as response:release=json.load(response)
            declared=next(x for x in release['urls'] if x['filename']==p.name)
            if sha(p)!=declared['digests']['sha256']:raise ValueError('PyPI published SHA')
            proofs.append(dict(url=declared['url'],published_sha256=declared['digests']['sha256'],**row(p)))
        save(BUILD/'python-dependencies.json',proofs)
    check_rows([{k:r[k] for k in ['path','bytes','sha256']} for r in read(BUILD/'python-dependencies.json')])
    r=run([python,'-m','pip','install','--no-index','--find-links',wheels,'tokenizers==0.23.2'],env);(BUILD/'pip-install.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    # Use the existing exact NumPy module read-only; all tokenizers dependencies
    # are installed task-locally with their normal closure.
    env['PYTHONPATH']=str(HERE)
    r=run([python,HERE/'build_verify.py','oracle-compute'],env);print(r.stdout,end='')
    save(BUILD/'source-provenance.json',records)
def oracle_compute():
    import tokenizers
    inv,m=header();tm,size,branches=q.compressed_map(BUILD/'source/tokenizer.json');mult,primes,offsets=q.constants()
    keys=['deepseek41.engram.token_map','deepseek41.ple.layer_multipliers','deepseek41.ple.head_vocab_sizes','deepseek41.ple.head_offsets']
    if [tm,mult,primes,offsets]!=[m[k] for k in keys] or size!=99092:raise ValueError('independent HF N differs from native Q metadata')
    tuples=q.tuples([0,42],tm,mult,primes,offsets);contract=read(HERE/'contract.json')
    if q.tuple_sha(tuples)!=contract['tuple_sha256'] or len({r[-1] for r in tuples})!=96:raise ValueError('pre-fixed tuple derivation')
    expected=dict(token_map=tm,multipliers=mult,primes=primes,offsets=offsets,compressed_size=size,branches=branches,tuples=tuples)
    save(BUILD/'nq.json',expected)
    # Full normalizer map equality, followed by independent scalar state traces.
    traces=[]
    for batch in range(2):
        for length in [1,2,4,8]:
            for dead in [False,True]:
                raw=[(17+i*37+batch*113)%129280 for i in range(length)];mask=[not(dead and i==length//2) for i in range(length)]
                traces.append((raw,mask))
    traces.append(([0,42],[True,True]))
    with (BUILD/'hash-input.bin').open('wb') as f:
        f.write(struct.pack('<I',len(traces)))
        for raw,mask in traces:f.write(struct.pack('<I',len(raw))+struct.pack('<'+'I'*len(raw),*raw)+bytes(mask))
    expected_hash=b''.join(struct.pack('<'+'Q'*(len(raw)*48),*(x for rows in q.hashes(raw,mask,tm,mult,primes,offsets) for x in rows)) for raw,mask in traces)
    (BUILD/'hash-expected.bin').write_bytes(expected_hash)
    identity=[row(Path(tokenizers.__file__)),row(Path(np.__file__))]+[row(p) for p in Path(tokenizers.__file__).parent.glob('*.pyd')]+[row(p) for p in Path(np.__file__).parent.rglob('*.pyd')]+[row(p) for p in Path(np.__file__).parent.parent.joinpath('numpy.libs').glob('*.dll')]
    save(BUILD/'nq-manifest.json',dict(schema='T13-NQ-before-native/v1',metadata_derived_Q_distinct_HF_normalization_N=True,files=[row(BUILD/p) for p in ['nq.json','hash-input.bin','hash-expected.bin']]+[row(HERE/'reference.py'),row(HERE/'contract.json'),row(BUILD/'source/tokenizer.json')],oracle_modules=identity,tokenizers_version=tokenizers.__version__,numpy_version=np.__version__,NQ_exact=True,hash_cases=len(traces),literal_tests=q.selftest(),G_executed=False))
    print(json.dumps(dict(NQ_exact=True,full_token_map=len(tm),compressed=size,real_rows=len(tuples),branches=branches)))
def fixture_set(receipts=None):
    n=read(BUILD/'nq.json');inv,m=header();tuples=q.tuples([0,42],m['deepseek41.engram.token_map'],m['deepseek41.ple.layer_multipliers'],m['deepseek41.ple.head_vocab_sizes'],m['deepseek41.ple.head_offsets'])
    if tuples!=n['tuples'] or q.tuple_sha(tuples)!=read(HERE/'contract.json')['tuple_sha256']:raise ValueError('tuple source derivation')
    h=inv['shards'][7];tensor=next(t for t in h['tensors'] if t['name']=='per_layer_token_embd.weight')
    if tensor['dims_ggml']!=[256,768022850] or tensor['row_bytes']!=264 or tensor['absolute_offset']!=192 or tensor['type_id']!=43:raise ValueError('source geometry')
    records=read(BUILD/'raw-receipt.json')['rows'] if receipts is None else receipts
    if len(records)!=96:raise ValueError('real row coverage')
    src=next(x for x in read(EXT/'tests/artifact/source-files.json')['files'] if x['index']==8)
    for i,(t,r) in enumerate(zip(tuples,records)):
        expected=dict(tuple=t,absolute_offset=192+t[-1]*264,bytes=264,revision=inv['revision'],shard_index=8,filename=src['filename'],file_bytes=h['bytes'],lfs_sha256=h['lfs_sha256'],type_id=43,dims_ggml=[256,768022850],row_bytes=264,full_file_sha_verified=False)
        if any(r.get(k)!=v for k,v in expected.items()):raise ValueError('row source identity/offset')
        http=r['http'];start=expected['absolute_offset']
        if http!=dict(status=206,start=start,end=start+263,total=h['bytes'],etag=h['http_ranges'][0]['etag'],content_length=264):raise ValueError('row HTTP range provenance')
        if r['path']!=str(RAW/f'row-{i:03d}.bin') or row(r['path'])!={k:r[k] for k in ['path','bytes','sha256']}:raise ValueError('row raw identity')
    return records
def acquire():
    nq=read(BUILD/'nq-manifest.json');check_rows(nq['files']+nq['oracle_modules']);inv,m=header();n=read(BUILD/'nq.json')
    if q.tuple_sha(q.tuples([0,42],m['deepseek41.engram.token_map'],m['deepseek41.ple.layer_multipliers'],m['deepseek41.ple.head_vocab_sizes'],m['deepseek41.ple.head_offsets']))!=read(HERE/'contract.json')['tuple_sha256']:raise ValueError('pre-acquisition tuple mismatch')
    fetch=module('t13_acquire',EXT/'native/artifact/acquire.py');full=module('t13_full',EXT/'native/artifact/full_acquire.py');h=inv['shards'][7];src=next(x for x in read(EXT/'tests/artifact/source-files.json')['files'] if x['index']==8)
    RAW.mkdir(exist_ok=True);records=[]
    url=f'https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF/resolve/{inv["revision"]}/{src["filename"]}'
    for i,t in enumerate(n['tuples']):
        p=RAW/f'row-{i:03d}.bin';start=192+t[-1]*264
        if p.exists():raise ValueError('preserve prior acquisition; no overwrite')
        request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{start+263}','Accept-Encoding':'identity'})
        with urllib.request.urlopen(request,timeout=60) as response:
            full.validate_response(response,start,264,h['bytes'],h['http_ranges'][0]['etag'])
            data,http=fetch.read_range_response(response,start,264,h['bytes'],h['http_ranges'][0]['etag'])
        http['content_length']=264;p.write_bytes(data)
        records.append(dict(tuple=t,absolute_offset=start,revision=inv['revision'],shard_index=8,filename=src['filename'],file_bytes=h['bytes'],lfs_sha256=h['lfs_sha256'],type_id=43,dims_ggml=[256,768022850],row_bytes=264,full_file_sha_verified=False,http=http,**row(p)))
        save(BUILD/'acquisition-progress.json',dict(rows=records));print(f'row {i+1}/96:264B',flush=True)
    save(BUILD/'raw-receipt.json',dict(rows=records,total_bytes=25344,whole_file_sha_verified=False,NQ_manifest=row(BUILD/'nq-manifest.json')));fixture_set()
    raw=b''.join(Path(r['path']).read_bytes() for r in records);(BUILD/'bank.bin').write_bytes(raw+q.literals())
    bank_count=103;indices=list(range(bank_count))+list(reversed(range(48)))+[0,0,95]
    (BUILD/'indices.bin').write_bytes(struct.pack('<'+'I'*len(indices),*indices))
    floats=q.decode(raw+q.literals()).reshape(bank_count,256)[indices].reshape(-1);floats.tofile(BUILD/'decode-expected.bin');q.bf16(floats).tofile(BUILD/'bf16-expected.bin')
    save(BUILD/'gather-q-manifest.json',dict(files=[row(BUILD/p) for p in ['raw-receipt.json','bank.bin','indices.bin','decode-expected.bin','bf16-expected.bin','nq-manifest.json']]+[{k:r[k] for k in ['path','bytes','sha256']} for r in records],requests=len(indices),real_rows=96,real_values=24576,literal_rows=7,G_executed=False))
    print('raw and all gather Q expectations fixed; no GPU executed')
def environment():
    vc=SHARED/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=SHARED/'.vision-toolchain/winsdk';inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
    tools=dict(clang=SDK/'lib/llvm/bin/clang++.exe',cmake=SHARED/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe',ninja=SHARED/'.vision-venv-10.1/Scripts/ninja.exe',linker=vc/'bin/Hostx64/x64/link.exe',dumpbin=vc/'bin/Hostx64/x64/dumpbin.exe',rc=wb/'rc.exe',mt=wb/'mt.exe',objdump=SDK/'lib/llvm/bin/llvm-objdump.exe')
    env=os.environ.copy();(BUILD/'tmp').mkdir(exist_ok=True);env.update(TMP=str(BUILD/'tmp'),TEMP=str(BUILD/'tmp'),HIP_PATH=str(SDK),ROCM_PATH=str(SDK),HIP_PLATFORM='amd',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']));env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64',SDK/'lib']))
    env['PATH']=os.pathsep.join(map(str,[EXE.parent,SDK/'bin',SDK/'lib/llvm/bin',vc/'bin/Hostx64/x64',wb,env.get('PATH','')]))
    return tools,env
def runtime_environment():
    _,env=environment();windows=Path(os.environ['SystemRoot'])
    env['PATH']=os.pathsep.join(map(str,[EXE.parent,windows/'System32',windows]))
    for name in ['HIP_PATH','ROCM_PATH','HIP_PLATFORM','INCLUDE','LIB']:env.pop(name,None)
    return env
def compiled_id():
    paths=OWN[:3]+[HERE/'engram_fixture.cpp']
    return hashlib.sha256(''.join(p.relative_to(ROOT).as_posix()+'|'+sha(p)+'\n' for p in paths).encode()).hexdigest()
def q_binding():
    n=read(BUILD/'nq-manifest.json');g=read(BUILD/'gather-q-manifest.json');check_rows(n['files']+n['oracle_modules']+g['files']);fixture_set()
    if n['tokenizers_version']!='0.23.2' or n['numpy_version']!='2.3.4' or not n['NQ_exact'] or g['real_rows']!=96 or g['requests']!=154:raise ValueError('Q coverage/precision')
    packed=b''.join(Path(r['path']).read_bytes() for r in fixture_set())+q.literals()
    expected_indices=list(range(103))+list(reversed(range(48)))+[0,0,95]
    if (BUILD/'bank.bin').read_bytes()!=packed or (BUILD/'indices.bin').read_bytes()!=struct.pack('<'+'I'*154,*expected_indices):raise ValueError('real/literal bank and ordered coverage')
    if (BUILD/'decode-expected.bin').stat().st_size!=154*256*4 or (BUILD/'bf16-expected.bin').stat().st_size!=154*256*2:raise ValueError('Q output count')
def build():
    q_binding();tools,env=environment();out=BUILD/'cmake';EXE.parent.mkdir(exist_ok=True)
    oracle_env=env.copy();oracle_env['PYTHONPATH']=str(HERE);run([BUILD/'oracle-venv/Scripts/python.exe','-B',HERE/'build_verify.py','oracle-runtime'],oracle_env)
    # Fixed offline T10 descriptors, not live models or .part files.
    for name in ['nine-prefixes.tsv','sources.tsv']:shutil.copyfile(ROOT/'build-deepseek-t10'/name,BUILD/name)
    records=fixture_set();lines=[]
    for i,r in enumerate(records):
        pos,layer,ngram,head,local,global_row=r['tuple'];lines.append('\t'.join(map(str,[i,layer,(ngram-2)*8+head,local,global_row,r['absolute_offset'],r['path']])))
    (BUILD/'rows.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    n=read(BUILD/'nq.json');values=n['token_map']+n['multipliers']+n['primes']+n['offsets'];(BUILD/'config-expected.bin').write_bytes(struct.pack('<'+'Q'*len(values),*values))
    commands=[[tools['cmake'],'--fresh','-S',HERE,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],[tools['cmake'],'--build',out,'--verbose']]
    for i,cmd in enumerate(commands):
        old=BUILD/f'build-{i}.txt'
        if old.exists():shutil.copyfile(old,BUILD/f'build-{i}-prior-{sha(old)[:12]}.txt')
        result=run(cmd,env,False,300);(BUILD/f'build-{i}.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError(f'build{i} failed; preserve log')
    shutil.copyfile(out/'bundle/t13-engram.exe',EXE)
    # Only the required already-qualified HIP/comgr/CRT and notices are copied.
    origins=[]
    for p in (ROOT/'build-deepseek-t09/bundle').rglob('*'):
        if p.is_file() and (p.suffix.lower()=='.dll' or 'licenses' in p.parts):
            target=EXE.parent/p.relative_to(ROOT/'build-deepseek-t09/bundle');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);origins.append(dict(source=row(p),destination=row(target)))
    # HIP's actual PE dependency was absent from the older T09 fixture bundle.
    source=SDK/'bin/rocm_kpack.dll';target=EXE.parent/source.name;shutil.copyfile(source,target);origins.append(dict(source=row(source),destination=row(target)))
    r=run([tools['dumpbin'],'/dependents',EXE.parent/'amdhip64_7.dll'],env);(BUILD/'HIP-direct-imports.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    for label,command in [('imports',[tools['dumpbin'],'/dependents',EXE]),('offloading',[tools['objdump'],'--offloading',EXE])]:
        r=run(command,env);(BUILD/f'{label}.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    if not all(x in (BUILD/'offloading.txt').read_text(encoding='utf-8') for x in ['gfx1100','gfx1201']):raise ValueError('two compiled architectures missing')
    deps=[EXT/'models/deepseek41'/p for p in ['artifact.hpp','artifact.cpp','reference-config.json']]+[EXT/'native/artifact'/p for p in ['native_reader.hpp','native_reader.cpp','gguf.py','acquire.py','full_acquire.py','quant_layouts.json']]+[EXT/'native/io'/p for p in ['span_provider.hpp','span_provider.cpp']]+[EXT/'native/cache'/p for p in ['lease_queue.hpp','lease_queue.cpp']]+[EXT/'native/stats'/p for p in ['measurement.hpp','measurement.cpp']]+[ROOT/p for p in ['src/platform/direct_file.cpp','include/strata/platform/direct_file.hpp','include/strata/artifact/gguf_reader.hpp','include/strata/artifact/gguf_split.hpp','include/strata/artifact/dequant.hpp','include/strata/artifact/model_family.hpp','include/strata/core/geometry.hpp']]
    priors=[ROOT/p for p in ['build-deepseek-t09/bundle/manifest.json','build-deepseek-t10/bundle-offline-r7/manifest.json','build-deepseek-t16/bundle/manifest.json','build-deepseek-t17/bundle/manifest.json','build-deepseek-t27/manifest.json']]+[EXT/'tests/artifact'/p for p in ['header-inventory.json','source-files.json','fixture-receipts.json']]
    dependency_report=run([tools['ninja'],'-C',out,'-t','deps'],env).stdout
    (BUILD/'compiled-dependencies.txt').write_text(dependency_report,encoding='utf-8')
    for line in dependency_report.splitlines():
        p=Path(line.strip())
        if p.is_absolute() and p.is_file() and p.resolve().is_relative_to(ROOT.resolve()) and p.resolve() not in [x.resolve() for x in OWN+deps]:deps.append(p)
    inputs=[BUILD/p for p in ['nq-manifest.json','gather-q-manifest.json','nq.json','raw-receipt.json','hash-input.bin','hash-expected.bin','bank.bin','indices.bin','decode-expected.bin','bf16-expected.bin','config-expected.bin','rows.tsv','nine-prefixes.tsv','sources.tsv','source-provenance.json','python-dependencies.json','compiled-dependencies.txt','build-0.txt','build-1.txt','imports.txt','offloading.txt','oracle-runtime.json','HIP-direct-imports.txt']]
    inputs.extend(Path(r['path']) for r in read(BUILD/'oracle-runtime.json')['loaded'])
    tools['python']=Path(sys.executable)
    inv,_=header();inputs.extend(Path(s['prefix_path']) for s in inv['shards']);inputs.extend(Path(r['path']) for r in records);inputs.extend(Path(r['path']) for r in read(BUILD/'source-provenance.json'));inputs.extend(Path(r['path']) for r in read(BUILD/'python-dependencies.json'))
    system=[]
    for name in re.findall(r'^\s+([\w.-]+\.dll)\s*$',(BUILD/'imports.txt').read_text(encoding='utf-8'),re.M|re.I):
        p=Path(os.environ['SystemRoot'])/'System32'/name
        if not (EXE.parent/name).exists() and p.exists():system.append(row(p))
    manifest=dict(schema='T13-offline-fixed-trial/v1',compiled_id=compiled_id(),own=[row(p) for p in OWN],deps=[row(p) for p in deps],prior=[row(p) for p in priors],inputs=[row(p) for p in inputs],tools={k:row(p) for k,p in tools.items()},system_direct_imports=system,bundle=[row(p) for p in sorted(EXE.parent.rglob('*')) if p.is_file()],artifact=row(EXE),commands=[list(map(str,c)) for c in commands],dll_origins=origins,scope=read(HERE/'contract.json')['scope'],full_source_qualified=False,patches=[],base=BASE,storage=dict(generated_bytes=sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file()),free=shutil.disk_usage(BUILD).free),G_executed=False)
    binding(manifest);save(BUILD/'manifest.json',manifest);print(json.dumps(dict(ready=True,manifest=row(BUILD/'manifest.json'),exe=row(EXE),Q=row(BUILD/'gather-q-manifest.json'))))
def binding(m):
    if m['own']!=[row(p) for p in OWN] or m['compiled_id']!=compiled_id() or m['base']!=BASE or m['patches']:raise ValueError('source identity')
    for key in ['own','deps','prior','inputs','bundle','system_direct_imports']:check_rows(m[key])
    if m['artifact']!=row(EXE):raise ValueError('artifact binding')
    if m['bundle']!=[row(p) for p in sorted(EXE.parent.rglob('*')) if p.is_file()]:raise ValueError('bundle file set')
    check_rows(list(m['tools'].values()));q_binding()
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE or run(['git','diff',BASE,'--name-only','--','.',':(exclude)Strata-extensions']).stdout.strip():raise ValueError('base tracked source changed')
    env=runtime_environment()
    if run([EXE,'--identity'],env).stdout!=m['compiled_id']:raise ValueError('compiled artifact identity')
def exact(actual,expected):
    if Path(actual).read_bytes()!=Path(expected).read_bytes():raise ValueError('exact output bytes differ')
def verify():
    m=read(BUILD/'manifest.json');fingerprint=sha(BUILD/'manifest.json');binding(m);env=runtime_environment();out=BUILD/'host-output-r2'
    if out.exists():raise ValueError('keep previous host output before rerun')
    result=run([EXE,'--host',BUILD,out,sha(BUILD/'gather-q-manifest.json'),fingerprint],env,False)
    (BUILD/'host.stdout.json').write_text(result.stdout,encoding='utf-8');(BUILD/'host.stderr.txt').write_text(result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('host fixture failure; logs preserved')
    receipt=json.loads(result.stdout)
    exact(out/'hashes.bin',BUILD/'hash-expected.bin');exact(out/'config.bin',BUILD/'config-expected.bin')
    raw=b''.join(Path(r['path']).read_bytes() for r in fixture_set())
    for i in range(3):
        if (out/f'row-bank-{i}.bin').read_bytes()!=raw:raise ValueError('T17 row bytes differ')
    binding(m)
    if sha(BUILD/'manifest.json')!=fingerprint or result.stderr or receipt['source_id']!=m['compiled_id']:raise ValueError('host receipt binding/diagnostic')
    save(BUILD/'host-verification.json',dict(manifest_sha256=fingerprint,receipt=receipt,outputs=[row(p) for p in sorted(out.glob('*'))],before_after_binding=True,runtime_PATH=env['PATH'],HIP_PATH_present='HIP_PATH' in env,GPU_executed=False));print(receipt)
def selftest():
    m=read(BUILD/'manifest.json');binding(m);records=fixture_set();cases=[]
    for key in ['absolute_offset','tuple','revision','lfs_sha256','filename','http','type_id','dims_ggml']:
        bad=copy.deepcopy(records)
        if key=='tuple':bad[0][key][4]+=1
        elif key=='http':bad[0][key]['start']+=1
        elif key=='dims_ggml':bad[0][key][0]-=1
        elif isinstance(bad[0][key],str):bad[0][key]='changed'
        else:bad[0][key]+=1
        try:fixture_set(bad)
        except ValueError:cases.append(key)
        else:raise ValueError('receipt tamper accepted')
    tmp=BUILD/'negatives';tmp.mkdir(exist_ok=True)
    inv,_=header();prefix=Path(inv['shards'][0]['prefix_path']).read_bytes();key=b'deepseek41.engram.token_map';at=prefix.index(struct.pack('<Q',len(key))+key)+8+len(key)
    env=runtime_environment()
    for name,offset,value in [('count',at+8,struct.pack('<Q',129279)),('element-type',at+4,struct.pack('<I',6)),('short-span',None,None)]:
        bad=bytearray(prefix)
        if offset is None:bad=bad[:at+16+129280*4-1]
        else:bad[offset:offset+len(value)]=value
        path=tmp/('prefix-'+name+'.bin');path.write_bytes(bad);result=run([EXE,'--metadata',path],env,False)
        if result.returncode==0:raise ValueError('native metadata negative accepted')
        cases.append('native metadata '+name)
    for suffix in [b'\0',b'',b'\0\0\0']:
        expected=tmp/'expected';actual=tmp/'actual';expected.write_bytes(b'1234');actual.write_bytes(b'1234'+suffix if suffix else b'123')
        try:exact(actual,expected)
        except ValueError:cases.append('byte length')
        else:raise ValueError('output length tamper accepted')
    for key in ['own','artifact','compiled_id']:
        bad=copy.deepcopy(m)
        if key=='compiled_id':bad[key]='0'*64
        elif key=='artifact':bad['artifact']['sha256']='0'*64
        else:bad[key][0]['sha256']='0'*64
        try:binding(bad)
        except ValueError:cases.append(key)
        else:raise ValueError('binding tamper accepted')
    save(BUILD/'negatives.json',dict(passed=len(cases),cases=cases,oracle_literals=q.selftest(),GPU_executed=False));print(len(cases))
def compare_float(actual,expected):
    if Path(actual).stat().st_size!=Path(expected).stat().st_size or Path(actual).stat().st_size%4:raise ValueError('exact FP32 byte length')
    a=np.fromfile(actual,dtype='<f4');e=np.fromfile(expected,dtype='<f4');finite=np.isfinite(e)
    if not np.array_equal(a.view('<u4')[finite],e.view('<u4')[finite]) or not np.array_equal(np.isnan(a),np.isnan(e)) or not np.array_equal(np.isposinf(a),np.isposinf(e)) or not np.array_equal(np.isneginf(a),np.isneginf(e)):raise ValueError('FP32 bits/classification')
    return len(e)
def execute():
    m=read(BUILD/'manifest.json');fingerprint=sha(BUILD/'manifest.json');binding(m);env=runtime_environment();results=[]
    for role,pci in [('primary','0000:07:00.0'),('secondary','0000:03:00.0')]:
        out=BUILD/(role+'-output-r2')
        if out.exists():raise ValueError('preserve prior GPU output')
        r=run([EXE,'--gpu',pci,BUILD,out,fingerprint],env,False,180);(BUILD/(role+'.stdout.json')).write_text(r.stdout,encoding='utf-8');(BUILD/(role+'.stderr.txt')).write_text(r.stderr,encoding='utf-8')
        binding(m)
        if r.returncode:raise RuntimeError('GPU failure preserved; no blind retry')
        receipt=json.loads(r.stdout)
        if r.stderr or receipt['pci']!=pci or receipt['source_id']!=m['compiled_id']:raise ValueError('device receipt identity')
        values=compare_float(out/'decoded.bin',BUILD/'decode-expected.bin');a=np.fromfile(out/'bf16.bin',dtype='<u2');e=np.fromfile(BUILD/'bf16-expected.bin',dtype='<u2');expected=np.fromfile(BUILD/'decode-expected.bin',dtype='<f4');finite=np.isfinite(expected)
        if (out/'bf16.bin').stat().st_size!=(BUILD/'bf16-expected.bin').stat().st_size or not np.array_equal(a[finite],e[finite]) or not np.array_equal((a&0x7fff)>0x7f80,np.isnan(expected)) or not np.array_equal(a[np.isinf(expected)],e[np.isinf(expected)]):raise ValueError('BF16 cast bits/classification')
        actual_next=np.fromfile(out/'next.bin',dtype='<u4');expect_next=np.fromfile(BUILD/'decode-expected.bin',dtype='<u4')[:256]
        if not np.array_equal(actual_next,expect_next):raise ValueError('cleanup next operation')
        loaded=[row(p) for p in receipt['loaded_modules'] if Path(p).name.lower() in ['amd_comgr.dll','amdhip64_7.dll','rocm_kpack.dll']]
        if len(loaded)!=3 or any(Path(x['path']).resolve().parent!=EXE.parent.resolve() for x in loaded):raise ValueError('loaded DLL outside bundle')
        for x in loaded:exact_sha=sha(EXE.parent/Path(x['path']).name);assert exact_sha==x['sha256']
        binding(m)
        if sha(BUILD/'manifest.json')!=fingerprint:raise ValueError('manifest changed')
        record=dict(role=role,manifest_sha256=fingerprint,receipt=receipt,compared_values=values,loaded_DLL=loaded,outputs=[row(p) for p in sorted(out.glob('*'))],before_after_binding=True,runtime_PATH=env['PATH'],HIP_PATH_present='HIP_PATH' in env,status='pass',full_source_qualified=False)
        save(BUILD/(role+'-verification.json'),record);results.append(row(BUILD/(role+'-verification.json')))
    save(BUILD/'verification.json',dict(manifest_sha256=fingerprint,host=row(BUILD/'host-verification.json'),negatives=row(BUILD/'negatives.json'),devices=results,pre_GPU_status=row(BUILD/'gpu-pre-status-r2.json'),scope=m['scope'],full_source_qualified=False,generated_bytes=sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file()),free=shutil.disk_usage(BUILD).free));print(row(BUILD/'verification.json'))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['oracle','oracle-compute','oracle-runtime','acquire','build','verify','selftest','execute']);a=p.parse_args();globals()[a.mode.replace('-','_')]()
