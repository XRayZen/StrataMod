"""T46 finite four-mode pilot. Source/CPU first; no operation runs on import.

Receipts separate candidate numeric review and publication; this program never
writes public files. CPU fixtures are explicitly ineligible as model evidence.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import sys
import time
from decimal import Decimal

R = Path('C:/Develop/AI/Strata-data/build/deepseek-v41')
B = R/'build-deepseek-t46'
HERE = Path(__file__).resolve().parent
DATA = Path('C:/Develop/AI/Strata-data')
ID = 'e32f159e984ec22450b7d378d59a2dfdadb95a62cdeca22c8bf4c8e5c825a0a6'
PACKAGE = Path('C:/Develop/AI/Strata-extensions/runtime/deepseek41')/ID
BUNDLE = '2c12eedaa97e137ed7125935ce74f1cf9eb8a8e9807e46bd44b50cf8e817afdc'
HOOK = '0a5c240f279a641148e57ddacdad7154e9acfbe5c1dc884622c4b43593ec6e98'
MODES = ('single','cache-only','expert-assist','layer-split')
MODEL = 'deepseek-v4.1-flash-1017-ud-q4_k_xl'
PROMPT = [0,128803,128804,128822]
IDS = [4482,55753]
U64 = 2**64-1
ENV = 'DEEPSEEK_T46_OBSERVER_SPEC'
Q = R/'build-deepseek-t31/actual-sse-attempt-1/expectation.json'
PROFILE = B/'package-candidate-e32f159e984e/profiles'/f'{MODEL}-4096.json'
MEMORY = R/'build-deepseek-t35/formal-report-only-CPU-1/source/Strata-extensions/tests/backend/build_verify.py'
CANDIDATE_INPUT = B/'package-input-r4/inputs.json'
CANDIDATE_PROOF = B/'package-candidate-e32f159e984e/verification.json'
CONTACT_ID='de662662c8da4ab6ba8d3c3f1ca5f61309cf95d52b88e75827858862b418fddf'
CONTACT_ROOT=R/'build-deepseek-t35/normal-perf-union-r1'
ORIGINAL_HERE=B/'actual-mode-runner'
CONTACT_PREP=ORIGINAL_HERE/'matching-contact-perf-preparation-r1'
CONTACT_INPUT='0c6657974d2e9ab238b0f3b80fc41b0736c2882c352c97159cf21b5f9c61af8e'
CONTACT_NATIVE='295ed33193a584dc3046b3c84431faf8d108278575f5a7c9353ac4cfdd116c77'
CONTACT_SOURCE='f30c9ba8ef21ea1c21d751caf8728e143d03e63d76c21ee83fc4743db2bba256'
CONTACT_EXE='e2f7f0d2a684788a72cc6e49549c799e9138df3d4d91480b8e4385497f94ddb7'
CONTACT_HOOK='d73dffd348ee35f771eefa7c665e92958374e8d7df5cf6809a29d41ac3df121e'
# Preserve the original de662 domain; new proof rows select one finite successor.
LEGACY_CONTACT={name:globals()[name] for name in ('CONTACT_ID','CONTACT_ROOT','CONTACT_PREP','CONTACT_INPUT','CONTACT_NATIVE','CONTACT_SOURCE','CONTACT_EXE','CONTACT_HOOK')}
_SELECTED_CONTACT=None
_CONTACT_BOUND=False

def contact_selected():
    """Never silently skip the contact contract for an unbound successor."""
    require(_CONTACT_BOUND,'selected contact bind incomplete or failed')
    if ID==LEGACY_CONTACT['CONTACT_ID'] and _SELECTED_CONTACT is None:return True
    require(_SELECTED_CONTACT is not None and _SELECTED_CONTACT['package_id']==ID
        and BUNDLE==CONTACT_NATIVE and HOOK==CONTACT_HOOK,'selected contact domain not bound')
    return True

def select_contact(inputs,proof):
    """One checked candidate proof extension record; no new package schema."""
    global _SELECTED_CONTACT,CONTACT_ID,CONTACT_ROOT,CONTACT_PREP,CONTACT_INPUT,CONTACT_NATIVE,CONTACT_SOURCE,CONTACT_EXE,CONTACT_HOOK,_CONTACT_BOUND
    _CONTACT_BOUND=False
    _SELECTED_CONTACT=None
    if ID==LEGACY_CONTACT['CONTACT_ID']:
        for name,value in LEGACY_CONTACT.items():globals()[name]=value
        _SELECTED_CONTACT=None
        return
    reference=proof.get('selected_contact')
    require(type(reference)is dict and set(reference)=={'path','bytes','sha256'},'selected contact record required')
    checked([reference]);descriptor=load(reference['path'])
    fields={'input','package_manifest','native_manifest','source_root','codeobject_root','identity_root','consumed_roots','counts','math_abi','runner'}
    require(type(descriptor)is dict and set(descriptor)==fields,'selected contact descriptor fields')
    require(descriptor['input']==row(CANDIDATE_INPUT)and descriptor['package_manifest']==proof['package_manifest'],'selected contact input/manifest')
    native_record=dict(path=inputs['native_manifest']['source'],bytes=inputs['native_manifest']['bytes'],sha256=inputs['native_manifest']['sha256'])
    require(descriptor['native_manifest']==native_record,'selected contact native manifest')
    checked([descriptor[k]for k in ('input','package_manifest','native_manifest','runner')])
    require(descriptor['runner']==row(__file__),'selected contact exact reviewed runner')
    native=load(native_record['path'])
    require(native['compiled_source_id']==inputs['native_compiled_source_id']and native['normal']is True and native['both_arch']is True,'selected contact source/build')
    require(type(descriptor['math_abi'])is str and re.fullmatch('[0-9a-f]{64}',descriptor['math_abi'])and descriptor['math_abi']==native.get('math_abi',native.get('graph_abi')),'selected contact supplied math ABI')
    for key in ('source_root','codeobject_root','identity_root'):
        require(type(descriptor[key])is str and Path(descriptor[key]).is_absolute()and str(Path(descriptor[key]).resolve())==descriptor[key],'selected contact exact root')
    require(Path(native['source_root']).resolve()==Path(descriptor['source_root']),'selected contact source root')
    require(type(descriptor['consumed_roots'])is list and descriptor['consumed_roots'] and all(type(x)is str and Path(x).is_absolute()and str(Path(x).resolve())==x for x in descriptor['consumed_roots']),'selected contact consumed roots')
    counts=descriptor['counts']
    require(type(counts)is dict and set(counts)=={'consumed','declared','source_snapshots','codeobjects_per_arch'}and all(type(x)is int and x>0 for x in counts.values()),'selected contact finite counts')
    require(len(native['CPU'])==1 and native['CPU'][0]['flag']=='--identity','selected contact one actual identity')
    identity=native['CPU'][0];checked([identity['exe']])
    selected_exe=[x for x in inputs['selected_files']if x['relative_destination']=='native/Strata-deepseek.exe']
    require(len(selected_exe)==1 and all(identity['exe'][k]==selected_exe[0][k]for k in ('bytes','sha256')),'selected contact EXE/payload')
    CONTACT_INPUT=row(CANDIDATE_INPUT)['sha256'];CONTACT_NATIVE=BUNDLE
    CONTACT_SOURCE=native['compiled_source_id'];CONTACT_EXE=identity['exe']['sha256'];CONTACT_HOOK=HOOK
    _SELECTED_CONTACT=dict(package_id=ID,record=reference,descriptor=descriptor)

# Exact WT_SITES in the pinned trial_wait_aggregate.hpp, not INFO counters.
WAIT_METRICS=tuple('ProjectionReady ProjectionKernel EmbeddingReady EmbeddingKernel RowReady RowKernel RowReturn Prefill DecodeStep RequestDrain ProjectionCallbacks EmbeddingDecodes QuantLaunches PrimaryPoll0 PrimaryPoll10 PrimaryPollOther RowPoll0 RowPoll10 RowPollOther ProviderPoll0 ProviderPoll10 ProviderPollOther DirectCall0 DirectCall10 DirectCallOther DirectActivePending DirectNoActivePending ProviderInstances ProviderFinishes ProviderTakes ProviderIssueCalls ProviderIssuedOperations DirectFileSubmissions PrimaryFilled PrimaryLastuse RowFilled RowConsumed RowReturned QuantAdmission QuantValidation QuantPointerAttributes QuantAllocationRange DecodePointerAttributes DecodeAllocationRange StorageUploadSync StorageDownloadSync StorageDrainSync CompressedPublishSync IndexPublishSync IndexSelectionSync RowIndexSync PrimaryErrorDrain RowErrorDrain'.split())

def _legacy_contact_native_records(inputs,native):
    """One exact perf successor; old8d pins remain immutable prior sources."""
    require(ID==inputs['candidate_package_id']==CONTACT_ID,'contact candidate')
    for path,digest in [(CANDIDATE_INPUT,CONTACT_INPUT),(CANDIDATE_PROOF,'4d9ecee5d20659bb7d75b21037511a297fce1a27fe4c3f8519b8e71584eb1e89'),(inputs['native_manifest']['source'],CONTACT_NATIVE)]:
        require(row(path)['sha256']==digest,'contact exact input/proof/native')
    require(native==load(inputs['native_manifest']['source'])and native['schema']=='strata-t46-perf-native-manifest/v1','contact native object exact')
    require(native['compiled_source_id']==CONTACT_SOURCE and native['normal']is True and native['both_arch']is True and Path(native['source_root']).resolve()==(CONTACT_ROOT/'source').resolve(),'contact perf native source')
    records=[]
    for key,digest in [('source_closure','0f0890ec82fcd337ec58f12f8e97a2bad73f74a4862ffc49c24b1a99c1cdd5f8'),('native_closure','2b283efbb5df40f720cebad2c49921f3bf7f7454422f36c88320de5105c665b6'),('build','4113d7d3e8050c47d3dd9ead66cbd017b2f96164da309c01b1f94a78c92106f5'),('accepted_report','025af5977fc1f55afda5e5f559d40aa14a537cf49b9cd7d5e1b48b923cf5e69b')]:
        value=native[key];require(value['sha256']==digest and Path(value['path']).resolve().parent==CONTACT_ROOT.resolve(),'contact perf closure pin');checked([value]);records.append(value)
    closure=load(native['native_closure']['path']);source=load(native['source_closure']['path'])
    require(native['consumed']==closure['consumed_dependencies']and native['declared_tsv']==closure['declared_sources']and native['codeobjects']==closure['codeobjects'],'contact perf consumed closure')
    def finite(values,*roots):
        require(len(values)==len({str(Path(v['path']).resolve())for v in values}),'contact duplicate identity row')
        for value in values:require(set(value)=={'path','bytes','sha256'}and any(Path(value['path']).resolve().is_relative_to(root.resolve())for root in roots),'contact foreign snapshot root')
        checked(values);records.extend(values)
    require(len(native['consumed'])==531 and len(native['declared'])==48 and len(source['records'])==110,'contact perf source counts')
    finite(native['consumed'],CONTACT_ROOT/'source',Path('C:/Develop/AI/StrataMod/.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207/include'),Path('C:/Develop/AI/StrataMod/.vision-toolchain/winsdk/microsoft.windows.sdk.cpp/c/Include'),Path('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages'))
    checked([native['declared_tsv']]);records.append(native['declared_tsv'])
    declared=[]
    for line in Path(native['declared_tsv']['path']).read_text(encoding='utf8').splitlines():
        relative,digest=line.split('|');value=row(CONTACT_ROOT/'source'/relative);require(value['sha256']==digest,'contact declared source hash');declared.append(value)
    require(native['declared']==declared,'contact exact perf declarations');finite(declared,CONTACT_ROOT/'source')
    finite([v['snapshot']for v in source['records']],CONTACT_ROOT/'source')
    require(len(native['codeobjects'])==18 and all(sum('--'+arch in v['path']for v in native['codeobjects'])==9 for arch in('gfx1100','gfx1201')),'contact bothgfx codeobjects')
    finite(native['codeobjects'],CONTACT_ROOT/'candidate-on/bundle')
    require(len(inputs['native_bundle_dlls'])==6 and inputs['native_bundle_dlls']==native['bundle_dlls'],'contact six unchanged DLLs');finite(inputs['native_bundle_dlls'],CONTACT_PREP/'identity-bundle')
    require(len(native['CPU'])==1,'contact one native identity');identity=native['CPU'][0]
    require(identity['flag']=='--identity'and identity['exit']==0 and identity['stderr']==''and json.loads(identity['stdout'])==dict(source_set_sha256=CONTACT_SOURCE,normal_audit_d2h=False)and identity['exe']['sha256']==CONTACT_EXE,'contact actual native identity')
    finite([identity['exe']],CONTACT_PREP/'identity-bundle')
    finite([identity[k]for k in('command','owner','result','handle_closed','stdout_file','stderr_file','outer')],CONTACT_PREP/'identity-attempt-r1')
    result=load(identity['result']['path']);close=load(identity['handle_closed']['path']);require(result['wait_completed']is True and result['exit']==0 and result['handle_closed']is True and result['disposed']is True and not result['secondary_errors']and close['original_safehandle_closed']is True and close['original_process_object_disposed']is True,'contact identity original wait/close')
    return list({v['path']:v for v in records}.values())

def contact_native_records(inputs,native):
    contact_selected()
    if ID==LEGACY_CONTACT['CONTACT_ID']:return _legacy_contact_native_records(inputs,native)
    d=_SELECTED_CONTACT['descriptor'];counts=d['counts']
    require(native==load(d['native_manifest']['path'])and native['schema']=='strata-t46-perf-native-manifest/v1','selected contact native exact object')
    records=[_SELECTED_CONTACT['record'],d['runner'],d['native_manifest']]
    for key in ('source_closure','native_closure','build','accepted_report'):
        checked([native[key]]);records.append(native[key])
    closure=load(native['native_closure']['path']);source=load(native['source_closure']['path'])
    require(native['consumed']==closure['consumed_dependencies']and native['declared_tsv']==closure['declared_sources']and native['codeobjects']==closure['codeobjects'],'selected contact consumed closure')
    def finite(values,roots):
        require(type(values)is list and len(values)==len({str(Path(x['path']).resolve())for x in values}),'selected contact duplicate identity row')
        for value in values:
            require(set(value)=={'path','bytes','sha256'}and any(Path(value['path']).resolve().is_relative_to(Path(root))for root in roots),'selected contact foreign snapshot root')
        checked(values);records.extend(values)
    require(len(native['consumed'])==counts['consumed']and len(native['declared'])==counts['declared']and len(source['records'])==counts['source_snapshots'],'selected contact exact finite counts')
    finite(native['consumed'],d['consumed_roots']);checked([native['declared_tsv']]);records.append(native['declared_tsv'])
    declared=[]
    for line in Path(native['declared_tsv']['path']).read_text(encoding='utf8').splitlines():
        relative,digest=line.split('|');value=row(Path(d['source_root'])/relative)
        require(value['sha256']==digest,'selected contact declaration SHA');declared.append(value)
    require(native['declared']==declared,'selected contact exact declarations')
    finite(declared,[d['source_root']]);finite([x['snapshot']for x in source['records']],[d['source_root']])
    require(len(native['codeobjects'])==2*counts['codeobjects_per_arch']and all(sum('--'+arch in x['path']for x in native['codeobjects'])==counts['codeobjects_per_arch']for arch in ('gfx1100','gfx1201')),'selected contact bothgfx codeobjects')
    finite(native['codeobjects'],[d['codeobject_root']])
    require(len(inputs['native_bundle_dlls'])==6 and inputs['native_bundle_dlls']==native['bundle_dlls'],'selected contact six DLL')
    finite(inputs['native_bundle_dlls'],[d['identity_root']])
    identity=native['CPU'][0]
    require(identity['flag']=='--identity'and identity['exit']==0 and identity['stderr']==''and json.loads(identity['stdout'])==dict(source_set_sha256=CONTACT_SOURCE,normal_audit_d2h=False)and identity['exe']['sha256']==CONTACT_EXE,'selected contact actual identity')
    finite([identity['exe']],[d['identity_root']])
    finite([identity[k]for k in ('command','owner','result','handle_closed','stdout_file','stderr_file','outer')],[d['identity_root']])
    result=load(identity['result']['path']);close=load(identity['handle_closed']['path'])
    require(result['wait_completed']is True and result['exit']==0 and result['handle_closed']is True and result['disposed']is True and not result['secondary_errors']and close['original_safehandle_closed']is True and close['original_process_object_disposed']is True,'selected contact identity wait/close')
    return list({x['path']:x for x in records}.values())

def parse_wait_aggregates(data,requests,binding):
    """Two typed native terminals from complete, retained stderr only."""
    require(len(requests)==2 and requests[0]['cancel']and not requests[1]['cancel'],'contact typed two requests')
    require(binding['hook_sha256']==CONTACT_HOOK,'contact aggregate hook')
    def pairs(items):
        result={}
        for key,value in items:require(key not in result,'aggregate duplicate JSON key');result[key]=value
        return result
    def nonfinite(value):raise ValueError('aggregate nonfinite '+value)
    rows=[]
    for line in data.decode('utf8').splitlines():
        if line.startswith('T46_WAIT_AGGREGATE'):
            require(line.startswith('T46_WAIT_AGGREGATE '),'aggregate prefix')
            rows.append(json.loads(line[len('T46_WAIT_AGGREGATE '):],object_pairs_hook=pairs,parse_constant=nonfinite))
    require(len(rows)==2,'exactly two aggregate rows')
    keys=set('schema mode request_id bundle_id epoch drain_confirmed collector_complete source_set_sha256 host_wall_semantics clock clock_observed_resolution_ns clock_period_num clock_period_den OS_wait_execution physical_SSD_IO expert metrics terminal_status_code generated_count stop_origin'.split())
    metric_keys=set('coverage calls iterations completed success not_ready error work open wall_ns partial_observed_ns observer_invalid'.split())
    seen=set()
    for aggregate,request_value in zip(rows,requests,strict=True):
        require(type(aggregate)is dict and set(aggregate)==keys,'aggregate exact structure')
        raw=request_value['raw'];context=raw['context'];cookie=request_value['cookie']
        require(type(cookie)is list and len(cookie)==2 and type(cookie[0])is str and type(cookie[1])is int,'aggregate typed cookie')
        uint(aggregate['epoch']);uint(aggregate['generated_count']);uint(aggregate['terminal_status_code'])
        uint(context['runtime_epoch']);uint(binding['runtime_epoch']);uint(raw['generated_count'])
        require(aggregate['request_id']==context['request_id']==cookie[0]and aggregate['epoch']==context['runtime_epoch']==cookie[1]==binding['runtime_epoch'],'aggregate request cookie/epoch')
        require(aggregate['request_id']not in seen,'aggregate duplicate request');seen.add(aggregate['request_id'])
        require(aggregate['schema']=='T46-single-wait-phase-aggregate/v1'and aggregate['mode']=='single'and aggregate['bundle_id']==context['bundle_id']==CONTACT_NATIVE and aggregate['source_set_sha256']==CONTACT_SOURCE,'aggregate exact native/source')
        terminal={'stop':0,'length':1,'cancel':2,'nonfinite':3,'error':4}
        require(aggregate['terminal_status_code']==terminal[raw['finish']]and aggregate['generated_count']==raw['generated_count']and aggregate['stop_origin']==raw['stop_origin'],'aggregate raw terminal/generated/origin')
        require(aggregate['drain_confirmed']is True and aggregate['collector_complete']is True,'aggregate incomplete collector/drain')
        require(aggregate['host_wall_semantics']=='inclusive_overlapping_API_envelopes'and aggregate['clock']=='steady_clock_nanoseconds','aggregate clock semantics')
        require(aggregate['clock_observed_resolution_ns']is None and aggregate['OS_wait_execution']is None and aggregate['physical_SSD_IO']is None and aggregate['expert']==dict(coverage='not_selected',calls=None,wall_ns=None),'aggregate unknown remains null')
        require(uint(aggregate['clock_period_num'])>0 and uint(aggregate['clock_period_den'])>0,'aggregate clock period')
        metrics=aggregate['metrics'];require(type(metrics)is dict and set(metrics)==set(WAIT_METRICS),'aggregate fixed 53 metrics')
        for metric in metrics.values():
            require(type(metric)is dict and set(metric)==metric_keys,'aggregate metric structure')
            require(metric['coverage']=='covered'and metric['observer_invalid']is False and uint(metric['open'])==0 and metric['partial_observed_ns']is None,'aggregate open/invalid/partial metric')
            for key in ('calls','iterations','completed','success','not_ready','error','work','wall_ns'):uint(metric[key])
    return dict(schema='strata-t46-contact-wait-validation/v1',package_id=ID,bundle_id=CONTACT_NATIVE,compiled_source_id=CONTACT_SOURCE,binding=binding,aggregates=rows,aggregate_count=2,metric_count=53,overlapping_envelopes_add_to_TTFT=False,physical_SSD_IO=None)

def contact_wait_evidence(attempt,validation,binding):
    receipt=load(attempt/'native-stderr.json')
    require(receipt['schema']=='strata-t46-contact-native-stderr/v1'and receipt['native_pid']==binding['owner']['engine']['pid'],'contact stderr original native owner')
    require(receipt['complete']is True and receipt['exit']==0 and receipt['log_closed']is True and not receipt['secondary_errors'],'contact stderr exit/log incomplete')
    require(receipt['package_id']==ID and receipt['bundle_id']==BUNDLE==CONTACT_NATIVE and receipt['compiled_source_id']==CONTACT_SOURCE and receipt['binding']==binding,'contact stderr source/owner binding')
    require(Path(receipt['raw']['path']).resolve()==(attempt/'native-stderr.raw').resolve(),'contact raw stderr path')
    require(Path(receipt['source_log']).resolve()==(attempt/'native.log').resolve(),'contact selected stderr source log')
    checked([receipt['raw']]);parsed=parse_wait_aggregates(Path(receipt['raw']['path']).read_bytes(),validation['requests'],binding)
    return dict(parsed,raw=receipt['raw'],capture=row(attempt/'native-stderr.json'))

def bind_candidate(input_path,proof_path):
    """Consume one exact finite candidate, including later reviewed observer fix."""
    global ID,PACKAGE,BUNDLE,HOOK,PROFILE,CANDIDATE_INPUT,CANDIDATE_PROOF,_SELECTED_CONTACT,_CONTACT_BOUND
    _CONTACT_BOUND=False
    _SELECTED_CONTACT=None
    inputs=load(input_path);proof=load(proof_path)
    require(proof['input']==row(input_path),'candidate input/proof join')
    checked([proof['package_manifest']]);manifest=load(proof['package_manifest']['path'])
    ID=inputs['candidate_package_id'];PACKAGE=Path(proof['package_root'])
    require(manifest['id']==PACKAGE.name==ID,'one finite final candidate')
    BUNDLE=inputs['native_manifest']['sha256'];require(BUNDLE==manifest['native_manifest_sha256'],'native immutable binding')
    hooks=[x for x in inputs['selected_files']if x['relative_destination']=='Strata-extensions/models/deepseek41/server_hooks.py']
    require(len(hooks)==1,'one selected observer hook');HOOK=hooks[0]['sha256']
    matches=[x['candidate']['path']for x in proof['profiles']if load(x['candidate']['path'])['context']==4096]
    require(len(matches)==1,'one candidate context4096 profile');PROFILE=Path(matches[0])
    CANDIDATE_INPUT=Path(input_path);CANDIDATE_PROOF=Path(proof_path)
    if ID==LEGACY_CONTACT['CONTACT_ID']:
        for name,value in LEGACY_CONTACT.items():globals()[name]=value
        require(row(input_path)['sha256']==CONTACT_INPUT and row(proof_path)['sha256']=='4d9ecee5d20659bb7d75b21037511a297fce1a27fe4c3f8519b8e71584eb1e89','contact pinned input/proof')
        require(proof['package_manifest']['sha256']=='977ee5c2b1f2dca1604f5023271f5204a47b9b446c81fd00caf6d705ffc197c1'and BUNDLE==CONTACT_NATIVE and HOOK==CONTACT_HOOK,'contact selected manifest/native/hook')
        cfg=load(PROFILE);require(row(cfg['exe'])['sha256']==CONTACT_EXE,'contact selected EXE')

    select_contact(inputs,proof)
    _CONTACT_BOUND=True # Commit only after all candidate and contact checks succeed.

def require(value, message):
    if not value: raise ValueError(message)

def exact_native_argv(actual,expected,configured_exe):
    """Both inputs are full argv; normalize only the bound executable path."""
    require(type(actual)is list and type(expected)is list and actual and expected and all(type(x)is str and x for x in actual+expected),'native full argv shape')
    require(Path(actual[0]).resolve()==Path(expected[0]).resolve()==Path(configured_exe).resolve()and actual[1:]==expected[1:],'actual owned native argv vs resolved configuration')

def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def row(path):
    p=Path(path).resolve()
    with p.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(path=str(p),bytes=p.stat().st_size,sha256=digest)

def save(path,value):
    # Caller owns attempt; immutable outputs cannot overwrite earlier evidence.
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def checked(records):
    for r in records: require(row(r['path'])==r,'changed source/proof: '+r['path'])

def stat(path):
    s=Path(path).stat()
    return dict(device=s.st_dev,file_id=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns)

def uint(value):
    require(type(value)is int and 0<=value<=U64,'uint64 bytes');return value

def roles(mode,weight=2097152,cut=24):
    require(mode in MODES,'mode');require(uint(weight)>0,'positive tile')
    require(type(cut)is int and 1<=cut<=39,'cut')
    if mode in MODES[:2]: return [(weight,True)]
    return [(weight,mode=='expert-assist' or cut>1),(weight,mode=='layer-split' and cut<=14)]

def minimum(mode,weight=2097152,cut=24):
    return uint(sum(w+264*int(r) for w,r in roles(mode,weight,cut)))

def budget(total,mode,weight=2097152,cut=24,assignment=192):
    """Integer explicit owner floor, matching r4 ratio_floor (never float guard)."""
    rs=roles(mode,weight,cut);base=minimum(mode,weight,cut);uint(total)
    require(total>=base,'all-role minimum')
    require(type(assignment)is int and 0<=assignment<=384,'assignment count')
    extra=total-base
    secondary=0 if len(rs)==1 else extra*(assignment if mode=='expert-assist' else 40-cut)//(384 if mode=='expert-assist' else 40)
    shares=[extra-secondary]+([secondary] if len(rs)==2 else [])
    out=[]
    for (w,hasrow),x in zip(rs,shares):
        unit=w+264*int(hasrow);target=unit+x;slots=target//unit
        out.append(dict(target=target,allocated=slots*unit,weight_slots=slots,row_slots=slots if hasrow else 0,unused=target-slots*unit))
    return dict(total=total,minimum=base,extra_primary=shares[0],extra_secondary=secondary,roles=out,allocated=sum(x['allocated']for x in out),unused=sum(x['unused']for x in out))

def select_total(available,payload,working,deferred,common_minimum):
    """One fresh noGEN observation, using accepted report-only selection."""
    ref=module('t46_ram_reference',R/'Strata-extensions/tests/secondary_cache/reference.py')
    choice=ref.dram_selection(available,payload,working,deferred)
    choice['payload']=max(choice['payload'],uint(common_minimum));uint(choice['payload'])
    choice.update(report_only=True,band_is_GEN_gate=False,reselection_count=1)
    return choice

def request():
    return dict(model=MODEL,messages=[dict(role='user',content='')],thinking=dict(type='disabled'),temperature=0,top_k=0,top_p=1,min_p=0,seed=0,max_tokens=2,logprobs=True,top_logprobs=3,stream=True,stream_options=dict(include_usage=True),return_progress=True)

def f32bits(x):
    require(type(x)in(int,float)and math.isfinite(x)and x<=0,'finite logprob')
    bits=struct.unpack('<I',struct.pack('<f',x))[0]
    return (~bits & 0xffffffff) if bits & 0x80000000 else bits | 0x80000000

def lp_equal(actual,want):
    require(abs(f32bits(actual[0])-f32bits(want[0]))<=2,'selected LP >2ULP')
    require(len(actual[1])==len(want[1])==3,'top3 coverage')
    for (ai,ap),(wi,wp) in zip(actual[1],want[1],strict=True):
        require(type(ai)is int and ai==wi and abs(f32bits(ap)-f32bits(wp))<=2,'ordered top3 LP >2ULP')

def numeric(raw,baseline=None):
    require(list(raw['original_token_ids'])==IDS and raw['generated_count']==2 and raw['finish']=='length'and raw['generation_success']is True,'raw complete IDs/count/length')
    require(raw.get('stop_origin')=='limit' and len(raw.get('logprobs',[]))==2,'raw LP/limit')
    q=load(Q);first=[q['selected_logprob_f32'],[(x['token_id'],x['logprob'])for x in q['top_logprobs']]]
    lp_equal(raw['logprobs'][0],first)
    require(len(raw['logprobs'][1][1])==3,'second token top3')
    if baseline is not None: lp_equal(raw['logprobs'][1],baseline['logprobs'][1])
    return dict(first_reference='old independent Q, local 2ULP',second_reference='final single actual observation' if baseline else 'new single observation; no old Q exists')

def sse_join(chunks,replayed):
    require(chunks and chunks[-1]=='[DONE]','HTTP SSE DONE')
    content='';lps=[];finish=[];usages=[];metadata=None
    for ch in chunks[:-1]:
        require(type(ch)is dict and ch.get('model')==MODEL,'SSE model')
        require(type(ch.get('id'))is str and bool(ch['id'])and ch.get('object')=='chat.completion.chunk'and type(ch.get('created'))is int and ch['created']>=0,'saved SSE observed metadata')
        observed=(ch['id'],ch['object'],ch['created'])
        if metadata is None:metadata=observed
        require(observed==metadata,'SSE observed metadata consistency')
        if ch.get('usage')is not None:usages.append(ch['usage'])
        for c in ch.get('choices',[]):
            require(c['index']==0,'one SSE choice')
            content+=c.get('delta',{}).get('content','') or ''
            lps+=c.get('logprobs',{}).get('content',[]) if c.get('logprobs')else []
            if c.get('finish_reason')is not None:finish.append(c['finish_reason'])
    response=replayed['response'];choice=response['choices'][0]
    require(content==choice['message']['content']and lps==choice['logprobs']['content'],'raw DTO -> Codec/Recipe -> HTTP text/LP/bytes join')
    require(finish==['length']and len(usages)==1,'HTTP finish/usage closure')
    for k,v in dict(prompt_tokens=4,completion_tokens=2,total_tokens=6).items():
        require(type(usages[0].get(k))is int and usages[0][k]==v and response['usage'][k]==v,'HTTP/Recipe usage')
    require(list(replayed['recipe_input_ids'])==IDS and replayed['success']is True,'Recipe exact raw ID consumption')
    return dict(text=content,usage=usages[0],observed_SSE_metadata=dict(id=metadata[0],object=metadata[1],created=metadata[2]),raw_to_Recipe_to_SSE=True)

def raw_lines(capture,cookie):
    rows=[json.loads(x)for x in Path(capture).read_text(encoding='utf8').splitlines()]
    return [r['line'] for r in rows if r['event']=='receive'and r['cookie']==cookie and isinstance(r.get('line'),str)and r['line'].startswith('{')]

def control_GEN(line,sampling,cookie):
    """Parse the selected hook's key=value GEN grammar, not text prefixes."""
    tokens=line.split();require(tokens[:2]==['GEN','2']and len(tokens)==len(sampling)+5,'control GEN schema')
    options={}
    for token in tokens[2:-1]:
        key,separator,value=token.partition('=')
        require(separator and key not in options and value,'control GEN unique options');options[key]=value
    require(set(options)==set(sampling)|{'request_id','epoch'}and options['request_id']==cookie[0]and options['epoch']==str(cookie[1]),'control GEN option/cookie schema')
    for key,want in sampling.items():
        text=options[key]
        require(re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',text)is not None,'control GEN finite numeric syntax')
        number=Decimal(text)
        require(number.is_finite()and number==Decimal(int(want)if type(want)is bool else str(want)),'control GEN exact sampler value')
    ids=tokens[-1].split(',')
    require(all(re.fullmatch(r'[0-9]+',value)is not None for value in ids)and [int(value)for value in ids]==PROMPT,'control GEN exact input IDs')

def cancel_prefix(path,spec,binding):
    """Prove only the first fixture cancellation before sending completion.

    The live observer remains open; its final two-request validator is unchanged.
    This function consumes the create-only prefix, never a synthetic summary.
    """
    observer=module('t46_cancel_order',B/'observer-capture.py')
    rows=[json.loads(line)for line in Path(path).read_text(encoding='utf8').splitlines()]
    require(spec['cancel_first_matching_begin']is True and len(rows)>=8,'declared cancellation prefix')
    prior=-1
    for i,r in enumerate(rows):
        require(r.get('schema')=='strata-t46-observer/v1'and type(r.get('sequence'))is int and r['sequence']==i and r.get('run_id')==spec['run_id']and type(r.get('monotonic_ns'))is int and r['monotonic_ns']>=prior,'control observer sequence/run/clock')
        prior=r['monotonic_ns']
    header=rows[0];require(header['event']=='header','control observer header')
    for key in ('owner','hook_sha256','runtime_epoch'):require(header.get(key)==binding[key],'control actual binding: '+key)
    for key in ('package_id','bundle_id','mode'):require(header.get(key)==spec[key],'control spec/header: '+key)
    request=rows[1];cookie=request.get('cookie')
    require(request.get('event')=='request'and type(cookie)is list and len(cookie)==2 and type(cookie[0])is str and bool(cookie[0])and type(cookie[1])is int and cookie[1]==binding['runtime_epoch']and request.get('owner')==binding['owner']and request.get('runtime_epoch')==binding['runtime_epoch'],'control request authority/cookie')
    require(spec['package_id']==ID and spec['bundle_id']==BUNDLE and binding['hook_sha256']==HOOK and spec['input_ids']==PROMPT and spec['max_tokens']==2,'control selected source/spec')
    sampling=dict(temperature=0,top_k=0,top_p=1,min_p=0,seed=0,logprobs=True,top_logprobs=3)
    require(spec['sampling']==sampling and all(type(spec['sampling'][k])is type(v)for k,v in sampling.items()),'control exact effective sampling')
    group=dict(cookie=cookie,send=[],lines=[],cancel=False,timeline=[])
    for r in rows[2:]:
        event=r['event'];require(event in('send','receive','cancel_fixture')and r.get('cookie')==cookie,'control unbound event/error')
        group['timeline'].append(r)
        if event=='send':group['send'].append(r['line'])
        elif event=='receive':group['lines'].append(r['line'])
        else:
            require(not group['cancel'],'duplicate control cancellation');group['cancel']=True
    require(group['cancel'],'control fixture missing');observer.validate_order(group)
    suffix=' request_id='+cookie[0]+' epoch='+str(cookie[1]);gen=[s for s in group['send']if s.startswith('GEN ')]
    require(len(gen)==1,'control GEN count');control_GEN(gen[0],spec['sampling'],cookie)
    require([s for s in group['send']if s.startswith('STOP ')]==['STOP'+suffix+' reason=user_cancel'],'control typed STOP')
    dto=None;done=None
    for line in group['lines']:
        require(type(line)is str and not line.startswith('ERR ')and done is None,'control native error/EOF/afterDONE')
        if line.startswith('{'):
            frame=observer.DTO.parse_frame(line)
            if dto is None:
                context={k:frame[k]for k in observer.DTO.CONTEXT}
                require(context['bundle_id']==BUNDLE and(context['request_id'],context['runtime_epoch'])==tuple(cookie),'control DTO authority')
                dto=observer.DTO.GenerationDTO(context)
            dto.feed(line)
        elif line.startswith('DONE '):done=uint(int(line.split()[1]))
        elif line.startswith('INFO '):json.loads(line[5:])
        else:require(line.startswith('PP '),'control unknown native line')
    require(dto is not None and done is not None,'control terminal missing')
    raw=dto.result()
    require(raw['finish']=='cancel'and raw['stop_origin']=='user_cancel'and done==raw['generated_count'],'control typed cancel terminal/count')
    return dict(schema='strata-t46-control-cancellation/v1',prefix=row(path),cookie=cookie,binding=binding,raw=raw,native_DONE=done,numerical_qualification=False,HTTP_completion=False)

def fresh_INFO_boundary(attempt,spec,binding):
    """Closed second request on the still-open original observer, not a fake summary."""
    observer=module('t46_INFO_boundary',B/'observer-capture.py')
    rows=[json.loads(x)for x in Path(spec['output']).read_text(encoding='utf8').splitlines()]
    previous=-1
    for i,value in enumerate(rows):
        require(value.get('sequence')==i and value.get('run_id')==spec['run_id']and value.get('schema')=='strata-t46-observer/v1'and type(value.get('monotonic_ns'))is int and value['monotonic_ns']>=previous,'INFO observer order')
        previous=value['monotonic_ns']
    header=rows[0]
    require(spec['package_id']==ID and spec['bundle_id']==BUNDLE and binding['hook_sha256']==HOOK and spec['mode']in MODES,'INFO selected candidate')
    require(header['event']=='header'and all(header.get(k)==binding[k]for k in('owner','hook_sha256','runtime_epoch'))and all(header.get(k)==spec[k]for k in('package_id','bundle_id','mode')),'INFO observer binding')
    requests=[v for v in rows if v['event']=='request']
    require(len(requests)==2 and requests[0]['cookie']!=requests[1]['cookie']and all(v['owner']==binding['owner']and v['cookie'][1]==binding['runtime_epoch']for v in requests),'INFO two owned cookies')
    saved=load(attempt/'control-cancellation.json')
    require(saved['cookie']==requests[0]['cookie']and saved['binding']==binding and saved['raw']['finish']=='cancel','INFO prior control')
    cookie=requests[1]['cookie'];tail=rows[requests[1]['sequence']+1:]
    if tail and tail[-1]['event']=='summary':tail=tail[:-1]
    require(tail and all(v['event']in('send','receive')and v.get('cookie')==cookie for v in tail),'INFO complete event boundary')
    group=dict(cookie=cookie,cancel=False,timeline=tail);observer.validate_order(group)
    commands=[v['line']for v in tail if v['event']=='send']
    require(len(commands)==1,'INFO complete GEN');control_GEN(commands[0],spec['sampling'],cookie)
    dto=None;done=None
    for value in tail:
        if value['event']!='receive':continue
        line=value['line'];require(type(line)is str and done is None,'INFO native EOF/after DONE')
        if line.startswith('{'):
            frame=observer.DTO.parse_frame(line)
            if dto is None:
                context={k:frame[k]for k in observer.DTO.CONTEXT}
                require(context['bundle_id']==BUNDLE and(context['request_id'],context['runtime_epoch'])==tuple(cookie),'INFO complete DTO binding')
                dto=observer.DTO.GenerationDTO(context)
            dto.feed(line)
        elif line.startswith('DONE '):
            require(line.split()==['DONE','2'],'INFO complete DONE');done=value
        else:require(line.startswith('PP '),'INFO unexpected complete line')
    raw=dto.result()if dto is not None else {}
    require(done is not None and raw.get('generation_success')is True and raw.get('generated_count')==2,'INFO successful complete terminal')
    http=load(attempt/'complete-http.json');clock=load(attempt/'complete-clock.json')
    require(http['HTTP_DONE']is True and load(attempt/'complete-sse.json')[-1]=='[DONE]'and type(clock.get('end_ns'))is int,'INFO complete HTTP boundary')
    return dict(binding=binding,cookie=cookie,cookies=[v['cookie']for v in requests],native_DONE=done,HTTP=row(attempt/'complete-http.json'),HTTP_clock=row(attempt/'complete-clock.json'),HTTP_end_ns=clock['end_ns'])

def fresh_INFO_receipt(attempt,config,binding,spec,info):
    receipt=load(attempt/'fresh-INFO-receipt.json');boundary=fresh_INFO_boundary(attempt,spec,binding)
    require(receipt['ok']is True and receipt['error']is None and receipt['boundary']==boundary and receipt['config']==row(attempt/'config.json'),'fresh INFO receipt binding')
    require(receipt['send']=='INFO'and len(receipt['responses'])==1 and receipt['responses'][0]['line'].startswith('INFO '),'fresh INFO response')
    response=receipt['responses'][0];parsed=json.loads(response['line'][5:])
    require(type(parsed)is dict and type(parsed.get('core_position'))is int and parsed['core_position']>=0 and parsed==receipt['parsed']==info==load(attempt/'argv-and-INFO.json')['final'],'fresh INFO parsed identity')
    require(type(receipt['send_ns'])is int and receipt['send_ns']>=max(boundary['native_DONE']['monotonic_ns'],boundary['HTTP_end_ns'])and type(response['monotonic_ns'])is int and response['monotonic_ns']>=receipt['send_ns'],'fresh INFO response clock')
    require(receipt['owner_before']==receipt['owner_after']==binding['owner']['engine']and type(receipt['generation'])is int,'fresh INFO same owner')
    return row(attempt/'fresh-INFO-receipt.json')

def role_info(config,info):
    mode=config['placement']['mode'];total=config['cache_budget']['ram_cache_payload_bytes']
    expected=budget(total,mode,config.get('tile_bytes',2097152),config['placement'].get('cut',24),len(config['placement'].get('assignment',list(range(192)))))
    require(info['ram_cache_payload_bytes']==expected['allocated'],'allocated RAM vs target/unused')
    p=expected['roles'][0]
    require(info['ram_slots']==p['weight_slots']and info['row_ram_slots']==p['row_slots'],'actual primary explicit slot floor')
    if mode in MODES[:2]:
        require(info['resolved_ram_cache_target_bytes']==total and info['cache_unused_ram_bytes']==expected['unused'],'single/cache target and unused')
        secondary=uint(info['cache_secondary_device_owned'])
        require(secondary==uint(info['cache_secondary_slots'])*uint(info['cache_slot_capacity']),'cache secondary allocated slots')
        require(uint(info['cache_secondary_target_bytes'])==secondary+uint(info['cache_secondary_unused_bytes']),'cache device target/allocated/unused')
    else:
        s=expected['roles'][1];secondary=uint(info['actual_secondary_device_owned'])
        require(info['secondary_ram_slots']==s['weight_slots']and info['secondary_row_ram_slots']==s['row_slots'],'actual secondary explicit slot floor')
        require(info['mode_ram_unused_bytes']==expected['unused']and info['mode_ram_extra_primary_bytes']==expected['extra_primary']and info['mode_ram_extra_secondary_bytes']==expected['extra_secondary'],'integer all-role target distribution')
    require(uint(info['actual_device_owned'])==uint(info['actual_primary_device_owned'])and uint(info['actual_all_role_device_owned'])==info['actual_device_owned']+secondary,'device aliases: primary once plus secondary once')
    secondary_pci=config['placement']['secondary']
    require(info['primary_pci']==config['primary_pci']and info['requested_secondary_pci']==secondary_pci and info['actual_secondary_pci']==secondary_pci,'actual mode PCI owners')
    return expected

def qualify(attempt,config,binding,codec,prepared,tokenizer,baseline=None,persist=True):
    contact_selected() # Failed rebind cannot re-enter qualification using old globals.
    observer=module('t46_existing_capture',B/'observer-capture.py')
    spec=load(attempt/'spec.json');validation=observer.validate_capture(spec['output'],spec,binding)
    control,complete=validation['requests']
    events=[json.loads(x)for x in Path(spec['output']).read_text(encoding='utf8').splitlines()]
    for request_value in validation['requests']:
        commands=[e['line']for e in events if e['event']=='send'and e.get('cookie')==request_value['cookie']and e['line'].startswith('GEN ')]
        require(len(commands)==1,'qualified request GEN count')
        control_GEN(commands[0],spec['sampling'],request_value['cookie'])
    wait=contact_wait_evidence(attempt,validation,binding)if contact_selected() and config['placement']['mode']=='single' else None
    require(control['cancel']and not complete['cancel']and control['cookie']!=complete['cookie'],'typed control before fresh completion')
    raw=complete['raw'];comparison=numeric(raw,baseline)
    replay=codec.CodecSession(raw['context'],prepared.prepared,tokenizer.recipe)
    for line in raw_lines(spec['output'],complete['cookie']):replay.feed(line)
    replayed=replay.end_of_stream();require(replayed['raw']==raw,'DTO replay identity')
    joined=sse_join(load(attempt/'complete-sse.json'),replayed)
    info=load(attempt/'final-info.json')
    fresh=fresh_INFO_receipt(attempt,config,binding,spec,info)if contact_selected()else None
    require(info['core_position']==5,'Core position 5; final ID unprocessed')
    helper=module('t46_ready_helper',R/'Strata-extensions/control/deepseek_launch.py');helper.validate_ready_info(config,info)
    require(info['configured_mode']==config['placement']['mode']and info['effective_mode']==config['placement']['mode'],'mode observed')
    expected=role_info(config,info)
    close=load(attempt/'cleanup.json');require(close['ok']is True,'regular cleanup incomplete')
    loaded=module('t46_existing_normal2',R/'build-deepseek-t22/normal-wrapper.py').runtime_modules(info,Path(config['exe']).parent)
    require(loaded['complete']is True,'loaded owned DLL observation incomplete')
    control_info=control['info'][-1] if control['info']else {}
    pipe_tokens=[];send_clock=None
    for e in events:
        if e.get('cookie')!=complete['cookie']:continue
        if e['event']=='send'and e['line'].startswith('GEN '):send_clock=e['monotonic_ns']
        if e['event']=='receive'and isinstance(e.get('line'),str)and e['line'].startswith('{'):
            frame=json.loads(e['line'])
            if frame['kind']=='token_batch':pipe_tokens.extend([e['monotonic_ns']]*len(frame['ids']))
    require(len(pipe_tokens)==2 and send_clock is not None,'raw model token clocks')
    timing=load(attempt/'clock.json');timing['native_pipe']=dict(domain='host monotonic observer after single native reader; includes sync log overhead',GEN_send_ns=send_clock,token_receipt_ns=pipe_tokens,TTFT_seconds=(pipe_tokens[0]-send_clock)/1e9,TPOT_seconds=(pipe_tokens[1]-pipe_tokens[0])/1e9 if pipe_tokens[1]>pipe_tokens[0]else None,coalesced_or_resolution_limited=pipe_tokens[1]==pipe_tokens[0],GPU_kernel_or_SSD_time=False)
    result=dict(schema='strata-t46-actual-mode/v1',mode=config['placement']['mode'],package_id=ID,bundle_id=BUNDLE,owner=binding['owner'],config=row(attempt/'config.json'),capture=validation['capture'],raw=raw,comparison=comparison,joined=joined,typed_control=dict(cookie=control['cookie'],fresh_cookie=complete['cookie'],generated=control['raw']['generated_count'],info=control_info,inflight_qualification=False,processed_zero_is_not_inflight=True),budget=expected,info=info,loaded_runtime=loaded,cleanup=row(attempt/'cleanup.json'),memory=row(attempt/'memory.json'),clock=timing,actual_model=True,CPU_fixture=False,pilot=True,OS_physical_cold=None,ordered_mode_observation=True,observer_sync_IO_overhead=True,performance_generalized=False)
    if wait is not None:result['wait_aggregate']=wait
    if fresh is not None:result['fresh_INFO']=fresh
    if persist:
        for name,value in [('observer-validation',validation),('raw-control',control),('raw-complete',complete),('service-result',replayed),('numerical-comparison',comparison),('runtime-DLLs',loaded),('timing',timing),('counter-evidence',dict(info=info,source_basis='sealed immutable r4 Primary/quant/producer union',direct_tile_key_trace=None,physical_cold=None))]:
            save(attempt/(name+'.json'),value)
        save(attempt/'verification.json',result)
        if wait is not None:save(attempt/'wait-validation.json',wait)
    return result

def replay_final_single_numeric(numeric_path):
    """Read-only publisher replay of saved actual-single finite evidence.

    Uses the same qualify/DTO/Recipe/SSE/LP checks as the original runner.
    No file creation, engine construction, subprocess, CLI, HTTP or publication.
    """
    numeric_path=Path(numeric_path).resolve();value=load(numeric_path)
    require(value['schema']=='strata-t46-final-single-numeric/v1'and value['mode']=='single'and value['actual_native']is True and value['actual_HTTP_SSE']is True and value['complete_request_count']==value['control_request_count']==1 and value['normal_numeric_qualified']is True and value['wholeT46_complete']is False and not value.get('CPU_fixture',False),'actual final single numeric schema/scope')
    refs=[v for v in value.values()if isinstance(v,dict)and set(v)=={'path','bytes','sha256'}]
    checked(refs);bind_candidate(value['input']['path'],value['candidate']['path'])
    if contact_selected():require(value.get('fresh_INFO')==row(numeric_path.parent/'fresh-INFO-receipt.json'),'numeric mandatory fresh INFO receipt ref')
    require(value['package_manifest']==row(PACKAGE/'evidence/package-manifest.json')and value['Q_expectation']==row(Q),'numeric selected manifest/Q exact')
    smap=load(value['source_map']['path']);checked(smap['records'])
    require(smap['package_id']==ID and smap['bundle_id']==BUNDLE,'numeric reviewed source map candidate/native')
    require(any(r==row(__file__)for r in smap['records']),'numeric replay implementation exact source')
    seal_value=load(value['seal']['path'])
    require(seal_value['candidate_input']==value['input']and seal_value['candidate_proof']==value['candidate']and Path(value['source_map']['path']).parent==Path(value['seal']['path']).parent,'single seal/source-map/input join')
    cfg=load(value['config']['path']);body=load(value['request']['path']);spec=load(value['observer_spec']['path'])
    require(body==request()and cfg['context']==4096 and cfg['placement']['mode']=='single'and cfg['runtime_package']['id']==ID and cfg['bundle_id']==BUNDLE,'actual saved single body/config')
    require(spec['run_id']==value['run_id']and spec['package_id']==ID and spec['bundle_id']==BUNDLE and Path(spec['output']).resolve()==Path(value['observer_capture']['path']).resolve(),'numeric spec/capture exact')
    before=load(value['model9_before']['path']);after=load(value['model9_after']['path'])
    require(before==after==protected_sources(cfg),'actual Model9 accepted identities before/after/current')
    protected_before=load(value['protected_before']['path']);require(protected_before==load(value['protected_after']['path']),'numeric protected before/after');checked(protected_before)
    owner=load(value['owner']['path']);binding=owner['binding']
    require(binding['runtime_epoch']==cfg['runtime_epoch']and binding['hook_sha256']==HOOK,'numeric owner epoch/hook')
    for role in ('server','engine'):
        identity=binding['owner'][role];require(type(identity['pid'])is int and identity['pid']>0 and type(identity['birth'])in(int,float)and math.isfinite(identity['birth']),'numeric owner PID/birth')
    argv=load(value['argv_and_INFO']['path']);helper=module('t46_numeric_helper',R/'Strata-extensions/control/deepseek_launch.py')
    require(argv['epoch']==cfg['runtime_epoch'],'numeric actual native epoch')
    exact_native_argv(argv['native_argv'],helper.native_command(cfg),cfg['exe'])
    # Instantiate only the real selected Service around a CPU shell. The real
    # engine class is installed but never constructed.
    previous_path=list(sys.path);key='STRATA_FAMILY_SOURCE_ROOT';old=os.environ.get(key)
    try:
        from types import SimpleNamespace
        sys.path[:0]=[str(PACKAGE/'base'),str(PACKAGE/'base/tools')];os.environ[key]=str(PACKAGE/'base')
        server=module('serve.server',PACKAGE/'native/server/serve/server.py');hook=module('t46_numeric_selected_hook',PACKAGE/'Strata-extensions/models/deepseek41/server_hooks.py')
        require(hook.install(server,cfg),'numeric selected Service hook');tokenizer=hook.TokenizerFacade(PACKAGE/'resources/tokenizer.json')
        shell=SimpleNamespace(max_context=4096,info=argv['final'],batch=0,alive=lambda:True)
        service=server.Service(shell,tokenizer,None,sampling_defaults={});ids,thinking,maximum=service.prepare(body['messages'],None,{},req=body)
        require(list(ids)==PROMPT and not thinking and maximum==2,'numeric actual Service.prepare saved body')
        result=qualify(numeric_path.parent,cfg,binding,hook.codec,ids,tokenizer,persist=False)
        if contact_selected():require(result['fresh_INFO']==value['fresh_INFO'],'numeric replayed fresh INFO receipt ref')
        same=lambda a,b:json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)
        stored=load(value['raw_complete']['path'])['raw']
        require(same(result['raw'],stored),'saved complete DTO vs replay')
        capture=module('t46_numeric_capture',B/'observer-capture.py').validate_capture(value['observer_capture']['path'],spec,binding)
        require(same(capture,load(value['observer_validation']['path']))and same(capture['requests'][0],load(value['raw_control']['path']))and same(capture['requests'][1],load(value['raw_complete']['path'])),'stored observer/control/complete vs replay')
        session=hook.codec.CodecSession(result['raw']['context'],ids.prepared,tokenizer.recipe)
        for rawline in raw_lines(value['observer_capture']['path'],capture['requests'][1]['cookie']):session.feed(rawline)
        require(same(session.end_of_stream(),load(value['service_result']['path'])),'saved Service/Recipe result vs raw replay')
        require(same(result['comparison'],load(value['numerical_comparison']['path']))and same(result['loaded_runtime'],load(value['runtime_DLLs']['path']))and same(result['clock'],load(value['timing']['path'])),'saved numeric/DLL/timing vs replay')
        require(load(value['counter_evidence']['path'])['info']==argv['final']==result['info'],'saved final INFO/counter closure')
        require(load(value['cleanup']['path'])['ok']is True,'numeric regular cleanup')
        if contact_selected():
            require(value['native_stderr']==row(numeric_path.parent/'native-stderr.raw')and value['native_stderr_capture']==row(numeric_path.parent/'native-stderr.json')and value['wait_validation']==row(numeric_path.parent/'wait-validation.json'),'numeric exact contact stderr refs')
            require(same(result['wait_aggregate'],load(value['wait_validation']['path'])),'numeric contact aggregate replay')
        return dict(numeric=row(numeric_path),source_map=value['source_map'],candidate=value['candidate'],replayed=True,write_count=0,native_count=0,CLI_API_count=0,raw=result['raw'])
    finally:
        sys.path[:]=previous_path
        if old is None:os.environ.pop(key,None)
        else:os.environ[key]=old

