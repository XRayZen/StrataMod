"""One-machine, exact-artifact authorization for the approved R9700 experiment."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'local_runtime'
DATA = ROOT.parent / 'Strata-data'
ORIGINAL = ROOT.parent / 'Strata'
MODEL = 'huihui-ud-iq4_xs'
CONTEXT = 262144
HEAD = '477ac13cbe8e582c20484871ce459d20d82df09d'
BASE_PROFILE = DATA / f'profiles/{MODEL}-{CONTEXT}.json'
PYTHON = Path(sys._base_executable)
VENV_PYTHON = ORIGINAL / '.venv/Scripts/python.exe'
SUITES = {'smoke':dict(max_posts=1,max_tokens=32,max_starts=1),
          'screen':dict(max_posts=12,max_tokens=128,max_starts=1),
          'diagnostic':dict(max_posts=3,max_tokens=128,max_starts=1),
          'vision-probe':dict(max_posts=0,max_tokens=0,max_starts=1,max_encodes=0),
          'vision-encode':dict(max_posts=0,max_tokens=0,max_starts=3,max_encodes=6),
          'vision-smoke':dict(max_posts=7,max_tokens=128,max_starts=1,max_browser_starts=1)}
ARMS = ('baseline', 't1-table', 't2-2048', 't2-4096', 't2-6144', 'd1-spec2', 'd2-workers8', 'd3-adapt-async1', 'vision-hip10.1')
RESIDENT_GIB = 16
# Historical available drop 77.5220 - 39.0 credited pinned resident = 38.5220,
# rounded up to 39. Historical commit rise 72.4733 - 39.0 = 33.4733 -> 34.
# 8-GiB historical uncertainty + 1-GiB async buffer/overhead allowance, common
# to baseline and candidate. No unbuffered/cache benefit credit.
BUDGET = dict(resident_gib=RESIDENT_GIB,nonresident_physical_gib=39,nonresident_commit_gib=34,
              uncertainty_gib=9,available_floor_gib=4,commit_floor_gib=8)
PROBE_BUDGET = dict(resident_gib=0,nonresident_physical_gib=8,nonresident_commit_gib=8,
                    uncertainty_gib=9,available_floor_gib=4,commit_floor_gib=8)
CRITICAL_DLLS = ('amdhip64_7.dll','amd_comgr.dll','hipblas.dll','libhipblaslt.dll',
                 'libtensilelite-host.dll','rocblas.dll','rocsolver.dll','origami.dll','rocm_kpack.dll')


def memory_budget(suite):
    if suite not in SUITES:raise RuntimeError('Unknown fixed memory-budget suite')
    return dict(PROBE_BUDGET if suite=='vision-probe' else BUDGET)


def require_memory_budget(value):
    budget=value.get('memory_budget')
    if (not isinstance(budget,dict) or any(type(number) is not int for number in budget.values())
            or budget!=memory_budget(value['suite'])):
        raise RuntimeError('Candidate typed suite memory budget changed')


def require_loader_binding(observation,fixed):
    """Gate only the text HIP/BLAS/COMGR closure, not every Windows DLL."""
    if observation.get('build') != read_json(ORIGINAL/'engine/BUILD.json'):
        raise RuntimeError('Critical loader SDK/version binding is unconfirmed')
    for name in CRITICAL_DLLS:
        rows = [row for row in observation.get('modules',[]) if Path(row.get('path','')).name.lower() == name]
        if len(rows) != 1:
            raise RuntimeError('Critical loader module is missing/ambiguous: '+name)
        row = rows[0]
        expected = next((sha for path,sha in fixed.items() if Path(path) == Path(row['path'])),None)
        if expected is None or row.get('sha256') != expected:
            raise RuntimeError('Critical loader actual path/hash is unconfirmed: '+name)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):
            result.update(chunk)
    return result.hexdigest()


def normalized_environment(config,inherited):
    """Only Windows/user essentials survive; SDK/Python injection is removed."""
    parent = {key.upper():value for key,value in inherited.items()}
    keep = ('USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA','COMPUTERNAME','USERNAME','USERDOMAIN',
            'NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','SYSTEMDRIVE')
    env = {key:parent[key] for key in keep if parent.get(key)}
    windows = Path('C:/Windows')
    env.update(SystemRoot=str(windows),WINDIR=str(windows),COMSPEC=str(windows/'System32/cmd.exe'),
               PATHEXT='.COM;.EXE;.BAT;.CMD',
               PATH=os.pathsep.join(str(path) for path in (PYTHON.parent,windows/'System32',windows)),
               HIP_PATH=str(Path(config['exe']).parent/'rocm') if config.get('vision',{}).get('reader_mode')=='official-bundle' else str(ORIGINAL/'engine/rocm'),
               ROCM_PATH=str(Path(config['exe']).parent/'rocm') if config.get('vision',{}).get('reader_mode')=='official-bundle' else str(ORIGINAL/'engine/rocm'),
               PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PYTHONSAFEPATH='1',
               PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8',__PYVENV_LAUNCHER__=str(VENV_PYTHON))
    temporary = str(Path(config['log']).parent/'tmp')
    env.update(TEMP=temporary,TMP=temporary,TMPDIR=temporary)
    env['AMD_COMGR_CACHE_DIR'] = str(Path(temporary)/'comgr')
    return env


def local_path(path, root=ROOT):
    path, root = Path(path), Path(root)
    if not path.is_absolute() or not path.is_relative_to(root):
        raise RuntimeError('Candidate path must remain inside its root')
    if path.resolve() != path.absolute():
        raise RuntimeError('Candidate path link is prohibited')
    return path


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def original_assets():
    # Read the unchanged production authority; it verifies the original artifacts,
    # never the candidate and never grants a validation/inspection scope.
    sys.path.insert(0, str(DATA)) if str(DATA) not in sys.path else None
    import model_catalog
    import huihui_authority
    model_catalog.require_public_context(MODEL, CONTEXT, DATA)
    model_catalog.require_ready(MODEL, DATA)
    huihui_authority.verify(DATA)
    return read_json(BASE_PROFILE)


def set_arg(args, name, value):
    if args.count(name) > 1:
        raise RuntimeError('Repeated option: '+name)
    if name in args:
        args[args.index(name)+1] = str(value)
    else:
        args.extend([name, str(value)])


def expected_config(arm, directory, base, suite='smoke',*,probe=None):
    if arm not in ARMS:
        raise RuntimeError('Unapproved experiment arm')
    if suite in ('vision-probe','vision-encode'):
        from . import image_phase
        if arm!='vision-hip10.1':
            raise RuntimeError('Standalone vision phase requires its fixed image arm')
        return image_phase.phase_config(suite,directory,base,probe)
    if suite=='vision-smoke':
        from . import image_phase
        if arm!='vision-hip10.1':raise RuntimeError('Fixed image smoke requires its image arm')
        text=expected_config('baseline',directory,base)
        cfg=image_phase.image_profile(text,probe,directory)
        cfg.update(phase='vision-smoke',shared=False)
        return cfg
    if arm=='vision-hip10.1':
        raise RuntimeError('Standalone image arm cannot become a text/server arm')
    cfg = copy.deepcopy(base)
    cfg['cwd'], cfg['log'] = str(ROOT), str(Path(directory)/'engine.log')
    # The previous activation dipped below the new 4-GiB safety floor. All arms
    # share a separately named 16-GiB resident baseline; unsafe old timing is not
    # a speed baseline. This also leaves room for prefill and the OS file cache.
    cfg['args'].remove('--resident-experts')
    set_arg(cfg['args'], '--resident-budget-gib', RESIDENT_GIB)
    set_arg(cfg['args'], '--prompt-cache', 0)
    cfg['env'] = {}
    if arm == 't1-table':
        cfg['env'] = dict(STRATA_HIPBLASLT_TUNING=str(ORIGINAL/'tools/hip/gfx1201-hipblaslt-100500.txt'))
    if suite == 'diagnostic':
        cfg['env']['STRATA_HIPBLASLT_VERBOSE'] = '1'
    if arm.startswith('t2-'):
        set_arg(cfg['args'], '--prefill', arm.split('-',1)[1])
    if arm == 'd1-spec2':
        set_arg(cfg['args'], '--spec', 2)
    if arm == 'd2-workers8':
        set_arg(cfg['args'], '--pool-workers', 8)
    if arm == 'd3-adapt-async1':
        set_arg(cfg['args'], '--adapt-async', 1)
    return cfg


def source_files():
    files = [ROOT/'setup.py',ROOT/'tools/strata_mcp.py',ROOT/'tools/strata_tokenizer.py',ROOT/'tools/calibrate.py',
             ROOT/'serve/chat_template.jinja',*sorted((ROOT/'serve').glob('*.py')),
             *sorted(LOCAL.glob('*.py'))]
    files.extend(ROOT/name for name in ('tools/vision/hip_windows.py','tools/gguf_reader.py','tools/vision/encode_io.py',
        'tools/vision/image_api_cases.py','tools/vision/webui_upload.mjs','serve/web/index.html','serve/web/app.js'))
    # Explicit extension roots only: never recurse into private records/data.
    for relative in ('serve/stratamod', 'serve/stratamod/amd_vision', 'tools/vision/amd_vision'):
        files.extend(sorted((ROOT/relative).glob('*.py')))
    # The release server imports these official packages. Bind their finite source
    # roots as well; a changed/missing inventory must invalidate an old receipt.
    for relative in ('strata_control', 'strata_cli', 'strata_cli/launch'):
        directory = ROOT/relative
        files.append(directory/'__init__.py')
        files.extend(sorted(directory.glob('*.py')))
    files.append(ROOT/'strata_control/update_keys.json')
    # Native revisions must cover the actual reader compilation inputs, including
    # the official architecture/header helpers and the opt-in Mod diagnostics.
    files.append(ROOT/'tools/vision/CMakeLists.txt')
    for relative in ('tools/vision', 'tools/vision/amd_vision'):
        for extension in ('*.cpp', '*.h'):
            files.extend(sorted((ROOT/relative).glob(extension)))
    return {str(path):digest(path) for path in files}


def dependency_paths(cfg,arm):
    if cfg.get('phase') in ('vision-probe','vision-encode','vision-smoke'):
        from . import image_phase
        base=original_assets()
        text=expected_config('baseline',Path(cfg['log']).parent,base)
        return list(dict.fromkeys([*dependency_paths(text,'baseline'),*image_phase.dependencies(base)]))
    paths = [Path(cfg['exe']),ORIGINAL/'engine/BUILD.json',PYTHON,VENV_PYTHON,
             DATA/'model_catalog.py',DATA/'huihui_authority.py',
             DATA/'records/verified-hip.json',DATA/'records/huihui-256k-authority.json',
             DATA/f'records/ready-{MODEL}.json',DATA/f'records/verified-pack-{MODEL}.json',
             DATA/f'records/gpu-verified-{MODEL}.json']
    # production_inactive imports this exact manager and its local top-level
    # helpers. Keep the list bounded to that reviewed read-only call graph.
    paths.extend(DATA/name for name in ('manage_runtime.py','official_runtime.py','startup_progress.py',
                                       'runtime_temp_probe.py','profile_defaults.py','runtime_permissions.py'))
    history = DATA/'records/huihui-256k-activation-20261017T225750Z'
    paths.extend(history/name for name in ('attempt5-memory.jsonl','final-menu-memory.jsonl','final-engine.snapshot.log'))
    paths.extend(sorted(path for path in (ORIGINAL/'engine').glob('*')
                        if path.is_file() and path.suffix.lower() == '.dll'))
    paths.extend(sorted(path for path in (ORIGINAL/'engine/rocm').rglob('*')
                        if path.is_file() and path.suffix.lower() in ('.dll','.kpack')))
    args = cfg['args']
    mtp = Path(args[args.index('--mtp')+1])
    paths.extend(mtp/name for name in ('experts.bin','dense.bin','dense.txt','draft_vocab.bin'))
    paths.append(Path(args[args.index('--expert-profile')+1]))
    tokenizer = Path(cfg.get('tokenizer',DATA/f'packs/{MODEL}/tokenizer'))
    paths.extend(tokenizer/name for name in ('vocab.json','merges.txt','token_type.json','chat_template.jinja'))
    if arm == 't1-table':
        paths.append(Path(cfg['env']['STRATA_HIPBLASLT_TUNING']))
    return paths


def verify_dependencies(paths,fixed):
    require_dependency_inventory(paths,fixed)
    for path in dict.fromkeys(paths):
        if digest(path) != fixed[str(path)]:
            raise RuntimeError('Candidate dependency contents changed')


def require_dependency_inventory(paths,fixed):
    if set(fixed) != {str(path) for path in paths}:
        raise RuntimeError('Candidate dependency inventory mismatch')


def git_revision():
    """Capture an exact descendant of the official baseline, without approving it."""
    try:
        git = ['git', '--no-optional-locks', '-C', str(ROOT)]
        head = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
        tree = subprocess.check_output([*git, 'rev-parse', 'HEAD^{tree}'], text=True).strip()
        if any(len(value) != 40 or any(c not in '0123456789abcdef' for c in value)
               for value in (head, tree)):
            raise ValueError('Invalid Git object identity')
        subprocess.run([*git, 'merge-base', '--is-ancestor', HEAD, head],
                       check=True, capture_output=True)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise RuntimeError('Candidate baseline ancestry/Git identity unavailable') from error
    return dict(baseline=HEAD, head=head, tree=tree)


def require_git_revision(value):
    actual = git_revision()
    if 'source_revision' not in value:
        # Immutable historical authorizations keep their original HEAD contract.
        if actual['head'] != HEAD:
            raise RuntimeError('Candidate fixed source HEAD changed')
    elif value['source_revision'] != actual:
        raise RuntimeError('Candidate approved baseline/commit/tree changed')


def validate_semantics(value,*,verify_assets=True):
    if value.get('root') != str(ROOT) or value.get('arm') not in ARMS:
        raise RuntimeError('Candidate source root/arm mismatch')
    require_memory_budget(value)
    require_git_revision(value)
    if value['source_files'] != source_files():
        raise RuntimeError('Candidate source inventory changed')
    if value.get('base_profile_sha256') != digest(BASE_PROFILE):
        raise RuntimeError('Original profile authority changed')
    config = Path(value['config'])
    cfg = read_json(config)
    is_image=value['suite'] in ('vision-probe','vision-encode','vision-smoke')
    probe=(encoder_reference(value) if value['suite']=='vision-smoke' else image_reference(value)) if is_image else None
    if cfg != expected_config(value['arm'],config.parent,original_assets(),value['suite'],probe=probe):
        raise RuntimeError('Candidate config differs from its exact approved arm')
    if is_image and value['suite']!='vision-smoke':
        from . import image_phase
        environment=image_phase.environment(config.parent,cfg['ordinal'],os.environ)
    else:
        environment=normalized_environment(cfg,os.environ)
    if value.get('environment') != environment:
        raise RuntimeError('Candidate prepared environment/memory budget changed')
    if value['suite']=='vision-smoke':
        from . import image_phase
        aux=local_path(value['webui_config'])
        if (digest(aux)!=value['webui_config_sha256'] or read_json(aux)!=image_phase.webui_config(config.parent)
                or value['webui_environment']!=image_phase.webui_environment(config.parent,os.environ)
                or value['webui_input']!=image_phase.webui_input(config.parent)
                or config.with_suffix('.shared-settings.json').exists()
                or value.get('protocol')!=image_phase.smoke_protocol()):
            raise RuntimeError('Private WebUI exact config/environment/input/shared settings changed')
    fixed = value.get('dependencies',{})
    expected = dependency_paths(cfg,value['arm'])
    require_dependency_inventory(expected,fixed)
    if is_image:
        image_phase.require_fixed_dependencies(fixed)
    if verify_assets:
        verify_dependencies(expected,fixed)
    if value['suite'] not in ('smoke','vision-probe','vision-encode','vision-smoke'):
        from . import benchmark
        if value.get('protocol') != benchmark.protocol(benchmark.prompts(cfg['tokenizer'])):
            raise RuntimeError('Screen prompt/protocol binding changed')
        baseline_reference(value)
    return cfg


def encoder_reference(value):
    require_memory_budget(value)
    reference=value.get('encode_reference');allocation=value.get('coexistence_reference')
    if not isinstance(reference,dict) or not isinstance(allocation,dict):raise RuntimeError('Image smoke requires exact ENC and coexistence receipts')
    path=local_path(reference['path']);budget_path=local_path(allocation['path'])
    if digest(path)!=reference['sha256'] or digest(budget_path)!=allocation['sha256']:raise RuntimeError('ENC/coexistence receipt changed')
    result=read_json(path);budget=read_json(budget_path)
    prior=_verify_authority(local_path(result['manifest']),result['manifest_sha256'])
    if (prior['suite']!='vision-encode' or any(prior.get(key)!=value.get(key) for key in ('source_files','dependencies'))
            or budget.get('encode_result_sha256')!=reference['sha256']):
        raise RuntimeError('ENC must match full source/dependencies and exact coexistence reference')
    from . import image_phase
    return image_phase.coexistence(result,budget)


def image_reference(value):
    require_memory_budget(value)
    reference=value.get('probe_reference')
    if value['suite']=='vision-probe':
        if reference is not None:
            raise RuntimeError('Unfiltered probe does not inherit a device selection')
        return None
    if not isinstance(reference,dict):
        raise RuntimeError('Encoder requires a completed fixed probe receipt')
    path=local_path(reference['path'])
    if digest(path)!=reference.get('sha256'):
        raise RuntimeError('Probe result changed')
    result=read_json(path)
    probe=_verify_authority(local_path(result['manifest']),result['manifest_sha256'])
    if (probe['suite']!='vision-probe' or result.get('status')!='passed'
            or result.get('cleanup',{}).get('status')!='passed'
            or any(probe.get(key)!=value.get(key) for key in ('source_files','dependencies'))
            or not isinstance(result.get('identity'),dict)):
        raise RuntimeError('Probe must match this source/SDK/budget and have complete cleanup/identity')
    return result['identity']


def baseline_reference(value):
    """Only today's completed baseline of this exact source/protocol can set deadlines."""
    reference = value.get('baseline_reference')
    if reference is None:
        if value['arm'] != 'baseline':
            raise RuntimeError('Nonbaseline screen/diagnostic requires a same-day baseline result')
        return None
    if value['arm'] == 'baseline':
        raise RuntimeError('Baseline starts independently with predeclared initial deadlines')
    path = local_path(reference['path'])
    if digest(path) != reference.get('sha256'):
        raise RuntimeError('Baseline result changed')
    result = read_json(path)
    original = verify(local_path(result['manifest']),result['manifest_sha256'])
    if (result.get('status') != 'passed'
            or result.get('cleanup',{}).get('status') != 'passed' or original.get('arm') != 'baseline'
            or original.get('suite') != 'screen' or result.get('completed_date') != time.strftime('%Y-%m-%d')
            or result.get('post_count') != 12 or result.get('start_count') != 1
            or original.get('source_files') != value['source_files'] or original.get('protocol') != value['protocol']
            or original.get('memory_budget') != value['memory_budget']):
        raise RuntimeError('Baseline must be a completed same-day screen with equal source/protocol/budget')
    require_loader_binding(result.get('loader',{}),original.get('dependencies',{}))
    from . import benchmark
    if (len(result['samples']) != 12 or benchmark.summarize(result['samples']) != result.get('summary')
            or any(not row['valid'] for row in result['samples'])):
        raise RuntimeError('Baseline sample summary mismatch')
    expected = {key:sha for key,sha in value['dependencies'].items()
                if key != str(ORIGINAL/'tools/hip/gfx1201-hipblaslt-100500.txt')}
    if original.get('dependencies') != expected:
        raise RuntimeError('Baseline fixed dependencies differ')
    return result


