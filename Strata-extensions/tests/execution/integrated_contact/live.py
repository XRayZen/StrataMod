"""Concrete T46 transports; import is inert. All CLI/API/GPU work is explicit.

run_stage is shared by the CPU dependency fixture and these actual transports.
No publisher is present: independent numeric and publication receipts are inputs.
"""
from pathlib import Path
import argparse
import contextlib
import copy
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
import runner as C

STARTUP_COPY_KEYS=('HIP_PATH','ROCM_PATH','HIP_PLATFORM','TMP','TEMP')
STARTUP_ENV_KEYS=(*STARTUP_COPY_KEYS,'PATH','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES','GPU_DEVICE_ORDINAL','HIP_DEVICE_ORDER')

def environment_projection(env):
    return {name:dict(present=name in env,value=env.get(name))for name in STARTUP_ENV_KEYS}

@contextlib.contextmanager
def observer_env(value):
    old=os.environ.get(C.ENV)
    try:
        if value is None:os.environ.pop(C.ENV,None)
        else:os.environ[C.ENV]=str(value)
        yield
    finally:
        if old is None:os.environ.pop(C.ENV,None)
        else:os.environ[C.ENV]=old

def quiescent_guard(manager,psutil):
    """Fresh read-only publication guard; no stop, metadata edit or adopt."""
    state=manager.read_state()
    C.require(not state or state.get('phase')in('stopped','failed'),'publication owner active or unknown')
    identities=(state or {}).get('owned_identities',[])
    if state and state.get('pid')is not None:identities=[state,*identities]
    for identity in identities:C.require(manager.process_identity_status(identity).status=='gone','publication old cohort not proven gone')
    listeners=[x for x in psutil.net_connections(kind='tcp')if x.laddr and x.laddr.port==18080 and x.status==psutil.CONN_LISTEN]
    C.require(not listeners,'publication listener active or foreign')
    for p in psutil.process_iter(['name']):
        C.require((p.info.get('name')or'').lower()!='strata-deepseek.exe','publication native owner active or foreign')
    return dict(quiescent=True,stop_sent=False,kill_sent=False,checked_at_ns=time.monotonic_ns())

@contextlib.contextmanager
def publication_guard_scope():
    """Caller passes yielded callback to existing explicit publisher.

    Holds the EXISTING CLI operation lock through that caller's finally. This
    provides no publish/rollback/retry action and is never a normal start gate.
    """
    sys.path.insert(0,str(C.DATA));import strata_cli,manage_runtime,psutil
    with strata_cli.operation_lock():
        guard=lambda:bool(quiescent_guard(manage_runtime,psutil))
        guard();yield guard

def http_request(base,body,evidence=None):
    """Completed requests always require the original HTTP [DONE]."""
    return _http_request(base,body,evidence)

def control_http_request(base,body,evidence,cancelled_control):
    """Only the declared trial cancellation can end at a bound native EOF."""
    C.require(evidence is not None and callable(cancelled_control),'typed control evidence required')
    return _http_request(base,body,evidence,cancelled_control)

def control_choice(choice):
    """Keep ordinary SSE shapes; reject malformed control data before GEN2."""
    C.require(isinstance(choice,dict)and type(choice.get('index'))is int and choice['index']>=0 and isinstance(choice.get('delta'),dict)and 'finish_reason'in choice and(choice['finish_reason']is None or type(choice['finish_reason'])is str),'control HTTP choice index/delta/finish')
    delta=choice['delta']
    for key in('role','content','reasoning_content'):
        if key in delta:C.require(delta[key]is None or type(delta[key])is str,'control HTTP delta text')
    if delta.get('tool_calls')is not None:
        C.require(isinstance(delta['tool_calls'],list),'control HTTP tool calls')
        for call in delta['tool_calls']:
            C.require(isinstance(call,dict)and type(call.get('index'))is int and call['index']>=0,'control HTTP tool index')
            for key in('id','type'):
                if key in call:C.require(type(call[key])is str,'control HTTP tool text')
            if 'function'in call:
                C.require(isinstance(call['function'],dict),'control HTTP tool function')
                for key in('name','arguments'):
                    if key in call['function']:C.require(type(call['function'][key])is str,'control HTTP tool function text')
    if choice.get('logprobs')is not None:
        lp=choice['logprobs'];C.require(isinstance(lp,dict),'control HTTP logprobs')
        if lp.get('content')is not None:
            C.require(isinstance(lp['content'],list)and all(isinstance(r,dict)for r in lp['content']),'control HTTP logprob content')

