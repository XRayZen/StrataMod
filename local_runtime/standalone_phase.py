"""One fixed, guarded native probe. Encode/full/serve remain separate gates."""
import json
from pathlib import Path
import time

from . import manifest,image_phase,official_runtime,gpu_observation
from . import runtime_safety as safety


def check_native_live(process,observer,state,monitor):
    monitor.check()
    observation=observer.snapshot()
    state.update(owned_identities=observation['identities'],spawn_observation=observation)
    safety.save(state)
    if observation['unknown'] or observation['errors'] or process.poll() is not None or not safety.owned(state):
        raise RuntimeError('Native encoder identity/cohort is unconfirmed or exited')
    for row in observation['identities']:
        identity=safety.process_identity_status(row)
        if identity.status=='gone':continue
        if identity.status!='verified' or not official_runtime.checked_job.membership_pid(row['pid']):
            raise RuntimeError('Native encoder Job membership is unconfirmed')


def encoder_event(process,observer,state,monitor,io,meter,deadline):
    while True:
        check_native_live(process,observer,state,monitor)
        meter.periodic()
        if time.monotonic()>deadline:raise TimeoutError('Fixed native encoder deadline exceeded')
        event=io.read_event(.05)
        if event is None:continue
        if event['kind'] in ('error','eof'):raise RuntimeError('Native encoder '+str(event))
        return event


def encode_exchanges(process,observer,state,monitor,value,result,index,io,meter):
    protocol=image_phase.encode_protocol()[index]
    directory=Path(value['config']).parent
    arm=dict(arm=protocol['arm'],images=[],valid=False)
    result.setdefault('arms',[]).append(arm)
    try:
        meter.sample('load')
        event=encoder_event(process,observer,state,monitor,io,meter,time.monotonic()+300)
        if event!={'kind':'ready','width':2560}:raise RuntimeError('Native READY width must be 2560')
        meter.sample('ready-after-warmup')
        for case in protocol['encodes']:
            row=dict(name=case['name'],input_sha256=case['sha256'],valid=False)
            arm['images'].append(row)
            output=directory/f"{protocol['arm']}-{case['name']}.sve"
            if output.exists():raise RuntimeError('Refuse to overwrite an existing SVE output')
            if result['encode_count']>=value['max_encodes']:raise RuntimeError('Fixed ENC budget exhausted')
            check_native_live(process,observer,state,monitor)
            meter.sample('before-'+case['name'])
            result['encode_count']+=1  # Reserve the sole outstanding command before write/flush.
            row.update(encode_index=result['encode_count'],output=str(output))
            io.send_encode(case['path'],output)
            event=encoder_event(process,observer,state,monitor,io,meter,time.monotonic()+case['deadline_seconds'])
            if event['kind']!='ok':raise RuntimeError('Expected exactly one native OK')
            sve=image_phase.read_sve(output)
            if sve['shape'][:3]!=[event[key] for key in ('n','nx','ny')]:raise RuntimeError('Native OK and SVE shape/grid disagree')
            row.update(ok=event,shape=sve['shape'],sve_sha256=sve['sha256'],valid=True)
            meter.sample('after-'+case['name'])
        arm['valid']=True
        return arm
    except BaseException as error:
        arm.update(error_type=type(error).__name__,reason=str(error))
        raise


def finish_encoder(process,observer,retained,monitor,io):
    io.send_quit()
    deadline=time.monotonic()+15
    while process.poll() is None:
        monitor.check()
        observation=observer.snapshot()
        if observation['unknown'] or observation['errors']:raise RuntimeError('Encoder exit cohort is unconfirmed')
        if time.monotonic()>deadline:raise TimeoutError('Encoder QUIT did not exit')
        time.sleep(.05)
    process.wait(timeout=0)
    if process.returncode!=0:raise RuntimeError('Native encoder exit failed')
    retained['state']['spawn_observation']=observer.finish_standalone()
    retained['state']['owned_identities']=retained['state']['spawn_observation']['identities']
    if not io.close_reader(2):raise RuntimeError('Encoder stdout reader remains pending')
    if io.read_event(0)!={'kind':'eof'}:raise RuntimeError('Unexpected extra encoder stdout event')
    for stream in (process.stdin,process.stdout):stream.close()
    deadline=time.monotonic()+15
    while True:
        proof=native_exit_proof(retained)
        if proof['complete']:return proof
        if time.monotonic()>deadline:raise RuntimeError('Encoder cohort exit remains pending')
        time.sleep(.1)


