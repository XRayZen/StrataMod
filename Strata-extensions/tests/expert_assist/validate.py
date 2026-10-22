"""Strict T44 fixture comparison; expectations are independent and sealed before G."""
from pathlib import Path
import collections,hashlib,json,re

def need(ok,message):
 if not ok:raise ValueError(message)
def integer(x):
 need(type(x)is int and x>=0,'strict nonnegative integer');return x
def exact(actual,expected,label):
 need(type(actual)is type(expected),label+' type')
 if isinstance(expected,dict):
  need(set(actual)==set(expected),label+' fields')
  for k,v in expected.items():exact(actual[k],v,label+'.'+k)
 elif isinstance(expected,list):
  need(len(actual)==len(expected),label+' length')
  for a,b in zip(actual,expected):exact(a,b,label)
 else:need(actual==expected,label+' value')
def number(x):
 need(re.fullmatch(r'-?(?:0|[1-9][0-9]*)',x)is not None,'integer TSV spelling');return int(x)
def table(path):return [x.split('\t')for x in Path(path).read_text(encoding='utf-8').splitlines()]
def stats(path):
 result={}
 for row in table(path):
  need(row[0]not in result,'duplicate statistic');result[row[0]]=[number(x)for x in row[1:]]
 return result
def checked(record):
 p=Path(record['path']);raw=p.read_bytes();need(len(raw)==record['bytes']and hashlib.sha256(raw).hexdigest()==record['sha256'],'sealed expectation changed');return raw

def transfer_rows(path):
 rows=[]
 for r in table(path):
  need(len(r)==21,'transfer shape')
  rows.append(dict(request=r[0],epoch=number(r[1]),position=number(r[2]),layer=number(r[3]),expert=number(r[4]),slot=number(r[5]),generation=number(r[6]),direction=r[7],bytes=number(r[8]),path=r[9],peer=number(r[10]),d2h=number(r[11]),h2d=number(r[12]),capability=number(r[13]),can=number(r[14]),enable=number(r[15]),copy=number(r[16]),disable=number(r[17]),record=number(r[18]),drain=number(r[19]),cancelled=number(r[20])))
 return rows

def validate_transfers(rows,policy):
 totals=[0,0,0];keys=set()
 for x in rows:
  for field in ('epoch','position','layer','expert','slot','generation','bytes','peer','d2h','h2d'):integer(x[field])
  need(x['bytes']>0 and x['generation']>0 and x['direction']in('input','route','down'),'copy extent/key')
  key=tuple(x[k]for k in ('request','epoch','position','layer','expert','slot','generation','direction'));need(key not in keys,'duplicate transfer');keys.add(key)
  for field in ('capability','can','enable','copy','disable','record','drain','cancelled'):need(type(x[field])is int,'strict status integer')
  need(x['cancelled']in(0,1),'cancel flag');need(x['record']==0 and x['drain']==-1,'actual last-use event status')
  if policy=='bounce':exact([x[k]for k in ('capability','can','enable','copy','disable')],[-1]*5,'forced peer unattempted')
  else:
   if x['capability']==0:
    need(x['can']in(0,1),'peer capability value')
    if x['can']==0:exact([x[k]for k in ('enable','copy','disable')],[-1]*3,'unattempted inaccessible peer')
    elif x['enable']in(0,704):
     need(x['copy']>=0,'enabled peer copy attempted');need(x['disable']==(0 if x['enable']==0 else -1),'only owned enable disabled')
    else:need(x['enable']>0 and x['copy']==-1 and x['disable']==-1,'enable failure fallback')
   else:need(x['capability']>0 and [x[k]for k in ('can','enable','copy','disable')]==[-1]*4,'failed query unknown')
  if x['path']=='peer':
   need(policy=='auto' and x['capability']==0 and x['can']==1 and x['enable']in(0,704)and x['copy']==0,'actual peer path');exact([x['peer'],x['d2h'],x['h2d']],[x['bytes'],0,0],'peer traffic')
  else:
   need(x['path']=='host-bounce','actual bounce path');exact([x['peer'],x['d2h'],x['h2d']],[0,x['bytes'],x['bytes']],'bounce traffic');need(policy=='bounce'or x['copy']!=0,'peer successful cannot bounce')
  for i,k in enumerate(('peer','d2h','h2d')):totals[i]+=x[k]
 return totals

