"""Existing local ownership/cleanup protections, isolated to StrataMod.

Ported from Strata-data/manage_runtime.py at implementation start; behavior stays
fail-closed. Only storage/source paths and explicit candidate child paths differ.
No old metadata or module globals are changed.
"""
import json,math,os,pathlib,socket,time,urllib.request
from dataclasses import dataclass
import psutil
from . import official_runtime
ROOT=pathlib.Path(__file__).resolve().parent
REPO=ROOT.parent
STATE=ROOT/'records'/'owned-runtime.json'
CONHOST=(pathlib.Path(os.environ['SystemRoot'])/'System32'/'conhost.exe').resolve()
PORT=18080
IDENTITY_TOLERANCE=.00001

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
        if require_command and record.get('standalone'):
            standalone_authority(record)
        if require_command and not (standalone_command(process.cmdline(),record.get('config'),record.get('command'))
                                    if record.get('standalone') else server_command(process.cmdline(), record.get('config'))):
            return IdentityStatus('unverifiable', reason='Server command/config identity changed.')
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

def state_storage(state):
    if state.get('kind')=='stratamod-prefill-timing-pilot-v1':
        from .pilot_authority import context_for_state
        ctx=context_for_state(state)
        return ctx.local(ctx.state),ctx.local(ctx.pilot/'records')
    return STATE,ROOT/'records'


def save(state):
    destination,_=state_storage(state)
    temp=destination.with_suffix('.tmp')
    temp.write_text(json.dumps(state,indent=2),encoding='utf-8')
    deadline=time.monotonic()+.5
    while True:
        try:
            temp.replace(destination)
            return
        except PermissionError as error:
            # A short-lived Windows reader can deny atomic replacement.
            # Keep the same complete tmp; never delete/overwrite live state.
            if getattr(error,'winerror',None) not in (5,32) or time.monotonic()>=deadline:
                raise
            time.sleep(.025)

def read_state():return json.loads(STATE.read_text()) if STATE.exists() else {}

def server_command(command,config):
    script=str(REPO/'serve'/'server.py')
    i=1
    while i<len(command) and command[i] in ('-u','-B'):i+=1
    server=(command[i:i+2]==['-m','serve.server'] or (i<len(command) and os.path.normcase(str(command[i]))==os.path.normcase(script)))
    return server and command.count('--config')==1 and command[command.index('--config')+1:command.index('--config')+2]==[config]

def owned(state):
    return require_identity(process_identity_status(state, require_command=True))


def standalone_command(command,config,expected=None):
    if not config:return False
    cfg=json.loads(pathlib.Path(config).read_text(encoding='utf-8'))
    if cfg.get('phase') not in ('vision-probe','vision-encode','vision-webui'):return False
    return command in cfg['commands'] and (expected is None or command==expected)


def standalone_authority(state):
    from . import manifest
    if manifest.digest(state['manifest'])!=state['manifest_sha256']:
        raise OwnershipUnverifiable('Standalone manifest authority changed; no termination allowed')
    value=manifest.read_json(state['manifest'])
    auxiliary=state.get('auxiliary') is True
    key='webui_config' if auxiliary else 'config'
    suites=('vision-smoke',) if auxiliary else ('vision-probe','vision-encode')
    if (value.get('suite') not in suites or value.get(key)!=state['config']
            or manifest.digest(state['config'])!=value.get(key+'_sha256')):
        raise OwnershipUnverifiable('Standalone immutable config authority changed; no termination allowed')


def runtime_active(state):
    if owned(state):
        return True
    for row in state.get('owned_identities', []):
        if require_identity(process_identity_status(row)):
            return True
    return False

def family_config(config):
    if pathlib.Path(config).name=='strata-PrefillTimingPilot.json':
        from .prefill_timing_pilot import PilotRuntime
        return PilotRuntime.fixed_config(config)
    # Only the dedicated normal mutable path selects immutable snapshot authority.
    if pathlib.Path(config).name=='strata-StrataMod.json':
        from . import normal_runtime
        return normal_runtime.fixed_config(config)
    return json.loads(pathlib.Path(config).read_text(encoding='utf-8'))


def allowed_child(executable,command,config):
    return _allowed_child_config(executable,command,config,family_config(config))


