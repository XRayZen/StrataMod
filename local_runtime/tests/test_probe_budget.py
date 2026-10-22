"""Probe-only operational estimate; no SDK, GPU, HTTP or process launch."""
import copy
from pathlib import Path
import json
import unittest
from unittest import mock
from local_runtime import manifest as m,evaluate_r9700 as runner,image_phase
from local_runtime.tests import test_asset_passes as assets


class ProbeBudget(unittest.TestCase):
    fixture=assets.AssetPasses.fixture

    def test_only_probe_has_its_factory_budget_and_every_other_suite_stays_text_default(self):
        probe=dict(resident_gib=0,nonresident_physical_gib=8,nonresident_commit_gib=8,
                   uncertainty_gib=9,available_floor_gib=4,commit_floor_gib=8)
        for suite in m.SUITES:
            actual=m.memory_budget(suite)
            self.assertEqual(actual,probe if suite=='vision-probe' else m.BUDGET)
            actual['resident_gib']=999
            self.assertEqual(m.memory_budget(suite),probe if suite=='vision-probe' else m.BUDGET)
        with self.assertRaises(RuntimeError):m.memory_budget('unknown')

    def test_typed_factory_rejects_bool_float_missing_added_or_cross_suite_budget(self):
        value=dict(suite='vision-probe',memory_budget=m.memory_budget('vision-probe'))
        m.require_memory_budget(value)
        changes=[]
        for key in value['memory_budget']:
            for replacement in (False,float(value['memory_budget'][key]),-1):
                altered=copy.deepcopy(value);altered['memory_budget'][key]=replacement;changes.append(altered)
        for altered in (dict(value,memory_budget=m.BUDGET),dict(value,memory_budget={}),
                        dict(value,memory_budget=dict(value['memory_budget'],extra=0)),dict(value,suite='vision-encode'),*changes):
            with self.subTest(altered=altered),self.assertRaises(RuntimeError):m.require_memory_budget(altered)

    def test_preflight_probe_21_25_and_text_68_67_boundaries(self):
        def sample(available,commit):return dict(available_bytes=available*runner.GIB,commit_margin_bytes=commit*runner.GIB)
        for suite,available,commit in (('vision-probe',21,25),('smoke',68,67),('vision-encode',68,67)):
            with mock.patch.object(runner,'memory_sample',return_value=sample(available,commit)):
                result=runner.preflight_budget(suite=suite)
                self.assertEqual((result['required_available_gib'],result['required_commit_gib']),(available,commit))
            for low in (sample(available-1,commit),sample(available,commit-1)):
                with mock.patch.object(runner,'memory_sample',return_value=low):
                    advisory=runner.preflight_budget(suite=suite)
                    self.assertFalse(advisory['predicted_fits'])
                    self.assertTrue(advisory['startup_prediction_advisory'])

    def test_real_semantic_entry_rejects_budget_suite_phase_and_argv_tamper_zero_spawn(self):
        real_semantics=m.validate_semantics
        for kind in ('budget','bool','suite','phase','argv'):
            with self.subTest(kind=kind),self.fixture() as f:
                path,sha=m.prepare('vision-hip10.1','vision-probe')
                value=m.read_json(path)
                if kind=='budget':value['memory_budget']=m.BUDGET
                elif kind=='bool':value['memory_budget']['resident_gib']=False
                elif kind=='suite':value['suite']='vision-encode';value['max_starts']=3;value['max_encodes']=12
                else:
                    cfg=m.read_json(value['config'])
                    if kind=='phase':cfg['phase']='vision-encode'
                    else:cfg['commands'][0].append('--gpu')
                    Path(value['config']).write_text(json.dumps(cfg),encoding='utf-8')
                    value['config_sha256']=m.digest(value['config'])
                path.write_text(json.dumps(value),encoding='utf-8');sha=m.digest(path)
                m.validate_semantics.side_effect=real_semantics
                with mock.patch.object(image_phase,'require_fixed_dependencies'),\
                     mock.patch.object(m.subprocess,'check_output',return_value=m.HEAD),\
                     self.assertRaises(RuntimeError):runner.run(path,sha)
                f['spawn'].assert_not_called();runner.safety.save.assert_not_called()

    def test_encode_receipt_keeps_its_text_budget_while_prior_probe_keeps_probe_budget(self):
        probe=dict(suite='vision-probe',memory_budget=m.memory_budget('vision-probe'),source_files={},dependencies={})
        value=dict(suite='vision-encode',memory_budget=m.memory_budget('vision-encode'),source_files={},dependencies={},
                   probe_reference=dict(path=str(m.LOCAL/'records/fixture-result.json'),sha256='fixed'))
        result=dict(status='passed',cleanup=dict(status='passed'),manifest=str(m.LOCAL/'records/fixture-manifest.json'),
                    manifest_sha256='fixed',identity=dict(ordinal=1,arch='gfx1201'))
        with mock.patch.object(m,'digest',return_value='fixed'),mock.patch.object(m,'read_json',return_value=result),\
             mock.patch.object(m,'_verify_authority',return_value=probe):
            self.assertEqual(m.image_reference(value),result['identity'])
            value['memory_budget']=probe['memory_budget']
            with self.assertRaises(RuntimeError):m.image_reference(value)

    def test_predicted_shortage_is_advisory_at_initial_and_post_hash_boundary(self):
        real_preflight=runner.preflight_budget
        for after_hash in (False,True):
            with self.subTest(after_hash=after_hash),self.fixture() as f:
                path,sha=m.prepare('vision-hip10.1','vision-probe')
                self.assertEqual(m.read_json(path)['memory_budget'],m.memory_budget('vision-probe'))
                samples=[dict(available_bytes=(21 if after_hash else 20)*runner.GIB,commit_margin_bytes=25*runner.GIB),
                         dict(available_bytes=20*runner.GIB,commit_margin_bytes=25*runner.GIB)]
                runner.preflight_budget.side_effect=lambda **kw:real_preflight(**kw)
                with mock.patch.object(runner,'memory_sample',side_effect=samples):result=runner.run(path,sha)
                self.assertFalse(result['memory_budget_before_spawn']['predicted_fits'])
                self.assertTrue(result['memory_budget_before_spawn']['startup_prediction_advisory'])
                f['spawn'].assert_called_once()


if __name__=='__main__':unittest.main()
