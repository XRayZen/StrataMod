"""Explicit T26 CPU qualification of fixed captures; never a runtime gate."""
import argparse,hashlib,importlib.util,json,math,re,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[4];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t26'

def require(ok,message):
 if not ok:raise ValueError(message)
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def record(path):
 p=Path(path);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=sha(p))

def validate_catalog(receipt,inventory,descriptor):
 model=descriptor['model'];require(model['family']=='deepseek41' and model['variant']=='UD-Q4_K_XL' and model['qwen_ple']is False and model['shared_qwen_mtp']is False,'wrong family/layout contract')
 require(receipt['complete']is True and receipt['revision']==inventory['revision']==model['revision'],'incomplete/revision mismatch')
 require(len(receipt['files'])==9 and len(inventory['shards'])==9,'missing original source')
 files={}
 for r in receipt['files']:
  index=r['index'];require(type(index)is int and index not in files and 1<=index<=9,'duplicate/index source');files[index]=r
  identity=r['file_identity'];require(all(type(identity[k])is int and identity[k]>0 for k in ['device','file_id','bytes','mtime_ns']),'invalid observed original identity')
 require(set(files)==set(range(1,10)),'missing source index')
 tensors=[];tokenizers=[]
 for s in inventory['shards']:
  r=files[s['index']];require(type(r['bytes'])is int and type(s['bytes'])is int and r['bytes']==s['bytes'] and r['sha256']==s['lfs_sha256'] and r['file_identity']['bytes']==r['bytes'],'LFS/size correspondence')
  if s['tokenizer_metadata_sha256']:tokenizers.append(s)
  for t in s['tensors']:
   require(type(t['type_id'])is int and t['type_id'] in [0,8,39,43],'unqualified native layout');tensors.append(t)
 require(len(tensors)==1043 and len({t['name'] for t in tensors})==1043,'original tensor coverage')
 layers={int(t['name'].split('.')[1]) for t in tensors if t['name'].startswith('blk.')};require(layers==set(range(40)),'original trunk layer coverage')
 require(len(tokenizers)==1 and tokenizers[0]['token_count']==129280 and tokenizers[0]['tokenizer_metadata_sha256']=='100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924','tokenizer identity')
 require(sum(r['bytes'] for r in files.values())==500707576573==receipt['total_bytes'],'whole original byte count')
 return dict(sources=9,tensors=1043,trunk_layers=40,tokenizer_metadata_sha256=tokenizers[0]['tokenizer_metadata_sha256'],current_identity_validation='caller must run existing validate_receipt before/after; no repeated payload fullhash')

def compare_logits(q,g,ids,positions,targets,implicit_BOS):
 require(type(ids)is list and all(type(x)is int for x in ids) and ids==[3,37,1024],'raw ID semantics')
 require(type(positions)is list and all(type(x)is int for x in positions) and positions==[0,1,2] and implicit_BOS is False,'position/BOS shift')
 require(type(targets)is list and len(targets)==3 and all(type(x)is int or x is None for x in targets) and targets==[37,1024,None],'next-token alignment')
 require(isinstance(q,np.ndarray) and isinstance(g,np.ndarray) and q.dtype==np.dtype('float32') and g.dtype==np.dtype('float32') and q.shape==g.shape==(3,129280),'full vocab/row shape/dtype')
 require(np.isfinite(q).all() and np.isfinite(g).all(),'nonfinite logits')
 require(np.array_equal(q.view(np.uint32),g.view(np.uint32)),'canonical logits bits differ')
 nll=[];margins=[];top=[]
 for row,target in zip(q,targets):
  x=row.astype(np.float64);maximum=float(x.max());shifted_logsum=math.log(float(np.exp(x-maximum).sum(dtype=np.float64)))
  nll.append(None if target is None else float((maximum-x[target])+shifted_logsum));order=np.lexsort((np.arange(x.size),-x));top.append(order[:20].tolist());margins.append(float(x[order[0]]-x[order[1]]))
 require(all(v is None or math.isfinite(v) for v in nll) and all(math.isfinite(v) for v in margins),'derived nonfinite metric')
 return dict(rows=3,vocabulary=129280,logit_values=387840,max_abs=0,max_ULP=0,NRMSE=0,zero_norm_absolute_fallback=True,KL=[0,0,0],top20_overlap=[1,1,1],top20=top,top1_margin=margins,target_NLL=nll,known_NLL_rows=2,terminal_target=None,metrics_scope='fixed text TF; exact Q/G only, no whole-model N-to-Q quality/sampling claim')


