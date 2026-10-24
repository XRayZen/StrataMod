"""Fixed probe and three-arm/two-RefImage encoder protocol; no hidden launches."""
from array import array
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import time

from . import manifest
from serve.stratamod.amd_vision.environment import windows_hip_env,reserve_args

SDK=manifest.ROOT/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
LEGACY_HIP_EXE=SDK/'bin/strata-vision-hip-v2-3707a62c9bea.exe'
HIP_EXE=manifest.ROOT/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel/bin/strata-vision-hip-m3-b2c8ee3ac9df.exe'
LEGACY_CPU_EXE=manifest.ROOT/'.vision-build/cpu-reference-2/bin/strata-vision-v2-4406416bd3d7.exe'
CPU_EXE=manifest.ROOT/'.vision-build/amd-vision-m3-c55e049b8c07/cpu/strata-vision-m3-e5be8b263e3b.exe'
REPAIR=manifest.ROOT/'.vision-tmp/vision-probe-repair-v2-receipt.json'
REPAIR_SHA='321d9a87ece6e9fec7f445ec0a54a04fd5b8995ab5bd3c88aa1f7c3b3d09ee9e'
MM_PROJ=manifest.DATA/'vision-sidecars/ista/mmproj-Qwen3.8-Flash-Next-BF16.gguf'
FIXTURES=manifest.ROOT.parent/'RefImage'
INPUT_INVENTORY=manifest.ROOT/'.vision-tmp/records/refimage-transition-20261018-v1/refimage-inventory.json'
INPUT_INVENTORY_SHA='e9e3e5e993d83978895506218e2224e17d5ddb1fcb10606c8a8c0ea6af7327d4'
MM_PROJ_SHA='b1a82259702816a5330d7bd7607cd9676b11780e79ff7348c21103ff3ce49bd0'
LEGACY_HIP_SHA='3707a62c9bea3175de8de5211b6615b7eeeceae93cffc633f5fb8def1a7bc988'
HIP_SHA='b2c8ee3ac9df0f65aa5ee17dea9e636f1cbbaa5eb4e6052c58084ae20282b0c4'
LEGACY_CPU_SHA='4406416bd3d7cfbdb1c38b8ab80736cbd32ec229bb13eb2960b40dd741631945'
CPU_SHA='e5be8b263e3bfacf7b34997d3505d6bc1a37c77d2a08432d8a18870f3456152f'
NODE=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
EDGE=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
PLAYWRIGHT=NODE.parent.parent/'node_modules/playwright'
WEBUI=manifest.ROOT/'tools/vision/webui_upload.mjs'
API_BINDING=manifest.ROOT/'.vision-tmp/image-api-refimage-v1-binding.json'
IMAGES=(('07','07.png','b3d0707f0812a413c9f8e017bcd40452fac7136174498db5c5d3b3e995c3b759'),
        ('48463779','48463779.jpeg','1806c40d735545d6852e1d1a90dba9c22f4501e79e9cb5784f93268e2331d699'))


def probe_command():
    return [str(HIP_EXE),'--list-devices','--require-hip']


def environment(directory,ordinal,inherited):
    base=manifest.normalized_environment(dict(log=str(Path(directory)/'engine.log')),inherited)
    base.pop('__PYVENV_LAUNCHER__',None)
    value=windows_hip_env(dict(rocm_root=str(SDK),exe=str(HIP_EXE),hip_device=0 if ordinal is None else ordinal,
                               temp_dir=str(Path(directory)/'tmp')),base)
    if ordinal is None:
        value.pop('HIP_VISIBLE_DEVICES',None)
    return value


def encode_command(arm,model):
    if arm not in ('cpu-aa1','cpu-aa2','hip'):
        raise RuntimeError('Unknown fixed encoder arm')
    command=[str(HIP_EXE if arm=='hip' else CPU_EXE),'--mmproj',str(MM_PROJ),'--model',str(model),
             '--threads','4','--max-tokens','300','--flash-attn','off','--trace-graph']
    if arm=='hip': command+=['--gpu','--require-hip']
    return command


def encode_protocol():
    return [dict(arm=arm,ready_deadline_seconds=300,
                 encodes=[dict(name=name,path=str(FIXTURES/file),sha256=sha,deadline_seconds=60)
                          for name,file,sha in IMAGES]) for arm in ('cpu-aa1','cpu-aa2','hip')]


