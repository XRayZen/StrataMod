"""T38 bounded CPU build. No GPU/network/normal-runtime claim."""
import argparse,hashlib,importlib.util,json,os,pathlib,shutil,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent
WORK=HERE.parents[3];EXT=WORK/'Strata-extensions'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def write(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def run(cmd,env,log):
 p=subprocess.run(list(map(str,cmd)),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
 log.write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
 return dict(argv=list(map(str,cmd)),exit_code=p.returncode,log=str(log),sha256=sha(log))

def seed_compare(input_manifest,q_manifest,q_seal,q_seal_sha,g):
 """Saved bytes only. Caller/Main supplies the reviewed pre-G Q seal SHA."""
 def require(ok,why):
  if not ok:raise ValueError(why)
 def unique(pairs):
  d={}
  for k,v in pairs:
   require(k not in d,'duplicate JSON key');d[k]=v
  return d
 def load(p):
  p=pathlib.Path(p);require(0<p.stat().st_size<=1024*1024,'finite metadata');return json.loads(p.read_text(encoding='utf-8'),object_pairs_hook=unique)
 def descriptor(p):p=pathlib.Path(p);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=sha(p))
 def record(r,p):return pathlib.Path(r['path']).resolve()==p.resolve() and r['bytes']==p.stat().st_size and r['sha256']==sha(p)
 g=pathlib.Path(g);q_manifest=pathlib.Path(q_manifest);q_seal=pathlib.Path(q_seal);input_manifest=pathlib.Path(input_manifest)
 require(0<q_seal.stat().st_size<=1024*1024 and 0<input_manifest.stat().st_size<=65536,'finite Q seal/caller metadata')
 require(sha(q_seal)==q_seal_sha,'pre-G Q seal mismatch');seal=load(q_seal);q=load(q_manifest);require(seal['schema']=='T38-independent-P3-seed-Q/preG-seal-v1' and q['schema']=='T38-P3-independent-seed-Q/r1' and q['status']=='complete','independent Q schema/status')
 require(any(record(r,q_manifest)for r in seal['records']if pathlib.Path(r['path']).resolve()==q_manifest.resolve()),'Q manifest absent/drifted in pre-G seal')
 specs={'joined':(1,15360,61440),'main':(1,5120,20480),'ring0':(128,512,262144),'ring1':(128,512,262144),'ring2':(128,512,262144)}
 outputs={x['name']:x for x in q['outputs']};require(len(q['outputs'])==5 and set(outputs)==set(specs),'Q five fields')
 binding=load(g/'input-binding.json');require(binding['schema']=='T38-seed-input-binding-v1' and binding['read_identity_before_after_equal']is True,'actual input binding schema/identity')
 for k in ['manifest_bytes_dec','volume_serial_dec','file_id_dec','last_write_FILETIME_dec']:require(isinstance(binding[k],str) and binding[k].isascii() and binding[k].isdecimal() and int(binding[k])<=2**64-1,'input binding exact uint64 string')
 require(int(binding['volume_serial_dec'])<=2**32-1 and pathlib.Path(binding['manifest_path']).resolve()==input_manifest.resolve() and int(binding['manifest_bytes_dec'])==input_manifest.stat().st_size and binding['manifest_sha256']==sha(input_manifest)==sha(g/'input-manifest.tsv'),'actual caller input bytes/binding')
 caller={};identity={};prompt=0
 for line in input_manifest.read_text(encoding='utf-8').splitlines():
  cells=line.split('\t')
  if cells[0]in ['caller','identity']:
   require(len(cells)==3,'caller columns');d=caller if cells[0]=='caller' else identity;require(cells[1]not in d,'duplicate caller/identity');d[cells[1]]=cells[2]
  if cells[0]=='prompt':require(cells==['prompt','3','37','1024'],'P3 prompt');prompt+=1
 require(prompt==1 and caller['owner'].isascii() and caller['owner'].isdecimal() and int(caller['owner'])>0 and caller['epoch'].isascii() and caller['epoch'].isdecimal() and int(caller['epoch'])>0,'explicit P3 caller')
 require(identity==dict(fixture_sha256=caller['bundle'],asset_sha256=caller['bundle'],bundle_sha256=caller['bundle'],request_id=caller['request_id'],epoch=caller['epoch'],phase='prefill'),'full caller Identity')
 capture=load(g/'capture.json');completion=load(g/'completion.json');require(capture['schema']=='T38-actual-seed-capture-v1' and capture['manifest_sha256']==binding['manifest_sha256'] and capture['owner']==int(caller['owner']) and capture['epoch']==int(caller['epoch']) and capture['bundle']==caller['bundle'] and capture['request_id']==caller['request_id'],'actual completed caller provenance')
 require(capture['position']==2 and capture['cursor']==3 and capture['stage_cursor']==[3,3,3] and capture['prior']==1024 and capture['valid']is True and capture['copy_drained']is True,'actual selected completion metadata')
 for k in ['producer_stream','actual_owner']:require(isinstance(capture[k],str) and capture[k].isascii() and capture[k].isdecimal() and int(capture[k])>0,'actual stream/owner identity')
 require(all(type(capture[k])is int and 0<capture[k]<=2**64-1 for k in ['owner','epoch','generation']),'actual exact owner/epoch/generation')
 require(completion==dict(actual_target_cursor=3,actual_draft_cursor=3,completion_known=True,RequestActor_run_called=False,propose_called=False,ledger_success_claimed=False),'actual prefill-only completion')
 require(q['expected_metadata']['processed_position']==2 and q['expected_metadata']['cursor']==3 and q['expected_metadata']['stage_cursor']==[3,3,3] and q['expected_metadata']['processed_prior']==1024 and q['expected_metadata']['valid']is True,'Q metadata')
 fields={x['name']:x for x in capture['fields']};require(len(capture['fields'])==5 and set(fields)==set(specs),'actual five fields')
 result=dict(schema='T38-saved-seed-comparison/v1',Q_seal=descriptor(q_seal),Q_manifest=descriptor(q_manifest),input_manifest=descriptor(input_manifest),capture=descriptor(g/'capture.json'),matched=[],mismatches=[],fields=[],GPU_started_by_comparer=False,expected_updated=False,Network_other_stages_qualified=False)
 for name,(rows,cols,size)in specs.items():
  e=outputs[name];actual=fields[name];expected=pathlib.Path(e['path']);saved=g/(name+'.bin')
  require(e['shape']==[rows,cols] and e['dtype']=='BF16-value in little-endian F32' and e['bytes']==size and expected.stat().st_size==size and sha(expected)==e['sha256'],'frozen Q descriptor/bytes')
  require(any(record(r,expected)for r in seal['records']if pathlib.Path(r['path']).resolve()==expected.resolve()),'Q field absent/drifted in pre-G seal')
  require(actual['rows']==rows and actual['columns']==cols and actual['dtype']=='BF16-in-F32' and actual['bytes']==size and saved.stat().st_size==size and sha(saved)==actual['sha256'],'actual field descriptor/raw bytes')
  exact=saved.read_bytes()==expected.read_bytes();result['matched'if exact else 'mismatches'].append(name);result['fields'].append(dict(name=name,actual=descriptor(saved),expected=descriptor(expected),exact_words=exact,maxabs=0 if exact else None,NRMSE=0 if exact else None,ULP=0 if exact else None,signed_zero_included=True))
 result['success']=not result['mismatches'];return result

PROPOSAL_SEAL_SHA='303a67d088174b1d422bd3d64f826dbbc34213272c7fcc58b83b0d082933f81e'
PROPOSAL_MANIFEST_SHA='8200b3a8772ff03eac71e423472dce2643cc0dd86bb6db3a2db62cb68c9c3d29'
def proposal_compare(input_manifest,q_manifest,q_seal,q_seal_sha,g):
 """Nine actual saved fields; immutable accepted greedy P3/W5 Q only."""
 def need(ok,why):
  if not ok:raise ValueError(why)
 def unique(pairs):
  d={}
  for k,v in pairs:need(k not in d,'duplicate JSON key');d[k]=v
  return d
 def load(p):
  p=pathlib.Path(p);need(0<p.stat().st_size<=1024*1024,'finite proposal metadata');return json.loads(p.read_text(encoding='utf-8'),object_pairs_hook=unique)
 def row(p):p=pathlib.Path(p);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=sha(p))
 def sealed(seal,p):return any(pathlib.Path(r['path']).resolve()==p.resolve()and r['bytes']==p.stat().st_size and r['sha256']==sha(p)for r in seal['records']if pathlib.Path(r['path']).resolve()==p.resolve())
 input_manifest=pathlib.Path(input_manifest);q_manifest=pathlib.Path(q_manifest);q_seal=pathlib.Path(q_seal);g=pathlib.Path(g)
 need(0<input_manifest.stat().st_size<=65536 and 0<q_seal.stat().st_size<=1024*1024 and 0<q_manifest.stat().st_size<=1024*1024,'finite caller/seal');need(q_seal_sha==PROPOSAL_SEAL_SHA==sha(q_seal)and sha(q_manifest)==PROPOSAL_MANIFEST_SHA,'accepted pre-G proposal authority')
 seal=load(q_seal);q=load(q_manifest);need(seal['schema']=='T38-independent-greedy-P3W5-proposal/preG-seal-v1'and q['schema']=='T38-greedy-P3-W5-independent-proposal-Q/r1'and q['status']=='complete'and sealed(seal,q_manifest),'proposal Q seal/schema')
 need(q['history']==[3,37,1024]and q['logical_width']==5 and q['position']==2 and q['q_sampling_options']==dict(seed=0,temperature=0,top_k=0,top_p=1,min_p=0,repetition=1,frequency=0,presence=0,logit_bias={},diagnostics=False),'finite accepted greedy options/history')
 rows={};caller={};identity={};receipts={};prompt=[]
 for line in input_manifest.read_text(encoding='utf-8').splitlines():
  v=line.split('\t')
  if v[0]in ['caller','identity']:
   need(len(v)==3,'proposal caller columns');d=caller if v[0]=='caller'else identity;need(v[1]not in d,'duplicate caller field');d[v[1]]=v[2]
  if v[0]=='prompt':prompt.append(v[1:])
  if v[0]=='receipt':need(len(v)==4 and v[1]not in receipts,'proposal receipt row');receipts[v[1]]=(v[2],v[3])
 need(prompt==[['3','37','1024']]and set(receipts)=={'target','draft','draft_prefix','input_lineage'},'actual finite P3/receipts')
 need(identity==dict(fixture_sha256=caller['bundle'],asset_sha256=caller['bundle'],bundle_sha256=caller['bundle'],request_id=caller['request_id'],epoch=caller['epoch'],phase='prefill'),'actual full Identity')
 binding=load(g/'input-binding.json');need(binding['schema']=='T38-seed-input-binding-v1'and binding['read_identity_before_after_equal']is True,'actual input handle binding')
 for k in ['manifest_bytes_dec','volume_serial_dec','file_id_dec','last_write_FILETIME_dec']:need(type(binding[k])is str and binding[k].isascii()and binding[k].isdecimal()and int(binding[k])<=2**64-1,'exact input identity integer string')
 need(pathlib.Path(binding['manifest_path']).resolve()==input_manifest.resolve()and int(binding['manifest_bytes_dec'])==input_manifest.stat().st_size and binding['manifest_sha256']==sha(input_manifest)==sha(g/'input-manifest.tsv'),'actual immutable caller bytes')
 lineage=pathlib.Path(receipts['input_lineage'][0]);need(lineage.stat().st_size<=1024*1024 and sha(lineage)==receipts['input_lineage'][1],'proposal lineage receipt bytes');values={};refs={};fields={}
 for line in lineage.read_text(encoding='utf-8').splitlines():
  v=line.split('\t')
  if len(v)==2:need(v[0]not in values,'duplicate lineage value');values[v[0]]=v[1]
  elif len(v)==4 and v[0]=='ref':need(v[1]not in refs,'duplicate lineage ref');refs[v[1]]=v[2:]
  elif len(v)==6 and v[0]=='field':need(v[1]not in fields,'duplicate lineage field');fields[v[1]]=v[2:]
  else:raise ValueError('proposal explicit lineage format')
 need(values['fixture_kind']=='proposal'and values['schema']=='T38-proposal-lineage-v1'and values['source_origin_sha256']=='fc5b8c8d26eb1f89f1b18cf4e983f615ffcb757104b491c386f7d350889392ae','explicit proposal branch/source lineage')
 need(len(values)==10 and len(refs)==5 and len(fields)==9,'finite proposal lineage rows')
 for k in ['owner','epoch','bundle','request_id']:need(values[k]==caller[k],'proposal lineage caller')
 for k in ['target','draft','draft_prefix']:need(values[k+'_receipt_sha256']==receipts[k][1],'proposal original receipt lineage')
 need(refs['proposal_seal']==[str(q_seal),q_seal_sha]and refs['proposal_manifest']==[str(q_manifest),PROPOSAL_MANIFEST_SHA],'proposal lineage selected Q')
 for k,h in {'seed_seal':'2057666abb7a2d7b162f6fb9752c6a4ccaab9d80181952d8fd4abfe5e6985eb0','seed_manifest':'2e44f3e6f79f1ad511da1135e34ba3127a6c599b56efea93ee9284319acd1918','seed_input_seal':'59801533ef8ffc46f43d99487fabb930d4d4b05cd7b1dc7f9dd795073acf2acd'}.items():
  rp=pathlib.Path(refs[k][0]);need(refs[k][1]==h and 0<rp.stat().st_size<=1024*1024 and sha(rp)==h,'original seed authority metadata')
 capture=load(g/'capture.json');need(capture['schema']=='T38-actual-proposal-capture-v1'and capture['fixture_kind']=='proposal'and capture['manifest_sha256']==binding['manifest_sha256'],'actual proposal capture type/input')
 for k in ['owner','epoch']:need(type(capture[k])is int and 0<capture[k]<=2**64-1 and capture[k]==int(caller[k]),'actual proposal binding integer')
 need(capture['bundle']==caller['bundle']and capture['request_id']==caller['request_id']and capture['processed_cursor']==3 and capture['position']==2 and capture['width']==5 and capture['copy_drained']is True,'actual proposal completed metadata')
 specs={'stage0-residual':(5,20480,'<f4',409600),'stage1-residual':(5,20480,'<f4',409600),'stage2-residual':(5,20480,'<f4',409600),'tail-collapsed':(5,5120,'<f4',102400),'head-normalized':(5,5120,'<f4',102400),'head-pre-markov':(5,129280,'<f4',2585600),'q':(5,129280,'<f8',5171200),'ids':(1,5,'<u4',20),'raw-confidence':(1,5,'<f4',20)}
 need([e['field']for e in capture['events']]==list(specs)[:6],'six actual ordered proposal events')
 for e in capture['events']:
  need(e['copy_drained']is True and type(e['generation'])is int and e['generation']>0 and e['device']==0,'actual event drain/lease/device')
  for k in ['producer_stream','allocation_owner']:need(type(e[k])is str and e[k].isascii()and e[k].isdecimal()and int(e[k])>0,'actual producing stream/owner')
 need(len({e['producer_stream']for e in capture['events'][:5]})==1 and capture['events'][5]['producer_stream']!=capture['events'][0]['producer_stream'],'head TargetSupply versus weights producer stream')
 need(capture['RNG_draws_measured']is False and capture['source_RNG_callsite_contract']==dict(Proposal=5,Target=0,Accept=0,Residual=0,Bonus=0),'source-only RNG contract')
 need(load(g/'completion.json')==dict(fixture_kind='proposal',actual_target_cursor=3,actual_draft_cursor=3,completion_known=True,proposal_calls=1,RequestActor_run_called=False,target_step_called=False,ledger_success_claimed=False),'actual one proposal completion')
 actual={x['name']:x for x in capture['fields']};expected={x['name']:x for x in q['outputs']};need(len(capture['fields'])==len(q['outputs'])==9 and set(actual)==set(expected)==set(fields)==set(specs),'nine fields only')
 result=dict(schema='T38-saved-proposal-comparison/v1',Q_seal=row(q_seal),Q_manifest=row(q_manifest),input_manifest=row(input_manifest),capture=row(g/'capture.json'),matched=[],mismatches=[],fields=[],GPU_started_by_comparer=False,expected_updated=False,actor_or_normal_qualified=False)
 for name,(r,c,t,n)in specs.items():
  a,e=actual[name],expected[name];saved=g/(name+'.bin');frozen=pathlib.Path(e['path']);shape=[c]if name in ['ids','raw-confidence']else[r,c]
  need(fields[name]==[str(r),str(c),t,str(n)],'lineage nine descriptor');need(e['shape']==shape and e['dtype']==t and e['bytes']==n and frozen.stat().st_size==n and sha(frozen)==e['sha256']and sealed(seal,frozen),'frozen proposal Q field')
  need(a['rows']==r and a['columns']==c and a['dtype']==t and a['bytes']==n and saved.stat().st_size==n and sha(saved)==a['sha256'],'actual proposal field bytes/descriptor')
  exact=True
  with saved.open('rb')as x,frozen.open('rb')as y:
   while True:
    xb=x.read(65536);yb=y.read(65536)
    if xb!=yb:exact=False;break
    if not xb:break
  result['matched'if exact else'mismatches'].append(name);result['fields'].append(dict(name=name,actual=row(saved),expected=row(frozen),exact_words=exact,maxabs=0 if exact else None,NRMSE=0 if exact else None,ULP=0 if exact else None,signed_zero_included=True))
 result['success']=not result['mismatches'];return result