def validate_events(path):
 rows=table(path);groups=collections.defaultdict(list)
 for sequence,r in enumerate(rows):
  need(len(r)==9 and number(r[0])==sequence,'ordered event trace')
  key=(r[1],number(r[2]),number(r[3]),number(r[4]),number(r[5]),number(r[6]),number(r[7]));groups[key].append(r[8])
 for key,names in groups.items():
  need(names[0]=='reserved','reservation precedes visibility')
  if 'adopted'in names:
   need('return-ready'in names and names.index('return-ready')<names.index('adopted'),'ready before adoption')
  if 'retired'in names:need(names[-1]=='retired' and 'last-use-complete'in names,'actual last-use before retirement')
  if 'secondary-compute-begin'in names:need('input-ready'in names and names.index('input-ready')<names.index('secondary-compute-begin'),'copy before compute')
 return groups

def common(s,slots):
 need(set(s)>=set(('jobs','payload','actual_transfer','owned','secondary_weight','secondary_hits','secondary_host','snapshot_d2d_issued')),'stat coverage')
 for fields in s.values():
  for x in fields:integer(x)
 exact(s['owned'],[slots*8*(5120+1+5120)*4,slots*8*(5120+1+5120+5120+4*2304+5120)*4,2*2097152+512,slots*8*5120*4],'actual simultaneous requested storage')
 host=s['secondary_host'];need(len(host)==5 and host[3]in(0,1)and host[4]in(0,1),'host observed metadata')
 need(host[0]>=2*2097152+2*65536 and host[1]>0,'explicit host and metadata subset');need(host[2]<=4*2097152,'pinned subset bound')

def pinned(path,s):
 rows=table(path);need(len(rows)==4,'four observed pinned stages');subset=0;known=True;observed=True;owned=0;addresses=set()
 for r in rows:
  need(len(r)==5,'stage attributes');address,capacity,attempted,status,kind=map(number,r);need(attempted in(0,1),'attempted flag')
  if attempted:
   need(address>0 and address not in addresses and capacity==2097152,'observed actual stage extent');addresses.add(address);owned+=capacity
   if status==0:
    need(kind>=0,'successful attribute type')
    if kind==1:subset+=capacity
   else:need(status>0 and kind==-1,'failed query unknown');known=False
   observed=observed and status==0 and kind==1
  else:need([address,capacity,status,kind]==[0,0,-1,-1],'unattempted stage');observed=False
 exact(s['secondary_host'][2:],[subset,int(known),int(observed)],'stage-derived pinned subset/flags');exact(s['secondary_host'][0],4194304+131072+owned,'actual host payload accounting')

def micro_event_expectation(slots):
 remote=['reserved','snapshot-ready','input-ready','secondary-compute-begin','secondary-compute-complete','return-ready']
 local=['reserved','primary-local-enqueued','snapshot-ready','primary-local-complete','return-ready']
 return [remote+['last-use-complete','retired'],local+['last-use-complete','retired'],['reserved','cancel-retired'],remote+['last-use-complete','retired'],['reserved','snapshot-ready','input-ready','cancel-retired'],remote+['last-use-complete','retired'],remote+['cancel-retired'],remote+['last-use-complete','retired'],remote+['cancel-retired'],remote+['last-use-complete','retired']]

def micro_trace(groups,rows,batch,slots,main,fresh):
 need(len(groups)==10,'all main/shutdown/fresh jobs present');ordered=list(groups.items());names=micro_event_expectation(slots);experts=[38,155,155,38,38,38,38,38,38,38];expected_copy={};main_keys=set();fresh_keys=set()
 for i,((key,actual),expected)in enumerate(zip(ordered,names,strict=True)):
  request,epoch,position,layer,expert,slot,generation=key
  need(request==('T44-micro-fresh'if i==9 else'T44-micro')and epoch==1 and position==0 and layer==0 and expert==experts[i],'original micro request/expert/call order')
  expected_slot=1 if slots==2 and i==1 else 0
  expected_generation=1 if i==9 or slots==2 and i==1 else i if slots==2 and i>1 else i+1
  need(slot==expected_slot and generation==expected_generation,'actual slot generation continuity')
  exact(actual,expected,'micro actual event sequence')
  if i<8:main_keys.add(key)
  if i==9:fresh_keys.add(key)
  directions=[]if i in(1,2)else['input','route']if i==4 else['input','route','down']
  for direction in directions:expected_copy[key+(direction,)]=batch*(4 if direction=='route'else 20480)
 seen={};totals_main=[0,0,0];totals_fresh=[0,0,0]
 for row in rows:
  key=tuple(row[k]for k in('request','epoch','position','layer','expert','slot','generation'));copy=key+(row['direction'],)
  need(copy in expected_copy and copy not in seen and row['bytes']==expected_copy[copy],'original job/copy event binding');seen[copy]=row['bytes']
  target=totals_main if key in main_keys else totals_fresh if key in fresh_keys else None
  if target is not None:
   for j,name in enumerate(('peer','d2h','h2d')):target[j]+=row[name]
 need(set(seen)==set(expected_copy),'all per-job transfers')
 exact(main['actual_transfer'],totals_main,'main actual transfer sum');exact(fresh['actual_transfer'],totals_fresh,'fresh actual transfer sum')

