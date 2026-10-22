"""CPU-first T35 recipe. GPU execution is explicit and needs sealed actual inputs.

No normal profile is written. Actual native/encoding/budget records must be sealed for each measurement.
CPU test success is never an eager performance result.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import threading
import ctypes
from ctypes import wintypes
import eager_bench as B

ROOT=B.ROOT;HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t35'
SOURCES=[HERE/x for x in ('eager_contract.json','eager_bench.py','test_eager_bench.py','build_verify.py')]
ENV_KEYS=('PATH','TMP','TEMP','SystemRoot','WINDIR','HIP_PATH','ROCM_PATH','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','GPU_DEVICE_ORDINAL','HIP_PLATFORM','STRATA_PAGEABLE_STAGING')
ACCEPTED_REFS={'T20':ROOT/'build-deepseek-t20/verification-final.json','T26':ROOT/'build-deepseek-t26/verification.json','T34':ROOT/'build-deepseek-t34/bundle/verification.json'}

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def row(path):return dict(path=str(Path(path).resolve()),sha256=sha(path))
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def bindings(rows):
    for r in rows:B.require(row(r['path'])==r,'changed binding: '+r['path'])
def cpu():
    BUILD.mkdir(exist_ok=True);before=[row(p) for p in SOURCES+[B._dto_path]]
    result=subprocess.run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s',str(HERE),'-p','test_eager_bench.py','-v'],capture_output=True,text=True,encoding='utf-8')
    (BUILD/'cpu-tests.log').write_text(result.stdout+result.stderr,encoding='utf-8');B.require(result.returncode==0,'CPU tests failed')
    bindings(before)
    proof=dict(schema='T35-CPU-preparation/v1',status='passed',sources=before,log=row(BUILD/'cpu-tests.log'),runtime=dict(executable=str(Path(sys.executable).resolve()),version=sys.version),red_log=row(BUILD/'tdd-red.log'),actual_GPU_runs=0,actual_performance_qualified=False,remaining=['T28 exact normal bundle/source/flags and encoding IDs','actual INFO schema/normal auto budget','sealed pilot and measured results','post-pilot paired contract','independent implementation review'])
    save(BUILD/'cpu-verification.json',proof);print(json.dumps(dict(CPU_status='passed',proof_sha256=sha(BUILD/'cpu-verification.json'),GPU=0)))

def stat_identity(path):
    st=Path(path).stat()
    return dict(device=st.st_dev,file_id=st.st_ino,bytes=st.st_size,mtime_ns=st.st_mtime_ns)

def physical_memory(pid,expected_birth=None):
    """Public Win32 counters only; commit and private working set are distinct."""
    class Status(ctypes.Structure):
        _fields_=[('dwLength',wintypes.DWORD),('dwMemoryLoad',wintypes.DWORD)]+[(n,ctypes.c_uint64)for n in ('total_physical','available_physical','total_pagefile','available_pagefile','total_virtual','available_virtual','extended_virtual')]
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t)for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage','PrivateWorkingSetSize')]+[('SharedCommitUsage',ctypes.c_uint64)]
    result=dict(pid=pid,t_ns=time.perf_counter_ns(),available_physical_bytes=None,working_set_bytes=None,private_working_set_bytes=None,private_commit_bytes=None,birth=None,identity_verified=None,global_status=False,process_status=False,global_error=None,process_error=None)
    start=result['t_ns']
    try:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
        kernel.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(Status)];kernel.GlobalMemoryStatusEx.restype=wintypes.BOOL
        status=Status();status.dwLength=ctypes.sizeof(status)
        result['global_status']=bool(kernel.GlobalMemoryStatusEx(ctypes.byref(status)))
        if result['global_status']:result['available_physical_bytes']=status.available_physical
        else:result['global_error']=ctypes.get_last_error()
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.OpenProcess(0x410,False,pid)
        if not handle:result['process_error']=ctypes.get_last_error()
        else:
            try:
                times=[wintypes.FILETIME()for _ in range(4)]
                kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4;kernel.GetProcessTimes.restype=wintypes.BOOL
                if kernel.GetProcessTimes(handle,*[ctypes.byref(t)for t in times]):
                    birth=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
                    result['birth']=birth;result['identity_verified']=expected_birth is None or birth==expected_birth
                else:result['process_error']=ctypes.get_last_error()
                psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD];psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
                counters=Counters();counters.cb=ctypes.sizeof(counters)
                result['process_status']=bool(psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb))
                if result['process_status']:
                    result.update(working_set_bytes=counters.WorkingSetSize,private_working_set_bytes=counters.PrivateWorkingSetSize,private_commit_bytes=counters.PrivateUsage)
                else:result['process_error']=ctypes.get_last_error()
            finally:kernel.CloseHandle(handle)
    except (AttributeError,OSError)as error:result['process_error']=str(error)
    result['observation_elapsed_ns']=time.perf_counter_ns()-start
    return result

def runtime_snapshot(config,info=None):
    bindings([config['normal_bundle_manifest']]);native=read(config['normal_bundle_manifest']['path']);bindings([dict(path=r['path'],sha256=r['sha256'])for r in native['bindings']])
    models=config['model_identity'];B.require(type(models)is list and len(models)==9 and len({r['path']for r in models})==9,'nine original model identities required')
    for record in models:
        B.require(stat_identity(record['path'])==record['identity'],'original model metadata changed: '+record['path'])
    declared=config['owned_runtime_modules'];B.require(set(declared)=={'amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'},'owned runtime modules declaration')
    bindings(list(declared.values()));observed=(info or{}).get('loaded_runtime_modules')or{};loaded={}
    for name,record in declared.items():
        actual=observed.get(name)
        if actual is not None:
            B.require(type(actual)is str and Path(actual).resolve()==Path(record['path']).resolve(),'loaded owned DLL path changed: '+name)
            B.require(row(actual)==record,'loaded owned DLL bytes changed: '+name)
        loaded[name]=dict(observed_path=actual,verified=None if actual is None else True,declared=record)
    return dict(native_binding_count=len(native['bindings']),model_metadata=models,loaded_modules=loaded,loaded_modules_complete=True if all(r['verified']is True for r in loaded.values())else None)

def validate_input(config):
    B.require(config.get('schema')=='T35-actual-execution-input/v1','execution input schema')
    B.require(config.get('phase')in('pilot','measurement'),'explicit measurement phase')
    command=config['command'];B.require(type(command)is list and len(command)>2 and all(type(x)is str and x for x in command),'actual native command')
    B.require(command.count('--serve')==1,'actual normal producer --serve required')
    executable=Path(command[0]);B.require(executable.is_file() and config['executable']==row(executable),'actual binary binding')
    ids=config['prompt_ids'];B.require(type(ids)is list and ids and all(type(x)is int and 0<=x<129280 for x in ids),'actual original prompt IDs')
    B.require(config['implicit_BOS'] is False,'do not insert implicit BOS')
    maximum=B.positive(config['maximum_new_tokens'],'fixture output reservation');context=B.positive(config['context'],'selected context')
    B.require(context<=1048576 and len(ids)+maximum<=context,'actual prompt plus generation context')
    def option(name):
        B.require(command.count(name)==1,'missing/duplicate native option '+name);i=command.index(name);B.require(i+1<len(command),'native option value');return command[i+1]
    B.require(option('--context')==str(context) and option('--bundle-id')==config['bundle_id'] and option('--runtime-epoch')==str(config['runtime_epoch']),'launch/source context binding')
    B.DTO.context(dict(request_id='seal-only',runtime_epoch=config['runtime_epoch'],bundle_id=config['bundle_id'],asset_revision=B.DTO.REVISION,model_family='deepseek41',tokenizer_identity=B.DTO.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280))
    # These are a declared measurement workload, not new normal restrictions.
    sampling=config['sampling'];B.require(sampling==dict(temperature=0,seed=0,top_k=0,top_p=1,min_p=0,logprobs=False),'eager baseline sampling contract')
    B.require(type(sampling['seed'])is int and type(sampling['top_k'])is int and type(sampling['logprobs'])is bool and all(type(sampling[k])in(int,float) for k in ('temperature','top_p','min_p')),'sampling declaration strict types')
    B.require(config['flags']==dict(graph=False,dspark=False,secondary=False) and all(type(x)is bool for x in config['flags'].values()),'eager primary flags scope')
    refs=config['qualification_refs'];B.require(type(refs)is dict and set(refs)==set(ACCEPTED_REFS)|{'normal'},'named applicable T20/T26/T34/normal evidence')
    for name,path in ACCEPTED_REFS.items():B.require(refs[name]==row(path),'accepted component receipt changed: '+name)
    bindings(list(refs.values())+[config['prompt_encoding_evidence'],config['normal_bundle_manifest']])
    encoding=read(config['prompt_encoding_evidence']['path']);B.require(encoding['raw_prompt_ids']==ids and encoding['input_count']==len(ids) and encoding['context']==context and encoding['reserved_generated_tokens']==maximum and encoding['implicit_BOS'] is False,'original encoding evidence does not describe selected workload')
    B.require(encoding['contract']==row(HERE/'eager_contract.json'),'encoding contract drift');bindings([encoding['contract'],encoding['tokenizer'],encoding['recipe_module']])
    native=read(config['normal_bundle_manifest']['path']);B.require(type(native.get('bindings'))is list,'actual consumed normal bundle bindings')
    B.require(any(Path(r['path']).resolve()==executable.resolve() and r['sha256']==config['executable']['sha256'] for r in native['bindings']),'normal manifest does not bind selected executable')
    bindings([dict(path=r['path'],sha256=r['sha256'])for r in native['bindings']])
    B.require(type(config['environment'])is dict and set(config['environment'])<=set(ENV_KEYS) and all(type(v)is str for v in config['environment'].values()),'nonsecret runtime environment keys only')
    B.require(Path(config['cwd']).is_dir(),'actual working directory')
    if config['phase']=='measurement':
        m=config['measurement_contract'];B.require(m['pair_count']==3 and type(m['pair_count'])is int and m['order']==['AB']*3,'prespecified paired schedule')
        B.require(m['CI']=='paired-log-t95-df2' and m['primary_metrics']==['TTFT_pipe_seconds','aggregate_TPOT_pipe_seconds'],'prespecified metrics/CI')
        B.require(0<B.finite(m['relative_precision_band'],'precision band')<1,'precision band, not a TPS SLO')
        bindings([m['pilot_receipt'],m['pre']])
        B.require(m['relative_precision_band']==0.20,'prespecified report precision')
        B.require(config['dram_condition']==dict(target_bytes=B.DRAM_LOW,band_bytes=[B.DRAM_LOW,B.DRAM_HIGH],aim_bytes=B.DRAM_AIM,maximum_candidate_constructions=1,monitor_interval_seconds=10,target_is_report_only=True),'prespecified DRAM condition')
        B.require(config.get('measurement_variant')=='approx-8g-r1','finite formal output variant')
        B.require(option('--device-cache-payload-bytes')=='auto' and option('--ram-cache-payload-bytes')=='auto','normal device auto with test-only RAM selection')
    return config

def measurement_root(config):
    if config['phase']=='pilot':return BUILD
    B.require(config.get('measurement_variant')=='approx-8g-r1','finite formal variant')
    return BUILD/'approx-8g-r1'


def seal(path):
    config=validate_input(read(path));runtime_snapshot(config);env=os.environ.copy();env.update(config['environment'])
    before=[row(p) for p in SOURCES+[B._dto_path]]
    clock=time.get_clock_info('perf_counter');B.require(clock.monotonic and not clock.adjustable and clock.resolution>0,'monotonic clock')
    base=measurement_root(config);base.mkdir(exist_ok=True);archive=base/(config['phase']+'-source');B.require(not archive.exists(),'preserve prior phase source snapshot');archive.mkdir()
    mapping=[]
    for record in before:
        original=Path(record['path']);snapshot=archive/original.relative_to(ROOT);snapshot.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,snapshot);B.require(sha(snapshot)==record['sha256'],'snapshot changed during copy');mapping.append(dict(original=record,snapshot=row(snapshot)))
    input_snapshot=archive/'execution-input.json';shutil.copyfile(path,input_snapshot);bindings(before)
    value=dict(schema='T35-execution-seal/v1',input=config,input_file=row(path),input_snapshot=row(input_snapshot),sources=before,source_snapshots=mapping,interpreter=row(sys.executable),python_version=sys.version,environment={k:env[k] for k in ENV_KEYS if k in env},clock=dict(domain='perf_counter_ns',implementation=clock.implementation,resolution=clock.resolution),phase=config['phase'])
    target=base/(config['phase']+'-seal.json');B.require(not target.exists(),'existing phase seal is immutable');save(target,value);print(json.dumps(dict(seal=str(target),sha256=sha(target))))

def ram_command(config,payload):
    command=list(config['command']);name='--ram-cache-payload-bytes'
    B.require(command.count(name)==1,'unique RAM option')
    B.natural(payload,'explicit RAM payload');B.require(payload>0,'positive RAM payload')
    command[command.index(name)+1]=str(payload)
    return command


def sample_memory(session,point,birth=None):
    value=physical_memory(session.proc.pid,birth);value['point']=point
    return value


def select_owner(config,env,out):
    command=config['command'];B.require(command.count('--tile-bytes')==1,'selected weight tile')
    tile=int(command[command.index('--tile-bytes')+1]);minimum=tile+264
    payload=minimum;selection=[];session=None
    # Minimum calibration, then one checked candidate; physical band is report-only.
    try:
        for index in range(2):
            session=B.ProcessSession(ram_command(config,payload),config['cwd'],env)
            info=session.info();closure=runtime_snapshot(config,info);sample=sample_memory(session,'constructed')
            slots=B.explicit_ram_slots(payload,tile)
            B.require(info['ram_slots']==info['row_ram_slots']==slots['weight'] and info['ram_cache_payload_bytes']==slots['payload_bytes'],'actual explicit equal-slot budget')
            entry=dict(index=index,command=ram_command(config,payload),declared_ram_payload_bytes=payload,actual_slots=slots,info=info,closure=closure,memory=sample,GEN_count=0,valid_model_payload_bytes=None)
            selection.append(entry);save(out/'owner-selection.json',selection)
            B.require(sample['identity_verified']is True,'owner process identity unavailable')
            available=sample['available_physical_bytes']
            if index==1 or available is None or B.DRAM_LOW<=available<=B.DRAM_HIGH:
                entry['allocation_reason']='candidate_selected'if index else 'available_unknown_keep_minimum'if available is None else 'minimum_near_target'
                save(out/'owner-selection.json',selection);return session,selection,sample
            # Deferred sampling vectors are not allocated until GEN. Metadata
            # already in Fcurrent is never subtracted a second time.
            deferred=B.natural(info['deferred_host_sampling'],'unallocated host sampling')
            candidate=B.select_ram_payload(available,slots['payload_bytes'],minimum,deferred)
            session.close();entry['closed_exit']=session.proc.returncode;session=None
            save(out/'owner-selection.json',selection);payload=candidate
    except BaseException as primary:
        if session is not None:
            try:session.close()
            except Exception as cleanup:primary.add_note('calibration cleanup: '+str(cleanup))
        save(out/'owner-selection.json',selection)
        raise


def measured_request(session,command,context,wid,condition,birth,samples,out,monitor_interval_seconds=10):
    def failed(point,error):
        return dict(point=point,pid=session.proc.pid,birth=birth,t_ns=time.perf_counter_ns(),identity_verified=None,
                    global_status=False,available_physical_bytes=None,process_status=False,
                    working_set_bytes=None,private_working_set_bytes=None,private_commit_bytes=None,monitor_error=str(error))
    samples.append(sample_memory(session,condition+'-before',birth));save(out/'memory.json',samples)
    B.require(samples[-1]['identity_verified']is True,'before-GEN owner identity unavailable')
    stop=threading.Event()
    def monitor():
        while not stop.wait(monitor_interval_seconds):
            try:
                samples.append(sample_memory(session,condition+'-monitor',birth));save(out/'memory.json',samples)
            except Exception as error:
                # Retain the failed observation even if a prior monitor passed.
                # The main thread saves it after join; never omit it as success.
                samples.append(failed(condition+'-monitor',error));break
    worker=threading.Thread(target=monitor,daemon=True);worker.start();request_error=None
    try:return session.request(command,context,wid)
    except BaseException as error:request_error=error;raise
    finally:
        stop.set();worker.join()
        try:samples.append(sample_memory(session,condition+'-after',birth))
        except Exception as error:samples.append(failed(condition+'-after',error))
        try:save(out/'memory.json',samples)
        except Exception as logging:
            if request_error is not None:request_error.add_note('memory capture save: '+str(logging))
            else:raise


def execute_measurement(seal_path,pair):
    sealed=read(seal_path);config=validate_input(sealed['input'])
    B.require(config['phase']=='measurement' and type(pair)is int and 0<=pair<3,'explicit formal pair index')
    bindings(sealed['sources']+[sealed['input_file'],sealed['interpreter']]);B.require(sealed['interpreter']==row(sys.executable) and sealed['python_version']==sys.version,'measurement interpreter')
    env=os.environ.copy();env.update(config['environment']);B.require({k:env[k]for k in ENV_KEYS if k in env}==sealed['environment'],'runtime environment drift')
    out=measurement_root(config)/'measurement-run'/f'pair-{pair}';out.mkdir(parents=True,exist_ok=False)
    before=runtime_snapshot(config);session=None;captures=[];samples=[];during=[]
    workload={k:config[k]for k in ('prompt_ids','sampling','maximum_new_tokens','context','flags')};wid=hashlib.sha256(json.dumps(workload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    try:
        session,selection,constructed=select_owner(config,env,out);birth=constructed['birth'];samples.append(constructed)
        # This selected input is fixed on disk before the first GEN.
        selected=dict(seal=row(seal_path),pair=pair,final_owner=selection[-1],workload_identity=wid,source=sealed['sources'],formal_GEN_started=False)
        save(out/'selected-input.json',selected)
        for condition in ('A','B'):
            rid=f't35-measurement-{pair}-{condition}'
            context=dict(request_id=rid,runtime_epoch=config['runtime_epoch'],bundle_id=config['bundle_id'],asset_revision=B.DTO.REVISION,model_family='deepseek41',tokenizer_identity=B.DTO.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)
            command='GEN '+str(config['maximum_new_tokens'])+' request_id='+rid+' epoch='+str(config['runtime_epoch'])+' temperature=0 top_k=0 top_p=1 min_p=0 seed=0 logprobs=0 '+','.join(map(str,config['prompt_ids']))
            capture=measured_request(session,command,context,wid,condition,birth,samples,out);save(out/(condition+'.json'),capture);captures.append(capture)
            during.append(dict(condition=condition,before=runtime_snapshot(config,capture['info_before']),after=runtime_snapshot(config,capture['info_after'])))
        analysis=B.analyze_pair(*captures);memory=B.memory_condition(samples)
    except BaseException as primary:
        if session is not None:
            try:session.close()
            except Exception as cleanup:primary.add_note('measurement cleanup: '+str(cleanup))
        save(out/'failure.json',dict(error=str(primary),notes=getattr(primary,'__notes__',[]),samples=samples,seal=row(seal_path),performance_qualified=False,exit_code=None if session is None else session.proc.poll()))
        raise
    else:
        session.close();save(out/'closed.json',dict(pid=session.proc.pid,birth=birth,exit_code=session.proc.returncode,closed=session.closed))
        (out/'stderr.log').write_text(''.join(session.stderr),encoding='utf-8')
    bindings(sealed['sources']+[sealed['input_file']]);after=runtime_snapshot(config)
    proof=dict(schema='T35-formal-pair/v1',pair_index=pair,seal=row(seal_path),selected_input=row(out/'selected-input.json'),selection=row(out/'owner-selection.json'),memory_capture=row(out/'memory.json'),memory_condition=memory,DRAM_target_is_report_only=True,analysis=analysis,raw_captures=[row(out/(c+'.json'))for c in ('A','B')],closed=row(out/'closed.json'),stderr=row(out/'stderr.log'),runtime_before=before,runtime_during=during,runtime_after=after,source_before_after_unchanged=True,normal_profile_modified=False,physical_cold_qualified=False,performance_qualified=False)
    save(out/'verification.json',proof);print(json.dumps(row(out/'verification.json')))


def validate_formal_pair(proof,config,seal_record):
    pair=proof['pair_index'];B.require(type(pair)is int and 0<=pair<3,'strict formal pair index')
    selected=read(proof['selected_input']['path']);B.require(type(selected.get('pair'))is int and selected['pair']==pair and selected['seal']==seal_record,'selected input pair/seal')
    workload={k:config[k]for k in ('prompt_ids','sampling','maximum_new_tokens','context','flags')}
    wid=hashlib.sha256(json.dumps(workload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    B.require(selected['workload_identity']==wid,'selected workload identity')
    final=selected['final_owner'];payload=final['declared_ram_payload_bytes']
    B.require(final['command']==ram_command(config,payload),'selected RAM-only command override')
    command=config['command'];B.require(command.count('--tile-bytes')==1,'selected tile option')
    slots=B.explicit_ram_slots(payload,int(command[command.index('--tile-bytes')+1]))
    B.require(final['actual_slots']==slots,'selected explicit slot accounting')
    initial=final['info'];B.require(initial['ram_slots']==initial['row_ram_slots']==slots['weight']and initial['ram_cache_payload_bytes']==slots['payload_bytes'],'selected actual RAM owner')
    identity=final['memory'];pid=identity['pid'];birth=identity['birth'];B.require(type(pid)is int and pid>0 and type(birth)is int and birth>0,'selected exact native identity')
    memory=read(proof['memory_capture']['path']);B.require(memory and memory[0]==identity,'selected constructed memory binding')
    B.memory_condition(memory)
    for sample in memory:B.require(sample['pid']==pid and sample['birth']==birth,'memory/selected owner identity')
    raw=[read(r['path'])for r in proof['raw_captures']];B.require(len(raw)==2,'formal AB captures')
    B.require(initial.get('context')==config['context'] and type(initial.get('context'))is int,'selected context')
    budget_fields=(*B.BUDGET,'context','cache_unused_ram_bytes','mandatory_measurement_device','deferred_constant_device','deferred_host_sampling')
    for condition,capture in zip(('A','B'),raw,strict=True):
        expected=dict(request_id=f't35-measurement-{pair}-{condition}',runtime_epoch=config['runtime_epoch'],bundle_id=config['bundle_id'],asset_revision=B.DTO.REVISION,model_family='deepseek41',tokenizer_identity=B.DTO.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)
        B.require(capture['context']==expected and capture['workload_identity']==wid,'formal context/workload binding')
        B.require(type(capture['process_id'])is int and capture['process_id']==pid,'raw/selected owner PID')
        B.require(B.analyze_run(capture)['generated_count']<=config['maximum_new_tokens'],'formal output reservation')
        for info in (capture['info_before'],capture['info_after']):
            for key in budget_fields:B.require(type(info.get(key))is int and type(initial.get(key))is int and info[key]==initial[key],'selected actual budget '+key)
    closed=read(proof['closed']['path']);B.require(closed['pid']==pid and type(closed['pid'])is int and closed['birth']==birth and type(closed['birth'])is int,'closed/selected owner identity')
    B.require(closed['closed']is True and type(closed['exit_code'])is int and closed['exit_code']==0,'normal exact owner close')
    return pid,birth


def aggregate_measurement(seal_path):
    sealed=read(seal_path);config=validate_input(sealed['input']);B.require(config['phase']=='measurement','formal aggregate phase')
    bindings(sealed['sources']+[sealed['input_file']]);proofs=[];records=[];identities=set()
    for pair in range(3):
        folder=measurement_root(config)/'measurement-run'/f'pair-{pair}';proof=read(folder/'verification.json')
        B.require(type(proof['pair_index'])is int and proof['pair_index']==pair and proof['seal']==row(seal_path),'pair index/seal')
        bindings(proof['raw_captures']+[proof[k]for k in ('selected_input','selection','memory_capture','closed','stderr')])
        B.require(B.analyze_pair(read(folder/'A.json'),read(folder/'B.json'))==proof['analysis'],'formal pair replay')
        B.require(B.memory_condition(read(folder/'memory.json'))==proof['memory_condition'],'memory replay')
        identity=validate_formal_pair(proof,config,row(seal_path))
        B.require(identity not in identities,'formal pairs require fresh owner identities');identities.add(identity)
        proofs.append(proof);records.append(row(folder/'verification.json'))
    conditions,intervals=formal_intervals(B,proofs)
    value=dict(schema='T35-formal-aggregate/v1',seal=row(seal_path),pairs=records,intervals=intervals,DRAM_observed_condition_met=conditions,DRAM_target_is_report_only=True,pilot_excluded=True,completion='independent_review_pending',performance_qualified=False,normal_profile_modified=False)
    target=measurement_root(config)/'measurement-run/verification.json';B.require(not target.exists(),'preserve formal aggregate');save(target,value);print(json.dumps(row(target)))


def execute(seal_path,pair_index=None):
    if read(seal_path)["input"]["phase"]=="measurement":return execute_measurement(seal_path,pair_index)
    sealed=read(seal_path);config=validate_input(sealed['input']);bindings(sealed['sources']+[sealed['input_file'],sealed['interpreter']]);B.require(sealed['interpreter']==row(sys.executable) and sealed['python_version']==sys.version,'benchmark interpreter changed');env=os.environ.copy();env.update(config['environment'])
    B.require({k:env[k] for k in ENV_KEYS if k in env}==sealed['environment'],'runtime environment drift')
    runtime_before=runtime_snapshot(config)
    phase=config['phase'];out=BUILD/(phase+'-run');B.require(not out.exists(),'preserve existing actual attempt');out.mkdir()
    # Only pairs prescribed by the pre-G seal are executed. Pilot does not
    # silently turn into a performance measurement or tune an existing seal.
    pairs=1 if phase=='pilot' else config['measurement_contract']['pair_count'];results=[];runtime_during=[]
    workload=dict(prompt_ids=config['prompt_ids'],sampling=config['sampling'],maximum_new_tokens=config['maximum_new_tokens'],context=config['context'],flags=config['flags'])
    wid=hashlib.sha256(json.dumps(workload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for pair in range(pairs):
        session=None;captures=[]
        try:
            session=B.ProcessSession(config['command'],config['cwd'],env)
            for condition in ('A','B'):
                rid=f't35-{phase}-{pair}-{condition}';context=dict(request_id=rid,runtime_epoch=config['runtime_epoch'],bundle_id=config['bundle_id'],asset_revision=B.DTO.REVISION,model_family='deepseek41',tokenizer_identity=B.DTO.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)
                command='GEN '+str(config['maximum_new_tokens'])+' request_id='+rid+' epoch='+str(config['runtime_epoch'])+' temperature=0 top_k=0 top_p=1 min_p=0 seed=0 logprobs=0 '+','.join(map(str,config['prompt_ids']))
                capture=session.request(command,context,wid);save(out/f'pair-{pair}-{condition}.json',capture);captures.append(capture)
                runtime_during.append(dict(pair=pair,condition=condition,before=runtime_snapshot(config,capture['info_before']),after=runtime_snapshot(config,capture['info_after'])))
            results.append(B.analyze_pair(*captures))
        except BaseException as primary:
            evidence=getattr(primary,'process_evidence',{})
            if session is not None:
                try:session.close()
                except Exception as cleanup:primary.add_note('benchmark cleanup: '+str(cleanup))
                evidence=dict(events=session.all_events,stderr=session.stderr,exit_code=session.proc.poll())
            try:save(out/f'pair-{pair}-failure.json',dict(error=str(primary),notes=getattr(primary,'__notes__',[]),process=evidence,seal=row(seal_path),performance_qualified=False))
            except Exception as logging:primary.add_note('failure record could not be written: '+str(logging))
            raise
        else:
            session.close();(out/f'pair-{pair}-stderr.log').write_text(''.join(session.stderr),encoding='utf-8');save(out/f'pair-{pair}-startup.json',dict(spawn_ns=session.spawn_ns,ready_ns=session.ready_ns,initial=session.initial,process_id=session.proc.pid))
    bindings(sealed['sources']+[sealed['input_file']]);runtime_after=runtime_snapshot(config);interval={}
    if phase=='measurement':
        for metric in ('TTFT_pipe_seconds','aggregate_TPOT_pipe_seconds'):
            values=[p['ratios'][metric]['value'] for p in results]
            interval[metric]=B.paired_interval(values) if all(v is not None for v in values) else dict(value=None,reason='one_or_more_pair_metrics_unknown',effect='unjudged')
    proof=dict(runtime_before=runtime_before,runtime_during=runtime_during,runtime_after=runtime_after,schema='T35-actual-eager-receipt/v1',phase=phase,seal=row(seal_path),pairs=results,intervals=interval,raw_captures=[row(p) for p in sorted(out.glob('pair-*-A.json'))+sorted(out.glob('pair-*-B.json'))],source_before_after_unchanged=True,physical_cold_qualified=False,normal_profile_modified=False,completion='pilot_only' if phase=='pilot' else 'independent_review_pending')
    save(out/'verification.json',proof);print(json.dumps(dict(actual_phase=phase,receipt=row(out/'verification.json'))))

def formal_intervals(analyzer,proofs):
    B.require(len(proofs)==3,'three formal pairs required')
    flags=[p['memory_condition']['condition_met']for p in proofs]
    conditions=False if any(x is False for x in flags)else None if any(x is not True for x in flags)else True
    intervals={}
    for metric in ('TTFT_pipe_seconds','aggregate_TPOT_pipe_seconds'):
        values=[p['analysis']['ratios'][metric]['value']for p in proofs]
        intervals[metric]=analyzer.paired_interval(values,expected_count=3)if all(v is not None for v in values)else dict(value=None,effect='unjudged',reason='one_or_more_pair_metrics_unknown')
    return conditions,intervals


def replay_formal(directory,proof):
    bindings([proof['seal']]+proof['pairs']);sealed=read(proof['seal']['path'])
    bindings([r['snapshot']for r in sealed['source_snapshots']]+[sealed['input_snapshot']])
    original=next(r['snapshot']['path']for r in sealed['source_snapshots']if Path(r['original']['path']).name=='eager_bench.py')
    spec=importlib.util.spec_from_file_location('t35_formal_captured_analyzer',original);analyzer=importlib.util.module_from_spec(spec);spec.loader.exec_module(analyzer)
    B.require(len(proof['pairs'])==3,'prespecified complete formal replay')
    values=[];identities=set()
    for i,record in enumerate(proof['pairs']):
        pair=read(record['path']);B.require(type(pair['pair_index'])is int and pair['pair_index']==i and pair['seal']==proof['seal'],'formal replay pair order/seal')
        bindings(pair['raw_captures']+[pair[k]for k in ('selected_input','selection','memory_capture','closed','stderr')])
        raw=[read(r['path'])for r in pair['raw_captures']];B.require(len(raw)==2,'AB raw pair')
        B.require(analyzer.analyze_pair(*raw)==pair['analysis'],'formal raw analyzer replay')
        B.require(analyzer.memory_condition(read(pair['memory_capture']['path']))==pair['memory_condition'],'formal physical sample replay')
        identity=validate_formal_pair(pair,sealed['input'],proof['seal'])
        B.require(identity not in identities,'formal replay requires fresh owners');identities.add(identity)
        values.append(pair)
    conditions,intervals=formal_intervals(analyzer,values)
    B.require(conditions==proof['DRAM_observed_condition_met'] and intervals==proof['intervals'],'formal CI/condition replay')
    return dict(CPU_replay='passed',receipt=row(directory/'verification.json'),captured_analyzer=row(original),current_replay_wrapper=row(__file__),GPU=0)


def replay(directory):
    proof=read(directory/'verification.json')
    if proof.get('schema')=='T35-formal-aggregate/v1':return replay_formal(directory,proof)
    bindings(proof['raw_captures']+[proof['seal']]);sealed=read(proof['seal']['path']);bindings([r['snapshot']for r in sealed['source_snapshots']]+[sealed['input_snapshot']])
    # Pilot and measurement may use different revisions of this test adapter.
    # Replay each capture with its exact archived pure analyzer/DTO, while the
    # present wrapper is separately identified. No model payload is rehashed.
    original=next(r['snapshot']['path']for r in sealed['source_snapshots']if Path(r['original']['path']).name=='eager_bench.py');spec=importlib.util.spec_from_file_location('t35_captured_analyzer',original);analyzer=importlib.util.module_from_spec(spec);spec.loader.exec_module(analyzer)
    count=1 if proof['phase']=='pilot' else 5
    pairs=[analyzer.analyze_pair(read(directory/f'pair-{i}-A.json'),read(directory/f'pair-{i}-B.json'))for i in range(count)]
    B.require(pairs==proof['pairs'],'raw-clock/ID/counter replay differs from proof')
    intervals={}
    if proof['phase']=='measurement':
        for metric in ('TTFT_pipe_seconds','aggregate_TPOT_pipe_seconds'):
            values=[p['ratios'][metric]['value'] for p in pairs]
            intervals[metric]=analyzer.paired_interval(values) if all(v is not None for v in values) else dict(value=None,reason='one_or_more_pair_metrics_unknown',effect='unjudged')
    B.require(intervals==proof['intervals'],'paired interval replay differs')
    return dict(CPU_replay='passed',receipt=row(directory/'verification.json'),captured_analyzer=row(original),current_replay_wrapper=row(__file__),GPU=0)

def validate_host_io(value,expected):
    B.require(value['schema']=='T35-host-io/v1' and value['expected_sha256']==expected,'host IO binding')
    B.require(value['physical_io'] is None and type(value['GPU'])is int and value['GPU']==0,'host scope/physical unknown')
    B.require(value['destination_bytes']==2097152 and value['expected_ram_bytes']==2097152,'separate RAM allocations')
    B.require([a['arm']for a in value['arms']]==list('ABBA'),'prespecified AB/BA schedule')
    clean=True
    counters=('chunk','lifecycles','logical_requested','logical_delivered','read_requested','received','direct_reads','buffered_reads','mapped_reads','errors','short_reads','unknown','overread_requested','outstanding','outstanding_bytes','peak_outstanding','peak_bytes','buffer_capacity','metadata_capacity')
    for a in value['arms']:
        B.require(all(type(a[k])is int and a[k]>=0 for k in counters),'strict actual counters')
        chunk=65536 if a['arm']=='A' else 2097152;count=2097152//chunk
        B.require(a['chunk']==a['buffer_capacity']==chunk and a['lifecycles']==count,'actual finite windows')
        B.require(a['logical_requested']==a['logical_delivered']==a['received']==2097152,'complete useful read')
        B.require(all(a[k]==0 for k in ('errors','short_reads','unknown','overread_requested','outstanding','outstanding_bytes','mapped_reads')),'read failure/drain')
        B.require(a['peak_outstanding']==1 and a['peak_bytes']<=chunk and a['peak_bytes']>0,'outstanding gauge scope')
        B.require(a['exact_bytes'] is True and a['sha256']==expected and a['closed'] is True,'raw bytes/hash/close')
        for k in ('host_lifecycle_seconds','enqueue_drain_seconds'):B.require(B.finite(a[k],k)>=0,'host clock')
        B.require(a['host_lifecycle_seconds']>=a['enqueue_drain_seconds'],'clock scope')
        if a['buffered_reads'] or a['direct_reads']==0:clean=False
        else:B.require(a['direct_reads']==count and a['read_requested']==2097152,'clean data operations')
    return dict(clean_pair=clean,physical_io=None,model_performance_qualified=False,useful_ABBA_bytes=8388608,
                explicit_ram_peak_bytes=4194304+max(a['buffer_capacity']+a['metadata_capacity']for a in value['arms']),
                explicit_ram_scope='expected 2MiB + destination 2MiB + actual aligned buffer + provider metadata; process heap/OS/DirectFile internals unknown')

def validate_key_lookup(value,expected):
    B.require(value['schema']=='T35-key-lookup/v1' and value['key_hex']==expected,'key binding')
    for name in ('original_weight_read_bytes','GPU'):
        B.require(type(value[name])is int and value[name]==0,'metadata-only scope')
    B.require(value['physical_io']is None and value['model_performance_qualified']is False,'unknown physical/model scope')
    rows=value['cases'];B.require(type(rows)is list and len(rows)==120,'complete lookup schedule')
    cursor=0
    for ram,counts in ((False,(2,7745)),(True,(2,8768,15262))):
        for count in counts:
            for kind in ('cold','first','middle','last','miss','blocked'):
                index={'first':0,'middle':count//2,'last':count-1,'blocked':1}.get(kind,-1)
                comparisons=(index+1 if index>=0 else count)-(1 if ram and kind=='blocked' else 0)
                if ram and kind=='cold':comparisons=0
                for arm in 'ABBA':
                    r=rows[cursor];cursor+=1
                    B.require(type(r['ram'])is bool and r['ram']==ram and type(r['slots'])is int and r['slots']==count and r['kind']==kind and r['arm']==arm,'lookup case/order')
                    for key,wanted in (('index',index),('comparisons',comparisons),('key_calls',1 if arm=='B'else comparisons)):
                        B.require(type(r[key])is int and r[key]==wanted,'lookup '+key)
                    B.require(type(r['elapsed_ns'])is int and r['elapsed_ns']>=0,'host elapsed clock')
    return dict(cases=30,arms=120,key_bytes=len(bytes.fromhex(expected)),original_read=0,GPU=0,model_performance_qualified=False)


def key_lookup_build():
    number=1
    while (BUILD/f'key-metadata-ab-{number}').exists():number+=1
    folder=BUILD/f'key-metadata-ab-{number}';folder.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('t35_key_toolchain',HERE.parent/'io/build_verify.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    old.BUILD=folder;tools,env=old.environment()
    baseline=BUILD/'key-hoist-source/primary_supply-before.hip';after=BUILD/'key-hoist-source/primary_supply-after.hip'
    pattern=rb'std::string SupplyMatrix::key\(\)const \{\r?\n.*?\r?\n\}'
    definitions=[re.findall(pattern,p.read_bytes(),re.S)for p in (baseline,after)]
    B.require(all(len(x)==1 for x in definitions)and definitions[0]==definitions[1],'actual key definition changed')
    index=ROOT/'build-deepseek-t10/offline-index.tsv';fields=index.read_text(encoding='utf-8').splitlines()[0].split('\t')
    count=min(256,int(fields[7]));matrix=dict(revision=fields[-1],lfs=fields[-2],path=fields[-4],name=fields[1],type=int(fields[2]),rows=count,k=int(fields[6]),offset=int(fields[3]),bytes=count*int(fields[5]))
    names=('revision','lfs','path','name','type','rows','k','offset','bytes')
    expected=lambda m:'|'.join(str(m[k])for k in names)
    q=dict(schema='T35-immutable-key-Q/v1',matrix=matrix,expected=expected(matrix),schedule='ABBA',device_slots=[2,7745],ram_slots=[2,8768,15262],kinds=['cold','first','middle','last','miss','blocked'],lookups_per_arm=1,weight_read_bytes=0,GPU=0)
    save(folder/'Q.json',q)
    headers=[];todo=[ROOT/'Strata-extensions/native/cache/primary_supply.hpp']
    while todo:
        p=todo.pop().resolve()
        if p in headers:continue
        headers.append(p)
        for inc in re.findall(r'^#include "([^"]+)"',p.read_text(encoding='utf-8'),re.M):
            selected=(p.parent/inc).resolve()
            if not selected.exists():
                candidates=list((ROOT/'Strata-extensions/native').rglob(inc));B.require(len(candidates)==1,'ambiguous header dependency');selected=candidates[0]
            todo.append(selected)
    paths=[*headers,HERE/'key_lookup_fixture.cpp',baseline,after,index,Path(__file__),HERE/'test_eager_bench.py',HERE/'eager_contract.json',BUILD/'key-hoist-pre-r1.md']
    before=[row(p)for p in paths];snapshot=folder/'source';mapping=[]
    for p,r in zip(paths,before,strict=True):
        target=snapshot/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        B.require(sha(target)==r['sha256'],'metadata source changed');mapping.append(dict(original=r,snapshot=row(target)))
    (folder/'key-definition.inc').write_bytes(b'namespace strata_ext::cache {\n'+definitions[0][0]+b'\n}\n')
    literal=lambda x:json.dumps(x,ensure_ascii=False)
    assignments={'revision':'m.original.source.revision','lfs':'m.original.source.lfs_sha256','path':'m.original.source.original_path','name':'m.original.span.name',**{x:'m.'+x for x in ('type','rows','k','offset','bytes')}}
    def setter(k,v):
        value='std::filesystem::u8path(u8'+literal(v)+')'if k=='path'else 'u8'+literal(v)if isinstance(v,str)else str(v)
        return assignments[k]+'='+value+';'
    header='strata_ext::cache::SupplyMatrix metadata_matrix(){strata_ext::cache::SupplyMatrix m;'+''.join(setter(k,matrix[k])for k in names)+'return m;}\n'
    header+='const char*metadata_key_hex(){return "'+expected(matrix).encode().hex()+'";}\nvoid metadata_check(){\n'
    for key in names:
        variant=dict(matrix);variant[key]=matrix[key]+('/日本語'if key=='path'else '!')if isinstance(matrix[key],str)else matrix[key]+1
        header+='{auto m=metadata_matrix();'+setter(key,variant[key])+'if(m.key()!=u8'+literal(expected(variant))+')throw std::runtime_error("key field contract");}\n'
    header+='}\n';(folder/'key-metadata.inc').write_text(header,encoding='utf-8')
    source=snapshot/'Strata-extensions/tests/backend/key_lookup_fixture.cpp'
    cmake='cmake_minimum_required(VERSION 3.20)\nproject(t35_key LANGUAGES CXX)\nadd_executable(t35-key "'+source.as_posix()+'")\ntarget_compile_features(t35-key PRIVATE cxx_std_17)\ntarget_compile_options(t35-key PRIVATE /W4 /EHsc /utf-8 /fp:strict)\ntarget_include_directories(t35-key PRIVATE "'+folder.as_posix()+'")\nset_property(TARGET t35-key PROPERTY MSVC_RUNTIME_LIBRARY MultiThreaded)\n'
    cmake+='target_include_directories(t35-key PRIVATE '+' '.join('"'+(snapshot/p.parent.relative_to(ROOT)).as_posix()+'"'for p in headers)+')\n'
    (folder/'CMakeLists.txt').write_text(cmake,encoding='utf-8')
    commands=[[tools['cmake'],'-S',folder,'-B',folder/'native','-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_CXX_COMPILER='+str(tools['cl']),'-DCMAKE_MAKE_PROGRAM='+str(tools['ninja'])],[tools['cmake'],'--build',folder/'native']]
    for n,cmd in enumerate(commands):
        result=old.run(cmd,env,False);(folder/f'build-{n}.log').write_text(result.stdout+result.stderr,encoding='utf-8');B.require(result.returncode==0,'key metadata build failed')
    exe=folder/'native/t35-key.exe';seal=dict(Q=row(folder/'Q.json'),exe=row(exe),source=before,generated=[row(folder/n)for n in ('key-definition.inc','key-metadata.inc','CMakeLists.txt')],tools={k:row(p)for k,p in tools.items()},mapping=mapping)
    save(folder/'seal.json',seal)
    result=subprocess.run([str(exe)],capture_output=True,text=True,encoding='utf-8',env=env)
    (folder/'stdout.json').write_text(result.stdout,encoding='utf-8');(folder/'stderr.txt').write_text(result.stderr,encoding='utf-8');B.require(result.returncode==0,'metadata execution failed')
    value=json.loads(result.stdout);analysis=validate_key_lookup(value,expected(matrix).encode().hex())
    bindings(before)
    proof=dict(schema='T35-key-metadata-AB/v1',seal=row(folder/'seal.json'),stdout=row(folder/'stdout.json'),stderr=row(folder/'stderr.txt'),analysis=analysis,actual_weight_read=0,GPU=0,normal_native_built=False,model_performance_qualified=False)
    save(folder/'verification.json',proof);print(json.dumps(row(folder/'verification.json')))


def normal_hoist_build():
    olddir=ROOT/'build-deepseek-t28/normal/normal-allocation-r1'
    oldmanifest=read(olddir/'manifest.json')
    for r in oldmanifest['bindings']:
        B.require(sha(r['path'])==r['sha256']and Path(r['path']).stat().st_size==r['bytes'],'old normal exact binding: '+r['path'])
    folder=BUILD/'key-normal-native-1';folder.mkdir(exist_ok=False)
    closure=folder/'source';mapping=[]
    for p in sorted((olddir/'source').rglob('*')):
        if not p.is_file():continue
        target=closure/p.relative_to(olddir/'source');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        mapping.append(dict(original=row(p),copy=row(target)))
    primary=closure/'Strata-extensions/native/cache/primary_supply.hip'
    before=BUILD/'key-hoist-source/primary_supply-before.hip';after=BUILD/'key-hoist-source/primary_supply-after.hip'
    B.require(sha(primary)==sha(before),'normal baseline Primary differs from accepted source')
    shutil.copyfile(after,primary)
    cmake=ROOT/'build-deepseek-t44/before-source/CMakeLists.txt'
    B.require(sha(cmake)=='faa3b20bcefa6b0d3fad3afe6ac426ee9d583fc275bf811d466756358d068c8f','accepted normal CMake changed')
    model=closure/'Strata-extensions/models/deepseek41';shutil.copyfile(cmake,model/'CMakeLists.txt')
    spec=importlib.util.spec_from_file_location('t35_normal_build_tools',HERE.parent/'serve_provider/build_verify.py');normal=importlib.util.module_from_spec(spec);spec.loader.exec_module(normal)
    normal.BUILD=folder;tools,env,sdk=normal.hip_tools();out=folder/'native'
    original_rows=[row(p)for p in sorted(closure.rglob('*'))if p.is_file()]
    command=[tools['cmake'],'--fresh','-S',model,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
    save(folder/'preflight.json',dict(parent=row(olddir/'manifest.json'),CPU=row(BUILD/'key-metadata-ab-3/verification-CPU.json'),Primary_before=row(before),Primary_after=row(after),source=original_rows,CMake=row(cmake),tool_recipe=row(HERE.parent/'serve_provider/build_verify.py'),tool_environment_recipe=row(HERE.parent/'core/build_verify.py'),fresh_free=shutil.disk_usage(ROOT).free,held_already_reflected=True,normal_cap=False,GPU=0,T45_live_consumed=False))
    for n,cmd in enumerate([command,[tools['cmake'],'--build',out,'--target','Strata-deepseek','--verbose']]):
        result=subprocess.run(list(map(str,cmd)),env=env,cwd=closure,capture_output=True,text=True,encoding='utf-8',errors='replace')
        save(folder/f'build-{n}.json',dict(command=list(map(str,cmd)),exit=result.returncode,stdout=result.stdout,stderr=result.stderr));print('normal hoist build',n,result.returncode,flush=True)
        B.require(result.returncode==0,'immutable normal hoist build failed')
    bundle=folder/'bundle';bundle.mkdir();copies=[]
    for name in ('Strata-deepseek.exe','amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):
        source=out/'bundle'/name if name.endswith('.exe')else olddir/'bundle'/name
        target=bundle/name;shutil.copyfile(source,target);copies.append(dict(origin=row(source),target=row(target)))
    server=bundle/'server/serve/server.py';server.parent.mkdir(parents=True);shutil.copyfile(olddir/'bundle/server/serve/server.py',server);copies.append(dict(origin=row(olddir/'bundle/server/serve/server.py'),target=row(server)))
    runtime=dict(env);runtime['PATH']=os.pathsep.join([str(bundle),'C:/Windows/System32','C:/Windows'])
    result=subprocess.run([str(bundle/'Strata-deepseek.exe'),'--identity'],env=runtime,capture_output=True,text=True,encoding='utf-8');B.require(result.returncode==0,'new normal identity failed')
    save(folder/'identity.json',json.loads(result.stdout))
    declared=(out/'declared-sources.tsv').read_text(encoding='utf-8');identity=read(folder/'identity.json')
    B.require(identity['source_set_sha256']==hashlib.sha256(declared.encode()).hexdigest(),'new normal declared identity')
    bindings(original_rows)
    deps=subprocess.run([str(tools['ninja']),'-C',str(out),'-t','deps'],env=env,capture_output=True,text=True,encoding='utf-8');B.require(deps.returncode==0,'new normal dependencies')
    (folder/'ninja-deps.txt').write_text(deps.stdout,encoding='utf-8')
    consumed=[];seen=set()
    for line in deps.stdout.splitlines():
        if not line.startswith('    '):continue
        p=Path(line.strip()).resolve()
        if p.is_file()and str(p).lower()not in seen:seen.add(str(p).lower());consumed.append(row(p))
    manifest=dict(schema='strata-t35-key-hoist-normal/v1',copies=copies,bindings=original_rows+consumed+[row(p)for p in tools.values()if Path(p).is_file()],declared_source_sha256=identity['source_set_sha256'],parent=row(olddir/'manifest.json'),preflight=row(folder/'preflight.json'),identity=row(folder/'identity.json'),declared=row(out/'declared-sources.tsv'),deps=row(folder/'ninja-deps.txt'),CPU=row(BUILD/'key-metadata-ab-3/verification-CPU.json'),only_runtime_source_delta='Primary immutable key hoist',normal_fault_api=False,both_architectures=['gfx1100','gfx1201'],actual_owner_G=False,new_normal_model_qualified=False,GPU=0,T45_live_consumed=False)
    save(folder/'manifest.json',manifest);print(json.dumps(row(folder/'manifest.json')))


def host_io_build(lifecycle=False):
    folder=BUILD/('provider-lifecycle-build-r2'if lifecycle else'host-io');folder.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('t35_t17_recipe',HERE.parent/'io/build_verify.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    old.BUILD=folder;tools,env=old.environment()
    if lifecycle:env['STRATA_IO_THREADS']='4'
    relative=['Strata-extensions/native/io/span_provider.hpp','Strata-extensions/native/io/span_provider.cpp',
              'Strata-extensions/tests/backend/io_chunk_fixture.cpp',*old.DEPS[:14]]
    originals=[ROOT/p for p in relative]+[Path(__file__),HERE/'test_eager_bench.py',HERE/'eager_contract.json',HERE.parent/'io/build_verify.py',ROOT/'LICENSE']
    if lifecycle:originals.append(HERE/'eager_bench.py')
    before=[row(p)for p in originals];mapping=[];snapshot=folder/'source'
    for p,r in zip(originals,before,strict=True):
        target=snapshot/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        B.require(sha(target)==r['sha256'],'host source changed during snapshot');mapping.append(dict(original=r,snapshot=row(target)))
    cpu=subprocess.run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s',str(HERE),'-p','test_eager_bench.py','-v'],capture_output=True,text=True,encoding='utf-8')
    (folder/'cpu.log').write_text(cpu.stdout+cpu.stderr,encoding='utf-8');B.require(cpu.returncode==0,'host CPU expectations failed')
    native=snapshot/'Strata-extensions/native'
    sources=[native/'io/span_provider.cpp',snapshot/'Strata-extensions/tests/backend/io_chunk_fixture.cpp',native/'artifact/native_reader.cpp',native/'cache/lease_queue.cpp',native/'stats/measurement.cpp',snapshot/'src/platform/direct_file.cpp']
    cmake='cmake_minimum_required(VERSION 3.20)\nproject(t35_host_io LANGUAGES CXX)\nadd_executable(t35-host-io '+ ' '.join('"'+p.as_posix()+'"'for p in sources)+')\n'
    cmake+='target_include_directories(t35-host-io PRIVATE '+ ' '.join('"'+p.as_posix()+'"'for p in (native/'io',native/'artifact',native/'cache',native/'stats',snapshot/'include'))+')\n'
    cmake+='target_compile_features(t35-host-io PRIVATE cxx_std_17)\ntarget_compile_options(t35-host-io PRIVATE /W4 /EHsc /fp:strict)\nset_property(TARGET t35-host-io PROPERTY MSVC_RUNTIME_LIBRARY MultiThreaded)\ntarget_compile_definitions(t35-host-io PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)\ntarget_link_libraries(t35-host-io PRIVATE bcrypt)\n'
    recipe=folder/'CMakeLists.txt';recipe.write_text(cmake,encoding='utf-8')
    commands=[[tools['cmake'],'-S',folder,'-B',folder/'native','-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_CXX_COMPILER='+str(tools['cl']),'-DCMAKE_MAKE_PROGRAM='+str(tools['ninja'])],[tools['cmake'],'--build',folder/'native']]
    for n,cmd in enumerate(commands):
        r=old.run(cmd,env,False);(folder/f'build-{n}.log').write_text(r.stdout+r.stderr,encoding='utf-8');B.require(r.returncode==0,'host build failed; logs retained')
    bindings(before)
    proof=dict(schema='T35-provider-lifecycle-build/v1'if lifecycle else'T35-host-io-build/v1',sources=before,source_snapshots=mapping,tools={k:row(p)for k,p in tools.items()},recipe=row(recipe),commands=[list(map(str,c))for c in commands],exe=row(folder/'native/t35-host-io.exe'),CPU=row(folder/'cpu.log'),pre=row(BUILD/('provider-lifecycle-pre-r1.md'if lifecycle else'host-io-pre-r2.md')),GPU=0,actual_read_executed=False)
    save(folder/'build.json',proof);print(json.dumps(row(folder/'build.json')))

def host_io_execute():
    folder=BUILD/'host-io';build=read(folder/'build.json');bindings(build['sources']+[build['exe'],build['recipe'],build['pre']]+list(build['tools'].values()))
    out=folder/'attempt-1';out.mkdir(exist_ok=False)
    receipt_path=ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json';receipt=read(receipt_path)
    B.require(receipt['complete']is True and receipt['revision']==B.DTO.REVISION,'qualified original revision')
    spec=importlib.util.spec_from_file_location('t35_t05_identity',ROOT/'Strata-extensions/native/artifact/full_acquire.py');acquire=importlib.util.module_from_spec(spec);spec.loader.exec_module(acquire)
    source=receipt['files'][0];path=Path(source['path']);before=acquire.stat_identity(path)
    B.require(source['index']==1 and before==source['file_identity'] and source['sha256']==source['source']['lfs_sha256'],'original current identity/LFS')
    for suffix in ('.part','.part.lock'):B.require(not Path(str(path)+suffix).exists(),'active acquisition body/lock')
    with path.open('rb')as stream:expected=stream.read(2097152)
    B.require(len(expected)==2097152,'expected prefix read')
    expected_sha=hashlib.sha256(expected).hexdigest()
    seal=dict(schema='T35-host-io-seal/v1',build=row(folder/'build.json'),receipt=row(receipt_path),identity=before,source=source,expected_prefix_bytes=len(expected),expected_sha256=expected_sha,schedule=list('ABBA'),data_requested_per_clean_arm=2097152,data_operations=dict(A=32,B=1),source_logical_bytes_maximum=12582912,header_payload_mixed=True,physical_io=None,GPU=0,raw_saved=False)
    save(out/'seal.json',seal)
    env=os.environ.copy();env['STRATA_IO_THREADS']='1'
    start=time.perf_counter_ns();result=subprocess.run([build['exe']['path'],str(path),str(before['bytes']),expected_sha,sha(out/'seal.json')],input=expected,capture_output=True,env=env)
    (out/'stdout.json').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
    execution=dict(exit=result.returncode,controller_elapsed_seconds=(time.perf_counter_ns()-start)/1e9);save(out/'execution.json',execution)
    B.require(result.returncode==0,'host read attempt failed; raw logs retained')
    value=json.loads(result.stdout);B.require(value['seal_sha256']==sha(out/'seal.json'),'native seal binding')
    analysis=validate_host_io(value,expected_sha)
    with path.open('rb')as stream:after_bytes=stream.read(2097152)
    B.require(after_bytes==expected and acquire.stat_identity(path)==before,'post original identity/prefix')
    bindings(build['sources']+[build['exe'],seal['receipt']])
    proof=dict(schema='T35-host-io-result/v1',seal=row(out/'seal.json'),raw=row(out/'stdout.json'),stderr=row(out/'stderr.log'),execution=row(out/'execution.json'),analysis=analysis,post_prefix_sha256=hashlib.sha256(after_bytes).hexdigest(),source_before_after_identity=True,source_read_bytes=12582912,physical_io=None,GPU=0,model_performance_qualified=False)
    save(out/'verification.json',proof);print(json.dumps(row(out/'verification.json')))

def lifecycle_close(session,observe):
    result=dict(sample=None,observation_error=None)
    try:result['sample']=observe()
    except Exception as error:result['observation_error']=str(error)
    finally:session.close()
    return result


def lifecycle_archive():
    """Reuse the accepted report-only owner code without importing mutable helpers."""
    seal_path=BUILD/'approx-8g-r1/measurement-seal.json';seal=read(seal_path)
    bindings([r['snapshot']for r in seal['source_snapshots']])
    backend=BUILD/'approx-8g-r1/measurement-source/Strata-extensions/tests/backend'
    prior=sys.modules.get('eager_bench')
    def load(name,path):
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
    try:
        old_b=load('C32_accepted_owner_math',backend/'eager_bench.py');sys.modules['eager_bench']=old_b
        old=load('C32_accepted_owner_recipe',backend/'build_verify.py')
    finally:
        if prior is None:sys.modules.pop('eager_bench',None)
        else:sys.modules['eager_bench']=prior
    return old,seal_path,seal


def provider_lifecycle_prepare(destination):
    destination=Path(destination).resolve();destination.mkdir(exist_ok=False)
    build_path=BUILD/'provider-lifecycle-build-r2/build.json';build=read(build_path)
    bindings([r['snapshot']for r in build['source_snapshots']]+[build['exe'],build['recipe'],build['pre']]+list(build['tools'].values()))
    old,owner_path,owner_seal=lifecycle_archive();config=owner_seal['input'];old.runtime_snapshot(config)
    receipt_path=ROOT/'Strata-extensions/tests/artifact/full-model-receipt.json';receipt=read(receipt_path)
    B.require(receipt['complete']is True and receipt['revision']==B.DTO.REVISION,'accepted original receipt')
    old_host=BUILD/'host-io/attempt-1/verification.json';old_host_proof=read(old_host);bindings([old_host_proof['raw']])
    B.require(old_host_proof['raw']==row(BUILD/'host-io/attempt-1/stdout.json'),'accepted old host input body')
    dto_record=next(r['original']for r in owner_seal['source_snapshots']if Path(r['original']['path']).resolve()==B._dto_path.resolve())
    bindings([dto_record])
    paths=[HERE/n for n in ('io_chunk_fixture.cpp','build_verify.py','eager_bench.py','test_eager_bench.py')]
    paths += [B._dto_path,Path(old_host_proof['raw']['path']),old_host,owner_path,receipt_path,HERE/'eager_contract.json',ROOT/'Strata-extensions/native/artifact/full_acquire.py']
    records=[row(p)for p in paths]+[r['snapshot']for r in owner_seal['source_snapshots']]
    records += [r['snapshot']for r in build['source_snapshots']]+[build['recipe']]+list(build['tools'].values())
    records += [row(BUILD/p)for p in ('provider-lifecycle-CPU-1/verification.json','provider-lifecycle-wrapper-RED.log','provider-lifecycle-wrapper-GREEN.log')]
    mapping=[]
    for path in paths[:4]:
        target=destination/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        B.require(row(path)['sha256']==row(target)['sha256'],'C32 source copy changed');mapping.append(dict(original=row(path),snapshot=row(target)));records.append(row(target))
    save(destination/'source-map.json',mapping);records.append(row(destination/'source-map.json'))
    save(destination/'seal.json',dict(schema='T35-provider-lifecycle-execution/v1',build=row(build_path),exe=build['exe'],records=records,owner_seal=row(owner_path),source=receipt['files'][0],receipt=row(receipt_path),workers=4,schedule=list('ACCA'),chunk=65536,windows=32,source_logical_bytes_maximum=12582912,original_payload_read=False,model_GEN_count=0,DRAM_report_only=True,production_modified=False))
    print(json.dumps(row(destination/'seal.json')))


def provider_lifecycle_execute(destination):
    destination=Path(destination).resolve();seal_path=destination/'seal.json';seal=read(seal_path)
    bindings(seal['records']+[seal['build'],seal['exe'],seal['owner_seal'],seal['receipt']])
    B.require(not(destination/'execution.json').exists()and not(destination/'owner-selection.json').exists(),'preserve original lifecycle attempts')
    old,owner_path,owner_seal=lifecycle_archive();config=copy.deepcopy(owner_seal['input']);config['environment']=dict(config['environment'])
    temporary=destination/'tmp';temporary.mkdir();config['environment'].update(TMP=str(temporary),TEMP=str(temporary))
    env=dict(os.environ);env.update(config['environment']);env['STRATA_IO_THREADS']='4'
    acquire_spec=importlib.util.spec_from_file_location('C32_original_identity',ROOT/'Strata-extensions/native/artifact/full_acquire.py');acquire=importlib.util.module_from_spec(acquire_spec);acquire_spec.loader.exec_module(acquire)
    source=seal['source'];path=Path(source['path']);before=acquire.stat_identity(path)
    B.require(source['index']==1 and before==source['file_identity']and source['sha256']==source['source']['lfs_sha256'],'original identity/LFS')
    for suffix in('.part','.part.lock'):B.require(not Path(str(path)+suffix).exists(),'active source acquisition')
    session=None;driver=None;memory=[];cleanup=None;primary_failure=None
    try:
        session,selection,first=old.select_owner(config,env,destination);birth=first['birth'];memory.append(dict(role='model-owner',point='constructed',sample=first))
        owner_info=session.info();owner_runtime=old.runtime_snapshot(config,owner_info)
        B.require(owner_info['core_position']==0 and owner_info['primary_logical_read']==0 and owner_info['primary_h2d']==0,'noGEN owner has no model computation')
        with path.open('rb')as stream:expected=stream.read(2097152)
        B.require(len(expected)==2097152,'single independent expected prefix read');expected_sha=hashlib.sha256(expected).hexdigest()
        run_seal=dict(parent=row(seal_path),source_identity=before,expected_prefix_bytes=2097152,expected_sha256=expected_sha,owner_selection=row(destination/'owner-selection.json'),owner_runtime=owner_runtime,command_environment_workers='4',schedule=list('ACCA'),source_logical_bytes_maximum=12582912,DRAM_report_only=True,raw_saved=False)
        save(destination/'actual-seal.json',run_seal)
        command=[seal['exe']['path'],str(path),str(before['bytes']),expected_sha,sha(destination/'actual-seal.json'),'reuse64']
        memory.append(dict(role='model-owner',point='before-arms',sample=old.physical_memory(session.proc.pid,birth)))
        start=time.perf_counter_ns();driver=subprocess.Popen(command,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        memory.append(dict(role='host-driver',point='before-input',sample=old.physical_memory(driver.pid)))
        stdout,stderr=driver.communicate(expected)
        (destination/'stdout.json').write_bytes(stdout);(destination/'stderr.log').write_bytes(stderr)
        save(destination/'execution.json',dict(command=command,exit=driver.returncode,controller_elapsed_seconds=(time.perf_counter_ns()-start)/1e9))
        memory.append(dict(role='host-driver',point='after-exit',sample=old.physical_memory(driver.pid)))
        memory.append(dict(role='model-owner',point='after-arms',sample=old.physical_memory(session.proc.pid,birth)))
        B.require(driver.returncode==0 and not stderr,'finite original host attempt failed; raw retained')
        value=json.loads(stdout);B.require(value['seal_sha256']==sha(destination/'actual-seal.json'),'native actual seal')
        analysis=B.validate_provider_lifecycle(value,expected_sha)
        with path.open('rb')as stream:after_bytes=stream.read(2097152)
        B.require(after_bytes==expected and acquire.stat_identity(path)==before,'post prefix/identity')
        final_info=session.info();B.require(final_info['core_position']==0 and final_info['primary_logical_read']==0 and final_info['primary_h2d']==0,'model owner received no GEN')
        save(destination/'owner-info.json',dict(before=owner_info,after=final_info,runtime_before=owner_runtime,runtime_after=old.runtime_snapshot(config,final_info),GEN_count=0,valid_model_payload_bytes=None))
        bindings(seal['records']+[seal['build'],seal['exe'],seal['owner_seal'],seal['receipt']])
    except BaseException as error:
        primary_failure=error;save(destination/'failure.json',dict(type=type(error).__name__,error=str(error)))
    finally:
        if driver is not None and driver.poll()is None:
            # Closing stdin permits the isolated bounded driver to finish/reject.
            if driver.stdin and not driver.stdin.closed:driver.stdin.close()
            driver.stdin=None
            try:driver.communicate()
            except BaseException as error:
                if primary_failure is None:primary_failure=error
        if session is not None:
            try:
                cleanup=lifecycle_close(session,lambda:old.physical_memory(session.proc.pid,birth));cleanup.update(pid=session.proc.pid,birth=birth,exit=session.proc.returncode)
            except BaseException as error:
                cleanup=dict(error=str(error),pid=session.proc.pid,exit=session.proc.poll())
                if primary_failure is None:primary_failure=error
        save(destination/'memory.json',memory);save(destination/'cleanup.json',cleanup)
    if primary_failure is not None:raise primary_failure
    bindings(seal['records']+[seal['build'],seal['exe'],seal['owner_seal'],seal['receipt']])
    B.require(acquire.stat_identity(path)==before,'source identity after owner cleanup')
    save(destination/'verification.json',dict(schema='T35-provider-lifecycle-actual/v1',seal=row(seal_path),actual_seal=row(destination/'actual-seal.json'),raw=row(destination/'stdout.json'),stderr=row(destination/'stderr.log'),execution=row(destination/'execution.json'),owner_info=row(destination/'owner-info.json'),memory=row(destination/'memory.json'),cleanup=row(destination/'cleanup.json'),analysis=analysis,post_prefix_sha256=hashlib.sha256(after_bytes).hexdigest(),source_before_after_identity=True,source_read_bytes=12582912,DRAM_report_only=True,model_GEN_count=0,GPU_model_kernels=0,noGEN_owner_used_HIP=True,production_modified=False,physical_io=None,model_performance_qualified=False))
    print(json.dumps(row(destination/'verification.json')))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--provider-lifecycle-prepare',type=Path);parser.add_argument('--provider-lifecycle-execute',type=Path);parser.add_argument('--pair-index',type=int);parser.add_argument('--aggregate',type=Path);parser.add_argument('--seal',type=Path);parser.add_argument('--execute',type=Path);parser.add_argument('--replay',type=Path);parser.add_argument('--host-io-build',action='store_true');parser.add_argument('--host-io-execute',action='store_true');parser.add_argument('--key-lookup-build',action='store_true');parser.add_argument('--normal-hoist-build',action='store_true');args=parser.parse_args()
    if args.provider_lifecycle_prepare:provider_lifecycle_prepare(args.provider_lifecycle_prepare)
    elif args.provider_lifecycle_execute:provider_lifecycle_execute(args.provider_lifecycle_execute)
    elif args.normal_hoist_build:normal_hoist_build()
    elif args.key_lookup_build:key_lookup_build()
    elif args.host_io_build:host_io_build()
    elif args.host_io_execute:host_io_execute()
    elif args.seal:seal(args.seal)
    elif args.aggregate:aggregate_measurement(args.aggregate)
    elif args.execute:execute(args.execute,args.pair_index)
    elif args.replay:print(json.dumps(replay(args.replay)))
    else:cpu()
if __name__=='__main__':main()
