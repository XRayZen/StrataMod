"""T34 isolated host measurement API; no GPU, server, or runtime gate."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
EXT=ROOT/'Strata-extensions'
BUILD=ROOT/'build-deepseek-t34'
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
OWN=['Strata-extensions/native/stats/measurement.hpp','Strata-extensions/native/stats/measurement.cpp',
     'Strata-extensions/tests/measurement/measurement_fixture.cpp']
RECIPES=['Strata-extensions/tests/measurement/CMakeLists.txt','Strata-extensions/tests/measurement/build_verify.py',
         'Strata-extensions/tests/native/build_verify.py']
CASES=['counter-delta','physical-zero','physical-unknown','same-sequence-rejected','reverse-sequence-rejected',
       'counter-reset-rejected','physical-reset-rejected','counter-source-rejected','counter-source-missing']+[f'identity-mismatch-{i}' for i in range(6)]+[
       'metadata-hash-rejected','metadata-phase-rejected','ledger-single-gauge-total','ledger-pinned-subset',
       'ledger-duplicate-device','ledger-overflow','ledger-no-implicit-add','host-duration-and-byte-rate',
       'host-reverse','host-zero-denominator','host-low-resolution','host-no-resolution','host-domain-mismatch',
       'host-incomplete','host-negative-stamp','same-device-event','cross-device-event','event-incomplete',
       'event-nan','event-inf','event-negative','event-zero','amplification-zero-useful','amplification-literal',
       'thread-sum-not-wall']

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def rows(paths):return [dict(path=str(p),sha256=sha(p)) for p in paths]

def aggregate(items):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n' for r in items).encode()).hexdigest()

def run(args,env=None,check=True):
    result=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if check and result.returncode:raise RuntimeError(str(args)+'\n'+result.stdout+result.stderr)
    return result

def binding(manifest,exe):
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE or run(['git','diff','--name-only','HEAD']).stdout.strip():
        raise ValueError('fixed upstream changed')
    if (manifest['owned']!=rows([ROOT/p for p in OWN]) or manifest['recipes']!=rows([ROOT/p for p in RECIPES])
            or manifest['owned_aggregate']!=aggregate(manifest['owned'])):raise ValueError('source/recipe changed')
    if any(sha(r['path'])!=r['sha256'] for k in ('owned','recipes','inputs','tools','licenses','direct_dlls') for r in manifest[k]):
        raise ValueError('manifest file binding changed')
    if sha(exe)!=manifest['artifact']['sha256'] or json.loads(run([exe,'--identity']).stdout)!={'source_sha256':manifest['owned_aggregate']}:
        raise ValueError('compiled artifact changed')

def validate_read(read,fixture,bundle_sha):
    wanted=dict(bytes=20480,fixture_sha256=fixture['fixture_sha256'],asset_sha256=fixture['file_lfs_sha256'],
                bundle_sha256=bundle_sha,request_id='t34-host-read',epoch=0,phase='startup',physical_io=None)
    if any(type(read.get(k)) is not type(v) or read[k]!=v for k,v in wanted.items()):raise ValueError('actual read binding/schema changed')
    for k in ('start_ns','end_ns','resolution_ns'):
        if type(read[k]) is not int or read[k]<0:raise ValueError('invalid clock output schema')
    elapsed=read['end_ns']-read['start_ns']
    if read['seconds'] is not None:
        if (type(read['seconds']) not in (int,float) or not math.isfinite(read['seconds']) or read['seconds']<=0
                or read['resolution_ns']<=0 or elapsed<=0 or elapsed<read['resolution_ns'] or read['seconds']!=elapsed/1e9):
            raise ValueError('invalid measured host duration')
    elif elapsed>0 and read['resolution_ns']>0 and elapsed>=read['resolution_ns']:raise ValueError('valid duration unexpectedly absent')

def verify(manifest,exe,manifest_path):
    binding(manifest,exe)
    receipt=json.loads((EXT/'tests/artifact/fixture-receipts.json').read_text(encoding='utf-8'))
    fixture=next(r for r in receipt['fixtures'] if r['tensor']=='output_norm.weight')
    if sha(fixture['fixture_path'])!=fixture['fixture_sha256']:raise ValueError('norm raw identity changed')
    output=json.loads(run([exe,fixture['fixture_path'],fixture['fixture_sha256'],fixture['file_lfs_sha256'],sha(manifest_path)]).stdout)
    if output['cases']!=CASES or type(output['count']) is not int or output['count']!=len(CASES):raise ValueError('native cases missing/duplicated')
    read=output['actual_read'];validate_read(read,fixture,sha(manifest_path))
    results=[dict(name=name,passed=True) for name in CASES]+[dict(name='real-norm-bounded-read',passed=True)]
    for field in ('zero-resolution','zero-elapsed','under-resolution','nonfinite-seconds'):
        wrong=copy.deepcopy(read)
        # A declared valid interval is the control, even on a coarse-clock run.
        wrong.update(start_ns=100,end_ns=200,resolution_ns=1,seconds=1e-7)
        if field=='zero-resolution':wrong['resolution_ns']=0
        elif field=='zero-elapsed':wrong['end_ns']=100
        elif field=='under-resolution':wrong['resolution_ns']=101
        else:wrong['seconds']=float('inf')
        try:validate_read(wrong,fixture,sha(manifest_path))
        except ValueError:results.append(dict(name='observed-'+field+'-rejected',passed=True))
        else:raise ValueError('invalid observed clock accepted')
    # Invalid fixture paths and physical sizes cannot produce successful output.
    for name,path in [('missing',BUILD/'absent.bin'),('short',BUILD/'short.bin')]:
        result=run([exe,path,fixture['fixture_sha256'],fixture['file_lfs_sha256'],sha(manifest_path)],check=False)
        if result.returncode==0 or result.stdout:raise ValueError('bad physical source accepted')
        results.append(dict(name='real-read-'+name+'-rejected',passed=True))
    for field in ('source','binary','input','aggregate'):
        wrong=copy.deepcopy(manifest)
        if field=='source':wrong['owned'][0]['sha256']='0'*64
        elif field=='binary':wrong['artifact']['sha256']='0'*64
        elif field=='input':wrong['inputs'][0]['sha256']='0'*64
        else:wrong['owned_aggregate']='0'*64
        try:binding(wrong,exe)
        except ValueError:results.append(dict(name=field+'-binding-rejected',passed=True))
        else:raise ValueError('binding mutation accepted')
    binding(manifest,exe)
    return dict(scope='Windows host measurement API/fixtures only; no GPU/token/server qualification',cases=results,
                count=len(results),actual_read=read,manifest_sha256=sha(manifest_path),artifact_sha256=sha(exe),pre_post_binding_equal=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    bundle=BUILD/'bundle';manifest_path=bundle/'manifest.json';exe=bundle/'t34_measurement.exe'
    if args.verify_only:
        print(json.dumps(verify(json.loads(manifest_path.read_text(encoding='utf-8')),exe,manifest_path)));return
    BUILD.mkdir(exist_ok=True);bundle.mkdir(exist_ok=True)
    spec=importlib.util.spec_from_file_location('t34_t06_tools',EXT/'tests/native/build_verify.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);tools,env=helper.toolchain(BUILD)
    owned=rows([ROOT/p for p in OWN]);identity=aggregate(owned);cmake_build=BUILD/'cmake-native'
    configure=run([tools['cmake'],'-S',Path(__file__).parent,'-B',cmake_build,'-G','Ninja',
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',
        f"-DCMAKE_CXX_COMPILER={tools['compiler'].as_posix()}",f"-DCMAKE_RC_COMPILER={tools['resource_compiler'].as_posix()}",
        f"-DCMAKE_MT={tools['manifest_tool'].as_posix()}",f"-DCMAKE_LINKER={tools['linker'].as_posix()}",
        f"-DCMAKE_MAKE_PROGRAM={tools['ninja'].as_posix()}",f'-DT34_SOURCE_SHA={identity}'],env)
    (BUILD/'configure.log').write_text(configure.stdout+configure.stderr,encoding='utf-8')
    built=run([tools['cmake'],'--build',cmake_build,'--verbose'],env)
    with (BUILD/'build.log').open('a',encoding='utf-8') as log:log.write(built.stdout+built.stderr)
    shutil.copy2(cmake_build/'t34_measurement.exe',exe)
    (BUILD/'short.bin').write_bytes(b'1234')
    receipt_path=EXT/'tests/artifact/fixture-receipts.json'
    fixture=next(r for r in json.loads(receipt_path.read_text(encoding='utf-8'))['fixtures'] if r['tensor']=='output_norm.weight')
    imported=run([tools['dumpbin'],'/DEPENDENTS',exe]).stdout
    dlls=[Path(os.environ['SystemRoot'])/'System32'/n for n in sorted(set(re.findall(r'^\s+([\w.-]+\.dll)\s*$',imported,re.M|re.I)))]
    (BUILD/'direct-imports.txt').write_text(imported,encoding='utf-8')
    manifest=dict(schema='strata-ext-t34-host/v1',upstream_base=BASE,owned=owned,owned_aggregate=identity,
        recipes=rows([ROOT/p for p in RECIPES]),inputs=rows([receipt_path,Path(fixture['fixture_path']),BUILD/'short.bin']),
        tools=rows(list(tools.values())+[Path(sys.executable)]),licenses=rows([ROOT/'LICENSE']),direct_dlls=rows(dlls),
        artifact=dict(path=str(exe),sha256=sha(exe)),scope='Host byte/clock/gauge API only; no runtime or token qualification')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result=verify(manifest,exe,manifest_path)
    (bundle/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