def encode_result(value,result):
    """Bind the twelve actual outputs, four shape parities and sampled peaks."""
    import re
    comparisons=[]
    for index in range(len(image_phase.IMAGES)):
        reference=image_phase.read_sve(result['arms'][0]['images'][index]['output'])
        comparisons.append(dict(name=result['arms'][0]['images'][index]['name'],
            cpu_aa=image_phase.compare_sve(reference,image_phase.read_sve(result['arms'][1]['images'][index]['output'])),
            hip=image_phase.compare_sve(reference,image_phase.read_sve(result['arms'][2]['images'][index]['output']))))
    hip=result['arms'][2]
    graph=re.findall(r'GRAPH phase=(warmup|encode) completed_hip_compute=(\d+) completed_cpu_compute=(\d+)',hip['stderr'])
    graph_passed=([row[0] for row in graph]==['warmup',*['encode']*len(image_phase.IMAGES)] and all(int(row[1])>0 for row in graph))
    shape_tokens=[row['shape'][0] for row in hip['images']]
    samples=hip['memory_samples']
    ready_samples=[row for row in samples if row['label']!='load']
    fields=('adapter_dedicated_bytes','adapter_shared_bytes','process_dedicated_bytes','process_shared_bytes')
    peaks={key:max((row['gpu'][key] for row in samples if row.get('gpu') is not None and row['gpu'].get(key) is not None),default=None) for key in fields}
    memory_ready=bool(ready_samples) and all(row.get('gpu') is not None and all(type(row['gpu'].get(key)) is int for key in fields) for row in ready_samples)
    result.update(parity=comparisons,parity_passed=all(row['cpu_aa']['passed'] and row['hip']['passed'] for row in comparisons),
                  coverage_passed=(len(hip['images'])==2 and all(row['valid'] for row in hip['images'])),
                  coverage=dict(scope='two original RefImage portraits only',landscape_proved=False,
                                exact_300_tokens_proved=False,actual_tokens=shape_tokens),
                  graph=dict(rows=graph,passed=graph_passed,meaning='completed ROCm placed high-cost graph operations, not all kernels'),
                  sampled_gpu_peaks=peaks,memory_observation_ready=memory_ready,memory_budget_ready=False,
                  coexistence_budget='pending typed actual-peak plus Main-approved residual receipt; no expected/zero substitution')
    if not (result['parity_passed'] and result['coverage_passed'] and graph_passed and memory_ready):
        raise RuntimeError('Encoder parity/shape coverage/HIP graph/sampled memory evidence is incomplete')


