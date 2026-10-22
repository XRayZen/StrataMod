from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'native/artifact'))
from acquire import read_range_response, validate_fixture, header_summary, validate_header_summary, validate_fixture_coverage, FIXTURE_REQUESTS
import copy
import hashlib


class Response:
    def __init__(self, status=206, content_range='bytes 10-13/100', body=b'abcd'):
        self.status = status
        self.headers = {'Content-Range': content_range, 'ETag': 'fixture-etag'}
        self.body = body
        self.read_called = False

    def read(self, n):
        self.read_called = True
        return self.body[:n]


class RangeTest(unittest.TestCase):
    def test_exact_bounded_response(self):
        self.assertEqual(read_range_response(Response(), 10, 4, 100)[0], b'abcd')

    def test_200_is_rejected_before_read(self):
        row = Response(status=200)
        with self.assertRaises(ValueError):
            read_range_response(row, 10, 4, 100)
        self.assertFalse(row.read_called)

    def test_wrong_range_identity_and_short_body(self):
        for row in [Response(content_range='bytes 0-3/100'), Response(content_range='bytes 10-13/101'),
                    Response(body=b'abc'), Response(body=b'abcde')]:
            with self.assertRaises(ValueError):
                read_range_response(row, 10, 4, 100)
        with self.assertRaises(ValueError):
            read_range_response(Response(), 10, 4, 100, expected_etag='different')

    def test_fixture_receipt_cross_field_binding(self):
        raw = bytes([127, 1] + [0] * 15)
        tensor = dict(name='w', dims_ggml=[32, 1], type_id=39, layout='MXFP4',
                      row_bytes=17, bytes=17, absolute_offset=32)
        shard = dict(index=2, filename='fixture.gguf', bytes=100, lfs_sha256='a' * 64,
                     full_shard_sha256_verified=False, http_ranges=[dict(etag='fixture-etag')])
        receipt = dict(revision='fixed', shard_index=2, filename='fixture.gguf', file_bytes=100,
                       file_lfs_sha256='a' * 64, full_file_sha_verified=False,
                       tensor='w', type_id=39, layout='MXFP4', dims_ggml=[32, 1], row_bytes=17,
                       selection='row', index=0, absolute_offset=32, bytes=17,
                       http=dict(status=206,start=32,end=48,total=100,etag='fixture-etag'),
                       fixture_sha256=hashlib.sha256(raw).hexdigest(), nonzero_scale_or_scalar_count=1)
        validate_fixture(receipt, tensor, shard, 'fixed', raw)
        changes = [('type_id',43),('layout','WRONG'),('dims_ggml',[1]),('index',999),
                   ('selection','full-vector'),('nonzero_scale_or_scalar_count',0),
                   ('row_bytes',18),('file_bytes',101),('full_file_sha_verified',True),
                   ('absolute_offset',33),('bytes',16)]
        for key, val in changes:
            changed = copy.deepcopy(receipt)
            changed[key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_fixture(changed, tensor, shard, 'fixed', raw)
        for key,val in [('status',200),('start',31),('end',49),('total',101),('etag','other')]:
            changed = copy.deepcopy(receipt)
            changed['http'][key] = val
            with self.subTest(http=key), self.assertRaises(ValueError):
                validate_fixture(changed, tensor, shard, 'fixed', raw)

    def test_header_summary_cannot_change_configuration_or_counts(self):
        header = dict(data_start=32, alignment=32, metadata={
            'deepseek41.expert_used_count': 6, 'tokenizer.ggml.tokens': ['a', 'b'],
            'deepseek41.layers': [1, 14]}, tokenizer_metadata_sha256='fixed', tensors=[])
        summary = header_summary(header)
        validate_header_summary(summary, header)
        for key,value in [('token_count',1),('data_start',64),('alignment',64),('metadata_arrays',{})]:
            changed=copy.deepcopy(summary);changed[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_header_summary(changed, header)
        changed=copy.deepcopy(summary);changed['metadata_scalars']['deepseek41.expert_used_count']=10
        with self.assertRaises(ValueError):
            validate_header_summary(changed, header)

    def test_required_real_fixture_coverage_cannot_be_empty_missing_or_duplicate(self):
        rows=[dict(tensor=name,selection=selection,index=index) for name,selection,index in FIXTURE_REQUESTS]
        validate_fixture_coverage(rows)
        for invalid in [[],rows[:-1],rows+[rows[0]],rows[1:]+[rows[1]]]:
            with self.assertRaises(ValueError):
                validate_fixture_coverage(invalid)


if __name__ == '__main__':
    unittest.main()
