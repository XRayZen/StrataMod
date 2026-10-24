"""Private, single-use entry to the unchanged official calibration algorithm.

Preparation does not start processes. Only the exact approved selection can run;
all native trials share the existing production exclusion and cleanup interlock.
"""
import argparse
import copy
from decimal import Decimal, InvalidOperation
import json
import math
import os
import re
from pathlib import Path
import threading
import time

from . import manifest as m
from . import evaluate_r9700 as runner
from . import official_runtime as official
from . import runtime_safety as safety
from . import checked_job, gpu_observation
from .standalone_phase import native_exit_proof
from tools import calibrate as cal

SELECTION = m.LOCAL/'calibration-selected.json'
APPROVAL = 'STRATAMOD_CALIBRATION_SELECTION_SHA256'
LIMITS = dict(starts=11,calls=213,tokens=34176,seconds=7200,start_seconds=900,call_seconds=600)


class CalibrationAbort(BaseException):
    """Must escape CAL.restart's ordinary candidate-rejection handler."""


def save(path,value):
    m.local_path(Path(path)).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def sources():
    value=m.source_files()
    for name in ('START-HERE.bat','tools/calibrate.py','tools/test_calibrate_lifecycle.py',
                 'local_runtime/tests/test_official_calibration.py'):
        path=m.ROOT/name
        value[str(path)]=m.digest(path)
    return value


def dependency_paths(cfg):
    """Bound the actual fixed model files, rather than trusting old size receipts."""
    paths=list(m.dependency_paths(cfg,'baseline'))
    native=Path(cal.arg_value(cfg['args'],'--native'))
    ple=Path(cal.arg_value(cfg['args'],'--ple-gguf'))
    match=re.fullmatch(r'(.+)-00001-of-00003\.gguf',native.name)
    if match is None:raise RuntimeError('Expected fixed three-shard Huihui native model')
    shards=[native.with_name(f'{match[1]}-{index:05d}-of-00003.gguf') for index in range(1,4)]
    if ple not in shards:raise RuntimeError('PLE GGUF is outside the fixed native closure')
    pack=Path(cal.arg_value(cfg['args'],'--pack'))
    paths.extend(shards)
    paths.extend(pack/name for name in ('dense.bin','index.txt','native_experts.txt',
        'tokenizer/vocab.json','tokenizer/merges.txt','tokenizer/tokenizer.json',
        'tokenizer/chat_template.jinja','tokenizer/token_type.json'))
    return list(dict.fromkeys(paths))


def validate_trial(base,args,env):
    def strip(values):
        values=list(values)
        found={}
        for flag in cal.DEFAULTS:
            if values.count(flag)>1:raise RuntimeError('Duplicate calibration option')
            if flag in values:
                index=values.index(flag)
                if index+1==len(values):raise RuntimeError('Missing option value')
                found[flag]=values[index+1]
                del values[index:index+2]
        return values,found
    fixed,_=strip(base)
    other,tune=strip(args)
    if fixed!=other or args.count('--max-context')!=1 or cal.arg_value(args,'--max-context')!='262144':
        raise RuntimeError('Calibration changed fixed native arguments/context')
    for flag,choices in (('--pcie-frac',{0.0,0.1,0.2,0.35,0.55,0.75,0.9,1.0}),
                         ('--spec-min-p',{0.3,0.5,0.7})):
        if flag in tune:
            try:valid=float(tune[flag]) in choices
            except (ValueError,TypeError):valid=False
            if not valid:raise RuntimeError('Not an official numeric calibration candidate')
    choices={'--pool-workers':{None,'13','9','6','3','5'},'--prefill-pipe':{None}}
    if any(tune.get(flag) not in values for flag,values in choices.items()):
        raise RuntimeError('Not an official single-GPU calibration candidate')
    adaptive=tuple(tune.get(flag) for flag in cal.ADAPT_FLAGS)
    if adaptive not in ((None,None,None),('1','80','0.97'),('1','160','0.97')):
        raise RuntimeError('Not an official adaptive tier candidate')
    if set(env)-{cal.SH_STREAM} or any(value not in ('0','1') for value in env.values()):
        raise RuntimeError('Unapproved calibration environment')