def phase_config(suite,directory,base,probe=None):
    if suite not in ('vision-probe','vision-encode'):
        raise RuntimeError('Unknown fixed standalone vision phase')
    model=base['args'][base['args'].index('--native')+1]
    ordinal=None
    if suite=='vision-encode':
        if (not probe or type(probe.get('ordinal')) is not int or probe['ordinal']<0
                or probe.get('arch')!='gfx1201' or not probe.get('pci')):
            raise RuntimeError('A validated unique SDK ordinal/PCI probe is required before encode')
        ordinal=probe['ordinal']
    commands=([probe_command()] if suite=='vision-probe' else
              [encode_command(arm,model) for arm in ('cpu-aa1','cpu-aa2','hip')])
    return dict(phase=suite,commands=commands,model=model,mmproj=str(MM_PROJ),ordinal=ordinal,
                cwd=str(SDK/'bin'),log=str(Path(directory)/'vision.log'),
                protocol=(dict(deadline_seconds=30) if suite=='vision-probe' else encode_protocol()),
                execution='foreground guarded evaluation; no background serve authority')


def dependencies(base):
    # This bounded list is the approved image build closure, not a SDK catalog.
    build=manifest.ROOT/'.vision-tmp/all-backend-build-receipt.json'
    vsr=manifest.ROOT/'.vision-tmp/vision-vsr01-binding.json'
    if (manifest.digest(build)!='93fe4af75843b1a6d7abb57050911d1459e71bb4b0525785b6f58fad920b70bf'
            or manifest.digest(vsr)!='02578e9d88523887cdb642c5541677b35b1202607871696ac034d3da8a6891f8'):
        raise RuntimeError('Pinned original image build/binding receipt changed')
    receipt=manifest.read_json(build)
    for name,meta in receipt['sdk_files'].items():
        manifest.local_path(SDK/name)
    repair=native_repair_pins()
    for path in (HIP_EXE,CPU_EXE,*repair,INPUT_INVENTORY):
        manifest.local_path(path)
    native=Path(base['args'][base['args'].index('--native')+1])
    pack=Path(base['args'][base['args'].index('--pack')+1])
    return [build,vsr,manifest.ROOT/'.vision-tmp/sdk-install.json',manifest.ROOT/'.vision-tmp/model-vision-binding.json',
            REPAIR,*repair,HIP_EXE,CPU_EXE,MM_PROJ,SDK/'include/hip/hip_version.h',*[SDK/name for name in receipt['sdk_files']],
            *sorted(native.parent.glob('*.gguf')),*sorted(path for path in pack.rglob('*') if path.is_file()),
            *[FIXTURES/file for _,file,_ in IMAGES],INPUT_INVENTORY,
            API_BINDING,manifest.ROOT/'.vision-tmp/encode-io-v1-binding.json',
            *browser_dependencies()]


def browser_dependencies():
    # Existing fixed installation only; a finite application/package closure,
    # not user profiles, downloads, or a browser/SDK discovery catalog.
    packages=(PLAYWRIGHT,PLAYWRIGHT.parent/'playwright-core')
    return [NODE,*sorted(p for p in EDGE.parent.rglob('*') if p.is_file()),
            *[p for package in packages for p in sorted(package.rglob('*')) if p.is_file()]]


def webui_config(directory):
    directory=Path(directory)
    profile=manifest.ROOT/'.vision-tmp'/('ui-'+directory.name)
    return dict(phase='vision-webui',commands=[[str(NODE),str(WEBUI)]],cwd=str(manifest.ROOT),
                log=str(directory/'webui.log'),profile_dir=str(profile),driver_root=str(PLAYWRIGHT.parent/'playwright-core'),
                browser_executables=[str(p) for p in sorted(EDGE.parent.rglob('*.exe'))
                                     if p.name.lower() in ('msedge.exe','msedge_crashpad_handler.exe')],ordinal=None)


def webui_environment(directory,inherited):
    env=manifest.normalized_environment(dict(log=str(Path(directory)/'webui.log')),inherited)
    for key in ('HIP_PATH','ROCM_PATH','HIP_DEVICE_LIB_PATH','LLVM_PATH','HIP_PLATFORM','__PYVENV_LAUNCHER__'):
        env.pop(key,None)
    env['PATH']=';'.join((str(NODE.parent),'C:\\Windows\\System32','C:\\Windows'))
    temporary=str(manifest.ROOT/'.vision-tmp'/('node-'+Path(directory).name))
    env.update(TEMP=temporary,TMP=temporary,TMPDIR=temporary,AMD_COMGR_CACHE_DIR=str(Path(temporary)/'comgr'))
    return env


def webui_input(directory):
    from tools.vision.image_api_cases import PROMPT
    return dict(url='http://127.0.0.1:18080/',browser_exe=str(EDGE),profile_dir=webui_config(directory)['profile_dir'],
                image_path=str(FIXTURES/IMAGES[1][1]),image_sha256=IMAGES[1][2],prompt=PROMPT,max_tokens=128,deadline_seconds=120)


