"""P0/P1 only. New private authority, existing fail-closed owner lifecycle."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time

from . import pilot_authority as a,manifest as m,normal_runtime as normal
from . import runtime_safety as safety,official_runtime as official,evaluate_r9700 as runner
from . import checked_job,gpu_observation,release_revision,release_trial,timing_parser

DEFAULTS=dict(STRATA_GDN_HEAD='1',STRATA_GDN_PP='2',STRATA_GDN_CONVL2='1',STRATA_GDN_NOY='1',STRATA_CVEC_FUSE='1')


class ClientReaders:
    """Read-only client birth proof, retained by the foreground lock owner."""
    def __init__(self,pilot,state):
        self.pilot,self.state=pilot,state
        self.proof=dict(complete=False,members=[])

    def close_reader(self,timeout):
        pilot,state=self.pilot,self.state;index=state['pilot_index'];members=[]
        for slot in range(3):
            if not (pilot.ctx.pilot/f'request-{index}-{slot}.claim').exists():continue
            row=dict(index=index,slot=slot,complete=False)
            try:
                path=pilot.ctx.local(pilot.ctx.pilot/f'request-{index}-{slot}.client.json')
                client=m.read_json(path);identity=client['client']
                if (client.get('index')!=index or client.get('slot')!=slot
                        or client.get('pilot_authority_sha256')!=pilot.approved
                        or client.get('run_authority_sha256')!=state['authority_sha256']
                        or identity.get('argv')!=pilot.client_command(index,slot)
                        or identity.get('exe')!=str(pilot.ctx.python)):
                    raise RuntimeError('Shared reader client run/argv/authority differs')
                marker=pilot.ctx.local(pilot.ctx.pilot/f'request-{index}-{slot}.reader.json')
                if marker.is_file():
                    evidence=m.read_json(marker)
                    if any(evidence.get(key)!=value for key,value in dict(index=index,slot=slot,
                           pilot_authority_sha256=pilot.approved,run_authority_sha256=state['authority_sha256'],
                           registration_sha256=m.digest(path)).items()):
                        raise RuntimeError('Shared reader completion binding differs')
                    if (evidence.get('cleanup_pending') is False and
                            (evidence.get('reader_stopped') is True or evidence.get('transport_never_started') is True)):
                        row.update(complete=True,proof='reader_stopped' if evidence['reader_stopped'] else 'transport_never_started',
                                   evidence=str(marker),evidence_sha256=m.digest(marker))
                if not row['complete']:
                    status=safety.process_identity_status(identity);presence=safety.process_presence(identity['pid'])
                    row.update(original_client=identity,identity_status=status.status,presence=presence)
                    if status.status=='gone' and presence=='gone':
                        row.update(complete=True,proof='original_client_birth_and_presence_gone')
            except BaseException as error:
                row.update(error_type=type(error).__name__,reason=str(error))
            members.append(row)
        self.proof=dict(complete=all(row['complete'] for row in members),members=members)
        pilot.write(pilot.ctx.runs/str(index)/'client-reader-proof.json',self.proof)
        return self.proof['complete']


class PilotRuntime:
    safety=safety
    gpu_observation=gpu_observation
    expected_child_commands=staticmethod(normal.expected_child_commands)
    require_child_command=staticmethod(normal.require_child_command)

    def __init__(self,ctx,approved,*,fast=False,full=False):
        self.ctx,self.approved=ctx,approved
        self.fixed=a.load(ctx,approved,fast=fast,full=full)

    @classmethod
    def attach(cls,state):
        return cls(a.context_for_state(state),state['pilot_authority_sha256'],fast=True)

    def read_state(self):
        self.ctx.local(self.ctx.state)
        return m.read_json(self.ctx.state) if self.ctx.state.exists() else {}

    def write(self,path,value):a.write(self.ctx.local(path),value)

    def abort(self,value):
        path=self.ctx.local(self.ctx.pilot/'aborted.json')
        try:
            with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        except FileExistsError:pass  # The first invalid/timeout reason is immutable.

    def client_command(self,index,slot):
        return [str(self.ctx.python),'-I','-B','-X','utf8',str(self.ctx.operator),'request',
                '--sha256',self.approved,'--index',str(index),'--slot',str(slot),'--execute']

    def capture_client(self,index,slot):
        process=safety.psutil.Process(os.getpid());row=safety.captured_identity(process)
        row['argv']=process.cmdline()
        if row['argv']!=self.client_command(index,slot):raise RuntimeError('Pilot original request client argv changed')
        return row

    def register_client(self,state,slot):
        self.authority(state)
        index=state['pilot_index']
        if type(slot) is not int or not 0<=slot<3:raise RuntimeError('Client slot outside fixed budget')
        row=dict(index=index,slot=slot,pilot_authority_sha256=self.approved,
                 run_authority_sha256=state['authority_sha256'],client=self.capture_client(index,slot))
        path=self.ctx.local(self.ctx.pilot/f'request-{index}-{slot}.client.json')
        with path.open('x',encoding='utf-8') as f:json.dump(row,f,ensure_ascii=False,indent=2)
        return dict(path=str(path),sha256=m.digest(path),value=row)

    def publish_reader(self,registration,state,sample):
        row=registration['value']
        stopped=sample.get('reader_stopped') is True and not state.get('request_cleanup_pending')
        never_started='transport_started_at' not in sample
        value=dict(index=row['index'],slot=row['slot'],pilot_authority_sha256=self.approved,
                   run_authority_sha256=row['run_authority_sha256'],registration_sha256=registration['sha256'],
                   reader_stopped=stopped,transport_never_started=never_started,
                   cleanup_pending=not(stopped or never_started),recorded_at=time.time())
        self.write(self.ctx.pilot/f"request-{row['index']}-{row['slot']}.reader.json",value)

    def environment(self,cfg,inherited):
        env=m.normalized_environment(cfg,inherited,python_path=self.ctx.python,venv_python=self.ctx.venv)
        directory=self.ctx.local(Path(cfg['log']).parent)
        user=directory/'user'
        env.update(USERPROFILE=str(user),LOCALAPPDATA=str(user/'AppData/Local'),APPDATA=str(user/'AppData/Roaming'))
        return env

    def authority(self,state):
        a.context_for_state(state)
        if m.digest(self.ctx.authority)!=self.approved:raise RuntimeError('Pilot immutable parent authority changed during run')
        if state.get('pilot_authority_sha256')!=self.approved:raise RuntimeError('Pilot live authority differs from exact client/owner approval')
        index=state.get('pilot_index')
        if type(index) is not int or not 0<=index<4:raise RuntimeError('Pilot launch index outside fixed budget')
        directory=self.ctx.runs/str(index)
        path=self.ctx.local(Path(state['authority']))
        if path!=directory/'authority.json' or m.digest(path)!=state.get('authority_sha256'):
            raise RuntimeError('Pilot immutable run authority changed')
        value=m.read_json(path)
        expected_cfg=a.arm_config(self.fixed['parent_data_proof']['profile'],self.ctx.source,directory,a.ORDER[index])
        expected_command=[str(self.ctx.python),str(self.ctx.source/'serve/server.py'),'--engine','strata','--config',str(directory/'strata-PrefillTimingPilot.json'),'--port','18080']
        if (value.get('kind')!=a.KIND or value.get('pilot_index')!=index or value.get('pilot_authority')!=str(self.ctx.authority)
                or value.get('pilot_authority_sha256')!=self.approved or value.get('command')!=expected_command
                or value.get('snapshot')!=str(directory/'startup.json') or value.get('config')!=str(directory/'strata-PrefillTimingPilot.json')
                or value.get('environment')!=self.environment(expected_cfg,os.environ)):
            raise RuntimeError('Pilot immutable run root/config/environment binding changed')
        if state.get('config')!=value['config']:raise RuntimeError('Pilot mutable config identity changed')
        for key in ('snapshot',):
            self.ctx.local(Path(value[key]))
            if m.digest(value[key])!=value[key+'_sha256']:raise RuntimeError('Pilot startup snapshot changed')
        snapshot=m.read_json(value['snapshot'])
        if snapshot!=expected_cfg:raise RuntimeError('Pilot effective snapshot differs from finite arm')
        if 'births' in state:
            if Path(state['births'])!=directory/'births.json' or m.digest(state['births'])!=state.get('births_sha256'):
                raise RuntimeError('Pilot immutable birth/argv proof changed')
            value['births']=m.read_json(state['births'])
        value['snapshot_config']=snapshot
        return value

    @staticmethod
    def fixed_config(config):
        ctx=a.production_context();ctx.local(Path(config))
        state=m.read_json(ctx.state);pilot=PilotRuntime.attach(state)
        if state.get('config')!=str(config):raise RuntimeError('Pilot config is not the active private authority')
        return pilot.authority(state)['snapshot_config']

    def manager(self,state):
        fixed=self.authority(state)
        strata=official.native().Strata(self.ctx.source,config_path=Path(fixed['snapshot']),
            tracking_dir=Path(state['config']).parent/'native',python=str(self.ctx.python))
        return strata,official.native().Tools(strata)

    def tracking(self,state):
        fixed=self.authority(state);process=safety.owned(state)
        if process is None or process.cmdline()!=fixed['command']:raise RuntimeError('Pilot original server birth/argv changed')
        for row in fixed.get('births',state.get('owned_identities',[])):
            member=safety.require_identity(safety.process_identity_status(row))
            if member is not None and 'argv' in row and member.cmdline()!=row['argv']:raise RuntimeError('Pilot saved child argv changed')
        strata,tools=self.manager(state);record=strata.state('server')
        if (record!=state.get('official_tracking') or record.get('pid')!=state.get('pid')
                or record.get('config')!=Path(state['config']).name or record.get('port')!=18080
                or not official.native().proc_alive(record.get('pid'),record.get('ident'))):
            raise RuntimeError('Pilot private MCP tracking/birth changed')
        safety.require_owned_listener(state)
        health=safety.get_json('/health')
        if health.get('service')!='strata' or health.get('model')!=m.MODEL or health.get('max_context')!=m.CONTEXT:
            raise RuntimeError('Pilot listener health/model/context changed')
        return strata,tools

    def require_tracking(self,state):
        result=self.tracking(state)
        for row in (state,*self.authority(state).get('births',state.get('owned_identities',[]))):
            member=safety.require_identity(safety.process_identity_status(row))
            if member is not None and not checked_job.membership_pid(member.pid):raise RuntimeError('Pilot foreground checked Job membership changed')
        return result

    def client_ready(self,state):
        current=self.read_state()
        if current!=state or state.get('phase')!='ready' or state.get('request_cleanup_pending'):
            raise RuntimeError('Pilot read-only client state identity changed')
        self.tracking(state)
        health=safety.get_json('/health');models=safety.get_json('/v1/models').get('data',[])
        if health.get('status')!='ok' or health.get('loaded') is not True:
            raise RuntimeError('Pilot model is not loaded and healthy')
        if len(models)!=1 or models[0].get('id')!=m.MODEL or models[0].get('meta',{}).get('n_ctx')!=m.CONTEXT or models[0].get('status',{}).get('value')!='loaded':
            raise RuntimeError('Pilot exact model list changed')
        props=safety.get_json('/props')
        cfg=self.authority(state)['snapshot_config']
        if (props.get('default_generation_settings',{}).get('n_ctx')!=m.CONTEXT
                or props.get('model_path')!=normal.cal.arg_value(cfg['args'],'--native')
                or props.get('model_alias')!=m.MODEL or props.get('modalities',{}).get('vision') is not True
                or props.get('is_sleeping') is not False):
            raise RuntimeError('Pilot props native model/context changed')
        return health

    def production_inactive(self):
        rows=[]
        for label,path,required in (
            ('original',self.ctx.data/'records/owned-runtime.json',True),
            ('normal',self.ctx.normal/'local_runtime/records/owned-runtime.json',True),
            ('pilot',self.ctx.state,False)):
            a.no_links(path)
            if not path.is_file():
                if required:raise RuntimeError('Canonical runtime state missing: '+label)
                rows.append(dict(label=label,present=False));continue
            state=m.read_json(path)
            if state.get('cleanup_pending'):raise RuntimeError('Prior '+label+' cleanup remains pending')
            members=[*state.get('owned_identities',[])]
            if state.get('pid'):members.append(state)
            for member in members:
                if safety.require_identity(safety.process_identity_status(member)) is not None:
                    raise RuntimeError('Existing '+label+' birth is still active')
            rows.append(dict(label=label,path=str(path),sha256=m.digest(path),saved_members=len(members),all_saved_births_gone=True))
        safety.check_port_available()
        return dict(states=rows,port_free=True)

    def actual_environment(self,state):
        cfg=self.authority(state)['snapshot_config'];expected=cfg['env'];rows=[]
        for executable,text in ((cfg['exe'],True),
             (cfg['vision']['exe'] if state['loader']['reader_backend']=='hip' else cfg['vision']['cpu_exe'],False)):
            match=[r for r in state['owned_identities'] if Path(r['exe'])==Path(executable)
                   and safety.process_identity_status(r).status=='verified']
            if len(match)!=1:raise RuntimeError('Pilot actual native process is absent/ambiguous')
            process=safety.require_identity(safety.process_identity_status(match[0]));env=process.environ()
            flags={k:v for k,v in env.items() if k.upper().startswith('STRATA_')}
            wanted=expected if text else {}
            controlled={k:v for k,v in flags.items() if k not in DEFAULTS}
            stock={k:v for k,v in flags.items() if k in DEFAULTS}
            if controlled!=wanted or (not text and stock) or any(DEFAULTS[k]!=v for k,v in stock.items()):
                raise RuntimeError('Pilot exact text flags/stock defaults or reader flag isolation changed')
            if env.get('HIP_VISIBLE_DEVICES')!='1':raise RuntimeError('Pilot physical HIP mask changed')
            private=self.environment(cfg,os.environ)
            for key in ('USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP'):
                if env.get(key)!=private[key]:raise RuntimeError('Pilot native private write environment changed: '+key)
            self.require_child_command(cfg,match[0]['exe'],process.cmdline())
            rows.append(dict(pid=process.pid,created=match[0]['created'],exe=executable,
                             trial_flags=controlled,observed_stock_defaults=stock,
                             stock_default_observation='complete' if (not text or stock==DEFAULTS) else 'partial_or_not_observed',
                             unobserved_stock_default_names=sorted(set(DEFAULTS)-set(stock)) if text else [],hip_visible_devices='1',
                             private_environment={key:env[key] for key in ('USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP')}))
        prior=self.ctx.runs/'0/ready.json'
        baseline=m.read_json(prior)['actual_environment'] if prior.is_file() else rows
        if ([r['observed_stock_defaults'] for r in rows]!=[r['observed_stock_defaults'] for r in baseline]
                or len(rows)!=2 or rows[1]['observed_stock_defaults']):
            raise RuntimeError('Observed stock defaults/reader isolation differ across pilot arms')
        return rows

    def actual_loader(self,state):
        """Loaded paths bound to the start's full hash proof plus unchanged metadata."""
        assets=self.fixed['parent_data_proof']['receipt']['assets'];deps={p:r['sha256'] for p,r in assets.items()}
        cfg=self.authority(state)['snapshot_config'];result={}
        for label,executable,names in (
                ('text',cfg['exe'],m.CRITICAL_DLLS),
                ('reader',cfg['vision']['exe' if state['loader']['reader_backend']=='hip' else 'cpu_exe'],
                 ('amdhip64_7.dll','hipblas.dll','rocblas.dll') if state['loader']['reader_backend']=='hip' else ())):
            identity=next(row for row in state['owned_identities'] if Path(row['exe'])==Path(executable))
            rows=gpu_observation.loaded_modules(identity,deps,hash_files=False)
            if any(row['manifest_sha256'] is None or not Path(row['path']).is_relative_to(self.ctx.runtime) for row in rows):
                raise RuntimeError('Pilot loaded module outside full-hashed signed stock closure')
            for name in names:
                if len([row for row in rows if Path(row['path']).name.lower()==name])!=1:
                    raise RuntimeError('Pilot actual critical DLL missing/ambiguous: '+name)
            result[label]=rows
        return dict(modules=result,proof='Actual loader paths; SHA proof inherited from this start full read with exact no-reparse metadata rechecked before POST')

    def new_run(self,index):
        a.reserve_start(self.ctx.pilot,index)
        directory=self.ctx.local(self.ctx.runs/str(index));directory.mkdir(exist_ok=False)
        cfg=a.arm_config(self.fixed['parent_data_proof']['profile'],self.ctx.source,directory,a.ORDER[index])
        snapshot=directory/'startup.json';mutable=directory/'strata-PrefillTimingPilot.json'
        self.write(snapshot,cfg);self.write(mutable,cfg)
        fixed=dict(kind=a.KIND,pilot_index=index,pilot_authority=str(self.ctx.authority),pilot_authority_sha256=self.approved,
                   snapshot=str(snapshot),snapshot_sha256=m.digest(snapshot),config=str(mutable),
                   command=[str(self.ctx.python),str(self.ctx.source/'serve/server.py'),'--engine','strata','--config',str(mutable),'--port','18080'],
                   environment=self.environment(cfg,os.environ))
        path=directory/'authority.json';self.write(path,fixed)
        state=dict(kind=a.KIND,pilot_root=str(self.ctx.pilot),pilot_index=index,pilot_authority_sha256=self.approved,
                   authority=str(path),authority_sha256=m.digest(path),config=str(mutable),engine_log=cfg['log'],
                   model=m.MODEL,context=m.CONTEXT,phase='spawning',cleanup_pending=True,owned_identities=[],runtime_provider='official_mcp')
        return directory,state,cfg

    def start(self,index,monitor,retained):
        directory,state,cfg=self.new_run(index);retained['state']=state
        retained['reader']=ClientReaders(self,state)
        fixed=self.authority(state)
        # The initial mutable startup file must be byte-identical before any spawn.
        if m.digest(state['config'])!=fixed['snapshot_sha256']:raise RuntimeError('Pilot startup copy changed; zero spawn')
        strata=official.native().Strata(self.ctx.source,config_path=Path(state['config']),tracking_dir=directory/'native',python=str(self.ctx.python))
        tools=official.native().Tools(strata)
        def launch(command,cwd,logfile,environment):
            fixed=self.authority(state)
            if command!=fixed['command'] or cwd!=self.ctx.source or logfile!=directory/'native/server.log':
                raise RuntimeError('Pilot spawn command/cwd/log changed')
            a.verify_parent(self.ctx,self.fixed['parent_data_proof'])
            env=official.clean_environment(cfg,environment,fixed['environment'],environment_factory=self.environment)
            for key in ('USERPROFILE','LOCALAPPDATA','APPDATA'):
                self.ctx.local(Path(env[key])).mkdir(parents=True,exist_ok=True)
            if any(k.upper().startswith('STRATA_') for k in env):raise RuntimeError('Parent trial flag injection before text-only config')
            state['job_at_launch']=checked_job.ensure_parent_job();monitor.check()
            try:retained['startup_forecast']=runner.preflight_budget(suite='vision-smoke')
            except Exception as error:retained['startup_forecast']=dict(advisory_error=type(error).__name__)
            observer_factory=official.SpawnObserver.authorized_launch(state,self)
            safety.save(state);retained['spawn_possible']=True
            process=official.native().spawn_detached(command,cwd,logfile,env,allow_breakaway=False)
            retained['process']=process;checked_job.require_child(process)
            observer=observer_factory(process);retained['observer']=observer;observer.begin()
            observation=observer.snapshot();state.update(pid=process.pid,created=observation['created'],exe=observation['identities'][0]['exe'],
                        owned_identities=observation['identities'],spawn_observation=observation)
            safety.save(state);return process
        tools.strata_start(port=18080,wait_seconds=0,launcher=launch)
        state['official_tracking']=strata.state('server');safety.save(state);deadline=time.monotonic()+900
        while True:
            monitor.check();observation=retained['observer'].snapshot()
            state.update(owned_identities=observation['identities'],spawn_observation=observation);safety.save(state)
            if observation['unknown'] or observation['errors']:raise RuntimeError('Pilot cohort observation incomplete')
            if retained['process'].poll() is not None:raise RuntimeError('Pilot server exited before READY')
            if time.monotonic()>deadline:raise TimeoutError('Pilot startup 900-second deadline')
            if safety.require_owned_listener(state,allow_absent=True):
                try:runner.ready(state)
                except (OSError,TimeoutError):pass
                else:
                    observation=retained['observer'].finish()
                    state.update(owned_identities=observation['identities'],spawn_observation=observation)
                    if observation['unknown'] or observation['errors']:raise RuntimeError('Pilot final cohort incomplete')
                    for row in state['owned_identities']:
                        member=safety.require_identity(safety.process_identity_status(row))
                        if member is None:
                            if Path(row['exe'])==Path(cfg['vision']['exe']) and checked_job.original_birth_exit(row)['original_gone']:continue
                            raise RuntimeError('Pilot member exited before READY')
                        command=member.cmdline();self.require_child_command(cfg,row['exe'],command)
                        if not checked_job.membership_pid(member.pid):raise RuntimeError('Pilot READY member Job changed')
                        row['argv']=command
                    births=directory/'births.json';self.write(births,state['owned_identities'])
                    state.update(births=str(births),births_sha256=m.digest(births));safety.save(state)
                    release_revision.ready(self,state,cfg,dict(assets=self.fixed['parent_data_proof']['receipt']['assets']),monitor,observation,runtime_root=self.ctx.runtime)
                    safety.save(state)
                    self.write(directory/'ready.json',dict(state=state,actual_environment=self.actual_environment(state),metrics=safety.get_json('/metrics')))
                    return directory,state

    def serve(self,index):
        retained={};result=dict(kind=a.KIND,index=index,status='starting');directory=self.ctx.pilot;failure=None;started=False
        with runner.shared_operation(data=self.ctx.data),runner.candidate_interrupts(retained):
            try:
                result['prestart']=self.production_inactive()
                a.load(self.ctx,self.approved,full=True)
                with runner.MemoryMonitor(self.ctx.pilot/f'memory-{index}.jsonl') as monitor:
                    monitor.cancel_requested=lambda:retained.get('cancel_requested',False)
                    try:
                        directory,state=self.start(index,monitor,retained);started=True
                        print('PREFILL TIMING PILOT READY '+str(index),flush=True)
                        while True:
                            monitor.check();self.require_tracking(state)
                            if (self.ctx.pilot/'aborted.json').exists():raise KeyboardInterrupt
                            time.sleep(.5)
                    except KeyboardInterrupt:
                        if not started:raise
                        result['status']='stopping'
                    except BaseException as error:
                        failure=error;raise
                    finally:
                        state=retained.get('state')
                        if retained.get('spawn_possible'):
                            monitor.expect_engine_exit()
                            try:
                                if started:
                                    runner.wait_request_release(state)
                                    state.update(phase='stopping',cleanup_pending=True);safety.save(state)
                                    safety.stop_owned(state)
                                else:runner.cleanup_failed_start(retained.get('process'),retained.get('observer'),state)
                                proof=runner.pending_exit_proof(retained)
                                if not proof['complete']:raise RuntimeError('Pilot whole-cohort exit remains pending')
                                proof['client_readers']=retained['reader'].proof
                                state.update(phase='stopped',cleanup_pending=False);safety.save(state);result['cleanup']=proof
                            except BaseException:
                                state.update(phase='cleanup-pending',cleanup_pending=True);safety.save(state)
                                runner.hold_pending_cleanup(retained,result,Path(state['config']).parent)
                                raise
                result['status']='stopped'
                samples={str(slot):m.digest(self.ctx.pilot/f'request-{index}-{slot}.sample.json') for slot in range(3)
                         if (self.ctx.pilot/f'request-{index}-{slot}.sample.json').is_file()}
                complete=(len(samples)==3 and all(m.read_json(self.ctx.pilot/f'request-{index}-{slot}.sample.json').get('valid') is True for slot in range(3))
                          and result.get('cleanup',{}).get('complete') is True)
                self.write(self.ctx.pilot/f'completion-{index}.json',dict(complete=complete,samples=samples,cleanup=result.get('cleanup')))
                if not complete:self.abort(dict(index=index,reason='Incomplete request/cohort'))
            except BaseException as error:
                result.update(status='failed',error_type=type(error).__name__,reason=str(error));self.abort(dict(index=index,error_type=type(error).__name__))
                raise
            finally:
                if retained.get('state'):directory=Path(retained['state']['config']).parent
                process=retained.get('process')
                result['server_popen']=dict(pid=process.pid,created=retained['state'].get('created')) if process is not None else None
                result['spawn_attempted']=bool(retained.get('spawn_possible'))
                self.write(directory/'result.json',result)

    def request(self,index,slot):
        try:return self._request(index,slot)
        except BaseException as error:
            self.abort(dict(index=index,slot=slot,preflight_or_request_failure=type(error).__name__))
            raise

    def _request(self,index,slot):
        a.load(self.ctx,self.approved)
        state=self.read_state()
        if state.get('pilot_index')!=index:raise RuntimeError('Client index differs from immutable running start')
        self.client_ready(state);actual=self.actual_environment(state);loader=self.actual_loader(state)
        before=safety.get_json('/metrics')
        if before.get('totals',{}).get('requests')!=slot:raise RuntimeError('Unexpected/unbudgeted prior API request')
        registration=self.register_client(state,slot)
        a.reserve_request(self.ctx.pilot,index,slot)
        content=self.fixed['warmup'] if slot==0 else self.fixed['fixture'][slot-1]['content']
        monitor=normal.NormalMonitor(self.ctx.pilot/'unused-client-monitor')
        cfg=self.authority(state)['snapshot_config'];monitor.engine=next(r for r in state['owned_identities'] if Path(r['exe'])==Path(cfg['exe']))
        monitor.images=[r for r in state['owned_identities'] if Path(r['exe'])==Path(cfg['vision']['exe' if state['loader']['reader_backend']=='hip' else 'cpu_exe'])]
        sample=dict(index=index,slot=slot,arm=a.ORDER[index],status='failed',valid=False,censored=False,
                    actual_environment=actual,actual_loader=loader,metrics_before=before,
                    client_invoked_at=time.time(),client_invoked_monotonic=time.monotonic())
        log=Path(state['engine_log']);offset=log.stat().st_size;sample['log_offset']=offset
        try:
            runner.stream_request(state,monitor,content,deadline_s=120,partial=sample,
                request_body=release_trial.body(content,quantitative=True),require_answer=False,
                ready_check=lambda current:self.client_ready(current))
            sample.update(status='completed',generation_status='completed')
            runner.wait_request_release(state,ready_check=lambda current:self.client_ready(current))
            sample['request_release_confirmed_at']=time.time()
        except BaseException as error:
            timeout=bool(sample.get('timeout_requested_at'))
            sample.update(status='timeout' if timeout else ('cleanup_failed' if sample.get('generation_status')=='completed' else 'failed'),
                          censored=timeout,error_type=type(error).__name__)
            if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
        finally:
            self.publish_reader(registration,state,sample)
            sample['client_registration']=dict(path=registration['path'],sha256=registration['sha256'])
            sample['client_terminal_at']=time.time()
            with log.open('rb') as f:f.seek(offset);sample['engine_log_delta']=f.read().decode('utf-8',errors='replace')
            try:
                case=self.fixed['fixture'][slot-1] if slot else None
                errors=release_trial.cold_errors(sample,case,sample['engine_log_delta']) if slot else ([] if sample['status']=='completed' else ['Warmup incomplete'])
                after=safety.get_json('/metrics');sample['metrics_after']=after
                if after.get('totals',{}).get('requests')!=slot+1:errors.append('Unexpected API request count')
                if slot==0 and sample.get('usage',{}).get('prompt_tokens')!=63:errors.append('Fixed warmup no longer 63 prompt tokens')
                sample['timing']=timing_parser.parse(sample['engine_log_delta'],timing='STRATA_PREFILL_TIMING' in a.ARMS[a.ORDER[index]],
                       prompt_tokens=sample.get('usage',{}).get('prompt_tokens',0),quantitative=slot>0)
                sample.update(errors=errors,valid=not errors)
            except BaseException as error:
                sample.update(valid=False,analysis_error=dict(type=type(error).__name__,message=str(error)))
            self.write(self.ctx.pilot/f'request-{index}-{slot}.sample.json',sample)
            if not sample['valid']:self.abort(dict(index=index,slot=slot,status=sample['status']))
        return sample


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','serve','request','status','summary'))
    parser.add_argument('--sha256');parser.add_argument('--index',type=int);parser.add_argument('--slot',type=int)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args();ctx=a.production_context()
    if args.action=='prepare':print(json.dumps(a.prepare(ctx)));return
    if not args.sha256:parser.error('Exact reviewed authority SHA256 required')
    pilot=PilotRuntime(ctx,args.sha256)
    if args.action=='status':print(json.dumps(pilot.read_state()));return
    if args.action=='summary':
        from .pilot_analysis import summarize
        value=summarize(ctx,pilot.fixed);pilot.write(ctx.pilot/'summary.json',value)
        print(json.dumps(dict(complete=value['complete'],starts=value['actual_starts'],requests=value['actual_requests'])));return
    if not args.execute:parser.error('Explicit reviewed execution gate required')
    if args.action=='serve':pilot.serve(args.index)
    else:
        sample=pilot.request(args.index,args.slot)
        print(json.dumps(dict(index=args.index,slot=args.slot,status=sample['status'],valid=sample['valid'])))
        if not sample['valid']:raise SystemExit(2)


if __name__=='__main__':main()
