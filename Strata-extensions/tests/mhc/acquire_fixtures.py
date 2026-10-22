"""Bounded T12 local extraction from T05 finalized files; no HTTP/part reads."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil

EXT=Path(__file__).resolve().parents[2]
BUILD=EXT.parent/'build-deepseek-t12'
RAW=Path('C:/Develop/AI/Strata-data/records/deepseek-v41/t12-20261021/weights')
RECEIPT=Path(__file__).with_name('fixture-receipts.json')
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def context():
 path=EXT/'native/artifact/full_acquire.py'
 if sha(path)!='9a08c847f14babe13777bcd88b3ec5c1c5387097a1a10c6b485c5d2f04ce9cfd':raise ValueError('fixed T05 acquisition implementation changed')
 acquire=load('t12_readonly_t05',path);source,inventory,_=acquire.load_fixed()
 return acquire,source,inventory

def finalized(index):
 a,source,inventory=context();f=source['files'][index-1];header=inventory['shards'][index-1]
 final,part,checkpoint=a.file_paths(a.DESTINATION,f)
 if index!=9 or not final.exists() or part.exists() or Path(str(final)+'.part.lock').exists():raise ValueError('only finalized shard9 allowed, never an active part')
 before=a.stat_identity(final)
 if before['bytes']!=f['bytes']:raise ValueError('source size changed')
 state=json.loads(checkpoint.read_text(encoding='utf-8'))
 identity=a.identity(f,header['http_ranges'][0]['etag'])
 if state.get('schema')!='strata-t05-part/v1' or state.get('source')!=identity or type(state.get('committed')) is not int or state['committed']!=f['bytes'] or state.get('prefix_sha256')!=f['lfs_sha256']:raise ValueError('individual acquisition checkpoint incomplete')
 a.validate_ranges(state['http_ranges'],f['bytes'],f['bytes'],identity['etag'])
 with final.open('rb') as stream:prefix=stream.read(header['prefix_bytes'])
 if hashlib.sha256(prefix).hexdigest()!=header['prefix_sha256'] or before!=a.stat_identity(final):raise ValueError('source header/stat binding changed')
 return a,header,dict(path=str(final),file_identity=before,acquisition_checkpoint=str(checkpoint),checkpoint_sha256=sha(checkpoint),
                     file_lfs_sha256=f['lfs_sha256'],filename=f['filename'],revision=source['revision'],bytes=f['bytes'],header_sha256=header['prefix_sha256'],
                     qualification='individual finalized acquisition observation and current stat/header; all9 receipt pending')

def wanted_specs(inventory):
 names=['blk.0.'+part+'.weight' for part in ('attn_norm','ffn_norm','hc_attn_fn','hc_attn_base','hc_attn_scale','hc_ffn_fn','hc_ffn_base','hc_ffn_scale')]
 shard=inventory['shards'][8]
 return [next(t for t in shard['tensors'] if t['name']==name) for name in names]

def derived(t):
 if t['type_id']!=0 or t['layout']!='F32':raise ValueError('T12 native F32 source required')
 return dict(shard_index=9,tensor=t['name'],type_id=0,layout='F32',dims_ggml=t['dims_ggml'],row_bytes=t['row_bytes'],absolute_offset=t['absolute_offset'],bytes=t['bytes'])

def verify_receipt(receipt):
 _,_,inventory=context();specs=wanted_specs(inventory)
 if receipt.get('schema')!='strata-t12-local-fixtures/v1' or receipt.get('full_model_source_qualified') is not False or not isinstance(receipt.get('fixtures'),list) or len(receipt['fixtures'])!=8:raise ValueError('T12 fixture scope/coverage')
 origin=finalized(9)[2]
 for row,t in zip(receipt['fixtures'],specs,strict=True):
  d=derived(t)
  if canonical({k:row.get(k) for k in d})!=canonical(d) or canonical(row.get('source'))!=canonical(origin):raise ValueError('T12 derived source receipt')
  path=Path(row.get('fixture_path','')).resolve()
  if not path.is_relative_to(RAW.resolve()) or path.stat().st_size!=d['bytes'] or sha(path)!=row.get('fixture_sha256'):raise ValueError('T12 physical fixture identity')
 if type(receipt.get('total_fixture_bytes')) is not int or receipt['total_fixture_bytes']!=sum(t['bytes'] for t in specs) or receipt['total_fixture_bytes']!=3973336:raise ValueError('T12 fixture total')
 return receipt

def extract():
 a,_,inventory=context();specs=wanted_specs(inventory);BUILD.mkdir(exist_ok=True);RAW.mkdir(parents=True,exist_ok=True)
 if RECEIPT.exists():verify_receipt(json.loads(RECEIPT.read_text()));print('existing fixture receipt verified');return
 with a.exclusive_writer(BUILD/'fixture-set'):
  if shutil.disk_usage(RAW).free<3973336:raise ValueError('T12 bounded fixture space')
  origin=finalized(9)[2];rows=[]
  with Path(origin['path']).open('rb') as stream:
   for t in specs:
    d=derived(t);target=RAW/(d['tensor'].replace('.','-')+'.bin');stream.seek(d['absolute_offset']);raw=stream.read(d['bytes'])
    if len(raw)!=d['bytes']:raise ValueError('short finalized read')
    with target.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    rows.append(dict(d,source=origin,fixture_path=str(target),fixture_sha256=hashlib.sha256(raw).hexdigest()))
  if origin!=finalized(9)[2]:raise ValueError('source changed during extraction')
  receipt=dict(schema='strata-t12-local-fixtures/v1',full_model_source_qualified=False,total_fixture_bytes=3973336,fixtures=rows)
  verify_receipt(receipt);RECEIPT.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(bytes=3973336,fixtures=8,receipt_sha256=sha(RECEIPT))))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');args=p.parse_args()
 if args.verify:verify_receipt(json.loads(RECEIPT.read_text()));print('verified T12 local bounded fixtures')
 else:extract()