def coexistence(encode,budget):
    """Actual measurement identity plus separately exact-approved residual input."""
    fields={'version','encode_result_sha256','pci','luid_high','luid_low','encoder_pid','encoder_created',
            'sampled_peak_process_dedicated_bytes','residual_mib','reserve_mib'}
    if set(budget)!=fields or type(budget['version']) is not int or budget['version']!=1:
        raise RuntimeError('Invalid typed coexistence receipt inventory')
    if not (encode.get('status')=='passed' and encode.get('cleanup',{}).get('status')=='passed'
            and all(encode.get(key) is True for key in ('parity_passed','coverage_passed','memory_observation_ready'))
            and encode.get('graph',{}).get('passed') is True):
        raise RuntimeError('Measured ENC parity/coverage/memory/cleanup is required before coexistence')
    hip=encode['arms'][2];rows=hip['memory_samples'];adapter=rows[-1]['gpu']['adapter']
    root=next(row for row in hip['cohort'] if Path(row['exe'])==HIP_EXE)
    peak=encode['sampled_gpu_peaks']['process_dedicated_bytes']
    for key in ('sampled_peak_process_dedicated_bytes','residual_mib','reserve_mib','encoder_pid','luid_high','luid_low'):
        if type(budget[key]) is not int or budget[key]<0:raise RuntimeError('Coexistence values must be strict nonnegative integers')
    if (type(peak) is not int or peak<0 or budget['sampled_peak_process_dedicated_bytes']!=peak
            or budget['encoder_pid']!=root['pid'] or type(budget['encoder_created']) not in (float,int)
            or isinstance(budget['encoder_created'],bool) or not math.isfinite(budget['encoder_created']) or budget['encoder_created']!=root['created']
            or any(budget[key]!=adapter[key] for key in ('luid_high','luid_low'))
            or budget['pci'].lower()!=encode['identity']['pci'].lower()):
        raise RuntimeError('Coexistence peak/birth/PCI/LUID differs from measured ENC')
    required=max(2560,math.ceil(peak/2**20)+budget['residual_mib'])
    if budget['reserve_mib']!=required or required*2**20>=adapter['dedicated_capacity_bytes']:
        raise RuntimeError('Coexistence reserve must equal measured peak plus approved residual/floor and fit the adapter')
    return dict(encode['identity'],parity_passed=True,coverage_passed=True,memory_budget_ready=True,
                reserve_mib=required,measurement='observed one-second and boundary-sampled process dedicated max, not instantaneous true peak')


def smoke_protocol():
    import base64
    from tools.vision.image_api_cases import fixed_cases
    image=FIXTURES/IMAGES[0][1]
    if manifest.digest(image)!=IMAGES[0][2]:raise RuntimeError('Original RefImage API PNG changed')
    cases=fixed_cases(base64.b64encode(image.read_bytes()).decode('ascii'),manifest.MODEL,128)
    return dict(order=['text-before','openai','anthropic','responses','webui','cancel','text-after'],
                requests=cases,deadline_seconds=120,max_tokens=128,max_generation_posts=7,
                meaning='A default-workers/spec4/async-off plus image; performance C=B+image remains pending')


def legacy_native_repair_pins():
    """One pinned repair receipt, bounded to the four approved backend builds."""
    if manifest.digest(REPAIR)!=REPAIR_SHA:raise RuntimeError('Pinned native diagnostic repair receipt changed')
    repair=manifest.read_json(REPAIR)
    original=manifest.read_json(manifest.ROOT/'.vision-tmp/all-backend-build-receipt.json')
    if (repair.get('version')!=2 or repair.get('head')!=manifest.HEAD
            or repair.get('sdk_files')!=original['sdk_files']
            or set(repair.get('builds',{}))!={'cpu','hip','cuda','sycl'}
            or set(repair.get('roles',{}))!={'cpu','hip','cuda','sycl','hip_staged'}
            or len(repair.get('executables',{}))!=5):
        raise RuntimeError('Native repair SDK/build/role inventory is inconsistent')
    pins={}
    def add(name,sha):
        path=manifest.local_path(manifest.ROOT/name)
        if path in pins and pins[path]!=sha:raise RuntimeError('Conflicting repair artifact identity')
        pins[path]=sha
    for name,sha in repair['executables'].items():add(name,sha)
    for role in repair['roles'].values():
        if pins.get(manifest.ROOT/role['path'])!=role['sha256']:
            raise RuntimeError('Native repair executable role differs from its fixed inventory')
    if pins.get(LEGACY_HIP_EXE)!=LEGACY_HIP_SHA or pins.get(LEGACY_CPU_EXE)!=LEGACY_CPU_SHA:
        raise RuntimeError('Native repair HIP/CPU selected executable changed')
    # Bind compilation inputs, not mutable work-journal snapshots recorded as
    # historical provenance in the receipt. No recursive receipt/catalog walk.
    for name in ('tools/vision/strata_vision.cpp','tools/vision/CMakeLists.txt','.vision-tmp/build-env.ps1'):
        add(name,repair['source_files'][name]['sha256'])
    for build in repair['builds'].values():
        if build.get('exit_code')!=0:raise RuntimeError('All four native builds must succeed')
        add(build['log'],build['log_sha256']);add(build['cache'],build['cache_sha256'])
    add(repair['sdk_closure_proof']['path'],repair['sdk_closure_proof']['sha256'])
    for archive in repair['archive_history']['archives']:add(archive['archive_path'],archive['sha256'])
    for name,sha in repair['archive_history']['unchanged_sdk_original'].items():add(name,sha)
    add(repair['old_source']['path'],repair['old_source']['sha256'])
    return pins


