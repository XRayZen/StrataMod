"""T35 bounded benchmark controller and pure replay. Import starts no process.

Arrival clocks measure this pipe boundary, not GPU kernels or per-token native
instants. T23 remains the authority for original IDs/count/hash/finish integrity.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import queue
import re
import statistics
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parents[3]
_dto_path=ROOT/'Strata-extensions/control/generation_frames.py'
_spec=importlib.util.spec_from_file_location('t35_generation_frames',_dto_path)
DTO=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(DTO)

def require(ok,message):
    if not ok:raise ValueError(message)

def uint(value,name='counter'):
    require(type(value)is int and 0<=value<=2**64-1,name+' must be an unsigned integer')
    return value

def positive(value,name):
    uint(value,name);require(value>0,name+' must be positive');return value

def finite(value,name):
    require(type(value)in(int,float) and math.isfinite(value),name+' must be finite')
    return value

def unknown(reason):return dict(value=None,reason=reason)
def measured(value):return dict(value=value,reason=None)

BUDGET=('device_cache_payload_bytes','ram_cache_payload_bytes','device_slots','ram_slots','row_device_slots','row_ram_slots')
OWNER_COUNTERS=('primary_logical_read','primary_aligned_read','primary_issued_read','primary_issued_reads','primary_h2d','primary_input_h2d','primary_output_d2h','primary_gpu_hits','primary_ram_hits','primary_ssd_misses','row_logical_read','row_requested_read','row_received','row_issued','row_issued_requested','row_weight_h2d','row_index_h2d','row_control_d2h','row_output_d2h','row_gpu_hits','row_ram_hits','row_ssd_misses')
CORE_COUNTERS=('core_constant_source_bytes','core_storage_upload_bytes','requested_logits_or_audit_d2h')
OWNED=('core_storage_device_owned','primary_device_owned','row_device_owned','actual_device_owned')

def check_info(value):
    require(type(value)is dict and value.get('family')=='deepseek41','INFO family')
    for name in BUDGET:positive(value.get(name),name)
    for name in OWNER_COUNTERS+CORE_COUNTERS+OWNED:uint(value.get(name),name)
    require(value['actual_device_owned']==sum(value[k] for k in OWNED[:3]),'device owned alias double count/mismatch')
    # No such Primary counter exists; aligned_read is not received.
    require('primary_received' in value and value['primary_received'] is None,'Primary received must remain explicit unknown')
    for prefix in ('primary','row'):
        for suffix in ('pinned_known','pinned_observed'):
            require(type(value.get(prefix+'_'+suffix))is bool,'pinned observation type')
        uint(value.get(prefix+'_host_owned'),prefix+' host bytes')
        if value[prefix+'_pinned_known']:
            uint(value.get(prefix+'_pinned_subset'),prefix+' pinned bytes')
            require(value[prefix+'_pinned_subset']<=value[prefix+'_host_owned'],'pinned is host subset')
        else:require(prefix+'_pinned_subset' in value and value[prefix+'_pinned_subset'] is None,'unknown pinned subset must be explicit null')
    uint(value.get('owner_metadata_bytes'),'owner metadata');uint(value.get('owned_host_owner_subset_bytes'),'host owner alias')
    require(value['owned_host_owner_subset_bytes']==value['primary_host_owned']+value['row_host_owned']+value['owner_metadata_bytes'],'host subset alias mismatch')
    return value

def info_delta(before,after):
    check_info(before);check_info(after)
    require(all(before[k]==after[k] for k in BUDGET),'request changed resolved owner capacity')
    result={}
    for name in OWNER_COUNTERS:
        require(after[name]>=before[name],'cumulative counter reset: '+name)
        result[name]=after[name]-before[name]
    # Core is recreated per request. These are absolute request values, even
    # when the previous request's value was larger.
    for name in CORE_COUNTERS:result[name]=after[name]
    result['known_logical_source_bytes']=result['primary_logical_read']+result['row_logical_read']+result['core_constant_source_bytes']
    result['known_component_h2d']=result['primary_h2d']+result['primary_input_h2d']+result['row_weight_h2d']+result['row_index_h2d']+result['core_storage_upload_bytes']
    uint(result['known_logical_source_bytes'],'known logical aggregate');uint(result['known_component_h2d'],'known H2D aggregate')
    for name in ('primary_received','physical_io','other_control_h2d','other_control_d2h'):result[name]=None
    result['physical_total_transfer_claim']=False
    return result

def analyze_run(capture):
    require(type(capture)is dict,'capture object')
    require(capture.get('clock_domain')=='perf_counter_ns','clock domain')
    resolution=positive(capture.get('clock_resolution_ns'),'clock resolution')
    start=uint(capture.get('request_start_ns'),'request start');last=start
    expected=DTO.context(capture['context']);dto=DTO.GenerationDTO(expected)
    first_token=last_token=None;first_frame=last_frame=None;done=None;finish_time=None
    progress=[];events=capture['events'];require(type(events)is list,'capture events')
    for index,event in enumerate(events):
        require(type(event)is dict and set(event)=={'line','t_ns'},'event fields')
        now=uint(event['t_ns'],'arrival timestamp');require(now>=last,'clock reversed');last=now
        line=event['line'];require(type(line)is str,'raw line')
        require(done is None,'events after DONE in request capture')
        if line.startswith('{'):
            frame=DTO.parse_frame(line);value=dto.feed(line)
            if frame['kind']=='token_batch':
                if first_token is None:first_token=now;first_frame=index
                last_token=now;last_frame=index
            elif frame['kind']=='finish':finish_time=now
        elif line.startswith('PP '):
            parts=line.split();require(len(parts)==3 and all(x.isdecimal() for x in parts[1:]),'prefill progress')
            a,b=map(int,parts[1:]);require(a<=b and (not progress or a>=progress[-1][0]),'prefill progress order');progress.append((a,b,now))
        elif line.startswith('DONE '):
            require(line[5:].isdecimal() and finish_time is not None,'DONE before valid finish')
            done=uint(int(line[5:]),'native DONE count')
        else:raise ValueError('unexpected/ERR/incomplete native line: '+line[:100])
    raw=dto.result();require(done is not None and done==raw['generated_count'],'missing/mismatched DONE count')
    require(raw['generation_success'],'native error/cancel/nonfinite is not a successful measurement')
    count=raw['generated_count'];elapsed=last-start
    ttft=unknown('no_model_tokens') if first_token is None else (measured((first_token-start)/1e9) if first_token-start>resolution else unknown('unresolved_request_to_first'))
    if count<2:tpot=unknown('fewer_than_two_generated_tokens')
    elif first_frame==last_frame or last_token-first_token<=resolution:tpot=unknown('coalesced_or_unresolved_endpoints')
    else:tpot=measured((last_token-first_token)/1e9/(count-1))
    tps=measured(count/(elapsed/1e9)) if count and elapsed>resolution else unknown('no_tokens_or_unresolved_elapsed')
    prefill=unknown('no_complete_progress_endpoints')
    if progress and progress[0][0]==0 and progress[-1][0]==progress[-1][1] and progress[-1][2]-progress[0][2]>resolution:
        prefill=measured((progress[-1][2]-progress[0][2])/1e9)
    stats=info_delta(capture['info_before'],capture['info_after'])
    after=capture['info_after'];memory=dict(host_owner_subset=after['owned_host_owner_subset_bytes'],owner_metadata=after['owner_metadata_bytes'],pinned_subset={k:after[k+'_pinned_subset'] for k in ('primary','row')},pinned_known={k:after[k+'_pinned_known'] for k in ('primary','row')},full_host_peak=None)
    return dict(original_ids=list(raw['original_token_ids']),generated_count=count,ids_sha256=raw['ids_sha256'],finish=raw['finish'],TTFT_pipe_seconds=ttft,aggregate_TPOT_pipe_seconds=tpot,output_tokens_per_request_second=tps,raw_first_last_arrival_span_ns=None if first_token is None else last_token-first_token,prefill_progress_receive_seconds=prefill,counters=stats,resolved_budget={k:after[k] for k in BUDGET},device_owned={k:after[k] for k in OWNED},memory=memory,physical_peak=None,kernel_seconds=None,individual_native_token_timestamps=None)

def analyze_pair(cold,warm):
    a,b=analyze_run(cold),analyze_run(warm)
    require(a['resolved_budget']==b['resolved_budget'],'pair capacity mismatch')
    require(positive(cold.get('process_id'),'cold process')==positive(warm.get('process_id'),'warm process'),'pair must retain same actual owners/process')
    require(cold.get('request_index')==0 and type(cold.get('request_index'))is int and warm.get('request_index')==1 and type(warm.get('request_index'))is int,'cold first / warm next request')
    require(all(cold['info_before'][k]==0 for k in OWNER_COUNTERS),'cold app owners were not empty')
    require(a['generated_count']>0,'no generated model token for an eager baseline')
    for key in ('primary_logical_read','primary_aligned_read','primary_issued_reads','primary_h2d','primary_ssd_misses'):
        require(a['counters'][key]>0,'cold full-Core supply counter falsely zero: '+key)
    require((a['original_ids'],a['finish'])==(b['original_ids'],b['finish']),'cold/warm greedy output mismatch')
    for key in ('bundle_id','runtime_epoch','asset_revision','tokenizer_identity'):
        require(cold['context'][key]==warm['context'][key],'pair source/epoch mismatch')
    require(type(cold.get('workload_identity'))is str and re.fullmatch('[0-9a-f]{64}',cold['workload_identity'])is not None and cold['workload_identity']==warm.get('workload_identity'),'pair workload/options binding')
    ratios={}
    for metric in ('TTFT_pipe_seconds','aggregate_TPOT_pipe_seconds'):
        x,y=a[metric]['value'],b[metric]['value']
        ratios[metric]=measured(x/y) if x is not None and y is not None and x>0 and y>0 else unknown('pair_metric_unavailable')
    coverage=dict(primary_compute=a['generated_count']>0,SSD_requested=a['counters']['primary_aligned_read']>0,RAM_hit=any(x['counters']['primary_ram_hits']>0 or x['counters']['row_ram_hits']>0 for x in (a,b)))
    return dict(A=a,B=b,ratios=ratios,cache_conditions=dict(A='process/app empty; OS cache unknown',B='same owners/new Core; partial warm'),tier_coverage=coverage,physical_cold_qualified=False)

def paired_interval(ratios,expected_count=5):
    require(type(expected_count)is int and expected_count in (3,5),"prespecified pair count")
    require(type(ratios)is list,'paired ratios')
    for value in ratios:require(finite(value,'ratio')>0,'ratio positive')
    if len(ratios)!=expected_count:return dict(value=None,reason='requires_prespecified_pairs',effect='unjudged')
    logs=list(map(math.log,ratios));center=statistics.mean(logs);critical=4.302652729911275 if expected_count==3 else 2.7764451051977987; margin=critical*statistics.stdev(logs)/math.sqrt(expected_count)
    try:interval=[math.exp(center-margin),math.exp(center+margin)]
    except OverflowError:return dict(value=None,reason='unrepresentable_derived_interval',effect='unjudged')
    if not all(math.isfinite(x) and x>0 for x in interval):return dict(value=None,reason='unrepresentable_derived_interval',effect='unjudged')
    geometric=math.exp(center);precision=max(interval[1]/geometric-1,1-interval[0]/geometric)
    if not math.isfinite(precision):return dict(value=None,reason='unrepresentable_derived_precision',effect='unjudged')
    return dict(value=interval,geometric_mean=geometric,relative_precision=precision,df=expected_count-1,reason=None,effect='improved' if interval[0]>1 else 'worse' if interval[1]<1 else 'unjudged',method=f'paired log ratio t95 df{expected_count-1}; cold/warm order is fixed')

DRAM_LOW=8589934592
DRAM_HIGH=9663676416
DRAM_AIM=9126805504


def natural(value,name):
    require(type(value)is int and 0<=value<=2**64-1,name+' must be uint64')
    return value


def select_ram_payload(available,current,minimum,deferred=0):
    for value,name in ((available,'available'),(current,'current'),(minimum,'minimum'),(deferred,'deferred')):natural(value,name)
    require(minimum>0 and current>=minimum,'working minimum RAM')
    if DRAM_LOW<=available<=DRAM_HIGH:return current
    candidate=current+(available-DRAM_AIM)-deferred
    require(minimum<=candidate<=2**64-1,'no legal RAM candidate for physical target')
    return candidate


def explicit_ram_slots(payload,weight):
    positive(weight,'weight capacity');natural(payload,'RAM payload')
    unit=weight+264;require(unit<=2**64-1 and payload>=unit,'explicit working minimum')
    slots=payload//unit
    return dict(weight=slots,row=slots,payload_bytes=slots*unit,unused_bytes=payload%unit)


def memory_condition(samples):
    require(type(samples)is list,'memory samples')
    required={'constructed','A-before','A-after','B-before','B-after'}
    order={'constructed':0,'A-before':1,'A-monitor':2,'A-after':3,'B-before':4,'B-monitor':5,'B-after':6}
    points=[];outside=False;unknown=False;previous=-1;identity=None
    for sample in samples:
        point=sample['point'];require(point in order,'sample point')
        require(order[point]>=previous,'physical observation order');previous=order[point]
        require(point.endswith('-monitor')or point not in points,'duplicate mandatory observation')
        points.append(point)
        if point.endswith('-monitor'):require(point[0]+'-before'in points and point[0]+'-after'not in points,'monitor outside GEN')
        pid=sample.get('pid');birth=sample.get('birth')
        require(type(pid)is int and pid>0,'positive observed process ID')
        require(birth is None or type(birth)is int and 0<birth<=2**64-1,'positive observed birth')
        if point=='constructed':identity=(pid,birth)
        else:require(identity is not None,'constructed observation first')
        if identity is None or identity[1]is None or birth is None:unknown=True
        else:require((pid,birth)==identity,'physical sample process identity changed')
        diagnostic=sample.get('identity_verified');require(diagnostic is None or type(diagnostic)is bool,'identity status bool/unknown')
        if diagnostic is not True:unknown=True
        status=sample.get('global_status');require(type(status)is bool,'GlobalMemoryStatusEx bool status')
        value=sample['available_physical_bytes']
        if not status:
            require(value is None,'failed global observation must be null');unknown=True
        else:
            natural(value,'successful available sample')
            if not DRAM_LOW<=value<=DRAM_HIGH:outside=True
        if sample.get('monitor_error')is not None:unknown=True
    missing=sorted(required-set(points))
    if missing or any(not any(p==c+'-monitor'for p in points)for c in ('A','B')):unknown=True
    return dict(condition_met=False if outside else None if unknown else True,missing_points=missing,
                observed_points_only=True,continuous_guarantee=False,target_bytes=DRAM_LOW,
                band_bytes=[DRAM_LOW,DRAM_HIGH],outside_band=outside,unknown=unknown)


def validate_provider_lifecycle(value,expected):
    require(value['schema']=='T35-host-lifecycle/v1' and value['expected_sha256']==expected,'lifecycle binding')
    require(value['GPU']==0 and type(value['GPU'])is int and value['physical_io']is None,'host-only observation')
    require(value['destination_bytes']==2097152 and value['expected_ram_bytes']==2097152,'separate RAM allocations')
    require([a['arm']for a in value['arms']]==list('ACCA'),'prespecified ACCA')
    clean=True
    for arm in value['arms']:
        for key in ('chunk','lifecycles','buffer_capacity','logical_requested','logical_delivered','received','read_requested','direct_reads','buffered_reads','mapped_reads','errors','short_reads','unknown','overread_requested','outstanding','outstanding_bytes','peak_outstanding','peak_bytes','metadata_capacity'):uint(arm[key],key)
        require(arm['chunk']==arm['buffer_capacity']==65536,'identical 64KiB windows')
        require(arm['lifecycles']==(1 if arm['arm']=='C'else 32),'provider lifetime count')
        require(arm['logical_requested']==arm['logical_delivered']==arm['received']==2097152,'exact useful bytes')
        require(all(arm[k]==0 for k in ('errors','short_reads','unknown','overread_requested','outstanding','outstanding_bytes','mapped_reads')),'failure or incomplete drain')
        require(arm['peak_outstanding']==1 and 0<arm['peak_bytes']<=65536,'same outstanding capacity')
        require(arm['closed']is True and arm['exact_bytes']is True and arm['sha256']==expected,'raw bytes and terminal close')
        for key in ('host_lifecycle_seconds','enqueue_drain_seconds','construct_seconds','close_seconds'):require(finite(arm[key],key)>=0,'host elapsed nonnegative')
        require(arm['host_lifecycle_seconds']>=arm['enqueue_drain_seconds'],'elapsed scope')
        if arm['buffered_reads']or arm['direct_reads']==0:clean=False
        else:require(arm['direct_reads']==32 and arm['read_requested']==2097152,'same direct read operations')
    return dict(clean_comparison=clean,useful_bytes=8388608,physical_io=None,model_performance_qualified=False,
                explicit_ram_peak_bytes=4194304+max(a['buffer_capacity']+a['metadata_capacity']for a in value['arms']),
                scope='same 64KiB windows/4 workers/outstanding1; provider lifecycle only; process/OS overhead unknown')


class ProcessSession:
    """One explicitly launched benchmark-owned normal producer, no registry.

    The caller supplies a sealed actual command/env; no normal default is
    invented here. Stderr is retained, never printed with arbitrary env data.
    """
    def __init__(self,command,cwd,env):
        self.spawn_ns=time.perf_counter_ns();self.lines=queue.Queue();self.stderr=[];self.closed=False;self.request_index=0;self.all_events=[];self.ready_ns=None
        self.proc=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='strict',bufsize=1)
        def pump():
            try:
                for line in self.proc.stdout:self.lines.put(dict(line=line.rstrip('\r\n'),t_ns=time.perf_counter_ns()))
            except Exception as exc:self.lines.put(dict(line='ERR reader '+str(exc),t_ns=time.perf_counter_ns()))
            finally:self.lines.put(None)
        def errors():
            for line in self.proc.stderr:self.stderr.append(line)
        self.reader=threading.Thread(target=pump,daemon=True);self.errors=threading.Thread(target=errors,daemon=True);self.reader.start();self.errors.start()
        self.initial=[]
        try:
            while True:
                event=self.next();self.initial.append(event)
                if event['line'].startswith('INFO '):self.last_info=DTO.parse_frame(event['line'][5:])
                if event['line'].startswith('READY '):self.ready_ns=event['t_ns'];break
        except BaseException as original:
            try:self.close()
            except Exception as cleanup:original.add_note('benchmark child cleanup: '+str(cleanup))
            original.process_evidence=dict(events=self.all_events,stderr=self.stderr,exit_code=self.proc.poll())
            raise
    def next(self):
        value=self.lines.get()
        if value is None:raise ValueError('native EOF before expected terminal')
        self.all_events.append(value)
        if value['line'].startswith('ERR '):raise ValueError(value['line'])
        return value
    def send(self,line):
        require(type(line)is str and '\n' not in line and '\r' not in line,'single native command')
        self.proc.stdin.write(line+'\n');self.proc.stdin.flush()
    def info(self):
        self.send('INFO')
        event=self.next();require(event['line'].startswith('INFO '),'expected INFO');self.last_info=DTO.parse_frame(event['line'][5:]);return self.last_info
    def request(self,command,context,workload_identity):
        before=self.info();check_info(before);start=time.perf_counter_ns();self.send(command);events=[]
        while True:
            event=self.next();events.append(event)
            if event['line'].startswith('DONE '):break
        after=self.info();clock=time.get_clock_info('perf_counter')
        result=dict(context=context,workload_identity=workload_identity,process_id=self.proc.pid,request_index=self.request_index,clock_domain='perf_counter_ns',clock_resolution_ns=max(1,math.ceil(clock.resolution*1e9)),request_start_ns=start,events=events,info_before=before,info_after=after);self.request_index+=1;return result
    def close(self):
        if self.closed:return
        if self.proc.poll()is None:
            try:self.send('QUIT')
            except (BrokenPipeError,OSError):pass
        if not self.proc.stdin.closed:
            try:self.proc.stdin.close()
            except (BrokenPipeError,OSError):pass
        self.proc.wait();self.reader.join();self.errors.join()
        self.proc.stdout.close();self.proc.stderr.close();self.closed=True
        require(self.proc.returncode==0,'normal producer exit failed')
