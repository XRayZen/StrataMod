"""Pure CPU comparison of sealed original Q and actual storage-owner records."""
from pathlib import Path
import hashlib,json
def need(value,message):
 if not value:raise ValueError(message)
def integer(value):
 need(type(value)is int and value>=0,'nonnegative integer');return value
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_rows(path,width):
 lines=Path(path).read_text(encoding='utf-8').splitlines();need(bool(lines),'empty receipt')
 rows=[line.split('\t')for line in lines];need(all(len(x)==width for x in rows),'receipt column count');return rows
def expected_operations(q,slots):
 integer(slots);need(slots>0,'active finite slots');keys=[None]*slots;result=[]
 for job in q['jobs']:
  for phase in ('fill','secondary','after-cancel','copy-failed-fallback','next-tile','first-again'):
   first=8 if phase=='next-tile'else 0;key=(job['id'],first);hit=key in keys
   if hit:index=keys.index(key)
   else:
    index=keys.index(None)if None in keys else 0;keys[index]=key
   failed=phase=='copy-failed-fallback'
   # The existing B3 coordinator emits B2+B1. A successful S return leaves
   # Primary empty, so both waves return from S. A fill/fallback leaves a
   # Primary resident hit for the second wave and adds no secondary operation.
   for wave in range(2 if hit and not failed else 1):
    result.append(dict(job=job,phase=phase,key=key,slot=index,hit=hit,failed=failed,wave=wave,bytes=job['bytes']//job['rows']*8))
 return result
def transfers(row):
 # Only submitted Ready/retired copies carry nonzero transfer counts.
 b,local,peer,d2h,h2d=map(int,row[8:13]);need(min(b,local,peer,d2h,h2d)>=0,'transfer negative')
 path=row[13];cap,can,enable,copy,disable,record,drain,cancel=map(int,row[14:22]);need(cancel in(0,1),'cancel boolean')
 if path=='local':need(local==b and peer==d2h==h2d==0 and(cap,can,enable,copy,disable)==(-1,)*5,'local copy exact/peer unattempted')
 elif path=='host-bounce':
  need(d2h==h2d==b and local==peer==0,'bounce both legs exact')
  if cap==-1:need((can,enable,copy,disable)==(-1,)*4,'forced peer APIs unattempted')
  elif cap==0:
   need(can in(0,1),'capability access result')
   if can==0:need((enable,copy,disable)==(-1,)*3,'unsupported peer APIs unattempted')
   else:need(enable>=0 and copy!=0 and disable==-1,'failed peer path statuses')
  else:need(cap>0 and(can,enable,copy,disable)==(-1,)*4,'failed capability API statuses')
 elif path=='peer':need(peer==b and local==d2h==h2d==0 and cap==0 and can==1 and copy==0,'actual peer success')
 else:raise ValueError('actual copy path')
 return b,local,peer,d2h,h2d
def validate_unit(q,output,slots,primary,secondary,policy='auto',ram_payload=131072):
 output=Path(output);integer(primary);integer(secondary);need(primary!=secondary,'distinct actual roles')
 expected={x['name']:x for x in q['outputs']};actual={p.name for p in output.glob('*.bin')};need(actual==set(expected),'output set')
 for name,item in expected.items():
  data=(output/name).read_bytes();need(len(data)==integer(item['bytes'])and hashlib.sha256(data).hexdigest()==item['sha256'],'canonical Q exact '+name)
 events=read_rows(output/'events.tsv',23);groups={}
 for row in events:
  need(row[0]=='T22-packed-storage-unit'and int(row[1])==1,'fixture identity/epoch');op,slot,gen=map(int,row[2:5]);need(op>0 and 0<=slot<slots and gen>=0,'operation slot/generation');groups.setdefault(op,[]).append(row)
 operations=expected_operations(q,slots);need(set(groups)==set(range(1,len(operations)+1)),'complete operation identities');need([int(r[2])for r in events]==sorted(int(r[2])for r in events),'serialized operation order')
 total=[0]*5;per_operation={};generations=[0]*slots
 for i,expected_op in enumerate(operations,1):
  rows=groups[i];is_hit=expected_op['hit'];failed=expected_op['failed'];names=[r[5]for r in rows]
  sequence=['hit_ready','retired','bypass']if failed else(['hit_ready','kernel_submitted','retired']if is_hit else['snapshot_ready','fill_ready','retired','retired','published'])
  need(names==sequence,'actual lease order/terminal');need(all(int(r[3])==expected_op['slot']for r in rows),'actual selected slot');need({r[22]for r in rows}=={expected_op['job']['tile_keys'][str(expected_op['key'][1])]},'same fixed original key per operation')
  previous=generations[expected_op['slot']]
  if is_hit:need([int(r[4])for r in rows]==[previous]*len(rows),'actual cache generation retained across hit')
  else:
   generations[expected_op['slot']]+=1;need([int(r[4])for r in rows]==[previous]+[previous+1]*(len(rows)-1),'actual fill generation publication')
  ready=[r for r in rows if r[5].endswith('_ready')];retired=[r for r in rows if r[5]=='retired'];need(len(ready)==len(retired),'every copy actually retired')
  for row in rows:
   if row in ready:need(tuple(map(int,row[19:22]))==(-1,-1,0),'Ready return API unattempted')
   elif row not in retired:need(tuple(map(int,row[6:13]))==(-1,-1,0,0,0,0,0)and row[13]=='none'and tuple(map(int,row[14:22]))==(-1,-1,-1,-1,-1,-1,-1,0),'non-copy event unattempted counters')
  sums=[0]*5
  for index,row in enumerate(ready):
   values=transfers(row);need(values[0]==expected_op['bytes'],'actual original tile bytes');target=(secondary,primary)if is_hit else((primary,primary)if index==0 else(primary,secondary));need(tuple(map(int,row[6:8]))==target,'copy role direction')
   if target[0]==target[1]:need(row[13]=='local','same-device actual local path')
   if target[0]!=target[1]:
    need(policy in('auto','bounce'),'declared copy policy')
    need((row[13]=='host-bounce'and tuple(map(int,row[14:19]))==(-1,)*5)if policy=='bounce'else int(row[14])>=0,'actual peer API attempt versus forced policy')
   terminal=retired[len(retired)-1-index];need(tuple(map(int,terminal[6:8]))==target and transfers(terminal)==values,'matching retired copy');need(tuple(map(int,terminal[19:21]))==(0,-1),'actual last-use event recorded, no return-drain attempt');need(int(terminal[21])==int(failed),'cancel status');total=[a+b for a,b in zip(total,values)];sums=[a+b for a,b in zip(sums,values)]
  need(int(rows[-1][4])>0,'published valid generation')
  per_operation.setdefault((expected_op['job']['id'],expected_op['phase']),[]).append((expected_op,sums))
 stats=[line.split('\t')for line in(output/'stats.tsv').read_text(encoding='utf-8').splitlines()];need(len(stats)==len(expected)+1 and stats[-1][0]=='owned','complete stats records')
 seen=set()
 for row in stats[:-1]:
  need(len(row)==14 and row[0]not in seen,'unique counter columns');seen.add(row[0]);name,phase=row[0].split('-',1);job=next(j for j in q['jobs']if j['id']==name);b=job['bytes']//job['rows']*8
  if phase in('ssd','local','ram'):
   target=[b if phase=='ssd'else 0,b if phase!='local'else 0,int(phase=='ssd'),2 if phase=='local'else 1,int(phase=='ram')]+[0]*8
  else:
   entries=per_operation[(name,phase)];read=any(not op['hit']or op['failed']for op,_ in entries);sums=[sum(s[i]for _,s in entries)for i in range(5)];fills=sum(not op['hit']for op,_ in entries);hits=sum(op['hit']and not op['failed']for op,_ in entries);returns=sum(op['hit']for op,_ in entries);target=[b if read else 0,b if read else 0,int(read),int(read),0,hits,fills,sums[1],fills*b,returns*b,sums[2],sums[3],sums[4]]
  need(list(map(int,row[1:]))==target,'independent actual counter derivation '+row[0])
 need(seen=={x[:-4]for x in expected},'counter/output set')
 owned=stats[-1];need(len(owned)==16,'owned columns');values=list(map(int,owned[1:]));need(all(x>=0 for x in values),'owned nonnegative');need(values[0]==(3*5120+3*2304)*4 and values[1]==2*65536+2*256 and values[2:5]==[65536,65536*slots,65536],'independent working/S/bounce capacity');need(values[6:8]==[slots,65536]and 0<values[8]<=slots and values[9]==2,'finite owner slot/stream count');need(values[10]==sum(len([r for r in group if r[5].endswith('_ready')])for group in groups.values())*2,'actual created copy events');integer(ram_payload);ram_slots=ram_payload//65536;need(ram_slots>=2 and values[13:15]==[ram_slots,ram_slots*65536]and values[11]==ram_slots*65536+131072+4*65536 and values[12]>0,'explicit model RAM payload/slots/host subset')
 return dict(output_values=q['output_values'],outputs=len(expected),operations=len(operations),copy_bytes=total[0],local_d2d=total[1],peer_bytes=total[2],bounce_d2h=total[3],bounce_h2d=total[4],whole_task_qualified=False)

def synthetic(q,output,slots=2):
 """CPU validator fixture only, explicitly not a GPU capture or numeric oracle."""
 import shutil
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 for item in q['outputs']:shutil.copyfile(item['path'],output/item['name'])
 events=[];counter={};generations=[0]*slots;copy_count=0
 def event(op,kind,source=-1,dest=-1,transfer=False,cancel=False):
  b=op['bytes']if transfer else 0;local=b if source==dest and transfer else 0;cross=transfer and source!=dest
  path='local'if local else'host-bounce'if cross else'none';peer_status=[0,0,-1,-1,-1]if cross else[-1]*5;record=0 if kind=='retired'else-1
  return ['T22-packed-storage-unit','1',str(op['number']),str(op['slot']),str(generations[op['slot']]),kind,str(source),str(dest),str(b),str(local),'0',str(b if cross else 0),str(b if cross else 0),path,*map(str,peer_status),str(record),'-1',str(int(cancel)),op['job']['tile_keys'][str(op['key'][1])]]
 for i,op in enumerate(expected_operations(q,slots),1):
  op['number']=i;b=op['bytes'];hit=op['hit'];failed=op['failed'];copies=[]
  if not hit:
   events.append(event(op,'snapshot_ready',1,1,True));copies.append((1,1));generations[op['slot']]+=1;events.append(event(op,'fill_ready',1,0,True));copies.append((1,0))
  else:events.append(event(op,'hit_ready',0,1,True));copies.append((0,1))
  if hit and not failed:events.append(event(op,'kernel_submitted'))
  for source,dest in reversed(copies):events.append(event(op,'retired',source,dest,True,failed))
  if failed:events.append(event(op,'bypass'))
  elif not hit:events.append(event(op,'published'))
  copy_count+=len(copies);read=not hit or failed
  values=[b if read else 0,b if read else 0,int(read),int(read),0,int(hit and not failed),int(not hit),b if not hit else 0,b if not hit else 0,b if hit else 0,0,b,b]
  key=(op['job']['id'],op['phase']);counter[key]=[a+c for a,c in zip(counter.get(key,[0]*13),values)]
 (output/'events.tsv').write_text('\n'.join('\t'.join(r)for r in events)+'\n',encoding='utf-8')
 rows=[]
 for item in q['outputs']:
  name,phase=item['source'],item['phase'];job=next(j for j in q['jobs']if j['id']==name);b=job['bytes']//job['rows']*8
  if phase in('ssd','local','ram'):values=[b if phase=='ssd'else 0,b if phase!='local'else 0,int(phase=='ssd'),2 if phase=='local'else 1,int(phase=='ram')]+[0]*8
  else:values=counter[(name,phase)]
  rows.append([name+'-'+phase,*map(str,values)])
 rows.append(['owned',str((3*5120+3*2304)*4),'131584','65536',str(65536*slots),'65536','1000',str(slots),'65536',str(slots),'2',str(2*copy_count),str(131072+131072+4*65536),'1000','2','131072'])
 (output/'stats.tsv').write_text('\n'.join('\t'.join(row)for row in rows)+'\n',encoding='utf-8');return output

def self_test(q,output,slots=2):
 output=synthetic(q,output,slots);positive=validate_unit(q,output,slots,1,0);rejected=0
 def refuse(path,changed):
  nonlocal rejected
  original=path.read_bytes();path.write_bytes(changed)
  try:
   try:validate_unit(q,output,slots,1,0)
   except (ValueError,IndexError,KeyError,StopIteration):rejected+=1;return
   raise AssertionError('validator accepted mutation')
  finally:path.write_bytes(original)
 events=output/'events.tsv';raw=events.read_text(encoding='utf-8');lines=raw.splitlines()
 refuse(events,b'');refuse(events,('\n'.join(lines[:-1])+'\n').encode());refuse(events,('\n'.join(line for line in lines if '\tretired\t'not in line)+'\n').encode())
 for column,value in ((0,'wrong'),(1,'0'),(2,'0'),(3,'2'),(4,'-1'),(4,'999'),(8,'0'),(9,'999'),(10,'1'),(11,'1'),(12,'1'),(13,'peer'),(14,'0'),(15,'1'),(19,'0'),(21,'1'),(22,'wrong')):
  changed=[x.split('\t')for x in lines];changed[0][column]=value;refuse(events,('\n'.join('\t'.join(x)for x in changed)+'\n').encode())
 stats=output/'stats.tsv';rows=[r.split('\t')for r in stats.read_text(encoding='utf-8').splitlines()]
 for index,column in ((0,1),(0,2),(0,3),(1,4),(2,5),(3,7),(3,8),(3,9),(4,6),(4,10),(4,12),(-1,1),(-1,3),(-1,4),(-1,5),(-1,7),(-1,8),(-1,10),(-1,11)):
  changed=[r[:]for r in rows];changed[index][column]=str(int(changed[index][column])+1);refuse(stats,('\n'.join('\t'.join(x)for x in changed)+'\n').encode())
 first=output/q['outputs'][0]['name'];raw=first.read_bytes();refuse(first,raw[:-1]);refuse(first,raw+b'\0');refuse(first,bytes([raw[0]^1])+raw[1:]);validate_unit(q,output,slots,1,0)
 return dict(rejected=rejected,positive=positive,GPU_executed=False,synthetic_only=True)

def validate_dram(q,output,ram_payload,measurement=False):
 import reference
 rows=read_rows(Path(output)/'dram.tsv',11);required=['owners-constructed']
 if not measurement:
  required += [item['name'][:-4]+suffix for item in q['outputs']for suffix in('-before','-after')]
 need([r[0]for r in rows]==required,'required DRAM observation point set/order');integer(ram_payload);resolved=ram_payload//65536*65536
 need(len({r[2]for r in rows})==1 and int(rows[0][2])>0,'same actual native PID');times=[int(r[1])for r in rows];need(times==sorted(times)and min(times)>=0,'monotonic DRAM observations');available={};resident_complete=True
 for r in rows:
  global_status,process_status=int(r[3]),int(r[5]);need(global_status>=0 and process_status>=0,'actual memory status');need(int(r[9])==resolved and r[10]=='null','zero-init capacity versus unexported valid payload')
  if global_status:need(r[4]=='null','failed global observation null');available[r[0]]=None
  else:available[r[0]]=integer(int(r[4]))
  if process_status:need(r[6:9]==['null']*3,'failed process memory observation null');resident_complete=False
  else:
   for value in r[6:9]:integer(int(value))
 condition=reference.dram_observed_condition(available,required)
 return dict(condition=condition,report_only=True,band_is_acceptance_gate=False,outside_band_refuses_GEN=False,required_points=len(required),process_resident_observations_complete=resident_complete,target_available_bytes=8589934592,band_available_bytes=[8589934592,9663676416],physical_available_bytes=available,zero_initialized_cache_payload_bytes=resolved,valid_model_payload_bytes=None,continuous_between_samples_guaranteed=False,numeric_result_independent=True)

def validate_unknown(q,output,slots,primary,secondary,ram_payload,policy='auto'):
 output=Path(output);integer(slots);integer(primary);integer(secondary);integer(ram_payload);need(slots>0 and primary!=secondary,'actual controlled roles/capacity')
 records=q['unknown_outputs'];need({p.name for p in output.glob('*.bin')}=={r['name']for r in records},'controlled output set')
 for r in records:need((output/r['name']).stat().st_size==r['bytes']and sha(output/r['name'])==r['sha256'],'controlled fallback/late/next canonical Q')
 job=next(j for j in q['jobs']if j['id']=='p0');b=job['bytes']//job['rows']*8;before=(output/'retained-before.bytes').read_bytes();after=(output/'retained-after.bytes').read_bytes();need(len(before)==b and before==after,'retained actual packed payload stable')
 rows=[line.split('\t')for line in(output/'unknown.tsv').read_text(encoding='utf-8').splitlines()];need([r[0]for r in rows]==['held','late','retained','RAM','actual_driver_fault']and list(map(len,rows))==[10,7,5,3,2],'controlled owner records')
 held=list(map(int,rows[0][1:]));late=list(map(int,rows[1][1:]));retain=list(map(int,rows[2][1:]));need(held[0]>0 and held[2]>0 and held[1]==held[3]==65536 and held[4:]==[1,1,1,1,1],'actual reader/job/retained/disabled/disjoint')
 for address,capacity in((held[0],held[1]),(held[2],held[3])):need(address+capacity<=2**64,'actual range overflow')
 need(held[0]+held[1]<=held[2]or held[2]+held[3]<=held[0],'actual fallback range independent of retained bundle');need(late==[held[0],held[1],0,0,1,1],'late retirement does not republish working storage');need(retain==[(slots+1)*65536,65536,0,0],'retained ownership and actual safe-stream observations');need(list(map(int,rows[3][1:]))==[ram_payload//65536,ram_payload//65536*65536]and rows[4][1]=='0','test RAM and controlled-not-driver-fault')
 events=read_rows(output/'events.tsv',23);sequence=['snapshot_ready','fill_ready','retired','retired','published','hit_ready','quarantined','bypass_retained','fallback_primary_ready','fallback_primary_ready','retired','controlled_late_retired','fallback_primary_ready','fallback_primary_ready'];need([r[5]for r in events]==sequence,'controlled retention/fallback/late/next order')
 need([int(r[2])for r in events]==[1]*5+[2]*9 and[int(r[4])for r in events]==[0]+[1]*13,'controlled operation/generation sequence')
 for r in events:need(r[0]=='T22-controlled-unknown'and r[1]=='2'and r[3]=='0'and r[22]==job['tile_keys']['0'],'controlled original identity/key/slot')
 for index,source,dest,cancel in((0,primary,primary,0),(1,primary,secondary,0),(2,primary,secondary,0),(3,primary,primary,0),(5,secondary,primary,0),(10,secondary,primary,1)):
  row=events[index];need(tuple(map(int,row[6:8]))==(source,dest)and transfers(row)[0]==b and int(row[21])==cancel,'controlled actual transfer/retirement')
  need(row[13]=='local'if source==dest else row[13]in('peer','host-bounce'),'controlled copy path role')
  need(tuple(map(int,row[19:21]))==((0,-1)if row[5]=='retired'else(-1,-1)),'controlled last-use API evidence')
  if source!=dest:need((int(row[14])>=0)if policy=='auto'else tuple(map(int,row[14:19]))==(-1,)*5,'controlled actual peer policy')
 for i in(4,6,7,8,9,11,12,13):need(tuple(map(int,events[i][6:13]))==(-1,-1,0,0,0,0,0)and events[i][13]=='none'and tuple(map(int,events[i][14:22]))==(-1,-1,-1,-1,-1,-1,-1,0),'controlled non-copy event statuses')
 return dict(outputs=len(records),output_values=q['unknown_output_values'],actual_copy_bytes=3*b,actual_retained_device_bytes=retain[0],actual_retained_host_bytes=retain[1],actual_primary_fallback_disjoint=True,late_result_unchanged=True,normal_unknown_reenable=False,controlled_certificate_unknown=True,actual_driver_fault=False,whole_task_qualified=False)

def unknown_self_test(q,output):
 import shutil
 output=Path(output);output.mkdir(parents=True,exist_ok=True);base=synthetic(q,output/'ordinary-synthetic',2)
 for record in q['unknown_outputs']:shutil.copyfile(record['path'],output/record['name'])
 allrows=read_rows(base/'events.tsv',23);events=[r[:]for r in allrows[:5]];hit=allrows[5][:];retired=allrows[7][:];retired[21]='1'
 def notification(name):
  row=allrows[4][:];row[2]='2';row[5]=name;return row
 events += [hit,notification('quarantined'),notification('bypass_retained'),notification('fallback_primary_ready'),notification('fallback_primary_ready'),retired,notification('controlled_late_retired'),notification('fallback_primary_ready'),notification('fallback_primary_ready')]
 for row in events:row[0]='T22-controlled-unknown';row[1]='2'
 ep=output/'events.tsv';ep.write_text('\n'.join('\t'.join(r)for r in events)+'\n',encoding='utf-8')
 rows=[['held',65536,65536,131072,65536,1,1,1,1,1],['late',65536,65536,0,0,1,1],['retained',196608,65536,0,0],['RAM',2,131072],['actual_driver_fault',0]]
 cp=output/'unknown.tsv';cp.write_text('\n'.join('\t'.join(map(str,r))for r in rows)+'\n',encoding='utf-8');b=q['jobs'][0]['bytes']//q['jobs'][0]['rows']*8;payload=bytes(i%256 for i in range(b));(output/'retained-before.bytes').write_bytes(payload);(output/'retained-after.bytes').write_bytes(payload)
 positive=validate_unknown(q,output,2,1,0,131072);count=0
 def refuse(path,data):
  nonlocal count
  original=path.read_bytes();path.write_bytes(data)
  try:
   try:validate_unknown(q,output,2,1,0,131072)
   except(ValueError,IndexError,KeyError,StopIteration):count+=1;return
   raise AssertionError('unknown validator accepted mutation')
  finally:path.write_bytes(original)
 refuse(ep,b'');refuse(ep,('\n'.join('\t'.join(r)for r in events[:-1])+'\n').encode())
 for index,column,value in((0,0,'wrong'),(0,1,'1'),(0,22,'wrong'),(5,4,'0'),(10,19,'-1'),(10,21,'0'),(13,5,'published')):
  changed=[r[:]for r in events];changed[index][column]=value;refuse(ep,('\n'.join('\t'.join(r)for r in changed)+'\n').encode())
 for index,column,value in((0,1,0),(0,3,65536),(0,5,0),(0,6,0),(0,7,0),(0,8,0),(0,9,0),(1,3,1),(1,4,1),(1,6,0),(2,1,0),(2,2,0),(2,3,1),(2,4,1),(4,1,1)):
  changed=[r[:]for r in rows];changed[index][column]=value;refuse(cp,('\n'.join('\t'.join(map(str,r))for r in changed)+'\n').encode())
 p=output/'retained-after.bytes';refuse(p,b'');refuse(p,bytes([payload[0]^1])+payload[1:]);p=output/q['unknown_outputs'][0]['name'];data=p.read_bytes();refuse(p,data[:-1]);refuse(p,data+b'\0');refuse(p,bytes([data[0]^1])+data[1:]);validate_unknown(q,output,2,1,0,131072)
 return dict(rejected=count,positive=positive,synthetic_only=True,GPU_executed=False)
