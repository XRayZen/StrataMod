"""Independent partition/transport expectations; no candidate executor/G imports."""
from pathlib import Path
import hashlib,json

def integer(x,positive=False):
 if type(x)is not int or x<0 or positive and not x:raise ValueError('strict nonnegative integer')
 return x

def ranges(cut):
 integer(cut,True)
 if cut>=40:raise ValueError('one internal cut')
 return [(0,cut),(cut,40)]

def writer(layer):
 return 40 if layer<2 else 2 if layer<8 else 8 if layer<14 else 14 if layer<20 else 20

def index_writer(layer):
 return writer(layer)if layer<20 else 20+(layer-20)//4*4

def cross_edges(cut):
 ranges(cut);cache=set();selected=set();candidates=set()
 for layer in range(cut,40):
  source=writer(layer);selection=index_writer(layer)
  if source<cut:cache.add(source)
  if selection<cut:selected.add(selection)
  if layer in(24,28,32,36)and 20<cut:candidates.add(20)
 return dict(cache=sorted(cache),selected=sorted(selected),candidates=sorted(candidates))

def delta(ratio,mirrored,published):
 integer(ratio,True);integer(mirrored);integer(published)
 if ratio not in(1,2)or mirrored>published:raise ValueError('writer ratio or nonmonotonic publication')
 n=published-mirrored
 return dict(first=mirrored,rows=n,kv_bytes=n*512*4,key_bytes=n*128*4)

def selected_bytes(rows):return min(integer(rows),512)*4

def cut24_bytes(tokens):
 integer(tokens,True);h=tokens*(20480+4)*4;k=tokens*512*4;keys=tokens*128*4;c=tokens*(tokens+1)//2*4
 return dict(residual_pre=h,new_kv=k,new_keys=keys,candidates=c,total=h+k+keys+c)

def tap_bytes(batch,sequence):return integer(batch,True)*integer(sequence,True)*15360*4

def fixed_reference(manifest):
 p=Path(manifest);raw=p.read_bytes()
 if hashlib.sha256(raw).hexdigest()!='afef342a7a9410fb5202f9c86bcf4e95ba0b5f8f7d9965ac5d6017879039bb0c':raise ValueError('accepted immutable single Q')
 q=json.loads(raw)
 if q['tokens']!=[3,37,1024]or len(q['frames'])!=120:raise ValueError('full teacher forcing source')
 return dict(source=dict(path=str(p.resolve()),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()),tokens=q['tokens'],frames=q['frames'],outputs=q['outputs'],cut=24,role_frames=dict(primary=72,secondary=48),cross_edges=cross_edges(24),operational=cut24_bytes(3),expected_generated_from_candidate=False)


def checked(item):
 p=Path(item['path']);raw=p.read_bytes()
 if len(raw)!=item['bytes']or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('immutable expected bytes/SHA')
 return raw

def seal_reference(manifest,directory,oracle_root):
 import importlib.util,numpy as np
 q=fixed_reference(manifest);original=json.loads(Path(manifest).read_text(encoding='utf-8'));out=Path(directory);out.mkdir(parents=True,exist_ok=True)
 def entry(position,name,raw,shape,scalar):
  p=out/(str(position)+'-boundary-'+name+'.bin');p.write_bytes(raw)
  return dict(position=position,name=name,path=str(p.resolve()),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),shape=shape,scalar=scalar)
 stages={ (f['position'],f['layer'],s['name']):s for f in q['frames']for s in f['stages']}
 for e in stages.values():checked(e)
 for e in q['outputs']:checked(e)
 source=Path(oracle_root)/'Strata-extensions/tests/numerics/t25/reference.py'
 if hashlib.sha256(source.read_bytes()).hexdigest()!='f3bc0e942ee9d523e20b4269d70cf3bc7a553b8089d738d1f19227d16d1b69bc':raise ValueError('accepted independent graph')
 sp=importlib.util.spec_from_file_location('t45_original_independent',source);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);oracle=m.ActualOracle(oracle_root)
 boundaries=[];cache=[];keys=[]
 for pos in range(3):
  latent=np.frombuffer(checked(stages[pos,20,'compression_pre_rope']),'<f4').reshape(1,512)
  rotated=oracle.kv.rope(latent,np.array([pos],np.int64),1);compressed=oracle.kv.fp4_qdq(rotated)[0];cache.append(compressed[0])
  key=m.bf16(oracle.linear('blk.20.indexer.attn_k.weight',latent));key=oracle.norm(key,'blk.20.indexer.k_norm.weight');key=oracle.att.rotary(key,np.array([pos],np.int64));key=oracle.att.fp4_index_qdq(key)[0];keys.append(key[0])
  boundaries.extend([entry(pos,'residual',checked(stages[pos,23,'block_output']),[1,20480],2),entry(pos,'pre',checked(stages[pos,23,'block_next_pre']),[1,4],0),entry(pos,'0-20',np.asarray(cache,'<f4').tobytes(),[pos+1,512],2),entry(pos,'1-20',np.asarray(keys,'<f4').tobytes(),[pos+1,128],2),entry(pos,'3-20',checked(stages[pos,20,'index_score']),[1,pos+1],0)])
 # The accepted allocation table is re-partitioned by actual ownership. Common
 # workspaces remain physically allocated on each role; constants are per-use.
 life=original['allocation_lifetimes'];common=sum(x[3]for x in life if not x[0].startswith(('SWA40-','compress-pending-','compressed-KV-','index-key-')))
 constants=original['constant_source'];cp=sum(x['bytes']for x in constants if x['name'].startswith('blk.')and int(x['name'].split('.')[1])<24);cs=sum(x['bytes']for x in constants)-cp
 storage_p=common+24*128*512*4+8*4096+(3*1+3)*512*4+(3*1+3)*128*4+cp
 storage_s=common+16*128*512*4+3*512*4+3*128*4+cs
 q.update(cache=cache_reference(original,oracle.inventory),schema='T45-independent-cut24-v1',GPU_used=False,expected_generated_from_candidate=False,expected_stages=[dict(position=f['position'],layer=f['layer'],**s)for f in q['frames']for s in f['stages']],boundaries=boundaries,independent_boundary_reads=oracle.reads,independent_boundary_diagnostics=oracle.diagnostics,core_storage=dict(primary=storage_p,secondary=storage_s),constant_source=dict(primary=cp,secondary=cs),expected_owned=dict(primary=storage_p+4194816+8448,secondary=storage_s+4194816),copy_sizes={str(pos):[81920,16,2048,512,(pos+1)*4]for pos in range(3)},ordinary_intermediate_audit=False)
 (out/'manifest.json').write_text(json.dumps(q,indent=2)+'\n',encoding='utf-8');return q


