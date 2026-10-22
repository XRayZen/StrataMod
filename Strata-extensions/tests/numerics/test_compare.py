import copy
import unittest
import json
from pathlib import Path
from compare import compare,check_selection


class CompareTest(unittest.TestCase):
    def setUp(self):
        contract=json.loads(Path(__file__).with_name('reference-contract.json').read_text(encoding='utf-8'))
        self.expected=contract['comparison']['synthetic_expected_manifest']
        self.tolerance=contract['comparison']['small_exact_baseline']

    def test_exact_and_zero_norm_baseline(self):
        self.assertEqual(compare(self.expected, copy.deepcopy(self.expected), self.tolerance)['max_abs'], 0.)
        zero = copy.deepcopy(self.expected);zero['values'] = [0.] * 8
        self.assertEqual(compare(zero, zero, self.tolerance)['nrmse'], 0.)
        tiny=copy.deepcopy(zero);tiny['values']=[1e-8] * 8
        fallback=dict(self.tolerance,zero_norm_atol=1e-7)
        self.assertEqual(compare(zero,tiny,fallback)['nrmse'],0.)

    def test_metadata_shape_length_and_finite_fail_closed(self):
        mutations = [('shape',[2, 3]),('dtype','bf16'),('token_ids',[6, 3]),
                     ('positions',[1, 2]),('next_token_ids',[2, 6]),('bos_shift',1),
                     ('values',[]),('values',[0.] * 7),('values',[float('nan')] * 8)]
        for key,val in mutations:
            got=copy.deepcopy(self.expected);got[key]=val
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(self.expected,got,self.tolerance)

    def test_wrong_nibble_scale_cast_and_derived_metric_fail(self):
        for delta in (1., 0.5, 1 / 256):
            got=copy.deepcopy(self.expected);got['values'][1] += delta
            with self.assertRaises(ValueError):
                compare(self.expected,got,self.tolerance)
        huge=copy.deepcopy(self.expected);huge['values']=[1e308] * 8
        with self.assertRaises(ValueError):
            compare(huge, huge, self.tolerance)

    def test_corrupt_expected_manifest_is_not_self_qualifying(self):
        for key,value in [('token_ids',[]),('positions',[0]),('next_token_ids',[4,2]),('shape',[])]:
            invalid=copy.deepcopy(self.expected);invalid[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(invalid,copy.deepcopy(invalid),self.tolerance)

    def test_observed_integer_contract_rejects_bool_and_float_equality(self):
        for key,value in [('token_ids',[True,3]),('positions',[0.,1.]),
                          ('next_token_ids',[3.,2.]),('bos_shift',False),('shape',[2.,4.])]:
            invalid=copy.deepcopy(self.expected);invalid[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                compare(self.expected,invalid,self.tolerance)

    def test_synthetic_tie_and_near_tie_allowed_sets(self):
        contract=json.loads(Path(__file__).with_name('reference-contract.json').read_text(encoding='utf-8'))
        for case in contract['selection_fixtures']:
            for ids in case['accepted']:
                check_selection(case,ids)
            for ids in case['rejected']:
                with self.subTest(ids=ids),self.assertRaises(ValueError):
                    check_selection(case,ids)
            wrong=copy.deepcopy(case);wrong['allowed_tie_ids'] += [3]
            with self.assertRaises(ValueError):
                check_selection(wrong,case['accepted'][0])


if __name__ == '__main__':
    unittest.main()
