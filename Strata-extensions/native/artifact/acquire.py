"""Strict bounded HTTP ranges for fixed-revision inspection, never full fallback."""
import re
import urllib.request
import urllib.parse

FIXTURE_REQUESTS = (('blk.0.ffn_gate_exps.weight', 'expert0', 0),
                    ('blk.0.ffn_up_exps.weight', 'expert0', 0),
                    ('blk.0.ffn_down_exps.weight', 'expert0', 0),
                    ('per_layer_token_embd.weight', 'row', 1),
                    ('token_embd.weight', 'row', 0),
                    ('output_norm.weight', 'full-vector', 0))


def header_summary(header):
    import hashlib
    import json
    metadata = header['metadata']
    return dict(data_start=header['data_start'], alignment=header['alignment'],
                metadata_scalars={k:v for k,v in metadata.items() if not isinstance(v,(list,dict))},
                metadata_arrays={k:dict(count=len(v),sha256=hashlib.sha256(json.dumps(
                    v,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
                    values=v if len(v)<=128 else None) for k,v in metadata.items()
                    if isinstance(v,list) and not k.startswith('tokenizer.')},
                tokenizer_metadata_sha256=header['tokenizer_metadata_sha256'],
                token_count=len(metadata.get('tokenizer.ggml.tokens',[])), tensors=header['tensors'])


def validate_header_summary(receipt, header):
    if any(receipt.get(k) != v for k,v in header_summary(header).items()):
        raise ValueError('header configuration/shape/tokenizer summary mismatch')


def validate_fixture_coverage(rows):
    keys = [(r.get('tensor'),r.get('selection'),r.get('index')) for r in rows]
    if len(keys) != len(FIXTURE_REQUESTS) or set(keys) != set(FIXTURE_REQUESTS):
        raise ValueError('required real fixture coverage missing or duplicated')


def read_range_response(response, start, length, total, expected_etag=None):
    if response.status != 206:
        raise ValueError('range requires HTTP206; body not read')
    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
    if not match or tuple(map(int, match.groups())) != (start, start + length - 1, total):
        raise ValueError('Content-Range identity/bounds mismatch; body not read')
    etag = response.headers.get('ETag')
    if not etag or (expected_etag is not None and etag != expected_etag):
        raise ValueError('missing or changed file ETag; body not read')
    encoding = response.headers.get('Content-Encoding', 'identity')
    if encoding != 'identity':
        raise ValueError('encoded range cannot prove raw offsets')
    data = response.read(length + 1)
    if len(data) != length:
        raise ValueError('short or excessive range body')
    return data, dict(status=206, start=start, end=start + length - 1, total=total, etag=etag)


def fetch_range(url, start, length, total, expected_etag=None):
    if type(start) is not int or type(length) is not int or start < 0 or length <= 0 or start + length > total:
        raise ValueError('invalid bounded range')
    req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{start + length - 1}',
                                               'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return read_range_response(response, start, length, total, expected_etag)


def capture_headers(raw_root, receipt_root):
    """One explicit development acquisition, with immutable HF revision URLs."""
    import hashlib
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    from gguf import parse_header, NeedMore

    repo = 'unsloth/DeepSeek-V4.1-Flash-1017-GGUF'
    revision = 'f924b94f19c1fea02c06a65c8475b0a45e2b88b1'
    api = f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true'
    with urllib.request.urlopen(api, timeout=60) as response:
        metadata_bytes = response.read(8 * 1024 * 1024 + 1)
    if len(metadata_bytes) > 8 * 1024 * 1024:
        raise ValueError('metadata response exceeds development bound')
    metadata = json.loads(metadata_bytes)
    if metadata.get('sha') != revision:
        raise ValueError('metadata revision mismatch')
    files = []
    pattern = r'UD-Q4_K_XL/DeepSeek-V4\.1-Flash-1017-UD-Q4_K_XL-(\d{5})-of-00009\.gguf'
    for row in metadata['siblings']:
        match = re.fullmatch(pattern, row['rfilename'])
        if match:
            lfs = row['lfs']
            if not re.fullmatch('[0-9a-f]{64}', lfs['sha256']) or type(lfs['size']) is not int:
                raise ValueError('missing LFS content identity')
            files.append(dict(index=int(match[1]), filename=row['rfilename'],
                              bytes=lfs['size'], lfs_sha256=lfs['sha256']))
    files.sort(key=lambda row: row['index'])
    if [r['index'] for r in files] != list(range(1, 10)) or sum(r['bytes'] for r in files) != 500707576573:
        raise ValueError('fixed nine-shard set/size mismatch')
    raw_root, receipt_root = Path(raw_root), Path(receipt_root)
    (raw_root / 'headers').mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)
    source = dict(repo=repo, revision=revision, metadata_url=api,
                  metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest(),
                  captured_utc=datetime.now(timezone.utc).isoformat(),
                  identity='siblings.lfs.sha256, not blobId Git pointer', files=files)
    (receipt_root / 'source-files.json').write_text(json.dumps(source, indent=2) + '\n', encoding='utf-8')
    inventories = []
    for row in files:
        url = f'https://huggingface.co/{repo}/resolve/{revision}/' + urllib.parse.quote(row['filename'])
        prefix, observations, etag = b'', [], None
        target = min(16384, row['bytes'])
        while True:
            added, observation = fetch_range(url, len(prefix), target - len(prefix), row['bytes'], etag)
            prefix += added
            observations.append(observation)
            etag = observation['etag']
            try:
                header = parse_header(prefix, row['bytes'])
                break
            except NeedMore:
                if target == row['bytes'] or target >= 64 * 1024 * 1024:
                    raise ValueError('header incomplete within development bound; revise estimate')
                target = min(target * 2, row['bytes'], 64 * 1024 * 1024)
        raw_path = raw_root / 'headers' / f"shard-{row['index']:02d}.prefix.bin"
        raw_path.write_bytes(prefix)
        full_verified = len(prefix) == row['bytes']
        if full_verified and hashlib.sha256(prefix).hexdigest() != row['lfs_sha256']:
            raise ValueError('small complete shard SHA mismatch')
        inventories.append(dict(**row, url=url, prefix_path=str(raw_path), prefix_bytes=len(prefix),
                                prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                                full_shard_sha256_verified=full_verified,
                                http_ranges=observations, **header_summary(header)))
        (receipt_root / 'header-inventory.json').write_text(json.dumps(dict(
            revision=revision, scope='header/span inventory only; no full-model SHA or numerical execution',
            shards=inventories), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f"shard {row['index']}: {len(prefix)} prefix bytes, {len(header['tensors'])} tensors, "
              f"types {sorted(set(t['type_id'] for t in header['tensors']))}", flush=True)


def capture_fixtures(raw_root, receipt_root):
    """Capture actual full single-expert matrices and small dense/Engram rows."""
    import hashlib
    import json
    import math
    import struct
    from pathlib import Path

    raw_root, receipt_root = Path(raw_root), Path(receipt_root)
    inventory = json.loads((receipt_root / 'header-inventory.json').read_text(encoding='utf-8'))
    (raw_root / 'fixtures').mkdir(parents=True, exist_ok=True)
    receipts, total = [], 0
    for name, selection, index in FIXTURE_REQUESTS:
        matches = [(s, t) for s in inventory['shards'] for t in s['tensors'] if t['name'] == name]
        if len(matches) != 1:
            raise ValueError(f'unique fixture tensor missing: {name}')
        shard, tensor = matches[0]
        dims = tensor['dims_ggml']
        length = tensor['row_bytes'] * math.prod(dims[1:-1]) if selection == 'expert0' else (
            tensor['bytes'] if selection == 'full-vector' else tensor['row_bytes'])
        start = tensor['absolute_offset'] + index * length
        if start + length > tensor['absolute_offset'] + tensor['bytes']:
            raise ValueError('fixture outside tensor')
        total += length
        if total > 512 * 1024 * 1024:
            raise ValueError('fixture development estimate exceeded; revise estimate')
        blob, observation = fetch_range(shard['url'], start, length, shard['bytes'], shard['http_ranges'][0]['etag'])
        block_bytes = {39: 17, 43: 33, 8: 34, 0: 4}[tensor['type_id']]
        scales = blob[::block_bytes] if tensor['type_id'] in (39, 43) else None
        if scales is not None:
            nonzero_scales = sum(0 < s < 255 for s in scales)
        elif tensor['type_id'] == 8:
            nonzero_scales = sum(math.isfinite(v := struct.unpack_from('<e', blob, p)[0]) and v != 0
                                 for p in range(0, len(blob), 34))
        else:
            nonzero_scales = sum(math.isfinite(v[0]) and v[0] != 0 for v in struct.iter_unpack('<f', blob))
        if not nonzero_scales or not any(blob):
            raise ValueError('fixture lacks nonzero finite scale/data; not numerical qualification')
        path = raw_root / 'fixtures' / f'{name}.{selection}{index}.bin'
        path.write_bytes(blob)
        receipts.append(dict(revision=inventory['revision'], shard_index=shard['index'],
                             filename=shard['filename'], file_bytes=shard['bytes'],
                             file_lfs_sha256=shard['lfs_sha256'], full_file_sha_verified=shard['full_shard_sha256_verified'],
                             tensor=name, type_id=tensor['type_id'], layout=tensor['layout'],
                             dims_ggml=dims, row_bytes=tensor['row_bytes'], selection=selection,
                             index=index, absolute_offset=start, bytes=length, http=observation,
                             fixture_path=str(path), fixture_sha256=hashlib.sha256(blob).hexdigest(),
                             nonzero_scale_or_scalar_count=nonzero_scales,
                             qualification='real source bytes only; no numerical decode/kernel PASS'))
        print(f'{name}: {length} bytes; nonzero scale/scalar count {nonzero_scales}', flush=True)
    (receipt_root / 'fixture-receipts.json').write_text(json.dumps(dict(
        revision=inventory['revision'], total_fixture_bytes=total,
        future_scope='T09 actual top6 may acquire more distinct expert spans under this revision/file/span receipt scheme; these expert0 fixtures are not top6 kernel qualification.',
        fixtures=receipts), indent=2) + '\n', encoding='utf-8')


def validate_fixture(fixture, tensor, shard, revision, raw):
    """Rederive selection, identity, layout, range and scale facts from sources."""
    import hashlib
    import math
    import struct

    identities = dict(revision=revision, shard_index=shard['index'], filename=shard['filename'],
                      file_bytes=shard['bytes'], file_lfs_sha256=shard['lfs_sha256'],
                      full_file_sha_verified=shard['full_shard_sha256_verified'],
                      tensor=tensor['name'], type_id=tensor['type_id'], layout=tensor['layout'],
                      dims_ggml=tensor['dims_ggml'], row_bytes=tensor['row_bytes'])
    if any(fixture.get(k) != v for k, v in identities.items()):
        raise ValueError('fixture source/layout binding mismatch')
    dims, selection, index = tensor['dims_ggml'], fixture.get('selection'), fixture.get('index')
    if type(index) is not int or index < 0:
        raise ValueError('invalid fixture index')
    if selection == 'expert0' and len(dims) == 3 and index == 0:
        length = tensor['row_bytes'] * math.prod(dims[1:-1])
    elif selection == 'row' and len(dims) == 2 and index < dims[1]:
        length = tensor['row_bytes']
    elif selection == 'full-vector' and len(dims) == 1 and index == 0:
        length = tensor['bytes']
    else:
        raise ValueError('selection/index incompatible with tensor')
    start = tensor['absolute_offset'] + index * length
    expected_http = dict(status=206, start=start, end=start + length - 1,
                         total=shard['bytes'], etag=shard['http_ranges'][0]['etag'])
    if (fixture.get('http') != expected_http or fixture.get('absolute_offset') != start
            or fixture.get('bytes') != length or len(raw) != length
            or start + length > tensor['absolute_offset'] + tensor['bytes']
            or hashlib.sha256(raw).hexdigest() != fixture.get('fixture_sha256')):
        raise ValueError('fixture selection/range/hash mismatch')
    dtype = tensor['type_id']
    if dtype in (39, 43):
        count = sum(0 < scale < 255 for scale in raw[::(17 if dtype == 39 else 33)])
    elif dtype == 8:
        count = sum(math.isfinite(v := struct.unpack_from('<e', raw, p)[0]) and v != 0
                    for p in range(0, len(raw), 34))
    elif dtype == 0:
        count = sum(math.isfinite(v[0]) and v[0] != 0 for v in struct.iter_unpack('<f', raw))
    else:
        raise ValueError('fixture scale contract unsupported')
    if count <= 0 or fixture.get('nonzero_scale_or_scalar_count') != count:
        raise ValueError('nonzero scale/scalar count mismatch')


def verify_captures(receipt_root):
    """Read back raw files and rederive all headers/spans; no network or GPU."""
    import hashlib
    import json
    from pathlib import Path
    from gguf import parse_header

    root = Path(receipt_root)
    inventory = json.loads((root / 'header-inventory.json').read_text(encoding='utf-8'))
    source = json.loads((root / 'source-files.json').read_text(encoding='utf-8'))
    if inventory['revision'] != source['revision'] or len(inventory['shards']) != 9:
        raise ValueError('incomplete or mixed-revision inventory')
    names = set()
    for shard, file in zip(inventory['shards'], source['files'], strict=True):
        for key in ('index', 'filename', 'bytes', 'lfs_sha256'):
            if shard[key] != file[key]:
                raise ValueError('file identity mismatch')
        raw = Path(shard['prefix_path']).read_bytes()
        if len(raw) != shard['prefix_bytes'] or hashlib.sha256(raw).hexdigest() != shard['prefix_sha256']:
            raise ValueError('raw prefix receipt mismatch')
        if shard['full_shard_sha256_verified'] and hashlib.sha256(raw).hexdigest() != file['lfs_sha256']:
            raise ValueError('complete shard SHA mismatch')
        parsed = parse_header(raw, file['bytes'])
        validate_header_summary(shard, parsed)
        if shard['full_shard_sha256_verified'] != (len(raw) == file['bytes']):
            raise ValueError('full-shard verification scope mismatch')
        meta = parsed['metadata']
        if meta.get('split.no') != shard['index'] - 1 or meta.get('split.count') != 9 or meta.get('split.tensors.count') != 1043:
            raise ValueError('split identity mismatch')
        for tensor in parsed['tensors']:
            if tensor['name'] in names:
                raise ValueError('duplicate tensor across shards')
            names.add(tensor['name'])
    if len(names) != 1043:
        raise ValueError('global tensor coverage mismatch')
    fixtures = json.loads((root / 'fixture-receipts.json').read_text(encoding='utf-8'))
    validate_fixture_coverage(fixtures['fixtures'])
    for fixture in fixtures['fixtures']:
        raw = Path(fixture['fixture_path']).read_bytes()
        shard = inventory['shards'][fixture['shard_index'] - 1]
        tensor = next(t for t in shard['tensors'] if t['name'] == fixture['tensor'])
        validate_fixture(fixture, tensor, shard, inventory['revision'], raw)
    if (fixtures.get('revision') != inventory['revision']
            or fixtures.get('total_fixture_bytes') != sum(f['bytes'] for f in fixtures['fixtures'])):
        raise ValueError('fixture aggregate revision/bytes mismatch')
    print(f"verified {len(inventory['shards'])} raw headers / {len(names)} tensors / "
          f"{len(fixtures['fixtures'])} real fixtures / {fixtures['total_fixture_bytes']} fixture bytes")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', required=True)
    parser.add_argument('--receipt-root', required=True)
    parser.add_argument('--fixtures', action='store_true', help='Use existing header inventory to capture bounded real fixtures')
    parser.add_argument('--verify', action='store_true', help='Offline raw/receipt readback only')
    args = parser.parse_args()
    if args.verify:
        verify_captures(args.receipt_root)
    elif args.fixtures:
        capture_fixtures(args.raw_root, args.receipt_root)
    else:
        capture_headers(args.raw_root, args.receipt_root)