def validate_micro(directory,micro,batch,slots=2,policy='auto'):
 d=Path(directory);case=next(x for x in micro['cases']if x['batch']==batch);q={x['expert']:checked(x)for x in case['outputs']};names=['expert-38','expert-155','after-local-error','after-worker-error','cancel-readback','after-ready-cancel','fresh-after-shutdown']
 for name in names:need((d/(name+'.bin')).read_bytes()==q[155 if name=='expert-155'else 38],'micro exact '+name)
 need({p.name for p in d.glob('*.bin')}=={x+'.bin'for x in names},'micro output coverage')
 exact(stats(d/'controls.tsv'),dict(rejections=[15],positive_cases=[8]),'native controls')
 main=stats(d/'main-assist-stats.tsv');fresh=stats(d/'assist-stats.tsv');common(main,slots);common(fresh,slots);pinned(d/'main-secondary-stages.tsv',main);pinned(d/'secondary-stages.tsv',fresh)
 exact(main['jobs'],[1,5,5,3],'main jobs');exact(fresh['jobs'],[0,1,1,0],'fresh jobs')
 exact(main['payload'],[6*batch*20480,6*batch*4,5*batch*20480],'main payload');exact(fresh['payload'],[batch*20480,batch*4,batch*20480],'fresh payload')
 exact(main['snapshot_d2d_issued'],[8*batch*20484],'main snapshot issued');exact(fresh['snapshot_d2d_issued'],[batch*20484],'fresh snapshot issued')
 rows=transfer_rows(d/'transfers.tsv');need(len(rows)==23,'micro transfer coverage');counts=collections.Counter(x['direction']for x in rows);exact(dict(counts),dict(input=8,route=8,down=7),'micro directions')
 for x in rows:need(x['bytes']==batch*(4 if x['direction']=='route'else 20480),'micro actual extent')
 totals=validate_transfers(rows,policy);micro_trace(validate_events(d/'events.tsv'),rows,batch,slots,main,fresh)
 return dict(outputs=7,values=7*batch*5120,transfers=len(rows),actual_transfer=totals)

def validate_full(directory,q,policy='auto'):
 d=Path(directory);expected={(x['position'],x['layer'],x['name']):x for x in q['expected_stages']};seen=set();values=0
 for r in table(d/'stages.tsv'):
  need(len(r)==8,'stage shape');position,layer=map(number,r[:2]);key=(position,layer,r[2]);need(key in expected and key not in seen,'stage identity/coverage');seen.add(key);e=expected[key]
  shape=e['shape'];need(number(r[3])==shape[0]and number(r[4])==__import__('math').prod(shape[1:]),'logical stage shape')
  scalar=number(r[5]);need(scalar in ({4}if e['dtype']=='uint32'else{5}if e['dtype']=='int32'else{0,2}),'stage scalar encoding');raw=(d/r[7]).read_bytes();need(number(r[6])==e['bytes']==len(raw)and raw==checked(e),'full exact stage');values+=len(raw)//4
 need(seen==set(expected),'all stage coverage')
 logits={x['position']:checked(x)for x in q['outputs']if x['name']=='logits'};need((d/'prefill2-logits.bin').read_bytes()==logits[0]+logits[1]and(d/'append-logits.bin').read_bytes()==logits[2],'full exact requested logits')
 s=stats(d/'assist-stats.tsv');common(s,2);pinned(d/'secondary-stages.tsv',s);exact(s['primary_total'],[q['expected_primary_owned']],'primary total includes owners once');exact(s['jobs'],[365,355,720,0],'full jobs');exact(s['payload'],[355*20480,355*4,355*20480],'full payload');exact(s['snapshot_d2d_issued'],[720*20484],'full snapshots')
 c=q['secondary_cache'];exact(s['secondary_weight'],[c['logical_read'],c['weight_h2d'],c['issued_reads']],'secondary original cache trace');exact(s['secondary_hits'],[c['gpu_hits'],c['ram_hits'],c['ssd_misses']],'secondary hits')
 exact(s['state_positions'],[3]*40,'all state positions');exact(s['compressed'],[1,1,1,3],'published source schedule');exact(s['keys'],[1,1,1,3],'published key schedule')
 rows=transfer_rows(d/'transfers.tsv');need(len(rows)==1065,'full transfer coverage');groups=collections.defaultdict(dict)
 for x in rows:
  key=(x['position'],x['layer'],x['expert']);need(x['direction']not in groups[key],'duplicate job direction');groups[key][x['direction']]=x['bytes']
 expected_jobs={(f['position'],f['layer'],j['expert'])for f in q['frame_jobs']for j in f['canonical_jobs']if j['secondary']};need(set(groups)==expected_jobs,'secondary original route coverage')
 for value in groups.values():exact(value,dict(input=20480,route=4,down=20480),'full transfer per job')
 exact(s['actual_transfer'],validate_transfers(rows,policy),'actual transfer counters');events=validate_events(d/'events.tsv');need(len(events)==720,'all job event coverage')
 full_trace(events,q,rows)
 return dict(stages=len(seen),values=values+3*129280,transfers=len(rows),primary_jobs=365,secondary_jobs=355)