def _http_request(base,body,evidence,cancelled_control=None):
    start=time.monotonic_ns();chunks=[];received=[];raws=[];status=None;headers=[]
    failure=None;secondary=[];control=None;ended=False
    try:
        req=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(body,allow_nan=False).encode('utf8'),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=None)as response:
            status=response.status;headers=list(getattr(response,'headers',{}).items())
            C.require(type(status)is int and status==200,'HTTP status')
            for raw in response:
                raws.append(raw)
                line=raw.decode('utf8').rstrip('\r\n')
                if not line or line.startswith(':'):continue
                if line.startswith('event:'):continue
                C.require(line.startswith('data:'),'SSE field')
                data=line[5:].strip();now=time.monotonic_ns()
                chunks.append('[DONE]' if data=='[DONE]' else json.loads(data));received.append(now)
            ended=True
        if cancelled_control is None:
            C.require(chunks and chunks[-1]=='[DONE]','HTTP SSE closure')
        else:
            # Never let an arbitrary disconnect start the second request.
            C.require(chunks and all(isinstance(c,dict)or(c=='[DONE]'and i==len(chunks)-1)for i,c in enumerate(chunks)),'control HTTP chunks')
            metadata=None
            for chunk in chunks:
                if chunk=='[DONE]':continue
                C.require('error'not in chunk and chunk.get('model')==body['model']and chunk.get('object')=='chat.completion.chunk'and isinstance(chunk.get('id'),str)and chunk['id']and type(chunk.get('created'))is int and chunk['created']>=0,'control HTTP metadata/error')
                current=(chunk['id'],chunk['object'],chunk['created'])
                if metadata is None:metadata=current
                C.require(current==metadata and isinstance(chunk.get('choices'),list)and all(isinstance(c,dict)for c in chunk['choices']),'control HTTP metadata/choices')
                json.dumps(chunk,allow_nan=False) # JSON's nonfinite extensions are not valid SSE data.
                for choice in chunk['choices']:control_choice(choice)
                for key in('usage','prompt_progress','timings'):
                    if key in chunk:C.require(chunk[key]is None or isinstance(chunk[key],dict),'control HTTP '+key)
            C.require(metadata is not None,'control HTTP response missing')
            control=cancelled_control()
    except BaseException as error:
        failure=error
        if status is None:status=getattr(error,'code',None)
    clock=_http_clock(start,chunks,received)
    if evidence is not None:
        evidence=Path(evidence)
        for suffix,value,raw in [('http.raw',b''.join(raws),True),('http-chunks.json',chunks,False),('http-clock.json',clock,False)]:
            try:
                path=Path(str(evidence)+'-'+suffix)
                if raw:
                    with path.open('xb')as output:output.write(value)
                else:C.save(path,value)
            except BaseException as error:secondary.append(dict(stage=suffix,error=repr(error)))
        try:C.save(Path(str(evidence)+'-http.json'),dict(status=status,headers=headers,EOF=ended,HTTP_DONE=bool(chunks and chunks[-1]=='[DONE]'),control_cancellation=control,error=repr(failure)if failure else None,secondary_errors=list(secondary),raw_path=str(evidence)+'-http.raw',chunks_path=str(evidence)+'-http-chunks.json',clock_path=str(evidence)+'-http-clock.json'))
        except BaseException as error:secondary.append(dict(stage='http-receipt',error=repr(error)))
    if failure is not None:
        if secondary:failure.add_note('Separate HTTP evidence errors: '+repr(secondary))
        raise failure
    if secondary:raise RuntimeError('HTTP evidence incomplete: '+repr(secondary))
    return chunks,clock

def _http_clock(start,chunks,received):
    times=[]
    for ch,clock in zip(chunks,received):
        if isinstance(ch,dict)and isinstance(ch.get('choices'),list)and any(isinstance(c,dict)and isinstance(c.get('delta'),dict)and(c['delta'].get('content')or c['delta'].get('reasoning_content'))for c in ch['choices']):times.append(clock)
    return dict(domain='host monotonic HTTP content receipt; includes observer synchronous I/O',start_ns=start,end_ns=time.monotonic_ns(),first_content_ns=times[0]if times else None,TTFT_seconds=(times[0]-start)/1e9 if times else None,TPOT_seconds=None,content_event_interval_seconds=(times[1]-times[0])/1e9 if len(times)==2 and times[1]>times[0]else None,TPOT_reason='HTTP content events lack individual-ID association; raw pipe batch timing is separate',receipt_ns=received,GPU_kernel_or_SSD_time=False)

