"""Tiny file fixtures for heavy-asset pass counts; zero native/SDK launches."""
import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from local_runtime import manifest as m,evaluate_r9700 as runner,official_runtime as official,standalone_phase as phase,image_phase


class AssetPasses(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(dir=m.LOCAL/'records') as folder:
            root=Path(folder);asset=root/'model.gguf';asset.write_bytes(b'original asset')
            source=root/'source.py';source.write_text('# fixed',encoding='utf-8')
            profile=root/'profile.json';profile.write_text('{}',encoding='utf-8')
            held=[False];full=[];after_full=[];real_digest=m.digest
            @contextlib.contextmanager
            def locks():
                held[0]=True
                try:yield
                finally:held[0]=False
            def config(arm,directory,base,suite,**kwargs):
                return dict(phase='vision-probe',commands=[['fixed-native','--list-devices']],
                            log=str(directory/'native.log'),cwd=str(directory),ordinal=None)
            def semantics(value,*,verify_assets=True):
                if verify_assets:
                    full.append(held[0]);m.verify_dependencies([asset],value['dependencies'])
                    for action in after_full:action()
                elif set(value['dependencies'])!={str(asset)}:
                    raise RuntimeError('inventory changed')
            with contextlib.ExitStack() as stack:
                for target,name,kwargs in (
                    (m,'LOCAL',dict(new=root)),(m,'BASE_PROFILE',dict(new=profile)),
                    (m,'git_revision',dict(return_value=dict(baseline=m.HEAD,head=m.HEAD,tree='1'*40))),
                    (m,'original_assets',dict(return_value={})),(m,'expected_config',dict(side_effect=config)),
                    (m,'dependency_paths',dict(return_value=[asset])),(m,'source_files',dict(return_value={str(source):real_digest(source)})),
                    (m,'validate_semantics',dict(side_effect=semantics)),(m,'digest',dict(wraps=real_digest)),
                    (image_phase,'environment',dict(return_value={'fixed':'yes'})),
                    (runner,'shared_operation',dict(side_effect=locks)),(runner,'production_inactive',dict()),
                    (runner,'preflight_budget',dict(return_value={})),(runner,'MemoryMonitor',dict()),
                    (official,'standalone_environment',dict(return_value={})),
                    (official.checked_job,'ensure_parent_job',dict()),(official.checked_job,'require_child',dict()),
                    (runner.safety,'save',dict()),(official,'SpawnObserver',dict()),
                    (phase,'wait_probe',dict()),(phase,'native_exit_proof',dict(return_value=dict(complete=True)))):
                    stack.enter_context(mock.patch.object(target,name,**kwargs))
                process=mock.Mock(pid=123);process.poll.return_value=0
                observer=official.SpawnObserver.return_value
                observer.snapshot.return_value=dict(created=1,identities=[dict(pid=123,created=1,exe='fixed-native')],unknown=[],errors=[])
                with mock.patch.object(official.subprocess,'Popen',return_value=process) as spawn:
                    yield dict(root=root,asset=asset,source=source,full=full,spawn=spawn,after_full=after_full)

    @staticmethod
    def asset_reads(asset):
        return sum(Path(call.args[0])==asset for call in m.digest.call_args_list)

    def test_prepare_has_one_asset_pass_but_public_verify_stays_full(self):
        with self.fixture() as f:
            path,sha=m.prepare('vision-hip10.1','vision-probe')
            self.assertEqual(self.asset_reads(f['asset']),1)
            m.digest.reset_mock();f['full'].clear()
            m.verify(path,sha)
            self.assertEqual(self.asset_reads(f['asset']),1)
            self.assertEqual(f['full'],[False])

    def test_run_full_asset_pass_occurs_once_inside_shared_locks_before_spawn(self):
        with self.fixture() as f:
            path,sha=m.prepare('vision-hip10.1','vision-probe')
            m.digest.reset_mock();f['full'].clear()
            runner.run(path,sha)
            self.assertEqual(self.asset_reads(f['asset']),1)
            self.assertEqual(f['full'],[True])
            f['spawn'].assert_called_once()

    def test_same_size_asset_replacement_is_refused_before_any_spawn(self):
        with self.fixture() as f:
            path,sha=m.prepare('vision-hip10.1','vision-probe')
            f['asset'].write_bytes(b'changed! asset')
            with self.assertRaisesRegex(RuntimeError,'dependency contents'):
                runner.run(path,sha)
            f['spawn'].assert_not_called()
            with self.assertRaisesRegex(RuntimeError,'dependency contents'):
                official.start_standalone(path,sha,retained={})
            f['spawn'].assert_not_called()

    def test_source_or_config_change_during_the_asset_read_is_refused_at_launch_boundary(self):
        for kind in ('source','config'):
            with self.subTest(kind=kind),self.fixture() as f:
                path,sha=m.prepare('vision-hip10.1','vision-probe')
                target=f['source'] if kind=='source' else Path(m.read_json(path)['config'])
                f['after_full'].append(lambda:target.write_text('changed while assets were read',encoding='utf-8'))
                with self.assertRaisesRegex(RuntimeError,kind):runner.run(path,sha)
                f['spawn'].assert_not_called()

    def test_abort_cancel_collector_failure_or_start_budget_change_during_hash_refuses_spawn(self):
        for kind in ('abort','cancel','collector','budget'):
            with self.subTest(kind=kind),self.fixture() as f:
                path,sha=m.prepare('vision-hip10.1','vision-probe')
                error=KeyboardInterrupt('cancel while hashing') if kind=='cancel' else RuntimeError(kind+' while hashing')
                def trip():
                    if kind=='budget':runner.preflight_budget.side_effect=error
                    else:runner.MemoryMonitor.return_value.__enter__.return_value.check.side_effect=error
                f['after_full'].append(trip)
                with self.assertRaises(type(error)):runner.run(path,sha)
                f['spawn'].assert_not_called()
                self.assertFalse(runner.safety.save.called)


if __name__=='__main__':unittest.main()
