"""Terminal unittest summaries keep skips separate from actual passes."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    import minimal_server_smoke as smoke
finally:
    sys.path.remove(str(TOOLS))


class RuntimeSummary(unittest.TestCase):
    def result(self, summary="Ran 35 tests in 0.012s\n\nOK (skipped=3)\n", code=0):
        return subprocess.CompletedProcess([], code, "", summary)

    def test_runtime_smoke_accepts_legal_skips_without_counting_them_as_passes(self):
        visible = lambda name: object() if name in ("numpy", "jinja2", "requests") else None
        with mock.patch.object(smoke, "os", SimpleNamespace(name="posix")), \
                mock.patch.object(smoke.sys, "prefix", "private-runtime-venv"), \
                mock.patch.object(smoke.importlib.util, "find_spec", side_effect=visible), \
                mock.patch.object(smoke.subprocess, "run", return_value=self.result()):
            value = smoke.smoke()
        self.assertTrue(value["passed"])
        self.assertEqual((value["tests_run"], value["tests_skipped"], value["tests_passed"]), (35, 3, 32))

    def test_plain_success(self):
        value = smoke._summary(self.result("setup output\nRan 32 tests in 1.0s\n\nOK\n"))
        self.assertEqual((value["tests_run"], value["tests_skipped"], value["tests_passed"]), (32, 0, 32))
        self.assertTrue(value["passed"])

    def test_standard_crlf_and_blank_lines(self):
        self.assertTrue(smoke._summary(self.result("Ran 35 tests in 1.234s\r\n\r\nOK (skipped=3)\r\n"))["passed"])

    def test_skip_can_leave_too_few_actual_passes(self):
        value = smoke._summary(self.result("Ran 34 tests in 1.000s\n\nOK (skipped=3)\n"))
        self.assertFalse(value["passed"])
        self.assertEqual(value["tests_passed"], 31)

    def test_nonzero_exit_cannot_be_success(self):
        self.assertFalse(smoke._summary(self.result(code=1))["passed"])

    def test_malformed_or_unknown_summaries_have_unknown_counts(self):
        for text in ("", "Ran 35 tests in 0.1s", "Ran -1 tests in 1.0s\n\nOK\n",
                     "Ran 35 tests in nans\n\nOK\n", "Ran 35 tests in 1.0s\n\nFAILED (errors=1)\n",
                     "Ran 35 tests in 1.0s\n\nOK (expected failures=1)\n",
                     "Ran 35 tests in 1.0s\n\nOK (unexpected successes=1)\n",
                     "Ran 35 tests in 1.0s\n\nOK (skipped=-1)\n",
                     "Ran 35 tests in 1.0s\n\nOK (skipped=one)\n",
                     "Ran 35 tests in 1.0s\n\nOK\nextra diagnostic\n"):
            with self.subTest(text=text):
                value = smoke._summary(self.result(text))
                self.assertFalse(value["passed"])
                self.assertIsNone(value["tests_run"])
                self.assertIsNone(value["tests_skipped"])
                self.assertIsNone(value["tests_passed"])

    def test_multiple_summaries_are_not_joined(self):
        text = "Ran 35 tests in 0.1s\n\nOK\nRan 35 tests in 0.2s\n\nOK\n"
        self.assertFalse(smoke._summary(self.result(text))["passed"])

    def test_skips_cannot_exceed_runs(self):
        value = smoke._summary(self.result("Ran 35 tests in 0.1s\n\nOK (skipped=36)\n"))
        self.assertFalse(value["passed"])
        self.assertIsNone(value["tests_passed"])

    def test_parse_precedes_diagnostic_tail_truncation(self):
        value = smoke._summary(self.result("prefix\n" * 1000 + self.result().stderr))
        self.assertTrue(value["passed"])
        multiple = "Ran 35 tests in 1s\n\nOK\n" + "prefix\n" * 1000 + self.result().stderr
        self.assertFalse(smoke._summary(self.result(multiple))["passed"])

    def test_failure_writes_report_and_diagnostic_without_claiming_success(self):
        value = {"passed": False, "test_exit_code": 1, "summary_error": "missing terminal summary",
                 "test_summary": "actual failing test output"}
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "failure.json"
            stderr = io.StringIO()
            with mock.patch.object(smoke, "smoke", return_value=value), \
                    mock.patch.object(sys, "argv", ["minimal_server_smoke", "--report", str(report)]), \
                    contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(smoke.main(), 6)
            self.assertEqual(json.loads(report.read_text()), value)
            self.assertIn("actual failing test output", stderr.getvalue())
            self.assertIn("test_exit_code", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