class ActualTransport:
    def __init__(self,attempt,mode,total=None,return_only=False):
        import psutil
        self.psutil=psutil;self.attempt=Path(attempt);self.mode=mode;self.return_only=return_only
        self.engine=None;self.process=None;self.http=None;self.worker=None;self.port=None;self.state=None;self.cohort=[];self.memory=[];self.cfg=None;self.spec=None;self.total=total
        self.helper=C.module('t46_actual_helper',C.R/'Strata-extensions/control/deepseek_launch.py')
        sys.path.insert(0,str(C.MEMORY.parent));self.mem=C.module('t46_actual_memory',C.MEMORY)
        sys.path.insert(0,str(C.DATA));self.manager=__import__('manage_runtime')
        self.tokenizer=None;self.codec=None;self.prepared=None

    def cli(self,name,args,env=None):
        cmd=[str(Path('C:/Windows/System32/cmd.exe')),'/d','/c',str(C.DATA/'strata.cmd'),*args]
        with(self.attempt/(name+'.stdout')).open('xb')as out,(self.attempt/(name+'.stderr')).open('xb')as err:
            p=subprocess.run(cmd,cwd=C.DATA.parent,env=env,stdout=out,stderr=err)
        C.save(self.attempt/(name+'.json'),dict(command=cmd,exit=p.returncode,stdout=C.row(out.name),stderr=C.row(err.name)))
        C.require(p.returncode==0,name+' exit failure')

    def no_active(self):
        self.cli('status-before',['status'])
        state=self.manager.read_state()
        C.require(not state or state.get('phase')in('stopped','failed'),'active or unknown consumer; no automatic stop')
        self.no_listener(18080)

    def no_listener(self,port):
        listeners=[x for x in self.psutil.net_connections(kind='tcp')if x.laddr and x.laddr.port==port and x.status==self.psutil.CONN_LISTEN]
        C.require(not listeners,'owned listener not gone')

    def check_cohort(self):
        for p in self.cohort:
            try:C.require(self.psutil.Process(p['pid']).create_time()!=p['birth'],'same PID/birth survived regular close')
            except self.psutil.NoSuchProcess:pass
        if self.port is not None:self.no_listener(self.port)

    @staticmethod
    def close_constructed(engine,process):
        # Constructor ownership is the retained original Popen object/handle.
        # PID/birth/cohort sampling can fail after construction and must not
        # replace this authority or prevent the already-owned regular close.
        C.require(process is not None and engine.proc is process,'constructed engine original Popen changed; no foreign close')
        engine.close();C.require(process.poll()==0,'constructed native normal exit')

    def retain_stderr(self,engine,process):
        # Keep these original objects before selected engine.close clears proc.
        C.require(engine.proc is process,'stderr original Popen changed')
        self.stderr_native=(process,engine.log,Path(engine.log_path).resolve())

    def snapshot_stderr(self,exitcode=None,exit_observed=False):
        process,log,path=self.stderr_native;errors=[]
        if not exit_observed:
            try:exitcode=process.poll()
            except BaseException as e:errors.append(dict(stage='native-exit',error=repr(e)))
        closed=getattr(log,'closed',False)is True
        raw=None
        try:
            data=path.read_bytes()
            try:
                with(self.attempt/'native-stderr.raw').open('xb')as output:output.write(data)
                raw=C.row(self.attempt/'native-stderr.raw')
            except BaseException as e:errors.append(dict(stage='raw-save',error=repr(e)))
        except BaseException as e:errors.append(dict(stage='raw-read',error=repr(e)))
        receipt=dict(schema='strata-t46-contact-native-stderr/v1',package_id=C.ID,bundle_id=C.BUNDLE,compiled_source_id=C.CONTACT_SOURCE,binding=getattr(self,'binding',None),source_log=str(path),native_pid=process.pid,exit=exitcode,log_closed=closed,raw=raw,complete=exitcode==0 and closed and raw is not None and not errors,secondary_errors=errors,explicit_native_handle_close=None)
        C.save(self.attempt/'native-stderr.json',receipt)
        return receipt

    def memory_now(self,point):
        pid=self.process.pid if self.process else self.state['pid']
        expected=self.memory[0]['birth']if self.memory else None
        sample=self.mem.physical_memory(pid,expected);sample['point']=point;self.memory.append(sample)
        return sample

    def startup_environment(self,cfg,observer):
        # Existing trial API; both of its mkdir effects stay in this fresh output.
        out=self.attempt/('startup-'+str(time.monotonic_ns()));out.mkdir(exist_ok=False)
        helper_path=C.R/'Strata-extensions/tests/serve_provider/build_verify.py'
        helper=C.module('t46_private_runtime_environment_'+out.name,helper_path)
        helper.BUILD=out/'helper-build'
        inherited=dict(os.environ);env=dict(inherited);env.update(cfg.get('env',{}))
        env['PATH']=os.pathsep.join([str(Path(cfg['exe']).parent),'C:/Windows/System32','C:/Windows'])
        if observer is None:env.pop(C.ENV,None)
        else:env[C.ENV]=str(observer)
        supplied=helper.runtime_env(out/'env-bundle')
        values={key:supplied[key]for key in STARTUP_COPY_KEYS};env.update(values)
        receipt=dict(schema='strata-t46-startup-env/v1',inherited=environment_projection(inherited),cfg_overlay=environment_projection(cfg.get('env',{})),final=environment_projection(env),helper_values=values,helper_calls=1,helper_sources=[C.row(C.R/('Strata-extensions/tests/'+name+'/build_verify.py'))for name in ('serve_provider','core','cache','layer_split')],helper_BUILD=str(helper.BUILD),helper_bundle=str(out/'env-bundle'),source=C.row(__file__),candidate=C.row(C.CANDIDATE_PROOF),selected_seal=C.load(self.attempt/'preseal.json')if(self.attempt/'preseal.json').is_file()else None,cwd=cfg['cwd'],parent_environment_unchanged=dict(os.environ)==inherited)
        C.require(receipt['parent_environment_unchanged'],'runtime_env changed parent environment')
        return env,receipt,out

    def failed_constructor(self,engine,process,cfg,original,out):
        # Diagnostic only. The retained object is authority; never reopen a PID.
        receipt=dict(original_error=repr(original),pid=getattr(process,'pid',None),exit=None,exit_unsigned=None,wait_exit=None,handle_closed=None,pipe_log_closed={},normal_close=False,secondary_errors=[])
        errors=receipt['secondary_errors']
        try:
            C.require(process is not None and engine.proc is process,'partial native original Popen changed or missing; no foreign close')
            exitcode=process.poll();receipt['exit']=exitcode
            if exitcode is None:
                observed=self.psutil.Process(process.pid)
                C.require(Path(observed.exe()).resolve()==Path(cfg['exe']).resolve(),'partial native foreign executable')
                C.require(engine.proc is process,'partial native original Popen changed; no foreign close')
                engine.close();receipt['normal_close']=True;receipt['exit']=process.poll()
            else:
                # CPython wait uses the established returncode for an exited
                # child. Do not close a handle before all exit reads finish.
                waited=process.wait();receipt['wait_exit']=waited
                C.require(waited==exitcode==process.returncode,'partial native exit observations disagree')
                receipt['exit_unsigned']=int(waited)&0xffffffff
                for name,stream in [('stdin',getattr(process,'stdin',None)),('stdout',getattr(process,'stdout',None)),('log',getattr(engine,'log',None))]:
                    try:
                        if stream is None or not hasattr(stream,'close'):receipt['pipe_log_closed'][name]=None
                        else:
                            if not stream.closed:stream.close()
                            receipt['pipe_log_closed'][name]=bool(stream.closed)
                    except BaseException as error:errors.append(dict(stage=name+'-close',error=repr(error)))
                handle=getattr(process,'_handle',None)
                C.require(handle is not None and hasattr(handle,'closed') and callable(getattr(handle,'Close',None)),'original Windows handle unavailable')
                if not handle.closed:handle.Close()
                receipt['handle_closed']=bool(handle.closed)
                C.require(receipt['handle_closed'],'original Windows handle close unconfirmed')
        except BaseException as error:errors.append(dict(stage='partial-construction-observation',error=repr(error)))
        try:C.save(out/'constructor-failure.json',receipt)
        except BaseException as error:errors.append(dict(stage='constructor-failure-record',error=repr(error)))
        if errors:original.add_note('T46 constructor secondary diagnostics: '+repr(errors))
        return receipt

    def service(self,cfg,observer=None):
        # Same selected package modules/Recipe/Service as accepted CPU probe.
        sys.path[:0]=[str(C.PACKAGE/'base'),str(C.PACKAGE/'base/tools')]
        family_key='STRATA_FAMILY_SOURCE_ROOT';old_family=os.environ.get(family_key)
        try:
            os.environ[family_key]=str(C.PACKAGE/'base')
            server=C.module('serve.server',C.PACKAGE/'native/server/serve/server.py')
        finally:
            if old_family is None:os.environ.pop(family_key,None)
            else:os.environ[family_key]=old_family
        hook=C.module('t46_selected_actual_hook',C.PACKAGE/'Strata-extensions/models/deepseek41/server_hooks.py')
        env,diagnostic,out=self.startup_environment(cfg,observer)
        env[family_key]=str(C.PACKAGE/'base') # same child value as the old parent-set route
        with observer_env(observer):
            C.require(hook.install(server,cfg),'selected family hook')
            engine=server.StrataEngine.__new__(server.StrataEngine)
            args=hook.native_args(cfg)
            diagnostic['native_argv']=[cfg['exe'],'--serve',*args]
            # This very mapping is passed through selected server to Popen.
            diagnostic['final']=environment_projection(env)
            C.save(out/'execution-environment.json',diagnostic)
            try:
                server.StrataEngine.__init__(engine,cfg['exe'],args,cwd=cfg['cwd'],env=env,log=str(self.attempt/('minimum-native.log'if observer is None else'native.log')))
                if C.contact_selected() and observer is not None:self.retain_stderr(engine,engine.proc)
            except BaseException as original:
                # Keep the actual Popen handle if initialization failed after
                # native spawn. Do not rely on an assignment after __init__.
                process=getattr(engine,'proc',None)
                if C.contact_selected() and observer is not None and process is not None:
                    try:self.retain_stderr(engine,process)
                    except BaseException as e:original.add_note('Separate stderr retain exception: '+repr(e))
                constructor_receipt=self.failed_constructor(engine,process,cfg,original,out)
                if getattr(self,'stderr_native',None)is not None:
                    # failed_constructor may already have closed its original
                    # handle. Reuse its observed exit; do not read Popen again.
                    try:self.snapshot_stderr(constructor_receipt['exit'],True)
                    except BaseException as e:original.add_note('Separate stderr capture exception: '+repr(e))
                raise
        return server,hook,engine

    def calibrate(self):
        self.no_active()
        cfg=C.load(C.PROFILE);cfg['runtime_epoch']=time.time_ns()//1000
        common=max(C.minimum(m,cfg['tile_bytes'],cfg['execution_defaults']['cut'])for m in C.MODES)
        # One single noGEN owner sized to the largest all-role minimum; no
        # single-only minimum is silently applied to compute modes.
        cfg['cache_budget']['ram_cache_payload_bytes']=common
        engine=None;process=None;birth=None;info=None;errors=[];selection=None;failure=None
        try:
            server,hook,engine=self.service(cfg);process=engine.proc
            birth=self.psutil.Process(process.pid).create_time();info=copy.deepcopy(engine.info)
            sample=self.mem.physical_memory(process.pid)
            selection=C.select_total(sample['available_physical_bytes'],info['ram_cache_payload_bytes'],info['working_minimum_payload_bytes'],info['deferred_host_sampling'],common)
            if C.contact_selected():
                prior=C.row(C.ORIGINAL_HERE/'one-noGEN-r5-attempt-01/calibration.json')
                C.require(prior['sha256']=='39edcf574c00e40048ba5bacc8aa652ff7f19c9d1ec202b04a90b78de99a2398','contact prior budget provenance')
                reference=C.load(prior['path'])['selection']['payload'];C.require(reference==49480035432,'contact prior reference value')
                fresh=C.uint(selection['payload']);chosen=min(fresh,reference);C.require(chosen>=common,'contact common minimum')
                selection.update(fresh_selected_payload=fresh,prior_reference=prior,prior_reference_payload=reference,payload=chosen,selection_reason='min(fresh selection, source-bound 86c reference); no upward rounding',prior_is_8d_calibration=False)
        except BaseException as e:
            failure=e;raise
        finally:
            if engine is not None:
                try:self.close_constructed(engine,process)
                except BaseException as e:errors.append(dict(stage='regular-close',error=repr(e)))
            try:C.save(self.attempt/'calibration.json',dict(config=cfg,info=info,memory=locals().get('sample'),selection=selection,original_error=repr(failure)if failure else None,close_errors=list(errors),exit=process.poll()if process else None,GEN_count=0,common_minimum=common,per_mode_minima={m:C.minimum(m,cfg['tile_bytes'],cfg['execution_defaults']['cut'])for m in C.MODES},physical_peak=None))
            except BaseException as e:errors.append(dict(stage='calibration-log',error=repr(e)))
            if failure is None and errors:raise RuntimeError('minimum cleanup/log failure: '+repr(errors))
        C.require(process.poll()==0 and not errors,'minimum owner regular close')
        try:C.require(self.psutil.Process(process.pid).create_time()!=birth,'minimum same owner survived')
        except self.psutil.NoSuchProcess:pass
        self.total=selection['payload'];return self.total

    def start_candidate(self):
        cfg=self.helper.overlay(C.load(C.PROFILE),dict(mode='single',ram_cache_payload_bytes=self.total));cfg['runtime_epoch']=time.time_ns()//1000
        observer=C.module('t46_actual_spec',C.B/'observer-capture.py');self.spec=observer.spec(self.attempt,cfg)
        C.save(self.attempt/'spec.json',self.spec);self.cfg=cfg;C.save(self.attempt/'config.json',cfg)
        C.save(self.attempt/'launch-seal.json',dict(config=C.row(self.attempt/'config.json'),observer_spec=C.row(self.attempt/'spec.json'),request=C.request(),package_id=C.ID,bundle_id=C.BUNDLE,native_args=self.helper.native_command(cfg),before_native_constructor=True))
        server,hook,engine=self.service(cfg,self.attempt/'spec.json');self.engine=engine;self.process=engine.proc;self.info_parser=server.FAMILY_INFO_PARSER
        self.cohort=[dict(pid=self.process.pid,birth=self.psutil.Process(self.process.pid).create_time(),exe=self.psutil.Process(self.process.pid).exe())]
        self.tokenizer=hook.TokenizerFacade(C.PACKAGE/'resources/tokenizer.json');self.codec=hook.codec
        svc=server.Service(engine,self.tokenizer,None,sampling_defaults={});self.svc=svc
        self.prepared=self.prepare(svc)
        self.http=server.Server(('127.0.0.1',0),server.make_handler(svc));self.port=self.http.server_port
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True);self.worker.start();self.base='http://127.0.0.1:'+str(self.port)
        self.binding=dict(owner=engine.trial_observer.owner,hook_sha256=engine.trial_observer.hook_sha256,runtime_epoch=cfg['runtime_epoch'])
        actual=self.binding['owner'];C.require(actual['server']==dict(pid=os.getpid(),birth=self.psutil.Process().create_time())and actual['engine']==dict(pid=self.process.pid,birth=self.cohort[0]['birth']),'candidate actual server/native birth binding')
        if self.spec:self.bind_public_owner()
        self.memory_now('actual-ready');C.save(self.attempt/'startup-info.json',copy.deepcopy(engine.info))
        C.save(self.attempt/'owner.json',dict(binding=self.binding,cohort=self.cohort,server=dict(pid=os.getpid(),birth=self.psutil.Process().create_time()),entry='candidate prepared Service HTTP',native_Popen_handle_bound=True))

    def prepare(self,svc):
        ids,thinking,maximum=svc.prepare(C.request()['messages'],None,{},req=C.request())
        C.require(list(ids)==C.PROMPT and not thinking and maximum==2,'actual Service.prepare exact official request')
        return ids

    def start_public(self):
        self.no_active();self.port=18080;profile=C.DATA/'profiles'/f'{C.MODEL}-4096.json'
        cfg=self.helper.overlay(C.load(profile),dict(mode=self.mode,ram_cache_payload_bytes=self.total))
        C.require(cfg['runtime_package']['id']==C.ID and cfg['bundle_id']==C.BUNDLE,'published final package required')
        observer=C.module('t46_actual_public_spec',C.B/'observer-capture.py');self.spec=None if self.return_only else observer.spec(self.attempt,cfg)
        env=dict(os.environ);env.pop(C.ENV,None)
        if self.spec is not None:C.save(self.attempt/'spec.json',self.spec);env[C.ENV]=str(self.attempt/'spec.json')
        args=['start','--model',C.MODEL,'--context','4096','--mode',self.mode,'--ram-cache-payload-bytes',str(self.total)]
        C.save(self.attempt/'launch-seal.json',dict(profile=C.row(profile),expected_resolved_without_epoch=cfg,observer_spec=C.row(self.attempt/'spec.json')if self.spec else None,request=C.request()if not self.return_only else None,CLI_args=args,package_id=C.ID,bundle_id=C.BUNDLE,before_CLI_start=True))
        try:self.cli('start',args,env)
        finally:
            # Capture owned partial launch too, so command/log failures do not
            # bypass normal finally cleanup. Never adopt a pre-existing owner.
            state=self.manager.read_state()
            if state and state.get('phase')not in('stopped','failed'):
                self.manager.require_owned_listener(state)
                actual=C.load(state['config'])
                C.require(actual.get('runtime_package',{}).get('id')==C.ID and actual.get('bundle_id')==C.BUNDLE and actual.get('placement',{}).get('mode')==self.mode,'partial launch exact requested config')
                self.state=state;self.cfg=actual
                self.cohort=[dict(pid=p.pid,birth=p.create_time(),exe=p.exe())for p in self.manager.verified_cohort(state)]
        C.require(self.state is not None,'no owned launch state')
        self.manager.require_family_ready(self.state);cfg=self.cfg;self.port=cfg['port'];self.base='http://127.0.0.1:'+str(self.port)
        C.save(self.attempt/'launch-binding.json',dict(state=self.state,launch_binding=self.state.get('launch_binding'),config=C.row(self.state['config'])))
        C.save(self.attempt/'config.json',cfg);C.require(cfg['cache_budget']['ram_cache_payload_bytes']==self.total,'one explicit total RAM')
        metrics=self.manager.get_json('/metrics');info=metrics['engine'];C.save(self.attempt/'startup-info.json',info)
        self.helper.validate_ready_info(cfg,info)
        engine_items=[p for p in self.cohort if Path(p['exe']).resolve()==Path(cfg['exe']).resolve()]
        C.require(len(engine_items)==1,'one exact owned native')
        self.process=self.psutil.Process(engine_items[0]['pid'])
        server_items=[p for p in self.cohort if p['pid']!=engine_items[0]['pid']]
        # Header server must be one verified member of this same launch cohort;
        # verify exact birth after normal stop (not merely trusted log metadata).
        self.binding=dict(runtime_epoch=cfg['runtime_epoch'],hook_sha256=C.HOOK,cohort=self.cohort,engine=engine_items[0])
        self.memory_now('actual-ready')
        # Actual selected Service.prepare in a CPU shell, no second native.
        sys.path[:0]=[str(C.PACKAGE/'base'),str(C.PACKAGE/'base/tools')]
        os.environ['STRATA_FAMILY_SOURCE_ROOT']=str(C.PACKAGE/'base')
        server=C.module('serve.server',C.PACKAGE/'native/server/serve/server.py');hook=C.module('t46_public_join_hook',C.PACKAGE/'Strata-extensions/models/deepseek41/server_hooks.py')
        with observer_env(None):hook.install(server,cfg)
        self.tokenizer=hook.TokenizerFacade(C.PACKAGE/'resources/tokenizer.json');self.codec=hook.codec
        from types import SimpleNamespace
        shell=SimpleNamespace(max_context=4096,info=copy.deepcopy(info),batch=0,alive=lambda:True)
        self.prepared=self.prepare(server.Service(shell,self.tokenizer,None,sampling_defaults={}))

    def start(self):
        if self.mode=='single'and not self.return_only:self.start_candidate()
        else:self.start_public()

    def fresh_INFO(self):
        engine=self.engine;process=engine.proc;generation=engine.gen;locked=False
        receipt=dict(schema='strata-t46-fresh-INFO/v1',ok=False,error=None,send=None,send_ns=None,responses=[],parsed=None,config=C.row(self.attempt/'config.json'),generation=generation)
        def owner():
            C.require(self.engine is engine and engine.proc is process and engine.gen==generation and engine.alive(),'INFO original engine alive')
            actual=self.psutil.Process(process.pid)
            value=dict(pid=actual.pid,birth=actual.create_time())
            C.require(value==self.binding['owner']['engine']and self.cfg['runtime_epoch']==self.binding['runtime_epoch']and engine.trial_observer.owner==self.binding['owner'],'INFO same owner/epoch')
            C.require(engine.active_cookie is None and engine.trial_observer.active is None,'INFO request still active')
            return value
        try:
            while not locked:
                owner();locked=engine.ctl.acquire(timeout=.5)
            receipt['owner_before']=owner()
            receipt['boundary']=C.fresh_INFO_boundary(self.attempt,self.spec,self.binding)
            C.require(engine.trial_observer.cookies==receipt['boundary']['cookies'],'INFO observer completed cookies')
            try:pending=engine.lines.get_nowait()
            except queue.Empty:pass
            else:
                receipt['responses'].append(dict(line=pending,monotonic_ns=time.monotonic_ns(),before_send=True))
                raise ValueError('INFO control queue not clean')
            receipt['send']='INFO';receipt['send_ns']=time.monotonic_ns();engine._send('INFO')
            # Same reader/queue and existing _drain_control default wait/liveness.
            deadline=time.monotonic()+300.0
            while True:
                owner();remaining=deadline-time.monotonic();C.require(remaining>0,'INFO response timeout')
                try:line=engine.lines.get(timeout=max(.1,min(1.,remaining)))
                except queue.Empty:continue
                receipt['responses'].append(dict(line=line,monotonic_ns=time.monotonic_ns()))
                C.require(type(line)is str and line.startswith('INFO '),'INFO response EOF/error/unexpected line')
                parsed=self.info_parser(line[5:])
                # The family JSON parser accepts NaN/Infinity; never put those
                # unsavable nested values in the otherwise raw-safe receipt.
                json.dumps(parsed,allow_nan=False)
                C.require(type(parsed)is dict and type(parsed.get('core_position'))is int and parsed['core_position']>=0,'INFO response position type')
                receipt['parsed']=parsed;receipt['owner_after']=owner();receipt['ok']=True
                return copy.deepcopy(parsed)
        except BaseException as error:
            receipt['error']=dict(type=type(error).__name__,message=str(error));raise
        finally:
            pending=sys.exception()
            try:C.save(self.attempt/'fresh-INFO-receipt.json',receipt)
            except BaseException as save_error:
                if pending is None:raise
                pending.add_note('fresh INFO receipt save failed: '+repr(save_error))
            finally:
                if locked:engine.ctl.release()

    def capture(self):
        C.save(self.attempt/'request.json',C.request())
        for label in ('control','complete'):
            if label=='control':chunks,clock=control_http_request(self.base,C.request(),self.attempt/label,self.control_cancelled)
            else:chunks,clock=http_request(self.base,C.request(),self.attempt/label)
            C.save(self.attempt/(label+'-sse.json'),chunks);C.save(self.attempt/(label+'-clock.json'),clock)
            self.memory_now('after-'+label)
        C.save(self.attempt/'clock.json',C.load(self.attempt/'complete-clock.json'))
        info=(self.public_INFO()if self.engine is None else self.fresh_INFO())if C.contact_selected() else(copy.deepcopy(self.engine.info)if self.engine else self.manager.get_json('/metrics')['engine'])
        C.save(self.attempt/'final-info.json',info)
        expected=self.helper.native_command(self.cfg)
        argv=self.psutil.Process(self.process.pid).cmdline()
        C.save(self.attempt/'argv-and-INFO.json',dict(native_argv=argv,expected_native_argv=expected,config=C.row(self.attempt/'config.json'),startup=C.load(self.attempt/'startup-info.json'),final=info,epoch=self.cfg['runtime_epoch']))
        C.exact_native_argv(argv,expected,self.cfg['exe'])
        C.save(self.attempt/'service-live-state.json',self.svc.metrics(all_requests=True)if self.engine else self.manager.get_json('/metrics'))

    def control_cancelled(self):
        prefix=self.attempt/'control-observer-prefix.jsonl'
        data=Path(self.spec['output']).read_bytes()
        with prefix.open('xb')as output:output.write(data)
        value=C.cancel_prefix(prefix,self.spec,self.binding)
        C.save(self.attempt/'control-cancellation.json',value)
        return value

    def return_observe(self):
        self.cli('return-status',['status']);self.cli('return-models',['models'])
        metrics=self.manager.get_json('/metrics');C.require(not metrics['requests'],'public single restore GEN0')
        C.require(metrics['engine']['configured_mode']==metrics['engine']['effective_mode']=='single','public single INFO')
        C.save(self.attempt/'return-info.json',dict(metrics=metrics,GEN_count=0,observer_env=False))

    def cleanup(self):
        errors=[]
        if self.engine is not None:
            def observe():self.memory_now('before-close')
            def close():
                try:
                    if self.http:self.http.shutdown();self.http.server_close();self.worker.join()
                finally:
                    self.close_constructed(self.engine,self.process)
            normal=C.module('t46_existing_close',C.R/'build-deepseek-t22/normal-wrapper.py')
            try:normal.observed_close(observe,close,errors)
            except BaseException as e:errors.append(dict(stage='close',error=repr(e)))
            try:self.check_cohort()
            except BaseException as e:errors.append(dict(stage='cohort/listener',error=repr(e)))
            for name,args in [('status-after',['status']),('models-after',['models'])]:
                try:self.cli(name,args)
                except BaseException as e:errors.append(dict(stage=name,error=repr(e)))
            if C.contact_selected():
                try:
                    receipt=self.snapshot_stderr()
                    if not receipt['complete']:errors.append(dict(stage='stderr-incomplete',error=repr(receipt['secondary_errors'])))
                except BaseException as e:errors.append(dict(stage='stderr-capture',error=repr(e)))
            result=dict(ok=not errors,errors=errors)
            C.save(self.attempt/'cleanup.json',result)
        elif self.state is not None:
            result=C.safe_cleanup(self.state,self.manager.read_state,self.manager.require_owned_listener,lambda:self.cli('stop',['stop']),lambda:self.cli('status-after',['status']),lambda:self.cli('models-after',['models']),self.check_cohort,lambda value:C.save(self.attempt/'cleanup.json',value))
        else:
            result=dict(ok=False,errors=[dict(stage='start',error='no owned launch recorded; foreign/unknown stop0')]);C.save(self.attempt/'cleanup.json',result)
        C.save(self.attempt/'memory.json',self.memory)
        if self.spec and self.state and Path(self.spec['output']).is_file():self.bind_public_owner()
        return result

    def public_INFO(self):
        # This transport-only wait is for the explicit trial INFO transaction;
        # ordinary manager/SDK deadlines and the existing 300s INFO wait stay unchanged.
        boundary=C.fresh_INFO_boundary(self.attempt,self.spec,self.binding)
        C.save(self.attempt/'fresh-INFO-boundary.json',dict(schema='strata-t46-public-INFO-boundary/v1',
               boundary=boundary,config=C.row(self.attempt/'config.json'),spec=C.row(self.attempt/'spec.json')))
        started=time.monotonic_ns();status=None;error=None
        body_kind='unobserved';body_record=None;body_read_error=None;partial_type=None
        def partial_body(read_error,primary):
            nonlocal body_kind,body_record,body_read_error,partial_type
            body_read_error=dict(type=type(read_error).__name__,message=str(read_error))
            try:partial=getattr(read_error,'partial',None)
            except BaseException as attribute_error:
                primary.add_note('public INFO partial attribute unavailable: '+repr(attribute_error));return
            partial_type=type(partial).__name__
            if type(partial)is not bytes:return
            body_kind='partial_observed'
            try:
                path=self.attempt/'fresh-INFO-HTTP.partial.raw'
                with path.open('xb')as output:output.write(partial)
                body_record=C.row(path);body_kind='partial_saved'
            except BaseException as save_error:primary.add_note('public INFO HTTP partial body save failed: '+repr(save_error))
        def complete_body(raw):
            nonlocal body_kind,body_record
            body_kind='complete_observed'
            path=self.attempt/'fresh-INFO-HTTP.raw'
            with path.open('xb')as output:output.write(raw)
            body_record=C.row(path);body_kind='complete_saved'
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request=urllib.request.Request(self.base+'/metrics',headers={'Accept':'application/json'})
            try:response=opener.open(request,timeout=305)
            except urllib.error.HTTPError as failure:
                status=failure.code
                try:
                    try:raw=failure.read()
                    except BaseException as read_error:
                        partial_body(read_error,failure)
                        failure.add_note('public INFO HTTP error body read failed: '+repr(read_error))
                    else:
                        try:complete_body(raw)
                        except BaseException as save_error:failure.add_note('public INFO HTTP error body save failed: '+repr(save_error))
                finally:
                    try:failure.close()
                    except BaseException as close_error:failure.add_note('public INFO HTTP error close failed: '+repr(close_error))
                raise
            try:
                status=response.status
                try:raw=response.read()
                except BaseException as failure:
                    partial_body(failure,failure);raise
                complete_body(raw)
            finally:
                pending=sys.exception()
                try:response.close()
                except BaseException as close_error:
                    if pending is None:raise
                    pending.add_note('public INFO HTTP response close failed: '+repr(close_error))
            C.require(status==200,'public INFO HTTP status')
            metrics=json.loads(raw);receipt=C.load(self.attempt/'fresh-INFO-receipt.json')
            C.require(receipt['ok']is True and receipt['error']is None,'public INFO receipt failed')
            parsed=receipt['parsed'];C.require(type(parsed)is dict,'public native INFO object')
            C.require(all(metrics['engine'].get(k)==v for k,v in parsed.items()),'fresh native INFO vs decorated metrics')
            return copy.deepcopy(parsed)
        except BaseException as failure:
            error=dict(type=type(failure).__name__,message=str(failure));raise
        finally:
            pending=sys.exception()
            try:C.save(self.attempt/'fresh-INFO-HTTP.json',dict(method='GET',path='/metrics',HTTP_status=status,
                       start_ns=started,end_ns=time.monotonic_ns(),error=error,trial_only_timeout_seconds=305,body_kind=body_kind,body_record=body_record,body_read_error=body_read_error,partial_type=partial_type))
            except BaseException as save_error:
                if pending is None:raise
                pending.add_note('public INFO HTTP receipt save failed: '+repr(save_error))

    def bind_public_owner(self):
        # A real observer header is checked against the already observed CLI
        # cohort before the first control request, and again after normal close.
        rows=Path(self.spec['output']).read_text(encoding='utf8').splitlines()
        C.require(rows,'public observer header missing')
        header=json.loads(rows[0]);owner=header.get('owner')
        C.require(header.get('schema')=='strata-t46-observer/v1'and header.get('event')=='header'and type(header.get('sequence'))is int and header.get('sequence')==0 and type(header.get('monotonic_ns'))is int and header.get('monotonic_ns')>=0 and header.get('run_id')==self.spec['run_id'],'public observer header structure')
        for key,value in [('hook_sha256',C.HOOK),('runtime_epoch',self.cfg['runtime_epoch']),('package_id',C.ID),('bundle_id',C.BUNDLE),('mode',self.mode)]:
            C.require(header.get(key)==value,'public observer header '+key)
        C.require(type(owner)is dict and set(owner)=={'server','engine'},'public observer owner structure')
        natives=[p for p in self.cohort if Path(p['exe']).resolve()==Path(self.cfg['exe']).resolve()]
        C.require(len(natives)==1,'one verified public native')
        native=natives[0]
        C.require(owner['engine']==dict(pid=native['pid'],birth=native['birth']),'header engine/verified cohort')
        C.require(any(owner['server']==dict(pid=p['pid'],birth=p['birth'])for p in self.cohort if p['pid']!=native['pid']),'header server/verified cohort')
        bound=dict(owner=owner,hook_sha256=C.HOOK,runtime_epoch=self.cfg['runtime_epoch'])
        if 'owner'in self.binding:C.require(self.binding==bound,'public owner changed after binding')
        self.binding=bound
        return bound

