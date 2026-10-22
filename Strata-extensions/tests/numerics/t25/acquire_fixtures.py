"""T25 explicit bounded fixture acquisition. Never normal-runtime code."""
import hashlib,importlib.util,json,shutil,struct,sys,urllib.request,datetime
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.append('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages')
HERE=Path(__file__).parent;ROOT=HERE.parents[3];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t25'
REV='1bae0e1088993b9b82de08f59de5be5a34e42170';BASE=f'https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/{REV}/'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,v):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def record(p):p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def get(url,limit,expected=None):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept-Encoding':'identity'}),timeout=60) as r:b=r.read(limit+1)
 if len(b)!=limit or expected and hashlib.sha256(b).hexdigest()!=expected:raise ValueError('fixed source size/SHA')
 return b
def ranged(spec,start,count):
 full=module('t25_full',EXT/'native/artifact/full_acquire.py');acq=module('t25_acq',EXT/'native/artifact/acquire.py')
 req=urllib.request.Request(BASE+spec['file'],headers={'Range':f'bytes={start}-{start+count-1}','Accept-Encoding':'identity'})
 with urllib.request.urlopen(req,timeout=60) as r:
  full.validate_response(r,start,count,spec['bytes'],spec['etag'])
  raw,transport=acq.read_range_response(r,start,count,spec['bytes'],spec['etag'])
 return raw,transport
def stat(p):s=Path(p).stat();return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,device=s.st_dev,inode=s.st_ino)
def readspan(p,start,count):
 p=Path(p)
 if p.suffix=='.part' or not p.is_file() or start<0 or count<=0 or start+count>p.stat().st_size:raise ValueError('bounded final source')
 before=stat(p)
 with p.open('rb') as f:f.seek(start);b=f.read(count)
 if len(b)!=count or stat(p)!=before:raise ValueError('short/changed final source')
 return b,before
def capacity():
 rows=[s.split('\t') for s in (ROOT/'build-deepseek-t10/sources.tsv').read_text(encoding='utf-8').splitlines()];remaining=0;files=[]
 for r in rows:
  p=Path(r[4]);q=p if p.exists() else Path(str(p)+'.part');n=q.stat().st_size if q.exists() else 0;remaining+=max(0,int(r[1])-n);files.append(dict(index=int(r[0]),length=n,final_name=p.exists()))
 free=shutil.disk_usage(ROOT).free;future=6*2**30+128*2**20+3*32*2**20+2*2**30
 save(BUILD/'storage-start.json',dict(time=datetime.datetime.now().astimezone().isoformat(),free=free,remaining_model_length=remaining,metadata=2**24,future_T20_T15_T18_T19_T21_T25=future,remaining=free-remaining-2**24-future,files=files,length_not_fullSHA=True,existing_held_already_in_free=True,normal_gate=False))
