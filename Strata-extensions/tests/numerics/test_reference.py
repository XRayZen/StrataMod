import copy
import json
import math
import hashlib
from pathlib import Path
import unittest

from reference import decode_block, fp32_bits, bf16_bits, rmsnorm_trace

ROOT = Path(__file__).resolve().parent


class ReferenceTest(unittest.TestCase):
    def check_decode_result(self,row,actual):
        if 'expected_class' in row:
            self.assertEqual(['nan' if math.isnan(v) else ('-inf' if v < 0 else '+inf')
                              if math.isinf(v) else 'finite' for v in actual],row['expected_class'])
        else:
            self.assertEqual([fp32_bits(v) for v in actual],row['expected_fp32_bits'])

    def test_q_format_literal_oracle(self):
        vectors = json.loads((ROOT / 'known-vectors.json').read_text(encoding='utf-8'))
        for row in vectors['decode']:
            with self.subTest(name=row['name']):
                actual = decode_block(row['type_id'], bytes.fromhex(row['hex']))
                self.check_decode_result(row,actual)
        for row in vectors['bf16_cast']:
            self.assertEqual(bf16_bits(float.fromhex(row['input_hexfloat'])), row['expected_bf16_bits'])

    def test_finite_replacement_cannot_satisfy_inf_or_nan_oracle(self):
        vectors=json.loads((ROOT/'known-vectors.json').read_text(encoding='utf-8'))
        for row in vectors['decode']:
            if 'expected_class' in row:
                with self.subTest(name=row['name']),self.assertRaises(AssertionError):
                    self.check_decode_result(row,[1.0]*len(row['expected_class']))

    def test_zero_policy_is_native_format_specific(self):
        vectors=json.loads((ROOT/'known-vectors.json').read_text(encoding='utf-8'))
        mx=next(row for row in vectors['decode'] if row['name']=='MXFP4-native-zero-canonical')
        self.assertTrue(all(fp32_bits(v)=='00000000' for v in decode_block(39,bytes.fromhex(mx['hex']))))
        with self.assertRaises(AssertionError):
            self.check_decode_result(mx,[-0.]*32)
        self.assertEqual(fp32_bits(decode_block(0,bytes.fromhex('00000080'))[0]),'80000000')
        self.assertTrue(all(fp32_bits(v)=='80000000' for v in decode_block(43,bytes.fromhex('7f'+'80'*32))))

    def test_q_real_blocks_are_bound_to_t03_receipts(self):
        contract=json.loads((ROOT/'reference-contract.json').read_text(encoding='utf-8'))
        receipt_path=ROOT.parent/'artifact/fixture-receipts.json'
        self.assertEqual(hashlib.sha256(receipt_path.read_bytes()).hexdigest(), contract['real_fixture_receipt_sha256'])
        receipts=json.loads(receipt_path.read_text(encoding='utf-8'))
        types=set()
        for row in receipts['fixtures']:
            raw=Path(row['fixture_path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['fixture_sha256'])
            size={0:4,8:34,39:17,43:33}[row['type_id']]
            for offset in (0, len(raw)-size):
                values=decode_block(row['type_id'],raw[offset:offset+size])
                self.assertTrue(all(math.isfinite(v) for v in values))
            types.add(row['type_id'])
        self.assertEqual(types,{0,8,39,43})

    def test_n_official_rms_literal_trace(self):
        oracle = json.loads((ROOT / 'n-rms-trace.json').read_text(encoding='utf-8'))
        for row in oracle['cases']:
            with self.subTest(name=row['name']):
                actual = rmsnorm_trace(row['input_pattern'], row['weight'], oracle['hidden'], oracle['epsilon'])
                self.assertEqual(actual, row['expected'])

    def test_wrong_epsilon_and_early_output_cast_are_detected(self):
        oracle = json.loads((ROOT / 'n-rms-trace.json').read_text(encoding='utf-8'))
        row = next(r for r in oracle['cases'] if r['name'] == 'small-weighted')
        wrong_eps = rmsnorm_trace(row['input_pattern'], row['weight'], oracle['hidden'], 1e-6)
        wrong_cast = rmsnorm_trace(row['input_pattern'], row['weight'], oracle['hidden'], oracle['epsilon'], early_cast=True)
        self.assertNotEqual(wrong_eps['output_bf16_pattern'], row['expected']['output_bf16_pattern'])
        self.assertNotEqual(wrong_cast['output_bf16_pattern'], row['expected']['output_bf16_pattern'])

    def test_invalid_blocks_and_nonfinite_n_inputs_are_rejected(self):
        for kind, data in [(117, b''), (39, bytes(16)), (8, bytes(33)), (43, bytes(32))]:
            with self.assertRaises(ValueError):
                decode_block(kind, data)
        with self.assertRaises(ValueError):
            rmsnorm_trace([float('nan')], 1, 5120, 1e-20)


if __name__ == '__main__':
    unittest.main()