def run_stage(transport,qualify,return_only=False):
    """The actual orchestrator, also used by finite CPU fault fixtures."""
    failure=None;cleanup=None;result=None
    try:
        transport.start()
        if return_only:transport.return_observe()
        else:transport.capture()
    except BaseException as e:failure=e
    finally:
        try:cleanup=transport.cleanup()
        except BaseException as e:
            if failure is None:failure=e
            else:failure.add_note('Separate cleanup exception: '+repr(e))
    if failure is not None:raise failure
    C.require(cleanup is not None and cleanup['ok']is True,'failed cleanup')
    if not return_only:result=qualify(transport)
    return result

def execute(args):
    seal=C.load(args.seal);C.bind_candidate(seal['candidate_input']['path'],seal['candidate_proof']['path']);C.checked(seal['records'])
    C.require(C.protected_sources(C.load(C.PROFILE))==seal['original_Model9'],'Model9 original before')
    # This is the existing independent review boundary; no additional human GO.
    review=C.load(args.review);C.require(review['important_unresolved']==0 and review['independent']is True and review['preseal']==C.row(args.seal),'latest exact runner/observer review required')
    mode=args.mode;previous=[]
    for path in args.previous:
        value=C.load(path);value['record']=C.row(path);previous.append(value)
    numeric=C.load(args.accepted_numeric)if args.accepted_numeric else None
    publication=C.load(args.publication)if args.publication else None
    if args.return_only:
        C.require(mode=='single'and [v['mode']for v in previous]==list(C.MODES),'restore only after four completed modes')
        C.verify_prior_records(previous)
        C.stage_receipts('layer-split',previous[:3],numeric,publication)
        C.require(all(v.get('actual_model')is True and v.get('CPU_fixture')is False and v['package_id']==C.ID and v['bundle_id']==C.BUNDLE for v in previous),'restore requires actual exact four-mode evidence')
        C.require(len({v['config_total_RAM']for v in previous})==1,'restore same explicit RAM')
        total=previous[0]['config_total_RAM']
    else:
        stage=C.stage_receipts(mode,previous,numeric,publication);total=previous[0]['config_total_RAM']if previous else None
    attempt=Path(args.attempt).resolve();C.require(attempt.is_relative_to(C.HERE),'ignored attempt only');attempt.mkdir(exist_ok=False)
    transport=ActualTransport(attempt,mode,total,args.return_only);C.save(attempt/'preseal.json',C.row(args.seal))
    before_model=C.protected_sources(C.load(C.PROFILE));C.save(attempt/'model9-before.json',before_model)
    # Preserve Huihui/default/catalog/bootstrap and all non-published profiles.
    allowed={str(Path(p['destination']).resolve())for p in C.load(C.CANDIDATE_PROOF)['profiles']}
    protected=[r for r in seal['protected_profiles']if str(Path(r['path']).resolve())not in allowed]
    protected += [C.row(C.DATA/'model_catalog.py'),C.row(C.DATA/'profile_defaults.py'),seal['public_helper_before'][2]]
    C.checked(protected);C.save(attempt/'protected-before.json',protected)
    original=None
    try:
        if mode=='single'and not args.return_only:total=transport.calibrate()
        def qualify(t):
            value=C.qualify(attempt,t.cfg,t.binding,t.codec,t.prepared,t.tokenizer,stage['single_baseline'])
            return value
        result=run_stage(transport,qualify,args.return_only)
    except BaseException as e:
        original=e
        try:C.save(attempt/'failure.json',dict(type=type(e).__name__,error=str(e),traceback=traceback.format_exc()))
        except BaseException:pass
    finally:
        # Publication intentionally changes eight files between stages; the
        # immutable consumed source and original nine sources must never drift.
        C.checked(seal['records']);C.require(C.protected_sources(C.load(C.PROFILE))==seal['original_Model9'],'Model9 after')
        C.checked(protected);C.save(attempt/'protected-after.json',protected);C.save(attempt/'model9-after.json',C.protected_sources(C.load(C.PROFILE)))
    if original is not None:raise original
    if result is not None:
        C.require(all(result['owner']['engine']!=x['owner']['engine']for x in previous),'fresh native owner per mode')
        C.require(all(result['raw']['context']['runtime_epoch']!=x['raw']['context']['runtime_epoch']for x in previous),'distinct actual runtime epochs')
        numeric_record=C.final_single_numeric(attempt,args.seal)if mode=='single'else previous[0]['numeric_record']
        C.save(attempt/'stage-receipt.json',dict(result,config_total_RAM=total,numeric_record=numeric_record,verification=C.row(attempt/'verification.json'),entry='candidate prepared Service/HTTP'if mode=='single'else'usual CLI mode-only'))
    else:C.save(attempt/'stage-receipt.json',dict(schema='strata-t46-public-single-return/v1',GEN_count=0,cleanup=C.row(attempt/'cleanup.json'),package_id=C.ID,actual_model=True))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('seal');s.add_argument('destination');s.add_argument('--input',required=True);s.add_argument('--candidate-proof',required=True);s.add_argument('--evidence',action='append',default=[])
    x=sub.add_parser('execute');x.add_argument('--seal',required=True);x.add_argument('--review',required=True);x.add_argument('--attempt',required=True);x.add_argument('--mode',choices=C.MODES,required=True);x.add_argument('--previous',action='append',default=[]);x.add_argument('--accepted-numeric');x.add_argument('--publication');x.add_argument('--return-only',action='store_true')
    args=p.parse_args()
    if args.command=='seal':C.bind_candidate(args.input,args.candidate_proof);print(json.dumps(C.seal(args.destination,args.evidence)))
    else:execute(args)