def full_trace(events,q,rows=None):
 frame_jobs={(f['position'],f['layer'],j['expert']):j['secondary']for f in q['frame_jobs']for j in f['canonical_jobs']};seen_jobs=set()
 for key,names in events.items():
  request,epoch,position,layer,expert,slot,generation=key;identity=(position,layer,expert)
  need(request=='T44-full40'and epoch==1 and identity in frame_jobs and identity not in seen_jobs and 0<=slot<2 and generation>0,'full original job identity');seen_jobs.add(identity)
  expected=micro_event_expectation(2)[0 if frame_jobs[identity]else 1];exact(names,expected,'full event lifecycle')
 need(seen_jobs==set(frame_jobs),'all primary/secondary original jobs')
 if rows is not None:
  remote_keys={key for key in events if frame_jobs[(key[2],key[3],key[4])]};seen_copies=set()
  for row in rows:
   key=tuple(row[k]for k in('request','epoch','position','layer','expert','slot','generation'));copy=key+(row['direction'],)
   need(key in remote_keys and copy not in seen_copies and row['direction']in('input','route','down'),'full transfer to exact remote lifecycle');seen_copies.add(copy)
  need(seen_copies=={key+(direction,)for key in remote_keys for direction in('input','route','down')},'full remote lifecycle copy coverage')

