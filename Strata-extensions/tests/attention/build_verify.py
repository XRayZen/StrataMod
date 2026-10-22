"""Explicit T15 fixture qualification; never an ordinary runtime gate."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import subprocess
import shutil

ROOT=Path(__file__).resolve().parents[3]
EXT=ROOT/'Strata-extensions'
HERE=Path(__file__).resolve().parent
BUILD=ROOT/'build-deepseek-t15'

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def record(path):
 path=Path(path)
 with path.open('rb')as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 return dict(path=str(path),bytes=path.stat().st_size,sha256=digest)

def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

def prepare():
 q=load('t15_independent_q',HERE/'reference.py');a=load('t15_local_origin',HERE/'acquire_fixtures.py')
 receipt=json.loads((HERE/'fixture-receipts.json').read_text(encoding='utf-8'));a.verify_receipt(receipt)
 contract=json.loads((HERE/'contract.json').read_text(encoding='utf-8'))
 if contract['N']!=q.decimal_literals():raise ValueError('independent N literal changed')
 folder=BUILD/'q';folder.mkdir(parents=True,exist_ok=True)
 if(folder/'manifest.json').exists():raise ValueError('preserve frozen Q manifest')
 def write(target,name,array):
  value=np.asarray(array)
  if value.ndim==1:value=value.reshape(-1,1)
  elif value.ndim>2:value=value.reshape(value.shape[0],-1)
  if value.ndim!=2 or value.dtype.kind not in 'fiu':raise ValueError('declared stage geometry/dtype')
  value=value.astype(value.dtype.newbyteorder('<'));path=target/(name+'.bin');value.tofile(path)
  policy='ulp2'if name.endswith(('_inv','_alpha','_prob','_max'))else'bits'
  special={}
  if value.dtype.kind=='f':
   if np.isnan(value).any():raise ValueError('Q NaN '+name)
   for label,mask in [('positive_inf',np.isposinf(value)),('negative_inf',np.isneginf(value))]:
    if mask.any():special[label]=np.flatnonzero(mask).tolist()
  return dict(name=name,**record(path),dtype=value.dtype.str,shape=list(value.shape),allow_empty=value.size==0,compare=policy,nonfinite=special)
 def job(name,kind,inputs,outputs,**params):
  target=folder/name;target.mkdir(exist_ok=False)
  row=dict(name=name,kind=kind,inputs=[write(target,'input__'+k,v)for k,v in sorted(inputs.items())],outputs=[write(target,k,v)for k,v in sorted(outputs.items())],**params)
  print(json.dumps(dict(prepared=name,outputs=len(row['outputs']),bytes=sum(v['bytes']for v in row['outputs']))),flush=True)
  return row
 weights=q.learned_weights(receipt);prepared=q.prepared_projection(weights)
 t14_receipt=json.loads((EXT/'tests/kv/fixture-receipts.json').read_text(encoding='utf-8'))
 projected=q._kv.learned_projection(t14_receipt);jobs=[]
 for batch in(1,2,4,8):
  for phase in(0,4):
   ids=(np.arange(batch)+phase)%8;stages={}
   for layer,rows in prepared.items():
    stages.update({f'layer{layer}__'+k:v[ids]for k,v in rows.items()})
   jobs.append(job(f'projection-B{batch}-phase{phase}','projection',dict(input=q._kv.fixed_inputs()[ids]),stages,batch=batch,phase=phase))
 for length in(1,2,3,8):
  for phase in(0,4):
   jobs.append(job(f'short-L{length}-phase{phase}','short',dict(input=q._kv.fixed_inputs()),q.short_context(weights,prepared,projected,length,phase),batch=1,length=length,phase=phase))
 for batch in(2,4,8):
  for phase in(0,4):
   stages={}
   for context in range(batch):stages.update({'c'+str(context)+'__'+k:v for k,v in q.short_context(weights,prepared,projected,3,(phase+context)%8).items()})
   jobs.append(job(f'short-B{batch}-L3-phase{phase}','short_batch',dict(input=q._kv.fixed_inputs()),stages,batch=batch,length=3,phase=phase))
 for name,parts in q.controls().items():
  jobs.append(job('controlled-'+name,parts['kind'],parts['inputs'],parts['outputs'],batch=1,**{k:v for k,v in parts.items()if k not in('kind','inputs','outputs')}))
 for width in(16383,16384,16385):
  for variant in(0,1):
   parts=q.long_control(width,variant);jobs.append(job(f'long-N{width}-variant{variant}','long',parts['inputs'],parts['outputs'],batch=3,width=width,variant=variant))
 refs=[HERE/n for n in('reference.py','contract.json','acquire_fixtures.py','fixture-receipts.json')]+[EXT/'tests/kv'/n for n in('reference.py','fixture-receipts.json')]+[EXT/'tests/quant/q_reference.py',EXT/'models/deepseek41/reference-config.json']
 manifest=dict(schema='strata-t15-fixed-q/v1',G_executed=False,full_source_qualified=False,N=contract['N'],references=[record(p)for p in refs],jobs=jobs,scope=contract['scope'],allocation_expectations_pending=True)
 # Numerical expectations are generated before the native implementation. The
 # complete G binding additionally requires the allocation/lifetime expectations.
 save(folder/'manifest.json',manifest)
 print(json.dumps(dict(numerical_Q=record(folder/'manifest.json'),jobs=len(jobs),stages=sum(len(j['outputs'])for j in jobs),G_ready=False)),flush=True)


Q_SHA='a4087bd5cd683a5d6f552bd84220bb3ef8489382363e1602abdaa085f3b86cfe'

def q_binding():
 path=BUILD/'q/manifest.json'
 if record(path)['sha256']!=Q_SHA:raise ValueError('G-before numerical Q changed')
 m=json.loads(path.read_text(encoding='utf-8'))
 if m['G_executed']is not False or m['full_source_qualified']is not False or len(m['jobs'])!=55 or len({j['name']for j in m['jobs']})!=55:raise ValueError('Q declared coverage')
 for row in m['references']:
  if record(row['path'])!=row:raise ValueError('Q reference changed')
 for job in m['jobs']:
  names=set()
  for row in job['inputs']+job['outputs']:
   shape=row['shape'];dtype=row['dtype']
   if not isinstance(shape,list)or len(shape)!=2 or any(type(v)is not int or v<0 for v in shape)or dtype not in('<f4','|u1','<i4','<i8'):raise ValueError('Q strict shape/type')
   if type(row['allow_empty'])is not bool or row['allow_empty']!=(shape[0]*shape[1]==0)or row['bytes']!=shape[0]*shape[1]*np.dtype(dtype).itemsize or record(row['path'])!={k:row[k]for k in('path','bytes','sha256')}:raise ValueError('Q byte binding')
   if row['name']in names:raise ValueError('duplicate stage')
   names.add(row['name'])
 return m


BOUNDARY_SHA='1fa760ffb9c3f157491987a013af11403d010ed31f67afa92e5bde53b05cc7f9'

def boundary_expectation(length):
 if type(length)is not int or length not in(127,128,129):raise ValueError('declared SWA boundary')
 q=load('t15_fixed_boundary_q',HERE/'reference.py');positions=np.arange(length,dtype=np.float32);keys=q.bf16(np.repeat(((positions+1)/256)[:,None],512,axis=1));keys[:,0]=q.bf16((positions+1)/64);keys[0]=np.float32(.125)
 if length==129:keys[128]=np.float32(1.5)
 query=np.zeros((64,512),np.float32);query[:,0]=q.bf16((np.arange(64,dtype=np.float32)+1)/64);sinks=np.arange(64,dtype=np.float32)/64
 indices=q._kv.window_indices(length,0);mask=np.zeros((length,length),np.uint8)
 for r,row in enumerate(indices):mask[r,row[row>=0]]=1
 output,trace=q.online_attention(query,keys,indices[-1],sinks)
 if length==129:
  wrong,_=q.online_attention(query,keys,np.arange(128,dtype=np.int32),sinks)
  if np.array_equal(output.view(np.uint32),wrong.view(np.uint32)):raise ValueError('wrong window must expose numerical fault')
 return dict(inputs=dict(query=query,keys=keys,sinks=sinks),outputs=dict(output=output,window_indices=indices,causal_mask=mask,**trace))

def prepare_boundary():
 q_binding();root=BUILD/'q-boundary';root.mkdir(exist_ok=True)
 if(root/'manifest.json').exists():raise ValueError('preserve G-before boundary expectations')
 jobs=[]
 for length in(127,128,129):
  name=f'controlled-prefill-L{length}';folder=root/name;folder.mkdir();parts=boundary_expectation(length)
  def write(name,value):
   value=np.asarray(value)
   if value.ndim==1:value=value.reshape(-1,1)
   path=folder/(name+'.bin');value.astype(value.dtype.newbyteorder('<')).tofile(path);nonfinite={}
   if value.dtype.kind=='f':
    if np.isnan(value).any():raise ValueError('boundary NaN')
    for label,mask in(('positive_inf',np.isposinf(value)),('negative_inf',np.isneginf(value))):
     if mask.any():nonfinite[label]=np.flatnonzero(mask).tolist()
   return dict(name=name,**record(path),dtype=value.dtype.str,shape=list(value.shape),allow_empty=False,compare='ulp2'if name.endswith(('_alpha','_prob','_max'))else'bits',nonfinite=nonfinite)
  jobs.append(dict(name=name,kind='prefill',length=length,batch=1,inputs=[write('input__'+k,v)for k,v in sorted(parts['inputs'].items())],outputs=[write(k,v)for k,v in sorted(parts['outputs'].items())]))
 manifest=dict(schema='strata-t15-prefill-boundary-q/v1',G_executed=False,original_Q=record(BUILD/'q/manifest.json'),references=records([HERE/'reference.py',EXT/'tests/kv/reference.py']),jobs=jobs,scope='all prefill query indices/mask and final actual online for nonperiodic controlled K/V; not 129 learned projections or fullmodel')
 save(root/'manifest.json',manifest);print(json.dumps(record(root/'manifest.json')),flush=True)

def all_jobs():
 m=q_binding();path=BUILD/'q-boundary/manifest.json'
 if record(path)['sha256']!=BOUNDARY_SHA:raise ValueError('G-before SWA boundary Q changed')
 boundary=json.loads(path.read_text(encoding='utf-8'))
 if boundary['G_executed']is not False or boundary['original_Q']!=record(BUILD/'q/manifest.json')or [j['length']for j in boundary['jobs']]!=[127,128,129]:raise ValueError('boundary Q coverage/origin')
 for row in boundary['references']:
  if record(row['path'])!=row:raise ValueError('boundary reference changed')
 for job in boundary['jobs']:
  for row in job['inputs']+job['outputs']:
   if record(row['path'])!={k:row[k]for k in('path','bytes','sha256')}:raise ValueError('boundary bytes changed')
 return {**m,'jobs':m['jobs']+boundary['jobs']}

def online_peak(heads,payload_rows,indices):
 blocks=(indices+63)//64
 return 4096*heads+max(4,2048*payload_rows)+max(8,8*indices)+8*heads+2828*blocks*heads

def index_peak(rows,positions):return 16384*rows+512*positions+128*rows+520*rows*positions

def select_peak(rows,positions):return 9*rows*positions+8*rows+8*rows*min(512,positions)+4*rows*((positions+7)//8)

def expected_peaks(job):
 # Each operation drains and its RAII buffers leave scope before the next.
 # These are live explicit allocations, excluding driver/context/host unknowns.
 kind=job['kind'];b=job.get('batch',1)
 if kind=='projection':return dict(primitive_peak=44564480+b*(1280+32768)*4,scratch_peak=b*32768*8)
 if kind in('short','short_batch'):
  length=job['length'];return dict(primitive_peak=45654016,scratch_peak=max(8*32768*8,length*64*4104+128))
 inputs={r['name'].removeprefix('input__'):r for r in job['inputs']}
 if kind=='fp4':n=np.prod(inputs['input']['shape']).item();scratch=n*9+n//32
 elif kind=='fp8':scratch=4625
 elif kind=='norm':r,w=inputs['input']['shape'];scratch=r*w*8+w*4+r*4
 elif kind=='rope':scratch=inputs['input']['shape'][0]*4104+128
 elif kind=='index':scratch=index_peak(inputs['query']['shape'][0],inputs['keys']['shape'][0])
 elif kind=='online':scratch=online_peak(inputs['query']['shape'][0],inputs['keys']['shape'][0],np.prod(inputs['indices']['shape']).item())
 elif kind=='select':scratch=select_peak(*inputs['score']['shape'])
 elif kind=='prefill':scratch=online_peak(64,job['length'],min(job['length'],128))
 elif kind=='long':
  n=job['width'];scratch=max(index_peak(3,n),select_peak(3,n),online_peak(64,n+128,640),n*128*9+n*4)
 else:raise ValueError('undeclared allocation job')
 return dict(primitive_peak=0,scratch_peak=int(scratch))

def validate_job(observed,job):
 if not isinstance(observed,dict)or set(observed)!=set(('name','stages','primitive_peak','scratch_peak','cleanup_unknown'))or observed['name']!=job['name']:raise ValueError('native job schema')
 for field in('stages','primitive_peak','scratch_peak'):
  if type(observed[field])is not int or observed[field]<0:raise ValueError('strict native accounting')
 if observed['stages']!=len(job['outputs'])or observed['cleanup_unknown']is not False:raise ValueError('coverage/cleanup')
 for field,value in expected_peaks(job).items():
  if observed[field]!=value:raise ValueError('allocation/lifetime mismatch '+field)

def compare(path,row):
 raw=Path(path).read_bytes();expected=Path(row['path']).read_bytes()
 if len(raw)!=row['bytes']or len(expected)!=row['bytes']:raise ValueError('exact stage bytes')
 if not raw:
  if row['allow_empty']is not True:raise ValueError('unapproved empty output')
  return 0
 actual=np.frombuffer(raw,row['dtype']);want=np.frombuffer(expected,row['dtype'])
 if row['dtype']=='<f4':
  if np.isnan(actual).any()or np.isnan(want).any():raise ValueError('NaN stage')
  if not np.array_equal(np.isposinf(actual),np.isposinf(want))or not np.array_equal(np.isneginf(actual),np.isneginf(want)):raise ValueError('expected signed nonfinite class')
  for label,mask in(('positive_inf',np.isposinf(want)),('negative_inf',np.isneginf(want))):
   if np.flatnonzero(mask).tolist()!=row['nonfinite'].get(label,[]):raise ValueError('fixed nonfinite class positions')
 if row['compare']=='bits':
  if raw!=expected:raise ValueError('exact stage mismatch '+row['name'])
 elif row['compare']=='ulp2'and row['dtype']=='<f4':
  finite=np.isfinite(want);ab=actual[finite].view(np.uint32);eb=want[finite].view(np.uint32)
  if np.any((want[finite]==0)&(ab!=eb)):raise ValueError('signed zero mismatch')
  ai=np.where(ab&0x80000000,~ab,ab|0x80000000).astype(np.int64);ei=np.where(eb&0x80000000,~eb,eb|0x80000000).astype(np.int64)
  if np.any(np.abs(ai-ei)>2):raise ValueError('fixed2ULP '+row['name'])
 else:raise ValueError('comparison policy')
 return len(actual)

def cpu_checks():
 qm=all_jobs();rejects=0
 for kind in('projection','short','fp4','norm','index','online','select','long','prefill'):
  job=next(j for j in qm['jobs']if j['kind']==kind);valid=dict(name=job['name'],stages=len(job['outputs']),cleanup_unknown=False,**expected_peaks(job));validate_job(valid,job)
  for field in('primitive_peak','scratch_peak'):
   for value in(0,-1,True,valid[field]+1,max(0,valid[field]-1)):
    if type(value)is int and value==valid[field]:continue
    changed={**valid,field:value}
    try:validate_job(changed,job)
    except ValueError:rejects+=1
    else:raise ValueError('accounting false pass')
 folder=BUILD/'cpu-negative';folder.mkdir(exist_ok=True);output_rejects=0
 rows=[r for j in qm['jobs']for r in j['outputs']]
 cases=[next(r for r in rows if r['nonfinite'].get('positive_inf')),next(r for r in rows if r['nonfinite'].get('negative_inf')),next(r for r in rows if r['dtype']=='|u1'and r['bytes']>0),next(r for r in rows if r['dtype']=='<f4'and r['bytes']>4 and not r['nonfinite'])]
 for index,row in enumerate(cases):
  original=Path(row['path']).read_bytes();compare(row['path'],row);changed=bytearray(original)
  if row['nonfinite']:
   values=np.frombuffer(original,'<f4').copy();values[~np.isfinite(values)]=1;changed=values.tobytes()
  else:changed[0]^=1
  for label,raw in(('changed',changed),('short',original[:-1]),('extra',original+b'\0')):
   path=folder/(str(index)+'-'+label+'.bin');path.write_bytes(raw)
   try:compare(path,row)
   except ValueError:output_rejects+=1
   else:raise ValueError('output false pass '+label)
 save(folder/'result.json',dict(allocation_rejections=rejects,output_rejections=output_rejects,G_executed=False))
 print(json.dumps(dict(CPU_Q_binding=True,allocation_rejections=rejects,output_rejections=output_rejects,G_executed=False)),flush=True)


BUNDLE=BUILD/'bundle-r4'
EXE=BUNDLE/'t15-attention.exe'
COMPILED=[EXT/'models/deepseek41'/n for n in('attention.hpp','attention.hip')]+[HERE/'attention_fixture.cpp']
RECIPES=[HERE/n for n in('CMakeLists.txt','reference.py','contract.json','acquire_fixtures.py','fixture-receipts.json','build_verify.py')]
DEPS=[EXT/'models/deepseek41'/n for n in('kv.hpp','kv.hip','artifact.hpp','artifact.cpp','reference-config.json')]+[EXT/'native/quant'/n for n in('quant.hpp','quant.hip')]+[EXT/'native/artifact'/n for n in('native_reader.hpp','native_reader.cpp','acquire.py','gguf.py','full_acquire.py')]+[EXT/'native/stats'/n for n in('measurement.hpp','measurement.cpp')]+[ROOT/'include/strata/artifact'/n for n in('dequant.hpp','gguf_reader.hpp','gguf_split.hpp','model_family.hpp')]+[ROOT/'include/strata/core/geometry.hpp',EXT/'tests/kv/reference.py',EXT/'tests/kv/build_verify.py',EXT/'tests/kv/fixture-receipts.json',EXT/'tests/quant/q_reference.py',EXT/'tests/numerics/reference.py']

def aggregate(rows):return hashlib.sha256(''.join(r['path']+'|'+r['sha256']+'\n'for r in rows).encode()).hexdigest()
def records(paths):return [record(p)for p in paths]

def write_tables(qm):
 inputs=[];jobs=[]
 for job in qm['jobs']:
  input_table=BUILD/(job['name']+'-inputs.tsv');rows=[]
  for item in job['inputs']:rows.append('\t'.join(map(str,[item['name'].removeprefix('input__'),item['dtype'],*item['shape'],item['path']])))
  input_table.write_text('\n'.join(rows)+'\n',encoding='utf-8');inputs.append(input_table)
  kind=job['kind'];shape=next((r['shape']for r in job['inputs']if r['name']=='input__input'),None)
  if shape is None:shape=next((r['shape']for r in job['inputs']if r['name']in('input__query','input__score')), [job.get('batch',1),1])
  jobs.append('\t'.join(map(str,[job['name'],kind,job.get('batch',1),job.get('phase',0),job.get('length',0),shape[0],shape[1],input_table])))
 (BUILD/'jobs.tsv').write_text('\n'.join(jobs)+'\n',encoding='utf-8');inputs.append(BUILD/'jobs.tsv')
 for target,source in(('weights.tsv',HERE/'fixture-receipts.json'),('compression.tsv',EXT/'tests/kv/fixture-receipts.json')):
  receipt=json.loads(source.read_text(encoding='utf-8'));rows=['\t'.join(map(str,[r['tensor'],r['absolute_offset'],r['bytes'],r['fixture_path']]))for r in receipt['fixtures']];path=BUILD/target;path.write_text('\n'.join(rows)+'\n',encoding='utf-8');inputs.append(path)
 for name in('sources.tsv','prefixes.tsv'):
  path=BUILD/name;shutil.copy2(ROOT/'build-deepseek-t14'/name,path);inputs.append(path)
 path=BUILD/'input8.bin';load('t15_runtime_input_origin',HERE/'reference.py')._kv.fixed_inputs().astype('<f4').tofile(path);inputs.append(path)
 return inputs

def runtime_env():
 import os
 env=os.environ.copy();env['TMP']=env['TEMP']=str(BUILD/'tmp');env['PATH']=str(BUNDLE)+os.pathsep+os.environ.get('SystemRoot','C:/Windows')+'/System32';env.pop('HIP_PATH',None);env.pop('ROCM_PATH',None);env['HIP_PLATFORM']='amd';return env

def invoke(args,timeout=900):return subprocess.run(list(map(str,args)),cwd=ROOT,env=runtime_env(),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)

def freeze_bundle():
 qm=all_jobs();cpu_checks()
 if(BUNDLE/'manifest.json').exists():raise ValueError('preserve fixed native bundle')
 build_dev();BUNDLE.mkdir(exist_ok=True)
 for p in(BUILD/'bundle-dev').iterdir():
  if p.is_file():shutil.copy2(p,BUNDLE/p.name)
 inputs=write_tables(qm)
 allocation=BUILD/'allocation-expectations.json';save(allocation,dict(schema='strata-t15-fixed-allocation/v1',numerical_Q_sha256=Q_SHA,G_executed=False,jobs={j['name']:expected_peaks(j)for j in qm['jobs']},definition='explicit live device allocations; synchronous operation scope max, primitive and scratch nonoverlap; driver/context/fullhost unknown'))
 inputs.append(allocation);inputs.append(BUILD/'q/manifest.json');inputs.append(BUILD/'q-boundary/manifest.json')
 inputs.extend(Path(row['path'])for j in qm['jobs']for row in j['inputs']+j['outputs'])
 for path in(HERE/'fixture-receipts.json',EXT/'tests/kv/fixture-receipts.json'):
  inputs.extend(Path(row['fixture_path'])for row in json.loads(path.read_text(encoding='utf-8'))['fixtures'])
 for row in (BUILD/'prefixes.tsv').read_text(encoding='utf-8').splitlines():inputs.append(Path(row.split('\t')[1]))
 shutil.copytree(ROOT/'build-deepseek-t14/bundle-r7/licenses',BUNDLE/'licenses')
 source_rows=records(COMPILED);deps=records(DEPS);recipes=records(RECIPES);identity_paths=[EXT/'models/deepseek41'/n for n in('attention.hpp','attention.hip','kv.hpp','kv.hip')]+[HERE/'attention_fixture.cpp',EXT/'native/quant/quant.hpp',EXT/'native/quant/quant.hip']
 source_id=aggregate(records(identity_paths));result=invoke([EXE,'--identity'])
 if result.returncode or json.loads(result.stdout)!=dict(source_id=source_id):raise ValueError('compiled source identity')
 state=invoke([EXE,'--state'])
 if state.returncode or json.loads(state.stdout)['state_assertions']!=14:raise ValueError('host view contract')
 helper=load('t15_fixed_toolchain',EXT/'tests/kv/build_verify.py');helper.BUILD=BUILD;sdk,tools,env=helper.environment()
 manifest=dict(schema='strata-t15-native-bundle/v1',full_source_qualified=False,compiled=source_rows,dependencies=deps,recipes=recipes,identity_inputs=records(identity_paths),compiled_id=source_id,inputs=records(sorted(set(inputs))),tools=records(tools.values()),artifact=record(EXE),bundle=records(sorted(p for p in BUNDLE.rglob('*')if p.is_file())),dll_sources=records(sdk/'bin'/n for n in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')),flags=['-fno-fast-math','-ffp-contract=off','-fdenormal-fp-math=ieee'],host_assertions=14,allocation=record(allocation),numerical_Q_sha256=Q_SHA)
 save(BUNDLE/'manifest.json',manifest);print(json.dumps(dict(fixed_bundle=record(BUNDLE/'manifest.json'),artifact=record(EXE),G_executed=False)),flush=True)

def bundle_binding():
 path=BUNDLE/'manifest.json';fixed=record(path)['sha256'];m=json.loads(path.read_text(encoding='utf-8'));snapshot=BUILD/'capture-runner-r4.py';recipes=records(RECIPES)
 for index,row in enumerate(m['recipes']):
  if Path(row['path'])==HERE/'build_verify.py'and recipes[index]!=row:
   saved=record(snapshot)
   if saved['sha256']!=row['sha256']or saved['bytes']!=row['bytes']:raise ValueError('original capture recipe missing')
   recipes[index]=row
 if m['compiled']!=records(COMPILED)or m['dependencies']!=records(DEPS)or m['recipes']!=recipes:raise ValueError('bundle source binding')
 for group in('compiled','dependencies','recipes','identity_inputs','inputs','tools','bundle','dll_sources'):
  for row in m[group]:
   if group=='recipes'and Path(row['path'])==HERE/'build_verify.py'and record(row['path'])!=row:
    saved=record(snapshot)
    if saved['sha256']!=row['sha256']or saved['bytes']!=row['bytes']:raise ValueError('capture recipe changed')
    continue
   if record(row['path'])!=row:raise ValueError('bound file changed '+row['path'])
 if aggregate(m['identity_inputs'])!=m['compiled_id']or record(EXE)!=m['artifact']:raise ValueError('compiled identity binding')
 q_binding();allocation=json.loads((BUILD/'allocation-expectations.json').read_text(encoding='utf-8'));original=load('t15_original_capture_policy',snapshot)
 if allocation['jobs']!={j['name']:original.expected_peaks(j)for j in all_jobs()['jobs']}:raise ValueError('historical G-before allocation policy changed')
 if record(path)['sha256']!=fixed:raise ValueError('manifest changed during binding')
 return m,fixed

def verify_outputs(observed,output,qm):
 if observed.get('source_qualified')is not False or type(observed.get('state_assertions'))is not int or observed['state_assertions']!=14 or type(observed.get('ordinal'))is not int:raise ValueError('native top-level observed schema')
 if observed.get('before_status')!=0 or type(observed['before_status'])is not int or any(type(observed.get(k))is not int or observed[k]<0 for k in('before_free','before_total')):raise ValueError('native memory observation')
 if len(observed['jobs'])!=len(qm['jobs'])or len({r['name']for r in observed['jobs']})!=len(qm['jobs']):raise ValueError('native job coverage')
 values=0
 for native,job in zip(observed['jobs'],qm['jobs']):
  validate_job(native,job);folder=Path(output)/job['name'];rows={}
  for line in(folder/'stages.tsv').read_text(encoding='utf-8').splitlines():
   n,d,r,c,b=line.split('\t')
   if n in rows:raise ValueError('duplicate output stage')
   rows[n]=(d,int(r),int(c),int(b))
  if set(rows)!={r['name']for r in job['outputs']}:raise ValueError('exact stage coverage')
  if set(p.name for p in folder.iterdir())!={'stages.tsv'}|{r['name']+'.bin'for r in job['outputs']}:raise ValueError('unexpected output files')
  for row in job['outputs']:
   if rows[row['name']]!=(row['dtype'],*row['shape'],row['bytes']):raise ValueError('native output shape/type/bytes')
   values+=compare(folder/(row['name']+'.bin'),row)
 return dict(jobs=len(qm['jobs']),stage_values=values)

def run_gpu():
 import os
 m,fixed=bundle_binding();qm=all_jobs();output=BUILD/'primary-output-r4';status=invoke([EXE,'--run','0000:07:00.0',BUILD/'weights.tsv',BUILD/'compression.tsv',BUILD/'sources.tsv',BUILD/'prefixes.tsv',BUILD/'jobs.tsv',BUILD/'input8.bin',output],1800)
 (BUILD/'primary-stdout-r4.json').write_text(status.stdout,encoding='utf-8');(BUILD/'primary-stderr-r4.log').write_text(status.stderr,encoding='utf-8')
 env=runtime_env();save(BUILD/'primary-runtime-environment-r4.json',{k:env.get(k)for k in('TMP','TEMP','PATH','HIP_PLATFORM','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES')})
 if status.returncode or status.stderr:raise ValueError('native G failure '+str(status.returncode)+' '+status.stderr)
 observed=json.loads(status.stdout)
 if observed.get('source_id')!=m['compiled_id']or observed.get('pci')!='0000:07:00.0'or not observed.get('arch','').startswith('gfx1201'):raise ValueError('native actual device/identity')
 loaded={Path(p).name.lower():p for p in observed['loaded_modules']};dlls=[]
 for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'):
  if name not in loaded or Path(loaded[name]).resolve()!=(BUNDLE/name).resolve():raise ValueError('actual owned DLL path')
  dlls.append(record(loaded[name]))
 result=verify_outputs(observed,output,qm)
 _,after=bundle_binding()
 if after!=fixed:raise ValueError('before/after manifest mismatch')
 proof=dict(schema='strata-t15-primary-proof/v1',manifest_sha256=fixed,compiled_id=m['compiled_id'],artifact=m['artifact'],numerical_Q_sha256=Q_SHA,result=result,observed=observed,output=str(output),loaded_dlls=dlls,outputs=records(sorted(p for p in output.rglob('*')if p.is_file())),driver_context_peak=None,full_host_peak=None,full_source_qualified=False)
 save(BUILD/'primary-verification-r4.json',proof);print(json.dumps(dict(proof=record(BUILD/'primary-verification-r4.json'),result=result)),flush=True)

def revalidate_saved():
 m,fixed=bundle_binding();qm=all_jobs();stdout=BUILD/'primary-stdout-r4.json';stderr=BUILD/'primary-stderr-r4.log';output=BUILD/'primary-output-r4'
 if stderr.read_text(encoding='utf-8'):raise ValueError('saved native stderr')
 observed=json.loads(stdout.read_text(encoding='utf-8'))
 if observed.get('source_id')!=m['compiled_id']or observed.get('pci')!='0000:07:00.0'or not observed.get('arch','').startswith('gfx1201'):raise ValueError('saved actual device/identity')
 allocation=BUILD/'allocation-expectations-cpu-r5.json';save(allocation,dict(schema='strata-t15-cpu-allocation/v1',native_manifest_sha256=fixed,numerical_Q_sha256=Q_SHA,boundary_Q_sha256=BOUNDARY_SHA,jobs={j['name']:expected_peaks(j)for j in qm['jobs']},correction='prefill indices count is min(length,128), 127 uses 127 int64 entries, not128; native allocations unchanged'))
 result=verify_outputs(observed,output,qm);loaded={Path(p).name.lower():p for p in observed['loaded_modules']};dlls=[]
 for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'):
  if name not in loaded or Path(loaded[name]).resolve()!=(BUNDLE/name).resolve():raise ValueError('saved actual owned DLL')
  dlls.append(record(loaded[name]))
 cpu_checks();_,after=bundle_binding()
 if after!=fixed:raise ValueError('manifest changed during CPU revalidation')
 proof=dict(schema='strata-t15-cpu-revalidation/v1',manifest_sha256=fixed,compiled_id=m['compiled_id'],artifact=m['artifact'],capture_runner=record(BUILD/'capture-runner-r4.py'),validator=record(HERE/'build_verify.py'),allocation=record(allocation),native_stdout=record(stdout),native_stderr=record(stderr),numerical_Q_sha256=Q_SHA,boundary_Q_sha256=BOUNDARY_SHA,result=result,observed=observed,output=str(output),loaded_dlls=dlls,outputs=records(sorted(p for p in output.rglob('*')if p.is_file())),driver_context_peak=None,full_host_peak=None,full_source_qualified=False,G_reexecuted=False)
 path=BUILD/'primary-cpu-validation-r5.json'
 if path.exists():raise ValueError('preserve fixed CPU revalidation')
 save(path,proof);print(json.dumps(dict(CPU_revalidation=result,proof=record(path),G_reexecuted=False)),flush=True)

def verify_only():
 m,fixed=bundle_binding();path=BUILD/'primary-cpu-validation-r5.json';proof=json.loads(path.read_text(encoding='utf-8'))
 if proof['manifest_sha256']!=fixed or proof['artifact']!=m['artifact']or proof['compiled_id']!=m['compiled_id']or proof['numerical_Q_sha256']!=Q_SHA or proof['boundary_Q_sha256']!=BOUNDARY_SHA:raise ValueError('proof exact native binding')
 if proof['validator']!=record(HERE/'build_verify.py'):raise ValueError('CPU validator changed')
 for row in proof['outputs']+proof['loaded_dlls']+[proof[k]for k in('allocation','capture_runner','native_stdout','native_stderr')]:
  if record(row['path'])!=row:raise ValueError('saved capture changed')
 if proof['observed']!=json.loads(Path(proof['native_stdout']['path']).read_text(encoding='utf-8'))or Path(proof['native_stderr']['path']).read_text(encoding='utf-8'):raise ValueError('captured observed binding')
 allocation=json.loads(Path(proof['allocation']['path']).read_text(encoding='utf-8'))
 if allocation['jobs']!={j['name']:expected_peaks(j)for j in all_jobs()['jobs']}:raise ValueError('current allocation derivation changed')
 result=verify_outputs(proof['observed'],proof['output'],all_jobs())
 if result!=proof['result']:raise ValueError('proof result mismatch')
 cpu_checks();_,after=bundle_binding()
 if after!=fixed:raise ValueError('manifest changed during replay')
 print(json.dumps(dict(independent_replay=result,manifest_sha256=fixed,G_reexecuted=False,proof=record(path))),flush=True)

def build_dev():
 k=load('t15_fixed_build_environment',EXT/'tests/kv/build_verify.py');k.BUILD=BUILD;sdk,tools,env=k.environment();native=BUILD/'cmake-native';bundle=BUILD/'bundle-dev';bundle.mkdir(exist_ok=True)
 paths=[EXT/'models/deepseek41'/n for n in('attention.hpp','attention.hip','kv.hpp','kv.hip')]+[HERE/'attention_fixture.cpp',EXT/'native/quant/quant.hpp',EXT/'native/quant/quant.hip']
 identity=hashlib.sha256(''.join(str(p)+'|'+record(p)['sha256']+'\n'for p in paths).encode()).hexdigest()
 commands=[[tools['cmake'],'--fresh','-S',HERE,'-B',native,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}',f'-DT15_SOURCE_ID={identity}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,command in enumerate(commands):
  result=subprocess.run(list(map(str,command)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=900)
  with(BUILD/f'development-build-{i}.log').open('a',encoding='utf-8')as f:f.write(result.stdout+result.stderr+'\n')
  if result.returncode:raise RuntimeError(result.stdout+result.stderr)
 shutil.copy2(native/'bundle/t15-attention.exe',bundle/'t15-attention.exe')
 for name in('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):shutil.copy2(sdk/'bin'/name,bundle/name)
 print(json.dumps(dict(development_build=True,source_id=identity,artifact=record(bundle/'t15-attention.exe'),G_executed=False)),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--build-dev',action='store_true');parser.add_argument('--cpu-checks',action='store_true');parser.add_argument('--freeze-bundle',action='store_true');parser.add_argument('--gpu',action='store_true');parser.add_argument('--verify-only',action='store_true');parser.add_argument('--prepare-boundary',action='store_true');parser.add_argument('--revalidate-saved',action='store_true');args=parser.parse_args()
 if args.prepare_boundary:prepare_boundary()
 elif args.prepare:prepare()
 elif args.build_dev:build_dev()
 elif args.cpu_checks:cpu_checks()
 elif args.freeze_bundle:freeze_bundle()
 elif args.gpu:run_gpu()
 elif args.verify_only:verify_only()
 elif args.revalidate_saved:revalidate_saved()
 else:parser.error('explicit --prepare required; native qualification not implemented yet')