def require_fixed_dependencies(fixed):
    """Check pinned receipt metadata; the caller owns the one physical pass."""
    receipt=manifest.read_json(manifest.ROOT/'.vision-tmp/all-backend-build-receipt.json')
    pins=[(SDK/name,meta['sha256']) for name,meta in receipt['sdk_files'].items()]
    pins.extend(native_repair_pins().items())
    pins.extend(((HIP_EXE,HIP_SHA),(CPU_EXE,CPU_SHA),(MM_PROJ,MM_PROJ_SHA),
                 (SDK/'include/hip/hip_version.h','9b5f2630372e59eb14d3b3ac98c3b48f452f82c04ea4d9c76c327128f9aafebc')))
    pins.extend((FIXTURES/file,sha) for _,file,sha in IMAGES)
    pins.append((INPUT_INVENTORY,INPUT_INVENTORY_SHA))
    pins.extend((manifest.ROOT/name,sha) for name,sha in (
        ('.vision-tmp/image-api-refimage-v1-binding.json','e9de2d5fa6c2e3e7ce9834e78efb732288018cb09c688f0acccd9a449e1da97b'),
        ('.vision-tmp/encode-io-v1-binding.json','457d74288f2244f5df8ce95d1fc9947d69f0be7c24bcc0727de592bf00ef8e0f')))
    if any(fixed.get(str(path))!=sha for path,sha in pins):
        raise RuntimeError('Pinned image dependency receipt/hash changed')


def match_probe(raw,windows):
    devices=re.findall(r'^DEVICE (?:ROCm|HIP) ((?:ROCm|HIP)(\d+)) (.+?) PCI=(\S+)$',raw,re.M)
    identities=re.findall(r'HIP identity logical=(\d+) PCI=(\S+) arch=(\S+) name=(.*?) mask=(\S+)',raw)
    if len({int(row[1]) for row in devices})!=len(devices):
        raise RuntimeError('SDK device ordinal rows are duplicated/ambiguous')
    if len({int(row[0]) for row in identities})!=len(identities):
        raise RuntimeError('SDK HIP identity rows are duplicated/ambiguous')
    # Bind the complete unfiltered enumeration, not just whichever device is
    # current. No identity/name/PCI is inferred from a DEVICE row's position.
    for _,number,name,pci in devices:
        rows=[row for row in identities if int(row[0])==int(number)]
        if (len(rows)!=1 or rows[0][1].lower()!=pci.lower() or rows[0][3]!=name
                or rows[0][4]!='unfiltered' or not rows[0][2].startswith('gfx')):
            raise RuntimeError('SDK DEVICE ordinal/name/PCI and actual HIP identity do not agree')
    if {int(row[0]) for row in identities}!={int(row[1]) for row in devices}:
        raise RuntimeError('SDK DEVICE/HIP identity enumeration is incomplete')
    selected=[(int(ordinal),name,pci) for _,ordinal,name,pci in devices if 'R9700' in name]
    if len(selected)!=1:
        raise RuntimeError('R9700 SDK ordinal/PCI is absent or ambiguous')
    ordinal,name,pci=selected[0]
    exact=[row for row in identities if int(row[0])==ordinal and row[1].lower()==pci.lower()
           and row[2].split(':')[0]=='gfx1201' and row[3]==name and row[4]=='unfiltered']
    matched=[row for row in windows if str(row.get('pci','')).lower()==pci.lower()
             and 'R9700' in row.get('Name','') and 'VEN_1002&DEV_7551' in row.get('PNPDeviceID','').upper()]
    if len(exact)!=1 or len(matched)!=1:
        raise RuntimeError('SDK gfx1201/PCI and Windows R9700 identity are unconfirmed/ambiguous')
    return dict(ordinal=ordinal,pci=pci,arch=exact[0][2].split(':')[0],actual_arch=exact[0][2],name=exact[0][3],windows=matched[0])


def match_encoder_identity(raw,probe):
    rows=re.findall(r'HIP identity logical=(\d+) PCI=(\S+) arch=(\S+) name=(.*?) mask=(\S+)',raw)
    if (len(rows)!=1 or rows[0][1].lower()!=probe['pci'].lower() or rows[0][2].split(':')[0]!='gfx1201'
            or rows[0][3]!=probe['name'] or rows[0][4]!=str(probe['ordinal'])):
        raise RuntimeError('Masked encoder does not match the probed physical PCI/name/gfx')
    return dict(ordinal=int(rows[0][0]),pci=rows[0][1],arch=rows[0][2],name=rows[0][3],mask=rows[0][4])