def checked_logits(path,expected_bytes,expected_sha256):
 require(type(expected_bytes)is int and expected_bytes>0 and expected_bytes%4==0,'invalid expected logits bytes')
 path=Path(path);require(path.stat().st_size==expected_bytes and sha(path)==expected_sha256,'exact full logits file length/hash')
 return np.fromfile(path,dtype='<f4')

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def verify_refs(refs):
 require(type(refs)is dict and bool(refs),'missing fixed applicable inputs')
 result={}
 for name,r in refs.items():
  require(type(name)is str and type(r)is dict and type(r.get('path'))is str and type(r.get('sha256'))is str and re.fullmatch('[0-9a-f]{64}',r['sha256'])is not None,'malformed fixed source binding')
  path=(ROOT/r['path']).resolve();require(path.is_relative_to(ROOT) and path.is_file(),'fixed input outside owned evidence root/missing')
  require(sha(path)==r['sha256'],'fixed applicable receipt/source '+name);result[name]=record(path)
 return result


def capture_metadata(capture):
 binding=load(capture/'binding-before.json');snapshot=load(capture/'snapshot-binding.json');stdout=load(capture/'stdout.txt');cmake=next(Path(value) for name,value in snapshot['source_map'].items() if name.replace('\\','/').endswith('/tests/core/CMakeLists.txt'));text=cmake.read_text(encoding='utf-8');flags=['-fno-fast-math','-ffp-contract=off','-fdenormal-fp-math=ieee']
 require(all(flag in text for flag in flags),'captured precision flags missing');require(type(stdout.get('source_id'))is str and re.fullmatch('[0-9a-f]{64}',stdout['source_id'])is not None,'actual native source ID missing')
 names=[]
 for group in re.findall(r'(?:set\(INPUTS|list\(APPEND INPUTS) ([^)]+)\)',text):names.extend(group.split())
 require(bool(names),'compiled fingerprint inputs missing');material=''.join(name+'|'+binding['source'][str(ROOT/name)]+'\n' for name in names)
 require(hashlib.sha256(material.encode()).hexdigest()==stdout['source_id'],'compiled source fingerprint mismatch')
 require(stdout.get('full40_progress')is True and type(stdout.get('tokens'))is int and stdout['tokens']==3,'native full40 semantic scope')
 for name,saved in snapshot['source_map'].items():require(sha(saved)==binding['source'][name],'historical source copy changed')
 for name,h in binding['DLL'].items():require(sha(capture/name)==h,'captured native DLL changed')
 require(sha(capture/'captured-native.exe')==binding['EXE'] and sha(capture/'captured-Q-manifest.json')==binding['Q'],'historical native/Q changed')
 return dict(actual_native_source_id=stdout['source_id'],precision_flags=flags,flags_basis='captured compile recipe and actually built native fingerprint; historical fixture profile, not normal launch configuration',compile_recipe=record(cmake),compiled_architectures=['gfx1100','gfx1201'],runtime_selection='captured argv PCI0000:07:00.0 with native checked HIP PCI selection',fixture_profile=dict(family='deepseek41',text=True,context_storage=3,full_logits=True,audit_payload=False,normal_context_cap=False),runtime_environment=record(capture/'runtime-environment.json'),shared_window=record(capture/'shared-window.json'),overlap_scope=load(capture/'shared-window.json'),source_map=record(capture/'snapshot-binding.json'),DLL_SHA256=binding['DLL'])


