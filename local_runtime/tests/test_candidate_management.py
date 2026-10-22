"""Official management accepts one explicit candidate without changing defaults."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('candidate_mcp', ROOT / 'tools/strata_mcp.py')
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class CandidateManagementTests(unittest.TestCase):
    def test_default_config_and_tracking_paths_are_unchanged(self):
        runtime = mcp.Strata(ROOT)
        self.assertEqual(runtime.state_dir, ROOT / '.strata-mcp')
        self.assertEqual(runtime.run_python(), str(runtime.venv_python()))

    def test_explicit_config_tracking_and_python_are_used(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'profiles/strata-test.json'
            config.parent.mkdir()
            config.write_text('{"model_name":"test"}', encoding='utf-8')
            tracking = root / 'records/native'
            runtime = mcp.Strata(root, config_path=config, tracking_dir=tracking, python='python-test')
            self.assertEqual(runtime.configs(), [config])
            self.assertEqual(runtime.find_config('test'), config)
            self.assertEqual(runtime.state_dir, tracking)
            self.assertEqual(runtime.run_python(), 'python-test')

    def test_explicit_config_does_not_discover_other_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / 'strata-first.json'
            first.write_text('{}', encoding='utf-8')
            second = root / 'strata-second.json'
            second.write_text('{}', encoding='utf-8')
            runtime = mcp.Strata(root, config_path=first)
            self.assertEqual(runtime.configs(), [first])
            with self.assertRaises(mcp.ToolError):
                runtime.find_config('second')


if __name__ == '__main__':
    unittest.main()