def probe_modules(raw,modules,dependencies):
    """Only the private image runtime's used closure, never text critical-9."""
    reported=re.findall(r'strata-vision: (?:LOADED_DLL|HIP runtime DLL) (.+)',raw)
    runtime=re.findall(r'strata-vision: HIP runtime DLL (.+)',raw)
    if len(runtime)!=1 or Path(runtime[0]).name.lower()!='amdhip64_7.dll':
        raise RuntimeError('Native HIP runtime DLL role must name the actual HIP DLL, never its EXE import thunk')
    paths={str(Path(row['path']).resolve()).lower():row for row in modules}
    versions=re.findall(r'HIP runtime version (\d+)',raw)
    if len(set(versions))!=1 or int(versions[0])<=0:
        raise RuntimeError('Native HIP runtime version is unconfirmed')
    if not reported or not any(Path(path).name.lower()=='amdhip64_7.dll' for path in reported):
        raise RuntimeError('Native HIP runtime module report is absent')
    used=[]
    for name in dict.fromkeys(reported):
        path=Path(name).resolve()
        expected=next((sha for file,sha in dependencies.items() if Path(file).resolve()==path),None)
        standard=paths.get(str(path).lower())
        actual=manifest.digest(path)
        if (path.parent!=HIP_EXE.parent.resolve() or expected is None or actual!=expected
                or standard is None or not standard['matched'] or standard['sha256']!=expected):
            raise RuntimeError('Used HIP SDK module path/hash is not bound to the standard loader snapshot')
        used.append(dict(path=str(path),sha256=actual))
    # SDK package 10.1.0 ships HIP 7.16 headers; these are different version
    # namespaces. DLL full SHA binds the build, never a guessed decimal prefix.
    header=SDK/'include/hip/hip_version.h'
    return dict(sdk_package_version='10.1.0',runtime_version=int(versions[0]),hip_header=header.read_text(encoding='utf-8'),
                hip_header_sha256=manifest.digest(header),used_modules=used,
                method='native report + standard loader + manifest full SHA')


def read_sve(path):
    if Path(path).stat().st_size>20+300*2560*4:
        raise ValueError('SVE1 exceeds the fixed image cap')
    data=Path(path).read_bytes()
    if len(data)<20:
        raise ValueError('Truncated SVE1 header')
    magic,n,nx,ny,width=struct.unpack('<5i',data[:20])
    if (magic!=0x31455653 or not 0<n<=300 or nx<=0 or ny<=0 or nx*ny!=n
            or width!=2560 or len(data)!=20+n*width*4):
        raise ValueError('SVE1 shape/cap/length mismatch')
    values=array('f');values.frombytes(data[20:])
    if sys.byteorder!='little': values.byteswap()
    if not all(math.isfinite(x) for x in values):
        raise ValueError('Non-finite SVE1')
    return dict(shape=[n,nx,ny,width],values=values,sha256=manifest.digest(path))


def compare_sve(reference,candidate):
    if reference['shape']!=candidate['shape']:
        raise ValueError('CPU A/A and HIP SVE1 shape/grid mismatch')
    a,b=reference['values'],candidate['values']
    aa=math.fsum(float(x)*x for x in a);bb=math.fsum(float(x)*x for x in b)
    if not aa>0 or not bb>0:
        raise ValueError('Zero SVE1 norm')
    relative=math.sqrt(math.fsum((float(x)-y)**2 for x,y in zip(a,b))/aa)
    cosine=math.fsum(float(x)*y for x,y in zip(a,b))/math.sqrt(aa*bb)
    return dict(l2_relative=relative,cosine=cosine,passed=relative<=.02 and cosine>=.999)


def image_profile(text,receipt,directory):
    if (receipt.get('parity_passed') is not True or receipt.get('coverage_passed') is not True
            or receipt.get('memory_budget_ready') is not True or receipt.get('ordinal') is None):
        raise RuntimeError('Standalone identity/parity/shape peak and coexistence budget are required')
    cfg=copy.deepcopy(text)
    model=cfg['args'][cfg['args'].index('--native')+1]
    cfg['args']=reserve_args(cfg['args'])
    if '--vision' not in cfg['args']:cfg['args'].append('--vision')
    explicit=int(cfg['args'][cfg['args'].index('--vram-reserve-mib')+1])
    manifest.set_arg(cfg['args'],'--vram-reserve-mib',max(explicit,receipt['reserve_mib']))
    cfg.update(lazy_load=False,vram_elastic=False,vision=dict(backend='hip',gpu=True,exe=str(HIP_EXE),
        model=model,mmproj=str(MM_PROJ),rocm_root=str(SDK),hip_device=receipt['ordinal'],threads=4,
        max_tokens=300,elastic=False,temp_dir=str(Path(directory)/'tmp')))
    return cfg


