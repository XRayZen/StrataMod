"""Read-only DeepSeek family assets and profile declarations.

This module does not resolve allocation budgets, publish profiles, register a
runtime, or confer T05/T10/owner authority. The normal native loader validates
actual mapped metadata; source_spans is its pure original-span correspondence.
"""
import copy
import hashlib
import math
import pathlib
import re
import struct
import types

MODEL = 'deepseek-v4.1-flash-1017-ud-q4_k_xl'
FAMILY = 'deepseek41'
REVISION = 'f924b94f19c1fea02c06a65c8475b0a45e2b88b1'
LAYOUT = 'UD-Q4_K_XL'
CONTEXT_PRESETS = (4096,32768,131072,262144,524288,1048576)
TOKENIZER_SHA256 = "81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99"
CONTEXT_MAX = 1048576
SOURCES = [{'index': 1, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00001-of-00009.gguf', 'bytes': 5780589, 'lfs_sha256': 'cc15d470afcb030558bbc4d8e2ccd840182e2e95de1a95198138efe63a5fd99f'}, {'index': 2, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00002-of-00009.gguf', 'bytes': 48129640000, 'lfs_sha256': '17df217d8fc26a39f21ea40805dc6ab788c7ce8623a59a95c431051df7eafc94'}, {'index': 3, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00003-of-00009.gguf', 'bytes': 48129640000, 'lfs_sha256': '0c8065f620a049cb437024c54ff12c314c94603a1cc683f5191be4689d6d6d3b'}, {'index': 4, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00004-of-00009.gguf', 'bytes': 48129640000, 'lfs_sha256': '3bd8b2ebf8f51d8708a73ae0895f8d4acc7e4c983ba4e89d038492b203cc89ac'}, {'index': 5, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00005-of-00009.gguf', 'bytes': 48129640000, 'lfs_sha256': '929054a6bbf3701765779b58c37988b6c6284a3b8413901858b59c0e95f37cc3'}, {'index': 6, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00006-of-00009.gguf', 'bytes': 48129640000, 'lfs_sha256': '49d3de04bd6a09de786c9ef7db900eae02ee9fd391573f91a923013d7d5b24d3'}, {'index': 7, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00007-of-00009.gguf', 'bytes': 48129640000, 'lfs_sha256': 'f18feae5878dd680f1ea87ecd1d84f4fb098480298b25a3162dcbdab8dc2ca5b'}, {'index': 8, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00008-of-00009.gguf', 'bytes': 202758032592, 'lfs_sha256': '12df293355efbd104b088a77e13ee22410fb1ec3f7ab3863947f09896e64bec7'}, {'index': 9, 'filename': 'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00009-of-00009.gguf', 'bytes': 9165923392, 'lfs_sha256': 'c21ad6105a780bc2f44eb7dd41f9b1a1efb4e8ec87618f60b733bc2652bd2ffe'}]


def need(condition,message):
    if not condition:
        raise ValueError(message)


def context(value):
    need(type(value) is int and 0 < value <= CONTEXT_MAX,'DeepSeek context must be an integer in 1..1048576')
    return value


def absolute_file(value,label):
    need(type(value) is str and bool(value),label+' path missing')
    path=pathlib.Path(value)
    need(path.is_absolute(),label+' path must be absolute')
    need(path.is_file(),label+' file missing: '+str(path))
    return path.resolve()


def paths(artifact_root):
    need(type(artifact_root) is str and pathlib.Path(artifact_root).is_absolute(),'artifact_root must be absolute')
    return [str(pathlib.Path(artifact_root)/row['filename']) for row in SOURCES]


