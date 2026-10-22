"""Fixed T29 isolated CPU package, not an installer or runtime launcher."""
import argparse,hashlib,importlib.util,json,os,pathlib,re,shutil,subprocess,sys,time,urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[3]
EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t29';DATA=ROOT.parents[1]
BASE_PYTHON=pathlib.Path('C:/Users/yaruo/AppData/Local/Programs/Python/Python312/python.exe')

def digest(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def record(p):
 p=pathlib.Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=digest(p))
def check_record(row):
 p=pathlib.Path(row['path'])
 if not p.is_file()or type(row['bytes'])is not int or p.stat().st_size!=row['bytes']or digest(p)!=row['sha256']:raise ValueError('exact file binding mismatch: '+str(p))
 return p
def load(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def write(p,value):pathlib.Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def destination(root,relative):
 q=pathlib.PurePosixPath(relative)
 if q.is_absolute()or ':'in relative or '..'in q.parts or '\\'in relative:raise ValueError('unsafe package relative path')
 return pathlib.Path(root).joinpath(*q.parts)
def wheel_name(value):
 if pathlib.PurePath(value).name!=value or '/'in value or '\\'in value or not value.endswith('.whl'):raise ValueError('wheel filename')
 return value
def check_wheel(path,size,sha):return check_record(dict(path=str(path),bytes=size,sha256=sha))
def lock_line(row):
 check_record(row);return pathlib.Path(row['path']).resolve().as_uri()+' --hash=sha256:'+row['sha256']
def protected(root):return {str(p.resolve()):digest(p)for p in sorted(pathlib.Path(root).glob('*.json'))}
def copy_checked(row,target):
 source=check_record(row);target=pathlib.Path(target);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);check_record(row)
 if digest(target)!=row['sha256']:raise ValueError('copy differs')
 return dict(source=row,copy=record(target))