def correlate_history(before,after,started,canceled):
    """Chronological existing /metrics native rows, never len(ids) fallback."""
    if (not isinstance(before,list) or not isinstance(after,list) or len(after)!=len(before)+1
            or after[:-1]!=before):
        raise RuntimeError('Native request history is missing/ambiguous or changed outside this single POST')
    row=after[-1]
    if (type(row.get('time')) not in (int,float) or not math.isfinite(row['time']) or row['time']<started
            or any(type(row.get(key)) is not int or row[key]<0 for key in ('prompt_read','reused'))
            or row.get('finish') not in (('cancel','disconnect') if canceled else ('stop','length'))):
        raise RuntimeError('Actual native input count/time/finish is unconfirmed')
    output=row.get('engine_generated')
    if output is not None and (type(output) is not int or output<0):
        raise RuntimeError('Invalid native accepted output count')
    return dict(source='metrics.requests.prompt_read+reused',history_row=row,
                native_input_tokens=row['prompt_read']+row['reused'],native_output_tokens=output,
                request_started_at=started,owner_verified=True)


def require_image_answer(output,expected):
    from tools.vision.image_api_cases import score_known_answer
    output['semantic']=score_known_answer(output.get('text',''),expected)
    if (not output.get('normal_terminal') or type(output.get('output_tokens')) is not int
            or not 0<output['output_tokens']<=128 or not output['semantic']['passed']):
        raise RuntimeError('Image protocol/output bound or prebound RefImage meaning failed')


def require_webui_answer(output,expected):
    from tools.vision.image_api_cases import score_known_answer
    require_image_answer(output['protocol'],expected)
    output['ui_semantic']=score_known_answer(output.get('final_answer',{}).get('text',''),expected)
    if not output['ui_semantic']['passed']:
        raise RuntimeError('Actual rendered WebUI answer did not match prebound RefImage meaning')


def history(state):
    from . import official_runtime,runtime_safety as safety
    official_runtime.require_tracking(state);safety.require_owned_listener(state)
    rows=safety.get_json('/metrics').get('requests')
    if not isinstance(rows,list):raise RuntimeError('Existing native request history unavailable')
    # The endpoint exposes newest first, at most 12; this fixed phase spends 7.
    return list(reversed(rows))


def require_image_ready(state,value,monitor,*,initialize=False):
    from . import evaluate_r9700 as runner,official_runtime,runtime_safety as safety
    from . import checked_job
    runner.ready(state);monitor.check()
    status=safety.get_json('/v1/status');vision=status.get('vision',{})
    if not (vision.get('enabled') is True and vision.get('available') is True
            and vision.get('backend')=='hip' and vision.get('cleanup_pending') is False and vision.get('error') is None):
        raise RuntimeError('HIP encoder capability/alive/pending is unconfirmed')
    rows=[row for row in state['owned_identities'] if Path(row['exe'])==HIP_EXE]
    if len(rows)!=1:raise RuntimeError('One exact HIP encoder birth must be owned alongside text')
    if not initialize and rows!=monitor.images:raise RuntimeError('HIP encoder restarted/changed between image requests')
    for row in state['owned_identities']:
        identity=safety.process_identity_status(row)
        if identity.status=='verified' and not checked_job.membership_pid(row['pid']):
            raise RuntimeError('Image server cohort escaped its checked parent Job')
    if safety.process_identity_status(rows[0]).status!='verified':raise RuntimeError('Exact HIP encoder is not live')
    monitor.images=rows
    runner.wait_request_release(state)
    return rows[0]


def image_cache_evidence(cfg,image_index=0):
    """Actual cached SVE for the unchanged selected PNG or unrotated JPEG."""
    if type(image_index) is not int or image_index not in (0,1):raise RuntimeError('Unknown fixed RefImage')
    image=FIXTURES/IMAGES[image_index][1]
    if manifest.digest(image)!=IMAGES[image_index][2]:raise RuntimeError('Original wire image changed')
    # server.Vision.normalize returns PNG/unrotated JPEG unchanged; encode names the
    # cache with SHA256(data)[:32]. No GENI command trace is inferred here.
    key=IMAGES[image_index][2][:32]
    files=list(Path(cfg['vision']['temp_dir']).glob('*/'+key+'.sve'))
    if len(files)!=1:raise RuntimeError('Selected actual SVE cache is absent/ambiguous')
    sve=read_sve(files[0])
    return dict(path=str(files[0]),sha256=sve['sha256'],shape=sve['shape'],finite=True,
                wire_image_sha256=IMAGES[image_index][2],association='unchanged selected PNG/JPEG normalization/cache key source plus actual SVE',
                geni_evidence='fixed source branch only; direct command trace not collected')


