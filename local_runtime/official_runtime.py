"""Candidate-only adapter using the official manager through explicit arguments."""
import importlib.util
import json
import os
from pathlib import Path
import threading
import subprocess

import psutil

from . import manifest,checked_job

_native = None


def native():
    global _native
    if _native is None:
        path = manifest.ROOT/'tools/strata_mcp.py'
        spec = importlib.util.spec_from_file_location('stratamod_management',path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _native = module
    return _native


def management(value):
    config = Path(value['config'])
    strata = native().Strata(manifest.ROOT,config_path=config,
                            tracking_dir=config.parent/'native',python=str(manifest.PYTHON))
    return strata,native().Tools(strata)


def clean_environment(config,inherited,expected):
    env = manifest.normalized_environment(config,inherited)
    if env != expected:
        raise RuntimeError('Prepared candidate child environment changed; no spawn')
    temporary = Path(config['log']).parent/'tmp'
    temporary.mkdir(exist_ok=True)
    Path(env['AMD_COMGR_CACHE_DIR']).mkdir(exist_ok=True)
    probe = temporary/f'.write-probe-{os.getpid()}'
    with probe.open('xb') as stream:
        stream.write(b'probe')
    probe.unlink()
    return env


def observation_error(error,operation,*,allowed_paths=()):
    """Safe diagnostics only: no exception message, locals or request contents."""
    path=getattr(error,'filename',None)
    if path is not None and str(path) not in {str(p) for p in allowed_paths}:path=None
    row=dict(action='observe',operation=operation,error_type=type(error).__name__,
             errno=getattr(error,'errno',None),winerror=getattr(error,'winerror',None),filename=path)
    trace=error.__traceback__
    while trace:
        filename=Path(trace.tb_frame.f_code.co_filename)
        if filename.is_relative_to(manifest.ROOT):
            row['location']=dict(file=str(filename.relative_to(manifest.ROOT)),line=trace.tb_lineno)
        trace=trace.tb_next
    return row


class SpawnObserver:
    """Same fail-closed, exact-birth collection as the original local adapter."""
    def __init__(self,process,config):
        self.process,self.config = process,str(config)
        self.data = dict(identities=[],unknown=[],errors=[])
        self.lock,self.done = threading.Lock(),threading.Event()
        self.thread = None
        self._normal_command=None;self._normal_children=None;self._normal_paths=()
        self._operation='capture_root'

    @classmethod
    def normal_launch(cls,state):
        from . import normal_runtime,runtime_safety as safety
        import copy
        fixed=normal_runtime.authority(state)
        cfg=copy.deepcopy(fixed['snapshot_config']);command=tuple(fixed['command']);config=str(state['config'])
        expected=copy.deepcopy(normal_runtime.expected_child_commands(cfg))
        def classify(executable,actual):
            if not safety._allowed_child_config(executable,actual,config,cfg):return False
            required=expected.get(str(Path(executable).resolve()))
            if required is not None and actual!=required:
                raise RuntimeError('Normal child argv differs from immutable launch snapshot')
            if executable.name.lower()=='python.exe' and tuple(actual)!=command:
                raise RuntimeError('Normal server argv differs from immutable launch snapshot')
            return True
        def factory(process):
            observer=cls(process,config);observer._normal_command=command
            observer._normal_paths=tuple(fixed.get(k) for k in ('snapshot','receipt') if fixed.get(k))+(state['authority'],)
            observer._normal_children=lambda parent,unknown,errors:safety._descendants(
                parent,config,False,unknown,errors,classifier=classify)
            return observer

        return factory

    @classmethod
    def for_normal(cls,process,state):
        return cls.normal_launch(state)(process)

    def capture(self):
        from . import runtime_safety as safety
        try:
            self._operation='capture_root_metadata'
            parent = psutil.Process(self.process.pid)
            command=parent.cmdline()
            if self._normal_command is not None and tuple(command)!=self._normal_command:
                raise RuntimeError('Normal root argv differs from immutable launch snapshot')
            if not (safety.server_command(command,self.config) or safety.standalone_command(command,self.config)):
                raise RuntimeError('Unexpected candidate server/native command')
            created = parent.create_time()
            root=dict(pid=parent.pid,created=created,exe=parent.exe())
        except psutil.NoSuchProcess:
            # Only the pre-enumeration root lookup can be an expected native
            # exit. Nothing observed later in capture may be suppressed.
            if (self.process.poll() is not None and self.snapshot().get('created') is not None
                    and manifest.read_json(self.config).get('phase') in ('vision-probe','vision-encode','vision-webui')):
                return
            raise
        self.merge(identities=[root],created=created)
        unknown,errors = [],[]
        try:
            self._operation='capture_descendants'
            children=(safety.descendants(parent,self.config,strict=False,unrecognized=unknown,errors=errors)
                      if self._normal_children is None else self._normal_children(parent,unknown,errors))
        finally:
            self.merge(unknown=[dict(pid=p.pid) for p in unknown],errors=errors)
        for process in children:
            try:
                self._operation='capture_child_metadata'
                row=dict(pid=process.pid,created=process.create_time(),exe=process.exe())
                self.merge(identities=[row])
            except BaseException as error:
                self.merge(errors=[dict(observation_error(error,'capture_child_metadata'),pid=process.pid,action='capture_child_metadata')])
                raise

    def merge(self,*,identities=(),unknown=(),errors=(),created=None):
        with self.lock:
            changed=created is not None and 'created' in self.data and self.data['created']!=created
            if created is not None and not changed:self.data['created']=created
            for key,items in [('identities',identities),('unknown',unknown),('errors',errors)]:
                for row in items:
                    if row not in self.data[key]:
                        self.data[key].append(row)
            if changed:
                self.data['errors'].append(dict(action='root_birth_changed',created=created))
                raise RuntimeError('Candidate root birth identity changed')

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def _run(self):
        while not self.done.wait(.25):
            try:
                from . import runtime_safety as safety
                # A fixed native probe exits on its own. Its already captured
                # birth remains evidence; normal exit is not an inspect error.
                if self.process.poll() is not None and manifest.read_json(self.config).get('phase') in ('vision-probe','vision-encode','vision-webui'):
                    return
                self.capture()
            except Exception as error:
                with self.lock:
                    self.data['errors'].append(observation_error(error,self._operation,allowed_paths=self._normal_paths))
                return

    def begin(self):
        self.capture()
        self.thread = threading.Thread(target=self._run,daemon=True)
        self.thread.start()

    def finish(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(3)
            if self.thread.is_alive():
                raise RuntimeError('Candidate observer did not stop')
        self.capture()
        return self.snapshot()

    def finish_standalone(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(3)
            if self.thread.is_alive():raise RuntimeError('Native observer did not stop')
        if self.process.poll() is None:self.capture()
        return self.snapshot()


class LaunchFailure(RuntimeError):
    def __init__(self,error,process,watcher,tracking):
        super().__init__(str(error))
        self.process,self.watcher,self.tracking = process,watcher,tracking


def standalone_environment(cfg,expected):
    from . import image_phase
    environment=image_phase.environment(Path(cfg['log']).parent,cfg['ordinal'],os.environ)
    if environment!=expected:
        raise RuntimeError('Prepared standalone environment changed; zero spawn')
    for key in ('TEMP','TMP','AMD_COMGR_CACHE_DIR'):
        folder=Path(environment[key]);folder.mkdir(parents=True,exist_ok=True)
        probe=folder/f'.write-probe-{os.getpid()}'
        with probe.open('xb') as stream:stream.write(b'probe')
        probe.unlink()
    return environment


def start_standalone(path,approved_sha256,*,retained,index=0,before_spawn=None):
    """One exact native root; no official server tracking or HTTP ownership."""
    manifest.verify(path,approved_sha256)
    return _start_standalone(path,approved_sha256,retained=retained,index=index,before_spawn=before_spawn)


def _start_standalone(path,approved_sha256,*,retained,index=0,before_spawn=None):
    """Internal finite arm continuation; caller holds old locks and verified assets."""
    from . import runtime_safety as safety
    # Heavy assets are checked once by public verify. Recheck the cheap
    # authority after that potentially long read, before taking launch fields.
    value=manifest._verify_authority(path,approved_sha256)
    cfg=manifest.read_json(value['config'])
    if value['suite'] not in ('vision-probe','vision-encode') or cfg.get('phase')!=value['suite']:
        raise RuntimeError('Not an approved fixed standalone phase')
    if type(index) is not int or not 0<=index<len(cfg['commands']):raise RuntimeError('Invalid fixed native start index')
    environment=standalone_environment(cfg,value['environment'])
    checked_job.ensure_parent_job()  # Failure is proved zero-spawn.
    # The caller's live monitor and startup budget must still permit spawning
    # after the potentially long full-asset read. No pending/handle exists yet.
    if before_spawn is not None:before_spawn()
    command=cfg['commands'][index]
    pending=dict(phase='spawning',cleanup_pending=True,config=value['config'],standalone=True,command=command,
                 manifest=str(path),manifest_sha256=approved_sha256,owned_identities=[])
    retained['state']=pending
    safety.save(pending)
    process=observer=None
    try:
        with open(Path(cfg['log']).parent/f'native-{index}.log','xb') as log:
            retained['spawn_possible']=True
            process=subprocess.Popen(command,cwd=cfg['cwd'],env=environment,
                                     stdin=subprocess.DEVNULL if value['suite']=='vision-probe' else subprocess.PIPE,
                                     stdout=log if value['suite']=='vision-probe' else subprocess.PIPE,
                                     stderr=subprocess.STDOUT if value['suite']=='vision-probe' else log,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        retained['process']=process
        checked_job.require_child(process)
        observer=SpawnObserver(process,value['config'])
        retained['observer']=observer
        observer.begin()
        observation=observer.snapshot()
        state=dict(pending,pid=process.pid,created=observation['created'],exe=observation['identities'][0]['exe'],
                   owned_identities=observation['identities'],spawn_observation=observation,phase='running')
        retained['state']=state
        safety.save(state)
        return process,observer,state
    except BaseException as error:
        retained.update(process=process,observer=observer)
        raise LaunchFailure(error,process,observer,{}) from error


def start_webui(path,approved_sha256,*,parent_state,retained,before_spawn,persist_aux):
    """Fixed continuation of a verified, live image-smoke parent under its locks."""
    from . import image_phase,runtime_safety as safety
    value=manifest._verify_authority(path,approved_sha256)
    if value['suite']!='vision-smoke' or parent_state['manifest_sha256']!=approved_sha256 or parent_state['manifest']!=str(path):
        raise RuntimeError('WebUI requires its exact running image-smoke parent')
    require_tracking(parent_state);safety.require_owned_listener(parent_state)
    cfg=manifest.read_json(value['webui_config'])
    env=image_phase.webui_environment(Path(value['config']).parent,os.environ)
    if env!=value['webui_environment']:raise RuntimeError('Fixed Node environment changed')
    for name in ('TEMP','TMP'):
        Path(env[name]).mkdir(parents=True,exist_ok=True)
    checked_job.ensure_parent_job();before_spawn()
    from . import evaluate_r9700 as runner
    memory=runner.preflight_budget(suite='vision-smoke')
    pending=dict(phase='spawning',cleanup_pending=True,auxiliary=True,standalone=True,config=value['webui_config'],
                 command=cfg['commands'][0],manifest=str(path),manifest_sha256=approved_sha256,owned_identities=[],memory_before_spawn=memory)
    retained['state']=pending;persist_aux(pending)
    process=observer=None
    try:
        with Path(cfg['log']).open('xb') as log:
            retained['spawn_possible']=True
            process=subprocess.Popen(pending['command'],cwd=cfg['cwd'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                     stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        retained['process']=process
        checked_job.require_child(process)
        observer=SpawnObserver(process,value['webui_config']);retained['observer']=observer;observer.begin()
        observation=observer.snapshot()
        state=dict(pending,pid=process.pid,created=observation['created'],exe=observation['identities'][0]['exe'],
                   owned_identities=observation['identities'],spawn_observation=observation,phase='running')
        retained['state']=state;persist_aux(state)
        return process,observer,state
    except BaseException as error:
        retained.update(process=process,observer=observer)
        raise LaunchFailure(error,process,observer,{}) from error


def start_candidate(path,approved_sha256,*,retained=None,_image=False,before_spawn=None):
    value = manifest._verify_authority(path,approved_sha256) if _image else manifest.verify(path,approved_sha256)
    if _image and value['suite']!='vision-smoke':raise RuntimeError('Image continuation requires fixed image smoke')
    cfg = manifest.read_json(value['config'])
    strata,tools = management(value)
    captured = []
    retained = retained if retained is not None else {}
    process,observer = None,None

    def launch(command,cwd,logfile,environment):
        nonlocal process,observer
        from . import runtime_safety as safety
        manifest.verify(path,approved_sha256)
        if _image:manifest._verify_authority(path,approved_sha256)
        expected = [str(manifest.PYTHON),str(manifest.ROOT/'serve/server.py'),'--engine','strata',
                    '--config',value['config'],'--port','18080']
        if (captured or command != expected or cwd != manifest.ROOT
                or logfile != Path(value['config']).parent/'native/server.log'):
            raise RuntimeError('Official candidate launch changed at the spawn boundary')
        child_environment = clean_environment(cfg,environment,value['environment'])
        if _image:checked_job.ensure_parent_job()
        if before_spawn is not None:before_spawn()
        # Persist uncertainty BEFORE CreateProcess. Even losing the root's birth
        # proof must leave a durable start interlock rather than an empty state.
        pending = dict(phase='spawning',cleanup_pending=True,config=value['config'],
                       manifest=str(path),manifest_sha256=approved_sha256,owned_identities=[])
        safety.save(pending)
        retained['spawn_possible'] = True
        process = native().spawn_detached(command,cwd,logfile,child_environment,allow_breakaway=False) if _image else native().spawn_detached(command,cwd,logfile,child_environment)
        retained['process'] = process
        if _image:checked_job.require_child(process)
        observer = SpawnObserver(process,value['config'])
        retained['observer'] = observer
        captured.append((process,observer))
        safety.save(dict(pending,pid=process.pid))
        observer.begin()
        return process

    try:
        result = tools.strata_start(model=value['arm'],port=18080,wait_seconds=0,launcher=launch)
        if len(captured) != 1:
            raise RuntimeError('Official manager did not create exactly one candidate')
        process,observer = captured[0]
        tracking = strata.state('server')
        if tracking.get('pid') != process.pid or tracking.get('config') != Path(value['config']).name:
            raise RuntimeError('Candidate native tracking does not match the new process')
        return process,observer,tracking,result
    except BaseException as error:
        # Locals also survive an interrupt between the Popen return and the
        # context update, or between observer construction and registration.
        if retained.get('spawn_possible'):
            retained.update(process=process,observer=observer)
            try:
                tracking = strata.state('server')
            except BaseException as tracking_error:
                tracking = {}
                error.add_note('Native tracking unavailable: '+type(tracking_error).__name__)
            raise LaunchFailure(error,process,observer,tracking) from error
        raise


def require_tracking(state):
    if state.get('kind')=='stratamod-normal-v1':
        from . import normal_runtime
        return normal_runtime.require_tracking(state)
    from . import runtime_safety as safety
    if manifest.digest(state['manifest']) != state['manifest_sha256']:
        raise RuntimeError('Candidate manifest changed; no stop request was sent')
    value = manifest.read_json(state['manifest'])
    if value.get('config') != state['config'] or manifest.digest(state['config']) != value.get('config_sha256'):
        raise RuntimeError('Candidate config authority changed; no stop request was sent')
    strata,tools = management(value)
    record = strata.state('server')
    if (not safety.owned(state) or record != state.get('official_tracking')
            or record.get('pid') != state.get('pid')
            or record.get('config') != Path(state['config']).name
            or record.get('model') != value['arm'] or record.get('port') != 18080
            or not native().proc_alive(record.get('pid'),record.get('ident'))):
        raise RuntimeError('Candidate official ownership changed; no request was sent')
    return strata,tools


def stop(state):
    from . import runtime_safety as safety
    module = native()
    _,tools = require_tracking(state)
    unloaded = False

    def validate_owner():
        require_tracking(state)
        safety.require_owned_listener(state)

    def guarded_http(url,method='GET',**kwargs):
        nonlocal unloaded
        validate_owner()
        if url not in ('http://127.0.0.1:18080/status','http://127.0.0.1:18080/unload'):
            raise RuntimeError('Unexpected candidate stop HTTP target')
        status,body = module.http_json(url,method,**kwargs)
        if status != 200 or not isinstance(body,dict):
            raise RuntimeError('Candidate stop HTTP failed; termination prohibited')
        if url.endswith('/status'):
            if method != 'GET' or body.get('busy') is not False or type(body.get('queued')) is not int or body['queued'] != 0:
                raise RuntimeError('Candidate busy/queued; no unload or termination')
        elif method != 'POST' or body.get('status') not in ('unloaded','not loaded'):
            raise RuntimeError('Candidate unload not confirmed; termination prohibited')
        else:
            if body['status'] == 'not loaded':
                health = safety.get_json('/health')
                if not (health.get('service') == 'strata' and health.get('model') == state['model']
                        and health.get('max_context') == state['context'] and health.get('loaded') is False):
                    raise RuntimeError('Already-unloaded candidate health mismatch')
            unloaded = True
        return status,body

    def guarded_terminate(pid,ident):
        if not unloaded:
            raise RuntimeError('No confirmed unload; termination prohibited')
        validate_owner()
        if pid != state['pid'] or ident != state['official_tracking']['ident']:
            raise RuntimeError('Candidate termination identity changed')
        return module.proc_terminate(pid,ident)

    def no_tree_kill(*args,**kwargs):
        raise RuntimeError('Candidate graceful exit failed; unknown tree kill is prohibited')

    validate_owner()
    health = safety.get_json('/health')
    if not (health.get('service') == 'strata' and health.get('model') == state['model']
            and health.get('max_context') == state['context']):
        raise RuntimeError('Candidate stop health identity mismatch')
    result = tools.strata_stop(port=18080,force=False,request=guarded_http,
                              terminate=guarded_terminate,tree_kill=no_tree_kill)
    if not unloaded or result.get('ended_cleanly') is not True or result.get('engine_unloaded') not in ('unloaded','not loaded'):
        raise RuntimeError('Candidate graceful stop did not complete')
    return result
