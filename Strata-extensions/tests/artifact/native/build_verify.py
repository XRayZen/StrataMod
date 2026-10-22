"""T08 isolated host reader build and exact artifact/fixture validation."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import copy

ROOT=Path(__file__).resolve().parents[4]
EXT=ROOT/'Strata-extensions'
BUILD=ROOT/'build-deepseek-t08'
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
OWN=['Strata-extensions/native/artifact/native_reader.hpp','Strata-extensions/native/artifact/native_reader.cpp',
     'Strata-extensions/tests/artifact/native/reader_main.cpp']
VENDOR=['include/strata/artifact/gguf_reader.hpp','include/strata/artifact/dequant.hpp',
        'include/strata/artifact/gguf_split.hpp','include/strata/core/geometry.hpp','include/strata/artifact/model_family.hpp']
RECIPES=['Strata-extensions/tests/artifact/native/CMakeLists.txt',
         'Strata-extensions/tests/artifact/native/build_verify.py','Strata-extensions/tests/native/build_verify.py',
         'Strata-extensions/native/artifact/acquire.py','Strata-extensions/native/artifact/gguf.py']


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def run(args,env=None,ok=True):
    r=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if ok and r.returncode:raise RuntimeError(str(args)+'\n'+r.stdout+'\n'+r.stderr)
    return r


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def files(paths):return [dict(path=str(p),sha256=sha(p)) for p in paths]


def aggregate(rows):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n' for r in rows).encode()).hexdigest()


def string(s):
    b=s.encode();return struct.pack('<Q',len(b))+b


def synthetic(path,*,offset=0,dims=(32,2),dtype=39,split_no=0,split_count=1,total=1,name='w',names=None):
    names=[name] if names is None else names
    b=b'GGUF'+struct.pack('<IQQ',3,len(names),3)
    for k,v in [('split.no',split_no),('split.count',split_count),('split.tensors.count',total)]:
        b+=string(k)+struct.pack('<IQ',10,v)
    for name in names:b+=string(name)+struct.pack('<I',len(dims))+struct.pack('<'+'Q'*len(dims),*dims)+struct.pack('<IQ',dtype,offset)
    path.write_bytes(b+bytes((-len(b))%32));return path


def prepare():
    directory=BUILD/'tests';directory.mkdir(parents=True,exist_ok=True)
    inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text(encoding='utf-8'))
    original=directory/'nine-prefixes.tsv'
    original.write_text(''.join(str(s['bytes'])+'\t'+s['prefix_path']+'\n' for s in inventory['shards']),encoding='utf-8')
    vectors=json.loads((EXT/'tests/numerics/known-vectors.json').read_text(encoding='utf-8'))
    for i,row in enumerate(vectors['decode']):(directory/f'vector-{i}.bin').write_bytes(bytes.fromhex(row['hex']))
    for name,kwargs in [('good',{}),('unaligned',dict(offset=1)),('blockshape',dict(dims=(31,2))),
                        ('unknown',dict(dtype=117)),('outside',dict(offset=8192)),
                        ('zero',dict(dims=(0,))),('overflow',dict(dims=(32,2**63,2**63))),
                        ('missing',dict(split_count=2)),('wrongtotal',dict(total=2)),
                        ('overlap',dict(names=['a','b'],total=2))]:
        path=synthetic(directory/f'{name}.gguf',**kwargs)
        (directory/f'{name}.tsv').write_text('4096\t'+str(path)+'\n',encoding='utf-8')
    (directory/'duplicate-split.tsv').write_text((directory/'good.tsv').read_text()*2,encoding='utf-8')
    duplicate=[]
    for i in (0,1):duplicate.append(synthetic(directory/f'duplicate-{i}.gguf',split_no=i,split_count=2,total=2))
    (directory/'duplicate.tsv').write_text(''.join('4096\t'+str(p)+'\n' for p in duplicate),encoding='utf-8')
    (directory/'short.bin').write_bytes(b'1234')
    return directory


def binding(manifest,exe):
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE or run(['git','diff','--name-only','HEAD']).stdout.strip():
        raise ValueError('fixed upstream source changed')
    if (manifest['owned']!=files([ROOT/p for p in OWN]) or manifest['vendor']!=files([ROOT/p for p in VENDOR])
            or manifest['recipes']!=files([ROOT/p for p in RECIPES])
            or manifest['owned_aggregate']!=aggregate(manifest['owned'])):
        raise ValueError('canonical source/recipe binding changed')
    if any(sha(row['path'])!=row['sha256'] for key in ('owned','vendor','recipes','inputs','tools','licenses','direct_dlls') for row in manifest[key]):
        raise ValueError('source/input/tool/notice binding changed')
    if sha(exe)!=manifest['artifact']['sha256'] or json.loads(run([exe,'--identity']).stdout)['source_sha256']!=manifest['owned_aggregate']:
        raise ValueError('artifact compiled identity changed')


def verify(manifest,exe):
    binding(manifest,exe);directory=BUILD/'tests';results=[]
    # Enforce the API's strict-prefix caller condition using the fixed T03
    # validator in its own process; no sys.path/monkeypatch changes are needed.
    run([sys.executable,'-B','-X','utf8',EXT/'native/artifact/acquire.py',
         '--raw-root','C:/Develop/AI/Strata-data/records/deepseek-v41/t03-20261021',
         '--receipt-root',EXT/'tests/artifact','--verify'])
    results.append(dict(name='T03-strict-prefix-and-fixture-caller-condition',passed=True))
    def case(name,args,expected_ok=True):
        result=run([exe]+args,ok=False)
        if (result.returncode==0)!=expected_ok:raise ValueError(name+': unexpected result '+result.stdout+result.stderr)
        results.append(dict(name=name,passed=True));return json.loads(result.stdout) if expected_ok else None
    inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text(encoding='utf-8'))
    indexed=case('all-nine-prefix-native-index',['--index',directory/'nine-prefixes.tsv'])
    wanted=[dict(shard_index=s['index'],name=t['name'],type_id=t['type_id'],dims_ggml=t['dims_ggml'],row_bytes=t['row_bytes'],absolute_offset=t['absolute_offset'],bytes=t['bytes']) for s in inventory['shards'] for t in s['tensors']]
    if indexed['tensors']!=wanted:raise ValueError('native index does not match all1043 source spans')
    for name in ['unaligned','blockshape','unknown','outside','zero','overflow','missing','wrongtotal','duplicate','duplicate-split','overlap']:
        case(name,['--index',directory/f'{name}.tsv'],False)
    case('synthetic-good',['--index',directory/'good.tsv'])
    vectors=json.loads((EXT/'tests/numerics/known-vectors.json').read_text(encoding='utf-8'))
    for i,row in enumerate(vectors['decode']):
        length=len(bytes.fromhex(row['hex']))
        got=case(row['name'],['--decode',row['type_id'],directory/f'vector-{i}.bin',0,length,0,length])
        values=[struct.unpack('<f',bytes.fromhex(bits)[::-1])[0] for bits in got['bits']]
        classes=['nan' if math.isnan(v) else ('-inf' if v<0 else '+inf') if math.isinf(v) else 'finite' for v in values]
        if got['classes']!=classes:raise ValueError('native classes disagree with output bits')
        observed=classes if 'expected_class' in row else got['bits']
        if observed!=row.get('expected_class',row.get('expected_fp32_bits')):raise ValueError(row['name']+': literal oracle mismatch')
    q=load('t08_independent_q',EXT/'tests/numerics/reference.py')
    fixtures=json.loads((EXT/'tests/artifact/fixture-receipts.json').read_text(encoding='utf-8'))['fixtures']
    for i,f in enumerate(fixtures):
        size={0:4,8:34,39:17,43:33}[f['type_id']]
        for position in (0,f['bytes']-size):
            got=case(f['tensor']+f'-block-{position}',['--decode',f['type_id'],f['fixture_path'],f['absolute_offset'],f['bytes'],f['absolute_offset']+position,size])
            with Path(f['fixture_path']).open('rb') as stream:stream.seek(position);raw=stream.read(size)
            if got['bits']!=[q.fp32_bits(v) for v in q.decode_block(f['type_id'],raw)]:raise ValueError('independent real block mismatch')
        if f['bytes']>f['row_bytes']:
            position=f['row_bytes']-size
            got=case(f['tensor']+'-row-cross',['--decode',f['type_id'],f['fixture_path'],f['absolute_offset'],f['bytes'],f['absolute_offset']+position,size*2])
            with Path(f['fixture_path']).open('rb') as stream:stream.seek(position);raw=stream.read(size*2)
            expected=[q.fp32_bits(v) for n in (0,size) for v in q.decode_block(f['type_id'],raw[n:n+size])]
            if got['bits']!=expected:raise ValueError('row-cross block mismatch')
        out=BUILD/f'copy-{i}.bin'
        case(f['tensor']+'-lossless-copy',['--copy',f['fixture_path'],f['absolute_offset'],f['bytes'],f['absolute_offset'],f['bytes'],out])
        if sha(out)!=f['fixture_sha256']:raise ValueError('raw native staging changed bits')
        case(f['tensor']+'-logical-underflow',['--decode',f['type_id'],f['fixture_path'],f['absolute_offset'],f['bytes'],max(0,f['absolute_offset']-1),size],False)
    case('physical-short-source',['--decode',39,directory/'short.bin',0,17,0,17],False)
    case('partial-block',['--decode',39,directory/'vector-3.bin',0,17,0,16],False)
    case('logical-view-overflow',['--decode',39,directory/'vector-3.bin',2**64-1,17,2**64-1,17],False)
    case('logical-read-overrun',['--decode',39,directory/'vector-3.bin',100,17,101,17],False)
    for field in ('source','binary','receipt','aggregate'):
        wrong=copy.deepcopy(manifest)
        if field=='source':wrong['owned'][0]['sha256']='0'*64
        elif field=='binary':wrong['artifact']['sha256']='0'*64
        elif field=='receipt':wrong['inputs'][0]['sha256']='0'*64
        else:wrong['owned_aggregate']='0'*64
        try:binding(wrong,exe)
        except ValueError:results.append(dict(name=field+'-binding-change',passed=True))
        else:raise ValueError('binding mutation passed')
    binding(manifest,exe)
    return dict(scope='Windows host native reader/scalar; no HIP/GPU/fullmodel',cases=results,count=len(results))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    bundle=BUILD/'bundle';exe=bundle/'t08_reader.exe';manifest_path=bundle/'manifest.json'
    if args.verify_only:
        result=verify(json.loads(manifest_path.read_text(encoding='utf-8')),exe);print(json.dumps(result));return
    BUILD.mkdir(exist_ok=True);bundle.mkdir(exist_ok=True)
    helper=load('t08_fixed_t06_tools',EXT/'tests/native/build_verify.py');tools,env=helper.toolchain(BUILD)
    owned=files([ROOT/p for p in OWN]);identity=aggregate(owned)
    cmake_build=BUILD/'cmake-native'
    configure=run([tools['cmake'],'-S',Path(__file__).parent,'-B',cmake_build,'-G','Ninja',
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',
        f"-DCMAKE_CXX_COMPILER={tools['compiler'].as_posix()}",f"-DCMAKE_RC_COMPILER={tools['resource_compiler'].as_posix()}",
        f"-DCMAKE_MT={tools['manifest_tool'].as_posix()}",f"-DCMAKE_LINKER={tools['linker'].as_posix()}",
        f"-DCMAKE_MAKE_PROGRAM={tools['ninja'].as_posix()}",f'-DT08_SOURCE_SHA={identity}'],env)
    built=run([tools['cmake'],'--build',cmake_build],env)
    (BUILD/'build.log').write_text(configure.stdout+configure.stderr+built.stdout+built.stderr,encoding='utf-8')
    shutil.copy2(cmake_build/'t08_reader.exe',exe)
    shutil.copy2(EXT/'native/artifact/NOTICE.md',bundle/'NOTICE.md')
    directory=prepare()
    inputs=list(directory.iterdir())+[EXT/'tests/artifact'/p for p in ('source-files.json','header-inventory.json','fixture-receipts.json')]+[EXT/'tests/numerics'/p for p in ('reference.py','reference-contract.json','known-vectors.json')]+[EXT/'native/artifact/quant_layouts.json']
    inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text(encoding='utf-8'))
    inputs += [Path(s['prefix_path']) for s in inventory['shards']]
    inputs += [Path(f['fixture_path']) for f in json.loads((EXT/'tests/artifact/fixture-receipts.json').read_text(encoding='utf-8'))['fixtures']]
    imports=run([tools['dumpbin'],'/DEPENDENTS',exe]).stdout
    dlls=[Path(os.environ['SystemRoot'])/'System32'/n for n in sorted(set(re.findall(r'^\s+([\w.-]+\.dll)\s*$',imports,re.M|re.I)))]
    manifest=dict(schema='strata-ext-t08-host/v1',upstream_base=BASE,owned=owned,owned_aggregate=identity,
                  vendor=files([ROOT/p for p in VENDOR]),recipes=files([ROOT/p for p in RECIPES]),
                  inputs=files(inputs),tools=files(list(tools.values())+[Path(sys.executable)]),python_version=sys.version,licenses=files([ROOT/'LICENSE',ROOT/'third_party/ggml/LICENSE',EXT/'native/artifact/NOTICE.md',bundle/'NOTICE.md']),
                  direct_dlls=files(dlls),artifact=dict(path=str(exe),sha256=sha(exe)),
                  scope='Original logical spans from strict/SHA-bound T03 prefixes; bounded views only; no fullsource/GPU qualification')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result=verify(manifest,exe)
    (bundle/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