def smoke_requests(state,monitor,value,result,retained):
    from . import evaluate_r9700 as runner,webui_phase
    cfg=manifest.read_json(value['config']);rubrics=manifest.read_json(API_BINDING)
    expected=rubrics['expected_api07']
    protocol=smoke_protocol()
    if value['protocol']!=protocol:raise RuntimeError('Fixed image smoke protocol changed')
    result['requests']=[]
    for index,name in enumerate(protocol['order']):
        require_image_ready(state,value,monitor)
        before=history(state);started=time.time()
        row=dict(name=name,slot=index+1,valid=False,request_started_at=started)
        result['requests'].append(row)
        error=None
        try:
            if name=='webui':
                output=webui_phase.run(state,monitor,value,result,retained)
                row['sample']=output
                runner.wait_request_release(state)
                evidence=correlate_history(before,history(state),started,False)
                row['native']=evidence
                require_webui_answer(output,rubrics['expected_webui484'])
                row['sve']=image_cache_evidence(cfg,1)
            else:
                if result['post_count']!=index or result['post_count']>=7:raise RuntimeError('Fixed generation slot unavailable')
                result['post_count']+=1
                canceled=name=='cancel'
                case=next((case for case in protocol['requests'] if case['api']==name),None)
                body=case['body'] if case else (protocol['requests'][0]['body'] if canceled else None)
                sample={};row['sample']=sample
                if body is not None:
                    row.update(api=case['api'] if case else 'openai',pathname=case['pathname'] if case else '/v1/chat/completions',
                               payload_sha256=hashlib.sha256(json.dumps(body).encode('utf-8')).hexdigest(),wire_image_sha256=IMAGES[0][2])
                try:
                    runner.stream_request(state,monitor,'「準備ができました。」とだけ返してください。',128,120,partial=sample,
                        api=row.get('api','openai'),request_body=body,pathname=row.get('pathname','/v1/chat/completions'),
                        cancel_after_answer=canceled)
                except runner.FixedRequestCancelled:
                    if not canceled or not sample.get('reader_stopped'):raise
                    row['cancel_recovery']=dict(transport_disconnected=True,reader_stopped=True)
                runner.wait_request_release(state)
                row['native']=correlate_history(before,history(state),started,canceled)
                if body is not None:
                    row['sve']=image_cache_evidence(cfg)
                    if not canceled:require_image_answer(sample,expected)
                if not canceled:
                    count=row['native']['native_output_tokens']
                    if type(count) is not int or not 0<count<=128:raise RuntimeError('Actual native output bound unconfirmed')
                else:row['cancel_recovery']['idle_released']=True
            require_image_ready(state,value,monitor)
            row['valid']=True
        except BaseException as caught:
            error=caught;row.update(error_type=type(caught).__name__,reason=str(caught));raise
        finally:
            try:
                with (Path(value['config']).parent/'image-requests.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            except BaseException as saving:
                if error is None:raise
                error.add_note('Partial image request save failed: '+type(saving).__name__)
    if result['post_count']!=7 or len(result['requests'])!=7 or not all(row['valid'] for row in result['requests']):
        raise RuntimeError('Fixed image recognition flow incomplete; no replacement POST allowed')


def run_smoke(path,approved):
    """Exercise the existing APIs/WebUI; creates no product API or UI."""
    from . import evaluate_r9700 as runner,runtime_safety as safety,gpu_observation
    value=manifest._verify_authority(path,approved)
    if value['suite']!='vision-smoke' or value['max_posts']!=7 or value['max_starts']!=1:
        raise RuntimeError('Only the fixed A+image seven-flow evaluation is permitted')
    directory=Path(value['config']).parent
    with (directory/'claim.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(manifest_sha256=approved,at=time.time()),stream)
    result=dict(status='unverified',manifest=str(path),manifest_sha256=approved,post_count=0,start_count=0,browser_start_count=0)
    retained={};state=None;failure=None
    try:
        with runner.shared_operation(),runner.candidate_interrupts(retained):
            try:
                runner.production_inactive();result['memory_forecast']=runner.preflight_budget(suite='vision-smoke')
                with runner.MemoryMonitor(directory/'memory.jsonl') as monitor:
                    monitor.cancel_requested=lambda:retained.get('cancel_requested',False)
                    try:
                        result['start_count']=1
                        state=runner.start_session(path,approved,monitor,retained=retained,_image=True)
                        result['startup_seconds']=state['startup_seconds']
                        image=require_image_ready(state,value,monitor,initialize=True)
                        result['loader'],monitor.engine=runner.loader_observation(state,value)
                        manifest.require_loader_binding(result['loader'],value['dependencies'])
                        result['image_loader']=gpu_observation.loaded_modules(image,value['dependencies'])
                        cfg=manifest.read_json(value['config'])
                        # Existing Vision receives cfg['log']; both native text
                        # and encoder diagnostics share that configured file.
                        raw=Path(cfg['log']).read_text(encoding='utf-8',errors='replace')
                        result['image_identity']=match_encoder_identity(raw,manifest.encoder_reference(value))
                        result['image_sdk']=probe_modules(raw,result['image_loader'],value['dependencies'])
                        smoke_requests(state,monitor,value,result,retained)
                        result['recognition']='passed'
                    except BaseException as work:
                        failure=work;raise
                    finally:
                        if state is not None:
                            try:
                                runner.wait_request_release(state)
                                monitor.expect_engine_exit()
                                state.update(phase='stopping',cleanup_pending=True);safety.save(state)
                                stopped=safety.stop_owned(state)
                                proof=runner.pending_exit_proof(retained)
                                if not proof['complete']:raise RuntimeError('Image/cohort/reader/auxiliary exit remains pending')
                                state.update(phase='stopped',cleanup_pending=False);safety.save(state)
                                result['cleanup']=dict(status='passed',stopped_pids=stopped,proof=proof)
                            except BaseException as cleanup:
                                if failure is None:failure=cleanup;raise
                                failure.add_note('Image cleanup failed: '+type(cleanup).__name__)
                result['status']='passed'
            except BaseException as caught:
                original=failure if failure is not None else caught
                result.update(status='failed',error_type=type(original).__name__,reason=str(original))
                # All secondary persistence/reader failures must still reach
                # the existing compound barrier while the old locks are held.
                if retained.get('spawn_possible'):
                    runner.hold_pending_cleanup(retained,result,directory)
                raise original
    finally:
        (directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result



M3_BUILD=manifest.ROOT/'.vision-tmp/amd-vision-m3-build.json'
M3_BUILD_SHA='77fe5b3ac638b04a0baff77ca2e227dfc5a6fff5c799835326a1ff47e85940a0'


def m3_native_manifest():
    """One immutable build closure; it cannot authorize arbitrary asset changes."""
    manifest.local_path(M3_BUILD)
    if manifest.digest(M3_BUILD)!=M3_BUILD_SHA:raise RuntimeError('Pinned amdVision build evidence changed')
    value=manifest.read_json(M3_BUILD)
    inputs={str(manifest.ROOT/name) for name in ('tools/vision/strata_vision.cpp','tools/vision/CMakeLists.txt',
                'tools/vision/amd_vision/diagnostics.h','tools/vision/amd_vision/diagnostics.cpp')}
    changes={str(manifest.ROOT/name) for name in ('tools/vision/strata_vision.cpp','tools/vision/CMakeLists.txt')}
    if (value.get('version')!=3 or value.get('kind')!='amd-vision-m3-native-build'
            or value.get('llama_commit')!='3cf03257f219afbe7334045ff7c6a06ac68c627d'
            or set(value['source_files'])!=inputs or set(value['changed_assets'])!=changes
            or set(value['roles'])!={'cpu','hip','cuda','sycl','hip_staged'}
            or set(value['builds'])!={'cpu','hip','cuda','sycl'}
            or value['sdk_root']!=str(SDK)
            or value['roles']['hip_staged']!=dict(path=str(HIP_EXE),sha256=HIP_SHA)
            or value['roles']['cpu']!=dict(path=str(CPU_EXE),sha256=CPU_SHA)):
        raise RuntimeError('amdVision build role/input/SDK inventory changed')
    for name,row in value['changed_assets'].items():
        if row['after']['sha256']!=value['source_files'][name]:raise RuntimeError('amdVision compile input differs')
    for name,sha in value['source_files'].items():
        row=value['changed_assets'][name]['after'] if name in value['changed_assets'] else value['added_assets'].get(name,{})
        if row.get('sha256')!=sha:raise RuntimeError('amdVision input is not bound in the artifact closure')
    for role in value['roles'].values():
        if value['added_assets'].get(role['path'],{}).get('sha256')!=role['sha256']:
            raise RuntimeError('amdVision native role not bound in closure')
    for backend in value['builds'].values():
        if [x['kind'] for x in backend['actions']]!=['configure','compile','compile','link'] or any(x['exit_code']!=0 for x in backend['actions']):
            raise RuntimeError('All amdVision backend build actions must pass')
    for name in value['added_assets']:manifest.local_path(Path(name))
    return value


def native_repair_pins():
    pins=legacy_native_repair_pins();value=m3_native_manifest()
    for name,row in value['changed_assets'].items():
        path=manifest.local_path(Path(name))
        if pins.get(path)!=row['before']['sha256']:raise RuntimeError('Legacy native compilation parent changed')
        pins[path]=row['after']['sha256']
    for name,row in value['added_assets'].items():
        path=manifest.local_path(Path(name))
        if path in pins and pins[path]!=row['sha256']:raise RuntimeError('Native closure hash conflict')
        pins[path]=row['sha256']
    pins[M3_BUILD]=M3_BUILD_SHA
    return pins
