"""Explicit T05 single-copy acquisition; never invoked by normal runtime startup."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

EXT=Path(__file__).resolve().parents[2]
RECEIPTS=EXT/'tests/artifact'
REPO='unsloth/DeepSeek-V4.1-Flash-1017-GGUF'
REVISION='f924b94f19c1fea02c06a65c8475b0a45e2b88b1'
DESTINATION=Path('C:/Develop/AI/Model/DeepSeek-V4.1-Flash-1017-GGUF')/REVISION/'UD-Q4_K_XL'
CHUNK_BYTES=256*1024*1024
BUFFER_BYTES=1024*1024
METADATA_ALLOWANCE=16*1024*1024  # Acquisition metadata estimate, not runtime headroom.
FIXED_INPUTS={'source-files.json':'3c226d451f4b3a0b6b12b69fab492e559226bc23c6d02fcf926964bf33178ec6',
 'header-inventory.json':'08583c5cff84627962517db22ec877a69fd1aed3a811eb010d2f2f3e2f84366b',
 'fixture-receipts.json':'209bd9447056589998024b5cdb5a9d23c4a29fad281e11db30f201cd048df88b'}

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def stamp():return datetime.now(timezone.utc).isoformat()

def stat_identity(path):
    s=Path(path).stat()
    return dict(device=s.st_dev,file_id=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns)

def safe_directory(path):
    path=Path(path).absolute()
    for parent in (path,*path.parents):
        if parent.exists() and (parent.is_symlink() or getattr(parent.stat(),'st_file_attributes',0)&0x400):
            raise ValueError('model placement must not traverse a reparse point')
    return path

def file_paths(root,row):
    name=Path(row['filename']).name
    if not name or name in ('.','..') or '\\' in row['filename'] or '..' in row['filename'].split('/'):
        raise ValueError('unsafe model filename')
    final=Path(root)/name
    for path in (final,Path(str(final)+'.part'),Path(str(final)+'.part.json'),Path(str(final)+'.part.json.tmp')):
        if path.exists() and (path.is_symlink() or getattr(path.stat(),'st_file_attributes',0)&0x400 or not path.is_file()):
            raise ValueError('model path is not a regular owned file')
    return final,Path(str(final)+'.part'),Path(str(final)+'.part.json')

def identity(row,etag):
    return dict(repo=REPO,revision=REVISION,filename=row['filename'],bytes=row['bytes'],lfs_sha256=row['lfs_sha256'],etag=etag)

@contextmanager
def exclusive_writer(final):
    """One explicit acquisition transaction per source; crash releases the OS handle."""
    if os.name!='nt':raise ValueError('T05 writer locking is qualified on Windows only')
    lock=Path(str(final)+'.part.lock')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel.CreateFileW
    create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype=wintypes.HANDLE
    close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    # CREATE_NEW cannot delete an unrelated stale file. DELETE_ON_CLOSE also
    # removes the zero-byte lock if the acquisition process crashes.
    handle=create(str(lock),0xC0010000,0,None,1,0x04000080,None)
    if handle==ctypes.c_void_p(-1).value:
        error=ctypes.get_last_error()
        if error in (32,33,80,183):raise ValueError('T05 acquisition busy or unknown lock file; part/checkpoint unchanged')
        raise ctypes.WinError(error)
    try:yield
    finally:close(handle)

def checkpoint_owner_prefix(source):
    return ('{"schema":"strata-t05-part/v1","source":'+json.dumps(source,sort_keys=True,separators=(',',':'))+',').encode('utf-8')

def recover_checkpoint_temporary(path,source):
    temporary=Path(str(path)+'.tmp')
    if not temporary.exists():return
    prefix=checkpoint_owner_prefix(source)
    # Called only under the OS writer lock after the old checkpoint and its
    # committed raw prefix have been verified. A complete ownership header can
    # identify our interrupted metadata body; unknown/partial headers stay put.
    if (temporary.is_symlink() or getattr(temporary.stat(),'st_file_attributes',0)&0x400
            or temporary.stat().st_size>METADATA_ALLOWANCE):raise ValueError('unknown checkpoint temporary; preserved')
    with temporary.open('rb') as stream:owned=stream.read(len(prefix))==prefix
    if not owned:raise ValueError('unknown checkpoint temporary; preserved')
    temporary.unlink()

def checkpoint(path,state):
    temporary=Path(str(path)+'.tmp')
    # A crash-left metadata temporary is preserved for inspection, not clobbered.
    if temporary.exists():raise ValueError('checkpoint temporary already exists; preserved')
    with temporary.open('xb') as stream:
        stream.write(checkpoint_owner_prefix(state['source']));stream.flush();os.fsync(stream.fileno())
        rest={k:v for k,v in state.items() if k not in ('schema','source')}
        stream.write(json.dumps(rest,separators=(',',':')).encode()[1:]+b'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)

def hash_prefix(path,length):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        remaining=length
        while remaining:
            raw=stream.read(min(BUFFER_BYTES,remaining))
            if not raw:raise ValueError('committed prefix physically short')
            digest.update(raw);remaining-=len(raw)
    return digest

def validate_response(response,start,length,total,etag):
    if response.status!=206:raise ValueError('HTTP206 required; response body not read')
    expected=f'bytes {start}-{start+length-1}/{total}'
    if (response.headers.get('Content-Range')!=expected or response.headers.get('Content-Length')!=str(length)
            or response.headers.get('ETag')!=etag or response.headers.get('Content-Encoding','identity')!='identity'):
        raise ValueError('range/total/length/ETag/encoding mismatch; body not read')

def download_file(row,root,etag,*,open_url=urllib.request.urlopen,chunk_bytes=CHUNK_BYTES):
    root=safe_directory(root);root.mkdir(parents=True,exist_ok=True)
    final,_,_=file_paths(root,row)
    with exclusive_writer(final):
        return _download_locked(row,root,etag,open_url=open_url,chunk_bytes=chunk_bytes)

def _download_locked(row,root,etag,*,open_url,chunk_bytes):
    if type(row['bytes']) is not int or row['bytes']<=0 or not re.fullmatch('[0-9a-f]{64}',row['lfs_sha256']):raise ValueError('invalid source identity')
    if not etag or type(chunk_bytes) is not int or not 0<chunk_bytes<=CHUNK_BYTES:raise ValueError('invalid transport bound')
    final,part,state_path=file_paths(root,row);source=identity(row,etag)
    if final.exists():
        if part.exists():raise ValueError('final and partial both exist; preserved')
        before_hash=stat_identity(final)
        if final.stat().st_size!=row['bytes'] or sha(final)!=row['lfs_sha256'] or stat_identity(final)!=before_hash:raise ValueError('existing final mismatch; preserved')
        ranges=[]
        if state_path.exists():
            history=json.loads(state_path.read_text(encoding='utf-8'))
            if history.get('source')!=source or history.get('prefix_sha256')!=row['lfs_sha256']:raise ValueError('existing acquisition checkpoint mismatch; preserved')
            validate_ranges(history.get('http_ranges'),row['bytes'],row['bytes'],etag);ranges=history['http_ranges']
        return dict(index=row['index'],path=str(final),bytes=row['bytes'],sha256=row['lfs_sha256'],existing_final_verified=True,
                    verified_utc=stamp(),same_file_rename=False,http_ranges=ranges,source=source,file_identity=before_hash)
    resumed=part.exists()
    if resumed:
        if not state_path.exists():raise ValueError('unknown partial without checkpoint; preserved')
        state=json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('schema')!='strata-t05-part/v1' or state.get('source')!=source:raise ValueError('partial source mismatch; preserved')
        committed=state.get('committed')
        if type(committed) is not int or not 0<=committed<=row['bytes'] or part.stat().st_size<committed:
            raise ValueError('invalid committed prefix; preserved')
        # Exactly once per resume. Subsequent checkpoints use the running SHA.
        digest=hash_prefix(part,committed)
        if digest.hexdigest()!=state.get('prefix_sha256'):raise ValueError('modified committed prefix; preserved')
        validate_ranges(state.get('http_ranges'),committed,row['bytes'],etag)
        recover_checkpoint_temporary(state_path,source)
        with part.open('r+b') as stream:stream.truncate(committed)
    else:
        if state_path.exists() or Path(str(state_path)+'.tmp').exists():raise ValueError('orphan checkpoint; preserved')
        digest=hashlib.sha256();committed=0
        state=dict(schema='strata-t05-part/v1',source=source,committed=0,prefix_sha256=digest.hexdigest(),http_ranges=[])
        with part.open('xb') as stream:stream.flush();os.fsync(stream.fileno())
        checkpoint(state_path,state)
    canonical_url=f'https://huggingface.co/{REPO}/resolve/{REVISION}/'+urllib.parse.quote(row['filename'],safe='/')
    with part.open('r+b') as stream:
        stream.seek(committed)
        while committed<row['bytes']:
            length=min(chunk_bytes,row['bytes']-committed)
            request=urllib.request.Request(canonical_url,headers={'Range':f'bytes={committed}-{committed+length-1}','Accept-Encoding':'identity'})
            with open_url(request,timeout=60) as response:
                validate_response(response,committed,length,row['bytes'],etag)
                remaining=length
                while remaining:
                    raw=response.read(min(BUFFER_BYTES,remaining))
                    if not raw or len(raw)>remaining:raise ValueError('short/excess range body; tail uncommitted')
                    written=stream.write(raw)
                    if written!=len(raw):raise OSError('short local write')
                    digest.update(raw);remaining-=len(raw)
                if response.read(1):raise ValueError('excess range body; tail uncommitted')
            stream.flush();os.fsync(stream.fileno())
            state['http_ranges'].append(dict(status=206,start=committed,end=committed+length-1,total=row['bytes'],etag=etag,content_length=length))
            committed+=length
            state.update(committed=committed,prefix_sha256=digest.copy().hexdigest())
            checkpoint(state_path,state)
            print(json.dumps(dict(event='committed',index=row['index'],bytes=committed,total=row['bytes'],utc=stamp())),flush=True)
    if digest.hexdigest()!=row['lfs_sha256'] or part.stat().st_size!=row['bytes']:raise ValueError('full LFS SHA/size mismatch; partial preserved')
    before=part.stat()
    if final.exists():raise ValueError('final appeared concurrently; both files preserved')
    # os.rename refuses an existing destination on the supported Windows host.
    part.rename(final);after=final.stat()
    if (before.st_dev,before.st_ino,before.st_size)!=(after.st_dev,after.st_ino,after.st_size):raise ValueError('rename file identity changed')
    return dict(index=row['index'],path=str(final),bytes=row['bytes'],sha256=digest.hexdigest(),source=source,
                resumed=resumed,existing_final_verified=False,verified_utc=stamp(),same_file_rename=True,
                file_identity=stat_identity(final),http_ranges=state['http_ranges'])

def validate_ranges(ranges,committed,total,etag):
    if not isinstance(ranges,list):raise ValueError('missing range history')
    end=0
    for r in ranges:
        if (type(r.get('start')) is not int or type(r.get('end')) is not int or r['start']!=end
                or not r['start']<=r['end']<total or r.get('status')!=206 or r.get('total')!=total or r.get('etag')!=etag
                or r.get('content_length')!=r['end']-r['start']+1 or r['content_length']>CHUNK_BYTES):raise ValueError('invalid committed range history')
        end=r['end']+1
    if end!=committed:raise ValueError('range history does not cover committed prefix')

def storage_snapshot(root,files,*,free_bytes=None):
    root=safe_directory(root);remaining=0;held=0
    for row in files:
        final,part,_=file_paths(root,row)
        if final.exists() and part.exists():raise ValueError('duplicate final/partial model copy')
        existing=final if final.exists() else part
        present=existing.stat().st_size if existing.exists() else 0
        if present>row['bytes']:raise ValueError('existing file exceeds source size')
        held+=present;remaining+=row['bytes']-present
    parent=root
    while not parent.exists():parent=parent.parent
    free=shutil.disk_usage(parent).free if free_bytes is None else free_bytes
    planned=remaining+METADATA_ALLOWANCE
    if type(free) is not int or free<planned:raise ValueError(f'insufficient acquisition storage: free={free}, increment={planned}')
    return dict(captured_utc=stamp(),destination=str(root),free_bytes=free,existing_model_bytes=held,
                remaining_model_bytes=remaining,metadata_increment_estimate=METADATA_ALLOWANCE,planned_increment_bytes=planned,
                free_after_planned_increment=free-planned,scope='T05 acquisition only; existing builds already included in free; no future build/runtime headroom guarantee')

def validate_source_set(source):
    files=source.get('files',[])
    if source.get('repo')!=REPO or source.get('revision')!=REVISION or [r.get('index') for r in files]!=list(range(1,10)):
        raise ValueError('fixed nine-shard source identity required')
    for row in files:
        expected=f'UD-Q4_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-{row["index"]:05d}-of-00009.gguf'
        if row['filename']!=expected or type(row['bytes']) is not int or row['bytes']<=0 or not re.fullmatch('[0-9a-f]{64}',row['lfs_sha256']):raise ValueError('invalid fixed source row')
    if sum(r['bytes'] for r in files)!=500707576573:raise ValueError('fixed full-model byte total mismatch')

def validate_full_rows(files,rows):
    if len(rows)!=len(files) or [r.get('index') for r in rows]!=[r['index'] for r in files]:raise ValueError('full receipt shard coverage missing/duplicate')
    for file,row in zip(files,rows,strict=True):
        if type(row.get('index')) is not int or type(row.get('bytes')) is not int or row['bytes']!=file['bytes'] or row.get('sha256')!=file['lfs_sha256']:raise ValueError('full receipt content identity mismatch')

def load_fixed():
    loaded={}
    for name,wanted in FIXED_INPUTS.items():
        if sha(RECEIPTS/name)!=wanted:raise ValueError('fixed T03 metadata changed: '+name)
        loaded[name]=json.loads((RECEIPTS/name).read_text(encoding='utf-8'))
    validate_source_set(loaded['source-files.json'])
    return loaded['source-files.json'],loaded['header-inventory.json'],loaded['fixture-receipts.json']

def verify_model(root,source,inventory,fixtures,rows):
    validate_full_rows(source['files'],rows)
    def module(name,path):
        spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    gguf=module('t05_strict_gguf',Path(__file__).with_name('gguf.py'))
    bounded=module('t05_t03_validator',Path(__file__).with_name('acquire.py'))
    names=set();tensors=[]
    for file,header,row in zip(source['files'],inventory['shards'],rows,strict=True):
        final,_,_=file_paths(root,file)
        expected_source=identity(file,header['http_ranges'][0]['etag'])
        if (row.get('source')!=expected_source or row.get('path')!=str(final) or final.stat().st_size!=file['bytes']
                or row.get('file_identity')!=stat_identity(final)):raise ValueError('original source/path/stat identity mismatch')
        if row.get('http_ranges'):
            validate_ranges(row['http_ranges'],file['bytes'],file['bytes'],expected_source['etag'])
        elif row.get('existing_final_verified') is not True:raise ValueError('downloaded source lacks transport history')
        with final.open('rb') as stream:prefix=stream.read(header['prefix_bytes'])
        if hashlib.sha256(prefix).hexdigest()!=header['prefix_sha256']:raise ValueError('full source header differs from T03')
        parsed=gguf.parse_header(prefix,file['bytes']);bounded.validate_header_summary(header,parsed)
        meta=parsed['metadata']
        if meta.get('split.no')!=file['index']-1 or meta.get('split.count')!=9 or meta.get('split.tensors.count')!=1043:raise ValueError('full split identity mismatch')
        for tensor in parsed['tensors']:
            if tensor['name'] in names:raise ValueError('duplicate source tensor')
            names.add(tensor['name']);tensors.append(tensor)
    validate_trunk(names)
    checks=[]
    for f in fixtures['fixtures']:
        final,_,_=file_paths(root,source['files'][f['shard_index']-1])
        with final.open('rb') as stream:stream.seek(f['absolute_offset']);raw=stream.read(f['bytes'])
        if len(raw)!=f['bytes'] or hashlib.sha256(raw).hexdigest()!=f['fixture_sha256']:raise ValueError('full source fixture span differs from T03')
        checks.append(dict(tensor=f['tensor'],absolute_offset=f['absolute_offset'],bytes=f['bytes'],sha256=f['fixture_sha256']))
    if any(row['file_identity']!=stat_identity(row['path']) for row in rows):raise ValueError('model changed during structural readback')
    return dict(headers=9,tensors=len(names),trunk_layers=40,required_trunk_inventory_correspondence=True,source_fixture_checks=checks,
                scope='T03 fixed inventory correspondence only; T10 semantic adapter/DSpark/vision/numerics unqualified')

def validate_trunk(names):
    common=('ffn_gate_exps.weight','ffn_down_exps.weight','ffn_up_exps.weight','attn_sinks.weight',
        'attn_kv_a_norm.weight','attn_q_a_norm.weight','attn_kv.weight','attn_output_a.weight','attn_output_b.weight',
        'attn_q_a.weight','attn_q_b.weight','attn_norm.weight','exp_probs_b.bias','exp_probs_b_vl.bias','ffn_gate_inp.weight',
        'ffn_gate_shexp.weight','ffn_down_shexp.weight','ffn_up_shexp.weight','ffn_norm.weight','hc_attn_base.weight',
        'hc_attn_fn.weight','hc_attn_scale.weight','hc_ffn_base.weight','hc_ffn_fn.weight','hc_ffn_scale.weight')
    required={f'blk.{layer}.{role}' for layer in range(40) for role in common}|{'token_embd.weight','output.weight','output_norm.weight','per_layer_token_embd.weight'}
    if len(names)!=1043 or not required<=names:raise ValueError('trunk required assets/1043 inventory coverage missing')

def code_bindings():
    paths=[Path(__file__),EXT/'tests/artifact/test_full_acquire.py',Path(__file__).with_name('gguf.py'),Path(__file__).with_name('acquire.py')]
    return [dict(path=str(p),sha256=sha(p)) for p in paths]

def validate_receipt(receipt,root,source,inventory,fixtures):
    if (receipt.get('schema')!='strata-t05-full-model/v1' or receipt.get('complete') is not True
            or receipt.get('repo')!=REPO or receipt.get('revision')!=REVISION or receipt.get('destination')!=str(root)
            or type(receipt.get('total_bytes')) is not int or receipt['total_bytes']!=sum(f['bytes'] for f in source['files'])
            or receipt.get('t03_inputs')!=FIXED_INPUTS or receipt.get('code')!=code_bindings()):raise ValueError('full receipt scope/source/code mismatch')
    checks=verify_model(root,source,inventory,fixtures,receipt['files'])
    if receipt.get('checks')!=checks:raise ValueError('full receipt derived checks mismatch')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight',action='store_true');parser.add_argument('--acquire',action='store_true')
    parser.add_argument('--shard-one',action='store_true',help='Real small transport stage only; never emits full receipt')
    parser.add_argument('--verify-receipt',action='store_true',help='Explicit stat/header/span readback; not a second full payload hash')
    args=parser.parse_args();source,inventory,fixtures=load_fixed()
    # Preserve the existing strict T03 proof without changing its fixed files.
    subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('acquire.py')),
        '--raw-root','C:/Develop/AI/Strata-data/records/deepseek-v41/t03-20261021','--receipt-root',str(RECEIPTS),'--verify'],check=True)
    start=storage_snapshot(DESTINATION,source['files']);print(json.dumps(dict(event='storage',**start)),flush=True)
    if args.verify_receipt:
        validate_receipt(json.loads((RECEIPTS/'full-model-receipt.json').read_text(encoding='utf-8')),DESTINATION,source,inventory,fixtures)
        print('verified full receipt stat/header/span binding; full payload SHA is the recorded acquisition observation');return
    if not args.acquire:return
    binding=code_bindings();results=[];snapshots=[start]
    for file,header in zip(source['files'],inventory['shards'],strict=True):
        if args.shard_one and file['index']!=1:break
        snapshots.append(storage_snapshot(DESTINATION,source['files']))
        results.append(download_file(file,DESTINATION,header['http_ranges'][0]['etag']))
    if args.shard_one:
        print(json.dumps(dict(scope='small real shard1 only; no full-model receipt',files=results)));return
    checks=verify_model(DESTINATION,source,inventory,fixtures,results)
    if code_bindings()!=binding:raise ValueError('acquisition implementation changed during execution')
    receipt=dict(schema='strata-t05-full-model/v1',complete=True,repo=REPO,revision=REVISION,captured_utc=stamp(),
        destination=str(DESTINATION),total_bytes=sum(f['bytes'] for f in source['files']),files=results,
        t03_inputs=FIXED_INPUTS,code=binding,storage=snapshots,checks=checks,
        qualification='Explicit acquisition/full9LFS-SHA and T03 inventory correspondence; not runtime/numerical/DSpark qualification')
    validate_receipt(receipt,DESTINATION,source,inventory,fixtures)
    target=RECEIPTS/'full-model-receipt.json'
    with target.open('w',encoding='utf-8',newline='\n') as stream:json.dump(receipt,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(event='complete',receipt=str(target),sha256=sha(target))),flush=True)

if __name__=='__main__':main()
