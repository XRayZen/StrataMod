"""Independent T22 capacity/failure expectations; candidate math/output not imported."""
import math

def integer(value,positive=False):
 if type(value)is not int or value<0 or positive and value==0:raise ValueError('strict integer capacity')
 return value

def slots(target_bytes,tile_bytes):
 integer(target_bytes,True);integer(tile_bytes,True)
 if tile_bytes>2**64-256:raise ValueError('aligned tile overflow')
 unit=(tile_bytes+255)&~255
 if target_bytes<unit:raise ValueError('explicit target below working minimum')
 count=target_bytes//unit
 return dict(slots=count,capacity=count*unit,unused=target_bytes-count*unit)

def target(explicit,available,minimum,fraction):
 integer(minimum,True)
 if type(fraction)not in(int,float)or not math.isfinite(fraction)or not 0<=fraction<=1:raise ValueError('auto fraction [0,1]')
 if explicit is not None:return integer(explicit,True)
 if available is not None:integer(available)
 return minimum+math.floor((available or 0)*fraction)

def disjoint(a,b):
 def extent(pair):
  first,size=pair;integer(first,True);integer(size,True)
  if first>2**64-1 or size>2**64-1-first:raise ValueError('address overflow')
  return first,first+size
 x,y=extent(a),extent(b)
 return x[1]<=y[0]or y[1]<=x[0]

def recovery(reason,primary_drain,retained,separate):
 if type(primary_drain)is not int or type(retained)is not bool or type(separate)is not bool:raise ValueError('strict recovery facts')
 if reason=='copy_unknown':return 'bypass_retained'if primary_drain==0 and retained and separate else 'error_retain'
 if reason in ('allocation','copy_drained'):return 'bypass'if primary_drain==0 and separate else 'error_retain'
 return 'error'

def tile_key(values):
 if len(values)!=11:raise ValueError('all original tile key axes required')
 return tuple(values)
def bound_input(accepted,path):
 from pathlib import Path
 import hashlib
 path=Path(path).resolve();matches=[row for row in accepted['inputs']if Path(row['path']).resolve()==path]
 if len(matches)!=1:raise ValueError('one accepted original input record required')
 record=matches[0];data=path.read_bytes()
 if type(record['bytes'])is not int or record['bytes']!=len(data)or hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('accepted original input bytes/SHA')
 return data

