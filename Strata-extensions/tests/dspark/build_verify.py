"""T37 fixed artifact / host-contract qualification. No GPU or normal launcher."""
import argparse,copy,hashlib,importlib.util,json,math,os,pathlib,re,struct,subprocess,sys,urllib.request
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t37';HOST=BUILD/'host-r3';HERE=pathlib.Path(__file__).parent
sys.path.insert(0,str(HERE))
import reference as Q
import acquire as A

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def sha(path):
 with pathlib.Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(path):return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
def write(path,value):pathlib.Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def need(ok,msg):
 if not ok:raise ValueError(msg)
def record(path):return dict(path=str(path),sha256=sha(path))
def files():
 own=[EXT/'control/dspark_contract.json',EXT/'models/deepseek41/dspark_contract.hpp',EXT/'models/deepseek41/dspark_contract.cpp']+list(HERE.glob('*.py'))+[HERE/'contract_fixture.cpp',HERE/'CMakeLists.txt']
 dep=[EXT/'native/artifact'/x for x in ['native_reader.cpp','native_reader.hpp','gguf.py','quant_layouts.json','full_acquire.py','NOTICE.md']]
 dep+=[EXT/'tests/numerics/reference.py',EXT/'tests/native/build_verify.py']+sorted((ROOT/'include').rglob('*.hpp'))+sorted((ROOT/'include').rglob('*.h'))
 refs=list((BUILD/'reference-source').glob('*'))+[BUILD/'source-notices.json',ROOT/'LICENSE',ROOT/'third_party/ggml/LICENSE']
 return sorted(set(p for p in own+dep+refs if p.is_file()))
def identity():return A.transfer_module().stat_identity(A.DESTINATION/A.FILENAME)
def no_unfinished(root,row):
 final,part,state=A.transfer_module().file_paths(root,row)
 # exclusive_writer(final) creates final+'.part.lock', not final+'.lock'.
 need(not part.exists() and not pathlib.Path(str(part)+'.lock').exists(),'unfinished body/writer lock')
 return final
def capture_record(row):
 # Original Q and native recipe consumed the historical capture wrapper. The
 # present CPU validator is bound separately; it did not build the old EXE.
 return record(HOST/'capture-build_verify.py') if pathlib.Path(row['path'])==pathlib.Path(__file__) else record(row['path'])
def validate_metadata(header):
 need(header==read(BUILD/'reference-source/luce-draft-header.json'),'full artifact header differs from approved metadata')
 contract=read(EXT/'control/dspark_contract.json');counts={str(t):sum(r['type_id']==t for r in header['tensors']) for t in (0,1,8,39)}
 need(counts==contract['native_types'] and len(header['tensors'])==79,'required role/type coverage')
def artifact_check():
 receipt=read(BUILD/'artifact-receipt.json');need(receipt['source']==read(BUILD/'acquisition-before.json')['source'],'acquisition source')
 need(receipt['source']['revision']==A.REVISION and receipt['source']['lfs_sha256']==A.LFS and receipt['source']['bytes']==A.BYTES,'fixed draft identity')
 f=receipt['file'];need(f['sha256']==A.LFS and f['bytes']==A.BYTES and f['same_file_rename'] and receipt['full_LFS_qualified'] is True,'running SHA/rename qualification')
 need(identity()==receipt['current_identity']==f['file_identity'],'current final identity')
 no_unfinished(A.DESTINATION,dict(index=1,filename=A.FILENAME,bytes=A.BYTES,lfs_sha256=A.LFS))
 parser=load('t37_gguf',EXT/'native/artifact/gguf.py')
 with (A.DESTINATION/A.FILENAME).open('rb') as stream:header=parser.parse_header(stream.read(65536),A.BYTES)
 validate_metadata(header)
 return header
def decoded(dtype,raw):
 if dtype==1:return np.frombuffer(raw,dtype='<f2').astype('<f4').tobytes()
 oracle=load('t37_independent_scalar',EXT/'tests/numerics/reference.py');block={0:4,8:34,39:17}[dtype];out=[]
 for i in range(0,len(raw),block):out.extend(oracle.decode_block(dtype,raw[i:i+block]))
 return np.asarray(out,dtype='<f4').tobytes()