def final_single_numeric(attempt,seal_path):
    a=Path(attempt);seal_value=load(seal_path);spec=load(a/'spec.json')
    fragments=dict(candidate=row(CANDIDATE_PROOF),package_manifest=row(PACKAGE/'evidence/package-manifest.json'),input=row(CANDIDATE_INPUT),seal=row(seal_path),source_map=row(Path(seal_path).parent/'source-map.json'),config=row(a/'config.json'),request=row(a/'request.json'),observer_spec=row(a/'spec.json'),observer_capture=row(a/'observer.jsonl'),observer_validation=row(a/'observer-validation.json'),raw_control=row(a/'raw-control.json'),raw_complete=row(a/'raw-complete.json'),SSE=row(a/'complete-sse.json'),service_result=row(a/'service-result.json'),Q_expectation=row(Q),numerical_comparison=row(a/'numerical-comparison.json'),owner=row(a/'owner.json'),argv_and_INFO=row(a/'argv-and-INFO.json'),runtime_DLLs=row(a/'runtime-DLLs.json'),model9_before=row(a/'model9-before.json'),model9_after=row(a/'model9-after.json'),protected_before=row(a/'protected-before.json'),protected_after=row(a/'protected-after.json'),cleanup=row(a/'cleanup.json'),timing=row(a/'timing.json'),counter_evidence=row(a/'counter-evidence.json'))
    if contact_selected():fragments.update(native_stderr=row(a/'native-stderr.raw'),native_stderr_capture=row(a/'native-stderr.json'),wait_validation=row(a/'wait-validation.json'),fresh_INFO=row(a/'fresh-INFO-receipt.json'))
    checked(list(fragments.values()))
    save(a/'final-single-numeric.json',dict(schema='strata-t46-final-single-numeric/v1',run_id=spec['run_id'],**fragments,mode='single',actual_native=True,actual_HTTP_SSE=True,complete_request_count=1,control_request_count=1,normal_numeric_qualified=True,wholeT46_complete=False))
    return row(a/'final-single-numeric.json')

