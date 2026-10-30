"""CR-01/02: semantic source binding and lossless late-observer failure evidence."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from local_runtime import manifest,evaluate_r9700 as runner


class CodeReviewFixTests(unittest.TestCase):
    def test_tokenizer_edit_is_rejected_by_semantic_source_verifier(self):
        value = dict(root=str(manifest.ROOT),arm='baseline',suite='smoke',memory_budget=manifest.BUDGET,
                     source_files=manifest.source_files(),source_revision=manifest.git_revision())
        tokenizer = manifest.ROOT/'tools/strata_tokenizer.py'
        digest = manifest.digest
        with patch.object(manifest,'digest',side_effect=lambda path:'changed' if Path(path) == tokenizer else digest(path)):
            with self.assertRaisesRegex(RuntimeError,'source inventory'):
                manifest.validate_semantics(value)

    def test_production_guard_helper_edits_are_rejected_by_semantic_verifier(self):
        from local_runtime.tests.test_decode_arms import unit_base
        import json,os,contextlib
        with tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
            directory=Path(folder);base=unit_base(directory)
            profile=directory/'base-profile.json';profile.write_text(json.dumps(base),encoding='utf-8')
            for name,value in (('DATA',directory/'data'),('ORIGINAL',directory/'original'),
                               ('BASE_PROFILE',profile),('PYTHON',directory/'python.exe'),
                               ('VENV_PYTHON',directory/'venv-python.exe')):
                stack.enter_context(patch.object(manifest,name,value))
            stack.enter_context(patch.object(manifest,'original_assets',return_value=base))
            cfg=manifest.expected_config('baseline',directory,base)
            config=directory/'strata-baseline.json';config.write_text(json.dumps(cfg),encoding='utf-8')
            paths=manifest.dependency_paths(cfg,'baseline')
            names=('manage_runtime.py','official_runtime.py','startup_progress.py','runtime_temp_probe.py',
                   'profile_defaults.py','runtime_permissions.py')
            self.assertTrue({manifest.DATA/name for name in names}.issubset(set(paths)))
            for path in paths:
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'small dependency sentinel')
            value=dict(root=str(manifest.ROOT),arm='baseline',suite='smoke',source_files=manifest.source_files(),
                       source_revision=manifest.git_revision(),
                       config=str(config),base_profile_sha256=manifest.digest(profile),
                       environment=manifest.normalized_environment(cfg,os.environ),memory_budget=manifest.BUDGET,
                       dependencies={str(path):manifest.digest(path) for path in paths})
            manifest.validate_semantics(value)
            digest=manifest.digest
            for name in names:
                target=manifest.DATA/name
                with self.subTest(name=name),patch.object(manifest,'digest',side_effect=
                        lambda path:'changed' if Path(path)==target else digest(path)):
                    with self.assertRaisesRegex(RuntimeError,'dependency'):manifest.validate_semantics(value)

    def test_late_unknown_or_error_after_ready_preserves_all_observation_and_blocks_restart(self):
        for kind in ('unknown','errors'):
            with self.subTest(kind=kind):
                clean = dict(created=10.,identities=[dict(pid=100,created=10.,exe='python.exe'),
                                                   dict(pid=101,created=11.,exe='engine.exe')],unknown=[],errors=[])
                late = copy.deepcopy(clean)
                late[kind] = [dict(pid=102)] if kind == 'unknown' else [dict(action='late-inspection',error_type='AccessDenied')]
                process,observer,monitor = Mock(pid=100),Mock(),Mock()
                process.poll.return_value = None
                observer.snapshot.return_value = clean
                observer.finish.return_value = late
                saved = []
                with patch.object(manifest,'verify',return_value=dict(config='fixture.json')), \
                        patch.object(manifest,'read_json',return_value=dict(log='engine.log')), \
                        patch.object(runner.official_runtime,'start_candidate',return_value=(process,observer,{},{})), \
                        patch.object(runner.safety,'owned',return_value=Mock()), \
                        patch.object(runner.safety,'require_owned_listener',return_value=True), \
                        patch.object(runner,'ready',return_value=({},{})), \
                        patch.object(runner.safety,'save',side_effect=lambda state:saved.append(copy.deepcopy(state))), \
                        patch.object(runner.safety,'stop_owned') as cleanup:
                    with self.assertRaisesRegex(RuntimeError,'final observation'):
                        runner.start_session(Path('manifest.json'),'approved',monitor)
                failed = saved[-1]
                self.assertTrue(failed['cleanup_pending'])
                self.assertEqual(failed['created'],10.)
                self.assertEqual(failed['owned_identities'],late['identities'])
                self.assertEqual(failed['spawn_observation'],late)
                cleanup.assert_not_called()
                process.terminate.assert_called_once()  # Exact retained root; unknown/engine are not touched.
                with patch.object(runner.safety,'read_state',return_value=failed):
                    with self.assertRaisesRegex(RuntimeError,'cleanup'):
                        runner.require_candidate_inactive()


if __name__ == '__main__':
    unittest.main()