def atomic_new(path,raw):
 """Publish new owned bytes; never overwrite an unrelated existing file."""
 path=pathlib.Path(path)
 if path.exists():
  if not path.is_file()or path.read_bytes()!=raw:raise ValueError('existing destination differs: '+str(path))
  return
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.t29-new')
 with temp.open('xb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
 try:os.link(temp,path) # Atomic create-only: a racing foreign file is never replaced.
 finally:temp.unlink()
def package_paths(installed,id):
 if type(id)is not str or re.fullmatch('[0-9a-f]{64}',id)is None:raise ValueError('package identity')
 root=pathlib.Path(installed)/'runtime/deepseek41'/id
 return dict(root=root,native=root/'native/Strata-deepseek.exe',python=root/'venv/Scripts/python.exe',entry=root/'Strata-extensions/control/deepseek_serve.py',base=root/'base',tokenizer=root/'resources/tokenizer.json',manifest=root/'evidence/package-manifest.json')
def normal_options(paths,native_id,context,data):
 return dict(primary_pci='0000:07:00.0',secondary=None,placement=dict(mode='single',primary='0000:07:00.0',secondary=None),cache_budget=dict(device_cache_payload_bytes='auto',ram_cache_payload_bytes='auto'),auto_cache_fraction=.5,auto_row_fraction=1/64,tile_bytes=2097152,tile_rows=256,active_batch=8,python=str(paths['python']),server_entry=str(paths['entry']),upstream_root=str(paths['base']),runtime_package=dict(id=paths['root'].name,manifest=str(paths['manifest'])),bundle_id=native_id,arch='deepseek41',backend='hip',args=[],cwd=str(paths['native'].parent),lib_dirs=[str(paths['native'].parent)],aliases=['deepseek-v4.1-flash-1017'],host='127.0.0.1',port=18080,log=str(pathlib.Path(data)/'logs'/f'deepseek-v4.1-flash-1017-ud-q4_k_xl-{context}-engine.log'),env={})

def mode_options(paths,native_id,context,data):
 """Opt-in declarations for the future T46 package; old builders stay unchanged."""
 value=normal_options(paths,native_id,context,data)
 helper=module('t46_declared_defaults',EXT/'control/deepseek_launch.py')
 value['execution_defaults']=helper.execution_defaults(dict(devices=['0000:07:00.0','0000:03:00.0'],assignment=list(range(1,384,2)),cut=24))
 return value
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def catalog_module():
 previous=list(sys.path)
 try:
  sys.path.insert(0,str(DATA));return module('t29_published_catalog',DATA/'model_catalog.py')
 finally:sys.path[:]=previous
def scope_sources():
 return [EXT/'control/providers/__init__.py',EXT/'control/providers/deepseek41.py',DATA/'model_catalog.py',*(EXT/'tests/providers'/x for x in ('contract.json','test_provider.py','build_verify.py','runtime_stage.py','test_runtime_stage.py'))]
def selected_inputs(path):
 data=load(path);id=data['candidate_package_id'];copy=dict(data);copy.pop('candidate_package_id')
 if hashlib.sha256(json.dumps(copy,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=id:raise ValueError('deployment input identity')
 seen=set()
 for row in data['selected_files']:
  dest=row['relative_destination'];destination(BUILD,dest)
  if dest in seen:raise ValueError('duplicate package destination')
  seen.add(dest);check_record(dict(path=row['source'],bytes=row['bytes'],sha256=row['sha256']))
 if data.get('schema')=='strata-t46-execution-package-input/v1':
  validate_execution_extension(data,seen)
 elif data.get('schema')=='strata-t33-identity-package-input/v1':
  validate_identity_extension(data,seen)
 elif data.get('schema')=='strata-t31-client-package-input/v1':
  validate_client_extension(data,seen)
 elif data.get('schema')!='strata-t29-deployment-input-plan/v1'or len(seen)!=55:raise ValueError('fixed file scope')
 if sum(x['bytes']for x in data['selected_files'])!=data['copy_payload_bytes']:raise ValueError('fixed copy payload')
 if not {'resources/tokenizer-README.md','resources/tokenizer-LICENSE'}<=seen:raise ValueError('tokenizer notice coverage')
 manifest=data['native_manifest'];check_record(dict(path=manifest['source'],bytes=manifest['bytes'],sha256=manifest['sha256']))
 return data

def validate_client_extension(data,seen):
 """Finite reviewed client extension; old T29 inputs keep their 55-file contract."""
 check_record(data['parent_inputs']);check_record(data['parent_package'])
 if load(data['parent_inputs']['path']).get('schema')!='strata-t29-deployment-input-plan/v1':raise ValueError('client extension direct parent')
 parent=selected_inputs(data['parent_inputs']['path']);package=load(data['parent_package']['path'])
 if parent.get('schema')!='strata-t29-deployment-input-plan/v1':raise ValueError('client extension parent schema')
 if parent['candidate_package_id']!=package['id']or package['id']!=data['parent_id']:raise ValueError('client extension parent identity')
 original={r['relative_destination']:r for r in parent['selected_files']}
 actual={r['relative_destination']:r for r in data['selected_files']}
 extra={'clients/chat.py'}|{'Strata-extensions/clients/'+n for n in ('chat_adapter.py','stream_contract.py','web_stream.js','package_clients.py')}
 if seen!=set(original)|extra or len(seen)!=60 or data['expected_copy_count']!=60:raise ValueError('client extension finite paths')
 if data['public_write_executed']is not False or data['venv_not_copied']is not True:raise ValueError('client input scope')
 parent_root=pathlib.Path(data['parent_package']['path']).parent.parent
 if parent_root.name!=data['parent_id']:raise ValueError('client parent root')
 for relative,old in original.items():
  if digest(destination(parent_root,relative))!=old['sha256']:raise ValueError('parent installed copy changed')
  if relative not in ('native/Strata-deepseek.exe','base/serve/web/app.js'):
   if any(actual[relative][k]!=old[k]for k in ('bytes','sha256')):raise ValueError('unexpected parent payload change')
 native=data['native_manifest'];check_record(dict(path=native['source'],bytes=native['bytes'],sha256=native['sha256']))
 value=load(native['source'])
 if value['schema']!='strata-t35-key-hoist-normal/v1'or value['parent']['sha256']!=parent['native_manifest']['sha256']:raise ValueError('new native parent')
 exes=[r['target']for r in value['copies']if pathlib.Path(r['target']['path']).name=='Strata-deepseek.exe']
 if len(exes)!=1 or exes[0]['sha256']!=actual['native/Strata-deepseek.exe']['sha256']or record(exes[0]['path'])['bytes']!=actual['native/Strata-deepseek.exe']['bytes']:raise ValueError('new native executable selection')


def validate_identity_extension(data,seen):
 """Finite T33 metadata/client extension; native and old input schemas are retained."""
 check_record(data['parent_package']);check_record(data['parent_inputs'])
 parent=load(data['parent_package']['path']);old=load(data['parent_inputs']['path']);root=pathlib.Path(data['parent_package']['path']).parent.parent
 if parent.get('schema')!='strata-t29-runtime-package/v1'or parent.get('id')!=root.name or parent['id']!=data['parent_id']or type(parent.get('client_extension'))is not dict or'identity_extension'in parent:raise ValueError('identity parent package')
 if old.get('schema')!='strata-t31-client-package-input/v1'or old.get('candidate_package_id')!=parent['id']or parent['client_extension'].get('input')!=data['parent_inputs']:raise ValueError('identity parent input')
 original={r['relative_destination']:r for r in old['selected_files']};actual={r['relative_destination']:r for r in data['selected_files']}
 extra={'Strata-extensions/clients/'+n for n in ('runtime_identity.py','runtime_identity.js')}
 changed={'base/serve/web/app.js','clients/chat.py','Strata-extensions/control/deepseek_serve.py'}|{'Strata-extensions/clients/'+n for n in ('chat_adapter.py','stream_contract.py','web_stream.js','package_clients.py')}
 if len(original)!=60 or len(seen)!=62 or seen!=set(original)|extra or data.get('expected_copy_count')!=62:raise ValueError('identity finite file scope')
 if data.get('public_write_executed')is not False or data.get('venv_not_copied')is not True or data.get('runtime_python_created_at_final_location')is not True:raise ValueError('identity assembly scope')
 for r in parent['files']:check_record(r)
 for relative,oldrow in original.items():
  path=destination(root,relative);current=record(path)
  if any(current[k]!=oldrow[k]for k in ('bytes','sha256')):raise ValueError('identity accepted parent changed')
  if relative not in changed and any(actual[relative][k]!=oldrow[k]for k in ('bytes','sha256')):raise ValueError('identity protected native/base copy')
 n=data['native_manifest'];check_record(dict(path=n['source'],bytes=n['bytes'],sha256=n['sha256']))
 if n['sha256']!=parent['native_manifest_sha256']or n['relative_destination']!='evidence/native-manifest.json'or digest(root/'evidence/native-manifest.json')!=n['sha256']:raise ValueError('identity native version')
 generators=module('t33_identity_generator',actual['Strata-extensions/clients/package_clients.py']['source'])
 entry=root/'Strata-extensions/control/deepseek_serve.py';expected=generators.derive_identity_entry(entry.read_bytes(),digest(entry))
 if pathlib.Path(actual['Strata-extensions/control/deepseek_serve.py']['source']).read_bytes()!=expected:raise ValueError('identity entry derived delta')
 if len(data.get('upstream',[]))!=2:raise ValueError('identity upstream bindings')
 for r in data['upstream']:check_record(r)

def validate_execution_extension(data,seen):
 """Finite child of the accepted T33 package; never rewrites the old schemas."""
 check_record(data['parent_package']);check_record(data['parent_inputs']);check_record(data['plan'])
 parent=load(data['parent_package']['path']);old=load(data['parent_inputs']['path']);root=pathlib.Path(data['parent_package']['path']).parent.parent
 if parent.get('schema')!='strata-t29-runtime-package/v1'or parent.get('id')!=root.name or parent['id']!=data['parent_id']or type(parent.get('identity_extension'))is not dict or'execution_extension'in parent:raise ValueError('execution parent package')
 if old.get('schema')!='strata-t33-identity-package-input/v1'or old.get('candidate_package_id')!=parent['id']or parent['identity_extension'].get('input')!=data['parent_inputs']:raise ValueError('execution parent input')
 if data.get('execution_abi')!='strata-deepseek-execution/v1':raise ValueError('execution ABI')
 original={r['relative_destination']:r for r in old['selected_files']};actual={r['relative_destination']:r for r in data['selected_files']}
 changed={'native/Strata-deepseek.exe','Strata-extensions/models/deepseek41/server_hooks.py'};extra={'Strata-extensions/control/contracts.py'}
 if len(original)!=62 or len(actual)!=63 or len(seen)!=63 or seen!=set(original)|extra or type(data.get('expected_copy_count'))is not int or data['expected_copy_count']!=63:raise ValueError('execution finite file scope')
 if data.get('public_write_executed')is not False or data.get('venv_not_copied')is not True or data.get('runtime_python_created_at_final_location')is not True:raise ValueError('execution assembly scope')
 for r in parent['files']:check_record(r)
 for relative,oldrow in original.items():
  current=record(destination(root,relative))
  if any(current[k]!=oldrow[k]for k in ('bytes','sha256')):raise ValueError('execution accepted parent changed')
  if relative not in changed and any(actual[relative][k]!=oldrow[k]for k in ('bytes','sha256')):raise ValueError('execution protected parent copy')
 for row in actual.values():check_record(dict(path=row['source'],bytes=row['bytes'],sha256=row['sha256']))
 n=data['native_manifest'];check_record(dict(path=n['source'],bytes=n['bytes'],sha256=n['sha256']))
 if n['relative_destination']!='evidence/native-manifest.json':raise ValueError('execution native destination')
 native=load(n['source'])
 if native.get('compiled_source_id')!=data.get('native_compiled_source_id')or native.get('both_arch')is not True or native.get('normal')is not True:raise ValueError('execution native source identity')
 identities=[r for r in native.get('CPU',[])if r.get('flag')=='--identity']
 if len(identities)!=1:raise ValueError('execution native identity observation')
 identity=identities[0];exe=identity['exe'];check_record(exe)
 if identity.get('exit')!=0 or identity.get('stderr')!=''or load_json_identity(identity.get('stdout'))!=native['compiled_source_id']or any(exe[k]!=actual['native/Strata-deepseek.exe'][k]for k in ('bytes','sha256')):raise ValueError('execution selected native executable')
 expected_dll={pathlib.PurePosixPath(p).name:r for p,r in actual.items()if p.startswith('native/')and p.endswith('.dll')};dlls=data.get('native_bundle_dlls')
 if type(dlls)is not list or len(dlls)!=len(expected_dll)or len({pathlib.Path(r['path']).name for r in dlls})!=len(dlls):raise ValueError('execution native DLL set')
 for row in dlls:
  path=check_record(row);selected=expected_dll.get(path.name)
  if path.resolve().parent!=pathlib.Path(exe['path']).resolve().parent or selected is None or any(row[k]!=selected[k]for k in ('bytes','sha256')):raise ValueError('execution native DLL selection')

def load_json_identity(raw):
 try:return json.loads(raw)['source_set_sha256']
 except (TypeError,ValueError,KeyError):raise ValueError('execution identity JSON')

def public_INFO_profile_preflight(inputs):
 # Exact accepted predecessor only; this runs before even the work directory exists.
 if 'public_INFO_predecessor_input'not in inputs:return None
 predecessor=inputs['public_INFO_predecessor_input'];check_record(predecessor)
 if predecessor['sha256']!='0c6657974d2e9ab238b0f3b80fc41b0736c2882c352c97159cf21b5f9c61af8e':raise ValueError('public assembler predecessor input hash')
 prior=load(predecessor['path']);oldid='de662662c8da4ab6ba8d3c3f1ca5f61309cf95d52b88e75827858862b418fddf'
 if prior['candidate_package_id']!=oldid or inputs['candidate_package_id']==oldid:raise ValueError('public assembler predecessor/candidate identity')
 for key in ('parent_inputs','parent_package','parent_id','execution_abi'):
  if inputs.get(key)!=prior.get(key):raise ValueError('public assembler unchanged source field: '+key)
 oldfiles={r['relative_destination']:r for r in prior['selected_files']};newfiles={r['relative_destination']:r for r in inputs['selected_files']}
 allowed={'native/Strata-deepseek.exe','Strata-extensions/models/deepseek41/server_hooks.py','Strata-extensions/control/contracts.py'}
 if len(oldfiles)!=63 or len(newfiles)!=63 or set(oldfiles)!=set(newfiles) or not {k for k in oldfiles if any(oldfiles[k][field]!=newfiles[k][field]for field in ('bytes','sha256'))}<=allowed:raise ValueError('public assembler finite 63 payload')
 oldroot=package_paths(DATA.parent/'Strata-extensions',oldid)['root']
 if digest(oldroot/'evidence/package-manifest.json')!='977ee5c2b1f2dca1604f5023271f5204a47b9b446c81fd00caf6d705ffc197c1':raise ValueError('public assembler old manifest changed')
 expected={'deepseek-v4.1-flash-1017-ud-q4_k_xl-4096.json': (6491, 'a2257f7d606128f8b804dd2bdad156873ebc7636718119ccd7d6da77b39f0824'), 'deepseek-v4.1-flash-1017-ud-q4_k_xl-32768.json': (6493, '7b723f4b446e397e0bde7d73c0895a859f0c3e172de53a2e3f07a363cb8c870a'), 'deepseek-v4.1-flash-1017-ud-q4_k_xl-131072.json': (6495, '8f224d79d6076266c4ee5ca62233a205d1318c82f3283937cb1361c08270078f'), 'deepseek-v4.1-flash-1017-ud-q4_k_xl-262144.json': (6495, '2d067fd4d7fd16c8b014160332da4eb1e051960798ea496c988fc71745238507'), 'deepseek-v4.1-flash-1017-ud-q4_k_xl-524288.json': (6495, 'b2338585a610e93e2f22c7fcf91f5a58c615ce21f92e53c4d467877bb1ea5e0a'), 'deepseek-v4.1-flash-1017-ud-q4_k_xl-1048576.json': (6497, '2420e3f351d5cdd76e5e86651bbad332a2628778248cb3ec61b6ba449438b556')}
 for name,(size,sha)in expected.items():
  path=DATA/'profiles'/name
  if record(path)!=dict(path=str(path),bytes=size,sha256=sha):raise ValueError('public assembler current profile hash')
  cfg=load(path)
  if cfg['runtime_package']!={'id':oldid,'manifest':str(oldroot/'evidence/package-manifest.json')}:raise ValueError('public assembler current profile predecessor fields')
  if cfg['bundle_id']!=prior['native_manifest']['sha256']:raise ValueError('public assembler current profile native binding')
 return str(oldroot)

def assemble_client_candidate(input_path, *, identity_extension=False, execution_extension=False):
 """Final-path CPU assembly only. Profiles remain at their accepted parent bytes."""
 input_path=pathlib.Path(input_path).resolve();inputs=selected_inputs(input_path)
 if identity_extension and execution_extension:raise ValueError('one candidate extension per assembly')
 expected_schema='strata-t46-execution-package-input/v1'if execution_extension else('strata-t33-identity-package-input/v1'if identity_extension else'strata-t31-client-package-input/v1')
 if inputs['schema']!=expected_schema:raise ValueError('client input schema')
 public_oldroot=public_INFO_profile_preflight(inputs)if execution_extension else None
 work=ROOT/('build-deepseek-t46/package-candidate-'+inputs['candidate_package_id'][:12]if execution_extension else('build-deepseek-t33/identity-candidate-r1'if identity_extension else'build-deepseek-t31/package-candidate-r1'));work.mkdir(exist_ok=False)
 before=protected(DATA/'profiles');catalog=record(DATA/'model_catalog.py')
 paths=package_paths(DATA.parent/'Strata-extensions',inputs['candidate_package_id']);root=paths['root']
 if root.exists():raise ValueError('candidate destination already exists; preserve unknown or prior bytes')
 own=[EXT/'clients'/n for n in ('stream_contract.py','chat_adapter.py','web_stream.js','package_clients.py')]+[EXT/'tests/clients'/n for n in ('contract.json','test_clients.py','test_web_stream.mjs','build_verify.py')]+[pathlib.Path(__file__),DATA/'strata_cli.py']
 if identity_extension:
  own=[EXT/'clients'/n for n in ('runtime_identity.py','runtime_identity.js','stream_contract.py','web_stream.js','chat_adapter.py','package_clients.py')]+[EXT/'tests/lifecycle'/n for n in ('client_contract.json','test_clients.py','test_clients.mjs','build_verify.py','sdk_agents.mjs')]+[pathlib.Path(__file__),DATA/'strata_cli.py',DATA.parent/'Pi/guard-extension.mjs']
 if execution_extension:
  own=[EXT/'control/deepseek_launch.py',EXT/'control/providers/deepseek41.py',EXT/'control/contracts.py',EXT/'models/deepseek41/server_hooks.py',EXT/'tests/execution/test_modes.py',EXT/'tests/execution/mode_fixture.py',pathlib.Path(__file__),DATA/'strata_cli.py']
 source_map=[copy_checked(record(p),work/'source'/str(i)/p.name)for i,p in enumerate(own)]
 write(work/'source-map.json',dict(records=source_map))
 write(work/'capacity-before.json',dict(fresh_free=shutil.disk_usage(root.parent.parent.parent.parent).free,copy_payload=inputs['copy_payload_bytes'],engineering_future=536870912,held_already_reflected=True,normal_cache_limit=False))
 root.mkdir(parents=True);(root/'evidence').mkdir();copies=[]
 try:
  for r in inputs['selected_files']:
   copies.append(copy_checked(dict(path=r['source'],bytes=r['bytes'],sha256=r['sha256']),destination(root,r['relative_destination'])))
  n=inputs['native_manifest'];copies.append(copy_checked(dict(path=n['source'],bytes=n['bytes'],sha256=n['sha256']),root/'evidence/native-manifest.json'))
  copies.append(copy_checked(inputs['parent_package'],root/'evidence/parent-package-manifest.json'))
  parent_root=pathlib.Path(inputs['parent_package']['path']).parent.parent
  policy_name='parent-allocation-policy.json'if identity_extension or execution_extension else'allocation-policy.json'
  copies.append(copy_checked(record(parent_root/'evidence'/policy_name),root/'evidence/parent-allocation-policy.json'))
  oldroot=public_oldroot if public_oldroot is not None else str(parent_root);newroot=str(root)
  def relocated(value):
   if type(value)is dict:return {k:relocated(v)for k,v in value.items()}
   if type(value)is list:return [relocated(x)for x in value]
   if type(value)is str:return value.replace(oldroot,newroot).replace(oldroot.replace('\\','/'),newroot.replace('\\','/'))
   return value
  profiles=[];(work/'profiles').mkdir()
  provider_path=DATA.parent/'Strata-extensions/control/providers/deepseek41.py'if identity_extension else EXT/'control/providers/deepseek41.py'
  provider_dependency=record(provider_path)
  provider=module('t31_candidate_provider',provider_path)
  for context in (4096,32768,131072,262144,524288,1048576):
   original=DATA/'profiles'/f'{provider.MODEL}-{context}.json';cfg=relocated(load(original));cfg['runtime_package']['id']=inputs['candidate_package_id'];cfg['bundle_id']=inputs['native_manifest']['sha256']
   if execution_extension:cfg['execution_defaults']=mode_options(paths,cfg['bundle_id'],context,DATA)['execution_defaults']
   provider.normal_fields(cfg);provider.validate_profile(cfg,context)
   target=work/'profiles'/original.name;write(target,cfg);profiles.append(dict(known_old=record(original),candidate=record(target),destination=str(original)))
  wheels=[record(destination(root,r['relative_destination']))for r in inputs['selected_files']if r['relative_destination'].startswith('wheelhouse/')]
  lock=root/'evidence/requirements.lock';lock.write_text('\n'.join(lock_line(r)for r in wheels)+'\n',encoding='utf-8')
  env=dict(os.environ);env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
  call([BASE_PYTHON,'-E','-s','-B','-X','utf8','-m','venv',root/'venv'],work,'create-venv',env)
  call([paths['python'],'-E','-s','-B','-X','utf8','-m','pip','install','--no-index','--no-deps','--require-hashes','-r',lock],work,'install-fixed-wheels',env)
  cfg=load(profiles[0]['candidate']['path']);cfg['runtime_epoch']=1;write(root/'evidence/cpu-config.json',cfg)
  probe=PROBE.replace("root/'tokenizer.json'","root/'resources/tokenizer.json'").replace("root/'config.json'","root/'evidence/cpu-config.json'").replace("root/'probe-result.json'","root/'evidence/probe-result.json'")
  if identity_extension or execution_extension:probe=probe.replace("assert hook.install(server,{'family':'huihui'})is False","assert hook.install(server,{'family':'huihui'})is False\n"+IDENTITY_PROBE)
  (root/'evidence/probe.py').write_text(probe,encoding='utf-8');empty=work/'empty';empty.mkdir()
  env.update(PYTHONPATH='C:/nonexistent-T31-poison',PYTHONHOME='C:/nonexistent-T31-poison')
  call([paths['python'],'-E','-s','-B','-X','utf8',paths['entry'],'--config',root/'evidence/cpu-config.json','--help'],work,'selected-entry-help',env,empty)
  call([paths['python'],'-E','-s','-B','-X','utf8',root/'evidence/probe.py',root],work,'selected-location-probe',env,empty)
  call([paths['python'],'-E','-s','-B','-m','pip','check'],work,'pip-check',env,empty)
  call([paths['python'],'-E','-s','-B','-X','utf8',root/'clients/chat.py','--help'],work,'selected-chat-help',env,empty)
  for r in copies:check_record(r['source']);check_record(r['copy'])
  files=[record(p)for p in sorted(root.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
  manifest=dict(schema='strata-t29-runtime-package/v1',id=inputs['candidate_package_id'],native_manifest_sha256=inputs['native_manifest']['sha256'],copies=copies,files=files,base_python=record(BASE_PYTHON),normal_model_qualification=False,stage_cpu_scope=True,client_extension=dict(parent_id=inputs['parent_id'],input=record(input_path)))
  if identity_extension:manifest['identity_extension']=dict(schema='strata-runtime-identity/v1',parent_id=inputs['parent_id'],input=record(input_path))
  if execution_extension:
   parent=load(inputs['parent_package']['path']);manifest['client_extension']=parent['client_extension'];manifest['identity_extension']=parent['identity_extension']
   manifest['execution_extension']=dict(abi=inputs['execution_abi'],parent_id=inputs['parent_id'],input=record(input_path))
  write(paths['manifest'],manifest)
  for r in source_map:check_record(r['source']);check_record(r['copy'])
  check_record(provider_dependency)
  if protected(DATA/'profiles')!=before:raise ValueError('profile bytes changed during client CPU assembly')
  check_record(catalog)
  proof=dict(schema='strata-t46-execution-candidate-CPU/v1'if execution_extension else('strata-t33-identity-candidate-CPU/v1'if identity_extension else'strata-t31-client-candidate-CPU/v1'),input=record(input_path),source_map=record(work/'source-map.json'),package_manifest=record(paths['manifest']),package_root=str(root),profiles=profiles,protected_profiles=before,catalog=catalog,probe=record(root/'evidence/probe-result.json'),actual_bytes=sum(p.stat().st_size for p in root.rglob('*')if p.is_file()),CPU_only=True,new_native_model_qualified=False,public_profiles_updated=False,native_or_listener_started=False,GPU=0,wholeT31=False)
  proof['profile_validator_dependency']=provider_dependency
  write(work/'verification.json',proof);print(json.dumps(record(work/'verification.json')));return proof
 except BaseException as error:
  write(work/'failure.json',dict(type=type(error).__name__,message=str(error),package_preserved=str(root),public_profiles_updated=False));raise

def assemble_identity_candidate(input_path):
 return assemble_client_candidate(input_path,identity_extension=True)

def assemble_execution_candidate(input_path):
 return assemble_client_candidate(input_path,execution_extension=True)

def replace_known_profile_batch(rows):
 """Explicit reviewed replacement of exact known-old bytes; preflight the whole set."""
 targets=set();prepared=[]
 for item in rows:
  target=pathlib.Path(item['destination']).resolve()
  if target in targets:raise ValueError('duplicate profile target')
  targets.add(target)
  if pathlib.Path(item['known_old']['path']).resolve()!=target:raise ValueError('known-old target identity')
  check_record(item['known_old']);raw=check_record(item['candidate']).read_bytes()
  prepared.append((item,target,raw))
 temporaries=[]
 try:
  for item,target,raw in prepared:
   temp=target.with_name(target.name+'.t31-new')
   with temp.open('xb')as stream:
    temporaries.append(temp)
    stream.write(raw);stream.flush();os.fsync(stream.fileno())
  for item,_,_ in prepared:check_record(item['known_old'])
  published=[]
  for (item,target,raw),temp in zip(prepared,temporaries,strict=True):
   check_record(item['known_old']);os.replace(temp,target)
   if target.read_bytes()!=raw:raise ValueError('published profile differs')
   published.append(record(target))
  return published
 finally:
  for temp in temporaries:
   if temp.exists():temp.unlink()


def numeric_config(sealed):
 rows=[r for r in sealed['fixed_inputs']if pathlib.Path(r['path']).name=='config.json']
 if len(rows)!=1:raise ValueError('exactly one fixed numeric config required')
 return load(check_record(rows[0]))


def publish_client_profiles(candidate_path,numeric_verification_path):
 """Explicit T31 publication only after the one candidate numeric/SSE observation."""
 candidate_path=pathlib.Path(candidate_path).resolve();candidate=load(candidate_path)
 if candidate['schema']!='strata-t31-client-candidate-CPU/v1'or candidate['public_profiles_updated']is not False:raise ValueError('client candidate scope')
 check_record(candidate['input']);check_record(candidate['package_manifest']);check_record(candidate['catalog'])
 manifest=load(candidate['package_manifest']['path'])
 if manifest['id']!=pathlib.Path(candidate['package_root']).name or not manifest.get('client_extension'):raise ValueError('client package declaration')
 for r in manifest['files']:check_record(r)
 numeric_path=pathlib.Path(numeric_verification_path).resolve();numeric=load(numeric_path)
 check_record(numeric['capture']);check_record(numeric['manifest'])
 if numeric['runtime_before_after']is not True:raise ValueError('candidate runtime changed')
 capture=load(numeric['capture']['path']);sealed=load(numeric['manifest']['path'])
 if capture['actual_native']is not True or capture['actual_HTTP_SSE']is not True:raise ValueError('actual candidate SSE required for this publication')
 if capture['generated_original_ids']!=[4482]or capture['request_ids']!=[0,128803,128804,128822]:raise ValueError('candidate numeric input/output')
 config=numeric_config(sealed)
 if config['runtime_package']['id']!=manifest['id']or config['bundle_id']!=manifest['native_manifest_sha256']:raise ValueError('candidate numeric version')
 if protected(DATA/'profiles')!=candidate['protected_profiles']:raise ValueError('profiles changed before publication')
 rows=candidate['profiles'];contexts=set()
 provider=module('t31_publish_provider',EXT/'control/providers/deepseek41.py')
 for item in rows:
  target=pathlib.Path(item['destination']).resolve();cfg=load(check_record(item['candidate']));context=cfg['context'];contexts.add(context)
  if target.parent!=(DATA/'profiles').resolve()or target.name!=f'{provider.MODEL}-{context}.json':raise ValueError('profile target scope')
  if cfg['runtime_package']['id']!=manifest['id']or cfg['bundle_id']!=manifest['native_manifest_sha256']or'runtime_epoch'in cfg:raise ValueError('static profile version/epoch')
  provider.normal_fields(cfg);provider.validate_profile(cfg,context)
 if contexts!={4096,32768,131072,262144,524288,1048576}or len(rows)!=6:raise ValueError('six reviewed contexts')
 out=ROOT/'build-deepseek-t31/profile-publication-r1';out.mkdir(exist_ok=False)
 try:
  published=replace_known_profile_batch(rows)
  expected=dict(candidate['protected_profiles']);expected.update({r['path']:r['sha256']for r in published})
  if protected(DATA/'profiles')!=expected:raise ValueError('unrelated profile changed')
  catalog=catalog_module()
  for context in sorted(contexts):catalog.require_ready(provider.MODEL,DATA,context)
  check_record(candidate['catalog'])
  result=dict(schema='strata-t31-profile-publication/v1',candidate=record(candidate_path),numeric_verification=record(numeric_path),package_manifest=candidate['package_manifest'],published=published,protected_before=candidate['protected_profiles'],protected_after=expected,catalog=candidate['catalog'],wholeT31=False,normal_native_started=False,normal_client_entry_qualified=False)
  write(out/'verification.json',result);return result
 except BaseException as error:
  write(out/'failure.json',dict(type=type(error).__name__,error=str(error),saved_current=protected(DATA/'profiles'),candidate=record(candidate_path),package_preserved=True));raise


def identity_publication_inputs(candidate_path,numeric_path):
 """CPU-only join of the metadata extension to its unchanged, qualified parent native."""
 candidate=load(candidate_path)
 if candidate.get('schema')!='strata-t33-identity-candidate-CPU/v1'or candidate.get('public_profiles_updated')is not False:raise ValueError('identity candidate scope')
 for key in ('input','package_manifest','probe','catalog','profile_validator_dependency'):check_record(candidate[key])
 inputs=load(candidate['input']['path']);manifest=load(candidate['package_manifest']['path'])
 if inputs.get('schema')!='strata-t33-identity-package-input/v1'or manifest.get('id')!=inputs['candidate_package_id']or pathlib.Path(candidate['package_root']).name!=manifest['id']:raise ValueError('identity package version')
 declaration=manifest.get('identity_extension')
 if type(declaration)is not dict or declaration.get('schema')!='strata-runtime-identity/v1'or declaration.get('parent_id')!=inputs['parent_id']or declaration.get('input')!=candidate['input']:raise ValueError('identity declaration')
 check_record(inputs['parent_package']);parent=load(inputs['parent_package']['path'])
 if parent['id']!=inputs['parent_id']or parent['native_manifest_sha256']!=manifest['native_manifest_sha256']:raise ValueError('unchanged parent native')
 for r in manifest['files']:check_record(r)
 numeric=load(numeric_path)
 for key in ('capture','manifest'):check_record(numeric[key])
 capture=load(numeric['capture']['path']);sealed=load(numeric['manifest']['path']);config=numeric_config(sealed)
 if numeric.get('runtime_before_after')is not True or capture.get('actual_native')is not True or capture.get('actual_HTTP_SSE')is not True:raise ValueError('qualified parent numeric observation')
 if capture['generated_original_ids']!=[4482]or capture['request_ids']!=[0,128803,128804,128822]:raise ValueError('parent numeric input/output')
 if config['runtime_package']['id']!=inputs['parent_id']or config['bundle_id']!=manifest['native_manifest_sha256']:raise ValueError('parent numeric version')
 new_native=[r for r in manifest['files']if pathlib.Path(r['path']).resolve()==pathlib.Path(candidate['package_root']).resolve()/'native/Strata-deepseek.exe']
 if len(new_native)!=1 or digest(config['exe'])!=new_native[0]['sha256']:raise ValueError('same qualified executable bytes')
 rows=candidate['profiles'];provider=module('t33_publish_provider',candidate['profile_validator_dependency']['path']);contexts=set()
 if protected(DATA/'profiles')!=candidate['protected_profiles']:raise ValueError('profiles changed before identity publication')
 for item in rows:
  check_record(item['known_old']);cfg=load(check_record(item['candidate']));context=cfg['context'];contexts.add(context);target=pathlib.Path(item['destination']).resolve()
  if target.parent!=(DATA/'profiles').resolve()or target.name!=f'{provider.MODEL}-{context}.json':raise ValueError('identity profile destination')
  if cfg['runtime_package']['id']!=manifest['id']or cfg['bundle_id']!=manifest['native_manifest_sha256']or'runtime_epoch'in cfg:raise ValueError('identity profile version')
  provider.normal_fields(cfg);provider.validate_profile(cfg,context)
 if len(rows)!=6 or contexts!={4096,32768,131072,262144,524288,1048576}:raise ValueError('identity six contexts')
 return candidate,manifest


def publish_identity_profiles(candidate_path,numeric_path):
 candidate,manifest=identity_publication_inputs(candidate_path,numeric_path)
 out=ROOT/'build-deepseek-t33/profile-publication-r1';out.mkdir(exist_ok=False)
 try:
  published=replace_known_profile_batch(candidate['profiles']);expected=dict(candidate['protected_profiles']);expected.update({r['path']:r['sha256']for r in published})
  if protected(DATA/'profiles')!=expected:raise ValueError('unrelated identity profile change')
  provider=module('t33_published_provider',candidate['profile_validator_dependency']['path']);catalog=catalog_module()
  for context in (4096,32768,131072,262144,524288,1048576):catalog.require_ready(provider.MODEL,DATA,context)
  check_record(candidate['catalog']);check_record(candidate['profile_validator_dependency'])
  result=dict(schema='strata-t33-identity-profile-publication/v1',candidate=record(candidate_path),parent_numeric=record(numeric_path),package_manifest=candidate['package_manifest'],published=published,protected_before=candidate['protected_profiles'],protected_after=expected,catalog=candidate['catalog'],native_bytes_unchanged=True,new_model_generation=False,normal_native_started=False,wholeT33=False)
  write(out/'verification.json',result);return result
 except BaseException as error:
  write(out/'failure.json',dict(type=type(error).__name__,error=str(error),candidate=record(candidate_path),saved_current=protected(DATA/'profiles'),package_preserved=True));raise


def execution_publication_inputs(publication_input_path, *, accepted_numeric):
 """Read-only finite T46 join; accepted numeric review is supplied by the caller."""
 def require(ok,message):
  if not ok:raise ValueError('T46 publication: '+message)
 def exact(row):
  require(type(row)is dict and set(row)=={'path','bytes','sha256'},'record fields')
  path=pathlib.Path(row['path']);require(path.is_absolute()and str(path.resolve())==row['path'],'absolute resolved record')
  check_record(row);return path
 p=pathlib.Path(publication_input_path).resolve();input_record=record(p);value=load(p)
 require(set(value)=={'schema','plan','candidate','numeric','helpers','protected','attempt_directory'}and value['schema']=='strata-t46-execution-publication-input/v1','input fields/schema')
 for k in ('plan','candidate','numeric'):exact(value[k])
 require(set(accepted_numeric)=={'numeric','reviewed_source_map','existing_review_record','scope'}and accepted_numeric['scope']=='T46-final-single-publication-prerequisite','accepted scope')
 require(accepted_numeric['numeric']==value['numeric'],'reviewed numeric identity')
 for k in ('numeric','reviewed_source_map','existing_review_record'):exact(accepted_numeric[k])
 attempt=pathlib.Path(value['attempt_directory']);require(attempt.is_absolute()and str(attempt.resolve())==str(attempt)and attempt.is_relative_to(ROOT/'build-deepseek-t46')and attempt!=ROOT/'build-deepseek-t46','attempt scope')
 candidate=load(value['candidate']['path'])
 require(candidate.get('schema')=='strata-t46-execution-candidate-CPU/v1'and candidate.get('public_profiles_updated')is False,'candidate scope')
 for k in ('input','package_manifest','probe','catalog','profile_validator_dependency','source_map'):exact(candidate[k])
 inputs=selected_inputs(candidate['input']['path']);manifest=load(candidate['package_manifest']['path']);root=pathlib.Path(candidate['package_root']).resolve()
 require(inputs['schema']=='strata-t46-execution-package-input/v1'and manifest['id']==inputs['candidate_package_id']==root.name,'execution input/candidate/manifest')
 require(root==package_paths(DATA.parent/'Strata-extensions',manifest['id'])['root'].resolve(),'candidate final root')
 require(manifest.get('execution_extension')==dict(abi=inputs['execution_abi'],parent_id=inputs['parent_id'],input=candidate['input']),'execution declaration')
 parent=load(check_record(inputs['parent_package']))
 require(all(manifest[k]==parent[k]for k in ('client_extension','identity_extension'))and manifest['native_manifest_sha256']==inputs['native_manifest']['sha256'],'parent/native preservation')
 for row in manifest['files']:exact(row)
 for row in manifest['copies']:exact(row['copy']);exact(row['source'])
 # Captured assembly sources are immutable history, not the current publisher.
 for row in load(candidate['source_map']['path'])['records']:
  exact(row['copy']);require(all(row['copy'][k]==row['source'][k]for k in ('bytes','sha256')),'captured assembly source history')
  if pathlib.Path(row['source']['path']).resolve()!=pathlib.Path(__file__).resolve():exact(row['source'])
 numeric=load(value['numeric']['path'])
 fields='candidate package_manifest input seal source_map config request observer_spec observer_capture observer_validation raw_control raw_complete SSE service_result Q_expectation numerical_comparison owner argv_and_INFO runtime_DLLs model9_before model9_after protected_before protected_after cleanup timing counter_evidence'.split()
 contact_refs={'native_stderr':'native-stderr.raw','native_stderr_capture':'native-stderr.json','wait_validation':'wait-validation.json','fresh_INFO':'fresh-INFO-receipt.json'}
 fields+=list(contact_refs)
 flags={'schema':'strata-t46-final-single-numeric/v1','mode':'single','actual_native':True,'actual_HTTP_SSE':True,'complete_request_count':1,'control_request_count':1,'normal_numeric_qualified':True,'wholeT46_complete':False}
 require(set(numeric)==set(fields)|set(flags)|{'run_id'},'actual numeric finite schema')
 for k,v in flags.items():require(type(numeric[k])is type(v)and numeric[k]==v,'actual numeric '+k)
 for k in fields:exact(numeric[k])
 for key,name in contact_refs.items():require(exact(numeric[key])==(pathlib.Path(value['numeric']['path']).parent/name).resolve(),'actual numeric contact ref path: '+key)
 require(numeric['candidate']==value['candidate']and numeric['package_manifest']==candidate['package_manifest']and numeric['input']==candidate['input'],'numeric candidate identity')
 require(numeric['source_map']==accepted_numeric['reviewed_source_map'],'reviewed single source map')
 sealed=load(numeric['seal']['path']);source_map=load(numeric['source_map']['path'])
 require(sealed['candidate_input']==candidate['input']and sealed['candidate_proof']==value['candidate']and sealed['package_id']==source_map['package_id']==manifest['id'],'pre-G candidate seal')
 require(sealed['bundle_id']==source_map['bundle_id']==manifest['native_manifest_sha256']and sealed['records']==source_map['records'],'pre-G source domain')
 for row in source_map['records']:exact(row)
 runner_path=(ROOT/'build-deepseek-t46/actual-mode-runner/runner.py').resolve()
 if 'selected_contact' in candidate:
  descriptor=load(exact(candidate['selected_contact']))
  require(descriptor['input']==candidate['input']and descriptor['package_manifest']==candidate['package_manifest'],'selected contact publisher descriptor')
  runner_path=exact(descriptor['runner'])

 runners=[r for r in source_map['records']if pathlib.Path(r['path']).resolve()==runner_path]
 require(len(runners)==1,'sealed actual numeric replay source')
 replay=module('t46_publication_numeric_replay',exact(runners[0]))
 # Replay uses existing observer/DTO/Codec/Q checks; no alternate numeric algorithm.
 replay.replay_final_single_numeric(value['numeric']['path'])
 require(load(numeric['model9_before']['path'])==load(numeric['model9_after']['path']),'Model9 before/after')
 require(load(numeric['protected_before']['path'])==load(numeric['protected_after']['path']),'protected numeric before/after')
 protection=value['protected'];require(set(protection)=={'catalog','profile_defaults','bootstrap','profiles'},'protected fields')
 expected_protected={'catalog':DATA/'model_catalog.py','profile_defaults':DATA/'profile_defaults.py','bootstrap':DATA.parent/'Strata-extensions/control/deepseek_bootstrap.py'}
 for k,path in expected_protected.items():require(exact(protection[k])==path.resolve(),'protected canonical '+k)
 require(protection['catalog']==candidate['catalog']and protection['profiles']==candidate['protected_profiles']==protected(DATA/'profiles'),'whole public profile snapshot')
 helpers=value['helpers'];require(type(helpers)is list and len(helpers)==2,'two helper targets')
 canonical=[DATA.parent/'Strata-extensions/control/deepseek_launch.py',DATA.parent/'Strata-extensions/control/providers/deepseek41.py']
 for item,role,target,relative in zip(helpers,('helper','provider'),canonical,('control/deepseek_launch.py','control/providers/deepseek41.py'),strict=True):
  require(set(item)=={'role','destination','known_old','candidate'}and item['role']==role,'helper fields/order')
  require(pathlib.Path(item['destination'])==target.resolve()and exact(item['known_old'])==target.resolve(),'canonical helper target')
  require(exact(item['candidate'])==(EXT/relative).resolve(),'selected helper/provider source')
 require(candidate['profile_validator_dependency']==helpers[1]['candidate'],'candidate provider dependency')
 provider=module('t46_publication_candidate_provider',helpers[1]['candidate']['path'])
 rows=candidate['profiles'];require(type(rows)is list and len(rows)==6,'six profiles')
 contexts=[];allowed={'bundle_id','cwd','lib_dirs','tokenizer','exe','python','server_entry','upstream_root','runtime_package','execution_defaults'}
 for item in rows:
  require(set(item)=={'destination','known_old','candidate'},'profile fields')
  old=load(exact(item['known_old']));cfg=load(exact(item['candidate']));context=cfg['context'];contexts.append(context)
  target=(DATA/'profiles'/f'{provider.MODEL}-{context}.json').resolve()
  require(pathlib.Path(item['destination'])==target and pathlib.Path(item['known_old']['path'])==target,'canonical profile target')
  require(set(old)<=set(cfg)and set(cfg)-set(old)<={'execution_defaults'}and {k for k in old if old[k]!=cfg[k]}<=allowed,'profile permitted difference')
  require('runtime_epoch'not in cfg and cfg['runtime_package']==dict(id=manifest['id'],manifest=candidate['package_manifest']['path'])and cfg['bundle_id']==manifest['native_manifest_sha256'],'profile candidate identity/epoch')
  require(cfg['placement']['mode']=='single'and cfg['execution_defaults']==mode_options(package_paths(DATA.parent/'Strata-extensions',manifest['id']),cfg['bundle_id'],context,DATA)['execution_defaults'],'preserved single/defaults')
  provider.normal_fields(cfg);provider.validate_profile(cfg,context)
 require(contexts==[4096,32768,131072,262144,524288,1048576],'ordered six contexts')
 allrows=helpers+rows;require(len({str(pathlib.Path(r['destination']).resolve())for r in allrows})==8,'eight unique targets')
 for r in allrows:exact(r['known_old']);exact(r['candidate'])
 check_record(input_record)
 return dict(input=value,publication_input=input_record,candidate=candidate,manifest=manifest,rows=allrows,protected=protection,numeric=numeric)


def publish_execution_profiles(publication_input_path, *, accepted_numeric, publication_guard):
 """Explicit known-old helper -> provider -> six profiles; failures stop in place."""
 publication_input_path=pathlib.Path(publication_input_path).resolve();invocation_sources=[record(__file__),record(publication_input_path)];value=load(publication_input_path)
 out=pathlib.Path(value['attempt_directory'])
 if not out.is_absolute()or str(out.resolve())!=str(out)or not out.is_relative_to(ROOT/'build-deepseek-t46')or out==ROOT/'build-deepseek-t46':raise ValueError('T46 publication attempt scope')
 out.mkdir(exist_ok=False)
 stages=[];rows=[];original=None;guard_error=None;result=None;source_rows=[]
 def guard():
  if publication_guard()is not True:raise ValueError('T46 fresh publication guard did not prove quiescence under caller operation lock')
 def verify_sources():
  for r in source_rows:check_record(r)
 def verify_protected(expected):
  for k in ('catalog','profile_defaults','bootstrap'):check_record(value['protected'][k])
  if protected(DATA/'profiles')!=expected:raise ValueError('T46 protected/public profile drift')
 def states():
  current=[]
  for item in rows:
   try:
    row=record(item['destination']);kind='old'if row['sha256']==item['known_old']['sha256']else('new'if row['sha256']==item['candidate']['sha256']else'foreign')
    current.append(dict(current=row,classification=kind,before=item['known_old'],expected_new=item['candidate']))
   except BaseException as e:current.append(dict(path=item['destination'],classification='unknown',error=repr(e),before=item['known_old'],expected_new=item['candidate']))
  return current
 try:
  # Preserve current target evidence even if the read-only preflight rejects.
  preliminary=load(value['candidate']['path'])
  proposed=value['helpers']+preliminary.get('profiles',[])
  if len(proposed)==8 and all(type(r)is dict and {'destination','known_old','candidate'}<=set(r)for r in proposed):rows=proposed
  joined=execution_publication_inputs(publication_input_path,accepted_numeric=accepted_numeric);rows=joined['rows'];candidate=joined['candidate'];manifest=joined['manifest']
  for r in invocation_sources:check_record(r)
  if joined['publication_input']!=invocation_sources[1]:raise ValueError('T46 publication input changed during preflight')
  source_rows=invocation_sources+[value['plan'],value['candidate'],value['numeric'],accepted_numeric['reviewed_source_map'],accepted_numeric['existing_review_record'],candidate['input'],candidate['package_manifest'],candidate['source_map']]+[r['candidate']for r in rows]+[value['protected'][k]for k in ('catalog','profile_defaults','bootstrap')]
  source_rows += [r for r in joined['numeric'].values()if type(r)is dict and set(r)=={'path','bytes','sha256'}]
  source_rows += load(joined['numeric']['source_map']['path'])['records']+manifest['files']
  source_rows += [r['copy']for r in load(candidate['source_map']['path'])['records']]
  source_rows += [r['source']for r in manifest['copies']]
  source_rows=list({r['path']:r for r in source_rows}.values());verify_sources();write(out/'source-map.json',dict(records=source_rows,package_id=manifest['id'],scope='T46 publication operation; distinct from numeric pre-G source domain'))
  write(out/'before.json',states());expected=dict(value['protected']['profiles'])
  guard();verify_sources();verify_protected(expected)
  # Whole-eight preflight precedes the first helper mutation.
  for r in rows:check_record(r['known_old']);check_record(r['candidate'])
  installed=[]
  for label,group in (('helper',rows[:1]),('provider',rows[1:2]),('profiles6',rows[2:])):
   guard();verify_sources();verify_protected(expected)
   installed+=replace_known_profile_batch(group);stages.append(label)
   expected.update({str(pathlib.Path(r['destination']).resolve()):r['candidate']['sha256']for r in group if pathlib.Path(r['destination']).parent.resolve()==(DATA/'profiles').resolve()})
   for r in installed:check_record(r)
  verify_sources();verify_protected(expected);guard()
  catalog=catalog_module();provider=catalog._family_provider(DATA)
  if pathlib.Path(provider.__file__).resolve()!=pathlib.Path(rows[1]['destination']).resolve():raise ValueError('T46 installed provider resolution')
  for item in rows[2:]:
   cfg=load(item['destination']);provider.validate_profile(cfg,cfg['context']);catalog.require_ready(provider.MODEL,DATA,cfg['context'])
   if not catalog.availability(provider.MODEL,DATA,cfg['context'])[0]:raise ValueError('T46 installed pure availability')
  if not catalog.availability(provider.MODEL,DATA)[0]:raise ValueError('T46 default pure availability')
  verify_sources();verify_protected(expected)
  for item in rows:
   current=record(item['destination'])
   if any(current[k]!=item['candidate'][k]for k in ('bytes','sha256')):raise ValueError('T46 installed eight readback')
  result=dict(schema='strata-t46-publication/v1',package_id=manifest['id'],complete=True,numeric_review=accepted_numeric['existing_review_record'],numeric_verification=value['numeric'],publication_input=record(publication_input_path),source_map=record(out/'source-map.json'),package_manifest=candidate['package_manifest'],installed_records=[record(r['destination'])for r in rows],result='success')
 except BaseException as error:original=error
 finally:
  try:guard()
  except BaseException as error:
   guard_error=error
   if original is None:original=error
 if original is not None:
  temp_observations=[]
  for item in rows:
   observation=dict(path=item['destination'],present=None,observation='unknown')
   try:
    target=pathlib.Path(item['destination']);temp=target.with_name(target.name+'.t31-new')
    observation['path']=str(temp);observation['present']=temp.exists();observation['observation']='observed'
   except BaseException as error:observation['error']=repr(error)
   temp_observations.append(observation)
  result=dict(schema='strata-t46-publication/v1',complete=False,result='failed',stages=stages,current=states(),error=dict(type=type(original).__name__,message=str(original)),final_guard_error=None if guard_error is None else repr(guard_error),unperformed=['later publication stages','normal runtime generation'],temp_cleanup=temp_observations)
 try:write(out/'publication.json',result)
 except BaseException as save_error:
  if original is not None:
   original.add_note('T46 publication receipt save failed: '+repr(save_error));raise original from save_error
  raise
 if original is not None:raise original
 return result


def deployment_candidate(input_path):
 """Create prospective public diffs under B29; no public filesystem writes."""
 out=BUILD/'deployment-candidate-r2'
 if out.exists():raise ValueError('candidate exists; preserve this fixed candidate')
 out.mkdir();before=protected(DATA/'profiles');catalog=record(DATA/'model_catalog.py');inputs=selected_inputs(input_path)
 source_copies=[copy_checked(record(p),out/'source'/str(i)/p.name)for i,p in enumerate(scope_sources())]
 write(out/'source-map.json',dict(records=source_copies))
 paths=package_paths(DATA.parent/'Strata-extensions',inputs['candidate_package_id']);provider=module('t29_deploy_provider',EXT/'control/providers/deepseek41.py')
 source={x['relative_destination']:x['source']for x in inputs['selected_files']}
 target_root=ROOT/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json'
 # Provider owns the exact original path list; no fixture source TSV is used.
 acquire=module('t29_deploy_acquire',EXT/'native/artifact/full_acquire.py');artifact=acquire.DESTINATION
 asset=dict(artifact_root=str(artifact),native_paths=provider.paths(str(artifact)),fixedrevision=provider.REVISION,layout=provider.LAYOUT,tokenizer=str(target_root),exe=source['native/Strata-deepseek.exe'])
 profiles=[]
 for context in (4096,32768,131072,262144,524288,1048576):
  options=normal_options(paths,inputs['native_manifest']['sha256'],context,DATA)
  ordinary={k:v for k,v in options.items()if k not in ('python','server_entry','upstream_root','runtime_package')}
  profile=provider.profile(asset,context,ordinary);profile.update(options,exe=str(paths['native']),tokenizer=str(paths['tokenizer']));provider.normal_fields(profile)
  p=out/(provider.MODEL+'-'+str(context)+'.json');write(p,profile);profiles.append(dict(source=record(p),destination=str(DATA/'profiles'/p.name)))
 publish_sources=[dict(source=record(EXT/rel),destination=str(DATA.parent/'Strata-extensions'/rel))for rel in ('control/providers/__init__.py','control/providers/deepseek41.py','control/contracts.py')]
 for p in (DATA/'profiles').glob('*.json'):
  old=load(p)
  if old.get('model_name')==provider.MODEL:continue
  occupied={old.get('model_name','').casefold()}|{x.casefold()for x in old.get('aliases',[])if type(x)is str}
  aliases=load(profiles[0]['source']['path'])['aliases']
  if occupied.intersection(x.casefold()for x in aliases):raise ValueError('alias collides with another model')
 policy=ROOT/'build-deepseek-t28/normal/normal-allocation-r1/policy-verification.json';row=load(policy)
 if row['native_manifest']['sha256']!=inputs['native_manifest']['sha256']or row['math_and_success_path_unchanged']is not True:raise ValueError('native policy/source correspondence')
 assert protected(DATA/'profiles')==before;check_record(catalog)
 for row in source_copies:check_record(row['source']);check_record(row['copy'])
 proof=dict(schema='strata-t29-deployment-candidate/v1',source_map=record(out/'source-map.json'),input_manifest=record(input_path),package_id=inputs['candidate_package_id'],installed_root=str(DATA.parent/'Strata-extensions'),package_root=str(paths['root']),profiles=profiles,provider_sources=publish_sources,protected_profiles=before,catalog=catalog,policy_proof=record(policy),accepted_closure=record(BUILD/'runtime-stage-verification.json'),planned_base_python=record(BASE_PYTHON),public_mutation=False,native_or_listener=False,GPU_runs=0,static_runtime_epoch_omitted=True,whole_T29_complete=False)
 write(out/'verification.json',proof);print(json.dumps(record(out/'verification.json')));return proof

def publish(candidate_path):
 """Only this explicit, reviewed operation writes selected normal artifacts."""
 candidate_path=pathlib.Path(candidate_path).resolve();candidate=load(candidate_path)
 if candidate['schema']!='strata-t29-deployment-candidate/v1':raise ValueError('candidate schema')
 installed=DATA.parent/'Strata-extensions'
 if pathlib.Path(candidate['installed_root']).resolve()!=installed.resolve():raise ValueError('publication root mismatch')
 for name in ('source_map','input_manifest','catalog','policy_proof','accepted_closure','planned_base_python'):check_record(candidate[name])
 for row in load(candidate['source_map']['path'])['records']:check_record(row['source']);check_record(row['copy'])
 if protected(DATA/'profiles')!=candidate['protected_profiles']:raise ValueError('profiles changed since candidate review')
 inputs=selected_inputs(candidate['input_manifest']['path']);paths=package_paths(installed,inputs['candidate_package_id']);root=paths['root']
 if root.resolve()!=pathlib.Path(candidate['package_root']).resolve():raise ValueError('package destination mismatch')
 # Preflight all public profile/provider targets BEFORE creating the package.
 for row in candidate['profiles']+candidate['provider_sources']:
  source=check_record(row['source']);target=pathlib.Path(row['destination'])
  if target.exists()and (not target.is_file()or target.read_bytes()!=source.read_bytes()):raise ValueError('existing public target differs: '+str(target))
 if root.exists():raise ValueError('package already exists; preserve it and explicitly review reuse')
 logdir=BUILD/'deployment-publication-r1'
 if logdir.exists():raise ValueError('publication receipt directory exists')
 logdir.mkdir();write(logdir/'capacity-before.json',dict(free=shutil.disk_usage(installed.parent).free,new_copy_payload=inputs['copy_payload_bytes'],engineering_estimate=268435456,normal_cache_limit=False,existing_held_not_subtracted=True))
 root.mkdir(parents=True);(root/'evidence').mkdir();copy_rows=[]
 try:
  for row in inputs['selected_files']:
   original=dict(path=row['source'],bytes=row['bytes'],sha256=row['sha256']);target=destination(root,row['relative_destination']);copy_rows.append(copy_checked(original,target))
  original=inputs['native_manifest'];copy_rows.append(copy_checked(dict(path=original['source'],bytes=original['bytes'],sha256=original['sha256']),root/original['relative_destination']))
  policy=copy_checked(candidate['policy_proof'],root/'evidence/allocation-policy.json');copy_rows.append(policy)
  wheels=[record(root/x['relative_destination'])for x in inputs['selected_files']if x['relative_destination'].startswith('wheelhouse/')]
  lock=root/'evidence/requirements.lock';lock.write_text('\n'.join(lock_line(x)for x in wheels)+'\n',encoding='utf-8')
  env=dict(os.environ);env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
  call([BASE_PYTHON,'-E','-s','-B','-X','utf8','-m','venv',root/'venv'],logdir,'create-venv',env)
  call([paths['python'],'-E','-s','-B','-X','utf8','-m','pip','install','--no-index','--no-deps','--require-hashes','-r',lock],logdir,'install-fixed-wheels',env)
  config=load(candidate['profiles'][0]['source']['path']);config.update(context=4096,runtime_epoch=1)
  # This launch-free fixture is never saved into normal DATA profiles.
  write(root/'evidence/cpu-config.json',config)
  probe=PROBE.replace("root/'tokenizer.json'","root/'resources/tokenizer.json'").replace("root/'config.json'","root/'evidence/cpu-config.json'").replace("root/'probe-result.json'","root/'evidence/probe-result.json'")
  (root/'evidence/probe.py').write_text(probe,encoding='utf-8');(logdir/'empty-cwd').mkdir()
  env.update(PYTHONPATH='C:/nonexistent-T29-poison',PYTHONHOME='C:/nonexistent-T29-poison')
  call([paths['python'],'-E','-s','-B','-X','utf8',paths['entry'],'--config',root/'evidence/cpu-config.json','--help'],logdir,'actual-entry-help',env,logdir/'empty-cwd')
  call([paths['python'],'-E','-s','-B','-X','utf8',root/'evidence/probe.py',root],logdir,'final-location-probe',env,logdir/'empty-cwd')
  call([paths['python'],'-E','-s','-B','-m','pip','check'],logdir,'pip-check',env)
  provider=module('t29_publish_provider',EXT/'control/providers/deepseek41.py')
  for row in candidate['profiles']:provider.validate_profile(load(row['source']['path']),load(row['source']['path'])['context'])
  for row in copy_rows:check_record(row['source']);check_record(row['copy'])
  for row in load(candidate['source_map']['path'])['records']:check_record(row['source'])
  check_record(candidate['catalog']);assert protected(DATA/'profiles')==candidate['protected_profiles']
  files=[record(p)for p in sorted(root.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
  write(paths['manifest'],dict(schema='strata-t29-runtime-package/v1',id=candidate['package_id'],native_manifest_sha256=inputs['native_manifest']['sha256'],copies=copy_rows,files=files,base_python=record(BASE_PYTHON),normal_model_qualification=False,stage_cpu_scope=True))
  # Publish provider and prepared profile declarations only after CPU completion.
  published=[]
  for row in candidate['provider_sources']+candidate['profiles']:
   raw=check_record(row['source']).read_bytes();atomic_new(row['destination'],raw);published.append(record(row['destination']))
  catalog=catalog_module()
  for row in candidate['profiles']:
   value=load(row['source']['path']);catalog.require_ready(provider.MODEL,DATA,value['context'])
  if not catalog.availability(provider.MODEL,DATA)[0]:raise ValueError('published pure catalog availability')
  for path,sha in candidate['protected_profiles'].items():
   if digest(path)!=sha:raise ValueError('protected profile changed')
  check_record(candidate['catalog'])
  result=dict(schema='strata-t29-public-package-result/v1',candidate=record(candidate_path),package_manifest=record(paths['manifest']),probe=record(root/'evidence/probe-result.json'),published=published,protected_profiles=candidate['protected_profiles'],catalog=candidate['catalog'],logs=[record(p)for p in sorted(logdir.glob('*.txt'))],native_or_listener_started=False,GPU_runs=0,official_registration=False,T28_normal_qualification=False,whole_T29_complete=False)
  write(logdir/'verification.json',result);print(json.dumps(record(logdir/'verification.json')));return result
 except BaseException as error:
  write(logdir/'failure.json',dict(type=type(error).__name__,message=str(error),public_profile_paths=[r['destination']for r in candidate['profiles']if pathlib.Path(r['destination']).exists()],package_preserved=str(root)))
  raise

def verify_publication(candidate_path):
 """CPU wrapper-only readback after saved publication; never repeats assembly."""
 out=BUILD/'deployment-publication-r1';candidate_path=pathlib.Path(candidate_path).resolve();candidate=load(candidate_path)
 for key in ('source_map','input_manifest','catalog','policy_proof','accepted_closure','planned_base_python'):check_record(candidate[key])
 inputs=selected_inputs(candidate['input_manifest']['path']);paths=package_paths(DATA.parent/'Strata-extensions',inputs['candidate_package_id'])
 manifest=load(paths['manifest'])
 if manifest['id']!=candidate['package_id']or manifest['native_manifest_sha256']!=inputs['native_manifest']['sha256']:raise ValueError('saved package identity')
 for row in manifest['files']:check_record(row)
 for row in manifest['copies']:check_record(row['copy'])
 for row in load(candidate['source_map']['path'])['records']:check_record(row['copy'])
 published=[]
 for row in candidate['provider_sources']+candidate['profiles']:
  original=check_record(row['source']);dest=pathlib.Path(row['destination'])
  if not dest.is_file()or dest.read_bytes()!=original.read_bytes():raise ValueError('saved public file differs: '+str(dest))
  published.append(record(dest))
 current=protected(DATA/'profiles')
 expected=dict(candidate['protected_profiles']);expected.update({row['destination']:row['source']['sha256']for row in candidate['profiles']})
 if current!=expected:raise ValueError('protected/public profile set differs')
 catalog=catalog_module();provider=catalog._family_provider(DATA)
 if pathlib.Path(provider.__file__).resolve()!=(DATA.parent/'Strata-extensions/control/providers/deepseek41.py').resolve():raise ValueError('installed provider resolution')
 for row in candidate['profiles']:
  profile=load(row['destination']);provider.validate_profile(profile,profile['context']);catalog.require_ready(provider.MODEL,DATA,profile['context'])
  if not catalog.availability(provider.MODEL,DATA,profile['context'])[0]:raise ValueError('saved pure availability')
 if not catalog.availability(provider.MODEL,DATA)[0]:raise ValueError('default pure availability')
 check_record(candidate['catalog'])
 sources=[record(p)for p in scope_sources()];copies=[copy_checked(r,out/'cpu-validator-source'/str(i)/pathlib.Path(r['path']).name)for i,r in enumerate(sources)]
 write(out/'cpu-validator-source-map.json',dict(records=copies))
 tests=call([sys.executable,'-E','-s','-B','-X','utf8','-m','unittest','discover','-s',EXT/'tests/providers','-p','test_*.py'],out,'cpu-revalidation-tests')
 for row in sources:check_record(row)
 probe=record(paths['root']/'evidence/probe-result.json');observed=load(probe['path'])
 if observed['native_or_listener_started']is not False or observed['isolated_environment']!={'ignore_environment':1,'no_user_site':1}:raise ValueError('saved CPU probe scope')
 result=dict(schema='strata-t29-public-package-cpu-revalidation/v1',candidate=record(candidate_path),old_publish_failure=record(out/'failure.json'),historical_publish_sources=candidate['source_map'],current_CPU_validator_sources=record(out/'cpu-validator-source-map.json'),package_manifest=record(paths['manifest']),probe=probe,published=published,protected_profiles=candidate['protected_profiles'],catalog=candidate['catalog'],profile_defaults=record(DATA/'profile_defaults.py'),CPU_tests=37,CPU_tests_log=record(out/'cpu-revalidation-tests.stderr.txt'),catalog_provider_path=str(provider.__file__),contexts=[load(r['destination'])['context']for r in candidate['profiles']],package_actual_bytes=sum(p.stat().st_size for p in paths['root'].rglob('*')if p.is_file()),new_profile_or_package_writes_in_revalidation=False,original_package_rebuilt=False,source_before_after=True,GPU_runs=0,native_or_listener_started=False,official_registration=False,T28_normal_qualification=False,whole_T29_complete=False,rollback='Select prior model; leave Huihui/default intact; package and new profile declarations are separate from actual runtime selection')
 write(out/'verification-final.json',result);print(json.dumps(record(out/'verification-final.json')));return result
def call(args,stage,name,env=None,cwd=None):
 result=subprocess.run([str(x)for x in args],cwd=cwd or stage,env=env,capture_output=True,text=True,encoding='utf-8',errors='strict')
 (stage/(name+'.stdout.txt')).write_text(result.stdout,encoding='utf-8');(stage/(name+'.stderr.txt')).write_text(result.stderr,encoding='utf-8')
 if result.returncode:raise RuntimeError(name+' failed: '+str(result.returncode)+'; '+result.stderr[-1200:])
 return result


IDENTITY_PROBE=r'''
import types,threading
identity=load('t33_selected_identity',own/'clients/runtime_identity.py')
old_metrics=server.Service.metrics
svc=types.SimpleNamespace(status_lock=threading.Lock(),status={},live_reqs={},history=[],totals={},engine=types.SimpleNamespace(info={}),loaded=lambda:True,model=cfg['model_name'],reported_ctx=lambda:cfg['context'],vision=None,conv_log=types.SimpleNamespace(poll=lambda *args:{}))
before_metrics=old_metrics(svc)
class ControlledService:
 def model_for(self,req):return cfg['model_name']
run=[('ping',None),('mcp',{'kind':'fixture'}),('event',types.SimpleNamespace(kind='reasoning',text='controlled')),('event',types.SimpleNamespace(kind='tool_call',call=types.SimpleNamespace(id='fixture-call',name='f',arguments={}))),('done',{'finish':'stop','completion_tokens':2})]
base_chunks=list(server.openai_chunks(ControlledService(),{},[0],True,[],64,None,run=run))
identity.install(server,cfg);expected_identity=identity.from_config(cfg)
assert server._deepseek_runtime_identity==expected_identity
result_metrics=server.Service.metrics(svc);assert result_metrics.pop('strata_runtime')==expected_identity
before_metrics.pop('time');result_metrics.pop('time');assert result_metrics==before_metrics
actual_chunks=list(server.openai_chunks(ControlledService(),{},[0],True,[],64,None,run=run))
for before,actual in zip(base_chunks,actual_chunks,strict=True):
 if before is None:assert actual is None;continue
 assert actual.pop('strata_runtime')==expected_identity
 for field in ('id','created'):before.pop(field);actual.pop(field)
 assert actual==before
assert actual_chunks[-1]['choices'][0]['finish_reason']=='tool_calls'
assert actual_chunks[-1]['usage']['completion_tokens']==2
'''

PROBE=r'''
import ctypes,hashlib,importlib,importlib.util,json,os,pathlib,struct,sys
root=pathlib.Path(sys.argv[1]);base=root/'base';own=root/'Strata-extensions'
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
sys.path[:0]=[str(base),str(base/'tools')]
os.environ['STRATA_FAMILY_SOURCE_ROOT']=str(base)
server=load('serve.server',root/'native/server/serve/server.py')
hook=load('t29_selected_hook',own/'models/deepseek41/server_hooks.py')
codec=hook.codec
tok=hook.TokenizerFacade(root/'tokenizer.json')
for text in ('hello','日本語🦀','<｜end▁of▁sentence｜>'):
 assert tok.decode(tok.encode(text))==text
body={'model':'strata','messages':[{'role':'user','content':'Reply with two short sentences about the sky.'}],'thinking':{'type':'disabled'},'max_tokens':3,'temperature':0}
prepared=codec.prepare_chat(body,tok.recipe,4096)
assert list(prepared['input_ids'])==[0,128803,19905,418,1234,3107,15174,943,270,12709,16,128804,128822]
dto=codec._dto
context=dict(request_id='isolated-cpu',runtime_epoch=1,bundle_id='a'*64,asset_revision=dto.REVISION,model_family='deepseek41',tokenizer_identity=dto.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)
common=dict(schema='strata-generation/v1',request_id=context['request_id'],runtime_epoch=1)
events=[dict(common,kind='begin',**{k:v for k,v in context.items()if k not in('request_id','runtime_epoch')}),dict(common,kind='token_batch',sequence=0,origin='native-generated',ids=[4482,1]),dict(common,kind='finish',sequence=1,generated_count=2,finish='stop',ids_sha256=hashlib.sha256(struct.pack('<II',4482,1)).hexdigest())]
session=codec.CodecSession(context,prepared,tok.recipe)
for event in events:session.feed(json.dumps(event))
decoded=session.end_of_stream();assert decoded['success']and decoded['first_eos_index']==1 and decoded['recipe_input_ids']==(4482,)
bad=dto.GenerationDTO(context);bad.feed(json.dumps(events[0]));bad.feed(json.dumps(events[1]));mutant=dict(events[-1],ids_sha256='0'*64)
try:bad.feed(json.dumps(mutant))
except ValueError:pass
else:raise AssertionError('mutant raw ID hash accepted')
for module in ('serve.frontend','serve.mcp','serve.runconfig','serve.logit_bias','serve.winjob','serve.structured','serve.responses','serve.images','serve.telemetry','serve.prometheus','serve.session_save_retry','serve.replicas','serve.keepawake','serve.cpu_affinity','serve.cache_drop','strata_tokenizer','gguf_reader','jinja2','markupsafe','psutil','PIL.Image','regex'):
 importlib.import_module(module)
from serve.structured import jsonschema_modules
assert jsonschema_modules()is None
from serve.frontend import ChatTemplate
template=ChatTemplate(base/'serve/chat_template.jinja')
assert template.source
for relative in ('serve/web/index.html','serve/web/monitor.html'):
 assert (base/relative).stat().st_size>0
hook.validate_options({'seed':0,'top_k':0,'min_p':0})
for n,v in [('temperature',True),('top_k',-1),('seed',True)]:
 try:hook.validate_options({n:v})
 except ValueError:pass
 else:raise AssertionError('invalid option accepted')
for context in (16,4096,524288):
 cfg=json.loads((root/'config.json').read_text());cfg['context']=context
 args=hook.native_args(cfg);assert args[args.index('--context')+1]==str(context)
for fraction in (0,.5,1):
 cfg=json.loads((root/'config.json').read_text());cfg['auto_cache_fraction']=fraction
 args=hook.native_args(cfg);assert args[args.index('--auto-cache-fraction')+1]==str(fraction)
# Family install runs the actual hook but no Engine/Service instance/listener.
cfg=json.loads((root/'config.json').read_text());assert hook.install(server,cfg)
assert server.default_model_name({'model_name':'custom-alias'})=='custom-alias'
assert hook.install(server,{'family':'huihui'})is False
mods=[];allowed=(root.resolve(),pathlib.Path(sys.base_prefix).resolve())
for name,m in sorted(sys.modules.items()):
 path=getattr(m,'__file__',None)
 if not path or path.startswith('<'):continue
 p=pathlib.Path(path).resolve()
 assert any(p.is_relative_to(a)for a in allowed),(name,str(p))
 if 'site-packages'in p.parts:assert p.is_relative_to((root/'venv').resolve()),(name,str(p))
 mods.append({'module':name,'path':str(p)})
# Loaded native modules are observed, not just archive import-table guesses.
k=ctypes.WinDLL('kernel32',use_last_error=True);ps=ctypes.WinDLL('psapi',use_last_error=True)
k.GetCurrentProcess.restype=ctypes.c_void_p;handle=k.GetCurrentProcess();array=(ctypes.c_void_p*4096)();needed=ctypes.c_ulong()
ps.EnumProcessModules.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p]
assert ps.EnumProcessModules(handle,array,ctypes.sizeof(array),ctypes.byref(needed))
ps.GetModuleFileNameExW.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong]
native=[]
for h in list(array)[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
 buf=ctypes.create_unicode_buffer(32768)
 if ps.GetModuleFileNameExW(handle,h,buf,len(buf)):
  p=pathlib.Path(buf.value)
  if any(x in p.name.lower()for x in ('opencv','deepseek','concrt','msvcp')):
   assert p.resolve().is_relative_to((root/'venv').resolve())or p.resolve().is_relative_to(pathlib.Path(os.environ['SystemRoot']).resolve()),str(p)
   native.append({'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
assert sum('opencv'in x['path'].lower()for x in native)==3
out={'modules':mods,'native_modules':native,'base_prefix':sys.base_prefix,'prefix':sys.prefix,'version':sys.version,'isolated_environment':{'ignore_environment':sys.flags.ignore_environment,'no_user_site':sys.flags.no_user_site},'raw_prompt_ids':list(prepared['input_ids']),'codec_original_ids':list(decoded['raw']['original_token_ids']),'codec_recipe_ids':list(decoded['recipe_input_ids']),'hash_mutant_rejected':True,'structured_optional_installed':False,'native_or_listener_started':False,'context_cases':[16,4096,524288]}
(root/'probe-result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
'''

def stage():
 """Explicit acquisition and isolated CPU qualification under B29 only."""
 BUILD.mkdir(exist_ok=True);out=BUILD/'runtime-stage-r3'
 if out.exists():raise ValueError('stage already exists; preserve prior attempt and select a new fixed implementation revision')
 out.mkdir();before=protected(DATA/'profiles');catalog=record(DATA/'model_catalog.py')
 facts=load(BUILD/'runtime-distributions-r2.json');binary=load(BUILD/'runtime-python-binary-facts.json');base=load(BUILD/'import-facts-r2.json')
 own8=[EXT/'control/providers/__init__.py',EXT/'control/providers/deepseek41.py',DATA/'model_catalog.py',*(EXT/'tests/providers'/x for x in ('contract.json','test_provider.py','build_verify.py','runtime_stage.py','test_runtime_stage.py'))]
 sources=[record(p)for p in own8]+[record(BUILD/x)for x in ('profile-addendum-r5.md','runtime-distributions-r2.json','runtime-python-binary-facts.json','import-facts-r2.json')]
 capture_sources=[copy_checked(row,out/'capture-source'/str(i)/pathlib.Path(row['path']).name)for i,row in enumerate(sources)]
 write(out/'capture-source-map.json',dict(own8_count=len(own8),records=capture_sources))
 for row in binary['base_files']:check_record(row)
 if BASE_PYTHON.resolve()!=pathlib.Path(binary['python']['base_executable']).resolve():raise ValueError('base Python identity')
 for row in facts['distributions']:check_record(row['metadata_raw_file'])
 capacity={'free_before':shutil.disk_usage(out).free,'new_wheel_bytes':facts['new_wheel_bytes'],'stage_engineering_estimate':268435456,'already_held_not_deducted':True,'normal_budget_or_cap':False};write(out/'capacity-before.json',capacity)
 wheelhouse=out/'wheelhouse';wheelhouse.mkdir();wheels=[]
 for row in facts['distributions']:
  w=row['wheel'];name=wheel_name(w['filename']);target=wheelhouse/name
  req=urllib.request.Request(w['url'],headers={'User-Agent':'Strata-T29-fixed-runtime-wheel'})
  if not w['url'].startswith('https://files.pythonhosted.org/'):raise ValueError('fixed wheel origin')
  cached=BUILD/'runtime-stage-r1/wheelhouse'/name
  if cached.is_file():
   check_wheel(cached,w['size'],w['digests']['sha256']);raw=cached.read_bytes()
  else:
   with urllib.request.urlopen(req,timeout=60)as response:
    raw=response.read(w['size']+1)
  if len(raw)!=w['size']or hashlib.sha256(raw).hexdigest()!=w['digests']['sha256']:raise ValueError('fixed wheel transfer mismatch')
  target.write_bytes(raw);wheels.append(record(target))
  write(out/'acquisition.json',dict(wheels=wheels,bytes=sum(x['bytes']for x in wheels),full_source_weights_copied=False))
 recipe=check_record(binary['recipe_wheel']);wheels.append(record(recipe))
 lock=out/'requirements.lock';lock.write_text('\n'.join(lock_line(x)for x in wheels)+'\n',encoding='utf-8')
 clean=dict(os.environ);clean.pop('PYTHONHOME',None);clean.pop('PYTHONPATH',None)
 call([BASE_PYTHON,'-E','-s','-B','-X','utf8','-m','venv',out/'venv'],out,'create-venv',clean)
 python=out/'venv/Scripts/python.exe'
 call([python,'-E','-s','-B','-X','utf8','-m','pip','install','--no-index','--no-deps','--require-hashes','-r',lock],out,'install-wheels',clean)
 copies=[]
 for row in base['records']:
  if row['relative']=='serve/server.py':continue
  copies.append(copy_checked(row,destination(out/'base',row['relative'])))
 prepared=ROOT/'build-deepseek-t28/normal/normal-next2/bundle/server/serve/server.py'
 copies.append(copy_checked(record(prepared),out/'native/server/serve/server.py'))
 for relative in ('control/deepseek_serve.py','control/generation_frames.py','models/deepseek41/server_hooks.py','models/deepseek41/serve_codec.py'):
  copies.append(copy_checked(record(EXT/relative),destination(out/'Strata-extensions',relative)))
 tokenizer=ROOT/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json'
 copies.append(copy_checked(record(tokenizer),out/'tokenizer.json'))
 write(out/'source-map.json',dict(copies=copies,input_sources=sources,base_python_files=binary['base_files']))
 # The native path is a declaration for --help/config only; it is never launched.
 config=dict(family='deepseek41',arch='deepseek41',model_name='deepseek-v4.1-flash-1017-ud-q4_k_xl',exe=str(out/'native/Strata-deepseek.exe'),upstream_root=str(out/'base'),tokenizer=str(out/'tokenizer.json'),primary_pci='0000:07:00.0',context=4096,bundle_id='a'*64,runtime_epoch=1,artifact_root='declaration-only-original-root',native_paths=[],cache_budget=dict(device_cache_payload_bytes='auto',ram_cache_payload_bytes='auto'),auto_cache_fraction=.5,auto_row_fraction=1/64,args=[])
 write(out/'config.json',config);(out/'probe.py').write_text(PROBE,encoding='utf-8');(out/'empty-cwd').mkdir()
 # Deliberately poisoned paths must be ignored by -E, not repaired by fallback.
 clean['PYTHONPATH']='C:/nonexistent-T29-poison';clean['PYTHONHOME']='C:/nonexistent-T29-poison'
 call([python,'-E','-s','-B','-X','utf8',out/'Strata-extensions/control/deepseek_serve.py','--config',out/'config.json','--help'],out,'actual-entry-help',clean,out/'empty-cwd')
 call([python,'-E','-s','-B','-X','utf8',out/'probe.py',out],out,'isolated-probe',clean,out/'empty-cwd')
 call([python,'-E','-s','-B','-m','pip','check'],out,'pip-check',clean)
 probe=load(out/'probe-result.json');assert probe['isolated_environment']==dict(ignore_environment=1,no_user_site=1)
 for row in sources:check_record(row)
 for row in copies:check_record(row['source']);check_record(row['copy'])
 for row in wheels:check_record(row)
 check_record(catalog);assert protected(DATA/'profiles')==before
 generated=[record(p)for p in sorted(out.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
 proof=dict(schema='strata-t29-isolated-runtime-cpu/v1',source_map=record(out/'source-map.json'),capture_source_map=record(out/'capture-source-map.json'),inputs=sources,wheels=wheels,lock=record(lock),protected_profiles=before,profile_bytes_before_after=True,catalog_before_after=catalog,probe=record(out/'probe-result.json'),actual_entry_help=record(out/'actual-entry-help.stdout.txt'),generated_files=len(generated),generated_bytes=sum(x['bytes']for x in generated),generated_manifest=generated,runtime_python=record(python),base_python_files=binary['base_files'],GPU_runs=0,native_process_started=False,HTTP_listener_started=False,public_profile_saved=False,installed_deployment=False,T28_normal_qualification=False,whole_T29_complete=False,scope='isolated CPU dependency/base/Recipe/entry closure only')
 write(out/'verification.json',proof);print(json.dumps(record(out/'verification.json')))
 return proof

def replay(stage_dir):
 """Read back immutable captured files; no installer, native, or listener."""
 out=pathlib.Path(stage_dir);proof=load(out/'verification.json')
 for row in proof['generated_manifest']+proof['base_python_files']+proof['wheels']:check_record(row)
 check_record(proof['capture_source_map']);check_record(proof['source_map']);check_record(proof['probe'])
 for row in load(proof['capture_source_map']['path'])['records']:check_record(row['copy'])
 if load(proof['capture_source_map']['path'])['own8_count']!=8:raise ValueError('source scope count')
 result=load(proof['probe']['path'])
 if result['isolated_environment']!={'ignore_environment':1,'no_user_site':1}or result['native_or_listener_started']is not False:raise ValueError('isolated CPU scope')
 if proof['GPU_runs']!=0 or proof['installed_deployment']is not False or proof['public_profile_saved']is not False:raise ValueError('scope mismatch')
 return record(out/'verification.json')

if __name__=='__main__':
 argparse.ArgumentParser(description=__doc__).parse_args();stage()


def prepare_candidate_clients(output):
 """Relocate existing normal clients to this explicit candidate's real DATA owner."""
 output=pathlib.Path(output);home=DATA.parent;pi=home/'Pi';harness=home/'Harness';private=output/'Pi';ph=output/'Harness';copied=[]
 for directory in (private,ph,output/'Strata-extensions/clients'):directory.mkdir(parents=True,exist_ok=True)
 def client(relative,changes=(),transform=None):
  source=home/relative;target=output/relative;text=source.read_text(encoding='utf-8')
  for old,new in changes:
   if old not in text:raise ValueError('candidate client source contact changed: '+relative)
   text=text.replace(old,new)
  if transform:text=transform(text)
  target.write_bytes(text.replace('\r\n','\n').replace('\n','\r\n').encode('utf-8'));copied.append(dict(source=record(source),copy=record(target)))
 def imports(text,root,local):
  return re.sub(r"from '(\.\.?/[^']+)'",lambda m:"from '"+((private if m[1]in local else root)/m[1]).resolve().as_uri()+"'",text)
 source=home/'Strata-extensions/clients/runtime_binding.py';copied.append(copy_checked(record(source),output/'Strata-extensions/clients/runtime_binding.py'))
 for relative in ('Pi/runtime_check.py','Pi/catalog_bridge.py','Pi/native_arguments.py'):client(relative)
 client('Pi/policy.mjs',[("export const ROOT = path.dirname(fileURLToPath(import.meta.url));","export const ROOT = "+json.dumps(str(pi))+";"),("path.join(ROOT, 'catalog_bridge.py')",json.dumps(str(private/'catalog_bridge.py'))),("path.join(ROOT, 'runtime_check.py')",json.dumps(str(private/'runtime_check.py')))],lambda s:imports(s,pi,()))
 def launcher(text):
  text=imports(text,pi,('./policy.mjs','./session-history.mjs'))
  text=text.replace("import('@earendil-works/pi-coding-agent')","import("+json.dumps((pi/'node_modules/@earendil-works/pi-coding-agent/dist/index.js').as_uri())+")")
  return text.replace("['--extension',path.join(ROOT,file)]","['--extension',file==='guard-extension.mjs'?"+json.dumps(str(private/'guard-extension.mjs'))+":path.join(ROOT,file)]")
 client('Pi/launch.mjs',transform=launcher)
 client('Pi/guard-extension.mjs',transform=lambda s:imports(s,pi,('./policy.mjs',)))
 agent=private/'agent';agent.mkdir(exist_ok=True)
 for name in ('models.json','settings.json'):
  source=pi/'agent'/name
  if source.is_file():
   target=agent/name;write(target,load(source));copied.append(dict(source=record(source),copy=record(target),normalization='UTF8 no BOM; same parsed JSON, original unchanged'))
 def history(text):
  text=text.replace("export const AGENT_DIRECTORY=path.join(ROOT,'agent');","export const AGENT_DIRECTORY="+json.dumps(str(agent))+";")
  text=imports(text,pi,('./policy.mjs',))
  return text.replace("from '@earendil-works/pi-coding-agent'","from '"+(pi/'node_modules/@earendil-works/pi-coding-agent/dist/index.js').as_uri()+"'")
 client('Pi/session-history.mjs',transform=history)
 action=load(DATA/'pi-action.json');action['argv'][1]=str(private/'launch.mjs');write(output/'Strata-data/pi-action.json',action);copied.append(dict(source=record(DATA/'pi-action.json'),copy=record(output/'Strata-data/pi-action.json')))
 client('Harness/runtime_probe.py',[("data=Path(__file__).resolve().parent.parent/'Strata-data'","data=Path("+repr(str(output/'Strata-data'))+")")])
 client('Harness/runtime_binding.py',[("ROOT = Path(__file__).resolve().parent","ROOT = Path("+repr(str(harness))+")"),("ROOT.parent/'Strata-data'","Path("+repr(str(output/'Strata-data'))+")"),("str(ROOT / 'runtime_guard.mjs')","str(Path("+repr(str(ph/'runtime_guard.mjs'))+"))")])
 client('Harness/runtime_guard.mjs',[("from '@deepseek-ai/dsh-llm'","from '"+(harness/'node_modules/@deepseek-ai/dsh-llm/lib/index.js').as_uri()+"'"),("from './python-launcher.mjs'","from '"+(harness/'python-launcher.mjs').as_uri()+"'")])
 client('Harness/launch.py',[("ROOT = Path(__file__).resolve().parent","ROOT = Path("+repr(str(harness))+")"),("sys.path.insert(0, str(ROOT))","sys.path.insert(0, str(ROOT))\nsys.path.insert(0, "+repr(str(ph))+")")])
 return dict(source_map=copied,Pi_action=record(output/'Strata-data/pi-action.json'),Harness=record(ph/'launch.py'),Harness_python_environment=dict(__PYVENV_LAUNCHER__=str(home/'Strata/.venv/Scripts/python.exe')),ordinary_options_unchanged=True)

def prepare_candidate_context(candidate_path, output):
 """Existing ordinary CLI/manager, with private profile/official record paths.

 No source/profile registration or default is published. The new package already
 passed the ordinary assembly/identity checks; numeric review is not a start gate.
 """
 import ast
 candidate_path=pathlib.Path(candidate_path).resolve();candidate=load(candidate_path)
 if candidate.get('schema')!='strata-t46-execution-candidate-CPU/v1'or candidate.get('public_profiles_updated')is not False:raise ValueError('candidate normal context scope')
 check_record(candidate['package_manifest']);manifest=load(candidate['package_manifest']['path'])
 package=pathlib.Path(candidate['package_root']).resolve()
 if manifest['id']!=package.name or pathlib.Path(candidate['package_manifest']['path']).resolve()!=package/'evidence/package-manifest.json':raise ValueError('candidate context package binding')
 output=pathlib.Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
 data=output/'Strata-data';ext=output/'Strata-extensions';repo=output/'Strata'
 for path in (data/'profiles',data/'records',data/'logs',repo/'tools',repo/'serve',repo/'.strata-mcp'):path.mkdir(parents=True,exist_ok=True)
 copied=[];pending=['strata_cli','manage_runtime','official_runtime','startup_progress','server_bootstrap','runtime_temp_probe','temp_probe_child','model_catalog','profile_defaults','huihui_authority']
 seen=set()
 while pending:
  name=pending.pop()
  if name in seen:continue
  seen.add(name);source=DATA/(name+'.py')
  if name=='strata_cli':source=EXT/'control/strata_cli.py'
  if not source.is_file():raise ValueError('candidate ordinary module missing: '+name)
  target=data/source.name
  if name=='strata_cli':
   text=source.read_text(encoding='utf8')
   before="DATA_ROOT=pathlib.Path(r'C:/Develop/AI/Strata-data')"
   if before not in text:raise ValueError('candidate CLI original data domain')
   target.write_bytes(text.replace(before,'DATA_ROOT=pathlib.Path(__file__).resolve().parent').replace('\n','\r\n').encode('utf8'))
   copied.append(dict(source=record(source),copy=record(target),delta='candidate DATA root only'))
  else:copied.append(copy_checked(record(source),target))
  tree=ast.parse(target.read_text(encoding='utf8'))
  for node in ast.walk(tree):
   names=[alias.name.split('.')[0]for alias in node.names]if isinstance(node,ast.Import)else([node.module.split('.')[0]]if isinstance(node,ast.ImportFrom)and node.module else [])
   for dependency in names:
    if dependency not in seen and(DATA/(dependency+'.py')).is_file():pending.append(dependency)
 for relative in ('control/deepseek_launch.py','control/deepseek_bootstrap.py','control/contracts.py','control/providers/__init__.py','control/providers/deepseek41.py'):
  copied.append(copy_checked(record(EXT/relative),ext/relative))
 for relative in ('setup.py','tools/strata_mcp.py','serve/server.py'):
  copied.append(copy_checked(record(DATA.parent/'Strata'/relative),repo/relative))
 # A standard empty venv satisfies official MCP's executable discovery. The
 # selected family bootstrap still uses the already assembled package venv.
 call([BASE_PYTHON,'-E','-s','-B','-X','utf8','-m','venv','--without-pip',repo/'.venv'],output,'official-context-venv',dict(os.environ))
 profiles=[]
 for item in candidate['profiles']:
  check_record(item['candidate']);cfg=load(item['candidate']['path'])
  if cfg['runtime_package']!={'id':manifest['id'],'manifest':str(package/'evidence/package-manifest.json')}:raise ValueError('candidate context profile root')
  if pathlib.Path(cfg['exe']).resolve()!=package/'native/Strata-deepseek.exe':raise ValueError('candidate context actual image')
  cfg['log']=str(data/'logs'/pathlib.Path(cfg['log']).name)
  target=data/'profiles'/pathlib.Path(item['candidate']['path']).name;write(target,cfg);profiles.append(record(target))
 result=dict(candidate=record(candidate_path),package_manifest=candidate['package_manifest'],package_id=manifest['id'],data_root=str(data),official_root=str(repo),source_map=copied,profiles=profiles,CLI=record(data/'strata_cli.py'),python=str(package/'venv/Scripts/python.exe'),public_profiles_updated=False,ordinary_manager_reused=True,native_started=False,normal_numeric_qualified=False)
 result['clients']=prepare_candidate_clients(output)
 write(output/'candidate-context.json',result)
 return result
