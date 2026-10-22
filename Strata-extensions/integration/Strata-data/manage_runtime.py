"""Start/stop one task-owned Strata server, with finite readiness and a short state lock."""
import argparse,contextlib,json,math,msvcrt,os,pathlib,socket,subprocess,sys,time,urllib.error,urllib.request,uuid
import psutil
import official_runtime
import startup_progress
import runtime_temp_probe
from dataclasses import dataclass
from model_catalog import CATALOG,require_ready,require_public_context,source_receipts,validate_layout
ROOT=pathlib.Path(__file__).resolve().parent
REPO=ROOT.parent/'Strata'
STATE=ROOT/'records'/'owned-runtime.json'
VISIBILITY=['HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES','GPU_DEVICE_ORDINAL']
CONHOST=(pathlib.Path(os.environ['SystemRoot'])/'System32'/'conhost.exe').resolve()
PORT=18080
RUNTIME_POLICY_ENV=dict(PYTHONUTF8='1')
IDENTITY_TOLERANCE = .00001


class OwnershipUnverifiable(RuntimeError):
    """Inspection failed; this is neither permission to stop nor evidence of absence."""


@dataclass(frozen=True)
class IdentityStatus:
    status: str
    process: object = None
    reason: str = ''


def process_presence(pid):
    """Independent Windows presence proof; access denial is always uncertainty."""
    if os.name != 'nt':
        try:
            return 'present' if psutil.pid_exists(pid) else 'gone'
        except psutil.Error:
            return 'unverifiable'
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return 'gone' if ctypes.get_last_error() == 87 else 'unverifiable'
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return 'unverifiable'
        return 'present' if code.value == 259 else 'gone'
    finally:
        kernel.CloseHandle(handle)


def process_identity_status(record, *, require_command=False):
    if not record:
        return IdentityStatus('gone')
    if (not isinstance(record,dict) or type(record.get('pid')) is not int or not 0 < record['pid'] <= 0xffffffff
            or type(record.get('created')) not in (float,int) or not math.isfinite(record['created'])):
        return IdentityStatus('unverifiable', reason='Invalid saved process identity.')
    try:
        process = psutil.Process(record['pid'])
        if abs(process.create_time() - record['created']) >= IDENTITY_TOLERANCE:
            return IdentityStatus('gone', reason='Saved PID has a different creation identity.')
        if record.get('exe') and pathlib.Path(process.exe()).resolve() != pathlib.Path(record['exe']).resolve():
            return IdentityStatus('unverifiable', reason='Saved executable identity changed.')
        fast_identity = getattr(process, '_ident', (record['pid'], record['created']))
        if isinstance(fast_identity, tuple) and fast_identity[1] is None:
            return IdentityStatus('unverifiable', reason='Windows process identity is unreadable.')
        if require_command and not server_command(process.cmdline(), record.get('config')):
            return IdentityStatus('unverifiable', reason='Server command/config identity changed.')
        if (require_command and startup_progress.is_bootstrap_command(process.cmdline(), record.get('config'))
                and pathlib.Path(process.exe()).resolve() != startup_progress.BASE_PYTHON.resolve()):
            return IdentityStatus('unverifiable', reason='Bootstrap executable identity changed.')
        return IdentityStatus('verified', process)
    except psutil.NoSuchProcess:
        presence = process_presence(record['pid'])
        if presence == 'gone':
            return IdentityStatus('gone')
        return IdentityStatus('unverifiable', reason='Process inspection failed without proof of exit.')
    except (psutil.Error, OSError):
        return IdentityStatus('unverifiable', reason='Process identity cannot be read with these permissions.')


def require_identity(result):
    if result.status == 'unverifiable':
        raise OwnershipUnverifiable(result.reason + ' 所有状態は確認不能のため処理を中断しました。'
            ' 元の起動端末と同じ権限で確認してください。管理者で起動した場合は管理者PowerShellで同じ操作を実行してください。')
    return result.process

@contextlib.contextmanager
def state_lock():
    with (ROOT/'records'/'runtime.lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('Another start/stop operation is updating runtime state') from None
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def save(state):
    temp=STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(state,indent=2),encoding='utf-8');temp.replace(STATE)

