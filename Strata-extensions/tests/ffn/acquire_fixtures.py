"""Bounded T11 local extraction from T05 finalized files; no HTTP/part reads."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil

EXT=Path(__file__).resolve().parents[2]
BUILD=EXT.parent/'build-deepseek-t11'
RAW=Path('C:/Develop/AI/Strata-data/records/deepseek-v41/t11-20261021/weights')
RECEIPT=Path(__file__).with_name('fixture-receipts.json')
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def context():
 path=EXT/'native/artifact/full_acquire.py'
 if sha(path)!='9a08c847f14babe13777bcd88b3ec5c1c5387097a1a10c6b485c5d2f04ce9cfd':raise ValueError('fixed T05 acquisition implementation changed')
 acquire=load('t11_readonly_t05',path);source,inventory,_=acquire.load_fixed()
 return acquire,source,inventory

def finalized(index):
 a,source,inventory=context();f=source['files'][index-1];header=inventory['shards'][index-1]
 final,part,checkpoint=a.file_paths(a.DESTINATION,f)
 if index not in (2,9) or not final.exists() or part.exists() or Path(str(final)+'.part.lock').exists():raise ValueError('only finalized shard2/9 allowed, never an active part')
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

def wanted_specs(inventory,selected=None):
 specs=[]
 if selected is None:
  for name in ('ffn_gate_inp.weight','exp_probs_b.bias','exp_probs_b_vl.bias','ffn_gate_shexp.weight','ffn_up_shexp.weight','ffn_down_shexp.weight'):
   tensor=next(t for s in inventory['shards'] for t in s['tensors'] if t['name']=='blk.0.'+name)
   specs.append((9,tensor,None))
 else:
  if not isinstance(selected,list) or not selected or len(selected)>24 or any(type(i) is not int or i<0 or i>=384 for i in selected) or selected!=sorted(set(selected)):raise ValueError('selected expert union must be sorted unique, at most24 for these four fixtures only')
  for expert in selected:
   for role in ('gate','up','down'):
    name='blk.0.ffn_'+role+'_exps.weight';tensor=next(t for s in inventory['shards'] for t in s['tensors'] if t['name']==name)
    specs.append((2,tensor,expert))
 return specs

def derive(index,tensor,expert):
 size=tensor['bytes'] if expert is None else tensor['row_bytes']*tensor['dims_ggml'][1]
 offset=tensor['absolute_offset'] if expert is None else tensor['absolute_offset']+expert*size
 if size<=0 or offset+size>tensor['absolute_offset']+tensor['bytes']:raise ValueError('slice span')
 return dict(shard_index=index,tensor=tensor['name'],type_id=tensor['type_id'],layout=tensor['layout'],dims_ggml=tensor['dims_ggml'],row_bytes=tensor['row_bytes'],
             absolute_offset=offset,bytes=size,index=expert,selection='whole' if expert is None else 'expert'+str(expert))

def verify_receipt(receipt,selected=None):
 a,source,inventory=context()
 if receipt.get('schema')!='strata-t11-local-fixtures/v1' or receipt.get('full_model_source_qualified') is not False:raise ValueError('fixture scope')
 expected=wanted_specs(inventory)+([] if selected is None else wanted_specs(inventory,selected))
 actual=receipt.get('fixtures')
 if not isinstance(actual,list) or len(actual)!=len(expected):raise ValueError('fixture coverage')
 source_cache={}
 for row,(index,tensor,expert) in zip(actual,expected,strict=True):
  derived=derive(index,tensor,expert)
  if canonical({k:row.get(k) for k in derived})!=canonical(derived):raise ValueError('fixture derived provenance changed')
  if index not in source_cache:source_cache[index]=finalized(index)[2]
  if canonical(row.get('source'))!=canonical(source_cache[index]):raise ValueError('finalized source identity changed')
  path=Path(row.get('fixture_path','')).resolve()
  if not path.is_relative_to(RAW.resolve()) or path.stat().st_size!=row['bytes'] or sha(path)!=row.get('fixture_sha256'):raise ValueError('fixture physical binding')
 if sum(r['bytes'] for r in actual)!=receipt.get('total_fixture_bytes') or receipt['total_fixture_bytes']>512*1024**2:raise ValueError('fixture sum/engineering estimate')
 return receipt

def extract(selected=None):
 a,_,inventory=context();BUILD.mkdir(exist_ok=True);RAW.mkdir(parents=True,exist_ok=True)
 with a.exclusive_writer(BUILD/'fixture-set'):
  old=json.loads(RECEIPT.read_text()) if RECEIPT.exists() else None
  if old:verify_receipt(old,old.get('selected_experts'))
  specs=wanted_specs(inventory)+([] if selected is None else wanted_specs(inventory,selected))
  total=sum(derive(*spec)['bytes'] for spec in specs)
  if total>512*1024**2:raise ValueError('T11 raw estimate exceeded; revise plan, never normal capacity gate')
  if shutil.disk_usage(RAW).free<total:raise ValueError('insufficient additional fixture space')
  rows=[];existing={(r['tensor'],r['index']):r for r in old['fixtures']} if old else {}
  for index,tensor,expert in specs:
   d=derive(index,tensor,expert)
   if (d['tensor'],expert) in existing:rows.append(existing[(d['tensor'],expert)]);continue
   _,_,origin=finalized(index);source_path=Path(origin['path'])
   name=d['tensor'].replace('.','-')+('-expert'+str(expert) if expert is not None else '')+'.bin';target=RAW/name
   # Exclusive creation preserves unknown/interrupted files, no source overwrite.
   with source_path.open('rb') as stream,target.open('xb') as out:
    stream.seek(d['absolute_offset']);remaining=d['bytes'];h=hashlib.sha256()
    while remaining:
     block=stream.read(min(remaining,1024*1024))
     if not block:raise ValueError('short original source read')
     out.write(block);h.update(block);remaining-=len(block)
    out.flush();os.fsync(out.fileno())
   if origin!=finalized(index)[2]:raise ValueError('source changed during extraction')
   rows.append(dict(d,source=origin,fixture_path=str(target),fixture_sha256=h.hexdigest()))
  receipt=dict(schema='strata-t11-local-fixtures/v1',origin='local finalized T05 file only; no HTTP',full_model_source_qualified=False,
               selected_experts=selected,total_fixture_bytes=total,fixtures=rows)
  verify_receipt(receipt,selected)
  RECEIPT.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(fixtures=len(rows),bytes=total,receipt_sha256=sha(RECEIPT),full_model_source_qualified=False)))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--selected-json',type=Path);p.add_argument('--verify',action='store_true');args=p.parse_args()
 selected=json.loads(args.selected_json.read_text())['selected_experts'] if args.selected_json else None
 if args.verify:verify_receipt(json.loads(RECEIPT.read_text()),selected);print('verified local fixture bindings only')
 else:extract(selected)
