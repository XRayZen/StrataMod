"""T23 native emitter/control DTO host qualification, without any server/runtime."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t23'
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
COMPILED=['Strata-extensions/native/protocol/generation.hpp','Strata-extensions/native/protocol/generation.cpp',
          'Strata-extensions/tests/protocol/frame_fixture.cpp']
INTERPRETED=['Strata-extensions/control/generation_frames.py']
RECIPES=['Strata-extensions/tests/protocol/CMakeLists.txt','Strata-extensions/tests/protocol/build_verify.py',
         'Strata-extensions/tests/native/build_verify.py']

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def rows(paths):return [dict(path=str(p),sha256=sha(p)) for p in paths]

def aggregate(items):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n' for r in items).encode()).hexdigest()

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def run(args,env=None,check=True):
    r=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='strict')
    if check and r.returncode:raise RuntimeError(str(args)+'\n'+r.stdout+r.stderr)
    return r

def binding(manifest,exe):
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE or run(['git','diff','--name-only','HEAD']).stdout.strip():raise ValueError('base tracked source changed')
    for key,paths in [('compiled',COMPILED),('interpreted',INTERPRETED),('recipes',RECIPES)]:
        if manifest[key]!=rows([ROOT/p for p in paths]):raise ValueError('canonical source/recipe changed')
    if manifest['compiled_aggregate']!=aggregate(manifest['compiled']):raise ValueError('aggregate changed')
    if any(sha(row['path'])!=row['sha256'] for key in ('compiled','interpreted','recipes','inputs','tools','licenses','direct_dlls') for row in manifest[key]):raise ValueError('bound file changed')
    if sha(exe)!=manifest['artifact']['sha256'] or json.loads(run([exe,'--identity']).stdout)!={'source_sha256':manifest['compiled_aggregate']}:raise ValueError('compiled artifact changed')

def verify(manifest,exe,manifest_path):
    binding(manifest,exe);dto=load('t23_dto',EXT/'control/generation_frames.py');bundle=sha(manifest_path)
    inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text(encoding='utf-8'));first=inventory['shards'][0]
    if sha(first['prefix_path'])!=first['prefix_sha256']:raise ValueError('T03 tokenizer source changed')
    expected=dict(request_id='request-23',runtime_epoch=7,bundle_id=bundle,asset_revision=inventory['revision'],
        tokenizer_identity=first['tokenizer_metadata_sha256'],model_family='deepseek41',
        tokenizer_model=first['metadata_scalars']['tokenizer.ggml.model'],tokenizer_pre=first['metadata_scalars']['tokenizer.ggml.pre'],vocab_size=first['token_count'])
    results=[]
    def decode(lines,ctx=None):
        receiver=dto.GenerationDTO(expected if ctx is None else ctx)
        for line in lines:receiver.feed(line if isinstance(line,str) else json.dumps(line,ensure_ascii=False))
        return receiver.result()
    native={}
    for name in ('normal','empty','unicode','cancel','error','nonfinite','length'):
        lines=run([exe,name,bundle]).stdout.splitlines();native[name]=lines
        ctx=dict(expected)
        if name=='unicode':ctx['request_id']='要求"\\\n\t23'
        result=decode(lines,ctx);ids=[] if name=='empty' else [0,17] if name in ('cancel','error','nonfinite') else [0,17,129279]
        finish=name if name in ('cancel','error','nonfinite','length') else 'stop'
        digest=hashlib.sha256(b''.join(struct.pack('<I',v) for v in ids)).hexdigest()
        if result!=dict(context=ctx,original_token_ids=tuple(ids),generated_count=len(ids),finish=finish,
                       generation_success=finish in ('stop','length'),ids_sha256=digest):raise ValueError('native original ID/finish/escape mismatch')
        results.append(dict(name='native-'+name,passed=True))
    for name in ('before-begin','after-finish','duplicate-finish','invalid-id','duplicate-begin','empty-batch'):
        if run([exe,name,bundle],check=False).returncode==0:raise ValueError('native invalid frame state accepted')
        results.append(dict(name='native-'+name+'-rejected',passed=True))
    baseline=[json.loads(line) for line in native['normal']]
    def reject(name,mutator,ctx=None):
        frames=copy.deepcopy(baseline);mutator(frames)
        try:decode(frames,ctx)
        except (ValueError,UnicodeError):results.append(dict(name=name,passed=True))
        else:raise ValueError('invalid protocol accepted: '+name)
    reject('missing-begin',lambda f:f.pop(0));reject('missing-finish',lambda f:f.pop())
    reject('missing-token-batch',lambda f:f.pop(1));reject('duplicate-token-batch',lambda f:f.insert(2,f[1]))
    reject('reordered-token-batch',lambda f:f.__setitem__(slice(1,3),f[1:3][::-1]))
    reject('duplicate-begin',lambda f:f.insert(1,f[0]));reject('duplicate-finish',lambda f:f.append(f[-1]))
    reject('token-after-finish',lambda f:f.append(f[1]))
    mutations=[('id-integrity',1,'ids',[0,18]),('id-bool',1,'ids',[True,17]),('id-float',1,'ids',[0.0,17]),
        ('id-negative',1,'ids',[-1]),('id-oor',1,'ids',[129280]),('empty-ids',1,'ids',[]),
        ('origin-retokenized',1,'origin','re-tokenized'),('origin-synthetic',1,'origin','synthetic'),
        ('seq-float',1,'sequence',0.0),('seq-bool',1,'sequence',False),('seq-gap',1,'sequence',1),
        ('epoch-mismatch',1,'runtime_epoch',8),('epoch-bool',1,'runtime_epoch',True),('epoch-float',1,'runtime_epoch',7.0),
        ('request-mismatch',1,'request_id','other'),('unknown-schema',1,'schema','unknown'),('unknown-kind',1,'kind','heartbeat'),
        ('count-mismatch',3,'generated_count',2),('count-bool',3,'generated_count',True),('count-float',3,'generated_count',3.0),
        ('count-null',3,'generated_count',None),('hash-mismatch',3,'ids_sha256','0'*64),('finish-invalid',3,'finish','DONE'),
        ('wrong-family',0,'model_family','qwen4exp'),('wrong-asset',0,'asset_revision','0'*40),
        ('wrong-tokenizer',0,'tokenizer_pre','qwen2'),('wrong-tokenizer-hash',0,'tokenizer_identity','0'*64),
        ('wrong-bundle',0,'bundle_id','0'*64),('vocab-float',0,'vocab_size',129280.0)]
    for name,index,key,value in mutations:reject(name,lambda f,i=index,k=key,v=value:f[i].__setitem__(k,v))
    reject('missing-count',lambda f:f[-1].pop('generated_count'))
    reject('extra-token-field',lambda f:f[1].__setitem__('text','re-tokenization is not an ID source'))
    for key,value in [('runtime_epoch',False),('runtime_epoch',7.0),('vocab_size',129280.0),('tokenizer_pre','deepseek3')]:
        wrong=dict(expected,**{key:value});reject('strict-expected-'+key+'-'+str(value),lambda _:None,wrong)
    raw=list(native['normal']);raw[0]=raw[0].replace('"runtime_epoch":7','"runtime_epoch":7,"runtime_epoch":7')
    try:decode(raw)
    except ValueError:results.append(dict(name='duplicate-json-key-rejected',passed=True))
    else:raise ValueError('duplicate JSON key passed')
    # Zero is an actual generated count, not a fallback for absent metadata.
    zero=[json.loads(line) for line in native['empty']];zero[-1].pop('generated_count')
    try:decode(zero)
    except ValueError:results.append(dict(name='empty-missing-count-rejected',passed=True))
    else:raise ValueError('missing zero count passed')
    for field in ('source','binary','input','aggregate'):
        wrong=copy.deepcopy(manifest)
        if field=='source':wrong['compiled'][0]['sha256']='0'*64
        elif field=='binary':wrong['artifact']['sha256']='0'*64
        elif field=='input':wrong['inputs'][0]['sha256']='0'*64
        else:wrong['compiled_aggregate']='0'*64
        try:binding(wrong,exe)
        except ValueError:results.append(dict(name=field+'-binding-rejected',passed=True))
        else:raise ValueError('binding alteration passed')
    binding(manifest,exe)
    return dict(scope='T23 host protocol/DTO fixtures only; actual producer/owner/server integration unqualified',
                count=len(results),cases=results,manifest_sha256=bundle,artifact_sha256=sha(exe),pre_post_binding_equal=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    bundle=BUILD/'bundle';exe=bundle/'t23_frames.exe';manifest_path=bundle/'manifest.json'
    if args.verify_only:print(json.dumps(verify(json.loads(manifest_path.read_text(encoding='utf-8')),exe,manifest_path)));return
    BUILD.mkdir(exist_ok=True);bundle.mkdir(exist_ok=True)
    helper=load('t23_tools',EXT/'tests/native/build_verify.py');tools,env=helper.toolchain(BUILD)
    compiled=rows([ROOT/p for p in COMPILED]);identity=aggregate(compiled);cmake_build=BUILD/'cmake-native'
    configured=run([tools['cmake'],'-S',Path(__file__).parent,'-B',cmake_build,'-G','Ninja',
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',
        f"-DCMAKE_CXX_COMPILER={tools['compiler'].as_posix()}",f"-DCMAKE_RC_COMPILER={tools['resource_compiler'].as_posix()}",
        f"-DCMAKE_MT={tools['manifest_tool'].as_posix()}",f"-DCMAKE_LINKER={tools['linker'].as_posix()}",
        f"-DCMAKE_MAKE_PROGRAM={tools['ninja'].as_posix()}",f'-DT23_SOURCE_SHA={identity}'],env)
    (BUILD/'configure.log').write_text(configured.stdout+configured.stderr,encoding='utf-8')
    built=run([tools['cmake'],'--build',cmake_build,'--verbose'],env)
    with (BUILD/'build.log').open('a',encoding='utf-8') as f:f.write(built.stdout+built.stderr)
    shutil.copy2(cmake_build/'t23_frames.exe',exe)
    imports=run([tools['dumpbin'],'/DEPENDENTS',exe]).stdout;(BUILD/'direct-imports.txt').write_text(imports,encoding='utf-8')
    dlls=[Path(os.environ['SystemRoot'])/'System32'/n for n in sorted(set(re.findall(r'^\s+([\w.-]+\.dll)\s*$',imports,re.M|re.I)))]
    inventory_path=EXT/'tests/artifact/header-inventory.json';first=json.loads(inventory_path.read_text(encoding='utf-8'))['shards'][0]
    manifest=dict(schema='strata-ext-t23-host/v1',upstream_base=BASE,compiled=compiled,compiled_aggregate=identity,
        interpreted=rows([ROOT/p for p in INTERPRETED]),recipes=rows([ROOT/p for p in RECIPES]),
        inputs=rows([inventory_path,Path(first['prefix_path'])]),tools=rows(list(tools.values())+[Path(sys.executable)]),
        licenses=rows([ROOT/'LICENSE']),direct_dlls=rows(dlls),artifact=dict(path=str(exe),sha256=sha(exe)),
        scope='Native original IDs/frame integrity fixture; no actual generation/owner authority/server qualification')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result=verify(manifest,exe,manifest_path);(bundle/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