def read_state():return json.loads(STATE.read_text()) if STATE.exists() else {}

def server_command(command,config):
    if startup_progress.is_bootstrap_command(command,config):return True
    family = startup_progress.family_launch(config)
    if family:
        return bool(family[2]) and list(command) == family[0].server_command(family[1], config)
    script=str(REPO/'serve'/'server.py')
    i=1
    while i<len(command) and command[i] in ('-u','-B'):i+=1
    server=(command[i:i+2]==['-m','serve.server'] or (i<len(command) and os.path.normcase(str(command[i]))==os.path.normcase(script)))
    return server and command.count('--config')==1 and command[command.index('--config')+1:command.index('--config')+2]==[config]

def owned(state):
    return require_identity(process_identity_status(state, require_command=True))


def runtime_active(state):
    if owned(state):
        return True
    for row in state.get('owned_identities', []):
        if require_identity(process_identity_status(row)):
            return True
    return False

def allowed_child(executable,command,config):
    family = startup_progress.family_launch(config)
    if family:
        if not family[2]:return False
        cfg=family[1]
        if executable==pathlib.Path(cfg['exe']).resolve():
            return list(command)==family[0].native_command(cfg)
        return executable==CONHOST or (executable in (pathlib.Path(cfg['python']).resolve(),startup_progress.BASE_PYTHON.resolve()) and server_command(command,config))
    return executable.is_relative_to(REPO.resolve()) or executable==CONHOST or (executable.name.lower()=='python.exe' and server_command(command,config))

def descendants(process,config,strict=True,unrecognized=None,errors=None):
    found=[]
    try:children=process.children(recursive=True)
    except psutil.Error as error:
        if strict:raise OwnershipUnverifiable('子process集合を確認できません。終了済み・foreignとは判定しません。') from error
        if errors is not None:errors.append(dict(pid=process.pid,action='enumerate_children',error_type=type(error).__name__))
        return found
    for child in children:
        try:
            executable=pathlib.Path(child.exe()).resolve();command=child.cmdline()
            if allowed_child(executable,command,config):found.append(child)
            else:
                if strict:raise RuntimeError('Unexpected owned child executable: '+str(child.pid))
                if unrecognized is not None:unrecognized.append(child)
        except psutil.NoSuchProcess as error:
            if process_presence(child.pid) == 'gone':
                continue
            if strict:raise OwnershipUnverifiable('子process identityを確認できません。停止しません。') from error
            if unrecognized is not None:unrecognized.append(child)
            if errors is not None:errors.append(dict(pid=child.pid,action='inspect_child',error_type='OwnershipUnverifiable'))
        except psutil.Error as error:
            if strict:raise
            if unrecognized is not None:unrecognized.append(child)
            if errors is not None:errors.append(dict(pid=child.pid,action='inspect_child',error_type=type(error).__name__))
    return found

def captured_identity(process):
    """Immutable birth authority from collection, never cached is_running()."""
    identity=getattr(process,'_ident',None)
    if (not isinstance(identity,tuple) or len(identity)!=2 or identity[0]!=process.pid
            or type(identity[1]) not in (int,float) or not math.isfinite(identity[1])):
        raise OwnershipUnverifiable('採取時のprocess identityが確認不能です。終了要求を送りません。')
    if abs(process.create_time()-identity[1])>=IDENTITY_TOLERANCE:
        raise OwnershipUnverifiable('採取後にprocess identityが変わりました。終了要求を送りません。')
    return dict(pid=process.pid,created=identity[1],exe=str(pathlib.Path(process.exe()).resolve()))


def fresh_cleanup_candidate(identity):
    process=require_identity(process_identity_status(identity))
    if process is None:
        # This member was live during collection. Losing it during the common
        # preflight is not authority to terminate the remaining subset.
        raise OwnershipUnverifiable('採取後にprocessが消失・置換されました。全停止前に中断します。')
    return process


