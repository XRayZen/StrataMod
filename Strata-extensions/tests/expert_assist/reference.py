"""Independent placement/accounting expectation, reusing immutable accepted Q.
No candidate executor or GPU output is imported. No model math is duplicated.
"""
from pathlib import Path
import hashlib,json,struct
FIXED_Q='afef342a7a9410fb5202f9c86bcf4e95ba0b5f8f7d9965ac5d6017879039bb0c'
def integer(v,positive=False):
 if type(v)is not int or v<0 or positive and not v:raise ValueError('nonnegative integer')
 return v
def assignment(values):
 result=set()
 for v in values:
  integer(v)
  if v>=384 or v in result:raise ValueError('expert assignment')
  result.add(v)
 return frozenset(result)
def jobs(ids,secondary):
 secondary=assignment(secondary);group={}
 for token,row in enumerate(ids):
  if len(row)!=6:raise ValueError('top6 retained')
  selected=assignment(row)
  if len(selected)!=6:raise ValueError('duplicate route')
  for slot,expert in enumerate(row):group.setdefault(expert,[]).append([token,slot])
 return [dict(expert=e,pairs=group[e],secondary=e in secondary)for e in sorted(group)]
def canonical_results(expected,returned):
 if len(expected)!=len(set(expected))or len(returned)!=len(set(returned))or set(returned)!=set(expected):raise ValueError('result identity/coverage')
 return list(expected)
def reusable(**events):
 if set(events)!={'input_complete','compute_complete','return_complete','consumed','last_use_complete'}or any(type(v)is not bool for v in events.values()):raise ValueError('event states')
 return all(events.values())
def capacity(batch,slots):
 integer(batch,True);integer(slots,True)
 align=lambda x:(x+255)//256*256
 # input,route,QDQ,gate,up,hidden,downQDQ,downDot,returnedDown.
 sizes=[batch*5120*4,batch*4,batch*5120*4]+[batch*2304*4]*4+[batch*5120*4]*2
 return dict(batch=batch,slots=slots,secondary_workspace=sum(map(align,sizes))*slots,primary_job_storage=sum(map(align,[batch*5120*4,batch*4,batch*5120*4]))*slots,bounce_host=batch*5120*4*slots,driver_private_bytes=None)
def payload_bytes(calls,batch):
 integer(calls);integer(batch,True);x=calls*batch*5120*4;r=calls*batch*4
 return dict(input=x,route=r,down=x,total=x+r+x)
def checked(record):
 p=Path(record['path']);raw=p.read_bytes()
 if len(raw)!=record['bytes']or hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('immutable Q record '+str(p))
 return raw
def fixed_reference(manifest):
 manifest=Path(manifest);raw=manifest.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=FIXED_Q:raise ValueError('accepted immutable Q identity')
 q=json.loads(raw);counts=[[0,0]for _ in range(40)];frames=[];records=[]
 if q['tokens']!=[3,37,1024]or len(q['frames'])!=120:raise ValueError('full TF source')
 for f in q['frames']:
  position=f['position'];layer=f['layer'];integer(position);integer(layer)
  if position>=3 or layer>=40:raise ValueError('frame geometry')
  stages={s['name']:s for s in f['stages']}
  record=stages['ffn_router_ids'];raw=checked(record)
  if record['dtype']!='uint32'or record['shape']!=[1,6]or len(raw)!=24:raise ValueError('router original geometry')
  ids=list(struct.unpack('<6I',raw));plan=jobs([ids],range(0,384,2))
  for job in plan:counts[layer][int(job['secondary'])]+=1
  frames.append(dict(position=position,layer=layer,canonical_jobs=plan))
  # Preserve exact per-stage Q binding rather than copy hundreds of payloads.
  for stage in f['stages']:
   checked(stage);records.append(dict(position=position,layer=layer,**stage))
 result=dict(schema='strata-t44-independent-expectation/v1',Q_manifest=dict(path=str(manifest.resolve()),bytes=manifest.stat().st_size,sha256=FIXED_Q),tokens=q['tokens'],frames=len(frames),frame_jobs=frames,primary_calls=sum(x[0]for x in counts),secondary_calls=sum(x[1]for x in counts),per_layer=counts,all40_both_roles=all(a>0 and b>0 for a,b in counts),transfer=payload_bytes(sum(x[1]for x in counts),1),expected_stages=records,outputs=q['outputs'],source_reads_bound_by='Q_manifest source_reads; no duplicate table',candidate_GPU_used=False)
 result['secondary_cache']=secondary_cache(q,frames)
 result['expected_primary_owned']=q['expected_total_device_owned']
 return result

def secondary_cache(q,frames):
 record=next(x for x in q['independent_source_chain']if x['original'].replace('\\','/').endswith('tests/artifact/header-inventory.json'))
 raw=Path(record['snapshot']).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('fixed original tensor inventory')
 inventory=json.loads(raw);tensors={t['name']:(shard['index'],t) for shard in inventory['shards'] for t in shard['tensors']}
 device=[None,None];ram=[None,None];c=dict(logical_read=0,weight_h2d=0,issued_reads=0,gpu_hits=0,ram_hits=0,ssd_misses=0,projection_tiles=0)
 for f in frames:
  for job in f['canonical_jobs']:
   if not job['secondary']:continue
   for kind in ('gate','up','down'):
    name='blk.'+str(f['layer'])+'.ffn_'+kind+'_exps.weight';shard,t=tensors[name];k,n,experts=t['dims_ggml'];row=t['row_bytes'];maximum=min(256,2097152//row)
    if not maximum or experts!=384:raise ValueError('native expert row tile')
    for first in range(0,n,maximum):
     count=min(maximum,n-first);size=count*row;offset=t['absolute_offset']+(job['expert']*n+first)*row;key=(shard,offset,size,t['type_id'],k,count);c['projection_tiles']+=1
     if key in device:c['gpu_hits']+=1;continue
     target=device.index(None)if None in device else 0;device[target]=key;c['weight_h2d']+=size
     if key in ram:c['ram_hits']+=1;continue
     target=ram.index(None)if None in ram else 0;ram[target]=key;c['ssd_misses']+=1;c['logical_read']+=size
     remaining=size
     while remaining:
      delivered=min(remaining,65536-offset%4096);c['issued_reads']+=1;offset+=delivered;remaining-=delivered
 return c