def official_confidence(native_raw):
 output=HOST/'official-confidence.raw';headers=read(BUILD/'reference-source/official-draft-headers.json');row=headers[2];t=row['tensors']['mtp.2.confidence_head.proj.weight'];start=row['data_start']+t['data_offsets'][0];count=t['data_offsets'][1]-t['data_offsets'][0]
 need(count==10752 and t['dtype']=='BF16' and t['shape']==[1,5376],'official confidence geometry')
 url='https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/1bae0e1088993b9b82de08f59de5be5a34e42170/'+row['filename']
 if not output.exists():
  request=urllib.request.Request(url+'?t37-confidence=1',headers={'Range':f'bytes={start}-{start+count-1}','Accept-Encoding':'identity'})
  with urllib.request.urlopen(request,timeout=120) as response:
   need(response.status==206 and response.headers['Content-Range']==f"bytes {start}-{start+count-1}/{row['source_bytes']}",'official bounded Content-Range')
   need(response.headers.get('ETag')==row['ranges'][0]['etag'] and response.headers.get('Content-Encoding','identity')=='identity','official fixed transport identity');raw=response.read(count+1);need(len(raw)==count,'official bounded bytes');output.write_bytes(raw)
  write(HOST/'official-confidence-http.json',dict(url=url,revision='1bae0e1088993b9b82de08f59de5be5a34e42170',lfs=row['lfs_sha256'],offset=start,bytes=count,etag=row['ranges'][0]['etag'],sha256=sha(output)))
 transport=read(HOST/'official-confidence-http.json');need(transport['sha256']==sha(output) and transport['offset']==start and transport['bytes']==count,'official fixture binding')
 orig=(np.frombuffer(output.read_bytes(),'<u2').astype('<u4')<<16).view('<f4');converted=orig.astype('<f2').view('<u2');native=np.frombuffer(native_raw,'<u2')
 need(np.array_equal(native,converted),'actual converter BF16-to-F16 bridge')
 widened=native.view('<f2').astype('<f4');different=np.count_nonzero(widened.view('<u4')!=orig.view('<u4'))
 return dict(original=transport,compared_elements=len(orig),native_equals_BF16_to_F16_cast=True,original_value_difference_count=int(different),max_absolute_value_difference=float(np.max(np.abs(widened-orig))),lossless_value_claim=not bool(different))
