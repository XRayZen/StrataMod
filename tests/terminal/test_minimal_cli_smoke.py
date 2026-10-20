"""The no-site smoke distinguishes entry preflight from dispatcher JSON."""
import subprocess
import sys
from pathlib import Path
import unittest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    import minimal_cli_smoke as smoke
finally:
    sys.path.remove(str(TOOLS))


class PreflightRecord(unittest.TestCase):
    python = "/test/python"
    missing = ("jinja2", "numpy")

    def result(self, code=5, stdout="", stderr=None):
        if stderr is None:
            stderr = (
                "strata: the interpreter /test/python is missing packages the API server needs: jinja2, numpy.\n"
                "        Starting and serving never install anything. Use the Strata terminal archive (it carries them),\n"
                "        or install them yourself: python -m pip install -r requirements.txt\n"
                "        (status, monitor, timeskip and tune plan do not need them)\n")
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def check(self, result):
        return smoke._preflight_record(result, self.missing, self.python)

    def test_known_dependency_refusal(self):
        self.assertEqual(self.check(self.result()),
                         {"exit_code": 5, "missing_packages": list(self.missing),
                          "interpreter": self.python, "auto_install": False})

    def test_other_exit_is_rejected(self):
        for code in (0, 1, 2, 4, 6):
            with self.subTest(code=code), self.assertRaises(RuntimeError):
                self.check(self.result(code=code))

    def test_stdout_is_not_a_dependency_refusal(self):
        for stdout in ('{"schema_version":1}', "unexpected\n"):
            with self.subTest(stdout=stdout), self.assertRaises(RuntimeError):
                self.check(self.result(stdout=stdout))

    def test_packages_must_match_the_same_interpreter_probe(self):
        with self.assertRaises(RuntimeError):
            self.check(self.result(stderr=self.result().stderr.replace("jinja2, numpy", "jinja2")))

    def test_wrong_interpreter_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check(self.result(stderr=self.result().stderr.replace(self.python, "/other/python")))

    def test_unknown_message_or_traceback_is_rejected(self):
        for stderr in ("missing dependencies", "Traceback: failure\n" + self.result().stderr,
                       self.result().stderr + "extra failure\n"):
            with self.subTest(stderr=stderr), self.assertRaises(RuntimeError):
                self.check(self.result(stderr=stderr))

    def test_probe_requires_known_nonempty_ordered_packages(self):
        for missing in ((), ("unknown",), ("numpy", "jinja2"), ("numpy", "numpy")):
            with self.subTest(missing=missing), self.assertRaises(RuntimeError):
                smoke._preflight_record(self.result(), missing, self.python)

    def test_actionable_no_install_message_is_required(self):
        with self.assertRaises(RuntimeError):
            self.check(self.result(stderr=self.result().stderr.replace("never install anything", "install automatically")))

    def test_json_record_validation_remains_strict(self):
        for result in (self.result(), self.result(code=0, stdout="{}", stderr=""),
                       self.result(code=0, stdout='{"schema_version":1}\n{}', stderr="")):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                smoke._record(result, 0)


if __name__ == "__main__":
    unittest.main()