def run_encode(path,approved):
    from . import evaluate_r9700 as runner
    from tools.vision.encode_io import EncodeIO
    value=manifest._verify_authority(path,approved)
    if value['suite']!='vision-encode' or (value['max_starts'],value['max_encodes'],value['max_posts'])!=(3,6,0):
        raise RuntimeError('Only fixed CPU-AA/HIP three starts/six ENC/zero POST are allowed')
    directory=Path(value['config']).parent
    with (directory/'claim.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(manifest_sha256=approved,pid=runner.os.getpid(),at=time.time()),stream)
    result=dict(status='unverified',manifest=str(path),manifest_sha256=approved,start_count=0,spawn_attempt_count=0,
                post_count=0,encode_count=0,arms=[],cleanup=dict(status='pending'))
    retained={};process=observer=None
    try:
        with runner.shared_operation(),runner.candidate_interrupts(retained):
            try:
                runner.production_inactive()
                result['memory_budget']=runner.preflight_budget(suite=value['suite'])
                with runner.MemoryMonitor(directory/'memory.jsonl') as monitor:
                    monitor.cancel_requested=lambda:retained.get('cancel_requested',False)
                    manifest.verify(path,approved)  # One physical asset pass for all three locked arms.
                    probe=manifest.image_reference(value)
                    adapter=gpu_observation.select_adapter(gpu_observation.windows_displays(),gpu_observation.dxgi_adapters())
                    if adapter['windows']['pci'].lower()!=probe['pci'].lower():raise RuntimeError('ENC PDH adapter and probe PCI differ')
                    for index in range(3):
                        def before_spawn():
                            monitor.check();result['memory_before_spawn']=runner.preflight_budget(suite=value['suite'])
                        retained.update(spawn_possible=False,process=None,observer=None,state={})
                        retained.pop('reader',None)
                        result['spawn_attempt_count']+=1
                        process,observer,state=official_runtime._start_standalone(path,approved,retained=retained,index=index,before_spawn=before_spawn)
                        result['start_count']+=1
                        io=EncodeIO(process.stdin,process.stdout,directory/f'native-{index}.stdout')
                        retained['reader']=io
                        samples=[]
                        with gpu_observation.EncodeMemory(state,samples,adapter if index==2 else None) as meter:
                            try:
                                arm=encode_exchanges(process,observer,state,monitor,value,result,index,io,meter)
                            finally:
                                if len(result['arms'])>index:
                                    result['arms'][index].update(memory_samples=samples,cohort=list(state['owned_identities']))
                            if index==2:
                                raw=(directory/f'native-{index}.log').read_text(encoding='utf-8')
                                arm['physical_identity']=image_phase.match_encoder_identity(raw,probe)
                                arm['loader_modules']=gpu_observation.loaded_modules(state,value['dependencies'])
                                arm['sdk']=image_phase.probe_modules(raw,arm['loader_modules'],value['dependencies'])
                        arm['cleanup']=finish_encoder(process,observer,retained,monitor,io)
                        arm['stderr']=(directory/f'native-{index}.log').read_text(encoding='utf-8')
                        state.update(phase='stopped',cleanup_pending=False);safety.save(state)
                    encode_result(value,result)
                    result.update(status='passed',cleanup=dict(status='passed',all_three_cohorts=True,port_free=True),identity=probe,
                                  completed_date=time.strftime('%Y-%m-%d'))
            except BaseException as error:
                result.update(status='failed',error_type=type(error).__name__,reason=str(error))
                if retained.get('spawn_possible'):
                    try:
                        try:runner.cleanup_failed_start(retained.get('process'),retained.get('observer'),retained.get('state',{}))
                        except BaseException as cleanup_error:result['cleanup_error']=str(cleanup_error)
                        try:
                            if retained.get('reader') is not None and not retained['reader'].close_reader(2):
                                retained['state'].update(cleanup_pending=True,reader_cleanup_pending=True)
                                safety.save(retained['state'])
                        except BaseException as reader_error:
                            retained['state'].update(cleanup_pending=True,reader_cleanup_pending=True)
                            result['reader_cleanup_error']=dict(type=type(reader_error).__name__,reason=str(reader_error))
                    finally:
                        # Every possible spawn takes the existing barrier, even
                        # when secondary reader/persistence work itself failed.
                        # It independently proves cohort, reader and port exit.
                        runner.hold_pending_cleanup(retained,result,directory)
                raise
    finally:
        (directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result


def native_exit_proof(retained):
    """Wait for normal native exit before entering the sticky failure proof.

    A known console process can exit between its identity query and children().
    Normal cooperative exit does not need a live descendant traversal: finish
    the observer first, then require every captured member independently absent.
    Unknown/error evidence is never cleared here or promoted to exit authority.
    """
    from . import evaluate_r9700 as runner
    state=retained['state']
    for row in state.get('owned_identities',[]):
        identity=safety.process_identity_status(row)
        presence=safety.process_presence(row['pid'])
        if identity.status!='gone' or presence!='gone':
            return dict(complete=False,members=[dict(row,identity_status=identity.status,presence=presence)])
    return runner.pending_exit_proof(retained)


def wait_probe(process,observer,state,monitor,value,result):
    directory=Path(value['config']).parent
    native_log=directory/'native-0.log'
    started=time.monotonic()
    modules={};attempts=0
    while True:
        monitor.check()
        observation=observer.snapshot()
        state.update(owned_identities=observation['identities'],spawn_observation=observation)
        safety.save(state)
        if observation['unknown'] or observation['errors']:
            raise RuntimeError('Standalone native cohort is incomplete')
        if process.poll() is None:
            if not safety.owned(state):raise RuntimeError('Standalone root identity changed before exit')
            members=[]
            for row in observation['identities']:
                identity=safety.process_identity_status(row)
                if identity.status=='gone':continue
                if identity.status!='verified' or not official_runtime.checked_job.membership_pid(row['pid']):
                    raise RuntimeError('Native cohort Job membership is unconfirmed')
                members.append(row)
            result['job_members']=members
        raw=native_log.read_text(encoding='utf-8',errors='strict')
        result['native_log']=raw
        # A finite probe can exit immediately after its diagnostics. Capture
        # paths while it is alive, without hashing large SDK files on that
        # critical path; bind their hashes after native exit. No extra launch.
        if process.poll() is None:
            attempts+=1
            try:
                snapshot=gpu_observation.loaded_modules(state,value['dependencies'],hash_files=False)
                modules.update({row['path']:row for row in snapshot})
            except Exception as error:
                result.setdefault('loader_query_errors',[]).append(dict(type=type(error).__name__,reason=str(error)))
                if process.poll() is None:raise
        result['loader_query_count']=attempts
        result['loader_modules']=list(modules.values())
        if time.monotonic()-started>30:raise TimeoutError('Fixed native probe deadline exceeded')
        if process.poll() is not None:break
        time.sleep(.05)
    process.wait(timeout=0)
    observation=observer.finish_standalone()
    state.update(owned_identities=observation['identities'],spawn_observation=observation)
    raw=native_log.read_text(encoding='utf-8',errors='strict')
    result.update(native_log=raw,native_exit_code=process.returncode,probe_seconds=time.monotonic()-started)
    if process.returncode!=0:raise RuntimeError('Native HIP probe failed')
    if not modules:raise RuntimeError('Native probe ended without a verified standard loader snapshot')
    result['loader_modules']=gpu_observation.bind_module_hashes(list(modules.values()))
    result['sdk']=image_phase.probe_modules(raw,result['loader_modules'],value['dependencies'])
    result['identity']=image_phase.match_probe(raw,gpu_observation.windows_displays())
    return observation


def run_probe(path,approved):
    from . import evaluate_r9700 as runner
    value=manifest._verify_authority(path,approved)
    if value['suite']!='vision-probe' or value['max_starts']!=1 or value['max_posts']!=0:
        raise RuntimeError('Only one fixed native probe, zero generation POSTs, is implemented')
    directory=Path(value['config']).parent
    with (directory/'claim.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(manifest_sha256=approved,pid=runner.os.getpid(),at=time.time()),stream)
    result=dict(status='unverified',manifest=str(path),manifest_sha256=approved,start_count=0,spawn_attempt_count=0,post_count=0,
                encode_count=0,comparison_eligible=False,scope='native probe only; encode/full/serve remain unverified')
    retained={};process=observer=None
    try:
        with runner.shared_operation(),runner.candidate_interrupts(retained):
            try:
                runner.production_inactive()
                result['memory_budget']=runner.preflight_budget(suite=value['suite'])
                with runner.MemoryMonitor(directory/'memory.jsonl') as monitor:
                    monitor.cancel_requested=lambda:retained.get('cancel_requested',False)
                    try:
                        def before_spawn():
                            monitor.check()
                            result['memory_budget_before_spawn']=runner.preflight_budget(suite=value['suite'])
                        result['spawn_attempt_count']=1
                        process,observer,state=official_runtime.start_standalone(path,approved,retained=retained,before_spawn=before_spawn)
                        result['start_count']=1
                        wait_probe(process,observer,state,monitor,value,result)
                        # The original handles are reaped; known cohort members
                        # must additionally be absent before releasing old locks.
                        deadline=time.monotonic()+15
                        while True:
                            proof=native_exit_proof(retained)
                            result['cleanup']=dict(status='pending',lock_hold_proof=proof)
                            if proof['complete']:break
                            if time.monotonic()>deadline:raise RuntimeError('Native probe cohort exit remains pending')
                            time.sleep(.1)
                        state.update(phase='stopped',cleanup_pending=False)
                        safety.save(state)
                        result['cleanup']=dict(status='passed',lock_hold_proof=proof,port_free=True)
                    except BaseException:
                        result['start_count']=int(retained.get('process') is not None)
                        state=retained.get('state',{})
                        if retained.get('spawn_possible'):
                            try:
                                runner.cleanup_failed_start(process or retained.get('process'),observer or retained.get('observer'),state)
                            except BaseException as error:
                                result['cleanup_error']=dict(type=type(error).__name__,reason=str(error))
                        raise
                result.update(status='passed',completed_date=time.strftime('%Y-%m-%d'))
            except BaseException as error:
                result.update(status='failed',error_type=type(error).__name__,reason=str(error))
                if retained.get('spawn_possible') and retained.get('state',{}).get('cleanup_pending',True):
                    runner.hold_pending_cleanup(retained,result,directory)
                raise
    except BaseException as error:
        result.update(status='failed',error_type=type(error).__name__,reason=str(error))
        raise
    finally:
        (directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result
