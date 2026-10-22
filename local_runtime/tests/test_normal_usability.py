"""Normal settings must not inherit bounded experiment-only restrictions."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_runtime import normal_runtime as normal,runtime_safety as safety


class NormalUsability(unittest.TestCase):
    def setUp(self):
        from local_runtime.tests.test_normal_runtime import normal_authorities
        normal_authorities(self)

    def test_normal_profile_restores_official_prompt_cache_default_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=normal.profile(Path(tmp))
        self.assertEqual(cfg['args'][cfg['args'].index('--prompt-cache')+1],'6')
        self.assertEqual(cfg['args'][cfg['args'].index('--pool-workers')+1],'3')
        self.assertEqual(cfg['vision']['max_tokens'],300)

    def test_normal_low_ram_is_not_abort_and_no_experiment_thread_starts(self):
        monitor=normal.NormalMonitor(Path('not-opened.jsonl'))
        with patch.object(normal.runner.MemoryMonitor,'__enter__',side_effect=AssertionError('experiment collector started')):
            with monitor:
                for _ in range(4):monitor.observe(dict(available_bytes=0,commit_margin_bytes=0))
                monitor.check()
                self.assertFalse(monitor.abort.is_set())
                self.assertIsNone(monitor.thread)
        experiment=normal.runner.MemoryMonitor(Path('not-opened.jsonl'))
        experiment.observe(dict(available_bytes=0,commit_margin_bytes=0))
        self.assertTrue(experiment.abort.is_set())

    def test_normal_identity_and_cancel_are_still_fail_closed(self):
        monitor=normal.NormalMonitor(Path('not-opened.jsonl'));monitor.engine=dict(pid=1)
        with patch.object(safety,'process_identity_status',return_value=safety.IdentityStatus('gone')):
            with self.assertRaises(RuntimeError):monitor.check()
        monitor=normal.NormalMonitor(Path('not-opened.jsonl'));monitor.cancel_requested=lambda:True
        with self.assertRaises(KeyboardInterrupt):monitor.check()

    def test_optional_startup_forecast_failure_warns_and_keeps_running(self):
        with patch.object(normal.runner,'preflight_budget',side_effect=OSError('diagnostic unavailable')),\
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(normal.startup_forecast()['status'],'unavailable')
        self.assertIn('advisory',output.getvalue())


if __name__=='__main__':unittest.main(verbosity=2)