def safe_cleanup(state,read_state,owned,stop,status,models,post,save_log):
    """T33 ownercheck -> usual stop -> status/models -> birth/listener postflight.

    Observation/save errors never bypass the following close operations.
    Unknown or foreign owner never receives stop.
    """
    errors=[];stopped=False
    try:
        fresh=read_state()
        require(state is not None and fresh is not None and fresh.get('pid')==state.get('pid')and fresh.get('created')==state.get('created'),'owner changed/unknown; no stop')
        owned(fresh);stop();stopped=True
    except BaseException as e:errors.append(dict(stage='usual-stop',error=repr(e)))
    for name,fn in [('status',status),('models',models),('postflight',post)]:
        try:fn()
        except BaseException as e:errors.append(dict(stage=name,error=repr(e)))
    result=dict(ok=stopped and not errors,stopped=stopped,errors=errors)
    try:save_log(result)
    except BaseException as e:result['ok']=False;result['errors'].append(dict(stage='cleanup-log',error=repr(e)))
    return result

def publication_join(publication,numeric_review,single_record):
    require(publication is not None and publication['schema']=='strata-t46-publication/v1'and publication['package_id']==ID and publication['complete']is True and publication['result']=='success','known-old helper/provider +6profile publication pending')
    require(publication['numeric_review']==numeric_review and publication['numeric_verification']==single_record,'publication numeric/review exact join')
    proof=load(CANDIDATE_PROOF);manifest=proof['package_manifest']
    require(publication['package_manifest']==manifest,'publication final manifest')
    refs=[publication[k]for k in ('numeric_review','numeric_verification','publication_input','source_map','package_manifest')]
    checked(refs)
    expected={str((Path('C:/Develop/AI/Strata-extensions')/p).resolve()):row(R/'Strata-extensions'/p)['sha256']for p in ('control/deepseek_launch.py','control/providers/deepseek41.py')}
    for p in proof['profiles']:expected[str(Path(p['destination']).resolve())]=p['candidate']['sha256']
    records=publication['installed_records']
    require(len(records)==len({str(Path(x['path']).resolve())for x in records})==8,'eight unique installed targets')
    require({str(Path(x['path']).resolve()):x['sha256']for x in records}==expected,'exact two new helpers and candidate six profiles')
    checked(records)
    single=load(single_record['path'])
    require(single['schema']=='strata-t46-final-single-numeric/v1'and single['candidate']==row(CANDIDATE_PROOF)and single['package_manifest']==manifest and single['input']==row(CANDIDATE_INPUT),'published numeric/source candidate exact')
    return True

