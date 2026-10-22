"""Independent accepted T20 Q slices and original aligned-window arithmetic."""
from pathlib import Path
import hashlib,json,importlib.util
ROOT=Path('C:/Develop/AI/Strata-data/build/deepseek-v41')
def record(path):
 p=Path(path);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def checked(r):
 p=Path(r['path']);v=record(p)
 if any(v[k]!=r[k]for k in('bytes','sha256')if k in r):raise ValueError('independent input binding '+str(p))
 return p.read_bytes()
def windows(offset,size,grants=(65536,)):
 if type(offset)is not int or type(size)is not int or offset<0 or size<=0 or not grants or any(type(g)is not int or g<4096 for g in grants):raise ValueError('finite valid grants')
 result=[];done=0
 while done<size:
  grant=grants[min(len(result),len(grants)-1)];capacity=min(65536,grant//4096*4096);padding=(offset+done)%4096;logical=min(size-done,capacity-padding);requested=(padding+logical+4095)//4096*4096
  if logical<=0 or requested>grant:raise ValueError('aligned permit')
  result.append(dict(offset=offset+done,completed=done,logical=logical,requested=requested,grant=grant));done+=logical
 return result
def prepare(destination):
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
 source=ROOT/'build-deepseek-t20/owner-attempt-4/captured-Q-manifest.json'
 if record(source)['sha256']!='fdfa0a9bf0c0bb12b3cba716f23a70357a515ef79b104f6d6e1f0b53b8821e2b':raise ValueError('accepted pre-G Q manifest')
 q=json.loads(source.read_text(encoding='utf-8'));prior=ROOT/'build-deepseek-t22/fixed-r3/source/Strata-extensions/tests/secondary_cache/reference.py'
 spec=importlib.util.spec_from_file_location('accepted_T22_input_guard',prior);guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
 inputs=[];jobs=[];outputs=[]
 for name in('sources.tsv','prefixes.tsv'):
  data=guard.bound_input(q,ROOT/'build-deepseek-t20/owner-input'/name);p=destination/name;p.write_bytes(data);inputs.append(record(p))
 for name,rows in(('p0',64),('p16',32)):
  matches=[j for j in q['jobs']if j['id']==name]
  if len(matches)!=1:raise ValueError('unique accepted job')
  j=matches[0];x=ROOT/'build-deepseek-t20/owner-input'/f'{name}-x.bin';raw=x.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=j['input_sha256']or len(raw)!=3*j['k']*4:raise ValueError('accepted activation')
  p=destination/x.name;p.write_bytes(raw);inputs.append(record(p));prior_q=ROOT/'build-deepseek-t20/owner-q'/f'{name}.bin';data=prior_q.read_bytes()
  if hashlib.sha256(data).hexdigest()!=j['expected_sha256']or len(data)!=j['expected_bytes']:raise ValueError('accepted full output')
  value=b''.join(data[(b*j['rows'])*4:(b*j['rows']+rows)*4]for b in range(3));p=destination/f'{name}-q.bin';p.write_bytes(value)
  item=dict(j);item.update(tile_rows=rows,tile_bytes=rows*(j['bytes']//j['rows']),Q=record(p),activation=record(destination/x.name));item['windows64']=windows(j['offset'],item['tile_bytes']);item['windows_variable']=windows(j['offset'],item['tile_bytes'],(4096,65536));jobs.append(item);outputs.append(record(p))
 result=dict(schema='T35-primary-provider-Q/v1',accepted_manifest=record(source),accepted_guard=record(prior),inputs=inputs,outputs=outputs,jobs=jobs,logical_batch=3,kernel_waves=[2,1],candidate_output_used=False,GPU_executed=False)
 (destination/'manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');return result
def cpu():
 for offset in(0,32,511,4095,4096):
  for grants in((65536,),(4096,65536),(4096,)):
   w=windows(offset,174080,grants)
   assert sum(r['logical']for r in w)==174080 and all(r['requested']<=r['grant']for r in w)
   assert all(a['offset']+a['logical']==b['offset']for a,b in zip(w,w[1:]))
 rejected=0
 for args in((-1,1,(4096,)),(0,0,(4096,)),(0,1,(True,)),(0,1,(4095,))):
  try:windows(*args)
  except ValueError:rejected+=1
  else:raise AssertionError('invalid grant accepted')
 return dict(positive_schedules=15,rejections=rejected,GPU_executed=False)
NUMERIC=('cold64','resident','ram','variable','fresh-before','fresh-between','fresh-issued','fresh-prefetch','fresh-error','legacy')
GENERATIONS={'cold64':1,'variable':7,'cancel-before':9,'fresh-before':10,'cancel-between':12,'fresh-between':13,'cancel-issued':15,'fresh-issued':16,'prefetch-between':17,'fresh-prefetch':18,'source-error':20,'fresh-error':21,'legacy':1}
def validate(q,directory):
 directory=Path(directory);values=0;rows={};groups={};controls=[]
 for line in(directory/'stats.tsv').read_text(encoding='utf-8').splitlines():
  fields=line.split('\t')
  if len(fields)!=9 or fields[0]in rows:raise ValueError('unique complete stats')
  rows[fields[0]]=list(map(int,fields[1:]))
 for line in(directory/'trace.tsv').read_text(encoding='utf-8').splitlines():
  fields=line.split('\t')
  if len(fields)!=9:raise ValueError('trace extent')
  groups.setdefault(fields[0],[]).append((fields[1],*map(int,fields[2:])))
 for line in(directory/'controls.tsv').read_text(encoding='utf-8').splitlines():controls.append(line.split('\t'))
 expected_rows=set();expected_groups=set();expected_controls=[]
 for job in q['jobs']:
  name=job['id'];size=job['tile_bytes'];wanted=checked(job['Q']);metadata=None
  for phase in NUMERIC:
   label=name+'-'+phase;expected_rows.add(label);got=(directory/(label+'.bin')).read_bytes()
   if got!=wanted:raise ValueError('original numerical Q '+label)
   values+=len(got)//4;row=rows.get(label)
   if row is None or len(row)!=8 or any(v<0 for v in row):raise ValueError('exact phase stats '+label)
   if metadata is None:metadata=row[-1]
   if row[-1]!=metadata or metadata<=0:raise ValueError('same actual Primary metadata subset')
   schedule=job['windows_variable'if phase=='variable'else'windows64'];read=size;requested=sum(w['requested']for w in schedule);ops=len(schedule);upload=size;gpu=1;ram=0
   if phase=='resident':read=requested=ops=upload=0;gpu=2
   elif phase=='ram':read=requested=ops=0;ram=1
   if row[:7]!=[read,requested,requested,ops,upload,gpu,ram]:raise ValueError('independent actual counter delta '+label)
  for phase,generation in GENERATIONS.items():
   label=name+'-'+phase;expected_groups.add(label);trace=groups.get(label,[])
   if not trace:raise ValueError('missing lifecycle '+label)
   if any(r[-1]!=generation or any(type(v)is not int or v<0 for v in r[1:])for r in trace):raise ValueError('bound generation/trace integers')
   if phase in('cancel-before','source-error'):
    # issue_reads stores its finite window before constructing SpanProvider;
    # a missing original therefore retains that window without an issued read.
    window=0 if phase=='cancel-before'else job['windows64'][0]['logical']
    if trace!=[('cancel-idle',0,0,window,0,0,0,generation)]:raise ValueError('unissued cancellation exact trace')
    continue
   provider=trace[0][1]
   if provider<=0 or any(r[1]!=provider or r[6]<=0 for r in trace):raise ValueError('same retained provider/metadata')
   if trace[0][0]!='create'or trace[-1][0]!='close'or trace[0][4:6]!=(0,0):raise ValueError('actual create/close')
   if phase=='legacy':
    requested=sum(w['requested']for w in job['windows64'])
    if [r[0]for r in trace]!=['create','take','close']or [r[2:6]for r in trace]!=[(0,0,0,0),(0,size,size,requested),(size,size,size,requested)]:raise ValueError('legacy exact whole ticket')
    continue
   schedule=job['windows_variable'if phase=='variable'else'windows64']
   cancelled=phase in('cancel-between','cancel-issued','prefetch-between')
   if cancelled:schedule=schedule[:1]
   if trace[0][2:6]!=(0,schedule[0]['logical'],0,0):raise ValueError('initial exact window state')
   wanted_events=['create']+[event for _ in schedule for event in('issue','take')]+(['cancel-idle']if phase in('cancel-between','prefetch-between')else[])+['close']
   if [r[0]for r in trace]!=wanted_events:raise ValueError('complete exact window lifecycle '+label)
   cumulative_read=0;cumulative_logical=0
   for i,w in enumerate(schedule):
    issue,take=trace[1+2*i:3+2*i];cumulative_read+=w['requested']
    if issue[2]!=w['completed']or issue[3]!=w['logical']or issue[4:6]!=(cumulative_logical,cumulative_read):raise ValueError('aligned grant/issued cumulative')
    if phase!='cancel-issued':cumulative_logical+=w['logical']
    if take[2]!=w['completed']or take[3]!=w['logical']or take[4:6]!=(cumulative_logical,cumulative_read):raise ValueError('taken cumulative once')
   terminal=(cumulative_logical,schedule[-1]['logical'],cumulative_logical,cumulative_read)
   if trace[-1][2:6]!=terminal:raise ValueError('closed exact complete/partial source')
   if phase in('cancel-between','prefetch-between')and trace[-2][2:6]!=terminal:raise ValueError('idle cancelled exact terminal state')
  expected_controls += [[name+'-'+p,'cancelled',str(mode)]for p,mode in(('cancel-before',0),('cancel-between',1),('cancel-issued',2),('prefetch-between',3))]+[[name+'-source-error','error','0']]
 if set(rows)!=expected_rows or set(groups)!=expected_groups or controls!=expected_controls:raise ValueError('no missing/extra output/stage/control')
 expected_files={'stats.tsv','trace.tsv','controls.tsv','loaded-modules.txt'}|{label+'.bin'for label in expected_rows}
 if {p.name for p in directory.iterdir()if p.is_file()}!=expected_files:raise ValueError('strict saved output set')
 return dict(output_values=values,numerical_outputs=len(expected_rows),trace_groups=len(expected_groups),control_cases=len(controls),original_Q_exact=True,physical_io=None,model_performance_qualified=False)
def synthetic(q,directory):
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=False);stats=[];trace=[];controls=[]
 for job in q['jobs']:
  name=job['id'];size=job['tile_bytes']
  for phase in NUMERIC:
   label=name+'-'+phase;(directory/(label+'.bin')).write_bytes(checked(job['Q']));schedule=job['windows_variable'if phase=='variable'else'windows64'];read=size;requested=sum(w['requested']for w in schedule);ops=len(schedule);upload=size;gpu=1;ram=0
   if phase=='resident':read=requested=ops=upload=0;gpu=2
   elif phase=='ram':read=requested=ops=0;ram=1
   stats.append([label,read,requested,requested,ops,upload,gpu,ram,1928])
  for phase,generation in GENERATIONS.items():
   label=name+'-'+phase
   def add(event,completed=0,window=0,logical=0,requested=0,provider=1,metadata=1024):trace.append([label,event,provider,completed,window,logical,requested,metadata,generation])
   if phase in('cancel-before','source-error'):add('cancel-idle',window=0 if phase=='cancel-before'else job['windows64'][0]['logical'],provider=0,metadata=0);continue
   schedule=job['windows_variable'if phase=='variable'else'windows64']
   if phase=='legacy':add('create');add('take',window=size,logical=size,requested=sum(w['requested']for w in schedule));add('close',completed=size,window=size,logical=size,requested=sum(w['requested']for w in schedule));continue
   if phase in('cancel-between','cancel-issued','prefetch-between'):schedule=schedule[:1]
   add('create',window=schedule[0]['logical']);logical=0;requested=0
   for w in schedule:
    requested+=w['requested'];add('issue',w['completed'],w['logical'],logical,requested)
    if phase!='cancel-issued':logical+=w['logical']
    add('take',w['completed'],w['logical'],logical,requested)
   if phase in('cancel-between','prefetch-between'):add('cancel-idle',logical,schedule[-1]['logical'],logical,requested)
   add('close',logical,schedule[-1]['logical'],logical,requested)
  controls += [[name+'-'+p,'cancelled',mode]for p,mode in(('cancel-before',0),('cancel-between',1),('cancel-issued',2),('prefetch-between',3))]+[[name+'-source-error','error',0]]
 for name,rows in(('stats',stats),('trace',trace),('controls',controls)):(directory/(name+'.tsv')).write_text(''.join('\t'.join(map(str,r))+'\n'for r in rows),encoding='utf-8')
 (directory/'loaded-modules.txt').write_text('',encoding='utf-8');positive=validate(q,directory);rejected=0
 def reject(path,data):
  nonlocal rejected
  path=directory/path;before=path.read_bytes();path.write_bytes(data)
  try:
   try:validate(q,directory)
   except(ValueError,KeyError,FileNotFoundError):rejected+=1
   else:raise AssertionError('strict mutation accepted '+path.name)
  finally:path.write_bytes(before)
 raw=(directory/'stats.tsv').read_bytes();reject(Path('stats.tsv'),b'');reject(Path('stats.tsv'),raw+raw.splitlines(keepends=True)[0]);reject(Path('stats.tsv'),raw.replace(b'174080',b'348160',1));reject(Path('stats.tsv'),raw.replace(b'1928',b'-1',1))
 raw=(directory/'trace.tsv').read_bytes();reject(Path('trace.tsv'),b'');reject(Path('trace.tsv'),b'\n'.join(raw.splitlines()[:-1])+b'\n');reject(Path('trace.tsv'),raw.replace(b'\tclose\t',b'\tmissing\t',1));reject(Path('trace.tsv'),raw.replace(b'\tissue\t1\t',b'\tissue\t2\t',1));reject(Path('trace.tsv'),raw.replace(b'\t1024\t',b'\t0\t',1))
 changed=[]
 for line in raw.decode().splitlines():
  row=line.split('\t');row[-1]='0';changed.append('\t'.join(row))
 reject(Path('trace.tsv'),('\n'.join(changed)+'\n').encode())
 for phase,event,index in(('cancel-before','cancel-idle',3),('source-error','cancel-idle',4),('cold64','close',4),('cold64','create',3),('cold64','create',4),('cancel-between','cancel-idle',3),('legacy','take',3),('legacy','close',4)):
  changed=[];mutated=False
  for line in raw.decode().splitlines():
   fields=line.split('\t')
   if not mutated and fields[0]==q['jobs'][0]['id']+'-'+phase and fields[1]==event:fields[index]='999999';mutated=True
   changed.append('\t'.join(fields))
  if not mutated:raise AssertionError('required trace mutation not reached')
  reject(Path('trace.tsv'),('\n'.join(changed)+'\n').encode())
 sample=Path(q['jobs'][0]['id']+'-cold64.bin');raw=(directory/sample).read_bytes();reject(sample,raw[:-1]);reject(sample,raw+b'x');reject(sample,bytes([raw[0]^1])+raw[1:]);reject(Path('controls.tsv'),b'')
 return dict(positive=positive,rejections=rejected,GPU_executed=False)
if __name__=='__main__':print(json.dumps(cpu()))