def _allowed_child_config(executable,command,config,cfg):
    if cfg.get('phase')=='vision-webui':
        if executable==CONHOST:return True
        node=pathlib.Path(cfg['commands'][0][0]).resolve()
        if executable==node:
            if standalone_command(command,config):return True
            root=pathlib.Path(cfg['driver_root']).resolve()
            return len(command)>1 and pathlib.Path(command[1]).is_absolute() and pathlib.Path(command[1]).resolve().is_relative_to(root)
        return str(executable) in cfg['browser_executables']
    if cfg.get('phase') in ('vision-probe','vision-encode'):
        return executable==CONHOST or (standalone_command(command,config)
                                       and executable==pathlib.Path(command[0]).resolve())
    engine=pathlib.Path(cfg['exe']).resolve()
    vision=pathlib.Path(cfg['vision']['exe']).resolve() if cfg.get('vision',{}).get('exe') else None
    cpu=pathlib.Path(cfg['vision']['cpu_exe']).resolve() if cfg.get('vision',{}).get('cpu_exe') else None
    return executable in (engine,vision,cpu,CONHOST) or (executable.name.lower()=='python.exe' and server_command(command,config))

def descendants(process,config,strict=True,unrecognized=None,errors=None):
    return _descendants(process,config,strict,unrecognized,errors)


def _descendants(process,config,strict=True,unrecognized=None,errors=None,*,classifier=None):
    found=[]
    try:children=process.children(recursive=True)
    except psutil.Error as error:
        if strict:raise OwnershipUnverifiable('子process集合を確認できません。終了済み・foreignとは判定しません。') from error
        if errors is not None:errors.append(dict(pid=process.pid,action='enumerate_children',error_type=type(error).__name__))
        return found
    for child in children:
        try:
            executable=pathlib.Path(child.exe()).resolve();command=child.cmdline()
            accepted=allowed_child(executable,command,config) if classifier is None else classifier(executable,command)
            if accepted:found.append(child)
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
    # Audit collection below may grow; it must never grow post-unload authority.
    pre_unload_authority=tuple(dict(row) for row in state.get('owned_identities',[]))
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
    # Keep this evidence in the caller's retained state even if a later receipt
    # write/cancel fails; the foreground lock barrier must not lose unknowns.
    state['cleanup_observation']=dict(unknown=unknown_evidence,errors=errors)
    existing={(row['pid'],row['created']):row for row in state.get('owned_identities',[])}
    for row in captured.values():
        existing.setdefault((row['pid'],row['created']),row)
    state['owned_identities']=list(existing.values())
    root=unique.pop(state.get('pid'),None)
    victims=list(unique.values())
    if root:victims.append(root)
    if post_unload:
        # The official pre-unload snapshot is the cleanup authority. A newly
        # appearing descendant after unload must not expand that authority.
        saved=pre_unload_authority
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
        row=next((item for item in pre_unload_authority if item['pid']==pid),None)
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
        for row in pre_unload_authority:
            exited_after_unload(row['pid'])
        collected_errors=errors
        errors=[row for row in errors if not (
            row.get('pid') in independently_exited
            and row.get('action') in ('enumerate_children','inspect_cleanup_candidate','inspect_post_unload_identity')
            and row.get('error_type') in ('NoSuchProcess','OwnershipUnverifiable'))]
        # Keep the foreground's retained proof in sync with this same positive
        # exit decision. Save resolved observations separately so later pending
        # proof polling retains their history without marking them unresolved.
        state['cleanup_observation']['errors']=errors
        for error in collected_errors:
            if error not in errors:
                resolved=dict(error=dict(error),exit=dict(independently_exited[error['pid']]))
                history=state.setdefault('post_unload_resolved_errors',[])
                if resolved not in history:history.append(resolved)
        victims=[process for process in victims if process.pid not in independently_exited]
    if errors or unknown_evidence:
        # Collecting a validated subset is not authority to end its root while
        # another saved/unknown child cannot be inspected. Reject before *any*
        # termination; the separate retained-Popen cleanup remains exact-spawn only.
        receipt=state_storage(state)[1]/f'runtime-cleanup-{state.get("pid","unknown")}-{time.time_ns()}.json'
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
    receipt=state_storage(state)[1]/f'runtime-cleanup-{state.get("pid","unknown")}-{time.time_ns()}.json'
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

def get_json(path):
    with urllib.request.urlopen('http://127.0.0.1:'+str(PORT)+path,timeout=2) as response:return json.load(response)
