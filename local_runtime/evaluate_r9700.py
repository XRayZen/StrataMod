"""Prepare or run one bounded candidate; hold production locks through cleanup."""
import argparse
import contextlib
import ctypes
import http.client
import json
import msvcrt
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import psutil

from . import manifest,official_runtime,benchmark
from . import runtime_safety as safety

GIB = 2**30


@contextlib.contextmanager
def shared_operation(*,data=manifest.DATA):
    # Same order and byte as the old CLI: operation, then runtime state. Never
    # create, truncate or write an old file; missing files fail closed.
    with contextlib.ExitStack() as stack:
        for name in ('cli-operation.lock','runtime.lock'):
            stream = stack.enter_context((data/'records'/name).open('r+b'))
            if stream.seek(0,2) < 1:
                raise RuntimeError('Existing production lock is empty')
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                raise RuntimeError('Another production/candidate operation holds the shared lock') from None
            def release(stream=stream):
                stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            stack.callback(release)
        yield


@contextlib.contextmanager
def candidate_interrupts(retained):
    """Ctrl+C is synchronous after spawn, including inside failure handlers."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Candidate lifecycle requires the foreground main thread')
    previous = {}
    def interrupt(signum,frame):
        if retained.get('spawn_possible'):
            retained['cancel_requested'] = True
            retained.setdefault('deferred_signals',[]).append(signum)
            return
        handler = previous[signum]
        if callable(handler):
            handler(signum,frame)
        elif handler != signal.SIG_IGN:
            raise KeyboardInterrupt()
    try:
        for signum in (signal.SIGINT,*((signal.SIGBREAK,) if hasattr(signal,'SIGBREAK') else ())):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum,interrupt)
        yield
    finally:
        for signum,handler in previous.items():
            signal.signal(signum,handler)


def production_inactive():
    if str(manifest.DATA) not in sys.path:
        sys.path.insert(0,str(manifest.DATA))
    import manage_runtime as production
    if production.runtime_active(production.read_state()):
        raise RuntimeError('Production runtime is active; candidate start refused')
    require_candidate_inactive()
    production.check_port_available()


def require_candidate_inactive():
    state = safety.read_state()
    if state.get('cleanup_pending'):
        raise RuntimeError('Prior candidate cleanup is pending; no new start is permitted')
    if safety.runtime_active(state):
        raise RuntimeError('A prior candidate still owns processes; preserve it for normal cleanup')


def memory_sample():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[
            (name,ctypes.c_ulonglong) for name in ('total_phys','avail_phys','total_page','avail_page',
                                                  'total_virtual','avail_virtual','avail_extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    disk = psutil.disk_io_counters()
    return dict(at=time.time(),available_bytes=status.avail_phys,commit_margin_bytes=status.avail_page,
                commit_limit_bytes=status.total_page,disk_read_bytes=disk.read_bytes,
                disk_write_bytes=disk.write_bytes)


class MemoryMonitor:
    def __init__(self,path):
        self.path = Path(path)
        self.done,self.abort = threading.Event(),threading.Event()
        self.reason,self.low = '',0
        self.thread = None
        self.engine = None
        self.images = []
        self.cancel_requested = lambda:False

    def observe(self,row):
        if row['commit_margin_bytes'] < 2*GIB:
            self.reason = 'commit margin below 2 GiB'
            self.abort.set()
        low = row['available_bytes'] < 4*GIB or row['commit_margin_bytes'] < 8*GIB
        self.low = self.low+1 if low else 0
        if self.low >= 3:
            self.reason = 'three samples below available/commit floor'
            self.abort.set()

    def check(self):
        if self.cancel_requested():
            raise KeyboardInterrupt('Candidate cancel requested')
        if self.abort.is_set():
            raise RuntimeError('Memory guard: '+self.reason)
        self.engine_process()
        for image in list(self.images):
            if safety.process_identity_status(image).status != 'verified':
                self.reason = 'exact image encoder identity lost/changed/unverifiable'
                self.abort.set()
                raise RuntimeError(self.reason)

    def engine_process(self,row=None):
        engine = self.engine
        if engine is None:
            return None
        identity = safety.process_identity_status(engine)
        # Normal stop clears this watch immediately before the authorized unload.
        if engine is not self.engine:
            return None
        if row is not None:
            row['engine_identity_status'] = identity.status
        if identity.status != 'verified':
            self.reason = 'exact engine identity lost/changed/unverifiable: '+identity.status
            self.abort.set()
            raise RuntimeError(self.reason)
        return identity.process

    def expect_engine_exit(self):
        self.engine = None
        self.images = []

    def _run(self):
        with self.stream as stream:
            while not self.done.is_set():
                try:
                    row = memory_sample()
                    process = self.engine_process(row)
                    for image in list(self.images):
                        if safety.process_identity_status(image).status != 'verified':
                            raise RuntimeError('Image encoder identity lost during collection')
                    if process is not None:
                        info = process.memory_info()
                        row['engine_memory'] = dict(rss_bytes=info.rss,private_bytes=info.private,
                                                    page_faults=info.num_page_faults)
                    self.observe(row)
                    stream.write(json.dumps(row)+'\n')
                    stream.flush()
                except Exception as error:
                    if not self.abort.is_set():
                        self.reason = 'collector failure: '+type(error).__name__
                    self.abort.set()
                    return
                self.done.wait(1)

    def __enter__(self):
        self.stream = self.path.open('x',encoding='utf-8')
        self.thread = threading.Thread(target=self._run,daemon=True)
        self.thread.start()
        return self

    def __exit__(self,*args):
        self.done.set()
        self.thread.join(3)
        if self.thread.is_alive():
            raise RuntimeError('Memory collector did not stop')


def preflight_budget(*,suite='smoke'):
    row = memory_sample()
    budget = manifest.memory_budget(suite)
    physical = sum(budget[key] for key in ('resident_gib','nonresident_physical_gib','uncertainty_gib','available_floor_gib'))
    commit = sum(budget[key] for key in ('resident_gib','nonresident_commit_gib','uncertainty_gib','commit_floor_gib'))
    fits=row['available_bytes'] >= physical*GIB and row['commit_margin_bytes'] >= commit*GIB
    prediction=('probe-only 8-GiB SDK/driver/runner estimate +9-GiB uncertainty; no model load, peak unmeasured, not a hard upper bound'
                if suite=='vision-probe' else
                'historical peak minus pinned resident +16-GiB cap; 8-GiB historical uncertainty +1-GiB async allowance; new peak unmeasured')
    return dict(**row,**budget,required_available_gib=physical,required_commit_gib=commit,prediction=prediction,
                predicted_fits=fits,startup_prediction_advisory=True)


def ready(state):
    official_runtime.require_tracking(state)
    safety.require_owned_listener(state)
    health,models = safety.get_json('/health'),safety.get_json('/v1/models')
    if not (health.get('service') == 'strata' and health.get('status') == 'ok'
            and health.get('loaded') is True and health.get('model') == manifest.MODEL
            and health.get('max_context') == manifest.CONTEXT):
        raise RuntimeError('Candidate health/model/context mismatch')
    matched = [row for row in models.get('data',[]) if row.get('id') == manifest.MODEL
               and row.get('status',{}).get('value') == 'loaded'
               and row.get('meta',{}).get('n_ctx') == manifest.CONTEXT]
    if len(matched) != 1:
        raise RuntimeError('Candidate model list mismatch')
    return health,models


def start_session(path,approved,monitor,*,retained=None,_image=False):
    value = manifest._verify_authority(path,approved) if _image else manifest.verify(path,approved)
    cfg = manifest.read_json(value['config'])
    process,observer,tracking,result = None,None,{},None
    observation = dict(identities=[],unknown=[],errors=[])
    retained = retained if retained is not None else {}
    started = time.monotonic()
    try:
        try:
            if _image:
                def before_spawn():
                    monitor.check();retained['memory_before_spawn']=preflight_budget(suite=value['suite'])
                process,observer,tracking,result = official_runtime.start_candidate(path,approved,retained=retained,_image=True,before_spawn=before_spawn)
            else:
                process,observer,tracking,result = official_runtime.start_candidate(path,approved,retained=retained)
        except official_runtime.LaunchFailure as error:
            process,observer,tracking = error.process,error.watcher,error.tracking
            raise
        observation = observer.snapshot()
        if 'created' not in observation:
            raise RuntimeError('Candidate spawn identity unavailable')
        state = dict(pid=process.pid,created=observation['created'],exe=observation['identities'][0]['exe'],
                     config=value['config'],model=manifest.MODEL,context=manifest.CONTEXT,
                     manifest=str(path),manifest_sha256=approved,phase='loading',
                     runtime_provider='official_mcp',official_tracking=tracking,
                     owned_identities=observation['identities'],spawn_observation=observation,
                     log=str(Path(value['config']).parent/'native/server.log'),engine_log=cfg['log'],cleanup_pending=True)
        retained.update(spawn_possible=True,process=process,observer=observer,state=state)
        safety.save(state)
        while True:
            monitor.check()
            observation = observer.snapshot()
            state.update(owned_identities=observation['identities'],spawn_observation=observation)
            safety.save(state)
            if observation['unknown'] or observation['errors']:
                raise RuntimeError('Candidate descendants could not be completely verified')
            if process.poll() is not None or not safety.owned(state):
                raise RuntimeError('Candidate server exited/changed before READY')
            if safety.require_owned_listener(state,allow_absent=True):
                try:
                    health,models = ready(state)
                except (TimeoutError,ConnectionError,urllib.error.URLError):
                    pass
                else:
                    observation = observer.finish()
                    observer = None
                    if observation['unknown'] or observation['errors']:
                        raise RuntimeError('Candidate final observation failed')
                    state.update(phase='ready',health=health,models=models,
                                 startup_seconds=time.monotonic()-started,
                                 owned_identities=observation['identities'],spawn_observation=observation)
                    safety.save(state)
                    return state
            time.sleep(.25)
    except BaseException as original_error:
        process = process if process is not None else retained.get('process')
        observer = observer if observer is not None else retained.get('observer')
        failed = dict(phase='failed',config=value['config'],manifest=str(path),
                      manifest_sha256=approved,cleanup_pending=True,
                      owned_identities=observation['identities'],spawn_observation=observation)
        retained.update(process=process,observer=observer,state=failed)
        if 'created' in observation:
            failed['created'] = observation['created']
        try:
            cleanup_failed_start(process,observer,failed)
        except BaseException as cleanup_error:
            original_error.add_note('Failed-start cleanup/persistence: '+type(cleanup_error).__name__)
        if failed['cleanup_pending']:
            original_error.add_note('Candidate cleanup remains pending; new starts are interlocked')
        raise


def pending_exit_proof(retained,*,require_port=True):
    """Read-only saved-birth/cohort proof; never resolve unknowns by killing."""
    state = retained.get('state',{})
    observation = state.get('spawn_observation',{})
    rows = state.setdefault('owned_identities',[])
    watcher = retained.get('observer')
    if watcher is not None:
        final = watcher.snapshot()
        for key in ('identities','unknown','errors'):
            for row in final.get(key,[]):
                if row not in observation.setdefault(key,[]):
                    observation[key].append(row)
        if 'created' in final:
            if 'created' in observation and observation['created'] != final['created']:
                observation['errors'].append(dict(action='retained_observer_birth_changed'))
            else:
                observation['created'] = final['created']
        state['spawn_observation'] = observation
        for row in observation['identities']:
            if row not in rows:
                rows.append(row)
    proof = dict(complete=False,members=[],unknown=list(observation.get('unknown',[])),
                 errors=list(observation.get('errors',[])))
    if 'created' not in observation or not rows:
        proof['incomplete_cohort'] = True
    # Preserve cleanup's independently collected evidence too, including when
    # its receipt write itself failed. Unknown/error evidence stays fail-closed.
    cleanup = state.get('cleanup_observation',{})
    proof['unknown'].extend(cleanup.get('unknown',[]))
    proof['errors'].extend(cleanup.get('errors',[]))
    for row in list(rows):
        identity = safety.process_identity_status(row)
        presence = safety.process_presence(row['pid'])
        proof['members'].append(dict(row,identity_status=identity.status,presence=presence))
        if identity.status == 'verified':
            unknown,errors = [],[]
            children = safety.descendants(identity.process,state['config'],strict=False,
                                          unrecognized=unknown,errors=errors)
            for child in children:
                captured = safety.captured_identity(child)
                if captured not in rows:
                    rows.append(captured)
            proof['unknown'].extend(dict(pid=child.pid) for child in unknown)
            proof['errors'].extend(errors)
    # Any newly discovered child must itself get independent proof next poll.
    proof['complete'] = (not proof.get('incomplete_cohort') and not proof['unknown'] and not proof['errors']
                         and len(proof['members']) == len(rows)
                         and all(row['identity_status'] == 'gone' and row['presence'] == 'gone'
                                 for row in proof['members']))
    if retained.get('reader') is not None and not retained['reader'].close_reader(.05):
        proof.update(complete=False,reader_cleanup_pending=True)
    if retained.get('auxiliary',{}).get('spawn_possible'):
        proof['auxiliary']=pending_exit_proof(retained['auxiliary'],require_port=False)
        state['webui_auxiliary']=retained['auxiliary'].get('state',{})
        proof['complete']=proof['complete'] and proof['auxiliary']['complete']
    if proof['complete'] and require_port:
        safety.check_port_available()
        proof['port_free'] = True
    for key in ('unknown','errors'):
        proof[key] = [row for index,row in enumerate(proof[key]) if row not in proof[key][:index]]
    state['cleanup_observation'] = dict(unknown=proof['unknown'],errors=proof['errors'])
    return proof


def hold_pending_cleanup(retained,result,directory):
    """Called INSIDE shared_operation; exceptions/cancel cannot release its locks."""
    with candidate_interrupts(retained):
        _hold_pending_cleanup(retained,result,directory)


def _hold_pending_cleanup(retained,result,directory):
    state = retained.setdefault('state',dict(phase='cleanup-pending',cleanup_pending=True))
    previous = None
    pause = False
    notified = False
    while True:
        step = 'wait'
        try:
            if pause:
                time.sleep(1)
            pause = True
            if not notified:
                print('Candidate cleanup pending; production locks remain held. Evidence: '+str(directory/'result.json'),
                      file=sys.stderr,flush=True)
                notified = True
            step = 'proof'
            proof = pending_exit_proof(retained)
            step = 'persist'
            state.update(phase='cleanup-pending',cleanup_pending=True,lock_hold_proof=proof)
            result['deferred_signals'] = list(retained.get('deferred_signals',[]))
            result['cleanup'] = dict(status='pending',lock_hold_proof=proof)
            if proof['complete']:
                state.update(phase='stopped',cleanup_pending=False)
                result['cleanup'] = dict(status='passed',after_failed_cleanup=True,lock_hold_proof=proof)
            # Persist before a possible release. A failed write keeps the locks.
            signature = json.dumps(dict(state=state,result=result),sort_keys=True)
            if signature != previous:
                safety.save(state)
                (directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                previous = signature
            if proof['complete']:
                return
        except BaseException as hold_error:
            state.update(phase='cleanup-pending',cleanup_pending=True)
            extra = dict(error_type=type(hold_error).__name__,reason=str(hold_error))
            if step == 'proof':
                errors = state.setdefault('cleanup_observation',{}).setdefault('errors',[])
                evidence = dict(action='incomplete_exit_proof',**extra)
                if evidence not in errors:
                    errors.append(evidence)
            if extra not in result.setdefault('lock_hold_errors',[]):
                result['lock_hold_errors'].append(extra)
            # Re-enter the protected loop even for repeated Ctrl+C/SystemExit.
            # No kill, pending-clear, or success return is available here.


def cleanup_failed_start(process,observer,failed):
    """An exact Popen can end its root; only a full cohort proof clears pending."""
    failed.update(phase='failed',cleanup_pending=True)
    if process is not None:
        failed['pid'] = process.pid
    observation = failed.get('spawn_observation',dict(identities=[],unknown=[],errors=[]))
    try:
        safety.save(failed)
        if observer is not None:
            try:
                observation = observer.finish_standalone() if failed.get('standalone') else observer.finish()
            except Exception as error:
                observation = observer.snapshot()
                observation = dict(observation,errors=[*observation.get('errors',[]),
                    dict(action='final_observation',error_type=type(error).__name__)])
        failed.update(owned_identities=observation['identities'],spawn_observation=observation)
        if 'created' in observation:
            failed['created'] = observation['created']
        if 'created' not in observation or not observation['identities'] or observation['unknown'] or observation['errors']:
            raise RuntimeError('Complete spawn birth/cohort proof is unavailable')
        safety.stop_owned(failed,official_first=False)
        safety.check_port_available()
        failed.update(cleanup_pending=False,cleanup_status='all captured cohort members and port proved gone')
    except BaseException as error:
        failed['cleanup_failure'] = dict(error_type=type(error).__name__,reason=str(error))
        if process is not None and process.poll() is None:
            try:
                process.terminate()  # Retained root handle only; pending stays true.
                process.wait(timeout=15)
            except BaseException as retained_error:
                failed['retained_root_cleanup_failure'] = type(retained_error).__name__
    finally:
        safety.save(failed)


def wait_request_release(state,timeout_s=30):
    """The disconnected request may still be unwinding; never terminate it busy."""
    if state.get('request_cleanup_pending'):
        raise RuntimeError('API reader cleanup is unconfirmed; preserve candidate pending')
    end = time.monotonic()+timeout_s
    while True:
        official_runtime.require_tracking(state)
        safety.require_owned_listener(state)
        status = safety.get_json('/status')
        if type(status.get('busy')) is not bool or type(status.get('queued')) is not int or status['queued'] < 0:
            raise RuntimeError('Request release status is unverified; cleanup remains pending')
        if status['busy'] is False and status['queued'] == 0:
            return
        if time.monotonic() >= end:
            raise TimeoutError('Request release deadline exceeded; cleanup remains pending')
        time.sleep(.1)


def stream_smoke(state,monitor,max_tokens=32,deadline_s=120):
    return stream_request(state,monitor,'「準備ができました。」とだけ返してください。',max_tokens,deadline_s)


class FixedRequestCancelled(RuntimeError):
    pass


def stream_request(state,monitor,content,max_tokens=128,deadline_s=120,*,partial=None,
                   api='openai',request_body=None,pathname='/v1/chat/completions',cancel_after_answer=False):
    monitor.check()
    ready(state)
    status = safety.get_json('/status')
    if status.get('busy') is not False or status.get('queued') != 0:
        raise RuntimeError('Candidate is busy/queued; no request sent')
    body = dict(model=manifest.MODEL,messages=[dict(role='user',content=content)],
                stream=True,stream_options=dict(include_usage=True),max_tokens=max_tokens,
                seed=42,temperature=0,top_k=1,top_p=1,min_p=0,reasoning_effort='none')
    allowed={'openai':'/v1/chat/completions','anthropic':'/v1/messages','responses':'/v1/responses'}
    if allowed.get(api)!=pathname:raise RuntimeError('Unexpected fixed API path')
    if request_body is not None:body=request_body
    connection = http.client.HTTPConnection('127.0.0.1',18080,timeout=deadline_s)
    output,errors,transports = partial if partial is not None else {},[],[]
    cancelled = threading.Event()
    done = threading.Event()
    answer_seen=threading.Event()
    start = time.monotonic()

    def read():
        try:
            connection.connect()
            transports.append(connection.sock)
            connection.auto_open = 0
            if cancelled.is_set():
                return
            monitor.check()
            connection.request('POST',pathname,body=json.dumps(body).encode('utf-8'),
                               headers={'Content-Type':'application/json'})
            with connection.getresponse() as response:
                if response.status != 200:
                    raise RuntimeError('Candidate generation HTTP failed: '+str(response.status))
                output.update(text='',reasoning='')
                for raw in response:
                    output['raw_sse']=output.get('raw_sse','')+raw.decode('utf-8',errors='strict')
                    if len(output['raw_sse'].encode('utf-8'))>32*1024*1024:raise RuntimeError('Fixed SSE raw bound exceeded')
                    if api!='openai':continue
                    if not raw.startswith(b'data: '):
                        continue
                    output.setdefault('first_sse_seconds',time.monotonic()-start)
                    data = raw[6:].strip()
                    if data == b'[DONE]':
                        output['wire_done_seen']=True
                        if request_body is None:break
                        continue  # Preserve the actual terminating blank frame for the pure wire parser.
                    chunk = json.loads(data)
                    if chunk.get('usage'):
                        output['usage'] = chunk['usage']
                    if chunk.get('timings'):
                        output['timings'] = chunk['timings']
                    for choice in chunk.get('choices',[]):
                        delta = choice.get('delta',{})
                        if delta.get('reasoning_content'):
                            output.setdefault('first_reasoning_seconds',time.monotonic()-start)
                            output['reasoning'] += delta['reasoning_content']
                        if delta.get('content'):
                            output.setdefault('first_answer_seconds',time.monotonic()-start)
                            output['text'] += delta['content']
                            answer_seen.set()
                        if choice.get('finish_reason'):
                            output['finish_reason'] = choice['finish_reason']
                            output['wire_finish_reason_seen']=True
        except Exception as error:
            errors.append(error)
        finally:
            output['wall_seconds'] = time.monotonic()-start
            connection.close()
            done.set()

    thread = threading.Thread(target=read,daemon=True)
    thread.start()
    try:
        while not done.wait(.05):
            monitor.check()
            if cancel_after_answer and answer_seen.is_set():
                # Cancellation is an actual in-flight disconnect, never an
                # already-idle request or a response with a terminal observed.
                ready(state)
                active=safety.get_json('/status')
                output['cancel_trigger']=dict(at=time.time(),monotonic=time.monotonic(),status=active,
                                              owner_verified=True,wire_done_seen=bool(output.get('wire_done_seen')),
                                              wire_finish_reason_seen=bool(output.get('wire_finish_reason_seen')))
                if (done.is_set() or output.get('wire_done_seen') or output.get('wire_finish_reason_seen')
                        or active.get('busy') is not True or type(active.get('queued')) is not int or active['queued']!=0):
                    raise RuntimeError('Fixed cancel case was not confirmed busy before terminal; no successful cancel claimed')
                output['planned_cancel']=True
                raise FixedRequestCancelled('Fixed cancel case disconnected after actual answer delta')
            if time.monotonic()-start > deadline_s:
                raise TimeoutError('Fixed request deadline exceeded')
        if errors:
            raise errors[0]
        monitor.check()
        if cancel_after_answer:raise RuntimeError('Fixed cancel request completed before transport cancellation')
        if request_body is not None:
            from tools.vision.image_api_cases import parse_sse
            parsed=parse_sse(api,output.get('raw_sse',''))
            output.update(parsed)
            if not parsed['normal_terminal']:raise RuntimeError('Image API did not return a valid terminal: '+str(parsed['errors']))
        if not output.get('text') or output.get('finish_reason') not in ('stop','length'):
            raise RuntimeError('Candidate did not return a completed answer')
        output['status_after'] = safety.get_json('/v1/status')
        return output
    finally:
        if not done.is_set():
            cancelled.set()
            output['transport_cut_at']=time.time()
            output['transport_cut_monotonic']=time.monotonic()
            try:
                transport = transports[0] if transports else connection.sock
                if transport is not None:
                    transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
            thread.join(15)
            if thread.is_alive():
                state['request_cleanup_pending'] = True
                raise RuntimeError('Cancelled API reader did not stop; cleanup remains unconfirmed')
        output['reader_stopped']=not thread.is_alive()


def screen(state,monitor,value,result):
    cfg = manifest.read_json(value['config'])
    cases = benchmark.prompts(cfg['tokenizer'])
    if benchmark.protocol(cases) != value['protocol']:
        raise RuntimeError('Screen prompts differ at request boundary')
    baseline = manifest.baseline_reference(value)
    directory = Path(value['config']).parent
    result['samples'] = []
    for request in benchmark.requests(cases,value['suite']):
        monitor.check()
        wait_request_release(state)
        case = request['case']
        deadline = case['initial_deadline_seconds']
        if baseline is not None:
            deadline = max(row['sample']['wall_seconds'] for row in baseline['samples']
                           if row['case'] == case['name'])*2+60
        if result['post_count'] >= value['max_posts']:
            raise RuntimeError('Fixed POST budget exhausted')
        # Seek before each request, so a stale fresh line cannot validate it.
        with Path(state['engine_log']).open('rb') as log:
            log.seek(0,2)
            offset = log.tell()
        result['post_count'] += 1
        sample = {}
        row = dict(phase=request['phase'],case=case['name'],repeat=request['repeat'],
                   prompt_tokens=case['prompt_tokens'],input_sha256=case['input_sha256'],
                   token_sha256=case['token_sha256'],deadline_seconds=deadline,sample=sample,
                   valid=False,invalid_reasons=[],engine_log_offset=offset,engine_log_delta='')
        failure = None
        try:
            sample.update(stream_request(state,monitor,case['content'],value['max_tokens'],deadline,partial=sample))
            wait_request_release(state)
        except BaseException as error:
            failure = error
            row.update(error_type=type(error).__name__,error_reason=str(error))
            row['invalid_reasons'].append('request/transport/release failed')
            raise
        finally:
            try:
                with Path(state['engine_log']).open('rb') as log:
                    log.seek(offset)
                    row['engine_log_delta'] = log.read().decode('utf-8',errors='replace')
                if failure is None:
                    row['invalid_reasons'].extend(benchmark.validate_sample(sample,case,row['engine_log_delta']))
                    if value['arm'] == 't1-table':
                        observed = benchmark.tuning_observation(Path(state['engine_log']).read_text(encoding='utf-8',errors='replace'))
                        if not any(int(rows) > 0 and arch == 'gfx1201' and version == '100500'
                                   for rows,arch,version in observed['enabled']):
                            row['invalid_reasons'].append('expected gfx1201/hipBLASLt100500 table activation missing')
                    if value['arm'] == 'd3-adapt-async1':
                        log = Path(state['engine_log']).read_text(encoding='utf-8',errors='replace')
                        enabled = 'adaptive tier asynchronous (--adapt-async 1): up to 96 swaps per round, a round every 4 windows' in log
                        pinned = 'mapped pinned cache complement ready: resident 16.00 GiB, pinned 16.00 GiB' in log
                        fallback = '--adapt-async 1 is off' in log
                        counts = re.findall(r'asynchronous adaptive tier: (\d+) rounds, (\d+) experts swapped in',log)
                        rounds,swapped = map(int,counts[-1]) if counts else (0,0)
                        work_required = result['post_count'] >= 2  # fixed primary 4K warmup is POST 2
                        row['async_observation'] = dict(enabled=enabled,pinned=pinned,fallback=fallback,
                            rounds=rounds,swapped=swapped,counters_present=bool(counts),work_required=work_required)
                        if not enabled or not pinned or fallback:
                            row['invalid_reasons'].append('async initialization/pinned/fallback condition failed')
                        if work_required and (not counts or rounds <= 0 or swapped <= 0):
                            row['invalid_reasons'].append('async actual work unconfirmed by fixed primary 4K warmup')
                row['valid'] = not row['invalid_reasons']
            except BaseException as evidence_error:
                row.update(valid=False,evidence_error_type=type(evidence_error).__name__)
                row['invalid_reasons'].append('engine log/validation evidence unavailable')
            result['samples'].append(row)
            try:
                with (directory/'samples.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            except BaseException as save_error:
                if failure is None:
                    raise
                failure.add_note('Partial sample persistence failed: '+type(save_error).__name__)
            if failure is None and not row['valid']:
                raise RuntimeError('Screen sample invalid; saved without replacing or spending extra POSTs: '+'; '.join(row['invalid_reasons']))
    if value['suite'] == 'screen':
        result['summary'] = benchmark.summarize(result['samples'])
        result['adoption'] = 'pending full ABBA, quality, integration and rollback; screen only'
        if baseline is not None:
            result['comparison'] = {name:{key:result['summary'][name][key]/baseline['summary'][name][key]
                                         for key in ('wall_seconds','first_answer_seconds','prompt_per_second','predicted_per_second')}
                                    for name,_,_ in benchmark.LENGTHS}


def loader_observation(state,value):
    """One standard Windows loader query outside measured POSTs, not a VAD alias."""
    cfg = manifest.read_json(value['config'])
    engines = [row for row in state['owned_identities'] if Path(row['exe']) == Path(cfg['exe'])]
    if len(engines) != 1:
        raise RuntimeError('One exact engine identity is required for loader observation')
    engine = engines[0]
    if safety.require_identity(safety.process_identity_status(engine)) is None:
        raise RuntimeError('Engine exited before loader observation')
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    psapi = ctypes.WinDLL('psapi',use_last_error=True)
    from ctypes import wintypes
    kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE,ctypes.POINTER(wintypes.HMODULE),
                                          wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE,wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD]
    handle = kernel.OpenProcess(0x0400|0x0010,False,engine['pid'])
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    result = dict(engine=engine,method='EnumProcessModulesEx/GetModuleFileNameExW',modules=[],
                  build=manifest.read_json(manifest.ORIGINAL/'engine/BUILD.json'))
    try:
        modules = (wintypes.HMODULE*4096)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcessModulesEx(handle,modules,ctypes.sizeof(modules),ctypes.byref(needed),3):
            raise ctypes.WinError(ctypes.get_last_error())
        if needed.value > ctypes.sizeof(modules):
            raise RuntimeError('Loader module query exceeded bounded capacity')
        for module in modules[:needed.value//ctypes.sizeof(wintypes.HMODULE)]:
            buffer = ctypes.create_unicode_buffer(32768)
            count = psapi.GetModuleFileNameExW(handle,module,buffer,len(buffer))
            if not count or count == len(buffer):
                raise ctypes.WinError(ctypes.get_last_error())
            path = Path(buffer.value)
            if path.is_relative_to(Path('C:/Windows')):
                continue
            expected = next((sha for name,sha in value['dependencies'].items() if Path(name) == path),None)
            actual = manifest.digest(path) if path.is_file() else None
            result['modules'].append(dict(path=str(path),sha256=actual,manifest_sha256=expected,
                                           matched=actual is not None and expected == actual))
    finally:
        kernel.CloseHandle(handle)
    if safety.require_identity(safety.process_identity_status(engine)) is None:
        raise RuntimeError('Engine exited during loader observation')
    if value.get('suite')=='vision-smoke':
        from . import gpu_observation
        result['windows_gpu_identity']=gpu_observation.windows_displays()
    else:
        script = ('Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion '
                  '| ConvertTo-Json -Depth 3 -Compress')
        completed = subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],
                                   capture_output=True,text=True,encoding='utf-8',timeout=30,check=True)
        result['windows_gpu_identity'] = json.loads(completed.stdout)
    log = Path(state['engine_log']).read_text(encoding='utf-8',errors='replace')
    result['engine_gpu_lines'] = [line for line in log.splitlines() if 'GPU 0:' in line or 'HIP runtime ' in line or 'PCIe probe' in line]
    result['all_non_system_modules_bound'] = bool(result['modules']) and all(row['matched'] for row in result['modules'])
    return result,engine


def run(path,approved):
    value = manifest._verify_document(path,approved)
    if value['suite']=='vision-probe':
        from . import standalone_phase
        return standalone_phase.run_probe(path,approved)
    if value['suite']=='vision-encode':
        from . import standalone_phase
        return standalone_phase.run_encode(path,approved)
    if value['suite']=='vision-smoke':
        from . import image_phase
        return image_phase.run_smoke(path,approved)
    value = manifest.verify(path,approved)
    if value['suite'] not in ('smoke','screen','diagnostic') or (value['suite'] == 'smoke' and value.get('arm') != 'baseline'):
        raise RuntimeError('Only baseline text smoke, screen/diagnostic and standalone vision-probe are implemented; encode/full/serve remain pending')
    directory = Path(value['config']).parent
    # A consumed manifest cannot silently spend its startup/POST budget again or
    # overwrite a prior result. Preparing another arm creates another directory.
    with (directory/'claim.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(manifest_sha256=approved,pid=os.getpid(),at=time.time()),stream)
    result = dict(status='unverified',manifest=str(path),manifest_sha256=approved,post_count=0,start_count=0,
                  comparison_eligible=False)
    state,failure = None,None
    retained = {}
    try:
        with shared_operation(),candidate_interrupts(retained):
            try:
                production_inactive()
                result['memory_budget'] = preflight_budget()
                with MemoryMonitor(directory/'memory.jsonl') as monitor:
                    monitor.cancel_requested = lambda:retained.get('cancel_requested',False)
                    try:
                        result['start_count'] += 1
                        state = start_session(path,approved,monitor,retained=retained)
                        retained.update(spawn_possible=True,state=state)
                        result['startup_seconds'] = state['startup_seconds']
                        if value['suite'] == 'smoke':
                            result['post_count'] += 1
                            result['sample'] = stream_smoke(state,monitor,value['max_tokens'])
                        else:
                            result['loader'],monitor.engine = loader_observation(state,value)
                            (directory/'loader-observation.json').write_text(json.dumps(result['loader'],indent=2)+'\n',encoding='utf-8')
                            manifest.require_loader_binding(result['loader'],value['dependencies'])
                            result['comparison_eligible'] = True
                            screen(state,monitor,value,result)
                        monitor.check()
                        result['generation'] = 'passed'
                    except BaseException as work_error:
                        failure = work_error
                        raise
                    finally:
                        if state is not None:
                            try:
                                state.update(phase='stopping',cleanup_pending=True)
                                safety.save(state)
                                result['cleanup'] = dict(status='pending')
                                wait_request_release(state)
                                monitor.expect_engine_exit()
                                stopped = safety.stop_owned(state)
                                safety.check_port_available()
                                state.update(phase='stopped',stopped_pids=stopped,cleanup_pending=False)
                                safety.save(state)
                                result['cleanup'] = dict(status='passed',stopped_pids=stopped,port_free=True)
                                if value['suite'] != 'smoke':
                                    result['tuning_observation'] = benchmark.tuning_observation(
                                        Path(state['engine_log']).read_text(encoding='utf-8',errors='replace'))
                            except BaseException as cleanup_error:
                                state.update(phase='cleanup-pending',cleanup_pending=True,
                                             cleanup_failure=type(cleanup_error).__name__)
                                if failure is None:
                                    failure = cleanup_error
                                    raise
                                failure.add_note('Candidate cleanup failed: '+type(cleanup_error).__name__)
                result['status'] = 'passed'
                result['completed_date'] = time.strftime('%Y-%m-%d')
            except BaseException as error:
                original = failure if failure is not None else error
                if original is not error:
                    original.add_note('Later evaluation/collector failure: '+type(error).__name__)
                result.update(status='failed',error_type=type(original).__name__,reason=str(original),comparison_eligible=False)
                if retained.get('spawn_possible') and retained.get('state',{}).get('cleanup_pending',True):
                    hold_pending_cleanup(retained,result,directory)
                raise original
    except BaseException as error:
        result.update(status='failed',error_type=type(error).__name__,reason=str(error))
        raise
    finally:
        (directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action',required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--arm',choices=manifest.ARMS,required=True)
    prepare.add_argument('--suite',choices=manifest.SUITES,default='smoke')
    prepare.add_argument('--baseline-result',type=Path)
    prepare.add_argument('--probe-result',type=Path)
    prepare.add_argument('--encode-result',type=Path)
    prepare.add_argument('--coexistence-budget',type=Path)
    check = sub.add_parser('verify')
    execute = sub.add_parser('run')
    for command in (check,execute):
        command.add_argument('--manifest',type=Path,required=True)
        command.add_argument('--manifest-sha256',required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        path,sha = manifest.prepare(args.arm,args.suite,args.baseline_result,probe_result=args.probe_result,
                                    encode_result=args.encode_result,coexistence_budget=args.coexistence_budget)
        result = dict(manifest=str(path),sha256=sha,started=False)
    elif args.action == 'verify':
        result = manifest.verify(args.manifest,args.manifest_sha256)
    else:
        result = run(args.manifest,args.manifest_sha256)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()
