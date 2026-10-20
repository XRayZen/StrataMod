"""Mock the official POSIX smoke's child summary; never run the Linux suite here."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

TOOLS=Path(__file__).resolve().parents[2]/'tools'
sys.path.insert(0,str(TOOLS))
try:
    import minimal_server_smoke as smoke
finally:
    sys.path.remove(str(TOOLS))

class OfficialRuntimeSummary(unittest.TestCase):
    def report(self,text,code=0):
        visible=lambda name:object() if name in ('numpy','jinja2','requests') else None
        with mock.patch.object(smoke,'os',SimpleNamespace(name='posix')), \
                mock.patch.object(smoke.sys,'prefix','fixture-runtime-venv'), \
                mock.patch.object(smoke.importlib.util,'find_spec',side_effect=visible), \
                mock.patch.object(smoke.subprocess,'run',return_value=subprocess.CompletedProcess([],code,'',text)) as run:
            value=smoke.smoke()
        self.assertEqual(run.call_args.kwargs['timeout'],240)
        self.assertEqual(run.call_args.args[0][-1],smoke.TEST_MODULE)
        return value

    def test_plain_or_skipped_success_counts_only_actual_passes(self):
        for text in ('Ran 32 tests in 1.0s\n\nOK\n','Ran 35 tests in 1.0s\n\nOK (skipped=3)\n'):
            with self.subTest(text=text):
                value=self.report(text);self.assertTrue(value['passed']);self.assertEqual(value['tests_run'],32)

    def test_skipped_cases_do_not_satisfy_minimum_actual_passes(self):
        value=self.report('Ran 34 tests in 1.0s\n\nOK (skipped=3)\n')
        self.assertFalse(value['passed']);self.assertEqual(value['tests_run'],31)

    def test_nonzero_exit_cannot_be_success(self):
        self.assertFalse(self.report('Ran 35 tests in 1.0s\n\nOK\n',1)['passed'])

    def test_unknown_or_failed_summary_is_not_success(self):
        for text in ('','Ran 35 tests in 1.0s','Ran 35 tests in 1.0s\n\nFAILED (errors=1)\n',
                     'Ran 35 tests in 1.0s\n\nOK (expected failures=1)\n','Ran 35 tests in 1.0s\n\nOK\nextra'):
            with self.subTest(text=text):
                value=self.report(text);self.assertFalse(value['passed']);self.assertIsNone(value['tests_run'])

    def test_windows_guard_never_starts_a_posix_test(self):
        with mock.patch.object(smoke.sys,'prefix','fixture-runtime-venv'), \
                mock.patch.object(smoke,'os',SimpleNamespace(name='nt')), \
                mock.patch.object(smoke.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'POSIX'):smoke.smoke()
            run.assert_not_called()