def assets(value):
    need(type(value) is dict,'family assets must be an object')
    need(value.get('fixedrevision')==REVISION and value.get('layout')==LAYOUT,'fixed native revision/layout mismatch')
    expected=paths(value.get('artifact_root'));original=value.get('native_paths')
    need(type(original) is list and len(original)==9 and all(type(x)is str for x in original),'exactly nine ordered native_paths required')
    need(len({str(pathlib.Path(x).resolve()) for x in original})==9,'duplicate original source')
    sources=[]
    for row,name,want in zip(SOURCES,original,expected):
        path=absolute_file(name,'native source')
        need(path==pathlib.Path(want).resolve(),'native source order/path mismatch')
        before=path.stat()
        need(before.st_size==row['bytes'],'original source size mismatch: '+str(path))
        with path.open('rb') as stream: header=stream.read(8)
        need(len(header)==8 and header[:4]==b'GGUF' and struct.unpack('<I',header[4:])[0]==3,'original GGUF v3 header mismatch')
        after=path.stat()
        need((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'source changed during read-only check')
        sources.append(dict(index=row['index'],path=str(path),bytes=row['bytes'],lfs_sha256=row['lfs_sha256'],revision=REVISION,layout=LAYOUT,mtime_ns=before.st_mtime_ns))
    tokenizer=absolute_file(value.get('tokenizer'),'official Recipe tokenizer')
    executable=absolute_file(value.get('exe'),'normal native executable')
    need(tokenizer.stat().st_size>0 and executable.stat().st_size>0,'empty tokenizer/executable')
    need(hashlib.sha256(tokenizer.read_bytes()).hexdigest()==TOKENIZER_SHA256,'fixed official Recipe v41 tokenizer identity mismatch')
    return dict(artifact_root=str(pathlib.Path(value['artifact_root']).resolve()),sources=sources,tokenizer=str(tokenizer),exe=str(executable),qualification='read-only original identity/layout declaration; native mapped metadata, tokenizer and runtime qualification remain caller-owned')


def source_spans(checked_assets,spans):
    need(type(spans) is list,'source spans must be a list')
    sources={x['index']:x for x in checked_assets['sources']}
    for row in spans:
        need(type(row) is dict and type(row.get('shard_index'))is int and row['shard_index'] in sources,'original shard index')
        start,size=row.get('absolute_offset'),row.get('bytes')
        need(type(start)is int and type(size)is int and start>=0 and size>0 and start<=sources[row['shard_index']]['bytes'] and size<=sources[row['shard_index']]['bytes']-start,'original source span bounds')
        need(type(row.get('type_id'))is int and row['type_id'] in (0,8,39,43),'native type/layout')
        dims=row.get('dims');need(type(dims)is list and bool(dims) and all(type(x)is int and x>0 for x in dims),'original tensor shape')
        block,width={0:(1,4),8:(32,34),39:(32,17),43:(32,33)}[row['type_id']]
        need(dims[0]%block==0,'full K native row block alignment')
        row_bytes=dims[0]//block*width
        need(size==row_bytes*math.prod(dims[1:]),'original native shape/type/span bytes mismatch')
        if 'row_bytes' in row:need(type(row['row_bytes'])is int and row['row_bytes']==row_bytes,'original native row bytes mismatch')
    return copy.deepcopy(spans)


def budget(value):
    need(type(value)is dict,'cache_budget declaration must be an object')
    allowed={'device_cache_payload_bytes','ram_cache_payload_bytes','secondary_device_cache_payload_bytes'}
    need(set(value)<=allowed,'unknown cache budget field/unit')
    for name,amount in value.items():
        # Existing owners require nonzero active/cache slots; this is not a
        # blanket zero check for seed, top_k, optional role, or other options.
        need(amount=='auto' or (type(amount)is int and amount>0),name+' must be auto or positive payload bytes; current owner has no disabled-zero path')
    return copy.deepcopy(value)


def placement(options):
    if 'placement' not in options:
        return
    path=pathlib.Path(__file__).resolve().parents[1]/'contracts.py'
    module=types.ModuleType('strata_existing_role_contract');module.__file__=str(path)
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    row=options['placement'];module.validate_placement(row)
    need(row['primary']==options['primary_pci'],'placement/primary_pci mismatch')
    if 'secondary' in options:need(row['secondary']==options['secondary'],'placement/secondary mismatch')


def profile(asset_values,requested_context,options):
    context(requested_context);need(type(options)is dict,'profile options must be an object')
    checked=assets(asset_values)
    result=copy.deepcopy(options)
    need(re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]',str(result.get('primary_pci','')))is not None,'actual primary PCI identity required')
    result['cache_budget']=budget(result.get('cache_budget',{}))
    placement(result)
    for name in ('auto_cache_fraction','auto_row_fraction'):
        if name in result:need(type(result[name])in (int,float) and math.isfinite(result[name]) and 0<=result[name]<=1,name+' must be finite in [0,1]')
    for name in ('family','model_name','context','fixedrevision','layout','artifact_root','native_paths','tokenizer','exe'):
        need(name not in options,'profile identity cannot be overridden in options: '+name)
    result.update(family=FAMILY,model_name=MODEL,context=requested_context,fixedrevision=REVISION,layout=LAYOUT,artifact_root=checked['artifact_root'],native_paths=[x['path'] for x in checked['sources']],tokenizer=checked['tokenizer'],exe=checked['exe'])
    normal_fields(result)
    return result

def normal_fields(value):
    """Optional normal declaration checks, not a launch/qualification authority."""
    if 'execution_defaults'in value:
        path=pathlib.Path(__file__).resolve().parents[1]/'deepseek_launch.py'
        helper=types.ModuleType('strata_execution_defaults');helper.__file__=str(path)
        exec(compile(path.read_bytes(),str(path),'exec'),helper.__dict__)
        helper.execution_defaults(value['execution_defaults'])
    names={'python','server_entry','upstream_root','runtime_package'}
    if not names.intersection(value):return
    need(names<=set(value),'normal runtime declaration is incomplete')
    package=value['runtime_package']
    need(type(package)is dict and set(package)=={'id','manifest'},'runtime package declaration')
    need(type(package['id'])is str and re.fullmatch('[0-9a-f]{64}',package['id'])is not None,'runtime package identity')
    def absolute(v):return type(v)is str and pathlib.Path(v).is_absolute() and '\0'not in v
    need(absolute(package['manifest']),'runtime manifest absolute path')
    root=pathlib.Path(package['manifest']).parent.parent.resolve()
    need(root.name==package['id'],'runtime manifest/package identity mismatch')
    for name in names-{'runtime_package'}:
        need(absolute(value[name])and pathlib.Path(value[name]).resolve().is_relative_to(root),'normal runtime path outside package: '+name)
    need(pathlib.Path(value['exe'])==root/'native/Strata-deepseek.exe','native executable/package mismatch')
    need(pathlib.Path(value['tokenizer'])==root/'resources/tokenizer.json','tokenizer/package mismatch')
    need(value.get('bundle_id')is not None and type(value['bundle_id'])is str and re.fullmatch('[0-9a-f]{64}',value['bundle_id'])is not None,'native bundle identity')
    if 'runtime_epoch'in value:need(type(value['runtime_epoch'])is int and value['runtime_epoch']>0,'normal launch epoch must be positive')
    if 'aliases'in value:
        aliases=value['aliases'];need(type(aliases)is list and all(type(x)is str and x.strip()for x in aliases)and len({x.casefold()for x in aliases})==len(aliases),'model aliases')
    args=value.get('args',[]);need(type(args)is list and all(type(x)is str for x in args),'native args declaration')
    reserved={'--serve','--context','--primary-pci','--secondary-pci','--mode','--artifact-root','--bundle-id','--runtime-epoch','--device-cache-payload-bytes','--ram-cache-payload-bytes','--secondary-device-cache-payload-bytes','--auto-cache-fraction','--auto-row-fraction','--tile-bytes','--tile-rows','--active-batch'}|{'--source'+str(i)for i in range(1,10)}
    reserved.update(('--secondary-experts','--layer-cut'))
    need(not any(x.split('=')[0]in reserved for x in args),'duplicate generated native argument')


def validate_profile(value,requested_context):
    need(type(value)is dict and value.get('family')==FAMILY and value.get('model_name')==MODEL,'profile family/model mismatch')
    context(value.get('context'));need(value['context']==context(requested_context),'profile context mismatch')
    keys={'family','model_name','context','fixedrevision','layout','artifact_root','native_paths','tokenizer','exe'}
    options={k:v for k,v in value.items() if k not in keys}
    return profile(value,requested_context,options)
