"""Metadata-only preparation for the existing tile_rows knob. No HIP import."""
import hashlib,json,math,unittest,importlib.util,subprocess,os,sys,shutil,copy,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BUILD=ROOT/'build-deepseek-t35/tile-geometry'
# The sealed controller is executed from its retained evidence directory.
if '--normal-execute'in sys.argv or '--normal-replay'in sys.argv:
 ROOT=next(p for p in Path(__file__).resolve().parents if p.name=='deepseek-v41'and(p/'Strata-extensions/tests/geometry').is_dir())
 BUILD=ROOT/'build-deepseek-t35/tile-geometry'
PARENT=ROOT/'build-deepseek-t35/provider-persistent-parent/source'
HEADER=ROOT/'Strata-extensions/tests/artifact/header-inventory.json'
INDEX=ROOT/'build-deepseek-t10/full-source-index.tsv'
FACTS=ROOT/'build-deepseek-t35/tile-geometry-facts-r1.json'
U64=(1<<64)-1
def row(p):
 p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf8')
def module(name,p):
 spec=importlib.util.spec_from_file_location(name,p);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def fresh(prefix):
 n=1
 while(BUILD/f'{prefix}-{n}').exists():n+=1
 p=BUILD/f'{prefix}-{n}';p.mkdir(parents=True);return p
def check(record):
 if row(record['path'])!=record:raise ValueError('changed dependency '+record['path'])
