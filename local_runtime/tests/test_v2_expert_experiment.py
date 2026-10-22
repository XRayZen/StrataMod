import copy
import contextlib
import json
import struct
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from pathlib import Path

from local_runtime import v2_expert_experiment as exp


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(args=['--expert-profile', 'shared.bin', '--resident-budget-gib', '16',
                              '--prompt-cache', '6', '--max-context', '262144', '--spec', '4', '--vision'],
                        vision=dict(temp_dir='old', elastic=False), env={'FLAG': '1'},
                        model_name=exp.MODEL)

    def test_profile_rejects_duplicate_and_missing_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.bin'
            exp.write_profile(path, [(l, e) for l in range(48) for e in range(512)])
            self.assertEqual(exp.check_profile(path)['pairs'], 24576)
            rows = [(l, e) for l in range(48) for e in range(512)]
            rows[-1] = rows[0]
            exp.write_profile(path, rows)
            with self.assertRaises(ValueError):
                exp.check_profile(path)

    def test_trial_never_changes_normal_defaults_or_saves_during_eval(self):
        original = copy.deepcopy(self.cfg)
        result = exp.trial_config(self.cfg, Path('trial'), 'PR', Path('learned.bin'))
        self.assertEqual(self.cfg, original)
        self.assertEqual(exp.option(result['args'], '--resident-budget-gib'), '32')
        self.assertEqual(exp.option(result['args'], '--prompt-cache'), '0')
        self.assertNotIn('expert_profile_save', result)
        self.assertEqual(result['env'], self.cfg['env'])
        self.assertEqual(exp.option(result['args'], '--max-context'), '262144')

    def test_save_key_exists_only_for_learning_and_not_reused(self):
        cfg = exp.trial_config(self.cfg, Path('trial'), 'learn', Path('base.bin'))
        self.assertEqual(cfg['expert_profile_save_every'], 0)
        self.assertEqual(cfg['expert_profile_save'], str(Path('trial') / 'learned-profile.bin'))
        self.cfg['expert_profile_save'] = 'other.bin'
        with self.assertRaises(ValueError):
            exp.trial_config(self.cfg, Path('trial'), 'A', Path('base.bin'))

    def test_ram32_requires_margin_for_checkpoint_and_unknown_peak(self):
        row = dict(available_bytes=29 * exp.GIB, commit_margin_bytes=60 * exp.GIB)
        self.assertFalse(exp.ram32_fits(row, baseline_resident=16)['fits'])
        row['available_bytes'] = 65 * exp.GIB
        self.assertTrue(exp.ram32_fits(row, baseline_resident=0)['fits'])

    def test_early_finish_cached_and_nonfinite_are_ineligible(self):
        case = dict(prompt_tokens=4096)
        sample = dict(text='ok', reasoning='', finish_reason='length', wall_seconds=2,
                      first_answer_seconds=.5, first_sse_seconds=.5,
                      usage=dict(prompt_tokens=4096, completion_tokens=128,
                                 prompt_tokens_details=dict(cached_tokens=0)),
                      timings=dict(prompt_n=4096, predicted_n=128, cache_n=0, prompt_ms=300,
                                   predicted_ms=1000, prompt_per_second=12000, predicted_per_second=128))
        log = 'prompt 4096 tokens = 0 reused + 4096 read'
        self.assertEqual(exp.validate_performance(sample, case, log), [])
        for mutation in ('early', 'cached', 'nan'):
            changed = copy.deepcopy(sample)
            if mutation == 'early': changed['usage']['completion_tokens'] = 12
            if mutation == 'cached': changed['usage']['prompt_tokens_details']['cached_tokens'] = 10
            if mutation == 'nan': changed['timings']['predicted_per_second'] = float('nan')
            self.assertTrue(exp.validate_performance(changed, case, log))

    def test_saved_profile_does_not_override_fresh_base_and_eval_does_not_save(self):
        from serve.server import engine_args
        cfg = dict(self.cfg, vision=dict(backend='hip'))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cfg = exp.trial_config(cfg, directory, 'learn', directory / 'base.bin')
            args = engine_args(cfg)
            self.assertEqual(exp.option(args, '--expert-profile'), str(directory / 'base.bin'))
            self.assertEqual(exp.option(args, '--expert-profile-save-every'), '0')
            cfg = exp.trial_config(self.cfg, directory, 'P', directory / 'learned.bin')
            self.assertNotIn('--expert-profile-save', engine_args(cfg))

    def test_reload_after_unload_retains_server(self):
        with patch.object(exp.checked_job, 'original_birth_exit', return_value={'original_gone': True}), \
             patch.object(exp.safety, 'get_json', side_effect=[{'busy': False, 'queued': 0}, {'loaded': True}]):
            with self.assertRaisesRegex(RuntimeError, 'reloaded'):
                exp.confirm_unloaded({}, [{'pid': 100}], authority=lambda s: True)

    def test_base_and_snapshot_tamper_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            exp.write(directory / 'normal-profile.json', self.cfg)
            exp.write_profile(directory / 'base-profile.bin', [(l, e) for l in range(48) for e in range(512)])
            frozen = dict(normal_sha256=exp.digest(directory / 'normal-profile.json'),
                          profile={'sha256': exp.digest(directory / 'base-profile.bin')})
            exp.frozen_inputs(directory, frozen, 'A')
            pairs = [(l, e) for l in range(48) for e in range(512)]
            pairs.reverse()
            exp.write_profile(directory / 'base-profile.bin', pairs)
            with self.assertRaisesRegex(RuntimeError, 'Frozen profile'):
                exp.frozen_inputs(directory, frozen, 'A')
            exp.write(directory / 'normal-profile.json', {'changed': True})
            with self.assertRaisesRegex(RuntimeError, 'snapshot'):
                exp.frozen_inputs(directory, frozen, 'A')

    def test_unverified_ready_engine_gate_never_publishes_ready(self):
        for kind in ('missing', 'argv'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                cfg = dict(self.cfg, exe=str(directory / 'strata.exe'), log=str(directory / 'engine.log'),
                           vision={'exe': str(directory / 'vision.exe')})
                config = directory / 'trial-config.json'
                exp.write(config, cfg)
                rows = [dict(pid=10, created=1., exe='python.exe'),
                        dict(pid=11, created=2., exe=cfg['vision']['exe'])]
                if kind == 'argv': rows.append(dict(pid=12, created=3., exe=cfg['exe']))
                observation = dict(created=1., identities=rows, unknown=[], errors=[])
                observer = Mock()
                observer.snapshot.return_value = observer.finish.return_value = observation
                process = Mock(pid=10)
                process.poll.return_value = None
                saved, retained = [], {}
                with patch.object(exp.runner, 'production_inactive'), \
                     patch.object(exp.checked_job, 'ensure_parent_job'), \
                     patch.object(exp.checked_job, 'require_child'), \
                     patch.object(exp.checked_job, 'membership_pid', return_value=True), \
                     patch.object(exp.subprocess, 'Popen', return_value=process), \
                     patch.object(exp.manifest, 'normalized_environment', return_value={}), \
                     patch.object(exp.official_runtime, 'SpawnObserver', return_value=observer), \
                     patch.object(exp.safety, 'save', side_effect=lambda s: saved.append(copy.deepcopy(s))), \
                     patch.object(exp.safety, 'require_owned_listener', return_value=True), \
                     patch.object(exp, 'ready', return_value=({}, {})), \
                     patch.object(exp.psutil, 'Process', return_value=Mock(cmdline=lambda: ['wrong'])):
                    with self.assertRaises(RuntimeError): exp.start(config, Mock(), retained, {})
                self.assertEqual(retained['state']['phase'], 'loading')
                self.assertTrue(all(s['phase'] != 'ready' for s in saved))

    def test_nonfinite_failure_is_valid_json_and_blocks_next_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            profile = directory / 'normal-profile.json'
            shared = directory / 'shared.bin'
            exp.write(profile, self.cfg)
            shared.write_bytes(b'shared')
            exp.write(directory / 'suite.json', {})
            exp.write(directory / 'experiment.json', dict(normal_sha256=exp.digest(profile),
                      shared_sha256=exp.digest(shared), suite_sha256=exp.digest(directory / 'suite.json'), sources={}))
            trial = directory / 'first'
            trial.mkdir()
            exp.write(trial / 'result.json', dict(status='failed', sample={'rate': float('nan')}))
            parsed = json.loads((trial / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(parsed['sample']['rate'], {'invalid_nonfinite_number': 'nan'})
            with patch.object(exp, 'SHARED', shared), patch.object(exp, 'PLAIN', profile), \
                 patch.object(exp, 'source_snapshot', return_value={}):
                with self.assertRaisesRegex(RuntimeError, 'prior trial failed'):
                    exp.run(directory, 'A', 'next')

    def test_loading_failure_reaches_cleanup_and_persists_nonfinite_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            profile = directory / 'normal-profile.json'
            shared = directory / 'shared.bin'
            exp.write(profile, self.cfg)
            exp.write_profile(shared, [(l, e) for l in range(48) for e in range(512)])
            (directory / 'base-profile.bin').write_bytes(shared.read_bytes())
            exp.write(directory / 'suite.json', {'evaluation': []})
            exp.write(directory / 'experiment.json', dict(normal_sha256=exp.digest(profile),
                      shared_sha256=exp.digest(shared), suite_sha256=exp.digest(directory / 'suite.json'),
                      profile={'sha256': exp.digest(shared)}, sources={}))
            def fail_start(cfg, monitor, retained, result):
                retained.update(spawn_possible=True, process=Mock(), observer=Mock(),
                                state=dict(phase='loading', cleanup_pending=True))
                result['samples'].append({'nonfinite_failure': float('nan')})
                raise RuntimeError('Unverified engine argv')
            def cleanup(process, observer, failed): failed['cleanup_pending'] = False
            with patch.object(exp, 'SHARED', shared), patch.object(exp, 'PLAIN', profile), \
                 patch.object(exp, 'source_snapshot', return_value={}), \
                 patch.object(exp.runner, 'shared_operation', side_effect=contextlib.nullcontext), \
                 patch.object(exp.runner, 'MemoryMonitor'), \
                 patch.object(exp.runner, 'memory_sample', return_value={}), \
                 patch.object(exp.runner, 'preflight_budget', return_value={}), \
                 patch.object(exp, 'start', side_effect=fail_start), \
                 patch.object(exp.runner, 'cleanup_failed_start', side_effect=cleanup) as cleaned:
                with self.assertRaisesRegex(RuntimeError, 'Unverified engine argv'):
                    exp.run(directory, 'A', 'pilot-A')
                cleaned.assert_called_once()
            result = json.loads((directory / 'pilot-A/result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['samples'][0]['nonfinite_failure'], {'invalid_nonfinite_number': 'nan'})


if __name__ == '__main__':
    unittest.main()
