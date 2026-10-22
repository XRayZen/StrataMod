"""Pure saved-capture validation against pre-G immutable expectations."""
from pathlib import Path
import hashlib,math
from reference import checked

def need(ok,message):
 if not ok:raise ValueError(message)

def number(value):
 need(type(value)is str and value.isdecimal(),'strict native unsigned integer')
 return int(value)

def signed(value):
 need(type(value)is str and(value.isdecimal()or value.startswith('-')and value[1:].isdecimal()),'strict native signed integer')
 return int(value)

def table(path):return [line.split('\t')for line in Path(path).read_text(encoding='utf-8').splitlines()]

def stats(path):
 result={}
 for row in table(path):
  need(len(row)>1 and row[0]not in result,'unique stats key');result[row[0]]=[number(x)for x in row[1:]]
 return result

def full(directory,q,policy='auto'):
 d=Path(directory);expected={(x['position'],x['layer'],x['name']):x for x in q['expected_stages']};seen=set();values=0;files=set()
 for r in table(d/'stages.tsv'):
  need(len(r)==8,'stage fields');key=(number(r[0]),number(r[1]),r[2]);need(key in expected and key not in seen,'stage identity/coverage');seen.add(key);e=expected[key]
  need([number(r[3]),number(r[4])]==[e['shape'][0],math.prod(e['shape'][1:])],'stage logical shape');need(number(r[5])in({4}if e['dtype']=='uint32'else{5}if e['dtype']=='int32'else{0,2}),'stage scalar')
  need(r[7]==str(key[0])+'-layer'+str(key[1])+'-'+key[2]+'.bin','stage file identity');files.add(r[7]);raw=(d/r[7]).read_bytes();need(number(r[6])==e['bytes']==len(raw)and raw==checked(e),'exact stage bytes');values+=len(raw)//4
 need(seen==set(expected),'all stage coverage')
 logits={x['position']:checked(x)for x in q['outputs']if x['name']=='logits'}
 need((d/'prefill2-logits.bin').read_bytes()==logits[0]+logits[1]and(d/'append-logits.bin').read_bytes()==logits[2],'exact final requested logits');files|={'prefill2-logits.bin','append-logits.bin'}
 expected_b={(x['position'],x['name']):x for x in q['boundaries']};seen_b=set()
 for r in table(d/'boundaries.tsv'):
  need(len(r)==11,'boundary metadata fields');pos=number(r[2]);key=(pos,r[5]);need(key in expected_b and key not in seen_b,'unique required boundary');seen_b.add(key);e=expected_b[key]
  need(r[0]=='T45-full40'and number(r[1])==1 and number(r[3])==pos+1 and number(r[4])==24,'boundary source/epoch/position/generation/cut')
  need([number(r[6]),number(r[7])]==e['shape']and number(r[8])==e['scalar']and number(r[9])==e['bytes'],'boundary logical geometry/type/bytes');need(r[10]==str(pos)+'-boundary-'+r[5]+'.bin','boundary file identity');files.add(r[10]);need((d/r[10]).read_bytes()==checked(e),'exact complete valid mirror prefix')
 need(seen_b==set(expected_b),'boundary full coverage')
 rows=table(d/'transfers.tsv');keys=set();actual=[0,0,0]
 for r in rows:
  need(len(r)==18 and r[0]=='T45-full40'and number(r[1])==1,'copy source request/epoch');generation=number(r[2]);r=r[3:];pos,ordinal,n=map(number,r[:3]);need(generation==pos+1,'copy join to original boundary generation');key=(pos,ordinal);need(str(pos)in q['copy_sizes']and ordinal<len(q['copy_sizes'][str(pos)])and key not in keys,'unique copy identity');keys.add(key);need(n==q['copy_sizes'][str(pos)][ordinal],'exact per-copy bytes')
  peer,bd,bh=map(number,r[4:7]);cap,can,enable,copy,disable,record,drain=map(signed,r[7:14]);need(number(r[14])==0 and record==0 and drain==-1,'actual consumer return event')
  if r[3]=='host-bounce':
   need((peer,bd,bh)==(0,n,n),'actual bounce legs')
   if policy=='bounce':need((cap,can,enable,copy,disable)==(-1,-1,-1,-1,-1),'forced bounce unattempted peer')
   else:
    need((cap!=0 and can==-1)or(cap==0 and can in(0,1)),'actual capability status')
    if cap!=0 or can==0:need((enable,copy,disable)==(-1,-1,-1),'unattempted peer enable/copy/disable')
    if cap==0 and can==1:
     need(enable>=0,'capable peer must attempt enable');need(copy>0 if enable in(0,704)else copy==-1,'bounce follows failed enable or failed peer copy')
    if enable==0:need(disable==0,'owned peer enable release')
    else:need(disable==-1,'unowned peer enable release')
  elif r[3]=='peer':need(policy=='auto'and(peer,bd,bh)==(n,0,0)and cap==0 and can==1 and enable in(0,704)and copy==0 and disable==(0 if enable==0 else -1),'actual peer result')
  else:raise ValueError('cross-role copy path')
  actual=[a+b for a,b in zip(actual,(peer,bd,bh))]
 need(keys=={(p,i)for p in range(3)for i in range(5)},'all per-frame copies')
 events=table(d/'events.tsv');need(events==[[str(p*4+i),str(p),name]for p in range(3)for i,name in enumerate(('primary-ready','boundary-copy-ready','secondary-complete','retired'))],'exact lifecycle order/terminal')
 need(stats(d/'full-controls.tsv')=={'invalid_head_rejections':[1]},'existing final borrowed head invalidation guard');s=stats(d/'split-stats.tsv');need(set(s)=={'payload','actual_transfer','requested_logits_d2h','owned'}|{side+'_'+kind for side in ('primary','secondary')for kind in ('positions','compressed','keys','core')},'exact required stats coverage');o=q['operational'];need(s.pop('payload')==[o['total'],o['new_kv'],o['new_keys'],0,o['candidates']],'operational delta counters');need(s.pop('actual_transfer')==actual,'actual transfer aggregate');need(s.pop('requested_logits_d2h')==[3*129280*4],'requested final head D2H');need(s.pop('owned')==[q['expected_owned']['primary'],q['expected_owned']['secondary'],2097152],'per-role actual allocation sum once')
 for side in ('primary','secondary'):
  need(s.pop(side+'_positions')==[3 if (l<24)==(side=='primary')else 0 for l in range(40)],'owned layer state schedule')
  need(s.pop(side+'_core')==[q['core_storage'][side],q['constant_source'][side],q['constant_source'][side]+(54 if side=='primary'else 6),0 if side=='primary'else 3*129280*4],'Core storage/constant/upload/requested download')
  for kind in ('compressed','keys'):need(s.pop(side+'_'+kind)==([1,1,1,3]if side=='primary'else[0,0,0,3]),'writer/mirror valid publication')
 need(not s,'unexpected stats key');supply=stats(d/'supply-stats.tsv');need(set(supply)=={'primary','secondary','row'},'required source stats coverage')
 for side in ('primary','secondary'):
  c=q['cache'][side];need(supply.pop(side)==[c[k]for k in ('weight_read','weight_h2d','aligned_read','issued_reads','gpu_hits','ram_hits','ssd_misses')]+[0,0],'independent original-source cache/permit counters')
 need(supply.pop('row')==[38016,38016]and not supply,'original Engram row supply');owner_memory(d);need({p.name for p in d.glob('*.bin')}==files,'exact binary output set')
 return dict(stages=len(seen),boundary_outputs=len(seen_b),boundary_values=sum(x['bytes']for x in q['boundaries'])//4,values=values+3*129280,transfers=len(keys),operational_bytes=o['total'],physical_simultaneous_occupancy_measured=False,whole_task_qualified=False)


def small(directory,q,policy='auto'):
 d=Path(directory);expected=q['small_outputs'];seen=set();files=set()
 for r in table(d/'small-metadata.tsv'):
  need(len(r)==9,'small metadata fields');pos,kind,writer,ratio,epoch,rows,delta,n=map(number,r[:8]);key=f'{pos}:{kind}';need(key in expected and key not in seen,'small complete metadata identity');seen.add(key);e=expected[key];need([writer,ratio,epoch,rows,delta,n]==e['metadata'],'small writer/ratio/current row/delta');need(r[8]==e['file'],'small file identity');files.add(r[8]);need((d/r[8]).read_bytes()==checked(e),'small exact valid prefix')
 need(seen==set(expected),'small all frames/kinds');need((d/'tap.bin').read_bytes()==checked(q['tap']),'typed reverse tap exact bytes');files.add('tap.bin');need({p.name for p in d.glob('*.bin')}==files,'small exact output set')
 need(stats(d/'small-controls.tsv')=={'rejections':[53],'copy_count':[8],'actual_consumer_d2h':[66576],'lease_early_checks':[16]},'same metadata/tap guard counts')
 rows=table(d/'small-transfers.tsv');need(len(rows)==8,'small copy coverage')
 actual=[0,0,0]
 for ordinal,(r,size)in enumerate(zip(rows,[2048,512,4,4,2048,512,8,61440])):
  need(len(r)==14 and number(r[13])==(1 if ordinal==0 else 0)and[number(r[0]),number(r[1])]==[ordinal,size],'small exact transfer ordinal/size');peer,bd,bh=map(number,r[3:6]);cap,can,enable,copy,disable,record,drain=map(signed,r[6:13]);need(record==0 and drain==-1,'small actual last use')
  need((r[2]=='host-bounce'and(peer,bd,bh)==(0,size,size))or(r[2]=='peer'and policy=='auto'and(peer,bd,bh)==(size,0,0)and cap==0 and can==1 and enable in(0,704)and copy==0),'small reached path bytes')
  if policy=='bounce':need((cap,can,enable,copy,disable)==(-1,-1,-1,-1,-1),'small forced path unattempted peer')
  elif r[2]=='host-bounce':
   need(cap>=0 and((cap!=0 and can==-1)or(cap==0 and can in(0,1))),'small actual capability query')
   if cap!=0 or can==0:need((enable,copy,disable)==(-1,-1,-1),'small unattempted peer operations')
   else:need(enable>=0 and(copy>0 if enable in(0,704)else copy==-1),'small actual failed peer fallback')
  if enable==0:need(disable==0,'small own enable release')
  else:need(disable==-1,'small unowned enable release')
  actual=[x+y for x,y in zip(actual,(peer,bd,bh))]
 need(actual[0]+actual[1]==66576 and actual[1]==actual[2],'small operational bytes')
 return dict(outputs=13,values=(sum(x['bytes']for x in expected.values())+q['tap']['bytes'])//4,copies=8,bytes=66576)

def api(directory,q):
 d=Path(directory);need(stats(d/'api-controls.tsv')=={'rejections':[6],'positive':[5]},'actual API/cancel/publication-failure/fresh counts')
 for file,name in [('fresh-layer0.bin','block_output'),('fresh-pre.bin','block_next_pre')]:
  e=next(x for x in q['expected_stages']if x['position']==0 and x['layer']==0 and x['name']==name);need((d/file).read_bytes()==checked(e),'fresh prefix same independent input')
 need({p.name for p in d.glob('*.bin')}=={'fresh-layer0.bin','fresh-pre.bin'},'API exact outputs');return dict(rejections=6,positive=5,values=20484)

def cancelled(directory,q):
 d=Path(directory);need(stats(d/'cancel-controls.tsv')=={'rejections':[2],'positive':[3]},'before issue/Ready failure/late/fresh control counts');need(table(d/'events.tsv')==[['0','0','primary-ready'],['1','0','boundary-copy-ready']],'Ready cancellation happened before consumer')
 need(not table(d/'transfers.tsv'),'no successful consumer return callback invented');s=stats(d/'split-stats.tsv');need(set(s)=={'payload','actual_transfer','requested_logits_d2h','owned'}|{side+'_'+kind for side in ('primary','secondary')for kind in ('positions','compressed','keys','core')},'cancel complete stats coverage');o=[84500,2048,512,0,4];need(s['payload']==o and s['requested_logits_d2h']==[0]and s['actual_transfer'][0]+s['actual_transfer'][1]==84500 and s['actual_transfer'][1]==s['actual_transfer'][2],'Ready copy bytes/drain without head')
 expected={x['name']:x for x in q['boundaries']if x['position']==0};seen=set()
 for r in table(d/'boundaries.tsv'):
  need(len(r)==11 and r[0]=='T45-cancel'and list(map(number,r[1:5]))==[1,0,1,24]and r[5]in expected and r[5]not in seen,'Ready cancelled original metadata');seen.add(r[5]);e=expected[r[5]];need(list(map(number,r[6:10]))==e['shape']+[e['scalar'],e['bytes']]and(d/r[10]).read_bytes()==checked(e),'Ready reached actual mirror bytes')
 need(seen==set(expected),'Ready all copy prefixes')
 for file,name in [('fresh-layer0.bin','block_output'),('fresh-pre.bin','block_next_pre')]:
  e=next(x for x in q['expected_stages']if x['position']==0 and x['layer']==0 and x['name']==name);need((d/file).read_bytes()==checked(e),'after Ready cancellation actual fresh prefix')
 return dict(rejections=2,positive=3,values=20484,ready_bytes=84500)


def self_test(q,directory):
 """Synthetic positive exercises the comparator; it is never a G capture."""
 import shutil
 d=Path(directory);d.mkdir(parents=True,exist_ok=True)
 lines=[]
 for e in q['expected_stages']:
  name=f"{e['position']}-layer{e['layer']}-{e['name']}.bin";(d/name).write_bytes(checked(e));lines.append([e['position'],e['layer'],e['name'],e['shape'][0],math.prod(e['shape'][1:]),4 if e['dtype']=='uint32'else 5 if e['dtype']=='int32'else 0,e['bytes'],name])
 def write(name,rows): (d/name).write_text(''.join('\t'.join(map(str,r))+'\n'for r in rows),encoding='utf-8')
 write('stages.tsv',lines);logits={x['position']:checked(x)for x in q['outputs']if x['name']=='logits'};(d/'prefill2-logits.bin').write_bytes(logits[0]+logits[1]);(d/'append-logits.bin').write_bytes(logits[2]);boundaries=[]
 for e in q['boundaries']:
  name=f"{e['position']}-boundary-{e['name']}.bin";(d/name).write_bytes(checked(e));boundaries.append(['T45-full40',1,e['position'],e['position']+1,24,e['name'],*e['shape'],e['scalar'],e['bytes'],name])
 write('boundaries.tsv',boundaries);write('transfers.tsv',[['T45-full40',1,p+1,p,i,n,'host-bounce',0,n,n,0,0,-1,-1,-1,0,-1,0]for p in range(3)for i,n in enumerate(q['copy_sizes'][str(p)])]);write('events.tsv',[[p*4+i,p,name]for p in range(3)for i,name in enumerate(('primary-ready','boundary-copy-ready','secondary-complete','retired'))]);write('full-controls.tsv',[['invalid_head_rejections',1]])
 o=q['operational'];rows=[['payload',o['total'],o['new_kv'],o['new_keys'],0,o['candidates']],['actual_transfer',0,o['total'],o['total']],['requested_logits_d2h',1551360],['owned',q['expected_owned']['primary'],q['expected_owned']['secondary'],2097152]]
 for side in ('primary','secondary'):
  rows.extend([[side+'_positions',*[3 if(l<24)==(side=='primary')else 0 for l in range(40)]],[side+'_compressed',*([1,1,1,3]if side=='primary'else[0,0,0,3])],[side+'_keys',*([1,1,1,3]if side=='primary'else[0,0,0,3])],[side+'_core',q['core_storage'][side],q['constant_source'][side],q['constant_source'][side]+(54 if side=='primary'else 6),0 if side=='primary'else 1551360]])
 write('split-stats.tsv',rows);write('supply-stats.tsv',[[side,*[q['cache'][side][k]for k in ('weight_read','weight_h2d','aligned_read','issued_reads','gpu_hits','ram_hits','ssd_misses')],0,0]for side in ('primary','secondary')]+[['row',38016,38016]])
 write('owner-memory.tsv',[[side,4194304+131072+4*2097152,100,4*2097152,1,1]for side in ('primary','secondary')]+[['row',16064+4*65536,100,4*65536,1,1]]);write('owner-stages.tsv',[[side,i,1000+(20000000 if side=='secondary'else 0)+i*3000000,2097152,1,0,1]for side in ('primary','secondary')for i in range(4)]+[['row',i,50000000+i*65536,65536,1,0,1]for i in range(4)]);positive=full(d,q);negative=0
 def reject(name,raw):
  nonlocal negative
  p=d/name;old=p.read_bytes();p.write_bytes(raw)
  try:
   try:full(d,q)
   except(ValueError,OSError):negative+=1
   else:raise AssertionError('invalid capture accepted '+name)
  finally:p.write_bytes(old)
 for name in ('stages.tsv','boundaries.tsv','transfers.tsv','events.tsv','split-stats.tsv','supply-stats.tsv','full-controls.tsv','owner-memory.tsv','owner-stages.tsv'):
  raw=(d/name).read_bytes();reject(name,b'');reject(name,b'\n'.join(raw.splitlines()[:-1])+b'\n');reject(name,raw+raw.splitlines()[0]+b'\n')
 for name in ('prefill2-logits.bin','append-logits.bin','0-boundary-0-20.bin'):
  raw=(d/name).read_bytes();reject(name,raw[:-1]);reject(name,raw+b'\0');reject(name,bytes([raw[0]^1])+raw[1:])
 for name in ('boundaries.tsv','transfers.tsv','split-stats.tsv','supply-stats.tsv','full-controls.tsv','owner-memory.tsv','owner-stages.tsv'):
  original=table(d/name)
  indices=[i for i,v in enumerate(original[0])if v.isdecimal()]
  for index in indices:
   for change in ('0.0','-1',str(int(original[0][index])+1)):
    if change==str(int(original[0][index])+1)and(name=='owner-memory.tsv'and index==2 or name=='owner-stages.tsv'and index==2):continue # Dynamic host metadata/address is observed, not an invented exact expected address.
    changed=[r[:]for r in original];changed[0][index]=change;reject(name,(''.join('\t'.join(r)+'\n'for r in changed)).encode())
 for index,change in ((0,'wrong'),(1,'0'),(3,'0'),(4,'23'),(5,'omitted')):
  changed=[r[:]for r in table(d/'boundaries.tsv')];changed[0][index]=change;reject('boundaries.tsv',(''.join('\t'.join(r)+'\n'for r in changed)).encode())
 for index in (7,8,9):
  changed=[r[:]for r in table(d/'transfers.tsv')];changed[0][index]='0';reject('transfers.tsv',(''.join('\t'.join(r)+'\n'for r in changed)).encode()) if index!=7 else None
 original=table(d/'owner-stages.tsv')
 for target,source,delta in ((1,0,0),(1,0,1),(1,0,2097151),(4,0,0),(8,0,0)):
  changed=[r[:]for r in original];changed[target][2]=str(int(changed[source][2])+delta);reject('owner-stages.tsv',(''.join('\t'.join(r)+'\n'for r in changed)).encode())
 old=(d/'owner-stages.tsv').read_bytes();adjacent=[r[:]for r in original];cursor=4096
 for r in adjacent:r[2]=str(cursor);cursor+=int(r[3])
 try:
  write('owner-stages.tsv',adjacent);full(d,q)
 finally:(d/'owner-stages.tsv').write_bytes(old)
 return dict(synthetic_positive=positive,rejections=negative,GPU_used=False,actual_capture=False)


def owner_memory(d):
 memory=stats(d/'owner-memory.tsv');need(set(memory)=={'primary','secondary','row'},'all owner memory roles');groups={role:[]for role in memory};ranges=[]
 for r in table(d/'owner-stages.tsv'):
  need(len(r)==7 and r[0]in groups,'actual stage metadata');i,address,capacity,attempted=map(number,r[1:5]);status,kind=map(signed,r[5:]);need(i==len(groups[r[0]])and attempted in(0,1),'stage identity/attempt strict')
  if capacity:
   need(address<=2**64-1 and capacity<=2**64-1-address,'stage address range arithmetic');ranges.append((address,address+capacity))
  need((address>0 and capacity==(65536 if r[0]=='row'else 2097152)and attempted==1)or(address==0 and capacity==0 and attempted==0 and status==kind==-1),'actual acquired stage capacity/type');need((status==0 and kind>=0)or(status!=0 and kind==-1),'query failure remains unknown');groups[r[0]].append((capacity,attempted,status,kind))
 ranges.sort();need(all(a[1]<=b[0]for a,b in zip(ranges,ranges[1:])),'simultaneous stage address ranges must not alias')
 for role,rows in groups.items():
  need(len(rows)==4,'all four actual stage observations');host,metadata,subset,known,observed=memory[role];need(metadata>0 and known in(0,1)and observed in(0,1),'host metadata/strict pin flags');derived=sum(cap for cap,tried,status,kind in rows if tried and status==0 and kind==1);need(subset==derived and known==int(all(not tried or status==0 for cap,tried,status,kind in rows))and observed==int(all(cap and tried and status==0 and kind==1 for cap,tried,status,kind in rows)),'exact observed pinned subset/flags')
  need(host==(16064 if role=='row'else 4194304+131072)+sum(x[0]for x in rows),'owned host payload/stages; metadata separately aliased')


def small_self_test(q,directory):
 d=Path(directory);d.mkdir(parents=True,exist_ok=True)
 def write(name,rows):(d/name).write_text(''.join('\t'.join(map(str,r))+'\n'for r in rows),encoding='utf-8')
 records=[]
 for key,e in q['small_outputs'].items():
  pos,kind=map(int,key.split(':'));(d/e['file']).write_bytes(checked(e));records.append([pos,kind,*e['metadata'],e['file']])
 write('small-metadata.tsv',records);(d/'tap.bin').write_bytes(checked(q['tap']));write('small-controls.tsv',[['rejections',53],['copy_count',8],['actual_consumer_d2h',66576],['lease_early_checks',16]])
 write('small-transfers.tsv',[[i,n,'host-bounce',0,n,n,0,0,-1,-1,-1,0,-1,int(i==0)]for i,n in enumerate([2048,512,4,4,2048,512,8,61440])]);positive=small(d,q);count=0
 def reject(name,raw):
  nonlocal count
  p=d/name;old=p.read_bytes();p.write_bytes(raw)
  try:
   try:small(d,q)
   except(ValueError,OSError):count+=1
   else:raise AssertionError('small invalid accepted '+name)
  finally:p.write_bytes(old)
 for name in ('small-metadata.tsv','small-transfers.tsv','small-controls.tsv'):
  original=table(d/name);raw=(d/name).read_bytes();reject(name,b'');reject(name,b'\n'.join(raw.splitlines()[:-1])+b'\n');reject(name,raw+raw.splitlines()[0]+b'\n')
  for i,value in enumerate(original[0]):
   if not value.isdecimal():continue
   for wrong in ('0.0','-1',str(int(value)+1)):
    rows=[r[:]for r in original];rows[0][i]=wrong;reject(name,(''.join('\t'.join(r)+'\n'for r in rows)).encode())
 for name in ('1-small-2.bin','3-small-0.bin','tap.bin'):
  raw=(d/name).read_bytes();reject(name,raw[:-1]);reject(name,raw+b'\0');reject(name,bytes([raw[0]^1])+raw[1:])
 return dict(positive=positive,rejections=count,GPU_used=False,actual_capture=False)