def bound_record(r):
 require(type(r)is dict and type(r.get('path'))is str and type(r.get('bytes'))is int and r['bytes']>=0 and type(r.get('sha256'))is str and re.fullmatch('[0-9a-f]{64}',r['sha256'])is not None,'malformed linked component record')
 p=Path(r['path']).resolve();require(p.is_relative_to(ROOT) and p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'linked component bytes/hash changed')
 return p


def applicable_components(refs):
 full=load(ROOT/refs['T20_CPU']['path']);branch=load(ROOT/refs['T20_branch']['path']);helper=load(ROOT/refs['T25_helper']['path']);actual=load(ROOT/refs['T25_actual']['path']);restore=load(ROOT/refs['T25_restore']['path'])
 f=full.get('result',{});b=branch.get('result',{})
 require(all(type(f.get(k))is int and f[k]==v for k,v in dict(tokens=3,layers=40,logit_values=387840,explicit_simultaneous_device=19591605).items()),'T20 full component coverage')
 require(all(type(b.get(k))is int and b[k]==v for k,v in dict(default_last_values=129280,audit_pair_values=40968,audit_off_payload_bytes=0,failed_reuse_rejections=2,fresh_actual_layer_sequences=2).items()),'T20 branch/default/audit/failure coverage')
 require(full['original_native_capture']['sha256']==refs['T20_capture']['sha256'] and full['original_native_capture']['EXE']==refs['T20_native']['sha256'] and full['original_native_capture']['Q']==refs['T20_Q']['sha256'],'T20 historical capture linkage')
 require(type(helper.get('roles'))is list and len(helper['roles'])==2,'T25 helper role coverage')
 for role in helper['roles']:require(role.get('before_after')is True and type(role.get('jobs'))is int and role['jobs']==25 and type(role.get('stage_values'))is int and role['stage_values']==6572448,'T25 real helper numerical coverage')
 require(type(actual.get('CPU_validation'))is dict and type(actual.get('capture'))is dict,'T25 actual fixed receipts')
 cpu=load(bound_record(actual['CPU_validation']));captured=load(bound_record(actual['capture']));comparison=cpu.get('comparison',{})
 require(comparison.get('exact')is True and type(comparison.get('values'))is int and comparison['values']==11549556 and cpu.get('before_after')is True ,'T25 actual layer/state coverage')
 identities=cpu.get('original_source_identities_same_as_before_G');source_receipt=load(ROOT/refs['T05']['path']);require(type(identities)is list and len(identities)==9 and all(type(x.get('index'))is int for x in identities) and {x['index']:x['identity'] for x in identities}=={x['index']:x['file_identity'] for x in source_receipt['files']},'T25 original source identity correspondence')
 outputs=captured.get('comparison',{}).get('outputs',[]);require(len(outputs)==1626,'T25 exact stage output coverage')
 for r in outputs:bound_record(r)
 require(restore.get('schema')=='T25-smallstate-final/v1' and restore.get('CPU_runtime_before_after')is True and restore.get('G_after_independent_Q_seal')is True and restore.get('Core_public_snapshot_API_added')is False,'T25 deep restore scope/seal')
 require(type(restore.get('binding'))is list and bool(restore['binding']),'T25 restore binding missing')
 restore_capture=None
 for r in restore['binding']:
  path=bound_record(r)
  if path.name=='verification.json':restore_capture=load(path)
 require(restore_capture is not None and restore_capture.get('before_after')is True,'T25 restore actual capture')
 rc=restore_capture.get('comparison',{});require(rc.get('restored')is True and type(rc.get('values'))is int and rc['values']==15360 and type(rc.get('bytes'))is int and rc['bytes']==61440,'T25 actual deep payload restoration')
 return dict(T20='finitewave1 full40 and required default/audit/failure controls',T25='real Engram helper, actual bounded layer/state, smallstate deep restoration',historic_pending_status_strings_are_not_current_authority=True,selected_actual_stage_outputs=len(outputs),restored_values=15360)

