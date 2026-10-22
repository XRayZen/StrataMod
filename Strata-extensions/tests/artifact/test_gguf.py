import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'native/artifact'))
from gguf import parse_header, NeedMore


def text(s):
    b = s.encode()
    return struct.pack('<Q', len(b)) + b


def sample(offset=0, dims=(32, 2), dtype=39, duplicate=False):
    names = ['weight', 'weight'] if duplicate else ['weight']
    b = b'GGUF' + struct.pack('<IQQ', 3, len(names), 1)
    b += text('general.alignment') + struct.pack('<II', 4, 32)
    for name in names:
        b += text(name) + struct.pack('<I', len(dims))
        b += struct.pack('<' + 'Q' * len(dims), *dims) + struct.pack('<IQ', dtype, offset)
    return b + bytes((-len(b)) % 32)


class HeaderTest(unittest.TestCase):
    def test_native_span(self):
        h = parse_header(sample(), 4096)
        self.assertEqual(h['tensors'][0]['bytes'], 34)
        self.assertEqual(h['tensors'][0]['row_bytes'], 17)
        self.assertEqual(h['tensors'][0]['absolute_offset'], h['data_start'])

    def test_short_prefix_needs_more(self):
        for n in (0, 7, 24, len(sample()) - 1):
            with self.subTest(n=n), self.assertRaises(NeedMore):
                parse_header(sample()[:n], 4096)

    def test_metadata_only_shard_has_no_tensor_padding(self):
        b = b'GGUF' + struct.pack('<IQQ', 3, 0, 1)
        b += text('general.name') + struct.pack('<I', 8) + text('tokenizer-only')
        h = parse_header(b, len(b))
        self.assertIsNone(h['data_start'])
        self.assertEqual(h['tensors'], [])

    def test_invalid_native_shapes_offsets_types_names(self):
        for b in (sample(offset=1), sample(dims=(31, 2)), sample(dims=(0,)),
                  sample(dtype=117), sample(duplicate=True), sample(offset=4096)):
            with self.subTest(b=b), self.assertRaises(ValueError):
                parse_header(b, 4096)

    def test_untrusted_header_is_bounded(self):
        for b in (b'NOPE' + sample()[4:], sample()[:4] + struct.pack('<I', 99) + sample()[8:],
                  b'GGUF' + struct.pack('<IQQ', 3, 2**63, 0)):
            with self.assertRaises(ValueError):
                parse_header(b, 4096)

    def test_distinct_tensors_cannot_overlap(self):
        b = b'GGUF' + struct.pack('<IQQ', 3, 2, 0)
        for name in ['a', 'b']:
            b += text(name) + struct.pack('<IQIQ', 1, 32, 39, 0)
        b += bytes((-len(b)) % 32)
        with self.assertRaises(ValueError):
            parse_header(b, 4096)


if __name__ == '__main__':
    unittest.main()