def verify_prior_records(previous):
    for x in previous:
        require(x.get('actual_model')is True and x.get('CPU_fixture')is False and x['package_id']==ID and x['bundle_id']==BUNDLE,'actual immutable prior evidence required')
        require('verification'in x,'previous saved verification record required')
        checked([x['verification']]);verified=load(x['verification']['path'])
        require(all(k in x and x[k]==v for k,v in verified.items()),'previous receipt differs from saved verification')
        checked([verified['config'],verified['capture'],verified['cleanup'],verified['memory']])
        config=load(verified['config']['path'])
        require(x['config_total_RAM']==config['cache_budget']['ram_cache_payload_bytes'],'previous explicit RAM vs verified config')

def stage_receipts(mode,previous,numeric_review=None,publication=None):
    require(mode in MODES,'stage mode')
    expected=list(MODES[:MODES.index(mode)])
    require([x['mode']for x in previous]==expected,'four-mode stage order')
    baseline=None;verify_prior_records(previous)
    if mode!='single':
        require(numeric_review is not None,'candidate numeric independent review pending')
        require(set(numeric_review)=={'numeric','reviewed_source_map','existing_review_record','scope'}and numeric_review['scope']=='T46-final-single-publication-prerequisite','accepted numeric envelope exact fields/scope')
        require(numeric_review['numeric']==previous[0]['numeric_record'],'accepted actual single exact numeric')
        single=load(previous[0]['numeric_record']['path'])
        require(numeric_review['reviewed_source_map']==single['source_map'],'single numeric/pre-G reviewed source map')
        checked([numeric_review[k]for k in ('numeric','reviewed_source_map','existing_review_record')])
        checked([single['raw_complete'],single['config']])
        baseline=load(single['raw_complete']['path'])['raw'];numeric(baseline)
        require(previous[0]['raw']==baseline and previous[0]['config']==single['config'],'single receipt baseline vs accepted actual numeric')
        require(all(x['numeric_record']==numeric_review['numeric']for x in previous),'all prior modes use accepted single numeric')
        # publication.source_map is the publisher's operation/input domain;
        # numeric.source_map is the separately accepted single pre-G domain.
        publication_join(publication,numeric_review['existing_review_record'],previous[0]['numeric_record'])
    totals={x['config_total_RAM']for x in previous}
    require(len(totals)<=1,'same explicit total RAM across modes')
    return dict(entry='candidate prepared Service/HTTP'if mode=='single'else'usual CLI mode-only',completed_before=len(previous),single_baseline=baseline,wait_is_existing_approved_stage=True,new_human_GO=False)