def build():
 out=fresh('build');parent=out/'parent';source=[]
 for p in sorted(PARENT.rglob('*')):
  if not p.is_file():continue
  dest=parent/p.relative_to(PARENT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);source.append(dict(original=row(p),snapshot=row(dest)))
 for name in ('tile_rows_fixture.hip','tile_rows_contract.json','tile_rows_verify.py'):
  p=HERE/name;dest=out/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);source.append(dict(original=row(p),snapshot=row(dest)))
 qpath=ROOT/'Strata-extensions/tests/quant/q_reference.py';prior=sys.modules.get('q_reference')
 try:
  sys.modules['q_reference']=module('geometry_Q_toolchain_import',qpath);tools_helper=module('geometry_toolchain',ROOT/'Strata-extensions/tests/quant/build_verify.py');tools_helper.BUILD=out;tools,env=tools_helper.environment()
 finally:
  if prior is None:sys.modules.pop('q_reference',None)
  else:sys.modules['q_reference']=prior
 cmake='''cmake_minimum_required(VERSION 3.24)
project(t35_geometry LANGUAGES CXX HIP)
find_package(hip CONFIG REQUIRED)
set(MODEL "${CMAKE_CURRENT_SOURCE_DIR}/parent/Strata-extensions/models/deepseek41")
add_subdirectory("${MODEL}" normal EXCLUDE_FROM_ALL)
get_target_property(SOURCES Strata-deepseek SOURCES)
get_target_property(INCLUDES Strata-deepseek INCLUDE_DIRECTORIES)
set(FIXTURE_SOURCES "")
foreach(INPUT ${SOURCES})
 get_filename_component(ABSOLUTE_INPUT "${INPUT}" ABSOLUTE BASE_DIR "${MODEL}")
 if(NOT ABSOLUTE_INPUT MATCHES "/producer.cpp$")
  list(APPEND FIXTURE_SOURCES "${ABSOLUTE_INPUT}")
 endif()
endforeach()
set_source_files_properties("${CMAKE_CURRENT_SOURCE_DIR}/parent/src/core/device.cu" PROPERTIES LANGUAGE HIP)
add_executable(t35-tile-rows source/tile_rows_fixture.hip ${FIXTURE_SOURCES})
target_include_directories(t35-tile-rows PRIVATE "${MODEL}" ${INCLUDES})
target_compile_features(t35-tile-rows PRIVATE cxx_std_17)
target_compile_options(t35-tile-rows PRIVATE -fno-fast-math -ffp-contract=off -fdenormal-fp-math=ieee)
target_compile_definitions(t35-tile-rows PRIVATE STRATA_USE_HIP STRATA_HIP_ARCHS="gfx1100,gfx1201" NOMINMAX WIN32_LEAN_AND_MEAN)
target_link_libraries(t35-tile-rows PRIVATE hip::host psapi bcrypt dxgi)
set_target_properties(t35-tile-rows PROPERTIES HIP_STANDARD 17 HIP_STANDARD_REQUIRED YES)
'''
 (out/'CMakeLists.txt').write_text(cmake,encoding='utf8');sdk=tools_helper.SDK
 commands=[[str(tools['cmake']),'-S',str(out),'-B',str(out/'native'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={sdk.as_posix()}',f'-DCMAKE_PREFIX_PATH={sdk.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={sdk.as_posix()} --rocm-device-lib-path={sdk.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}'],[str(tools['cmake']),'--build',str(out/'native'),'--target','t35-tile-rows','--verbose']]
 results=[]
 for i,command in enumerate(commands):
  run=subprocess.run(command,env=env,capture_output=True);(out/f'build-{i}.log').write_bytes(run.stdout+run.stderr);results.append(dict(command=command,exit=run.returncode,log=row(out/f'build-{i}.log')))
  if run.returncode:save(out/'failure.json',dict(commands=results,sources=source));raise ValueError('geometry compile failed; original retained')
 exe=out/'native/t35-tile-rows.exe';dlls=[]
 for name in ('amdhip64_7.dll','amd_comgr.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'):
  p=sdk/'bin'/name;q=exe.parent/name;shutil.copyfile(p,q);dlls.append(dict(original=row(p),copy=row(q)))
 run=subprocess.run([str(tools['ninja']),'-C',str(out/'native'),'-t','deps'],env=env,capture_output=True);(out/'deps.txt').write_bytes(run.stdout+run.stderr)
 if run.returncode:raise ValueError('Ninja dependencies failed')
 dependencies=sorted({Path(line.strip()).resolve()for line in run.stdout.decode('utf8').splitlines()if line.startswith('    ')and Path(line.strip()).is_file()})
 project_dependencies=[p for p in dependencies if 'Strata-extensions'in p.parts]
 if any(not p.is_relative_to(out.resolve())for p in project_dependencies):raise ValueError('mutable project source dependency')
 if not(parent/'Strata-extensions/native/quant/quant.hip').resolve()in dependencies:raise ValueError('missing old quant source')
 offload=subprocess.run([str(tools['objdump']),'--offloading',str(exe)],env=env,capture_output=True);(out/'offloading.txt').write_bytes(offload.stdout+offload.stderr)
 if offload.returncode or not all(a.encode()in offload.stdout for a in ('gfx1100','gfx1201')):raise ValueError('both architecture code objects')
 for r in source:check(r['original']);check(r['snapshot'])
 save(out/'build.json',dict(schema='T35-tile-rows-build/v1',sources=source,commands=results,exe=row(exe),dlls=dlls,recipe=row(out/'CMakeLists.txt'),tools=[row(p)for p in tools.values()],toolchain_helper=row(ROOT/'Strata-extensions/tests/quant/build_verify.py'),toolchain_Q_import=row(qpath),deps=row(out/'deps.txt'),dependencies=[row(p)for p in dependencies],offloading=row(out/'offloading.txt'),environment={k:env[k]for k in ('PATH','TMP','TEMP','HIP_PATH','ROCM_PATH','HIP_PLATFORM')},GPU_work_submitted=False,actual_projection=False))
 print(row(out/'build.json'))
def natural(value,positive=False):
 if type(value)is not int or not (0<value<=U64 if positive else 0<=value<=U64):raise ValueError('uint64 domain')
 return value
def multiply(a,b):
 natural(a);natural(b)
 if a and b>U64//a:raise ValueError('uint64 overflow')
 return a*b
def geometry(kind,k,rows,matrices,row_bytes,tensor_bytes,byte_cap,row_cap):
 for value in (k,rows,matrices,row_bytes,tensor_bytes,byte_cap,row_cap):natural(value,True)
 types=read(HERE/'tile_rows_contract.json')['types']
 if type(kind)is not int or str(kind)not in types:raise ValueError('qualified type')
 block,width=types[str(kind)]
 if k%block or multiply(k//block,width)!=row_bytes or multiply(multiply(row_bytes,rows),matrices)!=tensor_bytes:raise ValueError('full-K packed tensor geometry')
 count=min(byte_cap//row_bytes,row_cap)
 if count==0:raise ValueError('one full-K row does not fit')
 tiles=(rows-1)//count+1;last=rows-(tiles-1)*count
 # This is metadata arithmetic, not execution of Core's C++ implementation.
 if not 1<=last<=count or multiply(count,row_bytes)>byte_cap or multiply(tiles-1,count)+last!=rows:raise ValueError('row cover')
 return dict(rows_per_full_tile=count,tile_count=tiles,last_rows=last,last_first=(tiles-1)*count,full_tile_bytes=multiply(count,row_bytes),last_tile_bytes=multiply(last,row_bytes),matrix_rows=rows,packed_row_bytes=row_bytes,byte_cap=byte_cap)
def metadata():
 facts=read(FACTS);contract=read(HERE/'tile_rows_contract.json')
 if row(FACTS)['sha256']!='c6fdaaf9446b6bdf3932d612cf4e88c676f304e4a0036cf5d6160a29720b5038':raise ValueError('accepted facts version')
 if row(PARENT/'Strata-extensions/native/quant/quant.hip')['sha256']!='29d9bf0ad876688d2db80d6f5e9a5cdeecb927ebece5cd17b3b2e3d6ab3007da':raise ValueError('old quant parent')
 for r in facts['source_refs']:
  if row(r['path'])!=r:raise ValueError('accepted geometry fact dependency')
 inventory=read(HEADER);records=[];seen=set()
 for shard in inventory['shards']:
  for tensor in shard['tensors']:
   dims=tensor['dims_ggml']
   if len(dims)not in (2,3):continue
   key=(shard['index'],tensor['name'])
   if key in seen:raise ValueError('duplicate source tensor')
   seen.add(key);k,rows=dims[:2];matrices=dims[2]if len(dims)==3 else 1
   arms=[geometry(tensor['type_id'],k,rows,matrices,tensor['row_bytes'],tensor['bytes'],contract['byte_cap'],cap)for cap in contract['row_budgets']]
   records.append(dict(shard=shard['index'],tensor=tensor['name'],type=tensor['type_id'],k=k,rows=rows,matrices=matrices,arms=arms))
 if {r['type']for r in records}!={0,8,39,43}:raise ValueError('all current packed projection types')
 # Bind the source bodies; actual execution is a later native fixture result.
 core=PARENT/'Strata-extensions/models/deepseek41/core.hip';body=core.read_text(encoding='utf8');start=body.index('SourceTile source_tile(');end=body.index('std::vector<uint32_t> batch_waves(',start)
 return dict(schema='T35-tile-geometry-metadata/v1',refs=[row(p)for p in (HEADER,INDEX,FACTS,core,PARENT/'Strata-extensions/models/deepseek41/device_ops.hpp',PARENT/'Strata-extensions/models/deepseek41/artifact.hpp',PARENT/'Strata-extensions/native/quant/quant.hip',PARENT/'Strata-extensions/native/quant/quant.hpp',HERE/'tile_rows_contract.json',Path(__file__))],body_sha256=hashlib.sha256(body[start:end].encode()).hexdigest(),records=records,native_geometry_executed=False,GPU=0,original_model_payload_read_bytes=0,normal_profile_modified=False,model_speed_qualified=False)
def native_cpu(build_path):
 build_path=Path(build_path).resolve();compiled=read(build_path);out=fresh('native-CPU');bindings=[r['snapshot']for r in compiled['sources']]+[compiled['exe']]+[r['copy']for r in compiled['dlls']]+compiled['dependencies'];[check(r)for r in bindings]
 value=metadata();records=value['records'];contract=read(HERE/'tile_rows_contract.json');lines=[];expected=[]
 for record in records:
  for cap,arm in zip(contract['row_budgets'],record['arms']):
   rowbytes=arm['packed_row_bytes'];lines.append([record['type'],record['k'],record['rows'],record['matrices'],rowbytes,rowbytes*record['rows']*record['matrices'],contract['byte_cap'],cap]);expected.append(dict(tiles=arm['tile_count'],first_rows=min(arm['rows_per_full_tile'],record['rows']),last_rows=arm['last_rows'],last_first=arm['last_first'],matrix_bytes=rowbytes*record['rows']))
 tsv=out/'metadata.tsv';tsv.write_text(''.join('\t'.join(map(str,line))+'\n'for line in lines),encoding='utf8');env=dict(os.environ);env.update(compiled['environment']);command=[compiled['exe']['path'],'--cpu',str(tsv),str(out)];run=subprocess.run(command,env=env,capture_output=True);(out/'stdout.json').write_bytes(run.stdout);(out/'stderr.log').write_bytes(run.stderr)
 save(out/'execution.json',dict(command=command,exit=run.returncode))
 if run.returncode or run.stderr:raise ValueError('native metadata CPU failed; original retained')
 native=json.loads(run.stdout)
 if native.get('schema')!='T35-native-row-geometry/v1'or native.get('GPU_work_submitted')is not False or native.get('jobs')!=expected:raise ValueError('actual Core row geometry differs from independent metadata')
 # Loaded paths are observations. CPU registration need not load compiler DLLs.
 dlls={str(Path(r['copy']['path']).resolve()).lower():r['copy']for r in compiled['dlls']}
 for path in native['loaded_modules']:
  key=str(Path(path).resolve()).lower()
  if key not in dlls:raise ValueError('foreign CPU loaded module')
  check(dlls[key])
 negatives=[]
 for name,values in [('partial_K',[39,5119,3,1,2720,8160,2097152,256]),('wrong_row_bytes',[39,5120,3,1,2719,8157,2097152,256]),('empty_row',[39,5120,0,1,2720,0,2097152,256]),('too_small_byte_cap',[39,5120,3,1,2720,8160,2719,256]),('overflow_tensor',[0,1,U64,2,4,4,2097152,256])]:
  bad=out/(name+'.tsv');bad.write_text('\t'.join(map(str,values))+'\n',encoding='utf8');command=[compiled['exe']['path'],'--cpu',str(bad),str(out)];failed=subprocess.run(command,env=env,capture_output=True);(out/(name+'.stdout')).write_bytes(failed.stdout);(out/(name+'.stderr')).write_bytes(failed.stderr)
  if failed.returncode==0 or not failed.stderr:raise ValueError('native invalid geometry accepted')
  negatives.append(dict(name=name,input=row(bad),command=command,exit=failed.returncode,stdout=row(out/(name+'.stdout')),stderr=row(out/(name+'.stderr'))))
 [check(r)for r in bindings+value['refs']]
 save(out/'verification.json',dict(schema='T35-native-row-geometry-CPU/v1',build=row(build_path),metadata=value,actual=row(out/'stdout.json'),stderr=row(out/'stderr.log'),execution=row(out/'execution.json'),tsv=row(tsv),records=bindings,source=row(Path(__file__)),negative_cases=negatives,actual_Core_body_executed=True,jobs=len(expected),GPU_work_submitted=False,original_model_payload_read_bytes=0,actual_projection=False,model_speed_qualified=False));print(row(out/'verification.json'))
def accepted_quant_math():
 path=ROOT/'build-deepseek-t35/quant-block-scale/CPU-3/source/Strata-extensions/tests/quant/block_scale_verify.py';value=module('geometry_accepted_quant_math',path);value.ROOT=ROOT
 return value,[row(path),row(path.with_name('q_reference.py'))]
def synthetic39(rows,k):
 import numpy as np
 natural(rows,True);natural(k,True)
 if k%32:raise ValueError('full block K')
 blocks=multiply(rows,k)//32
 if blocks>5120*5120//32:raise ValueError('finite synthetic block count')
 ids=np.arange(blocks,dtype=np.uint64);data=np.empty((blocks,17),np.uint8)
 data[:,0]=(120+ids%12).astype(np.uint8)
 data[:,1:]=(np.arange(16,dtype=np.uint64)*11+ids[:,None]*3).astype(np.uint8)
 return data.tobytes()
def prepare():
 import numpy as np
 contract=read(HERE/'tile_rows_contract.json');quant,refs=accepted_quant_math();out=fresh('input');records=[];jobs=[]
 for name,(kind,rows,k,batch,stride)in zip(('gate_up','down'),contract['projection_shapes']):
  if kind!=39:raise ValueError('finite synthetic projection type')
  raw=synthetic39(rows,k);x=np.tile(np.array([1,-1,2.**-14,-2.**-14],dtype='<f4'),batch*k//4);decoded=quant.Q.decode(kind,raw).reshape(rows,k);expected=quant.Q.ordered(decoded,x.reshape(batch,k))
  rawpath=out/(name+'.raw');xpath=out/(name+'.x');qpath=out/(name+'.Q');rawpath.write_bytes(raw);xpath.write_bytes(x.tobytes());qpath.write_bytes(expected.astype('<f4').tobytes());records += [row(rawpath),row(xpath),row(qpath)]
  arms=[geometry(kind,k,rows,1,quant.Q.BLOCKS[kind][1]*k//32,len(raw),contract['byte_cap'],cap)for cap in contract['row_budgets']]
  jobs.append(dict(name=name,type=kind,rows=rows,k=k,batch=batch,stride=stride,raw=row(rawpath),input=row(xpath),Q=row(qpath),geometry=arms))
 tsv=out/'projection.tsv';tsv.write_text(''.join('\t'.join(map(str,[j['name'],j['type'],j['rows'],j['k'],j['batch'],j['stride'],j['raw']['path'],j['input']['path']]))+'\n'for j in jobs),encoding='utf8')
 value=dict(schema='T35-tile-rows-input/v1',contract=row(HERE/'tile_rows_contract.json'),sources=refs+[row(Path(__file__)),row(HERE/'tile_rows_fixture.hip')],files=records,tsv=row(tsv),jobs=jobs,generated_bytes=sum(r['bytes']for r in records),GPU=0,original_model_payload_read_bytes=0,normal_profile_modified=False,model_speed_qualified=False);save(out/'input.json',value);print(row(out/'input.json'))
def compiled_records(value):
 return [r['snapshot']for r in value['sources']]+[value[k]for k in ('exe','recipe','toolchain_helper','toolchain_Q_import','deps','offloading')]+value['dependencies']+value['tools']+[r[k]for r in value['dlls']for k in ('original','copy')]
def input_records(value):return value['files']+value['sources']+[value['tsv'],value['contract']]
def compare_projection(native,inputs,out):
 import numpy as np
 quant,_=accepted_quant_math()
 if native.get('schema')!='T35-tile-rows-G/v1'or native.get('model_generation')is not False or[j.get('name')for j in native.get('jobs',[])]!=[j['name']for j in inputs['jobs']]:raise ValueError('finite projection native schema/order')
 result=[]
 for actual,job in zip(native['jobs'],inputs['jobs']):
  a=out/(job['name']+'.256.bin');b=out/(job['name']+'.1713.bin');av=a.read_bytes();bv=b.read_bytes()
  if av!=bv or len(av)!=job['batch']*job['stride']*4 or actual.get('exact_bits')is not True:raise ValueError('tile geometry old/new exact bits')
  words=np.frombuffer(bv,dtype='<u4').reshape(job['batch'],job['stride'])
  if not np.all(words[:,job['rows']:]==0xa5a5a5a5):raise ValueError('tile geometry output guard')
  q=quant.compare_q(words[:,:job['rows']].copy().tobytes(),Path(job['Q']['path']).read_bytes())
  if any(type(actual.get(key))is not int or actual[key]!=expected for key,expected in [('calls256',job['geometry'][0]['tile_count']),('calls1713',job['geometry'][1]['tile_count']),('weight_H2D_bytes',job['raw']['bytes']),('requested_device_bytes',job['raw']['bytes']+job['input']['bytes']+8*job['batch']*job['stride'])]):raise ValueError('actual tile/copy/requested counters')
  arms=actual.get('event_envelopes')
  if not isinstance(arms,list)or[x.get('arm')for x in arms]!=list('ABBA'):raise ValueError('ABBA schedule')
  for arm in arms:
   if type(arm.get('projections'))is not int or arm['projections']!=3 or any(type(arm.get(k))not in(int,float)or not math.isfinite(arm[k])for k in ('raw_event_ms','host_seconds'))or arm['host_seconds']<0:raise ValueError('geometry clock observation')
  observed=[dict(arm,event_ms=arm['raw_event_ms']if arm['raw_event_ms']>=0 else None,event_status='nonnegative_observation'if arm['raw_event_ms']>=0 else 'negative_event_invalid')for arm in arms]
  result.append(dict(name=job['name'],output256=row(a),output1713=row(b),Q=q,calls256=actual['calls256'],calls1713=actual['calls1713'],requested_device_bytes=actual['requested_device_bytes'],weight_H2D_bytes=actual['weight_H2D_bytes'],event_envelopes=observed))
 return result
def seal_execution(build_path,input_path,destination,cpu_path):
 build_path=Path(build_path).resolve();input_path=Path(input_path).resolve();cpu_path=Path(cpu_path).resolve();destination=Path(destination).resolve();compiled=read(build_path);inputs=read(input_path);cpu=read(cpu_path)
 if cpu['build']!=row(build_path)or cpu['actual_Core_body_executed']is not True:raise ValueError('actual Core geometry CPU binding')
 records=compiled_records(compiled)+input_records(inputs)+[row(build_path),row(input_path),row(cpu_path),row(Path(__file__)),row(Path(sys.executable))]
 for r in records:check(r)
 # The old build driver is historical. Its C++/contract and all immutable parent
 # sources remain compiled exact; the new Python runtime controller is separate.
 for r in compiled['sources']:
  if Path(r['original']['path'])!=Path(__file__):check(r['original'])
 quant,refs=accepted_quant_math();old,owner,owner_refs=quant.owner_archive();old.runtime_snapshot(owner['input']);records+=refs+[row(r['path'])for r in owner_refs]
 destination.mkdir(parents=True,exist_ok=False);copies=[]
 for name in ('tile_rows_fixture.hip','tile_rows_contract.json','tile_rows_verify.py'):
  target=destination/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(HERE/name,target);copies.append(dict(original=row(HERE/name),snapshot=row(target)));records.append(row(target))
 # Retain the already qualified notices for the same SDK DLL bytes.
 notices=[];prior=read(ROOT/'build-deepseek-t35/quant-block-scale/build-4/build.json')
 for n in prior['notices']:
  check(n['copy']);target=destination/'licenses'/Path(n['copy']['path']).parent.name/Path(n['copy']['path']).name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(n['copy']['path'],target);notices.append(dict(source=n['copy'],copy=row(target)));records += [n['copy'],row(target)]
 save(destination/'seal.json',dict(schema='T35-tile-geometry-execution/v1',build=row(build_path),input=row(input_path),native_CPU=row(cpu_path),records=records,runtime_sources=copies,notices=notices,owner_seal=row(ROOT/'build-deepseek-t35/approx-8g-r1/measurement-seal.json'),devices=['0000:07:00.0','0000:03:00.0'],DRAM_report_only=True,model_GEN_count=0,normal_profile_modified=False,normal_AB_executed=False,model_speed_qualified=False));print(row(destination/'seal.json'))
def execute(destination):
 destination=Path(destination).resolve();sealed=read(destination/'seal.json');[check(r)for r in sealed['records']];compiled=read(sealed['build']['path']);inputs=read(sealed['input']['path'])
 if(destination/'execution.json').exists()or(destination/'owner-selection.json').exists():raise ValueError('preserve original geometry attempts')
 quant,_=accepted_quant_math();old,owner,_=quant.owner_archive();config=copy.deepcopy(owner['input']);tmp=destination/'tmp';tmp.mkdir();config['environment'].update(TMP=str(tmp),TEMP=str(tmp));env=dict(os.environ);env.update(config['environment']);session=None;failure=None;cleanup=None;memory=[];runs=[]
 try:
  session,selection,first=old.select_owner(config,env,destination);birth=first['birth'];memory.append(dict(point='constructed',sample=first));before=session.info();before_runtime=old.runtime_snapshot(config,before)
  if any(before[k]!=0 for k in ('core_position','primary_logical_read','primary_h2d')):raise ValueError('model owner has work before geometry')
  for pci in sealed['devices']:
   out=destination/('pci-'+pci.replace(':','-').replace('.','-'));out.mkdir();memory.append(dict(point=pci+'-before',sample=old.physical_memory(session.proc.pid,birth)));runenv=dict(os.environ);runenv.update(compiled['environment']);runenv.update(TMP=str(tmp),TEMP=str(tmp));command=[compiled['exe']['path'],pci,inputs['tsv']['path'],str(out)]
   started=time.perf_counter_ns();run=subprocess.run(command,env=runenv,capture_output=True);(out/'stdout.json').write_bytes(run.stdout);(out/'stderr.log').write_bytes(run.stderr);entry=dict(pci=pci,command=command,exit=run.returncode,controller_seconds=(time.perf_counter_ns()-started)/1e9,raw=row(out/'stdout.json'),stderr=row(out/'stderr.log'));runs.append(entry);save(destination/'execution.json',runs);memory.append(dict(point=pci+'-after',sample=old.physical_memory(session.proc.pid,birth)))
   if run.returncode or run.stderr:raise ValueError('geometry finite fixture failed; original retained')
   actual=read(out/'stdout.json');entry['loaded_modules']=quant.module_bindings(actual['loaded_modules'],compiled['dlls']);entry['analysis']=compare_projection(actual,inputs,out);save(destination/'execution.json',runs)
  after=session.info();after_runtime=old.runtime_snapshot(config,after)
  if any(after[k]!=0 for k in ('core_position','primary_logical_read','primary_h2d')):raise ValueError('model owner received geometry GEN')
  save(destination/'owner-info.json',dict(before=before,after=after,runtime_before=before_runtime,runtime_after=after_runtime,GEN_count=0,valid_model_payload_bytes=None));[check(r)for r in sealed['records']]
 except BaseException as error:failure=error;save(destination/'failure.json',dict(type=type(error).__name__,error=str(error)))
 finally:
  if session is not None:
   last=None;observation_error=None
   try:last=old.physical_memory(session.proc.pid,birth)
   except Exception as error:observation_error=str(error)
   try:session.close();cleanup=dict(pid=session.proc.pid,birth=birth,exit=session.proc.returncode,sample=last,observation_error=observation_error,original_process_handle_exit_observed=session.proc.returncode is not None)
   except BaseException as error:
    cleanup=dict(pid=session.proc.pid,birth=birth,exit=session.proc.poll(),error=str(error))
    if failure is None:failure=error
  save(destination/'memory.json',memory);save(destination/'cleanup.json',cleanup)
 if failure is not None:raise failure
 if cleanup is None or cleanup['exit']!=0 or cleanup['original_process_handle_exit_observed']is not True:raise ValueError('geometry owner close unconfirmed')
 [check(r)for r in sealed['records']]
 save(destination/'verification.json',dict(schema='T35-tile-rows-actual/v1',seal=row(destination/'seal.json'),execution=row(destination/'execution.json'),memory=row(destination/'memory.json'),cleanup=row(destination/'cleanup.json'),owner_info=row(destination/'owner-info.json'),old_quant_same_native=True,full_K_Q_bits_exact=True,normal_AB_executed=False,DRAM_report_only=True,model_GEN_count=0,original_model_weight_payload_read_bytes=0,owner_header_metadata_reads_separate=True,normal_profile_modified=False,model_speed_qualified=False));print(row(destination/'verification.json'))
class CPU(unittest.TestCase):
 def test_projection_validator_rejects_Q_counter_and_guard_changes(self):
  import tempfile,numpy as np
  with tempfile.TemporaryDirectory()as temp:
   out=Path(temp);q=out/'Q';q.write_bytes(np.array([1],dtype='<f4').tobytes());payload=np.array([0x3f800000]+[0xa5a5a5a5]*3,dtype='<u4').tobytes()
   for suffix in ('256','1713'):(out/('tiny.'+suffix+'.bin')).write_bytes(payload)
   job=dict(name='tiny',rows=1,batch=1,stride=4,Q=row(q),raw=dict(bytes=17),input=dict(bytes=128),geometry=[dict(tile_count=1)]*2)
   native=dict(schema='T35-tile-rows-G/v1',model_generation=False,jobs=[dict(name='tiny',exact_bits=True,calls256=1,calls1713=1,weight_H2D_bytes=17,requested_device_bytes=177,event_envelopes=[dict(arm=a,projections=3,raw_event_ms=.01,host_seconds=.01)for a in 'ABBA'])])
   self.assertEqual(compare_projection(native,dict(jobs=[job]),out)[0]['Q']['values'],1)
   bad=copy.deepcopy(native);bad['jobs'][0]['calls1713']=2
   with self.assertRaises(ValueError):compare_projection(bad,dict(jobs=[job]),out)
   bad=copy.deepcopy(native);bad['jobs'][0]['event_envelopes'][0]['raw_event_ms']=-.01
   self.assertIsNone(compare_projection(bad,dict(jobs=[job]),out)[0]['event_envelopes'][0]['event_ms'])
   q.write_bytes(np.array([2],dtype='<f4').tobytes())
   with self.assertRaises(ValueError):compare_projection(native,dict(jobs=[job]),out)
   q.write_bytes(np.array([1],dtype='<f4').tobytes());(out/'tiny.1713.bin').write_bytes(payload[:-4]+bytes(4))
   with self.assertRaises(ValueError):compare_projection(native,dict(jobs=[job]),out)
 def test_large_seed_preserves_small_pattern_without_numpy_uint16_overflow(self):
  quant,_=accepted_quant_math();self.assertEqual(synthetic39(17,64),quant.finite_raw(39,17,64))
  raw=synthetic39(2304,5120);self.assertEqual(len(raw),6266880)
  self.assertEqual(raw[21846*17+1],2);self.assertEqual(raw[21846*17+16],167)
  with self.assertRaises(ValueError):synthetic39(5121,5120)
 def test_static_representative_caps_and_terminal_rows(self):
  gate=geometry(39,5120,2304,384,2720,2406481920,2097152,1713);self.assertEqual((gate['rows_per_full_tile'],gate['tile_count'],gate['last_rows']),(771,3,762))
  down=geometry(39,2304,5120,384,1224,2406481920,2097152,1713);self.assertEqual((down['rows_per_full_tile'],down['tile_count'],down['last_rows']),(1713,3,1694))
 def test_all_current_source_geometry(self):
  value=metadata();self.assertGreater(len(value['records']),120)
 def test_invalid_and_overflow(self):
  base=[39,5120,2304,384,2720,2406481920,2097152,256]
  for index,bad in ((0,True),(0,9),(1,5119),(2,0),(3,0),(4,2719),(5,2406481921),(6,2719),(7,False),(7,1.0)):
   args=base[:];args[index]=bad
   with self.assertRaises(ValueError):geometry(*args)
  with self.assertRaises(ValueError):multiply(U64,2)
 def test_nonquantized_and_other_packed_row_limits(self):
  for kind,k,width in ((0,5120,20480),(8,5120,5440),(43,5120,5280)):
   x=geometry(kind,k,257,1,width,width*257,2097152,1713);self.assertEqual(x['rows_per_full_tile'],min(2097152//width,1713))
# Normal-model diagnostic is deliberately separate from the older max2/LPfalse
# performance contract. Importing this path needs neither numpy nor a GPU.
NORMAL_PARENT=ROOT/'build-deepseek-t35/approx-8g-r1/measurement-seal.json'
NORMAL_EXPECT=ROOT/'build-deepseek-t31/actual-sse-attempt-1/expectation.json'
NORMAL_CONFIG=NORMAL_EXPECT.with_name('config.json')
NORMAL_MANIFEST=NORMAL_EXPECT.with_name('manifest.json')
NORMAL_FRAMES=NORMAL_EXPECT.with_name('raw-frames.jsonl')
NORMAL_EXE='142c4dacbcec6c651579e97b793e9b10f2b0fb89fbb69d2e8cce89b938f4a32c'
NORMAL_BUNDLE='b3d7d28015b2b7b288a2fcf8919bebc2f36259f6d042bdeacd67ad49e4f822fa'
NORMAL_BUDGET_SOURCE=ROOT/'build-deepseek-t35/key-normal-native-1/source/Strata-extensions/models/deepseek41/producer.cpp'
def normal_require(ok,message):
 if not ok:raise ValueError(message)
def normal_check(record):
 actual=row(record['path'])
 normal_require(all(actual.get(k)==v for k,v in record.items()),'normal dependency changed: '+record['path'])
def normal_owner():
 normal_require(row(NORMAL_PARENT)['sha256']=='fc7dea4fc2442155cbb414c1d2599abeb329c9c81525e4d306f63e7fc07c7a54','immutable normal parent seal')
 seal=read(NORMAL_PARENT);refs=[row(NORMAL_PARENT)]+[r['snapshot']for r in seal['source_snapshots']]
 for r in refs:normal_check(r)
 backend=NORMAL_PARENT.parent/'measurement-source/Strata-extensions/tests/backend'
 prior=sys.modules.get('eager_bench')
 try:
  bench=module('geometry_normal_owner_math',backend/'eager_bench.py');sys.modules['eager_bench']=bench
  old=module('geometry_normal_owner_recipe',backend/'build_verify.py')
 finally:
  if prior is None:sys.modules.pop('eager_bench',None)
  else:sys.modules['eager_bench']=prior
 return old,seal,refs
def normal_request():
 normal_require(row(NORMAL_EXPECT)['sha256']=='3bcd4f87aac8e4a40e63693fa8c89bf106e4fcefc58daa07f84dcf6484735419','accepted normal expectation')
 request=copy.deepcopy(read(NORMAL_EXPECT)['request']);request['top_p']=1
 return request
def normal_hooks():
 normal_fixed()
 config=read(NORMAL_CONFIG);package=Path(config['exe']).parent.parent
 hooks=module('geometry_normal_installed_hooks',package/'Strata-extensions/models/deepseek41/server_hooks.py')
 tokenizer=hooks.recipe.Tokenizer.from_file(config['tokenizer'])
 prepared=hooks.codec.prepare_chat(normal_request(),tokenizer,4096)
 normal_require(list(prepared['input_ids'])==[0,128803,128804,128822]and prepared['max_tokens']==1,'official normal encoding/maximum')
 normal_require(prepared['inference_options'].logprobs,'official logprobs required')
 return hooks,tokenizer,prepared
def normal_fixed():
 for path,digest in ((NORMAL_CONFIG,'a9e6e2114e862f6d9da91c572c396c947bc9dafc49e443e82f4fd9993c3f22cd'),(NORMAL_MANIFEST,'3b4e342fa25bd924a9b308feecb433d77e6bf2155b1dfd7fc76e6dae20aa0ab8'),(NORMAL_FRAMES,'7c7b95265fbe9c505ac802f356fa8382f54510ba1191c1686fdb28aaf0764d16')):
  normal_require(row(path)['sha256']==digest,'immutable normal hook/expectation closure')
 for record in read(NORMAL_MANIFEST)['runtime_files']:normal_check(record)
def normal_context(request_id):
 begin=json.loads(NORMAL_FRAMES.read_text(encoding='utf8').splitlines()[0])['frame']
 return {k:(request_id if k=='request_id'else begin[k])for k in ('request_id','runtime_epoch','bundle_id','asset_revision','model_family','tokenizer_identity','tokenizer_model','tokenizer_pre','vocab_size')}
def normal_command(command,device,ram,cap):
 command=list(command)
 for key,value in (('--device-cache-payload-bytes',device),('--ram-cache-payload-bytes',ram),('--tile-rows',cap)):
  normal_require(type(value)is int and value>0,'positive explicit normal budget/geometry')
  normal_require(command.count(key)==1,'unique normal option '+key);command[command.index(key)+1]=str(value)
 return command
def normal_validate_commands(commands):
 normal_require(type(commands)is list and len(commands)==2,'one normal AB only')
 old=read(NORMAL_PARENT)['input']['command']
 device=ram=None
 for arm,cap in zip(commands,(256,1713)):
  normal_require(type(arm)is list and len(arm)==len(old)and all(type(x)is str for x in arm),'finite normal command')
  values={}
  for key in ('--device-cache-payload-bytes','--ram-cache-payload-bytes','--tile-rows'):
   normal_require(arm.count(key)==1,'unique normal budget/geometry option');v=arm[arm.index(key)+1]
   normal_require(v.isdecimal()and 0<int(v)<=U64,'normal resolved explicit payload');values[key]=int(v)
  normal_require(values['--tile-rows']==cap,'normal arm geometry')
  if device is None:device=values['--device-cache-payload-bytes'];ram=values['--ram-cache-payload-bytes']
  normal_require(arm==normal_command(old,device,ram,cap),'only geometry differs; same explicit budgets/native/flags')
 return dict(device=device,ram=ram)
def normal_budget_expectation(target,tile):
 # Pinned old producer.cpp counts(explicit_budget=true), not its auto layout.
 natural(target,True);natural(tile,True)
 normal_require(tile<=U64-264,'normal explicit unit overflow');unit=tile+264
 normal_require(target>=unit,'normal explicit working minimum')
 slots=target//unit;payload=multiply(slots,unit)
 return dict(target=target,unit=unit,slots=slots,payload=payload,unused=target-payload)
def normal_budget_source():
 reference=row(NORMAL_BUDGET_SOURCE)
 normal_require(reference['sha256']=='1bbb997a6f0429d10096f08f786a49a688dd4ee83ecb1532db7aba28b4f4578b','pinned normal explicit budget source')
 return reference
def normal_expected_info(command):
 def option(name):
  normal_require(command.count(name)==1,'unique normal INFO budget option');value=command[command.index(name)+1]
  normal_require(type(value)is str and value.isdecimal(),'normal explicit command integer');return natural(int(value),True)
 tile=option('--tile-bytes');expected=dict(weight_tile_bytes=tile)
 for role in ('device','ram'):
  budget=normal_budget_expectation(option('--'+role+'-cache-payload-bytes'),tile)
  expected.update({'declared_'+role+'_cache_payload_bytes':budget['target'],'resolved_'+role+'_cache_target_bytes':budget['target'],role+'_cache_payload_bytes':budget['payload'],'cache_unused_'+role+'_bytes':budget['unused'],role+'_slots':budget['slots'],'row_'+role+'_slots':budget['slots']})
  expected['working_minimum_payload_bytes']=budget['unit']
 return expected
def normal_validate_info(info,command):
 expected=normal_expected_info(command)
 for name,value in expected.items():
  normal_require(type(info.get(name))is int and 0<=info[name]<=U64 and info[name]==value,'normal explicit INFO '+name)
 return expected
def normal_gen(hooks,prepared,request_id):
 sampling={k:normal_request()[k]for k in ('temperature','top_p','top_k','seed','logprobs','top_logprobs')}
 return 'GEN 1'+hooks.sampling_keys(sampling)+' request_id='+request_id+' epoch=1 '+','.join(map(str,prepared['input_ids']))
def normal_lp(got,want):
 import struct
 normal_require(type(got)in(int,float)and math.isfinite(got),'finite normal LP')
 normal_require(got<=0,'log probability domain')
 bits=lambda x:struct.unpack('<I',struct.pack('<f',x))[0]
 normal_require(abs(bits(got)-bits(want))<=2,'normal selected/top3 F32 2ULP')
def normal_decode(frames,context,hooks,tokenizer,prepared):
 codec=hooks.codec.CodecSession(context,prepared,tokenizer);events=[]
 try:
  for frame in frames:events.extend(codec.feed(frame))
  result=codec.end_of_stream()
 finally:codec.close()
 raw=result['raw'];response=result['response'];q=read(NORMAL_EXPECT)
 normal_require(result['success']is True and list(raw['original_token_ids'])==[4482]and raw['generated_count']==1 and raw['finish']=='length','normal raw ID/count/finish')
 normal_require(list(result['recipe_input_ids'])==[4482]and result['normalized_finish']=='length','normal recipe ID/finish')
 normal_validate_response(response)
 batches=[hooks.codec._dto.parse_frame(f)for f in frames if hooks.codec._dto.parse_frame(f)['kind']=='token_batch']
 lp=[x for b in batches for x in b['logprobs']]
 normal_require(len(lp)==1 and set(lp[0])=={'logprob','top_logprobs'},'normal one selected LP')
 normal_lp(lp[0]['logprob'],q['selected_logprob_f32']);top=lp[0]['top_logprobs']
 normal_require(len(top)==3,'normal exact top3')
 for got,want in zip(top,q['top_logprobs']):
  normal_require(got['token_id']==want['token_id'],'normal ordered top3 IDs');normal_lp(got['logprob'],want['logprob'])
 return dict(raw=raw,response=response,events=events,LP_F32_max_ULP=2)
def normal_validate_response(response):
 normal_require(type(response)is dict and len(response.get('choices',[]))==1,'normal one official choice')
 choice=response['choices'][0];usage=response.get('usage',{})
 normal_require(choice.get('message',{}).get('content')=='\u60a8'and choice.get('finish_reason')=='length','normal official Unicode/finish')
 normal_require(type(usage.get('prompt_tokens'))is int and usage['prompt_tokens']==4 and type(usage.get('completion_tokens'))is int and usage['completion_tokens']==1,'normal official usage4+1')
def normal_validate_capture(capture,old,hooks,tokenizer,prepared,command):
 for info in (capture['info_before'],capture['info_after']):normal_validate_info(info,command)
 analysis=old.B.analyze_run(capture)
 normal_require(capture.get('request_index')==0,'fresh normal process one request')
 normal_require(capture['context']==normal_context(capture['context']['request_id']),'normal full request context')
 normal_require(analysis['original_ids']==[4482]and analysis['generated_count']==1 and analysis['finish']=='length','normal measured raw expectation')
 frames=[e['line']for e in capture['events']if e['line'].startswith('{')]
 decoded=normal_decode(frames,capture['context'],hooks,tokenizer,prepared)
 normal_require(any(e['line']=='PP 4 4'for e in capture['events']),'normal complete prompt progress')
 normal_require(capture['info_before']['primary_logical_read']==0 and capture['info_before']['row_logical_read']==0,'fresh normal application cache')
 return dict(analysis=analysis,decoded=decoded)
def normal_validate_closed(closed):
 normal_require(type(closed)is dict and closed.get('closed')is True and type(closed.get('exit'))is int and closed['exit']==0 and closed.get('original_process_handle_exit_observed')is True,'normal exact process close exit0')
 normal_require(type(closed.get('pid'))is int and type(closed.get('birth'))is int and closed['birth']>0,'normal exact owner/birth')
def normal_validate_pair(commands,captures,closed):
 normal_validate_commands(commands)
 normal_require(len(captures)==len(closed)==2,'normal exact one AB capture/close')
 for command,capture,cleanup in zip(commands,captures,closed):
  normal_validate_closed(cleanup);normal_require(capture['process_id']==cleanup['pid'],'normal capture exact process owner')
  for info in (capture['info_before'],capture['info_after']):
   normal_validate_info(info,command)
 normal_require((closed[0]['pid'],closed[0]['birth'])!=(closed[1]['pid'],closed[1]['birth']),'normal fresh A/B process identities')
def normal_seal(destination):
 destination=Path(destination).resolve();old,parent,owner_refs=normal_owner();config=copy.deepcopy(parent['input'])
 normal_require(config['executable']['sha256']==NORMAL_EXE and config['bundle_id']==NORMAL_BUNDLE,'old same normal executable/bundle')
 normal_require(config['normal_bundle_manifest']['sha256']=='3fd3600fb2198f19811b6429007c1af293f271cced99ca6b0c77e102954d8309','old native manifest')
 old.runtime_snapshot(config)
 small=BUILD/'fixed-r1/verification.json';pre=ROOT/'build-deepseek-t35/tile-geometry-pre-r1.md'
 normal_require(row(small)['sha256']=='64d68329ad4516cee7412b459e54d74ce8b3aca155f72951ae9d56fbc2678b0e'and row(pre)['sha256']=='34b3d0676042f89f8da829b862d0cb02acb0582fe394b42cdec17e1ac6c0d409','accepted old-source small projection and plan')
 installed=read(NORMAL_MANIFEST);refs=owner_refs+installed['runtime_files']+[normal_budget_source()]+[row(p)for p in (NORMAL_EXPECT,NORMAL_CONFIG,NORMAL_MANIFEST,NORMAL_FRAMES,Path(__file__),Path(sys.executable),pre,small)]
 for r in refs:normal_check(r)
 hooks,tokenizer,prepared=normal_hooks()
 normal_require(Path(sys.executable).resolve()==Path(read(NORMAL_CONFIG)['python']).resolve(),'run normal path in immutable installed interpreter')
 destination.mkdir(parents=True,exist_ok=False);snapshot=destination/'tile_rows_verify.py';shutil.copyfile(__file__,snapshot);refs.append(row(snapshot))
 value=dict(schema='T35-tile-normal-1AB-seal/v2',input=config,request=normal_request(),expected_context=normal_context('1-1'),GEN=normal_gen(hooks,prepared,'1-1'),records=refs,interpreter=row(Path(sys.executable)),controller=row(snapshot),selection='old immutable select_owner noGEN; selected payloads become explicit A/B targets; validate whole-slot allocation/remainder',row_budgets=[256,1713],actual_GPU_runs=0,normal_profile_modified=False,model_speed_qualified=False,DRAM_report_only=True)
 save(destination/'seal.json',value);print(row(destination/'seal.json'))
def normal_execute(seal_path):
 seal_path=Path(seal_path).resolve();sealed=read(seal_path)
 normal_require(sealed.get('schema')=='T35-tile-normal-1AB-seal/v2','dedicated normal r2 seal only')
 normal_require(sealed['request']==normal_request()and sealed['expected_context']==normal_context('1-1'),'normal finite sealed request/context')
 for r in sealed['records']:normal_check(r)
 normal_require(row(Path(__file__))==sealed['controller']and row(Path(sys.executable))==sealed['interpreter'],'exact sealed normal controller/interpreter')
 out=seal_path.parent/'actual';out.mkdir(exist_ok=False);config=sealed['input'];old,parent,_=normal_owner()
 normal_require(config==parent['input'],'normal immutable selection config')
 env=dict(os.environ);env.update(config['environment']);hooks,tokenizer,prepared=normal_hooks();results=[];selection_session=None
 normal_require(sealed['GEN']==normal_gen(hooks,prepared,'1-1'),'normal exact sealed GEN')
 try:
  selection_session,selection,sample=old.select_owner(config,env,out);info=selection_session.info();device=info['device_cache_payload_bytes'];ram=info['ram_cache_payload_bytes']
  save(out/'resolved-budget.json',dict(device=device,ram=ram,info=info,sample=sample,selection=selection))
 finally:
  if selection_session is not None:
   selection_session.close();save(out/'selection-close.json',dict(exit=selection_session.proc.returncode,pid=selection_session.proc.pid))
 commands=[normal_command(config['command'],device,ram,cap)for cap in (256,1713)];normal_validate_commands(commands);save(out/'commands.json',commands)
 for label,command in zip(('A','B'),commands):
  arm=out/label;arm.mkdir();session=None;memory=[];closed=None;failure=None
  try:
   before=old.runtime_snapshot(config);session=old.B.ProcessSession(command,config['cwd'],env);sample=old.sample_memory(session,'constructed');memory.append(sample)
   normal_require(sample['identity_verified']is True and type(sample['birth'])is int,'normal owner birth');birth=sample['birth'];info=session.info();during=old.runtime_snapshot(config,info)
   normal_validate_info(info,command)
   capture=old.measured_request(session,sealed['GEN'],sealed['expected_context'],'normal1AB-'+label,label,birth,memory,arm)
   save(arm/'capture.json',capture);checked=normal_validate_capture(capture,old,hooks,tokenizer,prepared,command);after=old.runtime_snapshot(config,capture['info_after']);save(arm/'checked.json',checked)
   results.append(dict(arm=label,capture=row(arm/'capture.json'),checked=row(arm/'checked.json'),runtime_before=before,runtime_during=during,runtime_after=after))
  except BaseException as error:
   failure=error
   if hasattr(error,'process_evidence'):save(arm/'constructor-failure.json',error.process_evidence)
  finally:
   if session is not None:
    try:
     sample=old.sample_memory(session,'before-close',sample['birth']);memory.append(sample);normal_require(sample['identity_verified']is True,'normal exact owner before close')
    except Exception as error:
     if failure is None:failure=error
    try:
     session.close();closed=dict(pid=session.proc.pid,birth=memory[0]['birth'],closed=session.closed,exit=session.proc.returncode,original_process_handle_exit_observed=session.proc.returncode is not None)
    except BaseException as error:
     closed=dict(pid=session.proc.pid,exit=session.proc.poll(),error=str(error))
     if failure is None:failure=error
    save(arm/'all-events.json',session.all_events);(arm/'stderr.log').write_text(''.join(session.stderr),encoding='utf8')
   save(arm/'memory.json',memory);save(arm/'closed.json',closed)
   if failure is not None:save(arm/'failure.json',dict(error=str(failure)))
  if failure is not None:raise failure
  normal_validate_closed(closed);results[-1].update(closed=row(arm/'closed.json'),memory=row(arm/'memory.json'),all_events=row(arm/'all-events.json'),stderr=row(arm/'stderr.log'))
 for r in sealed['records']:normal_check(r)
 normal_validate_pair(commands,[read(a['capture']['path'])for a in results],[read(a['closed']['path'])for a in results])
 save(out/'verification.json',dict(schema='T35-tile-normal-1AB-actual/v2',seal=row(seal_path),commands=row(out/'commands.json'),resolved_budget=row(out/'resolved-budget.json'),arms=results,actual_GEN_count=2,DRAM_report_only=True,physical_cold_qualified=False,CI=None,model_speed_qualified=False,normal_profile_modified=False))
 print(row(out/'verification.json'))
def normal_replay(proof_path):
 proof_path=Path(proof_path).resolve();proof=read(proof_path);normal_require(proof.get('schema')=='T35-tile-normal-1AB-actual/v2'and proof['actual_GEN_count']==2,'normal actual r2 proof schema/count')
 normal_check(proof['seal']);sealed=read(proof['seal']['path'])
 normal_require(sealed.get('schema')=='T35-tile-normal-1AB-seal/v2','normal replay r2 seal schema')
 for r in sealed['records']:normal_check(r)
 normal_check(proof['commands']);commands=read(proof['commands']['path']);normal_validate_commands(commands)
 old,_,_=normal_owner();hooks,tokenizer,prepared=normal_hooks();normal_require([a['arm']for a in proof['arms']]==['A','B'],'normal exact AB order')
 for command,arm in zip(commands,proof['arms']):
  for key in ('capture','checked','closed','memory','all_events','stderr'):normal_check(arm[key])
  checked=normal_validate_capture(read(arm['capture']['path']),old,hooks,tokenizer,prepared,command)
  # Saved JSON represents DTO tuples as arrays; compare the serialized shape.
  normal_require(json.loads(json.dumps(checked,allow_nan=False))==read(arm['checked']['path']),'normal saved analysis replay');normal_validate_closed(read(arm['closed']['path']))
 normal_validate_pair(read(proof['commands']['path']),[read(a['capture']['path'])for a in proof['arms']],[read(a['closed']['path'])for a in proof['arms']])
 print(dict(replay=True,proof=row(proof_path),new_GPU_runs=0))
def normal_cpu():
 old,parent,refs=normal_owner();hooks,tokenizer,prepared=normal_hooks();frames=[json.loads(x)['frame']for x in NORMAL_FRAMES.read_text(encoding='utf8').splitlines()];context=normal_context('1-1')
 serialize=lambda values:[json.dumps(f,allow_nan=True)for f in values]
 decoded=normal_decode(serialize(frames),context,hooks,tokenizer,prepared);negatives=[]
 def reject(name,call):
  try:call()
  except (ValueError,KeyError,TypeError,OverflowError):negatives.append(name);return
  raise ValueError('normal negative accepted: '+name)
 commands=[normal_command(parent['input']['command'],16500249592,53635121952,c)for c in (256,1713)];normal_validate_commands(commands)
 for key,value in (('--ram-cache-payload-bytes','20000001'),('--device-cache-payload-bytes','auto'),('--context','8192'),('--tile-rows','256'),('--active-batch','1')):
  bad=copy.deepcopy(commands);bad[1][bad[1].index(key)+1]=value;reject('command '+key,lambda:normal_validate_commands(bad))
 for name,edit in (('raw ID',lambda f:f[1]['ids'].__setitem__(0,531)),('missing LP',lambda f:f[1].pop('logprobs')),('NaN LP',lambda f:f[1]['logprobs'][0].__setitem__('logprob',float('nan'))),('LP mismatch',lambda f:f[1]['logprobs'][0].__setitem__('logprob',-2.)),('top3 short',lambda f:f[1]['logprobs'][0]['top_logprobs'].pop()),('count',lambda f:f[2].__setitem__('generated_count',2)),('finish',lambda f:f[2].__setitem__('finish','stop')),('context',lambda f:f[0].__setitem__('runtime_epoch',2))):
  bad=copy.deepcopy(frames);edit(bad);reject(name,lambda:normal_decode(serialize(bad),context,hooks,tokenizer,prepared))
 for name,edit in (('usage',lambda r:r['usage'].__setitem__('completion_tokens',2)),('Unicode',lambda r:r['choices'][0]['message'].__setitem__('content','wrong'))):
  bad=copy.deepcopy(decoded['response']);edit(bad);reject(name,lambda:normal_validate_response(bad))
 closed=dict(pid=123,birth=123,closed=True,exit=0,original_process_handle_exit_observed=True);normal_validate_closed(closed)
 for key,value in (('exit',1),('birth',None),('original_process_handle_exit_observed',False)):
  bad=dict(closed);bad[key]=value;reject('cleanup '+key,lambda:normal_validate_closed(bad))
 # Synthetic pipe timestamps exercise the same analyzer as actual capture.
 # They are never presented as observed native timing or model performance.
 info=read(NORMAL_EXPECT.with_name('startup-info.json'));info.update(normal_expected_info(commands[0]));before=copy.deepcopy(info)
 for name in old.B.OWNER_COUNTERS:before[name]=0
 capture=dict(context=context,workload_identity='CPU-synthetic',process_id=123,request_index=0,clock_domain='perf_counter_ns',clock_resolution_ns=100,request_start_ns=1000,events=[dict(line='PP 0 4',t_ns=1100),dict(line=json.dumps(frames[0]),t_ns=1200),dict(line='PP 4 4',t_ns=1300),dict(line=json.dumps(frames[1]),t_ns=1400),dict(line=json.dumps(frames[2]),t_ns=1500),dict(line='DONE 1',t_ns=1600)],info_before=before,info_after=info)
 normal_validate_capture(capture,old,hooks,tokenizer,prepared,commands[0])
 for name,edit in (('clock reversal',lambda c:c['events'][2].__setitem__('t_ns',1)),('missing DONE',lambda c:c['events'].pop()),('DONE count',lambda c:c['events'][-1].__setitem__('line','DONE 2')),('second request',lambda c:c.__setitem__('request_index',1)),('cache nonempty',lambda c:c['info_before'].__setitem__('primary_logical_read',1)),('budget changes during request',lambda c:c['info_after'].__setitem__('ram_slots',1))):
  bad=copy.deepcopy(capture);edit(bad);reject(name,lambda:normal_validate_capture(bad,old,hooks,tokenizer,prepared,commands[0]))
 captures=[copy.deepcopy(capture),copy.deepcopy(capture)];closures=[dict(closed),dict(closed,pid=124,birth=124)];captures[1]['process_id']=124
 normal_validate_pair(commands,captures,closures)
 bad=copy.deepcopy(captures);bad[1]['info_before']['device_cache_payload_bytes']=10000001;reject('AB actual budget mismatch',lambda:normal_validate_pair(commands,bad,closures))
 bad=copy.deepcopy(closures);bad[1]=dict(closed);reject('AB process reused',lambda:normal_validate_pair(commands,captures,bad))
 for value in (float('nan'),float('inf'),True,-1.9):reject('direct LP '+str(value),lambda:normal_lp(value,-1.8800559043884277))
 # Saved real native INFO regression from the failed r1 noGEN attempt.
 regression=BUILD/'normal-sealed-r1/actual/A/all-events.json';regression_commands=regression.parent.parent/'commands.json'
 normal_require(row(regression)['sha256']=='7fc2c7d1ef1342c4c956e374b5a50237e4066d249caa2d3e3ea54a6003f18f3f'and row(regression_commands)['sha256']=='4617bf6047470e1222c83265b1a63cbcb78e1822607dcf14922411066c574ad4','saved real r1 regression version')
 real_commands=read(regression_commands);normal_validate_commands(real_commands)
 real_infos=[json.loads(e['line'][5:])for e in read(regression)if e['line'].startswith('INFO ')]
 normal_require(len(real_infos)==2,'saved real initial/explicit INFO')
 for real_info in real_infos:normal_validate_info(real_info,real_commands[0])
 device=normal_budget_expectation(16500249592,2097152);ram=normal_budget_expectation(53635121952,2097152)
 normal_require(device==dict(target=16500249592,unit=2097416,slots=7866,payload=16498274256,unused=1975336)and ram==dict(target=53635121952,unit=2097416,slots=25572,payload=53635121952,unused=0),'exact saved floor regression')
 for arm in range(2):
  for stage in ('info_before','info_after'):
   for field in normal_expected_info(commands[arm]):
    bad=copy.deepcopy(captures);bad[arm][stage][field]+=1
    reject('INFO '+str(arm)+' '+stage+' '+field,lambda:normal_validate_pair(commands,bad,closures))
 for field in normal_expected_info(commands[0]):
  for value in (True,None,-1,1.5,U64+1):
   bad=dict(info);bad[field]=value;reject('INFO domain '+field+' '+str(value),lambda:normal_validate_info(bad,commands[0]))
 for target,tile in ((True,2097152),(0,2097152),(-1,2097152),(1.5,2097152),(U64+1,2097152),(2097415,2097152),(U64,U64),(2097416,0)):
  reject('budget domain '+str((target,tile)),lambda:normal_budget_expectation(target,tile))
 for field,value in (('device_slots',7745),('row_device_slots',976543),('declared_device_cache_payload_bytes',None)):
  bad=dict(info);bad[field]=value;reject('auto layout under explicit '+field,lambda:normal_validate_info(bad,commands[0]))
 changed_commands=copy.deepcopy(commands);changed_commands[1]=normal_command(parent['input']['command'],16500249593,53635121952,1713)
 changed_captures=copy.deepcopy(captures)
 for stage in ('info_before','info_after'):changed_captures[1][stage].update(normal_expected_info(changed_commands[1]))
 reject('internally consistent B target differs',lambda:normal_validate_pair(changed_commands,changed_captures,closures))
 # Exercise the actual replay entry point using explicitly synthetic artifacts.
 # Fake owner identities and clocks here are never actual-process evidence.
 import tempfile,contextlib,io
 with tempfile.TemporaryDirectory()as temporary:
  replay_dir=Path(temporary);save(replay_dir/'seal.json',dict(schema='T35-tile-normal-1AB-seal/v2',records=[],synthetic_CPU_only=True));save(replay_dir/'commands.json',commands);arms=[]
  for index,(capture_value,close_value)in enumerate(zip(captures,closures)):
   arm=dict(arm=('A','B')[index])
   values=dict(capture=capture_value,checked=normal_validate_capture(capture_value,old,hooks,tokenizer,prepared,commands[index]),closed=close_value,memory=[],all_events=capture_value['events'],stderr='')
   for key,value in values.items():
    path=replay_dir/(str(index)+'-'+key+'.json');save(path,value);arm[key]=row(path)
   arms.append(arm)
  proof=dict(schema='T35-tile-normal-1AB-actual/v2',actual_GEN_count=2,seal=row(replay_dir/'seal.json'),commands=row(replay_dir/'commands.json'),arms=arms,synthetic_CPU_only=True)
  # schema count2 describes fake replay data, not executed GEN; CPU proof below
  # records actual_GEN_count0 and this directory is discarded after validation.
  proof_path=replay_dir/'proof.json';save(proof_path,proof)
  with contextlib.redirect_stdout(io.StringIO()):normal_replay(proof_path)
  bad_capture=copy.deepcopy(captures[1]);bad_capture['info_after']['cache_unused_device_bytes']+=1;save(Path(arms[1]['capture']['path']),bad_capture);arms[1]['capture']=row(arms[1]['capture']['path']);save(proof_path,proof)
  reject('actual replay INFO changed after B',lambda:normal_replay(proof_path))
 out=fresh('normal-CPU-r2');save(out/'verification.json',dict(schema='T35-tile-normal-1AB-CPU/v2',source=row(Path(__file__)),records=refs+[row(NORMAL_FRAMES),row(NORMAL_EXPECT),normal_budget_source(),row(regression),row(regression_commands)],request=normal_request(),GEN=normal_gen(hooks,prepared,'1-1'),replayed=decoded,saved_real_native_INFO_regression=dict(original_attempt_GEN_count=0,INFO_snapshots=len(real_infos),device=device,ram=ram),synthetic_capture_checked=True,synthetic_pair_checked=True,synthetic_actual_replay_checked=True,negative_cases=negatives,actual_GPU_runs=0,actual_GEN_count=0,old_formal_contract_reused=False,model_speed_qualified=False,normal_profile_modified=False,remaining=['independent implementation review','sole resource window and fresh explicit A/B','actual process/counter/clock/cleanup replay']))
 print(row(out/'verification.json'))
if __name__=='__main__':
 import sys
 if sys.argv[1:]==['--normal-cpu']:normal_cpu()
 elif len(sys.argv)==3 and sys.argv[1]=='--normal-seal':normal_seal(sys.argv[2])
 elif len(sys.argv)==3 and sys.argv[1]=='--normal-execute':normal_execute(sys.argv[2])
 elif len(sys.argv)==3 and sys.argv[1]=='--normal-replay':normal_replay(sys.argv[2])
 elif sys.argv[1:]==['--build']:build()
 elif sys.argv[1:]==['--prepare']:prepare()
 elif len(sys.argv)==3 and sys.argv[1]=='--native-cpu':native_cpu(sys.argv[2])
 elif len(sys.argv)==6 and sys.argv[1]=='--seal':seal_execution(*sys.argv[2:])
 elif len(sys.argv)==3 and sys.argv[1]=='--execute':execute(sys.argv[2])
 elif sys.argv[1:]==['--metadata']:
  path=BUILD/'metadata-CPU-1.json'
  if path.exists():raise ValueError('preserve previous metadata proof')
  save(path,metadata());print(row(path))
 else:unittest.main(verbosity=2)