def prepare():
    directory=m.LOCAL/'calibration-runs'/time.strftime('%Y%m%dT%H%M%S')
    directory.mkdir(parents=True,exist_ok=False)
    cfg=m.expected_config('baseline',directory,m.original_assets())
    save(directory/'config.json',cfg)
    paths=dependency_paths(cfg)
    value=dict(version=1,kind='official-calibration',created=time.time(),expires=time.time()+86400,
               directory=str(directory),config=cfg,limits=LIMITS,
               source=sources(),dependencies={str(path):m.digest(path) for path in dict.fromkeys(paths)},
               environment=m.normalized_environment(cfg,os.environ))
    save(directory/'manifest.json',value)
    save(SELECTION,dict(manifest=str(directory/'manifest.json'),sha256=m.digest(directory/'manifest.json')))
    print(json.dumps(dict(selection=str(SELECTION),selection_sha256=m.digest(SELECTION)),indent=2))


def selected_manifest(approved):
    approved=approved or os.environ.get(APPROVAL)
    if not approved or m.digest(SELECTION)!=approved:
        raise RuntimeError('Independent exact selection SHA256 approval is required; zero spawn')
    pointer=m.read_json(SELECTION)
    path=m.local_path(Path(pointer['manifest']))
    if m.digest(path)!=pointer['sha256']:raise RuntimeError('Selected manifest changed')
    value=m.read_json(path)
    directory=m.local_path(Path(value['directory']))
    if path!=directory/'manifest.json' or value.get('kind')!='official-calibration' or value.get('version')!=1:
        raise RuntimeError('Wrong private calibration manifest')
    if value['limits']!=LIMITS or not time.time()<value['expires']<=value['created']+86400:
        raise RuntimeError('Calibration limits/expiry changed')
    expected=m.expected_config('baseline',directory,m.original_assets())
    if value['config']!=expected or value['source']!=sources():raise RuntimeError('Calibration source/config changed')
    if value['environment']!=m.normalized_environment(expected,os.environ):raise RuntimeError('Environment changed')
    m.require_dependency_inventory(dependency_paths(expected),value['dependencies'])
    return value


class EngineObserver(official.SpawnObserver):
    """Only this exact native command; never impersonate a manager/server root."""
    def __init__(self,process,config,command):
        super().__init__(process,config)
        self.command=list(command)

    def capture(self):
        import psutil
        try:
            parent=psutil.Process(self.process.pid)
            if parent.cmdline()!=self.command:raise RuntimeError('Calibration native command changed')
            root=safety.captured_identity(parent)
        except psutil.NoSuchProcess:
            if self.process.poll() is not None and self.snapshot().get('created') is not None:return
            raise
        self.merge(identities=[root],created=root['created'])
        unknown,errors=[],[]
        try:
            children=safety.descendants(parent,self.config,strict=False,unrecognized=unknown,errors=errors)
            for child in children:self.merge(identities=[safety.captured_identity(child)])
        finally:
            self.merge(unknown=[dict(pid=p.pid) for p in unknown],errors=errors)

    def _run(self):
        while not self.done.wait(.25):
            if self.process.poll() is not None:return
            try:self.capture()
            except BaseException as error:
                self.merge(errors=[dict(action='observe',error_type=type(error).__name__)])
                return


class Trial:
    def __init__(self,engine,controller):self.engine,self.controller=engine,controller
    def __getattr__(self,key):return getattr(self.engine,key)
    def generate(self,ids,max_new,sampling,cancel):
        owner=self.controller
        owner.begin_call(max_new)
        count=0
        try:
            for token in self.engine.generate(ids,max_new,sampling,cancel):
                owner.check(self.engine)
                if token is not None:
                    count+=1
                    owner.tokens+=1
                    if count>max_new or owner.tokens>LIMITS['tokens']:owner.failed(self.engine,RuntimeError('Token cap'))
                yield token
            ms=(self.engine.last or {}).get('decode_ms',0)
            if count<=8 or not isinstance(ms,(int,float)) or not math.isfinite(ms) or ms<=0:
                owner.failed(self.engine,RuntimeError('Invalid native decode measurement'))
            owner.result['requests'].append(dict(call=owner.calls,tokens=count,decode_ms=ms))
            owner.persist()
        except BaseException as error:
            owner.failed(self.engine,error)
        finally:owner.call_deadline=None


