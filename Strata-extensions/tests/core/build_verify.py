"""T20 local build/replay. No GPU work unless explicit execute is selected."""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t20';SDK=Path('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel')
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def environment():
 s=importlib.util.spec_from_file_location('t20_existing_toolchain',EXT/'tests/cache/build_verify.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.BUILD=BUILD;return m.environment()
def run(cmd,env):return subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600)
def build():
 tools,env=environment();out=BUILD/'cmake-dev';cmd=[tools['cmake'],'--fresh','-S',HERE,'-B',out,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}',f'-DCMAKE_PREFIX_PATH={SDK.as_posix()}','-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201',f'-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}']
 for i,c in enumerate([cmd,[tools['cmake'],'--build',out,'--verbose']]):
  r=run(c,env);(BUILD/f'dev-build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise RuntimeError('build failed; original log saved')
 bundle=out/'bundle'
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll']:shutil.copy2(SDK/'bin'/name,bundle/name)
 env['PATH']=os.pathsep.join([str(bundle),str(Path(os.environ['SystemRoot'])/'System32'),os.environ['SystemRoot']])
 r=run([bundle/'t20-core.exe','--host'],env);(BUILD/'dev-host.stdout').write_text(r.stdout,encoding='utf-8');(BUILD/'dev-host.stderr').write_text(r.stderr,encoding='utf-8')
 if r.returncode or r.stderr:raise RuntimeError('host fixture failed; original log saved')
 x=json.loads(r.stdout)
 if x['GPU_used'] is not False or x['full_source_qualified'] is not False:raise ValueError('host scope')
 compat=run([bundle/'t20-lease-compat.exe'],env)
 (BUILD/'dev-lease-compat.stdout').write_text(compat.stdout,encoding='utf-8');(BUILD/'dev-lease-compat.stderr').write_text(compat.stderr,encoding='utf-8')
 if compat.returncode or compat.stderr:raise RuntimeError('affected existing lease host fixture failed')
 result=json.loads(compat.stdout)
 if result['assertions']!=135 or result['metadata_bytes']!=1472 or result['hardware_completion_claim'] is not False:raise ValueError('lease compatibility scope/count')
 print(dict(core=x,affected_lease=result))

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def prepare_owner():
 import numpy as np
 oracle=module('t20_independent_projection',EXT/'tests/quant/q_reference.py');geometry=module('t20_geometry',HERE/'reference.py')
 # Full receipt validator binds current identity/header/span; it does not hash
 # all model bytes a second time. Candidate GPU/native output is never imported.
 acquire=module('t20_full_source',EXT/'native/artifact/full_acquire.py')
 receipt_path=EXT/'tests/artifact/full-model-receipt.json'
 receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
 inventory=json.loads((EXT/'tests/artifact/header-inventory.json').read_text(encoding='utf-8'))
 data=BUILD/'owner-input';q=BUILD/'owner-q';data.mkdir(exist_ok=True);q.mkdir(exist_ok=True)
 shutil.copy2(ROOT/'build-deepseek-t10/sources.tsv',data/'sources.tsv');shutil.copy2(ROOT/'build-deepseek-t10/nine-prefixes.tsv',data/'prefixes.tsv')
 files={x['index']:x for x in receipt['files']};tensors={t['name']:(h,t) for h in inventory['shards'] for t in h['tensors']}
 manifest={'schema':'strata-t20-owner-q/v1','full_receipt_sha256':sha(receipt_path),'jobs':[],'rows':[],'inputs':[],'GPU_used':False,'scope':'new live owner/full-K rowtile and lazy borrowed row; full sequence not qualified'}
 jobs=[]
 for name,matrix in [('blk.0.ffn_gate_exps.weight',38),('blk.0.ffn_up_exps.weight',38),('blk.0.ffn_down_exps.weight',38),('blk.0.ffn_gate_inp.weight',0),('blk.0.attn_kv.weight',0)]:
  h,t=tensors[name];k,n=t['dims_ggml'][:2];offset=t['absolute_offset']+matrix*n*t['row_bytes'];count=n*t['row_bytes'];f=files[h['index']];path=Path(f['path']);before=path.stat()
  with path.open('rb') as stream:stream.seek(offset);raw=stream.read(count)
  after=path.stat()
  if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or len(raw)!=count:raise ValueError('bounded original source changed/short')
  weights=oracle.decode(t['type_id'],raw).reshape(n,k)
  tiles=geometry.row_tiles(n,t['row_bytes'],2097152,256)
  requested=operations=0
  for first,rows in tiles:
   windows=geometry.bounded_source_windows(offset+first*t['row_bytes'],rows*t['row_bytes'],4096);requested+=sum(w[2] for w in windows);operations+=len(windows)
  for batch in [3,19]:
   for family in [0,1]:
    jid='p'+str(len(jobs));x=((np.arange(batch*k,dtype=np.int64).reshape(batch,k)*(17+family*6)+family*3)%257-128).astype(np.float32)/np.float32(8192)
    x.tofile(data/(jid+'-x.bin'));expected=oracle.ordered(weights,x);expected.tofile(q/(jid+'.bin'))
    jobs.append('\t'.join(map(str,[jid,name,matrix,batch,jid+'-x.bin'])))
    manifest['jobs'].append(dict(id=jid,tensor=name,matrix=matrix,batch=batch,k=k,rows=n,type=t['type_id'],source_index=h['index'],source_path=f['path'],source_size=f['bytes'],source_sha256=f['sha256'],source_current_identity=dict(size=before.st_size,mtime_ns=before.st_mtime_ns,file_id=before.st_ino),offset=offset,bytes=count,raw_sha256=hashlib.sha256(raw).hexdigest(),input_sha256=sha(data/(jid+'-x.bin')),expected_sha256=sha(q/(jid+'.bin')),expected_bytes=expected.nbytes,cold=[count,requested,count,operations,0,0],hot=[0,0,0,0,0,0],row_tiles=tiles))
 (data/'owner-jobs.tsv').write_text('\n'.join(jobs)+'\n',encoding='utf-8')
 # Last row of every head: arbitrary unregistered rows, including >4GiB and
 # actual source8 EOF. Read only each 264-byte physical native row.
 h,t=tensors['per_layer_token_embd.weight'];f=files[h['index']]

 arrays=inventory['shards'][0]['metadata_arrays'];offsets=arrays['deepseek41.ple.head_offsets']['values'];sizes=arrays['deepseek41.ple.head_vocab_sizes']['values'];rowvalues=[];requested=received=0
 with Path(f['path']).open('rb') as stream:
  for head in range(24):
   index=24+head;row=sizes[index]-1;globalrow=offsets[index]+row;absolute=t['absolute_offset']+globalrow*264
   stream.seek(absolute);raw=stream.read(264)
   if len(raw)!=264:raise ValueError('real row short')
   decoded=oracle.decode(43,raw);bits=decoded.view(np.uint32);rounded=((bits+np.uint32(0x7fff)+((bits>>16)&1))>>16).astype(np.uint16);bf=(rounded.astype(np.uint32)<<16).view(np.float32);rowvalues.append(bf)
   windows=geometry.bounded_source_windows(absolute,264,4096);requested+=sum(w[2] for w in windows)
   actual=sum(min(w[2],f['bytes']-(w[0]//4096*4096)) for w in windows);received+=actual
   manifest['rows'].append(dict(layer=14,head=head,row=row,global_row=globalrow,offset=absolute,bytes=264,raw_sha256=hashlib.sha256(raw).hexdigest(),requested=sum(w[2] for w in windows),received=actual))
 expected=np.concatenate(rowvalues).astype('<f4');expected.tofile(q/'rows.bin')
 manifest['row_expected_sha256']=sha(q/'rows.bin');manifest['row_expected_bytes']=expected.nbytes
 manifest['row_counters']=[[6336,requested,6336,24,0,24*4],[0,0,0,0,0,24*4],[0,0,6336,0,0,24*4]]
 manifest['explicit_allocation']=[880640,4194816,8448]
 manifest['source_before_G']=[dict(path=x['path'],size=Path(x['path']).stat().st_size,mtime_ns=Path(x['path']).stat().st_mtime_ns,file_id=Path(x['path']).stat().st_ino,sha256=x['sha256']) for x in receipt['files']]
 inputs=[data/'sources.tsv',data/'prefixes.tsv',data/'owner-jobs.tsv']+list(data.glob('*-x.bin'))
 manifest['inputs']=[dict(path=str(x),bytes=x.stat().st_size,sha256=sha(x)) for x in inputs]
 manifest['projection_ready']=True;save(q/'manifest.json',manifest)
 print({'projection_jobs':len(jobs),'Q_sha256':sha(q/'manifest.json'),'row_values':expected.size,'GPU_used':False},flush=True)



def prepare_hot():
 import numpy as np
 q=BUILD/'owner-q';m=json.loads((q/'manifest.json').read_text(encoding='utf-8'));m['hot_only']=True
 geometry=module('hot_geometry',HERE/'reference.py')
 for j in m['jobs']:
  first,count=j['row_tiles'][-1];active=geometry.batch_waves(j['batch'])[0]
  full=np.fromfile(q/(j['id']+'.bin'),dtype='<f4').reshape(j['batch'],j['rows']);hot=full[:active,first:first+count].copy();hot.tofile(q/(j['id']+'-hot.bin'))
  j.update(hot_first=first,hot_rows=count,hot_batch=active,hot_expected_bytes=hot.nbytes,hot_expected_sha256=sha(q/(j['id']+'-hot.bin')))
 save(q/'hot-manifest.json',m);print(dict(hot_before_G_sha256=sha(q/'hot-manifest.json'),values=sum(j['hot_expected_bytes']//4 for j in m['jobs']),GPU_used=False))


def prepare_capacity():
 q=BUILD/'owner-q';m=json.loads((q/'hot-manifest.json').read_text(encoding='utf-8'));m['capacity_credit']=True;m['read_credit_bytes']=65536
 geometry=module('capacity_geometry',HERE/'reference.py')
 for j in m['jobs']:
  rowbytes=j['bytes']//j['rows'];absolute=j['offset']+j['hot_first']*rowbytes;size=j['hot_rows']*rowbytes;windows=geometry.bounded_source_windows(absolute,size,65536)
  j['warm']=[size,sum(w[2] for w in windows),size,len(windows),0,0]
 save(q/'capacity-manifest.json',m);print(dict(capacity_Q_before_G=sha(q/'capacity-manifest.json'),jobs=len(m['jobs']),derived_read_credit=65536,GPU_used=False))

def validate_hot(output,m):
 lines=(output/'owner.tsv').read_text(encoding='utf-8').splitlines();observed={}
 for line in lines:
  parts=line.split('\t')
  if parts[0] in observed:raise ValueError('duplicate hot counter')
  observed[parts[0]]=[int(x) for x in parts[1:]]
 names={j['id']+'-hot' for j in m['jobs']}
 if m.get('capacity_credit'):names|={j['id']+'-warm' for j in m['jobs']}
 if set(observed)!=names:raise ValueError('hot coverage')
 for j in m['jobs']:
  if m.get('capacity_credit') and observed[j['id']+'-warm']!=j['warm']:raise ValueError('capacity-bounded warm actual bytes/operations')
  if observed[j['id']+'-hot']!=[0]*6:raise ValueError('hot actual read/H2D/D2H counter')
  path=output/(j['id']+'-hot.bin')
  if path.stat().st_size!=j['hot_expected_bytes'] or sha(path)!=j['hot_expected_sha256']:raise ValueError('actual poisoned hot output bits/bytes')
 return dict(hot_jobs=len(m['jobs']),values=sum(j['hot_expected_bytes']//4 for j in m['jobs']),cold_suite_rerun=False,driver_context_physical_peak=None)


def test_hot_validator(capacity_credit=False):
 import tempfile
 q=BUILD/'owner-q';m=json.loads((q/('capacity-manifest.json' if capacity_credit else 'hot-manifest.json')).read_text());checks=0
 with tempfile.TemporaryDirectory(dir=BUILD,prefix='hot-validator-') as tmp:
  out=Path(tmp);lines=[]
  for j in m['jobs']:
   shutil.copy2(q/(j['id']+'-hot.bin'),out/(j['id']+'-hot.bin'));lines.append(j['id']+'-hot\t0\t0\t0\t0\t0\t0')
   if capacity_credit:lines.append(j['id']+'-warm\t'+'\t'.join(map(str,j['warm'])))
  r=out/'owner.tsv';r.write_text('\n'.join(lines)+'\n');validate_hot(out,m)
  path=out/(m['jobs'][0]['id']+'-hot.bin');raw=path.read_bytes()
  for changed in [raw[:-1],bytes([raw[0]^1])+raw[1:],b'\xff'*len(raw)]:
   path.write_bytes(changed)
   try:validate_hot(out,m)
   except ValueError:checks+=1
   else:raise AssertionError('hot numeric false PASS')
  path.write_bytes(raw)
  for changed in [lines+[lines[0]],[lines[0].replace('\t0','\t1',1)]+lines[1:]]:
   r.write_text('\n'.join(changed)+'\n')
   try:validate_hot(out,m)
   except ValueError:checks+=1
   else:raise AssertionError('hot counter/coverage false PASS')
  if capacity_credit:
   for value in ['0','True']:
    changed=lines.copy();parts=changed[1].split('\t');parts[2]=value;changed[1]='\t'.join(parts);r.write_text('\n'.join(changed)+'\n')
    try:validate_hot(out,m)
    except ValueError:checks+=1
    else:raise AssertionError('warm requested counter false PASS')
 print(dict(hot_validator_positive=1,meaningful_rejections=checks,GPU_used=False))

def validate_owner(output,manifest):
 import numpy as np
 q=BUILD/'owner-q';rows={}
 for line in (output/'owner.tsv').read_text(encoding='utf-8').splitlines():
  parts=line.split('\t')
  if parts[0] in rows:raise ValueError('duplicate receipt counter')
  rows[parts[0]]=parts[1:] if parts[0]=='fair' else [int(v) for v in parts[1:]]
 expected_names={'allocation','control','fair','borrow_cancel'}
 if rows.get('control')!=[8] or rows.get('fair')!=['ERE'] or rows.get('borrow_cancel')!=[3]:raise ValueError('noissue/cancel/borrow/fair actual control coverage')
 values=0
 for job in manifest['jobs']:
  jid=job['id'];expected_names.update([jid,jid+'-hot'])
  for suffix,counts in [('',job['cold']),('-hot',job['hot'])]:
   if rows[jid+suffix]!=counts:raise ValueError('actual I/O delta mismatch '+jid+suffix+' '+str(rows[jid+suffix])+' expected '+str(counts))
  path=output/(jid+'.bin');want=q/(jid+'.bin')
  if path.stat().st_size!=job['expected_bytes'] or sha(path)!=job['expected_sha256']:raise ValueError('exact projection bytes/bits '+jid)
  values+=job['expected_bytes']//4
 for i,counts in enumerate(manifest['row_counters']):
  name='rows-'+str(i);expected_names.add(name)
  if rows[name]!=counts:raise ValueError('lazy row counter mismatch '+name+' '+str(rows[name])+' expected '+str(counts))
  path=output/(name+'.bin')
  if path.stat().st_size!=manifest['row_expected_bytes'] or sha(path)!=manifest['row_expected_sha256']:raise ValueError('borrowed BF16 row mismatch '+name)
  values+=manifest['row_expected_bytes']//4
 path=output/'control-next.bin'
 if path.stat().st_size!=4 or sha(path)!=manifest['control_next_sha256']:raise ValueError('post issued-cancel next actual numeric output')
 values+=1
 path=output/'rows-next.bin'
 if path.stat().st_size!=manifest['row_expected_bytes'] or sha(path)!=manifest['row_expected_sha256']:raise ValueError('post cancellation next row output')
 values+=manifest['row_expected_bytes']//4
 if set(rows)!=expected_names:raise ValueError('counter coverage')
 if rows['allocation'][:3]!=manifest['explicit_allocation']:raise ValueError('explicit simultaneous allocation/lifetime')
 return dict(jobs=len(manifest['jobs']),row_passes=3,values=values,explicit_device_peak=sum(manifest['explicit_allocation']),driver_context_physical_peak=None)


def test_owner_validator():
 import tempfile
 m=json.loads((BUILD/'owner-q/manifest.json').read_text(encoding='utf-8'));q=BUILD/'owner-q'
 with tempfile.TemporaryDirectory(dir=BUILD,prefix='owner-validator-') as tmp:
  out=Path(tmp);lines=[]
  for j in m['jobs']:
   shutil.copy2(q/(j['id']+'.bin'),out/(j['id']+'.bin'))
   lines.extend([j['id']+'\t'+'\t'.join(map(str,j['cold'])),j['id']+'-hot\t'+'\t'.join(map(str,j['hot']))])
  for i,counts in enumerate(m['row_counters']):
   shutil.copy2(q/'rows.bin',out/('rows-'+str(i)+'.bin'));lines.append('rows-'+str(i)+'\t'+'\t'.join(map(str,counts)))
  shutil.copy2(q/'control-next.bin',out/'control-next.bin');shutil.copy2(q/'rows.bin',out/'rows-next.bin');lines.extend(['control\t8','fair\tERE','borrow_cancel\t3']);lines.append('allocation\t'+'\t'.join(map(str,m['explicit_allocation']+[1,1])));receipt=out/'owner.tsv';receipt.write_text('\n'.join(lines)+'\n',encoding='utf-8');validate_owner(out,m)
  rejected=0
  for value in ['0','-1','True','1.0',str(m['jobs'][0]['cold'][0]-1),str(m['jobs'][0]['cold'][0]+1)]:
   wrong=lines.copy();parts=wrong[0].split('\t');parts[1]=value;wrong[0]='\t'.join(parts);receipt.write_text('\n'.join(wrong)+'\n',encoding='utf-8')
   try:validate_owner(out,m)
   except (ValueError,KeyError):rejected+=1
   else:raise AssertionError('observed counter mutation false PASS')
  for mutation in [lines[:-1],lines+[lines[0]],lines[:-1]+['allocation\t0\t0\t0\t1\t1']]:
   receipt.write_text('\n'.join(mutation)+'\n',encoding='utf-8')
   try:validate_owner(out,m)
   except (ValueError,KeyError):rejected+=1
   else:raise AssertionError('coverage/allocation mutation false PASS')
  receipt.write_text('\n'.join(lines)+'\n',encoding='utf-8');path=out/(m['jobs'][0]['id']+'.bin');raw=path.read_bytes();path.write_bytes(raw[:-1])
  try:validate_owner(out,m)
  except ValueError:rejected+=1
  else:raise AssertionError('short output false PASS')
 print(dict(owner_validator_positive=1,meaningful_rejections=rejected,GPU_used=False))

def execute_owner(hot_only=False,capacity_credit=False,full_core=False,branch_core=False):
 data=BUILD/('branch-input' if branch_core else 'full-input' if full_core else 'owner-input');q=BUILD/('branch-q' if branch_core else 'full-q' if full_core else 'owner-q');exe=BUILD/'cmake-dev/bundle/t20-core.exe';bundle=exe.parent
 manifest_path=q/('manifest.json' if branch_core else 'sealed-manifest.json' if full_core else 'capacity-manifest.json' if capacity_credit else 'hot-manifest.json' if hot_only else 'manifest.json');m=json.loads(manifest_path.read_text(encoding='utf-8'))
 for r in m['inputs']+m.get('expected_files',[]):
  if Path(r['path']).stat().st_size!=r['bytes'] or sha(r['path'])!=r['sha256']:raise ValueError('G-before input binding')
 acquire=module('t20_execution_full_source',EXT/'native/artifact/full_acquire.py');source,inventory,fixtures=acquire.load_fixed();acquire.validate_receipt(json.loads((EXT/'tests/artifact/full-model-receipt.json').read_text(encoding='utf-8')),acquire.DESTINATION,source,inventory,fixtures)
 tools,env=environment();env['PATH']=os.pathsep.join([str(bundle),str(Path(os.environ['SystemRoot'])/'System32'),os.environ['SystemRoot']])
 deps=run([tools['ninja'],'-C',BUILD/'cmake-dev','-t','deps'],env)
 if deps.returncode:raise ValueError('consumed dependency inventory')
 dependencies={Path(line.strip()) for line in deps.stdout.splitlines() if line.startswith('    ') and Path(line.strip()).is_file()}
 owned={p for p in dependencies if p.is_relative_to(ROOT)}|{p for p in HERE.glob('*') if p.is_file()}|set((EXT/'models/deepseek41').glob('*.hip'))|set((EXT/'native/cache').glob('*.hip'))|set((EXT/'native/quant').glob('*.hip'))
 current={str(p):sha(p) for p in sorted(owned)}
 external={str(p):sha(p) for p in sorted(dependencies) if not p.is_relative_to(ROOT)}
 toolchain={name:dict(path=str(path),sha256=sha(path)) for name,path in tools.items() if Path(path).is_file()}
 bitcode={str(p):sha(p) for p in (SDK/'lib/llvm/amdgcn/bitcode').glob('*.bc')}
 binding=dict(source=current,external_consumed_dependencies=external,tools=toolchain,device_bitcode=bitcode,EXE=sha(exe),Q=sha(manifest_path),DLL={p.name:sha(p) for p in bundle.glob('*.dll')})
 attempt=1
 prefix='branch-core-attempt-' if branch_core else 'full-core-attempt-' if full_core else 'owner-capacity-attempt-' if capacity_credit else 'owner-hot-attempt-' if hot_only else 'owner-attempt-'
 while (BUILD/(prefix+str(attempt))).exists():attempt+=1
 out=BUILD/(prefix+str(attempt));out.mkdir();save(out/'binding-before.json',binding);(out/'consumed-deps.txt').write_text(deps.stdout,encoding='utf-8')
 snapshot=out/'immutable-source'
 for name in current:
  target=snapshot/Path(name).relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(name,target)
 shutil.copy2(exe,out/'captured-native.exe');shutil.copy2(manifest_path,out/'captured-Q-manifest.json')
 for name in binding['DLL']:shutil.copy2(bundle/name,out/name)
 save(out/'snapshot-binding.json',dict(source_map={name:str(snapshot/Path(name).relative_to(ROOT)) for name in current},native=str(out/'captured-native.exe'),Q=str(out/'captured-Q-manifest.json')))
 # Explicit selected non-secret keys only; no whole environment capture.
 save(out/'runtime-environment.json',{k:env.get(k) for k in ['PATH','TMP','TEMP','HIP_PLATFORM','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES']})
 cmd=[exe,'--branch-core' if branch_core else '--full-core' if full_core else '--capacity-owner' if capacity_credit else '--hot-owner' if hot_only else '--owner',data,out,'0000:07:00.0'];r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=7200 if full_core or branch_core else 600)
 (out/'stdout.txt').write_text(r.stdout,encoding='utf-8');(out/'stderr.txt').write_text(r.stderr,encoding='utf-8');save(out/'exit.json',dict(code=r.returncode))
 if r.returncode or r.stderr:raise RuntimeError('owner attempt failed; original evidence '+str(out))
 result=validate_branches(out,m) if branch_core else validate_full(out,m) if full_core else validate_hot(out,m) if hot_only else validate_owner(out,m)
 if sha(exe)!=binding['EXE'] or sha(manifest_path)!=binding['Q'] or any(sha(p)!=h for p,h in {**current,**external}.items()):raise ValueError('source/native/Q changed during G')
 if any(sha(record['path'])!=record['sha256'] for record in toolchain.values()) or any(sha(path)!=h for path,h in bitcode.items()):raise ValueError('actual tool/bitcode binding changed')
 acquire.validate_receipt(json.loads((EXT/'tests/artifact/full-model-receipt.json').read_text(encoding='utf-8')),acquire.DESTINATION,source,inventory,fixtures)
 loaded=[Path(x) for x in (out/'loaded-modules.txt').read_text(encoding='utf-8').splitlines()]
 actual={}
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']:
  matches=[p for p in loaded if p.name.lower()==name]
  if len(matches)!=1 or matches[0].resolve()!=(bundle/name).resolve() or sha(matches[0])!=binding['DLL'][name]:raise ValueError('actual owned DLL binding')
  actual[name]=dict(path=str(matches[0]),sha256=sha(matches[0]))
 proof=dict(binding=binding,result=result,actual_DLL=actual,outputs=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in out.glob('*.bin')],qualification='T20 actual full40 finite wave1 Core; T26 separate' if full_core else 'new owner subset only; full Core/prefill/state remains pending')
 save(out/'verification.json',proof);print(dict(path=str(out),result=result,proof_sha256=sha(out/'verification.json')),flush=True)


def replay_owner(output):
 output=Path(output);capture=output/'verification.json';capture_sha=sha(capture);proof=json.loads(capture.read_text(encoding='utf-8'));binding=proof['binding']
 if sha(output/'captured-native.exe')!=binding['EXE'] or sha(output/'captured-Q-manifest.json')!=binding['Q']:raise ValueError('captured native/Q binding')
 m=json.loads((output/'captured-Q-manifest.json').read_text(encoding='utf-8'))
 source_map=json.loads((output/'snapshot-binding.json').read_text(encoding='utf-8'))['source_map']
 for path,h in binding['source'].items():
  if sha(source_map[path])!=h:raise ValueError('immutable consumed source changed')
 for r in proof['outputs']:
  path=Path(r['path'])
  if path.stat().st_size!=r['bytes'] or sha(path)!=r['sha256']:raise ValueError('captured output binding')
 for name,h in binding['DLL'].items():
  if sha(output/name)!=h:raise ValueError('captured DLL bytes changed')
 result=validate_branches(output,m) if m.get("schema")=="strata-t20-branch-Q/v1" else validate_full(output,m) if m.get("schema")=="strata-t20-full-Q/v1" else validate_hot(output,m) if m.get("hot_only") else validate_owner(output,m)
 if json.dumps(result,sort_keys=True,allow_nan=False)!=json.dumps(proof['result'],sort_keys=True,allow_nan=False) or sha(capture)!=capture_sha:raise ValueError('capture result changed')
 record=dict(capture_sha256=capture_sha,validator_sha256=sha(Path(__file__)),result=result,independent_GPU_rerun=False,qualification='CPU replay of fixed T20 owner subset; full Core pending')
 save(output/'cpu-revalidation-v1.json',record);print(dict(path=str(output),result=result,CPU_revalidation_sha256=sha(output/'cpu-revalidation-v1.json')))


def prepare_full():
 import numpy as np
 directory=BUILD/'full-input';q=BUILD/'full-q';snapshot=BUILD/'full-independent-source'
 for p in [directory,q,snapshot]:p.mkdir(exist_ok=True)
 relative=['Strata-extensions/tests/numerics/t25/reference.py','Strata-extensions/tests/quant/q_reference.py','Strata-extensions/tests/mhc/reference.py','Strata-extensions/tests/kv/reference.py','Strata-extensions/tests/attention/reference.py','Strata-extensions/tests/ffn/reference.py','Strata-extensions/tests/engram/reference.py','Strata-extensions/tests/core/reference.py','Strata-extensions/tests/artifact/header-inventory.json','build-deepseek-t10/sources.tsv','build-deepseek-t13/nq.json']
 chain=[]
 for name in relative:
  source=ROOT/name;before=sha(source);target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
  if sha(source)!=before or sha(target)!=before:raise ValueError('independent Q source copy changed')
  chain.append(dict(original=str(source),snapshot=str(target),sha256=before))
 save(snapshot/'source-map.json',chain)
 actual=module('t20_independent_full_actual',snapshot/'Strata-extensions/tests/numerics/t25/reference.py');semantic=module('t20_independent_full_semantic',snapshot/'Strata-extensions/tests/core/reference.py');oracle=actual.ActualOracle(snapshot);full=semantic.FullModelOracle(oracle)
 tokens=[3,37,1024];manifest=dict(schema='strata-t20-full-Q/v1',independent_source_chain=chain,tokens=tokens,implicit_BOS=False,context_capacity=3,prefill_token_count=2,append_token_count=1,full_logits=True,outputs=[],frames=[],GPU_used=False,scope='G-before Q for actual full40 Core/finite prefill; not automatically a T26 acceptance')
 for position,token in enumerate(tokens):
  result=full.step(token,position)
  for name in ['embedding','residual','pre','collapsed','normalized','logits']:
   value=np.asarray(result[name],dtype='<f4');path=q/(str(position)+'-'+name+'.bin');value.tofile(path);manifest['outputs'].append(dict(position=position,name=name,shape=list(value.shape),path=str(path),bytes=value.nbytes,sha256=sha(path)))
  for frame in result['frames']:
   stages=[]
   for name,value in frame['stages'].items():
    value=np.asarray(value);path=q/(str(position)+'-layer'+str(frame['layer'])+'-'+name+'.bin');value.tofile(path);stages.append(dict(name=name,shape=list(value.shape),dtype=str(value.dtype),path=str(path),bytes=value.nbytes,sha256=sha(path)))
   manifest['frames'].append(dict(position=position,layer=frame['layer'],stages=stages))
  save(q/'progress.json',dict(completed_tokens=position+1,full40_frames=len(manifest['frames']),GPU_used=False));print(dict(full_Q_position=position,token_id=token,frames=len(manifest['frames'])),flush=True)
 manifest['source_reads']=oracle.reads;manifest['FP64_diagnostics']=oracle.diagnostics
 constants=[dict(name=name,bytes=oracle.tensors[name][1]['bytes']) for name in semantic.full_constant_names()]
 layout=semantic.core_storage_layout(3);manifest['allocation_lifetimes']=layout;manifest['constant_source']=constants;manifest['expected_CoreStorage_owned']=semantic.live_peak(layout)+sum(x['bytes'] for x in constants);manifest['expected_constant_source_bytes']=sum(x['bytes'] for x in constants)
 manifest['expected_requested_output_download_bytes']=3*129280*4;manifest['physical_driver_context_peak']=None
 save(q/'manifest.json',manifest);print(dict(full_Q_sha256=sha(q/'manifest.json'),frames=len(manifest['frames']),source_reads=len(oracle.reads),GPU_used=False),flush=True)


def seal_full():
 import numpy as np
 q=BUILD/'full-q';path=q/'manifest.json';m=json.loads(path.read_text(encoding='utf-8'))
 if m['GPU_used'] is not False or len(m['frames'])!=120:raise ValueError('all three full40 Q frames required')
 routes={str(layer):dict(tokens=0,experts=set()) for layer in range(40)}
 for frame in m['frames']:
  source=next(s for s in frame['stages'] if s['name']=='ffn_router_ids');p=Path(source['path'])
  if sha(p)!=source['sha256']:raise ValueError('independent route expectation changed')
  ids=np.fromfile(p,dtype=np.dtype(source['dtype']))
  if len(ids)!=6 or len(set(map(int,ids)))!=6 or any(not 0<=int(x)<384 for x in ids):raise ValueError('independent selected6 IDs')
  r=routes[str(frame['layer'])];r['tokens']+=1;r['experts'].update(map(int,ids))
 for r in routes.values():
  r['experts']=sorted(r['experts']);r['bits']=[sum(1<<(e%64) for e in r['experts'] if e//64==block) for block in range(6)]
 constant_names={r['name'] for r in m['constant_source']};weights=[r for r in m['source_reads'] if r['tensor']!='per_layer_token_embd.weight' and r['tensor'] not in constant_names];rows=[r for r in m['source_reads'] if r['tensor']=='per_layer_token_embd.weight']
 spans={}
 for r in weights:spans.setdefault(r['source'][4],[]).append((r['absolute_offset'],r['absolute_offset']+r['bytes']))
 unique=0
 for source,ranges in spans.items():
  left=right=None
  for a,b in sorted(ranges):
   if left is None:left,right=a,b
   elif a<=right:right=max(right,b)
   else:unique+=right-left;left,right=a,b
  if left is not None:unique+=right-left
 useful=sum(r['bytes'] for r in weights)
 m['expected_route_union']=routes;m['route_metadata_bytes']=2240;m['expected_Primary_logical_read']=useful;m['expected_Row_logical_read']=sum(r['bytes'] for r in rows);m['expected_weight_union_bytes']=unique;m['expected_weight_reread_bytes']=useful-unique
 m['expected_storage_upload_bytes']=m['expected_constant_source_bytes']+len(m['tokens'])*18
 m['expected_owner_device_bytes']=[4194816,8448];m['expected_total_device_owned']=m['expected_CoreStorage_owned']+sum(m['expected_owner_device_bytes']);m['expected_read_credit_bytes']=65536
 m['precision_contract']='native canonical +0/ascending fullK FP32 product-add; cast/state/logits bits exact; candidate output never used for threshold/expected generation'
 m['full_receipt_sha256']=sha(EXT/'tests/artifact/full-model-receipt.json');m['T10_full_source_proof_sha256']=sha(ROOT/'build-deepseek-t10/bundle-offline-r7/full-source-verification.json');m['full_source_qualification_scope']='T05/T10 original source structural/current identity, not native execution authority'
 records={(r['position'],r['name']):r for r in m['outputs']}
 for r in m['outputs']:
  if Path(r['path']).stat().st_size!=r['bytes'] or sha(r['path'])!=r['sha256']:raise ValueError('full expected output changed before seal')
 m['expected_prefill_bytes']=2*129280*4;m['expected_prefill_sha256']=hashlib.sha256(b''.join(Path(records[(i,'logits')]['path']).read_bytes() for i in range(2))).hexdigest();m['expected_append_sha256']=records[(2,'logits')]['sha256']
 m['inputs']=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in (BUILD/'full-input').glob('*') if p.is_file()]
 m['expected_files']=m['outputs']+[r for frame in m['frames'] for r in frame['stages']]
 save(q/'sealed-manifest.json',m);print(dict(full_Q_seal=sha(q/'sealed-manifest.json'),total_device=m['expected_total_device_owned'],constant=m['expected_constant_source_bytes'],weight_logical=useful,union_bytes=unique,reread_bytes=useful-unique,GPU_used=False))


def expected_full_stats(m):
 constant=m['expected_constant_source_bytes'];total=m['expected_CoreStorage_owned'];owners=m['expected_owner_device_bytes'];tokens=len(m['tokens'])
 e={'core':[total,constant,m['expected_storage_upload_bytes'],m['expected_requested_output_download_bytes']], 'owners':owners+[0,0,0], 'progress':[tokens,40,m['prefill_token_count'],m['append_token_count']], 'total_owned':[m['expected_total_device_owned']], 'source_logical':[m['expected_Primary_logical_read'],m['expected_Row_logical_read'],constant], 'read_credit':[m['expected_read_credit_bytes']], 'route_metadata':[2240], 'state_positions':[tokens]*40, 'compressed_rows':[tokens//2]*3+[tokens], 'key_rows':[tokens//2]*3+[tokens]}
 for layer,r in m['expected_route_union'].items():e['route-'+layer]=[r['tokens']]+r['bits']
 return e

def validate_full_stats(observed,m):
 expected=expected_full_stats(m)
 if set(observed)!=set(expected):raise ValueError('full runtime counter/state coverage')
 for key,value in observed.items():
  if type(value)is not list or any(type(x)is not int or x<0 or x>2**64-1 for x in value) or value!=expected[key]:raise ValueError('full runtime allocation/state/route/source mismatch '+key)

def validate_full(output,m):
 observed={}
 for line in (output/'full-stats.tsv').read_text(encoding='utf-8').splitlines():
  a=line.split('\t')
  if a[0] in observed:raise ValueError('duplicate full runtime row')
  observed[a[0]]=[int(x) for x in a[1:]]
 validate_full_stats(observed,m)
 for name,size,h in [('prefill2-logits.bin',m['expected_prefill_bytes'],m['expected_prefill_sha256']),('append-logits.bin',129280*4,m['expected_append_sha256'])]:
  path=output/name
  if path.stat().st_size!=size or sha(path)!=h:raise ValueError('full canonical native-source logits bits/bytes '+name)
 lines=(output/'full-progress.tsv').read_text(encoding='utf-8').splitlines();base=sum(x[3] for x in m['allocation_lifetimes'])
 if lines!=['created\t'+str(base),'prefill\t2']:raise ValueError('initial all40/workspace lifetime/prefill progression')
 return dict(tokens=3,layers=40,logit_values=3*129280,explicit_simultaneous_device=m['expected_total_device_owned'],weight_logical=m['expected_Primary_logical_read'],weight_source_union=m['expected_weight_union_bytes'],weight_reread=m['expected_weight_reread_bytes'],driver_context_physical_peak=None,full_host_peak=None,qualification='T20 finite wave1 full Core/source-canonical comparison; T26 final qualification separate')

def test_full_stats():
 import copy
 m=dict(tokens=[3,37,1024],prefill_token_count=2,append_token_count=1,expected_constant_source_bytes=10,expected_CoreStorage_owned=110,expected_owner_device_bytes=[20,30],expected_storage_upload_bytes=64,expected_requested_output_download_bytes=12,expected_total_device_owned=160,expected_Primary_logical_read=100,expected_Row_logical_read=24,expected_read_credit_bytes=65536,expected_route_union={str(l):dict(tokens=3,bits=[63,0,0,0,0,0]) for l in range(40)})
 observed=expected_full_stats(m);validate_full_stats(observed,m);count=0
 for key in observed:
  for value in [0,True,-1,float(observed[key][0])]:
   wrong=copy.deepcopy(observed);wrong[key][0]=value
   try:validate_full_stats(wrong,m)
   except ValueError:count+=1
   else:raise AssertionError('full metadata mutation false PASS '+key)
 wrong=copy.deepcopy(observed);wrong.pop('state_positions')
 try:validate_full_stats(wrong,m)
 except ValueError:count+=1
 else:raise AssertionError('missing all40 state false PASS')
 print(dict(full_stats_controlled_positive=1,meaningful_rejections=count,GPU_used=False))


def full_cache_accounting(m):
 # Same fixed two retained device/RAM slots, empty first then first eligible
 # valid slot. This replays source requests, never observed G counters.
 skip={r['name'] for r in m['constant_source']}|{'per_layer_token_embd.weight'}
 slots=[None,None];ram=[None,None];miss=0;logical=0;hits=[];ramhits=[]
 for r in m['source_reads']:
  if r['tensor'] in skip:continue
  key=(r['source'][-1],r['absolute_offset'],r['bytes']);logical+=r['bytes']
  if key in slots:hits.append(r);continue
  slot=slots.index(None) if None in slots else 0
  if key in ram:ramhits.append(r)
  else:
   target=ram.index(None) if None in ram else 0;ram[target]=key;miss+=r['bytes']
  slots[slot]=key
 return dict(projection_request_logical=logical,miss_source_logical=miss,unique_source_union=m['expected_weight_union_bytes'],actual_source_reread=miss-m['expected_weight_union_bytes'],resident_hits=hits,RAM_hits=ramhits,policy='two retained slots; empty first, then first eligible valid; no prefetch in this normal wave1 capture')


def verify_full_capture(output):
 output=Path(output);receipt=output/'native-capture-receipt.json';receipt_sha=sha(receipt);capture=json.loads(receipt.read_text(encoding='utf-8'));binding=capture['binding'];mapping=json.loads((output/'snapshot-binding.json').read_text(encoding='utf-8'))
 if sha(output/'captured-native.exe')!=binding['EXE'] or sha(output/'captured-Q-manifest.json')!=binding['Q']:raise ValueError('full historical EXE/Q binding')
 for original,snapshot in mapping['source_map'].items():
  if sha(snapshot)!=binding['source'][original]:raise ValueError('full historical consumed source')
 for r in capture['outputs']:
  if Path(r['path']).stat().st_size!=r['bytes'] or sha(r['path'])!=r['sha256']:raise ValueError('full saved native output')
 m=json.loads((output/'captured-Q-manifest.json').read_text(encoding='utf-8'))
 for r in m['inputs']+m['expected_files']:
  if Path(r['path']).stat().st_size!=r['bytes'] or sha(r['path'])!=r['sha256']:raise ValueError('full original input/independent Q changed')
 if type(capture['native_exit'])is not dict or set(capture['native_exit'])!={'code'} or type(capture['native_exit']['code'])is not int or capture['native_exit']['code']!=0 or capture['stderr_empty']is not True:raise ValueError('full native failed')
 loaded=[Path(x) for x in (output/'loaded-modules.txt').read_text(encoding='utf-8').splitlines()];actual={}
 for name in ['amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll']:
  found=[p for p in loaded if p.name.lower()==name]
  if len(found)!=1 or found[0].resolve()!=(BUILD/'cmake-dev/bundle'/name).resolve() or sha(found[0])!=binding['DLL'][name] or sha(output/name)!=binding['DLL'][name]:raise ValueError('full actual owned DLL')
  actual[name]=dict(path=str(found[0]),sha256=sha(found[0]))
 trace=full_cache_accounting(m);m['expected_Primary_logical_read']=trace['miss_source_logical'];m['expected_weight_reread_bytes']=trace['actual_source_reread'];result=validate_full(output,m)
 acquire=module('t20_full_cpu_source',EXT/'native/artifact/full_acquire.py');source,inventory,fixtures=acquire.load_fixed();acquire.validate_receipt(json.loads((EXT/'tests/artifact/full-model-receipt.json').read_text(encoding='utf-8')),acquire.DESTINATION,source,inventory,fixtures)
 if sha(receipt)!=receipt_sha or sha(output/'captured-Q-manifest.json')!=binding['Q']:raise ValueError('full capture changed during CPU revalidation')
 trace_path=output/'cache-accounting-r2.json';save(trace_path,trace)
 proof=dict(original_native_capture=dict(path=str(receipt),sha256=receipt_sha,EXE=binding['EXE'],Q=binding['Q'],runner=capture['original_runner_sha256']),current_CPU_validator=dict(path=str(Path(__file__).resolve()),sha256=sha(__file__)),cache_trace=dict(path=str(trace_path),sha256=sha(trace_path)),actual_DLL=actual,result=result,GPU_reexecuted=False,old_all_cold_expectation_preserved=True,qualification='T20 finite wave1 full Core canonical source comparison; T26 separate')
 save(output/'cpu-validation-r2.json',proof);print(dict(result=result,projection_request_logical=trace['projection_request_logical'],resident_hits=len(trace['resident_hits']),RAM_hits=len(trace['RAM_hits']),CPU_validation_sha256=sha(output/'cpu-validation-r2.json'),GPU_reexecuted=False))


def prepare_branches():
 import numpy as np,copy
 old=BUILD/'full-q/sealed-manifest.json';m=json.loads(old.read_text(encoding='utf-8'));data=BUILD/'branch-input';q=BUILD/'branch-q';data.mkdir(exist_ok=True);q.mkdir(exist_ok=True)
 for name in ['sources.tsv','prefixes.tsv']:shutil.copy2(BUILD/'full-input'/name,data/name)
 records={(r['position'],r['name']):r for r in m['outputs']};embedding=np.fromfile(records[0,'embedding']['path'],dtype='<f4');np.tile(embedding,4).astype('<f4').tofile(data/'residual.bin');np.array([1,0,0,0],dtype='<f4').tofile(data/'pre.bin')
 stages={r['name']:r for r in m['frames'][0]['stages']};expected={name:stages[key] for name,key in [('off-residual.bin','block_output'),('on-residual.bin','block_output'),('off-pre.bin','block_next_pre'),('on-pre.bin','block_next_pre'),('audit-block_output.bin','block_output'),('audit-block_next_pre.bin','block_next_pre')]};expected['last-logits.bin']=records[1,'logits']
 filtered=[];position=-1
 for r in m['source_reads']:
  if r['tensor']=='token_embd.weight':position+=1
  if position>=2:break
  if r['tensor']=='output.weight' and position==0:continue
  filtered.append(r)
 trace_m=copy.deepcopy(m);trace_m['source_reads']=filtered;trace=full_cache_accounting(trace_m)
 manifest=dict(schema='strata-t20-branch-Q/v1',original_full_Q=dict(path=str(old),sha256=sha(old)),tokens=[3,37],implicit_BOS=False,default_full_logits=False,audit_range=[0,1],expected=expected,expected_default=[1,129280,2,517120,m['expected_constant_source_bytes']+36,m['expected_CoreStorage_owned'],trace['miss_source_logical']],source_request_trace=trace,expected_files=list(expected.values()),inputs=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in data.glob('*') if p.is_file()],GPU_used=False)
 save(q/'manifest.json',manifest);print(dict(branch_Q_before_G=sha(q/'manifest.json'),default_expectation=manifest['expected_default'],GPU_used=False))


def validate_branches(output,m):
 for name,r in m['expected'].items():
  p=output/name
  if p.stat().st_size!=r['bytes'] or sha(p)!=r['sha256']:raise ValueError('branch actual numeric bits/bytes '+name)
 rows={}
 for line in (output/'branch-stats.tsv').read_text(encoding='utf-8').splitlines():
  parts=line.split('\t')
  if parts[0] in rows:raise ValueError('branch duplicate counter')
  rows[parts[0]]=[int(x) for x in parts[1:]]
 if set(rows)!={'default','failure','audit-off','audit-on'} or rows['default']!=m['expected_default'] or rows['failure']!=[2,2] or rows['audit-off']!=[1,81936,0,0,0]:raise ValueError('branch default/failure/off traffic/state')
 a=rows['audit-on']
 if len(a)!=5 or a[0]!=1 or a[1]!=81936 or a[2]<=0 or a[3:]!=[81936,0]:raise ValueError('branch audit on traffic/allocation')
 return dict(default_last_values=129280,audit_pair_values=2*20484,audit_off_payload_bytes=0,audit_on_payload_bytes=81936,audit_device_allocations=0,failed_reuse_rejections=2,fresh_actual_layer_sequences=2,driver_context_physical_peak=None)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--build',action='store_true');p.add_argument('--prepare-owner',action='store_true');p.add_argument('--execute-owner',action='store_true');p.add_argument('--test-owner-validator',action='store_true');p.add_argument('--verify-owner',type=Path);p.add_argument('--prepare-hot',action='store_true');p.add_argument('--execute-hot',action='store_true');p.add_argument('--test-hot-validator',action='store_true');p.add_argument('--prepare-full',action='store_true');p.add_argument('--prepare-capacity',action='store_true');p.add_argument('--execute-capacity',action='store_true');p.add_argument('--test-capacity-validator',action='store_true');p.add_argument('--seal-full',action='store_true');p.add_argument('--test-full-stats',action='store_true');p.add_argument('--execute-full',action='store_true');p.add_argument('--verify-full',type=Path);p.add_argument('--prepare-branches',action='store_true');p.add_argument('--execute-branches',action='store_true');args=p.parse_args()
 if args.build:build()
 if args.prepare_owner:prepare_owner()
 if args.execute_owner:execute_owner()
 if args.test_owner_validator:test_owner_validator()
 if args.verify_owner:replay_owner(args.verify_owner)
 if args.prepare_hot:prepare_hot()
 if args.execute_hot:execute_owner(True)
 if args.test_hot_validator:test_hot_validator()
 if args.prepare_full:prepare_full()
 if args.prepare_capacity:prepare_capacity()
 if args.execute_capacity:execute_owner(True,True)
 if args.test_capacity_validator:test_hot_validator(True)
 if args.seal_full:seal_full()
 if args.test_full_stats:test_full_stats()
 if args.execute_full:execute_owner(full_core=True)

 if args.verify_full:verify_full_capture(args.verify_full)

 if args.prepare_branches:prepare_branches()
 if args.execute_branches:execute_owner(branch_core=True)