def _verify_document(path, approved_sha256, *, root=ROOT):
    path = local_path(path,root)
    if not isinstance(approved_sha256,str) or len(approved_sha256) != 64 or digest(path) != approved_sha256:
        raise RuntimeError('Exact approved manifest hash mismatch')
    value = read_json(path)
    if (type(value.get('version')) is not int or value['version'] != 1 or value.get('root') != str(root)
            or type(value.get('expires_at')) not in (float,int) or not math.isfinite(value['expires_at'])
            or value['expires_at'] <= time.time()):
        raise RuntimeError('Invalid/expired manifest authority')
    limits = SUITES.get(value.get('suite'))
    if limits is None or any(type(value.get(key)) is not int or value[key] != limit for key,limit in limits.items()):
        raise RuntimeError('Manifest suite execution limits changed')
    config = local_path(value['config'],root)
    if digest(config) != value.get('config_sha256'):
        raise RuntimeError('Candidate config hash mismatch')
    if not isinstance(value.get('source_files'),dict) or not value['source_files']:
        raise RuntimeError('Candidate source inventory missing')
    for source, expected in value['source_files'].items():
        source = local_path(source,root)
        if digest(source) != expected:
            raise RuntimeError('Candidate source hash mismatch')
    return value


def _verify_authority(path,approved_sha256,*,root=ROOT):
    """Internal metadata boundary only; never grants permission to spawn."""
    value=_verify_document(path,approved_sha256,root=root)
    validate_semantics(value,verify_assets=False)
    return value