ACTOR_ORIGIN='acbfe10cc8107233972d8c6cb27bbe171cf8926eea4f304a53ea77f89612cf4f'
ACTOR_INITIAL_HEAD='09bc07791e97a128eaec01f195dd9c3b6baeccc9eb3c2c32b1db744801144835'
ACTOR_FIXED_REFS={'initial_head_handoff':'4fbea4762f84ddb1c20e528189fa1d32fed17246730f5adb3e8ebcc224fe20b6','initial_head_seal':'6abb4ab5dbca55309c1c06a9688c7c13d92e4f96e59d2af860e0952b69c002b3','initial_head_result':'dd06a42a1ecf962b75790d7e7ce6bdb96dec564aca23c8c499d76b5326785b93','proposal_seal':'303a67d088174b1d422bd3d64f826dbbc34213272c7fcc58b83b0d082933f81e','qualified_proposal_actual':'e1ef3f5d309d344f2cb95598731b9ab7dab111c7732c6cb6783c10a9fda8cda9'}
def actor_compare(input_manifest,q_manifest,q_seal,q_seal_sha,g):
 """SourceCPU accepts incomplete supplier metadata; comparison/native qualification require a preaccepted complete independent seal."""
 def need(ok,why):
  if not ok:raise ValueError(why)
 def load(p):
  p=pathlib.Path(p);need(0<p.stat().st_size<=1024*1024,'finite actor metadata')
  def unique(pairs):
   d={}
   for k,v in pairs:need(k not in d,'duplicate actor JSON key');d[k]=v
   return d
  return json.loads(p.read_text(encoding='utf-8'),object_pairs_hook=unique)
 def descriptor(p):p=pathlib.Path(p);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=sha(p))
 def sealed(s,p):return any(pathlib.Path(x['path']).resolve()==p.resolve()and x['bytes']==p.stat().st_size and x['sha256']==sha(p)for x in s['records']if pathlib.Path(x['path']).resolve()==p.resolve())
 input_manifest=pathlib.Path(input_manifest);q_manifest=pathlib.Path(q_manifest);q_seal=pathlib.Path(q_seal);g=pathlib.Path(g)
 need(len(q_seal_sha)==64 and sha(q_seal)==q_seal_sha,'selected accepted actor Q seal');seal=load(q_seal);q=load(q_manifest)
 need(q['schema']=='T38-independent-actor-P3-max2-Q/r1'and q['status']=='complete'and sealed(seal,q_manifest),'independent actor expectation incomplete/unsealed')
 need(q['prompt']==[3,37,1024]and q['maximum']==2 and q['width']==5 and q['seed']==0 and type(q['first_id'])is int and q['first_id']==288 and type(q['second_id'])is int and 0<=q['second_id']<129280,'actor finite expected case')
 need(q['initial_head_sha256']==ACTOR_INITIAL_HEAD and q['initial_target_p_sha256']=='746068dcb816deeccee38ef1064800b103959fe20e7d5acf35c09a918072a394'and q['qualified_initial_draft_id']==16,'actor independent initial boundary')
 need(input_manifest.stat().st_size<=65536,'finite actor input');text=input_manifest.read_text(encoding='utf-8');caller={};identity={};producer={};receipts={};prompt=[];schema=[]
 for line in text.splitlines():
  v=line.split('\t')
  if v[0]in ['caller','identity','producer']:
   need(len(v)==3,'actor input columns');d={'caller':caller,'identity':identity,'producer':producer}[v[0]];need(v[1]not in d,'duplicate actor input');d[v[1]]=v[2]
  elif v[0]=='receipt':need(len(v)==4 and v[1]not in receipts,'actor receipt');receipts[v[1]]=v[2:]
  elif v[0]=='prompt':prompt.append(v[1:])
  elif v[0]=='schema':schema.append(v[1:])
  else:raise ValueError('actor input field')
 need(schema==[['T38-seed-input-v1']]and prompt==[['3','37','1024']]and set(receipts)=={'target','draft','draft_prefix','input_lineage'}and int(producer['context'])>=4,'actor finite entry/context')
 need(caller['epoch']==producer['runtime_epoch']==identity['epoch']and caller['bundle']==producer['bundle_id']==identity['fixture_sha256']==identity['asset_sha256']==identity['bundle_sha256']and caller['request_id']==identity['request_id'],'actor caller identity equality')
 lineage=pathlib.Path(receipts['input_lineage'][0]);need(lineage.stat().st_size<=1024*1024 and sha(lineage)==receipts['input_lineage'][1],'actor lineage hash');values={};refs={}
 for line in lineage.read_text(encoding='utf-8').splitlines():
  v=line.split('\t')
  if len(v)==2:need(v[0]not in values,'duplicate actor lineage');values[v[0]]=v[1]
  elif len(v)==4 and v[0]=='ref':need(v[1]not in refs,'duplicate actor ref');refs[v[1]]=v[2:]
  else:raise ValueError('actor lineage columns')
 need(len(values)==13 and len(refs)==7 and values['schema']=='T38-actor-lineage-v1'and values['fixture_kind']=='actor'and values['source_origin_sha256']==ACTOR_ORIGIN and values['expected_status']=='complete','actor explicit complete lineage')
 for k in ['owner','epoch','bundle','request_id']:need(values[k]==caller[k],'actor lineage caller')
 for k in ['target','draft','draft_prefix']:need(values[k+'_receipt_sha256']==receipts[k][1],'actor original receipt')
 for k,v in ACTOR_FIXED_REFS.items():need(refs[k][1]==v and pathlib.Path(refs[k][0]).stat().st_size<=1024*1024 and sha(refs[k][0])==v,'actor accepted fixed reference')
 need(refs['final_expected_manifest']==[str(q_manifest),sha(q_manifest)]and refs['final_expected_seal']==[str(q_seal),q_seal_sha]and values['final_expected_manifest_sha256']==sha(q_manifest)and values['final_expected_seal_sha256']==q_seal_sha,'actor final preG expectation binding')
 capture=load(g/'capture.json');actual=load(g/'actor-result.json');binding=load(g/'input-binding.json');need((g/'input-manifest.tsv').read_bytes()==input_manifest.read_bytes()and capture['manifest_sha256']==binding['manifest_sha256']==sha(input_manifest)and binding['schema']=='T38-seed-input-binding-v1'and binding['manifest_path']==str(input_manifest.resolve())and binding['manifest_bytes_dec']==str(input_manifest.stat().st_size)and binding['read_identity_before_after_equal']is True,'actor saved original input binding')
 need(capture['schema']=='T38-actual-actor-capture-v1'and capture['fixture_kind']=='actor'and capture['RequestActor_run_calls']==1 and capture['RNG_draws_measured']is False,'actor actual source execution')
 for k in ['owner','epoch']:need(str(capture[k])==caller[k],'actor actual owner/epoch')
 for k in ['bundle','request_id']:need(capture[k]==caller[k],'actor actual caller')
 result=dict(schema='T38-saved-actor-comparison/v1',success=False,Q_seal=descriptor(q_seal),Q_manifest=descriptor(q_manifest),actual_result=actual,matched=[],mismatches=[],fields=[],GPU_started_by_comparer=False,expected_updated=False,normal_GEN_or_newprefix_draft_q_qualified=False)
 names={'initial-target-logits':(129280,517120),'post-step-target-logits':(129280,517120),'processed-tap-joined':(15360,61440)}
 fields={x['name']:x for x in capture['fields']};need(len(fields)==len(capture['fields'])and set(fields)<=set(names)|{'emitted-ids'},'finite actor capture fields')
 # Preserve actual premature EOS/error/cancellation result; it is never padded into the max2 success pattern.
 if capture['emitter_count']!=2 or not capture['joined_complete']or capture['copy_unknown']or actual['error']or not actual['completion_known']or not actual['context_valid']:
  result['classification']='actual_incomplete_or_failed';return result
 need(set(fields)==set(names)|{'emitted-ids'}and capture['emitter_timing']==[dict(id=288,target_cursor=3,draft_cursor=3),dict(id=q['second_id'],target_cursor=4,draft_cursor=4)]and capture['processed_position']==3 and capture['processed_prior']==288 and capture['processed_cursor']==4 and capture['stage_cursor']==[4,4,4]and capture['processed_valid']is True and int(capture['producer_stream'])!=0 and int(capture['allocation_owner'])!=0 and capture['generation']>0 and capture['device']==0,'actor successful emission/processed provenance')
 need(actual['schema']=='T38-actual-actor-result-v1'and actual['prompt']==3 and actual['processed_generated']==1 and actual['cursor']==4 and actual['emitted']==[288,q['second_id']]and actual['processed']==[288]and actual['pending']==q['second_id']and actual['finish']==('eos'if q['second_id']==1 else'length')and actual['known_target_cursor']==actual['draft_cursor']==4,'actual E2 G1 C4 pending/finish ledger')
 expected={x['name']:x for x in q['fields']};need(len(q['fields'])==3 and set(expected)==set(names),'independent three actor numeric fields')
 for name,(columns,size)in names.items():
  e=expected[name];p=pathlib.Path(e['path']);a=fields[name];saved=g/(name+'.bin');need(e['shape']==[1,columns]and e['dtype']=='<f4'and e['bytes']==size and p.stat().st_size==size and sha(p)==e['sha256']and sealed(seal,p),'actor presealed expected field')
  if name=='initial-target-logits':need(e['sha256']==ACTOR_INITIAL_HEAD,'accepted original initial head')
  need(a['rows']==1 and a['columns']==columns and a['dtype']=='<f4'and a['bytes']==size and saved.stat().st_size==size and sha(saved)==a['sha256'],'actual actor field descriptor')
  exact=True
  with p.open('rb')as ef,saved.open('rb')as gf:
   while True:
    eb=ef.read(65536);gb=gf.read(65536)
    if eb!=gb:exact=False
    if not eb and not gb:break
  result['matched'if exact else'mismatches'].append(name);result['fields'].append(dict(name=name,exact_words=exact,actual=descriptor(saved),expected=descriptor(p),maxabs=0 if exact else None,ULP=0 if exact else None,NRMSE=0 if exact else None,signed_zero_included=True))
 import struct
 ids=g/'emitted-ids.bin';a=fields['emitted-ids'];need(a['rows']==1 and a['columns']==2 and a['dtype']=='<u4'and a['bytes']==8 and ids.stat().st_size==8 and sha(ids)==a['sha256'],'actor exact two ID storage');exact=ids.read_bytes()==struct.pack('<II',288,q['second_id']);result['matched'if exact else'mismatches'].append('emitted-ids');result['success']=not result['mismatches'];result['classification']='exact_match'if result['success']else'numerical_mismatch';return result