def qualify():
 contract=load(Path(__file__).with_name('contract.json'));require(contract['dependencies_final']is True,'T20 final R1/T25 applicable receipts not yet final; T26 qualification not issued')
 refs=contract['fixed_inputs'];before=verify_refs(refs)
 coverage_ref=contract['T25_coverage'];coverage_before=verify_refs({'T25_coverage':coverage_ref})['T25_coverage'];coverage=load(ROOT/coverage_ref['path']);require(len(coverage.get('files',[]))==20,'T25 applicability map coverage')
 for r in coverage['files']:bound_record(r)
 required={'T05','T10','T20_capture','T20_CPU','T20_native','T20_Q','T20_historical_validator','T20_branch','T25_helper','T25_actual','T25_restore','header_inventory','descriptor','official_config','layouts'};require(set(refs)==required,'applicable component receipt coverage')
 acquire=module('t26_existing_full_source',EXT/'native/artifact/full_acquire.py');source,inventory,fixtures=acquire.load_fixed();receipt=load(EXT/'tests/artifact/full-model-receipt.json');acquire.validate_receipt(receipt,acquire.DESTINATION,source,inventory,fixtures)
 catalog=validate_catalog(receipt,inventory,load(EXT/'control/deepseek41.contract.json'));components=applicable_components(refs);capture=ROOT/'build-deepseek-t20/full-core-attempt-1';m=load(capture/'captured-Q-manifest.json');numeric={(r['position'],r['name']):r for r in m['outputs']};q=np.stack([checked_logits(numeric[i,'logits']['path'],numeric[i,'logits']['bytes'],numeric[i,'logits']['sha256']) for i in range(3)]);g=np.concatenate([checked_logits(capture/'prefill2-logits.bin',m['expected_prefill_bytes'],m['expected_prefill_sha256']).reshape(2,129280),checked_logits(capture/'append-logits.bin',129280*4,m['expected_append_sha256']).reshape(1,129280)])
 for r in m['inputs']+m['expected_files']:require(Path(r['path']).stat().st_size==r['bytes'] and sha(r['path'])==r['sha256'],'independent Q/input changed')
 metadata=capture_metadata(capture);metrics=compare_logits(q,g,m['tokens'],[0,1,2],[37,1024,None],m['implicit_BOS']);historical=module('t26_historical_resource_validator',capture/'cpu-validator-r2.py');trace=historical.full_cache_accounting(m);m['expected_Primary_logical_read']=trace['miss_source_logical'];m['expected_weight_reread_bytes']=trace['actual_source_reread'];resource=historical.validate_full(capture,m)
 acquire.validate_receipt(receipt,acquire.DESTINATION,source,inventory,fixtures)
 for name,r in refs.items():require(sha(ROOT/r['path'])==before[name]['sha256'],'applicable binding changed during CPU qualification')
 require(sha(ROOT/coverage_ref['path'])==coverage_before['sha256'],'T25 applicability map changed during CPU qualification')
 cpu_runtime=dict(python_executable=record(sys.executable),python_version=sys.version,numpy_version=np.__version__,numpy_core=record(np._core._multiarray_umath.__file__))
 proof=dict(schema='strata-t26-TF-receipt/v1',CPU_runtime=cpu_runtime,T25_coverage=coverage_before,inputs=before,numeric=metrics,resources=resource,catalog=catalog,applicable_components=components,actual_bundle=metadata,unobserved_all40_intermediate_drift=None,selected_layer_drift_basis=before['T25_actual'],raw_input_ids=m['tokens'],positions=[0,1,2],implicit_BOS=False,TF_next_targets=[37,1024,None],actual_capture=record(capture/'native-capture-receipt.json'),qualification='fixed primary text full40 teacher forcing; no HTTP/free generation/whole N-to-Q quality/DSpark/vision/secondary claim',GPU_reexecuted=False,validator=record(__file__),contract=record(Path(__file__).with_name('contract.json')))
 BUILD.mkdir(exist_ok=True);output=BUILD/'verification.json';output.write_text(json.dumps(proof,indent=2,allow_nan=False)+'\n',encoding='utf-8');print(json.dumps(dict(receipt=str(output),sha256=sha(output),values=387840,GPU_reexecuted=False)))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--qualify',action='store_true');args=parser.parse_args()
 if args.qualify:qualify()
