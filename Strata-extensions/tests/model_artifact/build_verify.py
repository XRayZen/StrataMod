"""T10 structural adapter qualification; offline preparation never qualifies full source."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[3]
EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t10'
OWN=[EXT/'models/deepseek41'/p for p in ('artifact.hpp','artifact.cpp')]+[Path(__file__).with_name('artifact_fixture.cpp')]
RECIPES=[Path(__file__),Path(__file__).with_name('CMakeLists.txt'),EXT/'tests/native/build_verify.py']
CONFIG=EXT/'models/deepseek41/reference-config.json'
BASE='477ac13cbe8e582c20484871ce459d20d82df09d'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(paths):return [dict(path=str(p),sha256=sha(p)) for p in paths]
def aggregate(r):return hashlib.sha256(''.join(x['path']+'|'+x['sha256']+'\n' for x in r).encode()).hexdigest()
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def run(args,env=None):
 r=subprocess.run([str(x) for x in args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
 if r.returncode:raise RuntimeError(str(args)+'\n'+r.stdout+r.stderr)
 return r

def binding(m,exe):
 if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE or run(['git','diff','--name-only','HEAD']).stdout.strip():raise ValueError('base changed')
 if rows(OWN)!=m['owned'] or rows(RECIPES)!=m['recipes'] or aggregate(m['owned'])!=m['owned_aggregate']:raise ValueError('source identity')
 for key in ('owned','recipes','inputs','vendor','tools','licenses','direct_dlls'):
  if any(sha(r['path'])!=r['sha256'] for r in m[key]):raise ValueError('bound file changed: '+key)
 if sha(exe)!=m['artifact']['sha256'] or json.loads(run([exe,'--identity']).stdout)['source_sha256']!=m['owned_aggregate']:raise ValueError('binary identity')

def manifest_binding(path,expected):
 if sha(path)!=expected:raise ValueError('disk manifest changed during verification')

def verify(m,exe,full,manifest_path,manifest_sha):
 manifest_binding(manifest_path,manifest_sha)
 binding(m,exe)
 run([sys.executable,'-B',EXT/'native/artifact/acquire.py','--raw-root','C:/Develop/AI/Strata-data/records/deepseek-v41/t03-20261021','--receipt-root',EXT/'tests/artifact','--verify'])
 inv=json.loads((EXT/'tests/artifact/header-inventory.json').read_text());config=json.loads(CONFIG.read_text())
 if sha(CONFIG)!='8be45ce0476004a3f529fd896115a4a2e800a129ad2d3ec05b16050f52e21879':raise ValueError('fixed official config changed')
 text=config['text_config']
 if (text['hidden_size'],text['num_hidden_layers'],text['n_routed_experts'],text['num_experts_per_tok'],text['engram_num_embeddings'])!=(5120,40,384,6,[384006168,384016682]):raise ValueError('config crosscheck')
 output=BUILD/'offline-index.tsv';report=json.loads(run([exe,BUILD/'nine-prefixes.tsv',BUILD/'sources.tsv',output]).stdout)
 got=output.read_text().splitlines();expected=[]
 source=json.loads((EXT/'tests/artifact/source-files.json').read_text());source_rows=[line.split('\t') for line in (BUILD/'sources.tsv').read_text().splitlines()]
 for shard in inv['shards']:
  for t in shard['tensors']:expected.append('\t'.join(str(x) for x in [shard['index'],t['name'],t['type_id'],t['absolute_offset'],t['bytes'],t['row_bytes'],*t['dims_ggml'],Path(source_rows[shard['index']-1][4]).as_posix(),shard['bytes'],shard['lfs_sha256'],inv['revision']]))
 if got[:1043]!=expected or report['tensor_count']!=1043 or report['assertions']<350 or report['full_source_qualified'] is not False:raise ValueError('all1043 index mismatch')
 meta=inv['shards'][0]['metadata_arrays'];offsets=meta['deepseek41.ple.head_offsets']['values'];sizes=meta['deepseek41.ple.head_vocab_sizes']['values'];table=next(t for s in inv['shards'] for t in s['tensors'] if t['name']=='per_layer_token_embd.weight')
 slices=[]
 tensors={t['name']:t for shard in inv['shards'] for t in shard['tensors']}
 for layer in range(40):
  for role in ('gate','up','down'):
   t=tensors[f'blk.{layer}.ffn_{role}_exps.weight'];expert_bytes=6266880
   for expert in (0,383):slices.append('\t'.join(str(x) for x in ['expert',layer,role,expert,t['absolute_offset']+expert*expert_bytes,expert_bytes]))
 for layer,start in [(1,0),(14,24)]:
  for head in range(24):
   for row in (0,sizes[start+head]-1):slices.append('\t'.join(str(x) for x in ['slice',layer,head,row,table['absolute_offset']+(offsets[start+head]+row)*264,264]))
 if got[1043:]!=slices:raise ValueError('independent head boundary formula mismatch')
 cases=[]
 for key in ('source','binary','aggregate','input'):
  bad=copy.deepcopy(m)
  if key=='source':bad['owned'][0]['sha256']='0'*64
  elif key=='binary':bad['artifact']['sha256']='0'*64
  elif key=='aggregate':bad['owned_aggregate']='0'*64
  else:bad['inputs'][0]['sha256']='0'*64
  try:binding(bad,exe)
  except ValueError:cases.append(key)
  else:raise ValueError('mutation passed')
 copy_path=BUILD/'manifest-negative-copy.json';copy_path.write_bytes(manifest_path.read_bytes()+b' ')
 try:manifest_binding(copy_path,manifest_sha)
 except ValueError:cases.append('disk-manifest-change')
 else:raise ValueError('manifest mutation passed')
 manifest_binding(manifest_path,manifest_sha)
 if full:
  receipt=EXT/'tests/artifact/full-model-receipt.json'
  if not receipt.exists():raise ValueError('T05 full-source dependency not yet fulfilled')
  # Explicit qualification, never called by normal runtime/start. T05 validator
  # must succeed before full-source headers can be semantic qualification input.
  run([sys.executable,'-B',EXT/'native/artifact/full_acquire.py','--verify-receipt'])
  receipt_sha=sha(receipt);data=json.loads(receipt.read_text())
  source_list=BUILD/'full-source.tsv';source_list.write_text(''.join(str(r['bytes'])+'\t'+r['path']+'\n' for r in data['files']),encoding='utf-8')
  full_output=BUILD/'full-source-index.tsv';native=json.loads(run([exe,source_list,BUILD/'sources.tsv',full_output]).stdout)
  if full_output.read_bytes()!=output.read_bytes() or native!=report:raise ValueError('full-source semantic index differs from T03-bound adapter')
  run([sys.executable,'-B',EXT/'native/artifact/full_acquire.py','--verify-receipt'])
  if sha(receipt)!=receipt_sha:raise ValueError('full receipt changed during qualification')
  binding(m,exe);manifest_binding(manifest_path,manifest_sha)
  return dict(manifest_sha256=manifest_sha,owned_aggregate=m['owned_aggregate'],artifact_sha256=m['artifact']['sha256'],scope='T10 full-source structural adapter qualification; no model numerics/generation',full_source_qualified=True,
              receipt=dict(path=str(receipt),sha256=receipt_sha),sources=[dict(path=r['path'],file_identity=r['file_identity'],sha256_acquisition=r['sha256']) for r in data['files']],
              native=report,indexed_tensors=1043,head_boundary_slices=96,expert_boundary_slices=240,binding_negatives=cases,GPU_used=False)
 binding(m,exe);manifest_binding(manifest_path,manifest_sha)
 return dict(manifest_sha256=manifest_sha,owned_aggregate=m['owned_aggregate'],artifact_sha256=m['artifact']['sha256'],scope='offline strict-header structural adapter preparation; T05 dependency outstanding',full_source_qualified=False,
             native=report,indexed_tensors=1043,head_boundary_slices=96,expert_boundary_slices=240,binding_negatives=cases,tokenizer=dict(gguf_pre='joyai-llm',gguf_pad=1,official_pad=2,engram_pad=2,compatible=None,compatibility_qualified=False),
             draft_vision='Independent names not detected in current inventory; DSpark shared/reuse mapping and image assets not qualified; no permanent absence claim',GPU_used=False)

def main():
 p=argparse.ArgumentParser();p.add_argument('--verify-only',action='store_true');p.add_argument('--qualify-full',action='store_true');a=p.parse_args()
 BUILD.mkdir(exist_ok=True);bundle=BUILD/'bundle-offline-r7';bundle.mkdir(exist_ok=True);exe=bundle/'t10_model_artifact.exe';manifest=bundle/'manifest.json'
 if a.verify_only:
  manifest_raw=manifest.read_bytes();m=json.loads(manifest_raw);result=verify(m,exe,a.qualify_full,manifest,hashlib.sha256(manifest_raw).hexdigest())
  if a.qualify_full:(bundle/'full-source-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
  print(json.dumps(result));return
 if manifest.exists():raise ValueError('fixed manifest exists; --verify-only required')
 license_url='https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/1bae0e1088993b9b82de08f59de5be5a34e42170/LICENSE'
 with urllib.request.urlopen(license_url,timeout=20) as response:license_raw=response.read(32769)
 if len(license_raw)!=1084 or hashlib.sha256(license_raw).hexdigest()!='f2c6c602815669d292889e5be8c802f2ed950653b77999b1584e8e6aed25d040':raise ValueError('fixed DeepSeek license changed')
 (bundle/'DeepSeek-LICENSE.txt').write_bytes(license_raw)
 shutil.copy2(EXT/'native/artifact/NOTICE.md',bundle/'NOTICE.md')
 tools,env=load('t10_t06_tools',EXT/'tests/native/build_verify.py').toolchain(BUILD)
 owned=rows(OWN);identity=aggregate(owned);cmake=BUILD/'cmake-native'
 try:
  configured=run([tools['cmake'],'-S',Path(__file__).parent,'-B',cmake,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',f'-DCMAKE_CXX_COMPILER={tools["compiler"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["resource_compiler"].as_posix()}',f'-DCMAKE_MT={tools["manifest_tool"].as_posix()}',f'-DCMAKE_LINKER={tools["linker"].as_posix()}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DT10_SOURCE_SHA={identity}'],env)
  built=run([tools['cmake'],'--build',cmake],env)
 except Exception as e:(BUILD/'build-failure.log').write_text(str(e),encoding='utf-8');raise
 (BUILD/'build.log').write_text(configured.stdout+configured.stderr+built.stdout+built.stderr,encoding='utf-8');shutil.copy2(cmake/'t10_model_artifact.exe',exe)
 inv=json.loads((EXT/'tests/artifact/header-inventory.json').read_text());prefixes=BUILD/'nine-prefixes.tsv';prefixes.write_text(''.join(str(s['bytes'])+'\t'+s['prefix_path']+'\n' for s in inv['shards']),encoding='utf-8')
 vendor=[ROOT/'include/strata/artifact'/p for p in ('gguf_reader.hpp','gguf_split.hpp','dequant.hpp','model_family.hpp')]+[ROOT/'include/strata/core/geometry.hpp',EXT/'native/artifact/native_reader.hpp',EXT/'native/artifact/native_reader.cpp']
 source=json.loads((EXT/'tests/artifact/source-files.json').read_text());source_table=BUILD/'sources.tsv';destination=Path('C:/Develop/AI/Model/DeepSeek-V4.1-Flash-1017-GGUF/f924b94f19c1fea02c06a65c8475b0a45e2b88b1/UD-Q4_K_XL')
 source_table.write_text(''.join('\t'.join(str(x) for x in [f['index'],f['bytes'],f['lfs_sha256'],source['revision'],destination/Path(f['filename']).name])+'\n' for f in source['files']),encoding='utf-8')
 inputs=[CONFIG,prefixes,source_table,EXT/'tests/artifact/source-files.json',EXT/'tests/artifact/header-inventory.json',EXT/'native/artifact/acquire.py',EXT/'native/artifact/gguf.py',EXT/'native/artifact/full_acquire.py',EXT/'tests/artifact/test_full_acquire.py',EXT/'native/artifact/quant_layouts.json',EXT/'tests/artifact/fixture-receipts.json']+[Path(s['prefix_path']) for s in inv['shards']]
 imports=run([tools['dumpbin'],'/DEPENDENTS',exe]).stdout;dlls=[Path(os.environ['SystemRoot'])/'System32'/n for n in sorted(set(re.findall(r'^\s+([\w.-]+\.dll)\s*$',imports,re.M|re.I)))]
 m=dict(schema='strata-t10-offline-host/v1',upstream_base=BASE,owned=owned,owned_aggregate=identity,recipes=rows(RECIPES),vendor=rows(vendor),inputs=rows(inputs),tools=rows(list(tools.values())+[Path(sys.executable)]),licenses=rows([ROOT/'LICENSE',ROOT/'third_party/ggml/LICENSE',EXT/'native/artifact/NOTICE.md',bundle/'NOTICE.md',bundle/'DeepSeek-LICENSE.txt']),direct_dlls=rows(dlls),artifact=dict(path=str(exe),sha256=sha(exe)),source_config=dict(url='https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/1bae0e1088993b9b82de08f59de5be5a34e42170/config.json',sha256=sha(CONFIG)),full_source_qualified=False)
 manifest.write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8');result=verify(m,exe,a.qualify_full,manifest,sha(manifest));(bundle/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
