"""No GPU, processes, SDK loads or asset reads: calibration boundary fakes."""
import unittest
from unittest import mock
import tempfile
import contextlib
import os
from pathlib import Path

from local_runtime import calibrate_official as c
from tools.test_calibrate import FakeEngine


class OfficialCalibration(unittest.TestCase):
    BASE = ['--max-context', '262144', '--spec', '4', '--resident-budget-gib', '16']

    def ready_fixture(self,owner,engine,info_text=None):
        import queue,threading
        from serve import server
        root=dict(pid=7,created=1.,exe='engine')
        owner.starts=1;owner.cfg['exe']='engine';owner.trial_args=self.BASE;owner.trial_env={}
        owner.retained['observer']=mock.Mock()
        owner.retained['observer'].snapshot.return_value={'identities':[root]}
        engine.log_path=str(owner.directory/'native.log')
        engine.proc=mock.Mock(pid=7)
        Path(engine.log_path).write_text('R9700 gfx1201',encoding='utf-8')
        with mock.patch.object(c.gpu_observation,'loaded_modules',return_value=[]), \
             mock.patch.object(c.gpu_observation,'windows_displays',return_value=[dict(
                 Name='AMD R9700',PNPDeviceID='VEN_1002&DEV_7551',pci='07')]), \
             mock.patch.object(c.m,'read_json',return_value={}),mock.patch.object(c.m,'require_loader_binding'):
            if info_text is None:
                owner.ready(engine)
            else:
                ready=queue.Queue()
                ready.put(info_text);ready.put('READY 262144 stop')
                hooks=mock.Mock();hooks.ready.side_effect=owner.ready
                hooks.failed.side_effect=lambda engine,error: (_ for _ in ()).throw(error)
                with mock.patch.object(server,'popen',return_value=mock.Mock(pid=7)), \
                     mock.patch.object(server,'contain'),mock.patch.object(server.threading,'Thread'), \
                     mock.patch.object(server.queue,'Queue',return_value=ready):
                    engine._guarded_start('engine',[],None,{}, {},hooks,threading.Event())

    def test_native_info_text_crosses_real_parser_without_numeric_type_mismatch(self):
        from serve import server
        for pcie in ('0.10','0.20'):
            with self.subTest(pcie=pcie),tempfile.TemporaryDirectory() as temp:
                owner=self.owner(Path(temp));engine=server.StrataEngine.__new__(server.StrataEngine)
                engine.info={};engine.log=None;engine.proc=None;engine.max_context=0
                self.ready_fixture(owner,engine,f'INFO pool_workers=13 pcie_frac={pcie} spec_min_p=0.50')
                self.assertEqual(engine.info['pcie_frac'],pcie)
                row=owner.result['native_info'][0]
                self.assertEqual(row['raw_info']['spec_min_p'],'0.50')
                self.assertEqual(row['raw_types']['spec_min_p'],'str')
                self.assertEqual(row['normalized']['pcie_frac'],float(pcie))

    def test_info_rejects_missing_nonfinite_bool_invalid_and_rounded_aliases(self):
        good=dict(pool_workers=13,pcie_frac='0.10',spec_min_p='0.50')
        for key in ('pcie_frac','spec_min_p'):
            for bad in (None,True,'','nonsense','NaN','Infinity','-inf','0.100000000000000001','0.500000000000000001','0.9'):
                with self.subTest(key=key,bad=bad),tempfile.TemporaryDirectory() as temp:
                    owner=self.owner(Path(temp));info=dict(good,**{key:bad})
                    engine=mock.Mock(pid=7,max_context=262144,info=info)
                    with self.assertRaises(RuntimeError):self.ready_fixture(owner,engine)
                    self.assertEqual(owner.calls,0);self.assertEqual(owner.starts,1)
                    self.assertEqual(owner.result['native_info'][0]['raw_info'],info)
            with tempfile.TemporaryDirectory() as temp:
                owner=self.owner(Path(temp));info=dict(good);del info[key]
                with self.assertRaises(RuntimeError):self.ready_fixture(owner,mock.Mock(max_context=262144,info=info))
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            self.ready_fixture(owner,mock.Mock(max_context=262144,info=dict(pool_workers=13,pcie_frac=.1,spec_min_p=.5)))
            self.assertEqual(owner.result['native_info'][0]['normalized'],dict(pcie_frac=.1,spec_min_p=.5))

    def test_only_official_trial_changes_are_allowed(self):
        c.validate_trial(self.BASE, self.BASE + ['--pool-workers', '5'], {})
        c.validate_trial(self.BASE, self.BASE + ['--adapt-every', '1', '--adapt-swaps', '160',
                                              '--adapt-decay', '0.97'], {'STRATA_SH_STREAM': '1'})
        for args, env in ((self.BASE + ['--max-context', '4096'], {}),
                          (self.BASE + ['--pool-workers', '8'], {}),
                          (self.BASE + ['--adapt-async', '1'], {}),
                          (self.BASE, {'HIP_PATH': 'another SDK'})):
            with self.subTest(args=args, env=env), self.assertRaises(RuntimeError):
                c.validate_trial(self.BASE, args, env)

    def test_prediction_is_advisory_and_calls_are_finite(self):
        monitor = mock.Mock()
        controller = c.Controller.__new__(c.Controller)
        controller.monitor = monitor
        controller.retained = {}
        controller.deadline = float('inf')
        controller.aborted = False
        controller.calls = 213
        controller.tokens = 0
        with self.assertRaises(c.CalibrationAbort):
            controller.begin_call(128)
        self.assertEqual(controller.calls, 213)

    def test_guarded_abort_is_not_a_candidate_rejection(self):
        self.assertFalse(issubclass(c.CalibrationAbort, Exception))

    def test_pointer_requires_independent_exact_approval(self):
        with mock.patch.object(c.m, 'digest', return_value='actual'):
            with self.assertRaises(RuntimeError):
                c.selected_manifest(None)

    def owner(self,directory):
        value=dict(directory=str(directory),config=dict(args=self.BASE),dependencies={})
        with mock.patch.object(c.cal,'engine_args',return_value=self.BASE):
            owner=c.Controller(value,mock.Mock())
        owner.persist=mock.Mock()
        owner.trial_config=directory/'config.json'
        return owner

    def test_pending_or_physical_cap_rejects_before_job_or_next_spawn(self):
        with tempfile.TemporaryDirectory() as temp:
            for pending,starts in ((True,1),(False,11)):
                owner=self.owner(Path(temp))
                owner.starts=starts
                owner.retained['spawn_possible']=pending
                with mock.patch.object(c.checked_job,'ensure_parent_job') as job:
                    with self.assertRaises(c.CalibrationAbort):owner.before_spawn(mock.Mock())
                job.assert_not_called()
                self.assertEqual(owner.starts,starts)

    def test_raw_handle_retained_even_when_observer_or_job_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            owner.cfg['exe']='engine'
            owner.trial_args=self.BASE
            owner.retained['state']={}
            engine=mock.Mock()
            with mock.patch.object(c,'EngineObserver') as observer:
                observer.return_value.begin.side_effect=RuntimeError('capture denied')
                with self.assertRaisesRegex(RuntimeError,'capture denied'):owner.spawned(engine)
                self.assertIs(owner.retained['process'],engine.proc)
                self.assertIs(owner.retained['observer'],observer.return_value)

    def test_close_uses_original_quit_and_independent_gone_not_raw_kill(self):
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            proc=mock.Mock()
            proc.poll.return_value=None
            proc.returncode=0
            observer=mock.Mock()
            observer.finish_standalone.return_value={'identities':[]}
            owner.retained.update(process=proc,observer=observer,spawn_possible=True,state={})
            engine=mock.Mock()
            engine.engine=engine
            with mock.patch.object(c,'native_exit_proof',side_effect=[{'complete':False},{'complete':True}]) as proof, \
                 mock.patch.object(c.time,'sleep'), \
                 mock.patch.object(c.safety,'save'),mock.patch.object(c.runner,'hold_pending_cleanup') as hold:
                owner.close(engine)
            proc.stdin.write.assert_called_once_with('QUIT\n')
            proc.wait.assert_called_once_with(60)
            proc.kill.assert_not_called()
            proc.terminate.assert_not_called()
            hold.assert_not_called()
            self.assertEqual(proof.call_count,2)
            self.assertFalse(owner.retained['spawn_possible'])

    def test_failed_cleanup_holds_same_retained_and_aborts_next_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            proc=mock.Mock()
            proc.poll.return_value=None
            proc.wait.side_effect=TimeoutError('still running')
            owner.retained.update(process=proc,observer=mock.Mock(),spawn_possible=True,state={})
            with mock.patch.object(c.runner,'hold_pending_cleanup') as hold,mock.patch.object(c.safety,'save'):
                with self.assertRaises(c.CalibrationAbort):owner.close(None)
            hold.assert_called_once_with(owner.retained,owner.result,owner.directory)
            self.assertTrue(owner.aborted)
            with self.assertRaises(c.CalibrationAbort):owner.before_spawn(mock.Mock())
            proc.kill.assert_not_called()

    def test_first_failure_and_native_partial_survive_double_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            engine=mock.Mock(log_path='native.log',last={'decode_ms':13},progress=(4,20))
            first=RuntimeError('collector original')
            for error in (first,c.CalibrationAbort('outer wrapper')):
                with self.assertRaises(c.CalibrationAbort):owner.failed(engine,error)
            self.assertEqual(owner.result['error'],{'type':'RuntimeError','message':'collector original'})
            self.assertEqual(owner.result['partial']['progress'],(4,20))

    def test_literal_batch_calibrate_dispatch_precedes_setup_and_install(self):
        text=(c.m.ROOT/'START-HERE.bat').read_text(encoding='utf-8')
        self.assertLess(text.index('goto private_calibrate'),text.index('goto run'))
        tail=text.split(':private_calibrate',1)[1]
        self.assertIn('-m local_runtime.calibrate_official %*',tail)
        for forbidden in ('setup.py','winget','pip install','data_folder'):
            self.assertNotIn(forbidden,tail)

    def test_complete_official_single_gpu_sweep_fits_fixed_guarded_caps(self):
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            starts=[]
            def start(args,env=None):
                c.validate_trial(self.BASE,args,env or {})
                self.assertEqual(c.cal.arg_value(args,'--max-context'),'262144')
                starts.append(list(args))
                self.assertLessEqual(len(starts),11)
                engine=FakeEngine(args,lambda f,p,w:50,info_workers=13)
                engine.info['pcie_frac']=0.1
                return c.Trial(engine,owner)
            result=c.cal.measure(self.BASE,[[1]]*3,start,say=lambda *_:None,
                                 extra_workers=[5],hip=True,close_engine=lambda _:None)
            self.assertEqual(result['settings'],{})
            self.assertEqual(len(starts),11)
            self.assertLessEqual(owner.calls,213)
            self.assertLessEqual(owner.tokens,34176)
            self.assertEqual(len(owner.result['requests']),owner.calls)

    def test_pending_save_precedes_possible_spawn_and_failed_save_has_zero_spawn(self):
        with tempfile.TemporaryDirectory() as temp:
            owner=self.owner(Path(temp))
            owner.approved='approved'
            with mock.patch.object(c,'selected_manifest',return_value=owner.value), \
                 mock.patch.object(c.checked_job,'ensure_parent_job'), \
                 mock.patch.object(c.safety,'save',side_effect=OSError('write refused')) as durable:
                with self.assertRaises(OSError):owner.before_spawn(mock.Mock())
            self.assertTrue(durable.call_args.args[0]['birth_pending'])
            self.assertTrue(durable.call_args.args[0]['cleanup_pending'])
            self.assertEqual(owner.starts,0)
            self.assertFalse(owner.retained.get('spawn_possible',False))
            with mock.patch.object(c,'selected_manifest',return_value=owner.value), \
                 mock.patch.object(c.checked_job,'ensure_parent_job'),mock.patch.object(c.safety,'save') as durable:
                owner.before_spawn(mock.Mock())
            durable.assert_called_once()
            self.assertTrue(owner.retained['spawn_possible'])
            self.assertEqual(owner.starts,1)

    def test_full_dependency_read_tamper_or_expiry_blocks_before_cal_or_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            value=dict(directory=temp,config={},dependencies={})
            for reason in ('source changed','selection changed','config changed','expired'):
                changed=False
                def selection(_):
                    if changed:raise RuntimeError(reason)
                    return value
                def full_read(*_):
                    nonlocal changed
                    changed=True
                with mock.patch.object(c,'selected_manifest',side_effect=selection), \
                     mock.patch.object(c.runner,'shared_operation',side_effect=contextlib.nullcontext), \
                     mock.patch.object(c.runner,'production_inactive'),mock.patch.object(c,'dependency_paths',return_value=[]), \
                     mock.patch.object(c.m,'verify_dependencies',side_effect=full_read) as heavy, \
                     mock.patch.object(c.cal,'run') as run,mock.patch.object(c.checked_job,'ensure_parent_job') as job:
                    with self.assertRaisesRegex(RuntimeError,reason):c.run('approved')
                heavy.assert_called_once()
                run.assert_not_called()
                job.assert_not_called()
                self.assertFalse((Path(temp)/'run.claim').exists())

    def test_asset_closure_hash_rejects_same_size_preserved_stat_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            native=root/'model-00001-of-00003.gguf'
            cfg=dict(args=['--native',str(native),'--ple-gguf',str(root/'model-00002-of-00003.gguf'),
                           '--pack',str(root/'pack')])
            with mock.patch.object(c.m,'dependency_paths',return_value=[]):paths=c.dependency_paths(cfg)
            self.assertEqual(len([p for p in paths if p.suffix=='.gguf']),3)
            for path in paths:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'original')
            fixed={str(path):c.m.digest(path) for path in paths}
            c.m.verify_dependencies(paths,fixed)
            for target in (paths[1],root/'pack/dense.bin'):
                with self.subTest(target=target):
                    info=target.stat()
                    target.write_bytes(b'modified')
                    os.utime(target,ns=(info.st_atime_ns,info.st_mtime_ns))
                    self.assertEqual(target.stat().st_size,info.st_size)
                    self.assertEqual(target.stat().st_mtime_ns,info.st_mtime_ns)
                    with self.assertRaisesRegex(RuntimeError,'contents changed'):c.m.verify_dependencies(paths,fixed)
                    value=dict(directory=temp,config=cfg,dependencies=fixed)
                    with mock.patch.object(c,'selected_manifest',return_value=value), \
                         mock.patch.object(c.runner,'shared_operation',side_effect=contextlib.nullcontext), \
                         mock.patch.object(c.runner,'production_inactive'),mock.patch.object(c,'dependency_paths',return_value=paths), \
                         mock.patch.object(c.cal,'run') as run,mock.patch.object(c.checked_job,'ensure_parent_job') as job:
                        with self.assertRaisesRegex(RuntimeError,'contents changed'):c.run('approved')
                    run.assert_not_called()
                    job.assert_not_called()
                    target.write_bytes(b'original')


if __name__ == '__main__':
    unittest.main()