def prepare():
 HOST.mkdir(parents=True,exist_ok=True);need(not (HOST/'q-manifest.json').exists(),'Q already sealed; use preserved fixed inputs')
 before=identity();header=artifact_check();spans=[];tsv=[];total=0;confidence=None
 with (A.DESTINATION/A.FILENAME).open('rb') as stream:
  for i,t in enumerate(header['tensors']):
   for label,relative in [('first',0)]+([] if t['bytes']==t['row_bytes'] else [('last',t['bytes']-t['row_bytes'])]):
    key=f'r{i:02d}-{label}';offset=t['absolute_offset']+relative;size=t['row_bytes'];stream.seek(offset);raw=stream.read(size);need(len(raw)==size,'short bounded original read');(HOST/(key+'.raw')).write_bytes(raw)
    expected=decoded(t['type_id'],raw);(HOST/(key+'.expected')).write_bytes(expected);total+=size
    spans.append(dict(key=key,tensor=t,offset=offset,bytes=size,raw_sha256=sha(HOST/(key+'.raw')),expected_sha256=sha(HOST/(key+'.expected')),values=len(expected)//4))
    tsv.append('\t'.join(map(str,[key,t['name'],t['type_id'],','.join(map(str,t['dims_ggml'])),t['absolute_offset'],t['bytes'],offset,size])))
    if 'confidence.weight' in t['name']:confidence=raw
 need(confidence is not None,'native confidence role');bridge=official_confidence(confidence);total+=10752
 (HOST/'spans.tsv').write_text('\n'.join(tsv)+'\n',encoding='utf-8')
 controls=[]
 for i,(dtype,raw) in enumerate([(8,struct.pack('<e',0.)+bytes([0,127,128,255]*8)),(8,struct.pack('<e',.5)+bytes([0,127,128,255]*8))]+[(39,bytes([e])+bytes(range(0,256,17))) for e in [0,1,127,254]]):
  key=f'c{i}';(HOST/(key+'.raw')).write_bytes(raw);(HOST/(key+'.expected')).write_bytes(decoded(dtype,raw));controls.append(dict(key=key,type=dtype,bytes=len(raw)));total+=len(raw)
 (HOST/'controls.tsv').write_text(''.join(f"{c['key']}\t{c['type']}\t{c['bytes']}\n" for c in controls),encoding='utf-8')
 literals=Q.contract_fixture();literals['confidence_control_raw']=[9.,-9.,0.,1000.];literals['confidence_control_rate']=[1/(1+math.exp(-min(60.,max(-60.,x)))) for x in literals['confidence_control_raw']];(HOST/'f16-literal.expected').write_bytes(np.asarray(literals['F16_expected_bits'],'<u4').tobytes());(HOST/'tap.expected').write_bytes(Q.tap_mean(np.stack([np.full(5120,x,np.float32) for x in (0,2,4,10)])).tobytes());(HOST/'confidence-literal.expected').write_bytes(struct.pack('<4f',*literals['confidence_control_raw']));(HOST/'pq.expected').write_bytes(struct.pack('<8d',*(literals['accept']+literals['residual'])))
 for key,ids,accepted,cancel in [('first-reject',[5,6,7],[True,False,True],False),('all-accept',[5,6],[True,True],False),('eos',[5,1,7],[True,True,True],False),('cancel',[5],[True],True)]:
  (HOST/(key+'.expected')).write_bytes(np.asarray(Q.verified_trace(ids,accepted,cancelled=cancel),'<u4').tobytes())
 need(total<=8*2**20,'declared bounded raw envelope');need(identity()==before,'source changed during original bounded fixtures')
 manifest=dict(schema='T37-independent-NQ/v1',stage='sealed before native candidate execution',artifact_receipt=record(BUILD/'artifact-receipt.json'),current_identity=before,header_sha256=sha(BUILD/'reference-source/luce-draft-header.json'),source_coverage=record(BUILD/'reference-source/native-source-coverage.json'),literals=literals,spans=spans,controls=controls,confidence_bridge=bridge,raw_bytes=total,scope='original packed decode/host contracts only; no learned draft forward',bindings=[record(p) for p in files()],inputs=[record(p) for p in sorted(HOST.iterdir()) if p.suffix in {'.raw','.expected','.tsv'}])
 write(HOST/'q-manifest.json',manifest);print(json.dumps(dict(stage='NQ-sealed',sha256=sha(HOST/'q-manifest.json'),spans=len(spans),raw_bytes=total)))
def bindings(manifest):
 for row in manifest['bindings']+manifest['inputs']+[manifest['artifact_receipt'],manifest['source_coverage']]:need(capture_record(row)['sha256']==row['sha256'],'source/input binding changed: '+row['path'])
 need(identity()==manifest['current_identity'],'original artifact identity changed')
def verify_outputs(q):
 for row in q['inputs']:
  p=pathlib.Path(row['path'])
  if p.suffix=='.expected':need(p.with_suffix('.out').read_bytes()==p.read_bytes(),'native expected output mismatch: '+p.stem)
 result=read(HOST/'native-result.json');need(result['native_rejections']==11+6*len(q['spans']) and result['native_positives']==3+len(q['spans']) and result['decoded_values']==sum(s['values'] for s in q['spans']),'native contract counts')
 return dict(real_spans=len(q['spans']),real_decoded_values=result['decoded_values'],native_rejections=result['native_rejections'],raw_bytes=q['raw_bytes'],confidence_bridge=q['confidence_bridge'],all_output_bytes_exact=True,GPU_executions=0,draft_forward_qualified=False)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
 need(args.verify_only and not args.prepare_only,'r2 wrapper is CPU-only; original acquisition/Q/native build use the preserved capture recipe')
 validator_before=record(pathlib.Path(__file__))
 if args.prepare_only:prepare();return
 q=read(HOST/'q-manifest.json');bindings(q);artifact_check();helper=load('t37_host_toolchain',EXT/'tests/native/build_verify.py');tools,env=helper.toolchain(HOST);compiled=[EXT/'models/deepseek41/dspark_contract.hpp',EXT/'models/deepseek41/dspark_contract.cpp',HERE/'contract_fixture.cpp',EXT/'native/artifact/native_reader.cpp',EXT/'native/artifact/native_reader.hpp'];source_id=hashlib.sha256(''.join(str(p)+'|'+sha(p)+'\n' for p in compiled).encode()).hexdigest();exe=HOST/'native/t37_dspark_contract.exe'
 if not args.verify_only:
  tool_before={k:record(v) for k,v in tools.items()}
  commands=[[tools['cmake'],'-S',HERE,'-B',HOST/'native','-G','Ninja','-DCMAKE_BUILD_TYPE=Release',f"-DCMAKE_CXX_COMPILER={tools['compiler'].as_posix()}",f"-DCMAKE_MAKE_PROGRAM={tools['ninja'].as_posix()}",f"-DCMAKE_RC_COMPILER={tools['resource_compiler'].as_posix()}",f"-DCMAKE_MT={tools['manifest_tool'].as_posix()}",f'-DT37_SOURCE_SHA={source_id}'],[tools['cmake'],'--build',HOST/'native','--verbose']]
  for i,cmd in enumerate(commands):r=helper.run(cmd,env);(HOST/f'compile-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  need(tool_before=={k:record(v) for k,v in tools.items()},'tool changed during compile');imports=helper.run([tools['dumpbin'],'/dependents',exe],env).stdout;(HOST/'direct-imports.txt').write_text(imports,encoding='utf-8');names=sorted(set(re.findall(r'^\s+([\w.-]+\.dll)\s*$',imports,re.M|re.I)));need(bool(names),'missing PE imports')
  dlls=[record(pathlib.Path(os.environ['SystemRoot'])/'System32'/name) for name in names]
  manifest=dict(schema='T37-host-bundle/v1',source_id=source_id,q=record(HOST/'q-manifest.json'),compiled=[record(p) for p in compiled],recipe=[record(HERE/'CMakeLists.txt'),record(pathlib.Path(__file__))],tools=tool_before,executable=record(exe),commands=[[str(x) for x in c] for c in commands],flags=['/fp:strict','/MT','/utf-8'],direct_imports=dlls,actual_loaded_DLL_paths_verified=False,GPU=False)
  write(HOST/'manifest.json',manifest);bindings(q);result=helper.run([exe,HOST],env);(HOST/'native-result.json').write_text(result.stdout+'\n',encoding='utf-8');(HOST/'native-stderr.log').write_text(result.stderr,encoding='utf-8')
 manifest=read(HOST/'manifest.json');need(manifest['executable']==record(exe) and manifest['q']==record(HOST/'q-manifest.json') and manifest['source_id']==source_id,'native binary/Q identity')
 for row in manifest['compiled']+manifest['recipe']+manifest['direct_imports']+list(manifest['tools'].values()):need(row['sha256']==capture_record(row)['sha256'],'compiled/recipe/tool/DLL binding changed')
 need(json.loads(helper.run([exe,'--identity'],env).stdout)=={'source_sha256':source_id},'compiled identity')
 result=verify_outputs(q);negative=[]
 # Real comparator fault probes, restoring original bytes before the next case.
 for stem in ['f16-literal','tap','confidence-literal','pq','first-reject','r00-first']:
  p=HOST/(stem+'.out');raw=p.read_bytes();p.write_bytes(bytes([raw[0]^1])+raw[1:])
  try:
   try:verify_outputs(q)
   except ValueError:negative.append(stem)
   else:raise AssertionError('output mutation accepted')
  finally:p.write_bytes(raw)
 metadata_negative=[];original=artifact_check()
 for kind in ['missing','duplicate','type','offset','shape','layout','capture','width-as-stage']:
  altered=copy.deepcopy(original)
  if kind=='missing':altered['tensors'].pop()
  elif kind=='duplicate':altered['tensors'][-1]=copy.deepcopy(altered['tensors'][0])
  elif kind=='type':altered['tensors'][0]['type_id']=1
  elif kind=='offset':altered['tensors'][0]['absolute_offset']+=32
  elif kind=='shape':altered['tensors'][0]['dims_ggml'][0]+=1
  elif kind=='layout':altered['tensors'][0]['layout']='BF16'
  elif kind=='capture':altered['metadata']['deepseek41-dflash-draft.dflash.capture_layer_ids']=[37,38,39]
  else:altered['metadata']['deepseek41-dflash-draft.block_count']=5
  try:validate_metadata(altered)
  except ValueError:metadata_negative.append(kind)
  else:raise AssertionError('metadata mutation accepted')
 unfinished_negative=[];fake=HOST/'isolated-writer-lock';fake.mkdir(exist_ok=True);fake_row=dict(index=1,filename='fixture.gguf',bytes=A.BYTES,lfs_sha256=A.LFS)
 final,part,state=A.transfer_module().file_paths(fake,fake_row);no_unfinished(fake,fake_row)
 for label,path in [('actual-part-lock',pathlib.Path(str(part)+'.lock')),('part-body',part)]:
  need(not path.exists(),'unknown isolated fault file');path.write_bytes(b'')
  try:
   # Reproduce the old lock predicate accepting the real writer basename.
   if label=='actual-part-lock':need(not pathlib.Path(str(final)+'.lock').exists() and not part.exists(),'old predicate RED reproduction')
   try:no_unfinished(fake,fake_row)
   except ValueError:unfinished_negative.append(label)
   else:raise AssertionError('unfinished writer accepted')
  finally:path.unlink()
 no_unfinished(fake,fake_row)
 bindings(q);artifact_check();need(verify_outputs(q)==result,'post-negative outputs changed');need(record(pathlib.Path(__file__))==validator_before,'validator changed during CPU validation')
 proof=dict(schema='T37-host-qualification/v1',status='passed',scope='draft fixed artifact / host contracts / original bounded scalar fixtures only',manifest=record(HOST/'manifest.json'),Q=record(HOST/'q-manifest.json'),artifact_receipt=record(BUILD/'artifact-receipt.json'),result=result,output_negative_cases=negative,metadata_negative_cases=metadata_negative,outputs=[record(p) for p in sorted(HOST.glob('*.out'))],source_before_after_unchanged=True,not_qualified=read(EXT/'control/dspark_contract.json')['not_qualified'])
 cpu=dict(schema='T37-wrapper-only-CPU-validation/v2',validator=validator_before,old_capture_runner=record(HOST/'capture-build_verify.py'),old_capture_proof=record(HOST/'capture-verification-r1.json'),old_native_manifest=record(HOST/'manifest.json'),old_Q=record(HOST/'q-manifest.json'),result=result,output_negative_cases=negative,metadata_negative_cases=metadata_negative,unfinished_negative_cases=unfinished_negative,source_before_after_unchanged=True,additional_numeric_fixture_execution=False,additional_GPU_execution=False,native_identity_query_only=True)
 write(HOST/'cpu-validation-r2.json',cpu);aggregate=dict(schema='T37-host-qualification/v2',status='passed',scope=proof['scope'],original_capture=record(HOST/'capture-verification-r1.json'),CPU_revalidation=record(HOST/'cpu-validation-r2.json'),artifact_receipt=proof['artifact_receipt'],result=result,not_qualified=proof['not_qualified'])
 write(BUILD/'verification-r2.json',aggregate);print(json.dumps(dict(status='passed',verification_sha256=sha(BUILD/'verification-r2.json'),CPU_sha256=sha(HOST/'cpu-validation-r2.json'),result=result,output_negative=len(negative),metadata_negative=len(metadata_negative),unfinished_negative=len(unfinished_negative))))
if __name__=='__main__':main()