class Controller:
    def __init__(self,value,monitor):
        self.value,self.monitor=value,monitor
        self.directory=Path(value['directory'])
        self.cfg=value['config']
        self.base=cal.engine_args(self.cfg)
        self.retained={}
        self.deadline=time.monotonic()+LIMITS['seconds']
        self.calls=self.tokens=self.starts=0
        self.aborted=False
        self.call_deadline=None
        self.current=None
        self.result=dict(status='running',requests=[],sessions=[],limits=LIMITS)

    def persist(self):
        self.result.update(calls=self.calls,tokens=self.tokens,physical_spawns=self.starts)
        save(self.directory/'result.json',self.result)

    def check(self,engine=None):
        try:
            if self.aborted:raise RuntimeError('Calibration already aborted')
            self.monitor.check()
            if self.retained.get('cancel_requested'):raise KeyboardInterrupt('Calibration cancel')
            deadline=min(self.deadline,getattr(self,'startup_deadline',self.deadline))
            if getattr(self,'call_deadline',None) is not None:deadline=min(deadline,self.call_deadline)
            if time.monotonic()>=deadline:raise RuntimeError('Calibration deadline')
            observer=self.retained.get('observer')
            if observer and any(observer.snapshot().get(key) for key in ('errors','unknown')):
                raise RuntimeError('Native cohort observation incomplete')
        except BaseException as error:self.failed(engine,error)

    def begin_call(self,max_new):
        if max_new not in (128,512) or self.calls>=LIMITS['calls']:
            self.failed(None,RuntimeError('Calibration call cap'))
        self.check()
        self.calls+=1
        self.call_deadline=time.monotonic()+LIMITS['call_seconds']

    def failed(self,engine,error):
        self.aborted=True
        if hasattr(self,'result'):
            self.result.setdefault('error',dict(type=type(error).__name__,message=str(error)))
            self.result['status']='failed'
            if engine is not None:
                self.result['partial']=dict(log=getattr(engine,'log_path',None),
                    last=getattr(engine,'last',None),progress=getattr(engine,'progress',None))
            self.persist()
        raise CalibrationAbort(str(error)) from error

    def before_spawn(self,engine):
        self.check()
        if self.retained.get('spawn_possible'):raise CalibrationAbort('Previous cohort has not been reclaimed')
        if self.starts>=LIMITS['starts']:raise CalibrationAbort('Physical spawn cap')
        if selected_manifest(self.approved)!=self.value:raise CalibrationAbort('Approval changed before native spawn')
        checked_job.ensure_parent_job()
        self.current=engine
        pending=dict(config=str(self.trial_config),phase='calibration-starting',cleanup_pending=True,
                     birth_pending=True,spawn_possible=True,owned_identities=[])
        safety.save(pending)  # Durable uncertainty before Popen; a failed write permits zero spawn.
        self.starts+=1
        self.retained.update(spawn_possible=True,state=pending)
        self.persist()

    def spawned(self,engine):
        self.retained['process']=engine.proc
        observer=EngineObserver(engine.proc,self.trial_config,[self.cfg['exe'],'--serve',*self.trial_args])
        self.retained['observer']=observer
        observer.begin()
        checked_job.require_child(engine.proc)
        snapshot=observer.snapshot()
        self.retained['state'].update(pid=engine.proc.pid,created=snapshot['created'],
            exe=self.cfg['exe'],birth_pending=False,spawn_observation=snapshot,owned_identities=snapshot['identities'])
        safety.save(self.retained['state'])

    def ready(self,engine):
        info=dict(engine.info)
        diagnostic=dict(physical_spawn=self.starts,raw_info=info,
                        raw_types={key:type(value).__name__ for key,value in info.items()},normalized={})
        self.result.setdefault('native_info',[]).append(diagnostic)
        self.persist()  # Preserve parser-output values/types even if validation rejects them.
        decimals={}
        for key in ('pcie_frac','spec_min_p'):
            value=info.get(key)
            if type(value) not in (str,int,float):raise RuntimeError('Invalid native INFO number: '+key)
            text=str(value)
            if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',text):
                raise RuntimeError('Invalid native INFO number: '+key)
            try:number=Decimal(text)
            except InvalidOperation:raise RuntimeError('Invalid native INFO number: '+key) from None
            if not number.is_finite() or not math.isfinite(float(number)):
                raise RuntimeError('Nonfinite native INFO number: '+key)
            decimals[key]=number
        if engine.max_context!=262144:raise RuntimeError('Native READY context differs')
        if self.starts==1:
            if engine.info.get('pool_workers')!=13:raise RuntimeError('Official candidate bounds need INFO pool_workers=13')
            if decimals['pcie_frac'] not in (Decimal('0.1'),Decimal('0.2')) or decimals['spec_min_p']!=Decimal('0.5'):
                raise RuntimeError('Official candidate bounds differ from prepared INFO assumptions')
        diagnostic['normalized']={key:float(value) for key,value in decimals.items()}
        self.persist()
        snapshot=self.retained['observer'].snapshot()
        root=next(row for row in snapshot['identities'] if row['pid']==engine.proc.pid)
        self.monitor.engine=root
        modules=gpu_observation.loaded_modules(root,self.value['dependencies'])
        observation=dict(build=m.read_json(m.ORIGINAL/'engine/BUILD.json'),modules=modules,
                         windows_displays=gpu_observation.windows_displays())
        m.require_loader_binding(observation,self.value['dependencies'])
        cards=[row for row in observation['windows_displays'] if 'R9700' in row.get('Name','')
               and 'VEN_1002&DEV_7551' in row.get('PNPDeviceID','').upper() and row.get('pci')]
        if len(cards)!=1:raise RuntimeError('Unique Windows R9700 PCI identity absent')
        log=Path(engine.log_path).read_text(encoding='utf-8',errors='replace')
        if 'gfx1201' not in log or 'R9700' not in log:raise RuntimeError('R9700 gfx1201 startup identity absent')
        self.result['sessions'].append(dict(args=self.trial_args,env=self.trial_env,info=engine.info,loader=observation))
        self.startup_deadline=self.deadline
        self.persist()

    def start(self,args,env=None):
        from serve.server import StrataEngine
        try:
            validate_trial(self.base,args,env or {})
            self.trial_args,self.trial_env=list(args),dict(env or {})
            trial=self.directory/f'trial-{self.starts+1:02d}'
            trial.mkdir(exist_ok=False)
            cfg=copy.deepcopy(self.cfg)
            cfg.update(args=list(args),env=dict(env or {}),log=str(trial/'engine.log'))
            self.trial_config=trial/'config.json'
            save(self.trial_config,cfg)
            environment=official.clean_environment(self.cfg,os.environ,self.value['environment'])
            environment.update(env or {})
            environment['HIP_VISIBLE_DEVICES']='1'
            environment['PATH']=os.pathsep.join([*cfg['lib_dirs'],environment['PATH']])
            for key in ('APPDATA','LOCALAPPDATA'):
                private=self.directory/key.lower()
                private.mkdir(exist_ok=True)
                environment[key]=str(private)
            self.startup_deadline=min(self.deadline,time.monotonic()+LIMITS['start_seconds'])
            engine=StrataEngine(cfg['exe'],args,cwd=cfg['cwd'],log=cfg['log'],env=environment,
                                lifecycle=self,startup_retries=0)
            return Trial(engine,self)
        except BaseException as error:self.failed(self.current,error)

    def close(self,engine):
        engine=getattr(engine,'engine',engine)
        process=self.retained.get('process')
        if not self.retained.get('spawn_possible'):return
        self.monitor.expect_engine_exit()
        error=None
        try:
            if process is None:raise RuntimeError('Original Popen unavailable after possible spawn')
            if process.poll() is None:
                observer=self.retained.get('observer')
                if observer:observer.capture()
                process.stdin.write('QUIT\n')
                process.stdin.flush()
                process.stdin.close()
                process.wait(60)
            if process.returncode!=0:raise RuntimeError('Native engine exited unsuccessfully')
            if self.retained.get('observer'):
                snapshot=self.retained['observer'].finish_standalone()
                self.retained['state'].update(spawn_observation=snapshot,owned_identities=snapshot['identities'])
            # Same bounded normal-exit reconciliation as finish_encoder. A delay
            # never grants authority: every pass independently checks saved births.
            deadline=time.monotonic()+15
            while True:
                proof=native_exit_proof(self.retained)
                if proof['complete']:break
                if time.monotonic()>=deadline:raise RuntimeError('Native cohort cleanup incomplete')
                time.sleep(.1)
        except BaseException as failure:
            error=failure
            self.aborted=True
            self.result.update(status='failed',cleanup_error=str(failure))
            runner.hold_pending_cleanup(self.retained,self.result,self.directory)
        self.retained['spawn_possible']=False
        self.retained['state'].update(phase='stopped',cleanup_pending=False)
        safety.save(self.retained['state'])
        if engine is not None and getattr(engine,'log',None) is not None:
            engine.log.close()
        self.retained.pop('process',None)
        self.retained.pop('observer',None)
        self.current=None
        self.persist()
        if error:raise CalibrationAbort(str(error)) from error