def protected_sources(config):
    accepted=module('t46_original_model',R/'Strata-extensions/tests/layer_split/build_verify.py').original_sources()
    require([str(Path(x['source'][4]).resolve())for x in accepted['sources']]==[str(Path(p).resolve())for p in config['native_paths']],'accepted original Model9 paths')
    return accepted

def seal(destination,evidence=None):
    out=Path(destination).resolve();require(out.is_relative_to(HERE),'ignored runner directory only');out.mkdir(exist_ok=False)
    cfg=load(PROFILE);package=load(PACKAGE/'evidence/package-manifest.json')
    require(package['id']==ID,'final package ID')
    records=[row(p)for p in [Path(__file__),HERE/'live.py',HERE/'test_contact_binding.py',Q,PROFILE,B/'actual-mode-addendum-r1.md',B/'actual-mode-addendum-r2-draft.md',B/'publication-join-plan-r2.md',B/'observer-capture.py',CANDIDATE_INPUT,CANDIDATE_PROOF,PACKAGE/'evidence/package-manifest.json',MEMORY,MEMORY.parent/'eager_bench.py',MEMORY.parent/'eager_contract.json',R/'build-deepseek-t22/normal-wrapper.py',R/'build-deepseek-t33/normal-identity-entry-attempt-2/run.py',R/'Strata-extensions/control/deepseek_launch.py',R/'Strata-extensions/control/contracts.py',R/'Strata-extensions/tests/layer_split/build_verify.py',R/'Strata-extensions/tests/secondary_cache/reference.py',R/'Strata-extensions/tests/secondary_cache/build_verify.py',DATA/'strata.cmd',DATA/'strata_cli.py',DATA/'manage_runtime.py',DATA/'official_runtime.py',DATA/'profile_defaults.py',DATA/'model_catalog.py',Path('C:/Develop/AI/Strata/tools/strata_mcp.py'),*(evidence or [])]]
    checked(package['files']);records+=package['files']+[package['base_python']]
    inputs=load(CANDIDATE_INPUT);native=load(inputs['native_manifest']['source'])
    # Freeze immutable r4's own finite source/build records, never live T36 source.
    records.append(row(inputs['native_manifest']['source']));records+=inputs['native_bundle_dlls']
    def walk(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str)and 'sha256'in value and Path(value['path']).is_file():
                actual=row(value['path']);require(actual['sha256']==value['sha256'],'native/source SHA');records.append(actual)
            for x in value.values():walk(x)
        elif isinstance(value,list):
            for x in value:walk(x)
    # Native build preserves original+snapshot rows. Only immutable snapshot
    # rows are current qualification; original live T36 paths may have moved.
    def native_walk(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str)and 'sha256'in value and Path(value['path']).is_file()and Path(value['path']).resolve().is_relative_to((B/'native-union-build-r4').resolve()):
                actual=row(value['path']);require(actual['sha256']==value['sha256'],'immutable r4 snapshot SHA');records.append(actual)
            for x in value.values():native_walk(x)
        elif isinstance(value,list):
            for x in value:native_walk(x)
    if contact_selected():
        records+=contact_native_records(inputs,native)
        prior=row(ORIGINAL_HERE/'one-noGEN-r5-attempt-01/calibration.json');require(prior['sha256']=='39edcf574c00e40048ba5bacc8aa652ff7f19c9d1ec202b04a90b78de99a2398','contact prior calibration source');records.append(prior)
    else:native_walk(native)
    # New hook's test/CPU and previous history are records in the finite input.
    walk(inputs.get('observer_extension',{}))
    records=list({str(Path(x['path']).resolve()):dict(x,bytes=Path(x['path']).stat().st_size)for x in records}.values())
    checked(records);originals=protected_sources(cfg)
    records += [row(originals[k]['path'])for k in ('accepted_receipt','accepted_T10')]
    records += [row(R/'build-deepseek-t10/sources.tsv')]
    save(out/'source-map.json',dict(schema='strata-t46-actual-source-map/v1',records=records,original_Model9=originals,package_id=ID,bundle_id=BUNDLE))
    save(out/'seal.json',dict(schema='strata-t46-actual-preseal/v1',candidate_input=row(CANDIDATE_INPUT),candidate_proof=row(CANDIDATE_PROOF),records=records,original_Model9=originals,protected_profiles=[row(p)for p in sorted((DATA/'profiles').glob('*.json'))],public_helper_before=[row(Path('C:/Develop/AI/Strata-extensions')/p)for p in ('control/deepseek_launch.py','control/providers/deepseek41.py','control/deepseek_bootstrap.py')],package_id=ID,bundle_id=BUNDLE,hook_sha256=HOOK,request=request(),mode_order=list(MODES),max_completed_requests=4,max_typed_controls=4,public_single_return_GEN=0,GPU_executed=False,large_RAM=0,requires_latest_independent_runner_observer_review=True,requires_actual_launch_binding_at_execution=True))
    return row(out/'seal.json')
