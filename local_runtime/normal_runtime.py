"""Installed private StrataMod profile; foreground ownership and Ctrl+C cleanup."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import psutil

from . import manifest as m,official_runtime as official,runtime_safety as safety
from . import evaluate_r9700 as runner,checked_job,gpu_observation,image_phase as image
from . import calibrate_official as calibration
from tools import calibrate as cal

KIND='stratamod-normal-v1'
HOME=m.LOCAL/'normal'
RUNS=HOME/'runs'
SELECTION=HOME/'installed.json'
SHIM=Path.home()/'.local/bin/StrataMod.cmd'
INSTALLER=m.ROOT/'Install-StrataMod.cmd'
NATIVE_INSTALLER=m.ROOT/'Install-StrataMod.ps1'
FULL_BASE=HOME/'installations/1792335253210543300/receipt.json'
FULL_BASE_SHA='c28fdd09fe05201a23c04cafb6551c9f3dbe9dc055c77d069d95c327becc2c6d'
SHIM_BYTES=('@echo off\r\ncall "'+str(m.ROOT/'StrataMod.cmd')+'" %*\r\nexit /b %errorlevel%\r\n').encode('ascii')
CAL=m.LOCAL/'calibration-runs/20261018T222734'
IMAGE=m.LOCAL/'runs/20261018T214104-1792327264798271800-vision-hip10.1'
REFERENCES={CAL/'result.json':'5fc87f8d3f01380940cc8bc0da031cb2fbfa0d54928d952f901f6ab38733cd48',
 CAL/'config-calibrated.json':'136775c0827c7421d745f22bac67bdd086fcb0447d1b6fb0549f1ce01400ad15',
 CAL/'completion-readback.json':'22f03a1646a5ec8639b1e999c905704fd7c87da4ff54fd84a7adea1ff90f8ed1',
 IMAGE/'manifest.json':'24884668b0e6182bcba35a203ad575e25eb39a6611ee8000c8c5005285719162',
 IMAGE/'result.json':'0d58ad2957ccf726e5085d34dc62e2b0525b46bff8d522d1c6a39d044cc67bc5',
 IMAGE/'one-post-evidence-handoff.json':'361be57a9a4a700aed93608055abcecb62e6698649103c39658a6e51fde77a04'}


def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def atomic(path,value):
    path=Path(path);temporary=path.with_suffix('.new')
    write(temporary,value);temporary.replace(path)


class NormalMonitor(runner.MemoryMonitor):
    """Foreground ownership/cancel checks, without experiment-only RAM policy.

    Optional continuous memory/PDH/log collection belongs to the diagnostic
    operator; unavailable statistics must not prevent ordinary use.
    """
    def observe(self,row):
        pass

    def __enter__(self):
        return self

    def __exit__(self,*args):
        return False


def startup_forecast():
    try:return runner.preflight_budget(suite='vision-smoke')
    except Exception as error:
        print('[StrataMod] Startup memory forecast unavailable (advisory): '+type(error).__name__,flush=True)
        return dict(status='unavailable',advisory=True,error_type=type(error).__name__)


def no_links(path):
    path=Path(path)
    if not path.is_absolute():raise RuntimeError('Absolute asset path required: '+str(path))
    for part in (path,*path.parents):
        row=part.lstat()
        if stat.S_ISLNK(row.st_mode) or getattr(row,'st_file_attributes',0)&0x400:
            raise RuntimeError('Linked/reparse asset refused: '+str(part))


def metadata(path):
    path=Path(path);no_links(path);row=path.stat()
    return dict(path=str(path),size=row.st_size,mtime_ns=row.st_mtime_ns,reparse=False)


def check_metadata(path,expected):
    if metadata(path)!=expected:raise RuntimeError('Installed asset metadata changed; run StrataMod verify/reinstall: '+str(path))


def critical_dlls(cfg):
    # Accepted actual image loader closure (12 rows), not native's six reports.
    evidence=m.read_json(IMAGE/'one-post-evidence-handoff.json')
    paths={Path(row['path']).resolve() for row in evidence['image_loader_modules']}
    paths.update((Path(folder)/name).resolve() for folder in cfg.get('lib_dirs',[])
                 for name in m.CRITICAL_DLLS)
    return paths


def critical(path,cfg,*,dlls=None):
    return (Path(path) in (Path(cfg['exe']),Path(cfg['vision']['exe']))
            or Path(path).suffix.lower() in ('.py','.json','.txt','.jinja','.cpp','.h','.hpp','.cmake')
            or (Path(path).suffix.lower()=='.dll' and Path(path).resolve() in
                (critical_dlls(cfg) if dlls is None else dlls)))


def source_files():
    result=m.source_files();result[str(m.ROOT/'StrataMod.cmd')]=m.digest(m.ROOT/'StrataMod.cmd')
    result[str(m.ROOT/'tools/calibrate.py')]=m.digest(m.ROOT/'tools/calibrate.py')
    result[str(INSTALLER)]=m.digest(INSTALLER)
    result[str(NATIVE_INSTALLER)]=m.digest(NATIVE_INSTALLER)
    return result


def references():
    for path,sha in REFERENCES.items():
        if m.digest(path)!=sha:raise RuntimeError('Immutable accepted image/calibration evidence changed: '+str(path))


def profile(directory):
    references()
    accepted=m.read_json(IMAGE/'manifest.json')
    if m.digest(accepted['config'])!=accepted['config_sha256']:raise RuntimeError('Accepted image profile changed')
    cfg=copy.deepcopy(m.read_json(accepted['config']))
    result=m.read_json(CAL/'result.json')
    outcome=result['calibration']
    if result['status']!='passed' or outcome['settings']!={'--pool-workers':'3'} or outcome['env']!={}:
        raise RuntimeError('Unexpected official calibration selection')
    cfg['args']=cal.with_arg(cal.apply(cfg['args'],outcome['settings']),'--prompt-cache','6')
    cfg['env']=cal.apply_env(cfg.get('env'),outcome['env'])
    cfg.pop('phase',None)
    cfg.update(log=str(Path(directory)/'engine.log'),shared=False,open_browser=False)
    cfg['vision']['temp_dir']=str(Path(directory)/'tmp')
    if cfg['vision'].get('backend')=='hip':cfg['vision']['exe']=str(image.HIP_EXE)
    return cfg


def dependencies(cfg):
    # Reuse the exact official model closure and the existing bounded native repair.
    build=m.read_json(m.ROOT/'.vision-tmp/all-backend-build-receipt.json')
    return list(dict.fromkeys([*calibration.dependency_paths(cfg),*image.native_repair_pins(),
        image.REPAIR,image.HIP_EXE,image.MM_PROJ,*[image.SDK/name for name in build['sdk_files']],
        *REFERENCES]))


def read_receipt(path):
    value=m.read_json(m.local_path(Path(path)))
    if value.get('kind')!=KIND:raise RuntimeError('Not a normal StrataMod receipt')
    if value['sources']!=source_files():raise RuntimeError('Installed source changed; explicit reinstall required')
    if m.digest(value['profile'])!=value['profile_sha256']:raise RuntimeError('Installed profile changed')
    references()
    cfg=m.read_json(value['profile'])
    if cfg!=profile(Path(value['profile']).parent):raise RuntimeError('Installed image/calibration profile changed')
    if set(value['assets'])!={str(p) for p in dependencies(cfg)}:raise RuntimeError('Installed asset inventory changed')
    if 'native_revision' in value:
        from . import amd_vision_revision
        amd_vision_revision.validate(sys.modules[__name__],value)
    elif 'full_verification_origin' in value:check_inheritance(value)
    return value


def validate_assets(value,*,full=False,hash_small=True):
    cfg=m.read_json(value['profile'])
    dlls=critical_dlls(cfg) if full or hash_small else set()
    hashed={name for name in value['assets'] if full or (hash_small and critical(Path(name),cfg,dlls=dlls))}
    total=sum(value['assets'][p]['metadata']['size'] for p in hashed);done=0;shown=0
    if hashed:print(f'[StrataMod] Checking {len(hashed)} files / {total:,} bytes; model metadata checked separately',flush=True)
    for name,row in value['assets'].items():
        check_metadata(name,row['metadata'])
        if name in hashed:
            if m.digest(name)!=row['sha256']:raise RuntimeError('Installed asset contents changed: '+name)
            check_metadata(name,row['metadata'])
            done+=row['metadata']['size']
            if done-shown>=128*1024**2 or done==total:
                print(f'[StrataMod] Verified {done:,}/{total:,} bytes: {Path(name).name}',flush=True);shown=done


def revision_base():
    if m.digest(FULL_BASE)!=FULL_BASE_SHA:raise RuntimeError('Original full verification receipt changed')
    return m.read_json(FULL_BASE)


def check_inheritance(value):
    base=revision_base()
    if value.get('full_verification_origin')!=dict(path=str(FULL_BASE),sha256=FULL_BASE_SHA):
        raise RuntimeError('Source-only revision origin changed')
    for key in ('kind','assets','references','full_content_verification_at'):
        if value.get(key)!=base.get(key):raise RuntimeError('Inherited full verification changed: '+key)
    path=m.local_path(Path(value['profile']))
    if m.digest(path)!=value['profile_sha256']:raise RuntimeError('Revised normal profile contents changed')
    if m.digest(base['profile'])!=base['profile_sha256']:raise RuntimeError('Original normal profile changed')
    expected=copy.deepcopy(m.read_json(base['profile']))
    expected['args']=cal.with_arg(expected['args'],'--prompt-cache','6')
    expected['log']=str(path.parent/'engine.log');expected['vision']['temp_dir']=str(path.parent/'tmp')
    if path.name!='profile.json' or m.read_json(path)!=expected:
        raise RuntimeError('Unapproved normal profile revision')
    if value.get('normal_profile_revision')!=dict(prompt_cache='official-default-6',
            original_profile=base['profile'],original_profile_sha256=base['profile_sha256'],
            private_log_temp_paths=True):raise RuntimeError('Normal profile revision evidence changed')
    if value.get('assets_full_sha_read_this_revision') is not False:
        raise RuntimeError('Source-only revision must not claim a new full asset pass')
    changed={p for p in set(base['sources'])|set(value['sources']) if base['sources'].get(p)!=value['sources'].get(p)}
    if changed!={str(m.ROOT/'local_runtime/normal_runtime.py'),str(INSTALLER),str(NATIVE_INSTALLER),
                 str(m.ROOT/'local_runtime/runtime_safety.py'),str(m.ROOT/'serve/server.py'),
                 str(m.ROOT/'serve/test_hip_multi_images.py'),str(m.ROOT/'local_runtime/official_runtime.py'),
                 str(m.ROOT/'local_runtime/checked_job.py'),str(m.ROOT/'local_runtime/manifest.py'),
                 str(m.ROOT/'local_runtime/image_phase.py'),str(m.ROOT/'local_runtime/webui_phase.py'),
                 str(m.ROOT/'tools/vision/webui_upload.mjs'),str(m.ROOT/'StrataMod.cmd'),
                 str(m.ROOT/'serve/vision_request.py'),
                 str(m.ROOT/'serve/vision_hip.py'),
                 str(m.ROOT/'tools/vision/hip_windows.py'),
                 str(m.ROOT/'serve/test_amd_vision_modules.py'),
                 str(m.ROOT/'serve/stratamod/__init__.py'),
                 str(m.ROOT/'serve/stratamod/amd_vision/__init__.py'),
                 str(m.ROOT/'serve/stratamod/amd_vision/environment.py'),
                 str(m.ROOT/'serve/stratamod/amd_vision/encoder.py'),
                 str(m.ROOT/'serve/stratamod/amd_vision/request.py'),
                 str(m.ROOT/'tools/vision/amd_vision/__init__.py'),
                 str(m.ROOT/'tools/vision/amd_vision/cli.py')}:
        raise RuntimeError('Source-only revision contains an unapproved source delta')


def revise_install():
    """Inherit one fixed full pass after unchanged metadata; never rehash models."""
    with runner.shared_operation():
        runner.production_inactive();base=revision_base();references()
        if m.digest(base['profile'])!=base['profile_sha256']:raise RuntimeError('Original installation profile changed')
        cfg=m.read_json(base['profile'])
        corrected=copy.deepcopy(cfg);corrected['args']=cal.with_arg(corrected['args'],'--prompt-cache','6')
        if corrected!=profile(Path(base['profile']).parent) or set(base['assets'])!={str(p) for p in dependencies(cfg)}:
            raise RuntimeError('Source-only profile/inventory changed')
        validate_assets(base,hash_small=False)
        directory=HOME/'installations'/str(time.time_ns());directory.mkdir(parents=True)
        profile_path=directory/'profile.json';write(profile_path,profile(directory))
        value=copy.deepcopy(base);value.update(sources=source_files(),source_revision_at=time.time(),
            full_verification_origin=dict(path=str(FULL_BASE),sha256=FULL_BASE_SHA),assets_full_sha_read_this_revision=False,
            profile=str(profile_path),profile_sha256=m.digest(profile_path),normal_profile_revision=dict(
                prompt_cache='official-default-6',original_profile=base['profile'],original_profile_sha256=base['profile_sha256'],
                private_log_temp_paths=True))
        check_inheritance(value)
        path=directory/'receipt.json';write(path,value)
        return dict(receipt=str(path),sha256=m.digest(path),inherited_full_asset_sha=True,new_full_asset_passes=0)


def selected():
    pointer=m.read_json(SELECTION)
    if m.digest(pointer['receipt'])!=pointer['sha256']:raise RuntimeError('Installed receipt pointer changed')
    value=read_receipt(pointer['receipt'])
    return pointer,value


def verify(*,full=True):
    with runner.shared_operation():
        runner.production_inactive()
        pointer,value=selected();validate_assets(value,full=full)
        return dict(status='verified',receipt=pointer,full_asset_sha=full)


def prepare_install():
    with runner.shared_operation():
        runner.production_inactive()
        directory=HOME/'installations'/str(time.time_ns());directory.mkdir(parents=True)
        cfg=profile(directory);write(directory/'profile.json',cfg)
        assets={}
        for path in dependencies(cfg):
            before=metadata(path);sha=m.digest(path);check_metadata(path,before)
            assets[str(path)]=dict(sha256=sha,metadata=before)
        value=dict(kind=KIND,profile=str(directory/'profile.json'),profile_sha256=m.digest(directory/'profile.json'),
                   sources=source_files(),assets=assets,full_content_verification_at=time.time(),
                   verification_mode='installed-receipt-plus-metadata',normal_launch_full_asset_sha=False,
                   limitation='Unchanged size/mtime is not cryptographic detection of large-asset changes',
                   references={str(p):sha for p,sha in REFERENCES.items()})
        path=directory/'receipt.json';write(path,value)
        return dict(receipt=str(path),sha256=m.digest(path))


def publish(path,sha):
    """Agent-side activation; the user never runs this asset verification step."""
    with runner.shared_operation():
        runner.production_inactive()
        if m.digest(path)!=sha:raise RuntimeError('Exact reviewed installation receipt changed')
        value=read_receipt(path);validate_assets(value,hash_small=True)
        atomic(SELECTION,dict(receipt=str(path),sha256=sha,critical_verified_at=time.time()))
        return dict(private_profile_activated=True,receipt=str(path),sha256=sha,shim_published=False)


def shim_receipt():
    # Deliberately not selected/read_receipt/profile/references: those perform
    # asset body hashes. This entry only checks the activated small authority.
    pointer=m.read_json(SELECTION);path=m.local_path(Path(pointer['receipt']))
    if path.parent.parent!=HOME/'installations' or m.digest(path)!=pointer['sha256']:
        raise RuntimeError('Activated private receipt changed')
    value=m.read_json(path)
    if value.get('kind')!=KIND or value.get('sources')!=source_files():
        raise RuntimeError('Activated source authority changed')
    if 'native_revision' in value:
        from . import amd_vision_revision
        amd_vision_revision.validate(sys.modules[__name__],value)
    else:check_inheritance(value)
    if m.digest(value['profile'])!=value['profile_sha256']:raise RuntimeError('Activated profile changed')
    for name,row in value['assets'].items():check_metadata(name,row['metadata'])
    return pointer,value


def check_shim_collision(value):
    if SHIM.exists() and SHIM.read_bytes()!=SHIM_BYTES:raise RuntimeError('StrataMod shim path collision; no overwrite')
    found=shutil.which('StrataMod')
    if found and Path(found).resolve() not in (SHIM.resolve(),(m.ROOT/'StrataMod.cmd').resolve()):
        raise RuntimeError('Existing StrataMod command collision: '+found)
    # The approved root command can be found via cwd; its source hash was just
    # checked. Every different alias/function/application still refuses install.
    command="Get-Command StrataMod -All -ErrorAction SilentlyContinue | Select-Object Name,@{N='Kind';E={$_.CommandType.ToString()}},Path | ConvertTo-Json -Compress; exit 0"
    shells=[Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe']
    if shutil.which('pwsh'):shells.append(Path(shutil.which('pwsh')))
    for shell in shells:
        queried=subprocess.run([str(shell),'-NoLogo','-NonInteractive','-Command',command],
                               capture_output=True,text=True,encoding='utf-8',timeout=20,check=True)
        if queried.stderr.strip():raise RuntimeError('StrataMod command resolution is unverifiable: '+str(shell))
        rows=json.loads(queried.stdout) if queried.stdout.strip() else []
        if isinstance(rows,dict):rows=[rows]
        for row in rows:
            if (row.get('Kind')!='Application' or not row.get('Path')
                    or Path(row['Path']).resolve() not in (SHIM.resolve(),(m.ROOT/'StrataMod.cmd').resolve())):
                raise RuntimeError('Existing StrataMod function/alias/command collision')
    if not SHIM.parent.is_dir():raise RuntimeError('Existing PATH shim directory missing')


def readonly_shim_guard():
    """No writes or lock acquisition: fixed native installer owns both locks."""
    runner.production_inactive();pointer,value=shim_receipt();check_shim_collision(value)
    return dict(status='checked',shim=str(SHIM),bytes=len(SHIM_BYTES),
                sha256=hashlib.sha256(SHIM_BYTES).hexdigest(),
                asset_body_digest_calls=0)


def install_shim(*,check=False):
    if not check:raise RuntimeError('Use the native Install-StrataMod.cmd; Python never writes the external shim')
    with runner.shared_operation():return readonly_shim_guard()


def _authority_io(path,operation,reader):
    try:return reader(path)
    except OSError as error:
        error.normal_observation=official.observation_error(error,operation,allowed_paths=(path,))
        raise


def authority(state):
    if state.get('kind')!=KIND:raise RuntimeError('Not a normal runtime authority')
    path=m.local_path(Path(state['authority']))
    if _authority_io(path,'normal_authority_read',m.digest)!=state['authority_sha256']:raise RuntimeError('Normal immutable authority changed')
    value=_authority_io(path,'normal_authority_read',m.read_json)
    if value.get('kind')!=KIND or value['config']!=state['config']:raise RuntimeError('Normal authority config identity changed')
    if (path.name!='authority.json' or path.parent.parent!=RUNS
            or Path(value['receipt']).parent.parent!=HOME/'installations'
            or Path(value['snapshot'])!=path.parent/'startup.json'
            or Path(value['config'])!=path.parent/'strata-StrataMod.json'):
        raise RuntimeError('Normal immutable authority paths changed')
    for key in ('receipt','snapshot'):
        if _authority_io(m.local_path(Path(value[key])),'normal_'+key+'_read',m.digest)!=value[key+'_sha256']:
            raise RuntimeError('Normal immutable '+key+' changed; no request permitted')
    value['snapshot_config']=_authority_io(value['snapshot'],'normal_snapshot_read',m.read_json)
    if 'births' in state:
        if Path(state['births'])!=path.parent/'births.json' or m.digest(state['births'])!=state['births_sha256']:
            raise RuntimeError('Normal immutable birth/argv authority changed')
        value['births']=m.read_json(state['births'])
    return value


def fixed_config(config):
    state=safety.read_state()
    if state.get('kind')!=KIND or state.get('config')!=str(config):raise RuntimeError('Normal fixed child authority missing')
    return authority(state)['snapshot_config']


def manager(state,*,immutable=False):
    value=authority(state)
    cfg=Path(value['snapshot'] if immutable else state['config'])
    strata=official.native().Strata(m.ROOT,config_path=cfg,tracking_dir=Path(state['config']).parent/'native',python=str(m.PYTHON))
    return strata,official.native().Tools(strata)


def _tracking(state):
    """Read-only immutable identity/listener checks, independent of Job handles."""
    value=authority(state);process=safety.owned(state)
    if process is None or process.cmdline()!=value['command']:raise RuntimeError('Normal original server birth/argv changed')
    for row in value.get('births',state.get('owned_identities',[])):
        member=safety.require_identity(safety.process_identity_status(row))
        if member is not None and 'argv' in row and member.cmdline()!=row['argv']:
            raise RuntimeError('Normal saved child birth/argv changed')
    strata,tools=manager(state,immutable=True);record=strata.state('server')
    if (record!=state.get('official_tracking') or record.get('pid')!=state['pid']
            or record.get('config')!=Path(state['config']).name or record.get('port')!=18080
            or not official.native().proc_alive(record.get('pid'),record.get('ident'))):
        raise RuntimeError('Normal private tracking/birth changed')
    safety.require_owned_listener(state)
    health=safety.get_json('/health')
    if (health.get('service')!='strata' or health.get('model')!=m.MODEL or health.get('max_context')!=m.CONTEXT):
        raise RuntimeError('Normal listener health/model/context changed')
    return strata,tools


def require_tracking(state):
    strata,tools=_tracking(state)
    if not checked_job.membership_pid(state['pid']):raise RuntimeError('Normal server Job membership changed')
    for row in authority(state).get('births',state.get('owned_identities',[])):
        member=safety.require_identity(safety.process_identity_status(row))
        if member is not None and not checked_job.membership_pid(member.pid):
            raise RuntimeError('Normal saved child Job changed')
    return strata,tools


def require_startup_copy(state):
    fixed=authority(state);no_links(Path(state['config']))
    if m.digest(state['config'])!=fixed['snapshot_sha256']:
        raise RuntimeError('Normal initial startup copy differs from immutable snapshot; zero spawn')


def expected_child_commands(cfg):
    from serve.server import engine_args
    vision=cfg['vision']
    # This installed profile uses the existing engine builder and Vision's fixed
    # non-elastic HIP argv (no min-token or effort-end override).
    encoder=[vision['exe'],'--mmproj',vision['mmproj'],'--model',vision['model'],
             '--gpu','--require-hip','--threads',str(vision['threads']),'--max-tokens',str(vision['max_tokens'])]
    return {str(Path(cfg['exe']).resolve()):[cfg['exe'],'--serve',*engine_args(cfg)],
            str(Path(vision['exe']).resolve()):encoder}


def require_child_command(cfg,executable,command):
    expected=expected_child_commands(cfg).get(str(Path(executable).resolve()))
    if expected is not None and command!=expected:raise RuntimeError('Normal native/encoder argv differs from immutable snapshot')


def new_run(pointer,value):
    directory=RUNS/str(time.time_ns());directory.mkdir(parents=True)
    cfg=copy.deepcopy(m.read_json(value['profile']));cfg['log']=str(directory/'engine.log')
    cfg['vision']['temp_dir']=str(directory/'tmp')
    snapshot=directory/'startup.json';mutable=directory/'strata-StrataMod.json'
    write(snapshot,cfg);write(mutable,cfg)
    command=[str(m.PYTHON),str(m.ROOT/'serve/server.py'),'--engine','strata','--config',str(mutable),'--port','18080']
    fixed=dict(kind=KIND,receipt=pointer['receipt'],receipt_sha256=pointer['sha256'],snapshot=str(snapshot),
               snapshot_sha256=m.digest(snapshot),config=str(mutable),command=command,
               environment=m.normalized_environment(cfg,os.environ))
    path=directory/'authority.json';write(path,fixed)
    state=dict(kind=KIND,authority=str(path),authority_sha256=m.digest(path),config=str(mutable),
               model=m.MODEL,context=m.CONTEXT,phase='spawning',cleanup_pending=True,owned_identities=[],
               runtime_provider='official_mcp',engine_log=cfg['log'],verification_mode=value['verification_mode'],
               normal_launch_full_asset_sha=False)
    (directory/'claim').write_text(str(time.time()),encoding='utf-8')
    return directory,state,cfg


def start(pointer,value,monitor,retained):
    directory,state,cfg=new_run(pointer,value);retained['state']=state
    strata,tools=manager(state)
    def launch(command,cwd,logfile,environment):
        fixed=authority(state)
        if command!=fixed['command'] or cwd!=m.ROOT or logfile!=directory/'native/server.log':
            raise RuntimeError('Normal launch argv/path changed')
        read_receipt(pointer['receipt']);validate_assets(value,hash_small=False)
        env=official.clean_environment(cfg,environment,fixed['environment'])
        state['job_at_launch']=checked_job.ensure_parent_job();monitor.check();startup_forecast();monitor.check()
        require_startup_copy(state)
        observer_factory=official.SpawnObserver.normal_launch(state)
        safety.save(state);retained['spawn_possible']=True
        process=official.native().spawn_detached(command,cwd,logfile,env,allow_breakaway=False)
        retained['process']=process;checked_job.require_child(process)
        observer=observer_factory(process);retained['observer']=observer;observer.begin()
        observation=observer.snapshot();state.update(pid=process.pid,created=observation['created'],
            exe=observation['identities'][0]['exe'],owned_identities=observation['identities'],spawn_observation=observation)
        safety.save(state)
        return process
    tools.strata_start(port=18080,wait_seconds=0,launcher=launch)
    state['official_tracking']=strata.state('server');safety.save(state)
    deadline=time.monotonic()+900
    while True:
        monitor.check();observation=retained['observer'].snapshot()
        state.update(owned_identities=observation['identities'],spawn_observation=observation);safety.save(state)
        if observation['unknown'] or observation['errors']:raise RuntimeError('Normal cohort observation incomplete')
        if retained['process'].poll() is not None:raise RuntimeError('Normal server exited before READY')
        if time.monotonic()>deadline:raise TimeoutError('Normal startup 900-second deadline')
        if safety.require_owned_listener(state,allow_absent=True):
            try:runner.ready(state)
            except (OSError,TimeoutError):pass
            else:
                observation=retained['observer'].finish();state.update(owned_identities=observation['identities'],spawn_observation=observation)
                if observation['unknown'] or observation['errors']:raise RuntimeError('Normal final cohort observation incomplete')
                for row in state['owned_identities']:
                    member=safety.require_identity(safety.process_identity_status(row))
                    if member is None:raise RuntimeError('Normal member exited before READY')
                    command=member.cmdline();require_child_command(cfg,row['exe'],command)
                    if not checked_job.membership_pid(member.pid):raise RuntimeError('Normal READY member Job changed')
                    row['argv']=command
                births=directory/'births.json';write(births,state['owned_identities'])
                state.update(births=str(births),births_sha256=m.digest(births))
                safety.save(state)
                image.require_image_ready(state,{},monitor,initialize=True)
                deps={name:row['sha256'] for name,row in value['assets'].items()}
                native=next(row for row in observation['identities'] if Path(row['exe'])==Path(cfg['exe']))
                monitor.engine=native
                text=gpu_observation.loaded_modules(native,deps,hash_files=False);gpu_observation.bind_module_hashes(text)
                m.require_loader_binding(dict(build=m.read_json(m.ORIGINAL/'engine/BUILD.json'),modules=text),deps)
                encoder=monitor.images[0];modules=gpu_observation.loaded_modules(encoder,deps,hash_files=False)
                gpu_observation.bind_module_hashes(modules)
                raw=Path(cfg['log']).read_text(encoding='utf-8',errors='replace')
                if 'GPU 0: AMD Radeon AI PRO R9700 (gfx1201)' not in raw:
                    raise RuntimeError('Normal text engine R9700/gfx1201 identity is absent')
                accepted=m.read_json(IMAGE/'result.json')['image_identity']
                identity=image.match_encoder_identity(raw,dict(accepted,ordinal=cfg['vision']['hip_device']))
                windows=gpu_observation.windows_displays()
                matched=[row for row in windows if 'R9700' in row.get('Name','')
                         and 'VEN_1002&DEV_7551' in row.get('PNPDeviceID','').upper()
                         and row.get('pci','').lower()==identity['pci'].lower()]
                if len(matched)!=1:raise RuntimeError('Normal physical R9700/PCI is not uniquely matched')
                sdk=image.probe_modules(raw,modules,deps)
                state.update(phase='ready',loader=dict(text=text,image=modules,identity=identity,sdk=sdk,windows=windows))
                safety.save(state);return directory,state
        time.sleep(.25)


def positive_failed_cleanup_proof(retained):
    """Normal only: retain history, prove current original Job/cohort is empty."""
    state=retained.get('state',{});proof=dict(complete=False)
    try:
        if state.get('kind')!=KIND or retained.get('process') is None or retained['process'].poll() is None:return proof
        fixed=authority(state)
        observation=copy.deepcopy(state.get('spawn_observation',{}))
        if retained.get('observer') is not None:
            fresh=retained['observer'].snapshot()
            for key in ('identities','unknown','errors'):
                observation.setdefault(key,[]).extend(x for x in fresh.get(key,[]) if x not in observation.get(key,[]))
        unknown=[*observation.get('unknown',[]),*state.get('cleanup_observation',{}).get('unknown',[])]
        errors=[*observation.get('errors',[]),*state.get('normal_observation_errors',[]),*state.get('cleanup_observation',{}).get('errors',[])]
        allowed_paths={state['authority'],*[fixed[k] for k in ('snapshot','receipt') if k in fixed]}
        allowed_operations={'normal_authority_read','normal_snapshot_read','normal_receipt_read'}
        if unknown or any(e.get('operation') not in allowed_operations or e.get('error_type') not in ('OSError','PermissionError','FileNotFoundError') or e.get('filename') not in allowed_paths for e in errors):return proof
        rows={(x['pid'],x['created']):x for x in [*state.get('owned_identities',[]),*observation.get('identities',[])]}
        if not rows or not observation.get('created'):return proof
        members=[]
        for row in rows.values():
            birth_exit=checked_job.original_birth_exit(row)
            members.append(dict(row,exit=birth_exit))
            if not birth_exit['original_gone']:return proof
        job_members=checked_job.active_members()
        if job_members!={os.getpid()}:return proof
        safety.check_port_available()
        return dict(complete=True,port_free=True,members=members,unknown=[],errors=[],
                    historical_errors=errors,original_checked_job_members=sorted(job_members),
                    after_failed_cleanup=True)
    except Exception as error:
        return dict(complete=False,current_inspection_error=official.observation_error(error,'normal_cleanup_reproof'))


def serve():
    pointer,value=selected();validate_assets(value)
    retained={};result=dict(kind=KIND,status='starting',generation_requests=0,
                           stop_request='POST /unload after idle; separate from generation requests')
    directory=HOME;failure=None;startup_complete=False
    with runner.shared_operation(),runner.candidate_interrupts(retained):
        try:
            runner.production_inactive();pointer,value=selected();validate_assets(value,hash_small=False)
            with NormalMonitor(HOME/f'memory-{time.time_ns()}.jsonl') as monitor:
                monitor.cancel_requested=lambda:retained.get('cancel_requested',False)
                try:
                    directory,state=start(pointer,value,monitor,retained)
                    startup_complete=True
                    result.update(status='ready',state=copy.deepcopy(state))
                    print('StrataMod READY http://127.0.0.1:18080/ — stop with Ctrl+C in this terminal',flush=True)
                    while True:monitor.check();require_tracking(state);time.sleep(.5)
                except KeyboardInterrupt as error:
                    if not startup_complete:
                        failure=error
                        raise
                    result['status']='stopping'
                except BaseException as error:
                    failure=error
                    raise
                finally:
                    state=retained.get('state')
                    if retained.get('spawn_possible'):
                        try:
                            # Ownership/status checks do not depend on a mutable UI config.
                            monitor.expect_engine_exit()
                            if startup_complete:
                                runner.wait_request_release(state)
                                state.update(phase='stopping',cleanup_pending=True);safety.save(state)
                                safety.stop_owned(state)
                            else:
                                runner.cleanup_failed_start(retained.get('process'),retained.get('observer'),state)
                            proof=runner.pending_exit_proof(retained)
                            if not proof['complete']:raise RuntimeError('Normal whole-cohort exit remains pending')
                            state.update(phase='stopped',cleanup_pending=False);safety.save(state)
                            result.update(status='stopped' if failure is None else 'failed',cleanup=proof)
                        except BaseException as cleanup:
                            if failure is not None:
                                failure.add_note('Normal cleanup secondary failure: '+type(cleanup).__name__)
                                raise failure
                            raise
        except BaseException as error:
            failure=failure if failure is not None else error
            result.update(status='failed',error_type=type(error).__name__,reason=str(error))
            if hasattr(error,'normal_observation'):result['observation_error']=error.normal_observation
            if retained.get('spawn_possible'):
                cleaned=False
                try:
                    proof=positive_failed_cleanup_proof(retained)
                    result['normal_positive_cleanup_attempt']=proof
                    if proof['complete']:
                        retained['state'].update(phase='stopped',cleanup_pending=False,normal_positive_exit_proof=proof)
                        safety.save(retained['state']);result['cleanup']=proof
                        write(Path(retained['state']['config']).parent/'result.json',result)
                        cleaned=True
                except BaseException as cleanup:
                    failure.add_note('Normal positive cleanup persistence failed: '+type(cleanup).__name__)
                if not cleaned:
                    retained['state'].update(phase='cleanup-pending',cleanup_pending=True)
                    runner.hold_pending_cleanup(retained,result,Path(retained['state']['config']).parent)
            raise
        finally:
            if retained.get('state'):directory=Path(retained['state']['config']).parent
            try:write(directory/'result.json',result)
            except BaseException as saving:
                if failure is not None:
                    failure.add_note('Normal result persistence failed: '+type(saving).__name__)
                    raise failure
                raise


def status():
    state=safety.read_state()
    if state.get('kind')!=KIND or not safety.runtime_active(state):return dict(running=False,cleanup_pending=state.get('cleanup_pending',False))
    _tracking(state)
    fixed=authority(state)
    try:
        no_links(Path(state['config']));pending=m.read_json(state['config'])
    except (OSError,ValueError,RuntimeError) as error:pending=dict(unreadable=type(error).__name__)
    return dict(running=True,state=state,health=safety.get_json('/health'),status=safety.get_json('/status'),
                job_at_launch=state.get('job_at_launch'),job_current_verified=False,
                job_observation='Saved launch confirmation only; this read-only process has no foreground Job handle',
                startup_snapshot=fixed['snapshot_config'],pending_mutable_file_values=pending,
                pending_mutable_config_path=state['config'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',nargs='?',default='serve',choices=('serve','status','verify','prepare-install','revise-install','install','install-shim','install-guard','stop'))
    parser.add_argument('--receipt');parser.add_argument('--sha256');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.action=='serve':serve();return
    if args.action=='status':value=status()
    elif args.action=='verify':value=verify()
    elif args.action=='prepare-install':value=prepare_install()
    elif args.action=='revise-install':value=revise_install()
    elif args.action=='install-shim':value=install_shim(check=args.check)
    elif args.action=='install-guard':value=readonly_shim_guard()
    elif args.action=='install':value=publish(args.receipt,args.sha256)
    else:value=dict(stopped=False,instruction='Use Ctrl+C in the original StrataMod foreground terminal')
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