def cache_reference(q,inventory):
 import math
 tensors={t['name']:t for shard in inventory['shards']for t in shard['tensors']}
 constants={x['name']for x in q['constant_source']};requests=[];pos=-1
 for call in q['FP64_diagnostics']:
  if 'tensor'not in call:continue
  name=call['tensor']
  if name=='blk.0.hc_attn_fn.weight':
   pos+=1;t=tensors['token_embd.weight'];requests.append(('primary','token_embd.weight',t['absolute_offset']+q['tokens'][pos]*t['row_bytes'],t['row_bytes']))
  if name in constants:continue
  t=tensors[name];k,n=t['dims_ggml'][:2];row=t['row_bytes'];chunk=min(256,2097152//row)
  if chunk<=0 or call['K']!=k:raise ValueError('qualified full-K rowtile')
  side='primary'if name.startswith('blk.')and int(name.split('.')[1])<24 else 'secondary'
  for first in range(0,call['count'],chunk):
   count=min(chunk,call['count']-first);offset=t['absolute_offset']+(call['matrix']*n+call['first']+first)*row
   if offset<t['absolute_offset']or count*row>t['bytes']-(offset-t['absolute_offset']):raise ValueError('source tile span')
   requests.append((side,name,offset,count*row))
 result={}
 for side in ('primary','secondary'):
  gpu=[None,None];ram=[None,None];total=dict(weight_read=0,weight_h2d=0,aligned_read=0,issued_reads=0,gpu_hits=0,ram_hits=0,ssd_misses=0,tiles=0)
  for role,name,offset,size in requests:
   if role!=side:continue
   key=(name,offset,size);total['tiles']+=1
   if key in gpu:total['gpu_hits']+=1;continue
   if key in ram:total['ram_hits']+=1
   else:
    total['ssd_misses']+=1;total['weight_read']+=size;aligned=(offset%4096+size+4095)//4096*4096;total['aligned_read']+=aligned;total['issued_reads']+=(aligned+65535)//65536;ram[ram.index(None)if None in ram else 0]=key
   total['weight_h2d']+=size;gpu[gpu.index(None)if None in gpu else 0]=key
  result[side]=total
 return result


def small_reference(directory):
 import struct
 out=Path(directory);out.mkdir(parents=True,exist_ok=True);result={};old=0
 def record(p,raw):p.write_bytes(raw);return dict(path=str(p.resolve()),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
 kv=b''.join(struct.pack('<f',i%29-14)for i in range(1024));keys=b''.join(struct.pack('<f',i%13-6)for i in range(256));selected=struct.pack('<ii',129,128)
 for pos in range(4):
  rows=(pos+1)//2
  for kind,width,raw in [(0,512,kv),(1,128,keys),(2,1,selected)]:
   raw=struct.pack('<ii',128 if rows<2 else 129,128)if kind==2 else raw;valid=rows*width*4;delta=valid if kind==2 else(rows-old)*width*4;file=f'{pos}-small-{kind}.bin';e=record(out/file,raw[:valid]);e.update(file=file,metadata=[2,2,3,rows,delta,valid]);result[f'{pos}:{kind}']=e
  old=rows
 # Exact independent binary32/BF16 ties: -0, 2.5, 0.501953125->0.5 RNE.
 raw=b''.join(struct.pack('<I',[0x80000000,0x40200000,0x3f000000][(i//5120+i%3)%3])for i in range(15360))
 return dict(small_outputs=result,tap=record(out/'tap.bin',raw),GPU_used=False,source='controlled metadata/HCmean host contract; not real compression math or actual target tap extraction')
