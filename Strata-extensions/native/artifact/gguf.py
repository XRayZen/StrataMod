"""Bounded little-endian GGUF header inspection; no tensor decode or execution."""
import hashlib
import json
import math
from pathlib import Path
import struct


class NeedMore(ValueError):
    """The bounded prefix ends before the complete header/alignment padding."""


def parse_header(prefix, file_bytes):
    cursor = 0

    def take(n):
        nonlocal cursor
        if n < 0 or cursor + n > file_bytes:
            raise ValueError('field outside source file')
        if cursor + n > len(prefix):
            raise NeedMore('header prefix incomplete')
        out = prefix[cursor:cursor + n]
        cursor += n
        return out

    def scalar(fmt):
        return struct.unpack('<' + fmt, take(struct.calcsize('<' + fmt)))[0]

    def string():
        n = scalar('Q')
        return take(n).decode('utf-8')

    formats = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'f',
               7: '?', 10: 'Q', 11: 'q', 12: 'd'}

    def value(kind):
        if kind == 8:
            return string()
        if kind == 9:
            subtype, n = scalar('I'), scalar('Q')
            if subtype not in formats and subtype != 8:
                raise ValueError('invalid array element type')
            # Even a string has an 8-byte length; no zero-width array entries.
            minimum = 8 if subtype == 8 else struct.calcsize('<' + formats[subtype])
            if n > (file_bytes - cursor) // minimum:
                raise ValueError('array count outside source')
            if n * minimum > len(prefix) - cursor:
                raise NeedMore('array prefix incomplete')
            return [value(subtype) for _ in range(n)]
        if kind not in formats:
            raise ValueError('unknown metadata type')
        return scalar(formats[kind])

    if take(4) != b'GGUF' or scalar('I') != 3:
        raise ValueError('only GGUF v3 little-endian supported')
    tensors, entries = scalar('Q'), scalar('Q')
    if tensors > file_bytes // 32 or entries > file_bytes // 12:
        raise ValueError('impossible descriptor count')
    metadata = {}
    for _ in range(entries):
        name = string()
        if name in metadata:
            raise ValueError('duplicate metadata key')
        metadata[name] = value(scalar('I'))
    layouts = json.loads(Path(__file__).with_name('quant_layouts.json').read_text(encoding='utf-8'))['types']
    rows, names = [], set()
    for _ in range(tensors):
        name, ndim = string(), scalar('I')
        if name in names or not 1 <= ndim <= 4:
            raise ValueError('duplicate tensor or invalid dimension count')
        names.add(name)
        dims = [scalar('Q') for _ in range(ndim)]
        dtype, offset = scalar('I'), scalar('Q')
        layout = layouts.get(str(dtype))
        if layout is None:
            raise ValueError(f'unknown type/layout {dtype}; no Q4-label inference')
        if not all(0 < d <= 2**63 - 1 for d in dims) or dims[0] % layout['block_values']:
            raise ValueError('invalid shape/block alignment')
        row_bytes = dims[0] // layout['block_values'] * layout['block_bytes']
        size = row_bytes * math.prod(dims[1:])
        rows.append(dict(name=name, dims_ggml=dims, type_id=dtype, layout=layout['name'],
                         relative_offset=offset, bytes=size, row_bytes=row_bytes))
    alignment = metadata.get('general.alignment', 32)
    if type(alignment) is not int or alignment <= 0 or alignment & (alignment - 1):
        raise ValueError('invalid data alignment')
    data_start = (cursor + alignment - 1) // alignment * alignment if rows else None
    if rows:
        take(data_start - cursor)
    end = data_start
    for row in sorted(rows, key=lambda r: r['relative_offset']):
        offset = row['relative_offset']
        start = data_start + offset
        if offset % alignment or start < end or start + row['bytes'] > file_bytes:
            raise ValueError('unaligned, overlapping or out-of-file tensor span')
        row['absolute_offset'] = start
        end = start + row['bytes']
    tokenizer = {k: v for k, v in metadata.items() if k.startswith('tokenizer.')}
    tokenizer_sha = hashlib.sha256(json.dumps(tokenizer, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
    return dict(data_start=data_start, alignment=alignment, metadata=metadata, tensors=rows,
                tokenizer_metadata_sha256=tokenizer_sha if tokenizer else None)