def unit_expected(root,destination):
 """Slice independently sealed T20 pre-G Q; never read a candidate capture."""
 from pathlib import Path
 import hashlib,json,shutil,struct
 root=Path(root);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
 capture=root/'build-deepseek-t20/owner-attempt-4/captured-Q-manifest.json'
 if hashlib.sha256(capture.read_bytes()).hexdigest()!='fdfa0a9bf0c0bb12b3cba716f23a70357a515ef79b104f6d6e1f0b53b8821e2b':raise ValueError('accepted immutable Q manifest')
 accepted=json.loads(capture.read_text(encoding='utf-8'));records=[];inputs=[];jobs=[]
 tables={name:bound_input(accepted,root/'build-deepseek-t20/owner-input'/name)for name in('sources.tsv','prefixes.tsv')}
 for job in accepted['jobs']:
  if job['id']not in('p0','p16'):continue
  name=job['id'];qpath=root/'build-deepseek-t20/owner-q'/f'{name}.bin';data=qpath.read_bytes()
  if hashlib.sha256(data).hexdigest()!=job['expected_sha256']or len(data)!=job['expected_bytes']:raise ValueError('sealed independent Q bytes')
  xp=root/'build-deepseek-t20/owner-input'/f'{name}-x.bin';x=xp.read_bytes()
  if hashlib.sha256(x).hexdigest()!=job['input_sha256']:raise ValueError('original activation binding')
  target=destination/'input'/xp.name;target.parent.mkdir(exist_ok=True);target.write_bytes(x);inputs.append(dict(path=str(target),sha256=hashlib.sha256(x).hexdigest(),bytes=len(x)))
  for phase in ('ssd','local','ram','fill','secondary','after-cancel','copy-failed-fallback','next-tile','first-again'):
   first=8 if phase=='next-tile'else 0
   expected=b''.join(data[(b*job['rows']+first)*4:(b*job['rows']+first+8)*4]for b in range(job['batch']))
   qp=destination/'q'/f'{name}-{phase}.bin';qp.parent.mkdir(exist_ok=True);qp.write_bytes(expected)
   records.append(dict(name=qp.name,path=str(qp),sha256=hashlib.sha256(expected).hexdigest(),bytes=len(expected),scalar='Float32',rows=3,columns=8,source=name,phase=phase,row_first=first))
  saved={k:job[k]for k in('id','tensor','matrix','batch','k','rows','type','source_index','source_path','source_size','source_sha256','offset','bytes','input_sha256','expected_sha256')}
  sources=[line.split('\t')for line in tables['sources.tsv'].decode('utf-8').splitlines()];source=next(x for x in sources if int(x[0])==job['source_index']);saved['tile_keys']={str(first):'|'.join(map(str,(source[3],source[2],source[4],job['tensor'],job['type'],8,job['k'],job['offset']+first*(job['bytes']//job['rows']),8*(job['bytes']//job['rows']))))for first in(0,8)}
  jobs.append(saved)
 for name in ('sources.tsv','prefixes.tsv'):
  target=destination/'input'/name;data=tables[name];target.write_bytes(data);inputs.append(dict(path=str(target),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
 unknown=[];first=next(x for x in records if x['name']=='p0-fill.bin');data=Path(first['path']).read_bytes()
 for phase in('unknown-warmup','unknown-fallback','unknown-after-late','unknown-next'):
  qp=destination/'unknown-q'/f'{phase}.bin';qp.parent.mkdir(exist_ok=True);qp.write_bytes(data);unknown.append(dict(name=qp.name,path=str(qp),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),scalar='Float32',rows=3,columns=8,source='p0',phase=phase,row_first=0))
 result=dict(schema='T22-storage-unit-Q/v1',GPU_executed=False,original_Q_manifest=dict(path=str(capture),sha256=hashlib.sha256(capture.read_bytes()).hexdigest()),inputs=inputs,jobs=jobs,outputs=records,output_values=sum(x['bytes']//4 for x in records),unknown_outputs=unknown,unknown_output_values=sum(x['bytes']//4 for x in unknown),normal_HTTP_qualified=False)
 p=destination/'manifest.json';p.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');return result
def dram_selection(available,current_payload,minimum,deferred=0):
 """Test-only checked explicit owner budget; no allocation or normal defaults."""
 target=8589934592;upper=9663676416;aim=9126805504
 for value in(current_payload,minimum,deferred):
  if type(value)is not int or not 0<=value<2**64:raise ValueError('checked DRAM observation/bytes')
 if not minimum or current_payload<minimum:raise ValueError('actual working minimum')
 if available is None:return dict(condition='unknown',reason='physical available unavailable; keep safe working owner and report',payload=current_payload)
 if type(available)is not int or not 0<=available<2**64:raise ValueError('checked DRAM observation/bytes')
 if target<=available<=upper:return dict(condition='candidate',reason='current owner already in band',payload=current_payload)
 candidate=current_payload+(available-aim)-deferred
 if not minimum<=candidate<2**64:return dict(condition='not_met',reason='no legal larger working owner target; keep safe owner and report',payload=current_payload)
 return dict(condition='candidate',reason='capture-before explicit reselection required',payload=candidate)

def dram_observed_condition(samples,required):
 if set(samples)!=set(required):return 'unknown'
 values=[samples[key]for key in required]
 if any(value is None for value in values):return 'unknown'
 for value in values:
  if type(value)is not int or value<0:raise ValueError('physical available observation')
 return 'met_at_observed_points'if all(8589934592<=value<=9663676416 for value in values)else'not_met'