# Dedicated five-case disk comparator and focused CPU runner. No runtime launch.
def global_compare(g,numeric):
 import struct,math as _finite_math
 g=pathlib.Path(g);numeric=pathlib.Path(numeric)
 def need(x,m):
  if not x:raise ValueError(m)
 def load(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
 def exact(a,b):
  need(a.is_file() and b.is_file() and a.stat().st_size==b.stat().st_size,'missing/size pair');need(a.read_bytes()==b.read_bytes(),'canonical word mismatch:'+str(a));return dict(candidate=str(a),fresh=str(b),bytes=a.stat().st_size,exact=True)
 def field_bytes(directory,f):
  p=directory/(f['name']+'.bin');need(p.stat().st_size==f['bytes'] and sha(p)==f['sha256'],'draft field binding');return p.read_bytes()
 def draft(a,b,full=False):
  aa=load(a/'draft.json');bb=load(b/'draft.json');need(set(aa)==set(bb),'draft metadata schema')
  for key in ('epoch','cursor','stage_cursor','prior','valid'):need(aa[key]==bb[key],'draft metadata:'+key)
  need(aa['valid']is True and aa['stage_cursor']==[aa['cursor']]*3,'healthy draft metadata');need((aa['owner']==bb['owner'])if full else(aa['owner']!=bb['owner']),'explicit same/fresh owner mapping')
  af={f['name']:f for f in aa['fields']};bf={f['name']:f for f in bb['fields']};need(set(af)==set(bf)=={'features','ring0','ring1','ring2'},'math four buffers')
  size=0
  for name in af:
   x,y=af[name],bf[name];need((x['rows'],x['columns'],x['scalar'],x['bytes'])==(y['rows'],y['columns'],y['scalar'],y['bytes']),'math shape/scalar')
   expected=(1,15360,61440)if name=='features'else(128,512,262144);need((x['rows'],x['columns'],x['bytes'])==expected,'math actual geometry')
   ab=field_bytes(a,x);ba=field_bytes(b,y);valid=len(ab)if full or name=='features'else min(aa['cursor'],128)*512*4;need(ab[:valid]==ba[:valid],'math exact valid rows');size+=valid
  return dict(cursor=aa['cursor'],exact_valid_bytes=size,unused_ring_capacity_compared=full,full_restore=full)
 candidate=g/'candidate';fresh=g/'fresh';need(candidate.is_dir() and fresh.is_dir(),'same-owner fresh Body missing')
 completion=load(g/'fresh-completion.json');need(completion['completion_known']is True and completion['old_pending_replayed']is False and completion['new_owner']!=completion['candidate_owner'],'actual fresh identity/completion')
 checkpoints=sorted(int(p.name[1:])for p in candidate.iterdir()if p.is_dir() and p.name.startswith('c') and p.name[1:].isdigit());need(checkpoints,'selected cursors')
 records=[];math=[]
 required={('core',0),('candidates',20),('history',0),('engram_hashes',0)}|{('swa',i)for i in range(40)}|{(k,i)for k in ('compressed','keys')for i in (2,8,14,20)}|{(k,i)for k in ('pending_kv','pending_score')for i in (2,8,14)}
 for cursor in checkpoints:
  a=candidate/('c'+str(cursor));b=fresh/('c'+str(cursor));
  for d in (a,b):need((d/'head.bin').stat().st_size==517120 and all(_finite_math.isfinite(v[0]) for v in struct.iter_unpack('<f',(d/'head.bin').read_bytes())),'full finite129280 head')
  records.append(exact(a/'head.bin',b/'head.bin'));aa=load(a/'state.json');bb=load(b/'state.json');need(aa['schema']==bb['schema']=='T38-global-state-v1' and aa['cursor']==bb['cursor']==cursor,'typed state cursor')
  def keyed(doc):
   result={}
   for r in doc['records']:
    key=(r['kind'],r['writer']);need(key not in result,'duplicate typed record')
    need(all(type(r[k])is int and r[k]>=0 for k in ('writer','ratio','position','epoch','rows','first','end','value_rows','columns','scalar','bytes')) and type(r['valid'])is bool,'typed exact integer metadata')
    kind=r['kind'];rows=r['rows'];vr=r['value_rows'];cols=r['columns'];scalar=r['scalar'];size=r['bytes'];need(scalar in range(7),'typed scalar')
    if vr or cols:need(vr>0 and cols>0 and size==vr*cols*(8 if scalar==6 else 2 if scalar==1 else 1 if scalar==3 else 4),'typed valid byte geometry')
    if kind=='core':need(r['first']==0 and r['end']==40 and r['position']==cursor and r['valid'] and size==0,'typed full forty core')
    elif kind=='swa':need(r['writer']<40 and r['ratio']==1 and r['position']==cursor and r['valid'] and rows==vr==min(cursor,128) and cols==512 and scalar==2,'typed SWA valid rows')
    elif kind in ('compressed','keys'):
     ratio=1 if r['writer']==20 else 2;need(r['writer']in(2,8,14,20) and r['ratio']==ratio and rows==vr==cursor//ratio and cols==(512 if kind=='compressed'else 128) and scalar==2 and r['valid'],'typed compressed/shared source geometry')
    elif kind in ('pending_kv','pending_score'):need(r['writer']in(2,8,14) and r['ratio']==2 and rows==vr==cursor%2 and cols==(512 if rows else 0) and scalar==0 and r['valid'],'typed ratio2 pending extent')
    elif kind=='history':need(rows==min(cursor,3) and size==rows*8 and vr==cols==0,'typed history extent')
    elif kind=='engram_hashes':need(rows==48 and size==384 and vr==cols==0 and r['position']==cursor-1,'typed full48 hash extent')
    elif kind=='candidates':need(rows==cursor and vr==1 and cols==rows and scalar==0 and r['writer']==20 and r['ratio']==1,'typed shared candidates')
    elif kind=='selection':need((r['valid'] and vr==1 and cols==min(512,rows) and scalar==6)or(not r['valid'] and not size),'typed selected valid extent')
    result[key]=r
   need(required<=set(result) and sum(k[0]=='selection'for k in result)==1 and len(result)==len(required)+1,'full forty typed record set');return result
  ar=keyed(aa);br=keyed(bb);need(set(ar)==set(br),'typed keys')
  for key in ar:
   x,y=ar[key],br[key];need({k:v for k,v in x.items()if k not in ('file','sha256','owner','generation','identity_request')}=={k:v for k,v in y.items()if k not in ('file','sha256','owner','generation','identity_request')},'typed metadata/validrows')
   for d,r in ((a,x),(b,y)):need(pathlib.Path(r['file']).name==r['file'] and (d/r['file']).stat().st_size==r['bytes'] and sha(d/r['file'])==r['sha256'],'typed payload binding')
   records.append(exact(a/x['file'],b/y['file']))
  math.append(draft(candidate/('c'+str(cursor)+'-draft'),fresh/('c'+str(cursor)+'-draft')))
 routes=[];ar=candidate/'routes';br=fresh/'routes';need(ar.is_dir() and br.is_dir(),'actual route records missing');names={p.name for p in ar.glob('*.bin')};need(names=={p.name for p in br.glob('*.bin')},'route selected frame set')
 expected_route={(c-1,l,k)for c in checkpoints for l in range(40)for k in ('ffn_router_ids','ffn_router_weights')}
 seen=set()
 for name in sorted(names):
  pos,layer,kind=name[:-4].split('-',2);seen.add((int(pos),int(layer),kind));routes.append(exact(ar/name,br/name));a=load(ar/(name[:-4]+'.json'));b=load(br/(name[:-4]+'.json'));need(a==b,'route shape/domain metadata');need(a['rows']==1 and a['columns']==6 and a['bytes']==24 and a['scalar']==(4 if kind=='ffn_router_ids'else 0),'full top6 route geometry')
 need(seen==expected_route,'all forty selected actual route frames')
 restore=[]
 long_case=any(c>=127 for c in checkpoints)
 if long_case:
  # Every L130 path reaches restore/replay at cursor128 before any possible EOS at130.
  # Missing proof is evidence failure, independent of cursor131 branch coverage.
  for original,label,cursor in [('c127-draft','restore-127',127),('c128-draft','replay-128',128)]:
   a=candidate/original;b=candidate/label
   for directory in (a,b):
    need(directory.is_dir() and (directory/'draft.json').is_file(),'required L130 restore/replay metadata')
    meta=load(directory/'draft.json');need(type(meta['cursor'])is int and meta['cursor']==cursor,'restore/replay actual cursor')
    need(type(meta['owner'])is int and meta['owner']>0 and type(meta['epoch'])is int and meta['epoch']>0 and type(meta['prior'])is int and 0<=meta['prior']<129280,'restore/replay required metadata')
    need(len(meta['fields'])==4 and {f['name'] for f in meta['fields']}=={'features','ring0','ring1','ring2'} and all(f['scalar']==2 for f in meta['fields']),'restore/replay actual four buffer metadata')
   restore.append(draft(a,b,True))
  a=candidate/'proposal-128-before';b=candidate/'proposal-128-after'
  names={'ids.json','confidence.bin'}|{'q-'+str(i)+'.bin'for i in range(5)}
  for directory in (a,b):
   need(directory.is_dir() and {p.name for p in directory.iterdir()}==names,'required L130 five-row proposal fullset')
   ids=load(directory/'ids.json');need(type(ids)is list and len(ids)==5 and all(type(i)is int and 0<=i<129280 for i in ids),'proposal actual five IDs')
   confidence=(directory/'confidence.bin').read_bytes();need(len(confidence)==20 and all(_finite_math.isfinite(x[0])for x in struct.iter_unpack('<f',confidence)),'proposal actual five confidence values')
   for i in range(5):
    q=(directory/('q-'+str(i)+'.bin')).read_bytes();need(len(q)==129280*8 and all(_finite_math.isfinite(x[0])for x in struct.iter_unpack('<d',q)),'proposal actual five full vocabulary rows')
  for name in sorted(names):records.append(exact(a/name,b/name))
 trace=None
 if (candidate/'trace/trace.json').exists():
  old=list(sys.path);sys.path.insert(0,str(numeric));saved=sys.modules.pop('validator',None)
  try:
   sp=importlib.util.spec_from_file_location('global_trace',numeric/'actual_trace.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);trace=m.replay(load(candidate/'trace/trace.json'),candidate/'trace')
  finally:
   sys.path[:]=old;sys.modules.pop('validator',None)
   if saved is not None:sys.modules['validator']=saved
 required_reached=bool(trace['branch_complete']) if trace is not None else set(checkpoints)=={127,128,129,130,131}
 return dict(schema='T38-global-saved-comparison-v1',status='exact' if required_reached else 'exact_but_required_branch_unreached',numerical_comparison_exact=True,required_branch_reached=required_reached,unreached_reasons=[] if required_reached else [trace.get('branch_incomplete_reason') or 'Required trace branch not reached; valid terminal is not global completion'] if trace is not None else ['L130 EOS prevents cursor131; valid terminal is not global completion'],selected_cursors=checkpoints,typed_pairs=len(records),route_pairs=len(routes),draft_valid_math=math,restore_full_math=restore,trace=trace,model_independent_Q_extended=False,sampler_bit_qualified=False,GPU_started=False)

def global_cpu_run(a):
 import ast
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);helper=a.toolchain_helper.resolve();tree=ast.parse(helper.read_text(encoding='utf8'));fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name=='environment');shared=pathlib.Path(r'C:/Develop/AI/StrataMod');ns=dict(os=os,SHARED=shared,SDK=shared/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel',BUILD=out);exec(compile(ast.Module(body=[fn],type_ignores=[]),str(helper),'exec'),ns);tools,env=ns['environment']()
 src=HERE;cmake=out/'cmake';commands=[]
 for cmd,name in [([tools['cmake'],'-S',src,'-B',cmake,'-G','Ninja',f'-DCMAKE_CXX_COMPILER={tools["clang"].as_posix()}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}','-DCMAKE_BUILD_TYPE=Release','-DT38_GLOBAL_CPU_TEST=ON',f'-DT38_GLOBAL_TEST_SOURCE={a.global_test_source.resolve().as_posix()}'],'configure'),([tools['cmake'],'--build',cmake,'--parallel','1','--verbose'],'build'),([cmake/'t38_global_cpu.exe'],'CPU'),([sys.executable,'-E','-s','-B','-X','utf8',a.python_tests.resolve()],'python')]:
  result=run(cmd,env,out/(name+'.log'));commands.append(result)
  if result['exit_code']:write(out/'verification.json',dict(status='failed',commands=commands,native_GPU=False));return 1
 write(out/'verification.json',dict(status='pass',commands=commands,sourceCPU_only=True,GPU=False,legacy1971_rerun=False));return 0

def main():
 if '--global-compare' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--global-compare',action='store_true');ap.add_argument('--G',type=pathlib.Path,required=True);ap.add_argument('--numeric-dir',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
  try:result=global_compare(a.G,a.numeric_dir);write(a.out/'comparison.json',result);return 0
  except Exception as e:write(a.out/'comparison.json',dict(status='evidence_failure',error=repr(e),GPU_started=False));return 1
 if '--global-cpu' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--global-cpu',action='store_true');ap.add_argument('--global-test-source',type=pathlib.Path,required=True);ap.add_argument('--python-tests',type=pathlib.Path,required=True);ap.add_argument('--toolchain-helper',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);return global_cpu_run(ap.parse_args())

 if '--normal-actor-cpu' in sys.argv or '--normal-ack-cpu' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--normal-actor-cpu',action='store_true');ap.add_argument('--normal-ack-cpu',action='store_true');ap.add_argument('--out',type=pathlib.Path,required=True);ap.add_argument('--seed-toolchain-helper',type=pathlib.Path,required=True);ap.add_argument('--normal-extract-dir',type=pathlib.Path);a=ap.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
  helper=a.seed_toolchain_helper.resolve();spec=importlib.util.spec_from_file_location('t38_normal_CPU_toolchain',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);tools,env=m.toolchain(out)
  root=HERE.parents[3];sources=sorted(p for p in root.rglob('*')if p.is_file())+[helper]
  if a.normal_extract_dir:sources+=sorted(p for p in a.normal_extract_dir.resolve().iterdir()if p.is_file()and p.suffix in ['.hpp','.inc','.json'])
  before=[dict(path=str(p),sha256=sha(p))for p in sources];configure=[tools['cmake'],'-S',HERE,'-B',out/'cmake','-G','Ninja',f'-DCMAKE_CXX_COMPILER={tools["compiler"]}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"]}','-DT38_NORMAL_ACTOR_CPU_TEST=ON']
  if a.normal_extract_dir:configure+=['-DT38_NORMAL_EXTRACT_DIR='+str(a.normal_extract_dir.resolve())]
  commands=[configure,[tools['cmake'],'--build',out/'cmake','--verbose'],[out/'cmake/t38_normal_actor_cpu.exe','normal-ack-selftest'if a.normal_ack_cpu else'normal-actor-selftest']];expected=[0,0,0]
  if a.normal_extract_dir and not a.normal_ack_cpu:commands.append([out/'cmake/t38_normal_actor_cpu.exe','normal-host-terminate']);expected.append(73)
  records=[]
  for n,cmd in enumerate(commands):
   result=run(cmd,env,out/f'CPU-{n}.log');result['expected_exit']=expected[n];records.append(result)
   if result['exit_code']!=expected[n]:break
  same=all(sha(x['path'])==x['sha256']for x in before);success=len(records)==len(commands)and all(x['exit_code']==x['expected_exit']for x in records)and same
  write(out/'verification.json',dict(success=success,sources=before,tools=[dict(role=k,path=str(v),sha256=sha(v))for k,v in tools.items()],commands=records,sources_unchanged=same,actual_RequestActor=not a.normal_ack_cpu,actual_producer_ACK_extract=a.normal_ack_cpu,CPU_spies_only=True,normal_native_executed=False,model_body_read=False,expected_binary_read=False,GPU=False))
  return 0 if success else 1
 if '--actor-compare' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--actor-compare',action='store_true');ap.add_argument('--actor-input',type=pathlib.Path,required=True);ap.add_argument('--actor-q-manifest',type=pathlib.Path,required=True);ap.add_argument('--actor-q-seal',type=pathlib.Path,required=True);ap.add_argument('--actor-q-seal-sha',required=True);ap.add_argument('--actor-G',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args()
  try:result=actor_compare(a.actor_input,a.actor_q_manifest,a.actor_q_seal,a.actor_q_seal_sha,a.actor_G)
  except (ValueError,KeyError,OSError,TypeError)as e:result=dict(success=False,evidence_error=str(e),GPU_started_by_comparer=False,expected_updated=False)
  with a.out.open('x',encoding='utf-8')as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
  return 0 if result['success']else 1
 if '--proposal-compare' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--proposal-compare',action='store_true');ap.add_argument('--proposal-input',type=pathlib.Path,required=True);ap.add_argument('--proposal-q-manifest',type=pathlib.Path,required=True);ap.add_argument('--proposal-q-seal',type=pathlib.Path,required=True);ap.add_argument('--proposal-q-seal-sha',required=True);ap.add_argument('--proposal-G',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args()
  try:result=proposal_compare(a.proposal_input,a.proposal_q_manifest,a.proposal_q_seal,a.proposal_q_seal_sha,a.proposal_G)
  except (ValueError,KeyError,OSError,TypeError)as e:result=dict(success=False,evidence_error=str(e),GPU_started_by_comparer=False,expected_updated=False)
  with a.out.open('x',encoding='utf-8')as f:json.dump(result,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
  return 0 if result['success']else 1
 if '--seed-compare' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--seed-compare',action='store_true');ap.add_argument('--seed-input',type=pathlib.Path,required=True);ap.add_argument('--seed-q-manifest',type=pathlib.Path,required=True);ap.add_argument('--seed-q-seal',type=pathlib.Path,required=True);ap.add_argument('--seed-q-seal-sha',required=True);ap.add_argument('--seed-G',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args()
  if a.out.exists():raise ValueError('create-only comparison output')
  try:result=seed_compare(a.seed_input,a.seed_q_manifest,a.seed_q_seal,a.seed_q_seal_sha,a.seed_G)
  except (ValueError,KeyError,OSError,TypeError)as e:result=dict(success=False,evidence_error=str(e),GPU_started_by_comparer=False,expected_updated=False)
  with a.out.open('x',encoding='utf-8')as f:json.dump(result,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
  return 0 if result['success']else 1
 if '--seed-body-cpu' in sys.argv or '--proposal-body-cpu' in sys.argv or '--actor-body-cpu' in sys.argv:
  ap=argparse.ArgumentParser();ap.add_argument('--seed-body-cpu',action='store_true');ap.add_argument('--proposal-body-cpu',action='store_true');ap.add_argument('--actor-body-cpu',action='store_true');ap.add_argument('--out',type=pathlib.Path,required=True);ap.add_argument('--seed-test-source',type=pathlib.Path,required=True);ap.add_argument('--seed-toolchain-helper',type=pathlib.Path,required=True);a=ap.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
  helper=a.seed_toolchain_helper.resolve();test=a.seed_test_source.resolve();spec=importlib.util.spec_from_file_location('t38_seed_CPU_toolchain',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);tools,env=m.toolchain(out)
  sources=[HERE/n for n in ['fixture.cpp','build_verify.py','CMakeLists.txt']]+[test,helper];before=[dict(path=str(p),sha256=sha(p)) for p in sources]
  flag='T38_ACTOR_BODY_CPU_TEST'if a.actor_body_cpu else'T38_PROPOSAL_BODY_CPU_TEST'if a.proposal_body_cpu else'T38_SEED_BODY_CPU_TEST';var='T38_ACTOR_TEST_SOURCE'if a.actor_body_cpu else'T38_PROPOSAL_TEST_SOURCE'if a.proposal_body_cpu else'T38_SEED_TEST_SOURCE';exe='t38_actor_body_cpu.exe'if a.actor_body_cpu else't38_proposal_body_cpu.exe'if a.proposal_body_cpu else't38_seed_body_cpu.exe'
  commands=[[tools['cmake'],'-S',HERE,'-B',out/'cmake','-G','Ninja',f'-DCMAKE_CXX_COMPILER={tools["compiler"]}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"]}',f'-D{flag}=ON',f'-D{var}={test}'],[tools['cmake'],'--build',out/'cmake','--verbose'],[out/'cmake'/exe]];records=[]
  for n,cmd in enumerate(commands):
   result=run(cmd,env,out/f'CPU-{n}.log');records.append(result)
   if result['exit_code']:break
  same=all(sha(r['path'])==r['sha256']for r in before);success=len(records)==3 and all(r['exit_code']==0 for r in records)and same
  write(out/'verification.json',dict(success=success,sources=before,tools=[dict(role=k,path=str(v),sha256=sha(v))for k,v in tools.items()],python=dict(path=sys.executable,sha256=sha(sys.executable)),commands=records,sources_unchanged=same,CPU_host_mock_only=True,actual_Network_called=False,model_body_read=False,Q_generated=False,GPU=False))
  return 0 if success else 1
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=pathlib.Path,required=True);ap.add_argument('--hip-compile',action='store_true');ap.add_argument('--sampling',action='store_true');ap.add_argument('--source-root',type=pathlib.Path);a=ap.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
 helper=EXT/'tests/native/build_verify.py';spec=importlib.util.spec_from_file_location('t38_toolchain',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 tools,env=m.toolchain(out)
 source_ext=a.source_root.resolve() if a.source_root else EXT;source_here=source_ext/'tests/dspark/t38'
 names=['draft_asset.hpp','draft_asset.cpp','draft.hpp','session.hpp','session.cpp','target_adapter.hpp']
 source=[source_ext/'models/deepseek41/dspark'/n for n in names]+[source_here/n for n in ['reference.py','test_session.py','test_asset.py','fixture.cpp','build_verify.py','CMakeLists.txt']]
 source+=[source_ext/'models/deepseek41/dspark/draft.hip'] if (source_ext/'models/deepseek41/dspark/draft.hip').exists() else []
 if a.sampling:source += [source_ext/'models/deepseek41/sampling.hpp',source_ext/'models/deepseek41/sampling.cpp']
 before=[]
 for p in source:
  target=out/'source/Strata-extensions'/p.relative_to(source_ext);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);before.append(dict(path=str(p),sha256=sha(p),snapshot=str(target),snapshot_sha256=sha(target)))
 tool_records=[dict(role=k,path=str(p),sha256=sha(p)) for k,p in tools.items()]
 tool_records.append(dict(role='python',path=sys.executable,sha256=sha(sys.executable)))
 input_paths=[WORK/'build-deepseek-t37/reference-source/luce-draft.prefix.bin',WORK/'build-deepseek-t37/reference-source/luce-draft-header.json',WORK/'build-deepseek-t37/artifact-receipt.json',WORK/'build-deepseek-t46/native-union-build-r4/build.json',WORK/'build-deepseek-t46/native-union-build-r4/cmake/declared-sources.tsv']
 inputs=[dict(path=str(p),sha256=sha(p)) for p in input_paths]
 receipt=json.loads((WORK/'build-deepseek-t37/artifact-receipt.json').read_text(encoding='utf-8'))
 artifact=pathlib.Path(receipt['file']['path'])
 def identity():
  s=artifact.stat();return dict(path=str(artifact),device=s.st_dev,inode=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns)
 artifact_before=identity()
 if artifact_before['bytes']!=7965746848:raise ValueError('artifact stat')
 if pathlib.Path(str(artifact)+'.part').exists() or pathlib.Path(str(artifact)+'.part.lock').exists():raise ValueError('unfinished artifact writer')
 write(out/'before.json',dict(scope='CPU adapter only; no effective-sampler/Core API or real draft network',source=before,inputs=inputs,artifact_before_stat=artifact_before,artifact_full_rehash=False,tools=tool_records,controller=dict(path=str(pathlib.Path(__file__)),sha256=sha(__file__)),toolchain_helper=dict(path=str(helper),sha256=sha(helper))))
 cmake=out/'cmake';src=out/'source/Strata-extensions/tests/dspark/t38'
 commands=[[tools['cmake'],'-S',src,'-B',cmake,'-G','Ninja',f'-DCMAKE_CXX_COMPILER={tools["compiler"]}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"]}'],[tools['cmake'],'--build',cmake,'--verbose']]
 if a.sampling:
  legacy=out/'legacy/t38_legacy';legacy.mkdir(parents=True)
  parent=WORK/'build-deepseek-t46/native-union-build-r4/source/Strata-extensions/models/deepseek41'
  for name in ['sampling.hpp','sampling.cpp']:
   text=(parent/name).read_text(encoding='utf-8').replace('namespace strata_ext::deepseek41','namespace t38_legacy')
   (legacy/name).write_text(text,encoding='utf-8')
  write(out/'legacy-oracle.json',[dict(path=str(parent/name),sha256=sha(parent/name),derived=str(legacy/name),derived_sha256=sha(legacy/name),transform='namespace rename only') for name in ['sampling.hpp','sampling.cpp']])
  commands[0]+=['-DT38_SHARED_SAMPLING=ON','-DT38_SAMPLING_DIR='+str(out/'source/Strata-extensions/models/deepseek41'),'-DT38_LEGACY_DIR='+str(out/'legacy')]
 records=[]
 for i,cmd in enumerate(commands):
  r=run(cmd,env,out/f'build-{i}.log');records.append(r)
  if r['exit_code']:write(out/'verification.json',dict(status='build_failed',commands=records,GPU=False,network=False));return 1
 exe=cmake/'t38_cpu.exe';env=env.copy();env['T38_EXE']=str(exe);env['T38_WORK_ROOT']=str(WORK);env['PYTHONDONTWRITEBYTECODE']='1'
 tests=run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s',src,'-p','test_*.py'],env,out/'tests.log');records.append(tests)
 if a.sampling:
  sr=run([cmake/'t38_sampler.exe','sampler-selftest'],env,out/'sampling-tests.log');records.append(sr)
  if sr['exit_code']:write(out/'verification.json',dict(status='sampling_failed',commands=records,GPU=False));return 1
 hip_record=None
 if a.hip_compile:
  sdk=pathlib.Path(r'C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel')
  clang=sdk/'lib/llvm/bin/clang++.exe';baseline=WORK/'build-deepseek-t46/native-union-build-r4/source'
  hip_source=out/'source/Strata-extensions/models/deepseek41/dspark/draft.hip';obj=out/'draft-ops.obj';deps=out/'draft-ops.d'
  command=[clang,f'--rocm-path={sdk}',f'--rocm-device-lib-path={sdk}/lib/llvm/amdgcn/bitcode','--offload-arch=gfx1100','--offload-arch=gfx1201','-O3','-std=gnu++17','-fno-fast-math','-ffp-contract=off','-fdenormal-fp-math=ieee','-D__HIP_PLATFORM_AMD__=1','-D__HIP_ROCclr__=1','-DNOMINMAX','-DWIN32_LEAN_AND_MEAN','-D_DLL','-D_MT','-Xclang','--dependent-lib=msvcrt','-I'+str(baseline/'Strata-extensions/models/deepseek41'),'-I'+str(baseline/'Strata-extensions/native/stats'),'-I'+str(baseline/'Strata-extensions/native/io'),'-I'+str(baseline/'Strata-extensions/native/cache'),'-I'+str(baseline/'include/strata/hip_compat'),'-I'+str(baseline/'include'),'-isystem',sdk/'include','-MD','-MF',deps,'-x','hip','-c',hip_source,'-o',obj]
  hr=run(command,env,out/'hip-compile.log');records.append(hr)
  if hr['exit_code']:
   write(out/'verification.json',dict(status='hip_compile_failed',commands=records,GPU=False,real_network=False));return 1
  dependencies=[]
  for line in deps.read_text(encoding='utf-8').replace('\\\n',' ').splitlines():
   for token in line.split():
    p=pathlib.Path(token)
    if p.is_file():dependencies.append(dict(path=str(p),sha256=sha(p)))
  hip_record=dict(compiler=dict(path=str(clang),sha256=sha(clang)),object=dict(path=str(obj),sha256=sha(obj)),dependency_file=dict(path=str(deps),sha256=sha(deps)),dependencies=dependencies,architectures=['gfx1100','gfx1201'],compile_only=True,GPU_executed=False)
 same=all(sha(r['path'])==r['sha256'] for r in before+inputs) and identity()==artifact_before
 write(out/'verification.json',dict(status='pass' if tests['exit_code']==0 and same else 'failed',scope='bounded CPU asset/schema+supplied-distribution acceptance+fake-target transaction adapter; optional HIP primitives compile only',commands=records,HIP=hip_record,source_and_input_unchanged=same,artifact_after_stat=identity(),executable=dict(path=str(exe),sha256=sha(exe)),GPU=False,noGEN=False,real_draft_network=False,shared_API_applied=False,normal_DSpark=False,performance_qualified=False,asset_full_hash=False))
 return 0 if tests['exit_code']==0 and same else 1
if __name__=='__main__':raise SystemExit(main())