def self_test():
 import copy
 rejects=0;positives=0
 t=dict(request='fixed',epoch=1,position=0,layer=0,expert=38,slot=0,generation=1,direction='input',bytes=20480,path='host-bounce',peer=0,d2h=20480,h2d=20480,capability=-1,can=-1,enable=-1,copy=-1,disable=-1,record=0,drain=-1,cancelled=0)
 validate_transfers([t],'bounce');positives+=1
 def reject(f):
  nonlocal rejects
  try:f()
  except(ValueError,KeyError,TypeError):rejects+=1
  else:raise AssertionError('mutant accepted')
 for key in ('epoch','position','layer','expert','slot','generation','bytes','peer','d2h','h2d','capability','can','enable','copy','disable','record','drain','cancelled'):
  for value in (True,float(t[key])):
   x=copy.deepcopy(t);x[key]=value;reject(lambda:validate_transfers([x],'bounce'))
 for key in ('capability','can','enable','copy','disable'):
  x=dict(t);x[key]=0;reject(lambda:validate_transfers([x],'bounce'))
 for key in ('bytes','peer','d2h','h2d','record','drain','cancelled'):
  x=dict(t);x[key]=2 if key=='cancelled'else x[key]+1;reject(lambda:validate_transfers([x],'bounce'))
 reject(lambda:validate_transfers([t,t],'bounce'))
 a=dict(t,capability=0,can=0);validate_transfers([a],'auto');positives+=1
 for key in ('enable','copy','disable'):
  x=dict(a);x[key]=0;reject(lambda:validate_transfers([x],'auto'))
 p=dict(t,path='peer',peer=20480,d2h=0,h2d=0,capability=0,can=1,enable=0,copy=0,disable=0);validate_transfers([p],'auto');positives+=1
 for key in ('peer','d2h','h2d','disable'):
  x=dict(p);x[key]+=1;reject(lambda:validate_transfers([x],'auto'))
 # Exact CPU controls model strict schema/counter comparisons, never GPU values.
 expected=dict(jobs=[365,355,720,0],payload=[7270400,1420,7270400],snapshot=[14748480],owned=[655424,1900608,4194816,327680])
 exact(expected,expected,'positive expected');positives+=1
 for key,values in expected.items():
  for i in range(len(values)):
   for value in (0,values[i]+1,float(values[i]),True):
    if type(value)is int and value==values[i]:continue
    x=copy.deepcopy(expected);x[key][i]=value;reject(lambda:exact(x,expected,'counter'))
 # Build the planned ten call histories independently of any native capture.
 groups={};rows=[];epoch=1;events=micro_event_expectation(2)
 for i,names in enumerate(events):
  key=('T44-micro-fresh'if i==9 else'T44-micro',epoch,0,0,155 if i in(1,2)else 38,1 if i==1 else 0,1 if i in(1,9)else i if i>1 else 1);groups[key]=names
  for direction in ([]if i in(1,2)else['input','route']if i==4 else['input','route','down']):
   x=dict(t);x.update(dict(zip(('request','epoch','position','layer','expert','slot','generation'),key)));x['direction']=direction;x['bytes']=4 if direction=='route'else 20480;x['d2h']=x['h2d']=x['bytes'];rows.append(x)
 main={'actual_transfer':[0,6*20484+5*20480,6*20484+5*20480]};fresh={'actual_transfer':[0,40964,40964]}
 micro_trace(groups,rows,1,2,main,fresh);positives+=1
 for owner in ('main','fresh'):
  for index in range(3):
   for value in(0,1,999999,float((main if owner=='main'else fresh)['actual_transfer'][index])):
    if type(value)is int and value==(main if owner=='main'else fresh)['actual_transfer'][index]:continue
    a=copy.deepcopy(main);b=copy.deepcopy(fresh);(a if owner=='main'else b)['actual_transfer'][index]=value;reject(lambda:micro_trace(groups,rows,1,2,a,b))
 reject(lambda:micro_trace({},rows,1,2,main,fresh))
 for axis in (0,1,2,3,4,5,6):
  damaged=copy.deepcopy(groups);key=next(iter(damaged));value=damaged.pop(key);wrong=list(key);wrong[axis]='wrong'if axis==0 else wrong[axis]+1;damaged[tuple(wrong)]=value;reject(lambda:micro_trace(damaged,rows,1,2,main,fresh))
 for key in groups:
  damaged=copy.deepcopy(groups);damaged[key]=damaged[key][:-1];reject(lambda:micro_trace(damaged,rows,1,2,main,fresh))
  damaged=copy.deepcopy(groups);damaged.pop(key);reject(lambda:micro_trace(damaged,rows,1,2,main,fresh))
 reject(lambda:micro_trace(groups,rows[:-1],1,2,main,fresh));reject(lambda:micro_trace(groups,rows+[rows[0]],1,2,main,fresh))
 q=json.loads((Path(__file__).resolve().parents[3]/'build-deepseek-t44/expected-Q.json').read_text(encoding='utf-8'));full={}
 for f in q['frame_jobs']:
  for j in f['canonical_jobs']:
   key=('T44-full40',1,f['position'],f['layer'],j['expert'],0,len(full)+1);full[key]=micro_event_expectation(2)[0 if j['secondary']else 1]
 fullrows=[]
 for key in full:
  if key[4]%2==0:
   for direction in('input','route','down'):
    r=dict(t);r.update(dict(zip(('request','epoch','position','layer','expert','slot','generation'),key)));r['direction']=direction;fullrows.append(r)
 full_trace(full,q,fullrows);positives+=1
 for field in('request','epoch','slot','generation'):
  damaged=copy.deepcopy(fullrows);damaged[0][field]='wrong'if field=='request'else damaged[0][field]+1;reject(lambda:full_trace(full,q,damaged))
 reject(lambda:full_trace({},q))
 for axis,value in((5,-1),(6,0)):
  damaged=copy.deepcopy(full);key=next(iter(damaged));names=damaged.pop(key);bad=list(key);bad[axis]=value;damaged[tuple(bad)]=names;reject(lambda:full_trace(damaged,q))
 for selected in (next(k for k in full if k[4]%2==0),next(k for k in full if k[4]%2==1)):
  damaged=copy.deepcopy(full);damaged[selected]=['reserved'];reject(lambda:full_trace(damaged,q))
  damaged=copy.deepcopy(full);damaged[selected]=damaged[selected][:-1];reject(lambda:full_trace(damaged,q))
  damaged=copy.deepcopy(full);damaged.pop(selected);reject(lambda:full_trace(damaged,q))
 damaged={(k[0],0,*k[2:]):v for k,v in full.items()};reject(lambda:full_trace(damaged,q))
 return dict(positive_checks=positives,rejected_mutants=rejects,GPU_used=False,independent_driver_fault=False)