def stop_owned(state,known=(),*,official_first=True,post_unload=False):
    if official_first and state.get('runtime_provider')=='official_mcp':
        if not owned(state):raise RuntimeError('Official root identity absent/changed; no stop or fallback was attempted')
        require_owned_listener(state,allow_absent=True)
        official_runtime.require_tracking(state)
        # Snapshot exact descendants before the official graceful unload/stop.
        cohort=verified_cohort(state)
        identities=[dict(pid=p.pid,created=p.create_time(),exe=str(pathlib.Path(p.exe()).resolve())) for p in cohort]
        existing={(row['pid'],row['created']):row for row in state.get('owned_identities',[])}
        existing.update({(row['pid'],row['created']):row for row in identities})
        state['owned_identities']=list(existing.values())
        state['official_stop_result']=official_runtime.stop(state)
        # Windows venv redirectors can leave a real-Python child. Finish only
        # the saved identities, after the official routine has unloaded first.
        return stop_owned(state,known,official_first=False,post_unload=True)
    process=owned(state);victims=list(known);unrecognized=[];unknown_evidence=[];errors=[]
    observation=state.get('spawn_observation',{})
    if observation.get('unknown') or observation.get('errors'):
        errors.append(dict(action='incomplete_saved_spawn_observation',error_type='OwnershipUnverifiable'))
    if not process and not known and not state.get('owned_identities'):
        errors.append(dict(action='root_missing_without_saved_descendant_identities'))
    for identity in state.get('owned_identities',[]):
        try:
            candidate=require_identity(process_identity_status(identity))
            if candidate is None:
                continue
            victims.append(candidate)
            if not process or candidate.pid!=process.pid:
                victims.extend(descendants(candidate,state['config'],strict=False,unrecognized=unrecognized,errors=errors))
        except (OwnershipUnverifiable,psutil.Error) as error:errors.append(dict(pid=identity['pid'],action='inspect_saved_identity_not_touched',error_type=type(error).__name__))
    if process:victims.extend(descendants(process,state['config'],strict=False,unrecognized=unrecognized,errors=errors))
    for child in unrecognized:
        row=dict(pid=child.pid)
        for field,method in [('created',child.create_time),('name',child.name),('exe',child.exe)]:
            try:row[field]=method()
            except psutil.Error as error:row[field]=None;errors.append(dict(pid=child.pid,action='inspect_unknown_'+field,error_type=type(error).__name__))
        unknown_evidence.append(row)
    if process:victims.append(process)
    unique={};captured={}
    for candidate in victims:
        try:
            identity=captured_identity(candidate)
            key=identity['pid']
            if key in captured and captured[key]!=identity:
                raise OwnershipUnverifiable('同じPIDに異なる採取identityがあります。終了要求を送りません。')
            # All origins (known/current/saved/descendants) pass the same fresh
            # proof, and only its new Process object can reach termination.
            unique[key]=fresh_cleanup_candidate(identity)
            captured[key]=identity
        except (OwnershipUnverifiable,psutil.Error,OSError) as error:
            errors.append(dict(pid=candidate.pid,action='inspect_cleanup_candidate',error_type=type(error).__name__))
    root=unique.pop(state.get('pid'),None)
    victims=list(unique.values())
    if root:victims.append(root)
    if post_unload:
        # The official pre-unload snapshot is the cleanup authority. A newly
        # appearing descendant after unload must not expand that authority.
        saved=state.get('owned_identities',[])
        for candidate in victims:
            try:
                identity=captured[candidate.pid]
                if not any(row['pid']==identity['pid'] and abs(row['created']-identity['created'])<IDENTITY_TOLERANCE for row in saved):
                    errors.append(dict(pid=candidate.pid,action='new_descendant_after_unload_not_touched'))
            except psutil.Error as error:
                errors.append(dict(pid=candidate.pid,action='inspect_post_unload_identity',error_type=type(error).__name__))
    independently_exited={}
    def exited_after_unload(pid):
        if not post_unload:
            return False
        row=next((item for item in state.get('owned_identities',[]) if item['pid']==pid),None)
        if row is None:
            return False
        result=process_identity_status(row)
        if result.status=='gone' and process_presence(pid)=='gone':
            independently_exited[pid]=dict(row,exit_proof='saved identity gone and independent Windows presence gone')
            return True
        return False
    if post_unload:
        # Official unload/stop can make a saved process exit between collection
        # and preflight. Exclude only independently absent, pre-unload identities.
        for row in state.get('owned_identities',[]):
            exited_after_unload(row['pid'])
        errors=[row for row in errors if not (
            row.get('pid') in independently_exited
            and row.get('action') in ('enumerate_children','inspect_cleanup_candidate','inspect_post_unload_identity')
            and row.get('error_type') in ('NoSuchProcess','OwnershipUnverifiable'))]
        victims=[process for process in victims if process.pid not in independently_exited]
    if errors or unknown_evidence:
        # Collecting a validated subset is not authority to end its root while
        # another saved/unknown child cannot be inspected. Reject before *any*
        # termination; the separate retained-Popen cleanup remains exact-spawn only.
        receipt=ROOT/'records'/f'runtime-cleanup-{state.get("pid","unknown")}-{time.time_ns()}.json'
        receipt.write_text(json.dumps(dict(root_pid=state.get('pid'),root_created=state.get('created'),
            phase='preflight_rejected',stopped_pids=[],known_alive=[p.pid for p in victims],
            owned_identities=state.get('owned_identities',[]),independently_exited=list(independently_exited.values()),unrecognized_children=unknown_evidence,errors=errors),indent=2),encoding='utf-8')
        state['cleanup_receipt']=str(receipt)
        raise OwnershipUnverifiable('全所有processの事前検査に失敗したため終了要求を送りません。保存identityは維持しました。 '+str(receipt))
    stopped=[]
    for victim in reversed(victims):
        try:
            # Recheck against the immutable preflight row immediately before
            # each action; a later failure cannot undo earlier normal exits.
            identity=captured[victim.pid]
            if exited_after_unload(victim.pid):
                continue
            fresh_cleanup_candidate(identity).terminate();stopped.append(victim.pid)
        except (OwnershipUnverifiable,psutil.Error,OSError) as error:
            if exited_after_unload(victim.pid):
                continue
            errors.append(dict(pid=victim.pid,action='terminate_identity_or_request',error_type=type(error).__name__))
            break
    victims=[process for process in victims if process.pid not in independently_exited]
    try:_,alive=psutil.wait_procs(victims,timeout=15)
    except psutil.Error as error:
        errors.append(dict(action='wait',error_type=type(error).__name__));alive=victims
    for row in unknown_evidence:
        try:
            child=psutil.Process(row['pid']);row['alive_after_cleanup']=child.is_running() and (row['created'] is None or abs(child.create_time()-row['created'])<.05)
        except psutil.NoSuchProcess:row['alive_after_cleanup']=False
        except psutil.Error as error:row['alive_after_cleanup']=None;errors.append(dict(pid=row['pid'],action='inspect_unknown_after',error_type=type(error).__name__))
    receipt=ROOT/'records'/f'runtime-cleanup-{state.get("pid","unknown")}-{time.time_ns()}.json'
    receipt.write_text(json.dumps(dict(root_pid=state.get('pid'),root_created=state.get('created'),stopped_pids=stopped,known_alive=[p.pid for p in alive],independently_exited=list(independently_exited.values()),unrecognized_children=unknown_evidence,errors=errors),indent=2),encoding='utf-8')
    state['cleanup_receipt']=str(receipt)
    if alive:raise RuntimeError('Task-owned processes have not exited: '+','.join(str(p.pid) for p in alive))
    if unknown_evidence:raise RuntimeError('Unrecognized descendants require Main review; see '+str(receipt))
    if errors:raise RuntimeError('Cleanup errors require Main review; see '+str(receipt))
    return stopped

