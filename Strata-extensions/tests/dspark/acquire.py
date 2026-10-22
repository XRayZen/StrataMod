"""Explicit one-artifact T37 acquisition; never called by normal startup.

Reuse a privately loaded, byte-unchanged T05 transfer implementation. Only its
module-local repo/revision transport parameters differ and are receipt-bound;
the accepted T05 source file/config/9 target files are never changed.
"""
import argparse,hashlib,importlib.util,json,pathlib,shutil,sys
ROOT=pathlib.Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';BUILD=ROOT/'build-deepseek-t37'
REPO='Lucebox/DeepSeek-V4.1-Flash-1017-ROCMFP-GGUF'
REVISION='ba58445f0818edfc69e680390bc9b4873af8a621'
FILENAME='DeepSeek-V4.1-Flash-1017-DSpark-draft-MXFP4-Q8.gguf'
BYTES=7965746848
LFS='02468aa72b7233d50696682817b66ea661ebf387a0b6beecf6954febd8680b1e'
DESTINATION=pathlib.Path('C:/Develop/AI/Model/DeepSeek-V4.1-Flash-1017-DSpark-GGUF')/REVISION/'MXFP4-Q8'
HELPER=EXT/'native/artifact/full_acquire.py'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def transfer_module():
 spec=importlib.util.spec_from_file_location('t37_private_transfer',HELPER);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.REPO=REPO;m.REVISION=REVISION;return m

def download():
 m=transfer_module();m.safe_directory(DESTINATION);DESTINATION.mkdir(parents=True,exist_ok=True)
 row=dict(index=1,filename=FILENAME,bytes=BYTES,lfs_sha256=LFS);snapshot=m.storage_snapshot(DESTINATION,[row]);header=json.loads((BUILD/'reference-source/luce-draft-header-receipt.json').read_text());assert header['revision']==REVISION and header['lfs_sha256']==LFS and header['source_bytes']==BYTES
 # Fresh free already includes every retained artifact. Reserve only future
 # increments; engineering estimates are not ordinary headroom/caps.
 final,part,state=m.file_paths(DESTINATION,row);committed=0
 if state.exists():
  saved=json.loads(state.read_text());committed=saved.get('committed',0);assert type(committed)is int and 0<=committed<=BYTES
 future=64*2**20+32*2**20+2*2**30+64*2**20+224*2**20+16*2**20
 own_future=(8+512+16)*2**20;required=(0 if final.exists() else BYTES-committed)+future+own_future
 free=shutil.disk_usage(DESTINATION).free;assert free>=required,'fresh capacity below declared acquisition plus future estimates'
 bindings={str(p):sha(p) for p in [HELPER,pathlib.Path(__file__),BUILD/'pre-r4.md',BUILD/'reference-source/luce-draft-header-receipt.json']}
 before=dict(schema='T37-acquisition-before/v1',source=dict(repo=REPO,revision=REVISION,filename=FILENAME,bytes=BYTES,lfs_sha256=LFS,etag=header['etag']),destination=str(DESTINATION),snapshot=snapshot,fresh_free=free,required_increment_and_estimates=required,estimated_surplus=free-required,existing_retained_not_subtracted_again=True,helper_private_parameters=dict(REPO=m.REPO,REVISION=m.REVISION),bindings=bindings,max_workers=1,chunk_bytes=m.CHUNK_BYTES)
 (BUILD/'acquisition-before.json').write_text(json.dumps(before,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(event='acquisition-start',destination=str(DESTINATION),free=free,required=required,surplus=free-required)),flush=True)
 result=m.download_file(row,DESTINATION,header['etag']);assert all(sha(path)==digest for path,digest in bindings.items()),'transfer consumed bindings changed'
 after=dict(schema='T37-artifact-receipt/v1',source=before['source'],file=result,before_bindings=bindings,after_bindings_unchanged=True,current_identity=m.stat_identity(final),full_LFS_qualified=True,target9_sources_modified=False,normal_start_gate=False)
 output=BUILD/'artifact-receipt.json';output.write_text(json.dumps(after,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(event='artifact-final',receipt=str(output),sha256=sha(output),file=result)),flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');args=parser.parse_args()
 if args.download:download()
