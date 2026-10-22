"""Task-owned Windows span-provider proof. No GPU or model runtime operations."""
import argparse
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
BUILD=ROOT/'build-deepseek-t17'
MANIFEST=BUILD/'bundle/manifest.json'
SHARED=Path('C:/Develop/AI/StrataMod')
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
COMPILED=['Strata-extensions/native/io/span_provider.hpp','Strata-extensions/native/io/span_provider.cpp','Strata-extensions/tests/io/span_fixture.cpp']
RECIPES=['Strata-extensions/native/io/CMakeLists.txt','Strata-extensions/tests/io/provider-contract.json','Strata-extensions/tests/io/build_verify.py']
DEPS=['Strata-extensions/native/artifact/native_reader.hpp','Strata-extensions/native/artifact/native_reader.cpp',
      'Strata-extensions/native/cache/lease_queue.hpp','Strata-extensions/native/cache/lease_queue.cpp',
      'Strata-extensions/native/stats/measurement.hpp','Strata-extensions/native/stats/measurement.cpp',
      'include/strata/platform/direct_file.hpp','src/platform/direct_file.cpp','include/strata/platform/aux_cpus.hpp',
      'include/strata/artifact/dequant.hpp','include/strata/artifact/gguf_reader.hpp','include/strata/artifact/gguf_split.hpp',
      'include/strata/core/geometry.hpp','include/strata/artifact/model_family.hpp',
      'Strata-extensions/tests/artifact/fixture-receipts.json',
      'build-deepseek-t08/bundle/manifest.json','build-deepseek-t08/bundle/verification.json',
      'build-deepseek-t16/bundle/manifest.json','build-deepseek-t16/verification.json',
      'build-deepseek-t34/bundle/manifest.json','build-deepseek-t34/bundle/verification.json']
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def row(p):return {'path':str(p),'bytes':Path(p).stat().st_size,'sha256':sha(p)}
def rows(paths):return [{'path':p,'sha256':sha(ROOT/p)} for p in paths]
def aggregate(items):return hashlib.sha256(''.join(f"{x['path']}|{x['sha256']}\n" for x in items).encode()).hexdigest()
def save(p,o):Path(p).write_text(json.dumps(o,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def run(cmd,env,check=True):
    r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    if check and r.returncode:raise RuntimeError(f'exit {r.returncode}: {r.stdout}\n{r.stderr}')
    return r
def environment():
    vc=SHARED/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=SHARED/'.vision-toolchain/winsdk'
    inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
    tools={'cl':vc/'bin/Hostx64/x64/cl.exe','link':vc/'bin/Hostx64/x64/link.exe','dumpbin':vc/'bin/Hostx64/x64/dumpbin.exe',
           'cmake':SHARED/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe','ninja':SHARED/'.vision-venv-10.1/Scripts/ninja.exe','rc':wb/'rc.exe','mt':wb/'mt.exe'}
    env=os.environ.copy();temporary=BUILD/'tmp';temporary.mkdir(parents=True,exist_ok=True);env['TMP']=env['TEMP']=str(temporary)
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']))
    env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64']))
    env['PATH']=os.pathsep.join(map(str,[vc/'bin/Hostx64/x64',wb,env.get('PATH','')]))
    env['STRATA_IO_THREADS']='1' # child fixture only; no production/default change
    return tools,env
def prepare():
    folder=BUILD/'input';folder.mkdir(parents=True,exist_ok=True);expected=BUILD/'expected';expected.mkdir(exist_ok=True)
    sources=[]
    for i,(name,size) in enumerate([('\u5143\u30c7\u30fc\u30bf.bin',65539),('b.bin',32769),('c.bin',8193)]):
        p=folder/name;p.write_bytes(bytes((n*37+n//251+i*61)%256 for n in range(size)));sources.append((p,1000000000*(i+1),size))
    receipts=read(ROOT/'Strata-extensions/tests/artifact/fixture-receipts.json')['fixtures']
    for name in ['gate','up','down']:
        entry=next(x for x in receipts if x['tensor']==f'blk.0.ffn_{name}_exps.weight')
        p=Path(entry['fixture_path'])
        if p.stat().st_size!=entry['bytes'] or sha(p)!=entry['fixture_sha256']:raise ValueError('T03 immutable fixture mismatch')
        sources.append((p,entry['absolute_offset'],entry['bytes']))
    (folder/'sources.tsv').write_text(''.join(f'{p}\t{base}\t{size}\n' for p,base,size in sources),encoding='utf-8')
    def gather(name,size,spans):
        output=bytearray([0xa5])*size
        for source,start,count,dest in spans:
            with sources[source][0].open('rb') as f:f.seek(start);data=f.read(count)
            if len(data)!=count:raise ValueError('independent expected short')
            output[dest:dest+count]=data
        (expected/name).write_bytes(output)
    for i in range(3):
        gather(f'gather-{i}.bin',18210,[(0,13,10001,7),(1,4095,8193,10008),(2,8192,1,18201)])
        gather(f'real-{i}.bin',5270,[(3,4093,5001,3),(4,17,257,5004),(5,6266879,1,5261)])
    gather('many.bin',391,[(0,4090+n,17,n*17) for n in range(23)])
    for skip in [0,13]:gather(f'credit-{skip}.bin',8192,[(0,skip,8192,0)])
    save(BUILD/'input-manifest.json',{'sources':[dict(row(p),logical_base=base,logical_bytes=size) for p,base,size in sources],
         'files':[row(folder/'sources.tsv')]+[row(p) for p in sorted(expected.iterdir())],
         'expected_role':'independent Python raw slices, logical source base distinct from fixture physical offsets','physical_io':None})
def binding(m):
    if m['compiled']!=rows(COMPILED) or m['recipes']!=rows(RECIPES) or m['dependencies']!=rows(DEPS) or m['source_id']!=aggregate(rows(COMPILED)):raise ValueError('source/recipe/dependency changed')
    for x in m['files']+list(m['tools'].values()):
        if row(x['path'])!=x:raise ValueError('fixed file changed: '+x['path'])
    _,env=environment()
    if run(['git','rev-parse','HEAD'],env).stdout.strip()!=BASE or run(['git','diff',BASE,'--name-only','--','.',':(exclude)Strata-extensions'],env).stdout.strip():raise ValueError('upstream reference changed')
def build():
    prepare();tools,env=environment();before=shutil.disk_usage(BUILD).free
    commands=[[tools['cmake'],'--fresh','-S',ROOT/'Strata-extensions/native/io','-B',BUILD,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',f'-DCMAKE_CXX_COMPILER={tools["cl"].as_posix()}',
               f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["link"].as_posix()}'],
              [tools['cmake'],'--build',BUILD,'--clean-first','--verbose']]
    for n,cmd in enumerate(commands):
        r=run(cmd,env,False);(BUILD/f'build-{n}.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(f'build step {n} failed; saved log')
    shutil.copyfile(ROOT/'LICENSE',MANIFEST.parent/'Strata-LICENSE')
    r=run([tools['dumpbin'],'/dependents',MANIFEST.parent/'t17-span.exe'],env);(BUILD/'imports.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    inp=read(BUILD/'input-manifest.json');files=[row(BUILD/'input-manifest.json')]+inp['files']+[{k:x[k] for k in ['path','bytes','sha256']} for x in inp['sources']]+[row(p) for p in sorted(MANIFEST.parent.iterdir()) if p.is_file() and p!=MANIFEST]
    kernel=ctypes.WinDLL('kernel32');module=ctypes.create_unicode_buffer(32768);kernel.GetModuleFileNameW(ctypes.c_void_p(kernel._handle),module,32768);system_dll=row(module.value);files.append(system_dll)
    versions={}
    for n,p in tools.items():
        r=run([p,'--version' if n in ['cmake','ninja'] else '/?'],env,False);versions[n]=[s for s in (r.stdout+r.stderr).splitlines() if s.strip()][:3]
    m={'schema':'t17-fixed-trial/v1','source_id':aggregate(rows(COMPILED)),'compiled':rows(COMPILED),'recipes':rows(RECIPES),'dependencies':rows(DEPS),'files':files,'tools':{n:row(p) for n,p in tools.items()},'tool_versions':versions,'direct_system_dll':system_dll,
       'upstream_reference':BASE,'patches':[],'commands':[list(map(str,c)) for c in commands],'scope':'host Windows bounded span provider; model supply/atomic working set/GPU unimplemented',
       'free_before_build':before,'free_after_build':shutil.disk_usage(BUILD).free}
    save(MANIFEST,m);binding(m);print(json.dumps({'manifest':row(MANIFEST),'exe':row(MANIFEST.parent/'t17-span.exe')}))
def exact(expected,actual):
    if Path(expected).stat().st_size!=Path(actual).stat().st_size or Path(expected).read_bytes()!=Path(actual).read_bytes():raise ValueError('raw output length/content mismatch')
def execute():
    m=read(MANIFEST);fixed=sha(MANIFEST);binding(m);_,env=environment();output=BUILD/'output';output.mkdir(exist_ok=True)
    r=run([MANIFEST.parent/'t17-span.exe',BUILD/'input',output,sha(BUILD/'input-manifest.json'),fixed],env,False);(BUILD/'host.stdout.json').write_text(r.stdout,encoding='utf-8');(BUILD/'host.stderr.txt').write_text(r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError('native fixture failed; attempt logs retained')
    receipt=json.loads(r.stdout)
    if receipt['source_id']!=m['source_id'] or receipt['fixture_sha256']!=sha(BUILD/'input-manifest.json') or receipt['bundle_sha256']!=fixed or not receipt['owner_drained'] or receipt['GPU_executed'] or receipt['physical_io'] is not None:raise ValueError('scope/binding')
    if receipt['assertions']<read(HERE/'provider-contract.json')['host_min_assertions'] or receipt['T16_host_lease_cycles']!=2 or receipt['EOF_data']!=1 or row(receipt['kernel32_path'])['sha256']!=m['direct_system_dll']['sha256']:raise ValueError('coverage/actual DLL')
    if len(receipt['byte_counters'])!=3 or any(x['logical_useful']!=23454 or x['physical_io'] is not None for x in receipt['byte_counters']):raise ValueError('T34 counter scope')
    for p in (BUILD/'expected').iterdir():exact(p,output/p.name)
    binding(m)
    if sha(MANIFEST)!=fixed:raise ValueError('manifest changed during tests')
    save(BUILD/'verification.json',{'manifest_sha256':fixed,'receipt':receipt,'outputs':[row(p) for p in sorted(output.iterdir())],
         'binding_before_after':True,'source_files_unchanged':True,'storage':{'generated_bytes':sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file()),'free_after':shutil.disk_usage(BUILD).free},'GPU_executed':False})
    print(json.dumps(receipt))
def negatives():
    m=read(MANIFEST);binding(m);count=0
    for key in ['compiled','recipes','dependencies','source_id']:
        bad=copy.deepcopy(m)
        if key=='source_id':bad[key]='0'*64
        else:bad[key][0]['sha256']='0'*64
        try:binding(bad)
        except ValueError:count+=1
        else:raise AssertionError('binding mutation accepted')
    for name in ['t17-span.exe','sources.tsv']:
        original=next(x for x in m['files'] if Path(x['path']).name==name);target=BUILD/('tampered-'+name);shutil.copyfile(original['path'],target)
        with target.open('r+b') as f:f.seek(-1,2);last=f.read(1);f.seek(-1,2);f.write(bytes([last[0]^1]))
        bad=copy.deepcopy(m);next(x for x in bad['files'] if x['path']==original['path'])['path']=str(target)
        try:binding(bad)
        except ValueError:count+=1
        else:raise AssertionError('same-identity modified file accepted')
    expected=BUILD/'expected/many.bin';p=BUILD/'tampered-output.bin'
    for data in [expected.read_bytes()+b'x',expected.read_bytes()[:-1],bytes([expected.read_bytes()[0]^1])+expected.read_bytes()[1:]]:
        p.write_bytes(data)
        try:exact(expected,p)
        except ValueError:count+=1
        else:raise AssertionError('raw mutation accepted')
    save(BUILD/'binding-negatives.json',{'passed':count,'GPU_executed':False});print(count)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['build','execute','negatives']);a=p.parse_args();BUILD.mkdir(parents=True,exist_ok=True);globals()[a.mode]()