def check_port_available(port=PORT):
    occupied=[dict(pid=c.pid,address=c.laddr.ip) for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==port and c.status==psutil.CONN_LISTEN]
    if occupied:raise RuntimeError('Task port already has an IPv4/IPv6 listener: '+json.dumps(occupied))
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        probe.bind(('127.0.0.1',port));probe.listen(1)

def require_owned_listener(state,allow_absent=False):
    cohort=verified_cohort(state)
    identities={p.pid:p.create_time() for p in cohort}
    listeners=[c for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==PORT and c.status==psutil.CONN_LISTEN]
    if not listeners:
        if allow_absent:return False
        raise RuntimeError('Task listener is absent before request')
    for listener in listeners:
        if listener.pid not in identities:
            raise OwnershipUnverifiable('Task listener is outside the verified process cohort: '+str(listener.pid)+
                                        '; no request was sent. 所有確認できないため停止しません。')
        result=process_identity_status(dict(pid=listener.pid,created=identities[listener.pid]))
        if not require_identity(result):raise RuntimeError('Task listener owner identity changed')
    return True


def verified_cohort(state):
    process=owned(state)
    if not process:raise RuntimeError('Owned server identity is no longer valid')
    cohort=[process]+descendants(process,state['config'])
    pids={p.pid for p in cohort}
    for row in state.get('owned_identities',[]):
        # A PID appearing in children() does not prove that its saved identity
        # is readable; preflight every saved member, not just missing PIDs.
        if require_identity(process_identity_status(row)) and row['pid'] not in pids:
            raise OwnershipUnverifiable('既知の子processが検証済みの親子集合にありません。foreignとは判定せず停止を中断します。')
    return cohort