def run(approved=None):
    value=selected_manifest(approved)
    directory=Path(value['directory'])
    with runner.shared_operation():
        # Selection/source/expiry can change while waiting for the shared locks.
        if selected_manifest(approved)!=value:raise RuntimeError('Approval changed while waiting for locks')
        runner.production_inactive()
        # Full dependency SHA exactly once after both existing exclusion locks.
        m.verify_dependencies(dependency_paths(value['config']),value['dependencies'])
        if selected_manifest(approved)!=value:raise RuntimeError('Approval changed during dependency verification')
        with (directory/'run.claim').open('x',encoding='utf-8') as claim:claim.write(str(time.time()))
        checked_job.ensure_parent_job()
        with runner.MemoryMonitor(directory/'memory.jsonl') as monitor:
            owner=Controller(value,monitor)
            owner.approved=approved
            monitor.cancel_requested=lambda:owner.retained.get('cancel_requested',False)
            owner.result['forecast_advisory']=runner.preflight_budget()
            with runner.candidate_interrupts(owner.retained):
                try:
                    with (directory/'console.txt').open('x',encoding='utf-8') as console:
                        def say(message):
                            print(message,flush=True)
                            console.write(str(message)+'\n')
                            console.flush()
                        outcome=cal.run(owner.cfg,say=say,start_engine=owner.start,close_engine=owner.close)
                    if owner.aborted:raise CalibrationAbort('Earlier calibration failure')
                    updated=copy.deepcopy(owner.cfg)
                    updated['args']=cal.apply(updated['args'],outcome['settings'])
                    updated['env']=cal.apply_env(updated.get('env'),outcome.get('env'))
                    validate_trial(owner.base,cal.engine_args(updated),updated['env'])
                    save(directory/'calibration.json',outcome)
                    save(directory/'settings.json',dict(calibration=outcome))
                    save(directory/'config-calibrated.json',updated)
                    owner.result.update(status='passed',calibration=outcome)
                except BaseException as error:
                    owner.result['status']='failed'
                    owner.result.setdefault('error',dict(type=type(error).__name__,message=str(error)))
                    raise
                finally:
                    try:owner.close(owner.current)
                    finally:owner.persist()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--no-start',action='store_true')
    parser.add_argument('--selection-sha256')
    args=parser.parse_args()
    if args.prepare:
        if args.calibrate or args.no_start:parser.error('prepare is a separate command')
        prepare()
    else:
        if not args.calibrate or not args.no_start:parser.error('Only --calibrate --no-start is supported')
        run(args.selection_sha256)


if __name__=='__main__':main()