def verify(path,approved_sha256,*,root=ROOT):
    """Independent public verification always includes full fixed assets."""
    value=_verify_document(path,approved_sha256,root=root)
    validate_semantics(value)
    return value


def prepare(arm, suite='smoke',baseline_result=None,*,probe_result=None,encode_result=None,coexistence_budget=None):
    if suite not in SUITES:
        raise RuntimeError('Unknown suite')
    if suite == 'smoke' and baseline_result is not None:
        raise RuntimeError('Smoke does not consume a screen baseline reference')
    is_image=suite in ('vision-probe','vision-encode','vision-smoke')
    if (is_image and baseline_result is not None) or (not is_image and probe_result is not None):
        raise RuntimeError('Text and standalone image references cannot be mixed')
    if suite!='vision-smoke' and (encode_result is not None or coexistence_budget is not None):
        raise RuntimeError('Only image smoke consumes ENC/coexistence references')
    base = original_assets()
    directory = LOCAL/'runs'/f'{time.strftime("%Y%m%dT%H%M%S")}-{time.time_ns()}-{arm}'
    directory.mkdir(parents=True)
    config = directory/f'strata-{arm}.json'
    probe_reference=(dict(path=str(local_path(Path(probe_result))),sha256=digest(probe_result))
                     if probe_result is not None else None)
    # Only completed, exact prior probe data selects the encoder ordinal.
    preliminary=dict(suite=suite,probe_reference=probe_reference,source_files=source_files(),memory_budget=memory_budget(suite))
    if suite=='vision-smoke':
        if encode_result is None or coexistence_budget is None:raise RuntimeError('Image smoke needs both measured receipts')
        encoded=read_json(local_path(encode_result))
        prior=_verify_authority(local_path(encoded['manifest']),encoded['manifest_sha256'])
        preliminary.update(dependencies=prior['dependencies'],
            encode_reference=dict(path=str(local_path(encode_result)),sha256=digest(encode_result)),
            coexistence_reference=dict(path=str(local_path(coexistence_budget)),sha256=digest(coexistence_budget)))
        probe=encoder_reference(preliminary)
    elif suite=='vision-encode':
        reference=read_json(probe_result) if probe_result is not None else {}
        prior=_verify_authority(local_path(reference['manifest']),reference['manifest_sha256']) if reference else {}
        preliminary['dependencies']=prior.get('dependencies')
        probe=image_reference(preliminary)
    else:
        probe=None
    cfg = expected_config(arm,directory,base,suite,probe=probe)
    config.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
    dependencies = list(dict.fromkeys(dependency_paths(cfg,arm)))
    if is_image:
        from . import image_phase
    if is_image and suite!='vision-smoke':
        environment=image_phase.environment(directory,cfg['ordinal'],os.environ)
    else:
        environment=normalized_environment(cfg,os.environ)
    value = dict(version=1,root=str(ROOT),arm=arm,config=str(config),config_sha256=digest(config),
                 source_revision=git_revision(),
                 base_profile_sha256=digest(BASE_PROFILE),source_files=source_files(),
                 dependencies={str(path):digest(path) for path in dependencies},
                 environment=environment,memory_budget=memory_budget(suite),
                 expires_at=time.time()+24*3600,suite=suite,**SUITES[suite],
                 authorization='User-approved plan-v6; exact artifact reviewed before GPU execution',
                 safe_baseline=('probe-only no model load; 8GiB allocation estimate +9GiB unknown overhead, not a hard upper'
                                if suite=='vision-probe' else
                                '16GiB resident; differs from historical public profile; all comparison arms equal'))
    if is_image:
        value['probe_reference']=probe_reference
        if suite=='vision-smoke':
            value.update(encode_reference=preliminary['encode_reference'],coexistence_reference=preliminary['coexistence_reference'])
            aux=directory/'webui-config.json'
            aux.write_text(json.dumps(image_phase.webui_config(directory),indent=2)+'\n',encoding='utf-8')
            value.update(webui_config=str(aux),webui_config_sha256=digest(aux),
                         webui_environment=image_phase.webui_environment(directory,os.environ),webui_input=image_phase.webui_input(directory),
                         protocol=image_phase.smoke_protocol())
    elif suite != 'smoke':
        from . import benchmark
        value['protocol'] = benchmark.protocol(benchmark.prompts(cfg['tokenizer']))
        value['baseline_reference'] = (dict(path=str(local_path(Path(baseline_result))),sha256=digest(baseline_result))
                                       if baseline_result is not None else None)
    path = directory/'manifest.json'
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    _verify_authority(path,digest(path))
    return path,digest(path)