def main():
 BUILD.mkdir(exist_ok=True);rawdir=BUILD/'raw';src=BUILD/'reference-source';rawdir.mkdir(exist_ok=True);src.mkdir(exist_ok=True)
 if not (BUILD/'storage-start.json').exists():capacity()
 c=read(HERE/'contract.json');specs=c['official_files'];records=[]
 for name,size,digest in [('model.safetensors.index.json',7470294,'74b0686a3d2891980d5e303251b075a3bccae2c2ff650747db2620a649b98fa8'),('inference/model.py',61669,'e5decd76fe70fd56ef2f10124d245c6f64fb6a0003cc9068a1d3182a168b8d2d'),('inference/kernel.py',23790,'1236c3507019ed176f5dba5e04bcea58867cf654818c6cf138ed4845398c2455'),('LICENSE',1084,'f2c6c602815669d292889e5be8c802f2ed950653b77999b1584e8e6aed25d040')]:
  dest=src/name;dest.parent.mkdir(parents=True,exist_ok=True)
  if not dest.exists():dest.write_bytes(get(BASE+name,size,digest))
  if sha(dest)!=digest or dest.stat().st_size!=size:raise ValueError('reference source changed')
  records.append(dict(url=BASE+name,**record(dest)))
 index=read(src/'model.safetensors.index.json')['weight_map'];official=[]
 cached=read(BUILD/'official-acquisition.json')['official'] if (BUILD/'official-acquisition.json').exists() else []
 for spec in specs:
  selected=[x for x in cached if x['source']['layer']==spec['layer']]
  if len(selected)==2:
   for x in selected:
    role=x['tensor'].split('.')[-1];offset=spec['q_start']+(40960 if role=='k_weight' else 0)
    if x['source']!=spec or x['revision']!=REV or x['absolute_offset']!=offset or index[x['tensor']]!=spec['file'] or record(x['path'])!={k:x[k] for k in ['path','bytes','sha256']}:raise ValueError('cached official receipt changed')
   header=(src/(spec['file']+'.header')).read_bytes()
   if len(header)!=8+spec['header_bytes'] or hashlib.sha256(header[8:]).hexdigest()!=spec['header_sha256']:raise ValueError('cached header changed')
   official.extend(selected);continue
  length,h0=ranged(spec,0,8)
  if struct.unpack('<Q',length)[0]!=spec['header_bytes']:raise ValueError('safetensor header length')
  header,ht=ranged(spec,8,spec['header_bytes'])
  if hashlib.sha256(header).hexdigest()!=spec['header_sha256']:raise ValueError('safetensor fixed header')
  (src/(spec['file']+'.header')).write_bytes(length+header);info=json.loads(header);start=spec['q_start']
  for role in ['q','k']:
   name=f'layers.{spec["layer"]}.engram.{role}_weight';offset=start+(40960 if role=='k' else 0);v=info[name]
   if index[name]!=spec['file'] or v['dtype']!='BF16' or v['shape']!=[4,5120] or v['data_offsets']!=[offset-8-len(header),offset+40960-8-len(header)]:raise ValueError('index/header tuple before weight body')
  combined,tr=ranged(spec,start,81920)
  for role in ['q','k']:
   name=f'layers.{spec["layer"]}.engram.{role}_weight';offset=start+(40960 if role=='k' else 0);v=info[name]
   if index[name]!=spec['file'] or v['dtype']!='BF16' or v['shape']!=[4,5120] or v['data_offsets']!=[offset-8-len(header),offset+40960-8-len(header)]:raise ValueError('index/header original tuple')
   p=rawdir/f'official-L{spec["layer"]}-{role}.bin';p.write_bytes(combined[offset-start:offset-start+40960]);official.append(dict(tensor=name,source=spec,revision=REV,absolute_offset=offset,transport=tr,whole_source_sha_verified=False,**record(p)))
 save(BUILD/'official-acquisition.json',dict(official=official,reference_sources=records))
 inv=read(EXT/'tests/artifact/header-inventory.json')
 if sha(EXT/'tests/artifact/header-inventory.json')!='08583c5cff84627962517db22ec877a69fd1aed3a811eb010d2f2f3e2f84366b':raise ValueError('T03 inventory changed')
 sources={int(r[0]):r for r in [s.split('\t') for s in (ROOT/'build-deepseek-t10/sources.tsv').read_text(encoding='utf-8').splitlines()]}
 full=module('t25_identity',EXT/'native/artifact/full_acquire.py');eight=read(ROOT/'build-deepseek-t05-worker7/before.json');nine=read(EXT/'tests/ffn/fixture-receipts.json')['fixtures'][0]['source'];final_proofs=[]
 for i,expected,proof in [(8,eight['eight_identity'],ROOT/'build-deepseek-t05-worker7/before.json'),(9,nine['file_identity'],EXT/'tests/ffn/fixture-receipts.json')]:
  actual=full.stat_identity(sources[i][4]);checkpoint=Path(sources[i][4]+'.part.json');state=read(checkpoint)
  if actual!=expected or state['committed']!=int(sources[i][1]) or state['prefix_sha256']!=sources[i][2] or state['source']['lfs_sha256']!=sources[i][2]:raise ValueError('individual finalized identity/full SHA observation changed')
  final_proofs.append(dict(index=i,current_identity=actual,recorded_observation=record(proof),checkpoint=record(checkpoint),scope='individual recorded full SHA/current identity; not all9/fullT10'))
 tensors={t['name']:(s,t) for s in inv['shards'] for t in s['tensors']};gates=[]
 for layer in [1,14]:
  name=f'blk.{layer}.engram_gate.weight';s,t=tensors[name];b,identity=readspan(sources[9][4],t['absolute_offset'],81920);p=rawdir/f'GGUF-L{layer}-gate.bin';p.write_bytes(b);gates.append(dict(tensor=name,source=t,source_file=sources[9],file_stat=identity,**record(p)))
 nq=read(ROOT/'build-deepseek-t13/nq.json');eg=module('t25_fixed_hash',EXT/'tests/engram/reference.py');ids=eg.hashes(c['tokens'],c['mask'],nq['token_map'],nq['multipliers'],nq['primes'],nq['offsets']);s,t=tensors['per_layer_token_embd.weight'];unique={};rows=[]
 for li,layer in enumerate([1,14]):
  for pos in range(8):
   for head in range(24):
    global_row=ids[pos][li*24+head];offset=t['absolute_offset']+global_row*264
    if global_row not in unique:
     b,identity=readspan(sources[8][4],offset,264);p=rawdir/f'row-{global_row}.bin';p.write_bytes(b);unique[global_row]=dict(global_row=global_row,absolute_offset=offset,file_stat=identity,**record(p))
    rows.append(dict(layer=layer,position=pos,head=head,**unique[global_row]))
 receipt=dict(schema='T25-bounded-fixtures/v1',official=official,reference_sources=records,individual_final_proofs=final_proofs,gguf_gates=gates,rows=rows,unique_rows=len(unique),row_source=t,row_file=sources[8],T13_NQ=record(ROOT/'build-deepseek-t13/nq.json'),raw_bytes=sum(p.stat().st_size for p in rawdir.glob('*.bin')),whole_HF_shard_hash_verified=False,full_T05_T10=False)
 if receipt['raw_bytes']>429056:raise ValueError('declared acquisition bytes exceeded')
 save(HERE/'fixture-receipts.json',receipt);save(BUILD/'acquisition.json',receipt);print(json.dumps(dict(raw_bytes=receipt['raw_bytes'],unique_rows=len(unique),official_bytes=163840)))
if __name__=='__main__':main()
