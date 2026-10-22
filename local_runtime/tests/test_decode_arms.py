"""The approved decode candidates change exactly one explicit engine option."""
from pathlib import Path
import unittest

from local_runtime import manifest


def unit_base(root=Path('fixture')):
    root=Path(root)
    return dict(exe=str(root/'text.exe'),tokenizer=str(root/'tokenizer'),args=[
        '--native',str(root/'model.gguf'),'--pack',str(root/'pack'),'--mtp',str(root/'mtp'),
        '--expert-profile',str(root/'experts.json'),'--resident-experts','--max-context','262144',
        '--spec','4','--prefill','auto','--prompt-cache','6'])


class DecodeArmTests(unittest.TestCase):
    def setUp(self):
        self.base = unit_base()
        self.baseline = manifest.expected_config('baseline',Path('fixture'),self.base,'screen')

    def test_d1_changes_spec_only_and_preserves_mtp_context_budget_and_pcie_auto(self):
        self.assertIn('d1-spec2',manifest.ARMS)
        cfg = manifest.expected_config('d1-spec2',Path('fixture'),self.base,'screen')
        self.assertEqual(cfg['args'][cfg['args'].index('--spec')+1],'2')
        restored = list(cfg['args'])
        restored[restored.index('--spec')+1] = '4'
        self.assertEqual(dict(cfg,args=restored),self.baseline)
        self.assertEqual(cfg['args'][cfg['args'].index('--max-context')+1],'262144')
        self.assertEqual(cfg['args'][cfg['args'].index('--resident-budget-gib')+1],'16')
        self.assertNotIn('--pcie-frac',cfg['args'])
        self.assertIn('--mtp',cfg['args'])

    def test_d2_adds_pool_workers_only_and_baseline_input_is_not_mutated(self):
        import copy
        original = copy.deepcopy(self.base)
        self.assertIn('d2-workers8',manifest.ARMS)
        cfg = manifest.expected_config('d2-workers8',Path('fixture'),self.base,'screen')
        self.assertEqual(cfg['args'][cfg['args'].index('--pool-workers')+1],'8')
        restored = list(cfg['args'])
        index = restored.index('--pool-workers')
        del restored[index:index+2]
        self.assertEqual(dict(cfg,args=restored),self.baseline)
        self.assertEqual(self.base,original)
        self.assertNotIn('--pool-workers',self.baseline['args'])
        self.assertEqual(self.baseline['args'][self.baseline['args'].index('--spec')+1],'4')
        self.assertEqual(self.baseline['env'],{})


if __name__ == '__main__':
    unittest.main()