def record_owned_identities(state):
    process=owned(state)
    if not process:raise RuntimeError('Cannot record identities: validated root is absent')
    cohort=verified_cohort(state)
    identities=[dict(pid=p.pid,created=p.create_time(),exe=str(pathlib.Path(p.exe()).resolve())) for p in cohort]
    state.update(owned_identities=identities,identities_recorded_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    with state_lock():
        current=read_state()
        if current.get('pid')!=state['pid'] or current.get('created')!=state['created']:raise RuntimeError('Runtime attempt identity changed before saving descendants')
        save(state)
    return identities

def get_json(path):
    with urllib.request.urlopen('http://127.0.0.1:'+str(PORT)+path,timeout=2) as response:return json.load(response)


def require_family_ready(state):
    family=startup_progress.family_launch(state['config'])
    if not family or family[2]!=state.get('launch_binding'):
        raise RuntimeError('Current family launch binding changed')
    helper,cfg,binding=family
    native=[]
    for row in state.get('owned_identities',[]):
        if pathlib.Path(row.get('exe','')).resolve()!=pathlib.Path(cfg['exe']).resolve():continue
        process=require_identity(process_identity_status(row))
        if process is None:continue
        command=process.cmdline()
        if command!=helper.native_command(cfg):raise RuntimeError('Owned native launch identity/argv mismatch')
        native.append(dict(identity=dict(row),command=command))
    if len(native)!=1:raise RuntimeError('Exactly one current owned family native is required')
    # The existing /status endpoint exposes only request busy/queue state.
    # /metrics (JSON without Prometheus Accept) carries Service.engine.info.
    response=get_json('/metrics')
    info=helper.validate_ready_info(cfg,response.get('engine'))
    observation=dict(native_info=info,native=native[0],bundle_id=cfg['bundle_id'],runtime_epoch=cfg['runtime_epoch'],
                     primary_pci=cfg['primary_pci'],identity_source='fresh owned native exact argv',native_info_endpoint='/metrics',
                     native_INFO_identity_fields={key:info.get(key) for key in ('bundle_id','runtime_epoch','primary_pci')})
    state['family_ready_observation']=observation
    return observation

def validate_profile(cfg,context):
    if cfg.get('family')=='deepseek41':
        import model_catalog as catalog
        catalog._family_provider(ROOT).validate_profile(cfg,context)
        if cfg.get('host')!='127.0.0.1' or cfg.get('port')!=PORT:raise RuntimeError('Unsafe family endpoint')
        return
    if cfg.get('host')!='127.0.0.1' or cfg.get('port')!=PORT or cfg.get('parallel')!=1:raise RuntimeError('Unsafe endpoint/concurrency')
    if type(cfg.get('gpu')) is not int or type(cfg.get('hip_ordinal')) is not int or cfg.get('backend')!='hip':raise RuntimeError('Single measured HIP GPU required')
    if cfg.get('env'):raise RuntimeError('Environment overrides require review')
    if any(x in cfg for x in ['layer_split','replicas','peer_device','helper_device']):raise RuntimeError('Multiple GPU option present')
    if any('peer' in str(x) or 'helper' in str(x) or 'layer-split' in str(x) or '--gpus' in str(x) for x in cfg['args']):raise RuntimeError('Multiple GPU argument present')
    for flag,want in [('--max-context',str(context))]:
        if cfg['args'][cfg['args'].index(flag)+1]!=want:raise RuntimeError('Profile mismatch: '+flag)

def cleanup_spawn_handle(launched,observation,profile,*,include_identities=True):
    """A retained Popen targets our spawn even when psutil cannot inspect its PID."""
    report=dict(handle_cleanup='not_needed',errors=[],observation=observation)
    try:
        if launched.poll() is None:
            launched.terminate();launched.wait(timeout=15);report['handle_cleanup']='terminated_and_waited'
    except BaseException as error:report['errors'].append(dict(action='retained_spawn_handle',error_type=type(error).__name__))
    identities=observation.get('identities',[])
    if identities and include_identities:
        temporary=dict(pid=launched.pid,created=observation.get('created',0),config=str(profile),
                       owned_identities=identities,spawn_observation=observation)
        try:report['stopped_pids']=stop_owned(temporary,official_first=False)
        except BaseException as error:report['errors'].append(dict(action='saved_spawn_descendants',error_type=type(error).__name__,reason=str(error)))
        report['cleanup_receipt']=temporary.get('cleanup_receipt')
    report['status']='failed' if report['errors'] or observation.get('unknown') or observation.get('errors') else 'completed'
    return report

def start(model,context,options=None):
    return _start(model,context,options)


def _start(model,context,options=None):
    import huihui_authority
    huihui_authority.require_context(model,context,ROOT,for_start=True)
    huihui_authority.check_monitor()
    family_model=CATALOG.get(model,{}).get('family')=='deepseek41'
    profile=ROOT/'profiles'/f'{model}-{context}.json'
    if family_model and not profile.exists():
        import model_catalog as catalog
        require_public_context(model,context,ROOT)
        cfg=catalog._family_profile(model,ROOT)
        cfg['context']=context
        cfg['log']=str(ROOT/'logs'/f'{model}-{context}-engine.log')
        cfg=catalog._family_provider(ROOT).validate_profile(cfg,context)
        with profile.open('x',encoding='utf-8') as stream:json.dump(cfg,stream,indent=2)
    ple_shard=require_ready(model,ROOT,context=context) if family_model else require_ready(model,ROOT)
    cfg=json.loads(profile.read_text(encoding='utf-8-sig'));validate_profile(cfg,context);validate_layout(cfg,model,context,ple_shard,ROOT)
    dependencies=[pathlib.Path(cfg['exe']),pathlib.Path(cfg['tokenizer'])] if family_model else [pathlib.Path(cfg['exe']),pathlib.Path(cfg['tokenizer'])/'vocab.json',ROOT/'mtp'/'rt'/'experts.bin']
    for path in dependencies:
        if not path.is_file():raise RuntimeError('Runtime dependency missing: '+str(path))
    profile=official_runtime.require_registration(model,context)
    source_profile=profile;launch=None
    if family_model:
        helper= startup_progress.family_launch(profile)[0]
        attempt=str(uuid.uuid4())
        profile,launch=helper.resolve(ROOT/'profiles'/f'{model}-{context}.json',ROOT,attempt,time.time_ns(),options,source_profile)
        cfg=json.loads(profile.read_text(encoding='utf-8'))
    elif options:
        raise ValueError('DeepSeek cache overlays cannot be applied to another family')
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('STRATA_') and k.upper() not in VISIBILITY}
    env.update(RUNTIME_POLICY_ENV)
    selected_temp,temp_probe=runtime_temp_probe.probe_temporary_environment(model,context,profile,env)
    env.update(selected_temp)
    sys.path.insert(0,str(REPO));original=os.environ.copy()
    try:
        os.environ.clear();os.environ.update(env)
        import importlib
        if family_model:
            helper_path=ROOT.parent/'Strata-extensions/control/deepseek_bootstrap.py'
            spec=importlib.util.spec_from_file_location('strata_selected_bootstrap',helper_path)
            bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
            selected_scope=bootstrap.selected_server(cfg)
        else:selected_scope=contextlib.nullcontext(importlib.import_module('serve.server'))
        with selected_scope as server, official_runtime.windows_temp_probe(server,selected_config=cfg if family_model else None):
            effective=server.child_env(cfg)
    finally:os.environ.clear();os.environ.update(original)
    # Preserve the fallback selected by the official HIP guard in the server
    # process too, so its engine does not re-probe the rejected inherited TEMP.
    for name in ('TEMP','TMP','TMPDIR'):
        if name in effective:env[name]=effective[name]
    visibility={k:effective.get(k) for k in VISIBILITY}
    if family_model:
        if any(visibility[k] is not None for k in VISIBILITY):raise RuntimeError('Family PCI selection unexpectedly masked by ordinal environment')
    elif visibility['HIP_VISIBLE_DEVICES']!=str(cfg['hip_ordinal']) or any(visibility[k] is not None for k in VISIBILITY[1:]):raise RuntimeError('Effective visibility mismatch')
    log=REPO/'.strata-mcp'/'server.log'
    state={};known=[];launched=None;observation={};watcher=None;progress=None;startup=None
    try:
        with state_lock():
            if runtime_active(read_state()):raise RuntimeError('A task-owned model is already running; stop it first')
            check_port_available()
            launch_error=None
            try:
                if launch:launched,tracking,official_result,observation,watcher=official_runtime.start(model,context,env,launch=launch)
                else:launched,tracking,official_result,observation,watcher=official_runtime.start(model,context,env)
            except official_runtime.LaunchFailure as error:
                launched=error.process;tracking=error.tracking;observation=error.observation;official_result=None;launch_error=error;startup=error.startup
            if 'created' not in observation:
                if launch_error:raise launch_error
                raise RuntimeError('Spawn identity unavailable; retained-handle cleanup required')
            command=list(launched.args)
            state=dict(pid=launched.pid,created=observation['created'],command=command,config=str(profile),
              model=model,context=context,log=str(log),engine_log=cfg['log'],effective_gpu_visibility=visibility,
              runtime_env={k:effective.get(k) for k in ['STRATA_START_RETRIES','STRATA_ENGINE_READY_S','STRATA_WDDM_BUDGET','STRATA_RESIDENT_HEADROOM_GIB']},
              phase='loading',started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              runtime_provider='official_mcp',official_tracking=tracking,official_start_result=official_result,
              owned_identities=observation['identities'],spawn_observation=observation)
            state['temporary_directory']=effective.get('TMP') or effective.get('TEMP')
            if launch:
                state.update(family='deepseek41',launch_binding=launch,source_config=str(source_profile),actual_launch_config=str(profile))
            state['temporary_probe']=temp_probe
            startup=startup or getattr(watcher,'startup',None)
            if isinstance(startup,dict):
                state['startup']=startup
                try:
                    if (not startup_progress.is_bootstrap_command(command,str(profile))
                            or startup.get('attempt') != command[10] or startup.get('stage') != command[12]
                            or startup.get('config_sha256') != official_runtime.digest(profile)):
                        raise ValueError('Startup stage does not match actual spawn command')
                    progress=startup_progress.StageMonitor(startup['stage'],startup['attempt'],profile,
                        startup['config_sha256'],launched.pid,observation['created'],cfg['exe'])
                    if launch_error:progress.update(observation['identities'])
                except (ValueError,TypeError,KeyError,OSError) as error:
                    print('[startup diagnostic] monitor unavailable: '+str(error),flush=True)
            save(state)
            if launch_error:raise launch_error
        # Engine readiness and transient retries are owned by official Strata.
        # Do not terminate a valid load at a shorter local deadline.
        while True:
            huihui_authority.check_monitor()
            observation=watcher.snapshot()
            if progress is not None:progress.update(observation['identities'])
            state.update(owned_identities=observation['identities'],spawn_observation=observation)
            if observation['unknown'] or observation['errors']:raise RuntimeError('Spawn descendant observation failed; see saved evidence')
            if launched.poll() is not None:raise RuntimeError('Server exited before readiness: '+str(launched.returncode))
            process=owned(state)
            if not process:raise RuntimeError('Server identity changed before readiness')
            known=descendants(process,str(profile))
            if not require_owned_listener(state,allow_absent=True):
                time.sleep(2);continue
            try:
                health=get_json('/health')
                if not (health.get('service')=='strata' and health.get('status')=='ok' and health.get('loaded') is True and health.get('model')==model and health.get('max_context')==context):raise RuntimeError('Health identity/readiness mismatch')
                models=get_json('/v1/models')
                matched=[x for x in models.get('data',[]) if x.get('id')==model and x.get('status',{}).get('value')=='loaded' and x.get('meta',{}).get('n_ctx')==context]
                if len(matched)!=1:raise RuntimeError('Model list identity/context mismatch')
                if launch:require_family_ready(state)
                observation=watcher.finish();watcher=None
                state.update(owned_identities=observation['identities'],spawn_observation=observation)
                if observation['unknown'] or observation['errors']:raise RuntimeError('Final spawn observation failed before READY')
                state.update(phase='ready',health=health,models=models,ready_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
                record_owned_identities(state)
                print(json.dumps(state,indent=2));return state
            except urllib.error.HTTPError as error:raise RuntimeError('Readiness HTTP failure: '+str(error.code)) from None
            except (urllib.error.URLError,TimeoutError,ConnectionError):pass
            time.sleep(2)
    except BaseException as original_error:
        if watcher is not None:
            observation=watcher.finish();watcher=None
            if state:state.update(owned_identities=observation['identities'],spawn_observation=observation)
        if state:
            stopped=[];cleanup=dict(status='completed')
            try:
                stopped=stop_owned(state,known,official_first=False)
                if observation.get('unknown') or observation.get('errors'):
                    cleanup=dict(status='incomplete',spawn_observation=observation)
            except BaseException as cleanup_error:cleanup=dict(status='failed',error_type=type(cleanup_error).__name__,reason=str(cleanup_error))
            if launched is not None and launched.poll() is None:
                cleanup['retained_handle']=cleanup_spawn_handle(launched,observation,profile,include_identities=False)
            failure=dict(error_type=type(original_error).__name__,reason=str(original_error),cleanup=cleanup,cleanup_receipt=state.get('cleanup_receipt'))
            try:(ROOT/'records'/f'runtime-start-failure-{state["pid"]}-{time.time_ns()}.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
            except OSError as record_error:failure['record_error_type']=type(record_error).__name__
            print(json.dumps(failure),flush=True)
            try:
                with state_lock():
                    current=read_state()
                    if current.get('pid')==state['pid'] and current.get('created')==state['created']:
                        current.update(phase='failed',stopped_pids=stopped,failure=failure);save(current)
            except (OSError,RuntimeError):pass
        elif launched is not None:
            cleanup=cleanup_spawn_handle(launched,observation,profile)
            failure=dict(error_type=type(original_error).__name__,reason=str(original_error),cleanup=cleanup)
            try:(ROOT/'records'/f'runtime-start-failure-{launched.pid}-{time.time_ns()}.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
            except OSError as record_error:failure['record_error_type']=type(record_error).__name__
            print(json.dumps(failure),flush=True)
        raise

def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['start','stop','status'])
    ap.add_argument('--model',choices=list(CATALOG));ap.add_argument('--context',type=int,choices=[4096,32768,131072,262144],default=4096)
    a=ap.parse_args()
    if a.action=='start':
        if not a.model:raise SystemExit('--model is required for start')
        start(a.model,a.context)
    elif a.action=='status':
        state=read_state();print(json.dumps(dict(running=bool(owned(state)),state=state),indent=2))
    else:
        with state_lock():
            state=read_state();stopped=stop_owned(state) if state else []
            if state:state.update(phase='stopped',stopped_pids=stopped,stopped_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()));save(state)
        print(json.dumps(dict(stopped_pids=stopped)))

if __name__=='__main__':main()
