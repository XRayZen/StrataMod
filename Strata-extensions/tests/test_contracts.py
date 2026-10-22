"""Offline metadata contracts; no GPU/runtime qualification is implied."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'control'))
from contracts import validate_contract, validate_placement, same_launch


class ContractsTest(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / 'control/deepseek41.contract.json').read_text(encoding='utf-8'))

    def test_planned_descriptor_is_not_runtime_evidence(self):
        validate_contract(self.contract)
        self.assertEqual(self.contract['evidence']['header_inventory'], 'pending-T03')

    def test_bad_schema_family_variant_and_source_are_rejected(self):
        for path, value in [(('schema_version',), 2), (('model', 'family'), 'qwen4exp'),
                            (('model', 'variant'), 'Q4'), (('sources', 'strata', 'revision'), 'main'),
                            (('sources', 'maya', 'revision'), '0' * 40),
                            (('model', 'quant_policy'), 'requantize-q4'),
                            (('model', 'tokenizer_family'), 'qwen')]:
            with self.subTest(path=path):
                row = copy.deepcopy(self.contract)
                owner = row
                for key in path[:-1]:
                    owner = owner[key]
                owner[path[-1]] = value
                with self.assertRaises(ValueError):
                    validate_contract(row)

    def test_reference_does_not_claim_adoption_or_inventory_success(self):
        for field, value in [('header_inventory', 'verified'), ('native_layouts', 'verified'),
                             ('tokenizer_identity', 'verified')]:
            row = copy.deepcopy(self.contract)
            row['evidence'][field] = value
            with self.assertRaises(ValueError):
                validate_contract(row)
        row = copy.deepcopy(self.contract)
        row['sources']['recipe']['adoption'] = 'adopted'
        with self.assertRaises(ValueError):
            validate_contract(row)

    def test_all_four_modes_have_meaningful_role_validation(self):
        primary, secondary = 'pci:0000:01:00.0', 'pci:0000:02:00.0'
        valid = [dict(mode='single', primary=primary, secondary=None),
                 dict(mode='cache-only', primary=primary, secondary=secondary),
                 dict(mode='expert-assist', primary=primary, secondary=secondary, assignment=[0, 383]),
                 dict(mode='layer-split', primary=primary, secondary=secondary, cut=20, head='secondary')]
        for row in valid:
            validate_placement(row)
        invalid = [dict(mode='single', primary=primary, secondary=secondary),
                   dict(mode='cache-only', primary=primary, secondary=None),
                   dict(mode='cache-only', primary=primary, secondary=secondary, assignment=[0]),
                   dict(mode='expert-assist', primary=primary, secondary=primary, assignment=[0]),
                   dict(mode='expert-assist', primary=primary, secondary=secondary, assignment=[]),
                   dict(mode='expert-assist', primary=primary, secondary=secondary, assignment=[384]),
                   dict(mode='expert-assist', primary=primary, secondary=secondary, assignment=[0, 0]),
                   dict(mode='layer-split', primary=primary, secondary=secondary, cut=40, head='secondary'),
                   dict(mode='layer-split', primary=primary, secondary=secondary, cut=20, head='primary')]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate_placement(row)

    def test_launch_identity_binds_epoch_bundle_and_ignores_transport(self):
        launch = dict(bundle_id='fixture-bundle', tokenizer_identity='fixture-tokenizer',
                      asset_revision='f' * 40, profile_snapshot='a' * 64, runtime_epoch='fixture-epoch',
                      placement=dict(mode='single', primary='fixture-pci-1', secondary=None))
        observed = copy.deepcopy(launch)
        observed['transfer_path'] = 'host-bounce'
        self.assertTrue(same_launch(launch, observed))
        for field in ['bundle_id', 'runtime_epoch', 'tokenizer_identity', 'profile_snapshot', 'asset_revision']:
            changed = copy.deepcopy(observed)
            changed[field] = 'different'
            self.assertFalse(same_launch(launch, changed))
        self.assertFalse(same_launch({}, {}))


if __name__ == '__main__':
    unittest.main()
