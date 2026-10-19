"""Original local ownership regressions, applied to the ported candidate safety functions. No live PID access."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from local_runtime import runtime_safety as manager


class IdentitySafetyTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        forbidden = AssertionError('Live boundary forbidden in ownership fixture')
        self.stack.enter_context(patch.object(manager, 'read_state', side_effect=forbidden))
        self.stack.enter_context(patch.object(manager, 'save', side_effect=forbidden))
        self.stack.enter_context(patch.object(manager.psutil, 'net_connections', side_effect=forbidden))
        self.stack.enter_context(patch.object(manager.psutil, 'Process', side_effect=forbidden))
        self.stack.enter_context(patch.object(manager, 'process_presence', side_effect=forbidden, create=True))
        self.stack.enter_context(patch.object(manager.official_runtime, 'management', side_effect=forbidden))
        self.stack.enter_context(patch.object(manager, 'get_json', side_effect=forbidden))
        self.state = dict(pid=100, created=10., config='fixture.json',
                          owned_identities=[dict(pid=100, created=10., exe='fixture-python.exe')])

    def test_no_such_with_independent_live_pid_is_unverifiable(self):
        with patch.object(manager.psutil, 'Process', side_effect=manager.psutil.NoSuchProcess(100)), \
                patch.object(manager, 'process_presence', return_value='present'):
            with self.assertRaises(RuntimeError):
                manager.owned(self.state)

    def test_no_such_with_independent_access_denial_is_unverifiable(self):
        with patch.object(manager.psutil, 'Process', side_effect=manager.psutil.NoSuchProcess(100)), \
                patch.object(manager, 'process_presence', return_value='unverifiable'):
            with self.assertRaises(RuntimeError):
                manager.owned(self.state)

    def test_independently_gone_pid_returns_no_owner(self):
        with patch.object(manager.psutil, 'Process', side_effect=manager.psutil.NoSuchProcess(100)), \
                patch.object(manager, 'process_presence', return_value='gone'):
            self.assertIsNone(manager.owned(self.state))

    def test_none_fast_ident_does_not_become_verified(self):
        process = Mock(pid=100, _ident=(100, None))
        process.create_time.return_value = 10.
        process.exe.return_value = 'fixture-python.exe'
        process.cmdline.return_value = ['python', '-m', 'serve.server', '--config', 'fixture.json']
        with patch.object(manager.psutil, 'Process', return_value=process):
            with self.assertRaises(RuntimeError):
                manager.owned(self.state)

    def test_children_inspection_loss_is_not_an_empty_verified_tree(self):
        process = Mock(pid=100)
        process.children.side_effect = manager.psutil.NoSuchProcess(100)
        with self.assertRaises(RuntimeError):
            manager.descendants(process, 'fixture.json')
        errors = []
        manager.descendants(process, 'fixture.json', strict=False, errors=errors)
        self.assertEqual(errors[0]['action'], 'enumerate_children')

    def test_unknown_saved_child_blocks_all_cleanup_termination(self):
        root = Mock(pid=100)
        root.create_time.return_value = 10.
        root.exe.return_value = 'fixture-python.exe'
        state = dict(self.state, owned_identities=[dict(pid=101, created=11., exe='fixture-engine.exe')])
        with tempfile.TemporaryDirectory(prefix='cleanup-preflight-', dir=Path(__file__).parents[1] / 'records') as folder:
            directory = Path(folder)
            (directory / 'records').mkdir()
            with patch.object(manager, 'ROOT', directory), patch.object(manager, 'owned', return_value=root), \
                    patch.object(manager, 'descendants', return_value=[]), \
                    patch.object(manager, 'process_identity_status', return_value=manager.IdentityStatus(
                        'unverifiable', reason='fixture child read denied')), \
                    patch.object(manager.psutil, 'wait_procs', return_value=([], [])):
                with self.assertRaises(RuntimeError):
                    manager.stop_owned(state, official_first=False)
            root.terminate.assert_not_called()
            self.assertEqual(state['owned_identities'], [
                dict(pid=101, created=11., exe='fixture-engine.exe')])

    def test_cached_cleanup_candidates_require_complete_fresh_identity(self):
        for source in ('known', 'descendant'):
            for failure in ('captured_none', 'fresh_none', 'fresh_denied', 'fresh_reused'):
                with self.subTest(source=source, failure=failure), tempfile.TemporaryDirectory(
                        prefix='candidate-proof-', dir=Path(__file__).parents[1] / 'records') as folder:
                    directory = Path(folder)
                    (directory / 'records').mkdir()
                    root = Mock(pid=100, _ident=(100, 10.))
                    root.create_time.return_value = 10.
                    root.exe.return_value = 'fixture-python.exe'
                    cached = Mock(pid=101, _ident=(101, None if failure == 'captured_none' else 11.))
                    cached.create_time.return_value = 11.
                    cached.exe.return_value = 'fixture-engine.exe'
                    cached.is_running.return_value = True
                    fresh = Mock(pid=101, _ident=(101, None if failure == 'fresh_none' else 11.))
                    fresh.create_time.return_value = 11.02 if failure == 'fresh_reused' else 11.
                    fresh.exe.return_value = 'fixture-engine.exe'
                    state = dict(self.state)
                    def lookup(pid):
                        if pid == 100:
                            return root
                        if failure == 'fresh_denied':
                            raise manager.psutil.AccessDenied(pid)
                        return fresh
                    with patch.object(manager, 'ROOT', directory), patch.object(manager, 'owned', return_value=root), \
                            patch.object(manager, 'descendants', return_value=[cached] if source == 'descendant' else []), \
                            patch.object(manager.psutil, 'Process', side_effect=lookup) as process_lookup, \
                            patch.object(manager.psutil, 'wait_procs', return_value=([], [])):
                        with self.assertRaises(RuntimeError):
                            manager.stop_owned(state, [cached] if source == 'known' else [], official_first=False)
                    root.terminate.assert_not_called()
                    cached.terminate.assert_not_called()
                    fresh.terminate.assert_not_called()
                    self.assertEqual(state['owned_identities'], self.state['owned_identities'])
                    if failure != 'captured_none':
                        self.assertTrue(any(call.args == (101,) for call in process_lookup.call_args_list))

    def test_cleanup_uses_fresh_process_instead_of_cached_is_running(self):
        with tempfile.TemporaryDirectory(prefix='fresh-candidate-', dir=Path(__file__).parents[1] / 'records') as folder:
            directory = Path(folder)
            (directory / 'records').mkdir()
            root = Mock(pid=100, _ident=(100, 10.))
            root.create_time.return_value = 10.
            root.exe.return_value = 'fixture-python.exe'
            cached = Mock(pid=101, _ident=(101, 11.))
            cached.create_time.return_value = 11.
            cached.exe.return_value = 'fixture-engine.exe'
            cached.is_running.return_value = False
            fresh = Mock(pid=101, _ident=(101, 11.))
            fresh.create_time.return_value = 11.
            fresh.exe.return_value = 'fixture-engine.exe'
            with patch.object(manager, 'ROOT', directory), patch.object(manager, 'owned', return_value=root), \
                    patch.object(manager, 'descendants', return_value=[]), \
                    patch.object(manager.psutil, 'Process', side_effect=lambda pid: root if pid == 100 else fresh), \
                    patch.object(manager.psutil, 'wait_procs', return_value=([], [])):
                stopped = manager.stop_owned(dict(self.state), [cached], official_first=False)
            self.assertIn(101, stopped)
            cached.terminate.assert_not_called()
            fresh.terminate.assert_called_once()

    def test_post_unload_first_seen_allowed_child_never_expands_stop_authority(self):
        for reused in (False,True):
            with self.subTest(reused=reused),tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]/'records') as folder:
                directory = Path(folder)
                (directory/'records').mkdir()
                root = Mock(pid=100,_ident=(100,10.))
                engine = Mock(pid=101,_ident=(101,11.))
                new = Mock(pid=101 if reused else 102,_ident=(101 if reused else 102,12.))
                for process,created in ((root,10.),(engine,11.),(new,12.)):
                    process.create_time.return_value = created
                    process.exe.return_value = str(directory/'allowed-engine.exe')
                rows = [dict(pid=p.pid,created=p.create_time(),exe=p.exe()) for p in (root,engine)]
                state = dict(self.state,owned_identities=list(rows),cleanup_pending=True)
                def status(row,**kwargs):
                    if reused and row['pid']==101 and row['created']==11.:
                        return manager.IdentityStatus('gone')
                    return manager.IdentityStatus('verified',root if row['pid']==100 else new if row['created']==12. else engine)
                def children(process,*args,**kwargs): return [new] if process.pid==100 else []
                with patch.object(manager,'ROOT',directory),patch.object(manager,'owned',return_value=root), \
                        patch.object(manager,'descendants',side_effect=children), \
                        patch.object(manager,'process_identity_status',side_effect=status), \
                        patch.object(manager,'process_presence',return_value='present'), \
                        patch.object(manager,'fresh_cleanup_candidate',side_effect=lambda row:status(row).process), \
                        patch.object(manager.psutil,'wait_procs',return_value=([],[])) as wait:
                    with self.assertRaisesRegex(RuntimeError,'事前検査'):
                        manager.stop_owned(state,official_first=False,post_unload=True)
                for process in (root,engine,new): process.terminate.assert_not_called()
                wait.assert_not_called()
                self.assertTrue(state['cleanup_pending'])
                self.assertIn(dict(pid=new.pid,created=12.,exe=new.exe()),state['owned_identities'])
                self.assertTrue(any(row['action']=='new_descendant_after_unload_not_touched'
                                    for row in state['cleanup_observation']['errors']))
                receipt = json.loads(Path(state['cleanup_receipt']).read_text(encoding='utf-8'))
                self.assertEqual(receipt['stopped_pids'],[])
                self.assertEqual(receipt['phase'],'preflight_rejected')

    def test_post_unload_saved_independently_gone_member_keeps_normal_cleanup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]/'records') as folder:
            directory = Path(folder)
            (directory/'records').mkdir()
            engine = Mock(pid=101,_ident=(101,11.))
            engine.create_time.return_value = 11.
            engine.exe.return_value = str(directory/'allowed-engine.exe')
            state = dict(self.state,owned_identities=[*self.state['owned_identities'],
                         dict(pid=101,created=11.,exe=engine.exe())])
            def status(row,**kwargs):
                return manager.IdentityStatus('gone') if row['pid']==100 else manager.IdentityStatus('verified',engine)
            with patch.object(manager,'ROOT',directory),patch.object(manager,'owned',return_value=None), \
                    patch.object(manager,'descendants',return_value=[]), \
                    patch.object(manager,'process_identity_status',side_effect=status), \
                    patch.object(manager,'process_presence',return_value='gone'), \
                    patch.object(manager,'fresh_cleanup_candidate',return_value=engine), \
                    patch.object(manager.psutil,'wait_procs',return_value=([],[])):
                self.assertEqual(manager.stop_owned(state,official_first=False,post_unload=True),[101])
            engine.terminate.assert_called_once()
            receipt = json.loads(Path(state['cleanup_receipt']).read_text(encoding='utf-8'))
            self.assertEqual([row['pid'] for row in receipt['independently_exited']],[100])


class PostUnloadObservationRaceTests(unittest.TestCase):
    @contextlib.contextmanager
    def race(self, fault=None):
        with tempfile.TemporaryDirectory(prefix='post-unload-race-') as folder, contextlib.ExitStack() as stack:
            directory=Path(folder);(directory/'records').mkdir()
            child=Mock(pid=101,_ident=(101,11.))
            child.create_time.return_value=11.;child.exe.return_value=str(directory/'conhost.exe')
            child.children.side_effect=manager.psutil.NoSuchProcess(101)
            rows=[dict(pid=100,created=10.,exe=str(directory/'python.exe')),
                  dict(pid=101,created=11.,exe=child.exe())]
            state=dict(pid=100,created=10.,config=str(directory/'strata-StrataMod.json'),
                       owned_identities=copy.deepcopy(rows[:1] if fault=='outside_authority' else rows),
                       spawn_observation=dict(created=10.,identities=copy.deepcopy(rows),unknown=[],errors=[]),
                       cleanup_pending=True)
            if fault=='spawn_unknown':state['spawn_observation']['unknown']=[dict(pid=999)]
            if fault=='spawn_error':state['spawn_observation']['errors']=[dict(action='capture',error_type='AccessDenied')]
            observations=[0]
            def identity(row):
                if row['pid']==100:return manager.IdentityStatus('gone')
                observations[0]+=1
                if observations[0]==1:return manager.IdentityStatus('verified',child)
                if fault=='unproven':return manager.IdentityStatus('unverifiable',reason='test-only access denied')
                return manager.IdentityStatus('gone')
            real_descendants=manager.descendants
            def descendants(process,*args,**kwargs):
                result=real_descendants(process,*args,**kwargs)
                if fault=='unknown_action':kwargs['errors'].append(dict(pid=101,action='unexpected_action',error_type='NoSuchProcess'))
                if fault=='unknown_type':kwargs['errors'].append(dict(pid=101,action='enumerate_children',error_type='AccessDenied'))
                return result
            for target,name,kw in ((manager,'ROOT',dict(new=directory)),(manager,'owned',dict(return_value=None)),
                    (manager,'process_identity_status',dict(side_effect=identity)),
                    (manager,'process_presence',dict(return_value='present' if fault=='reused_pid' else 'unverifiable' if fault=='presence_unverifiable' else 'gone')),
                    (manager,'descendants',dict(side_effect=descendants)),(manager,'check_port_available',{}),
                    (manager.psutil,'Process',dict(side_effect=AssertionError('No live process access in race fixture'))),
                    (manager.psutil,'net_connections',dict(side_effect=AssertionError('No live network in race fixture'))),
                    (manager.psutil,'wait_procs',dict(return_value=([],[])))):
                stack.enter_context(patch.object(target,name,**kw))
            yield directory,state,child

    @staticmethod
    def stop(state, child, *, post_unload=True):
        return manager.stop_owned(state,[child],official_first=False,post_unload=post_unload)

    def test_resolved_collection_race_updates_retained_proof_and_preserves_history(self):
        from local_runtime import evaluate_r9700 as runner
        with self.race() as (directory,state,child):
            self.assertEqual(self.stop(state,child),[])
            child.terminate.assert_not_called()
            receipt=json.loads(Path(state['cleanup_receipt']).read_text(encoding='utf-8'))
            self.assertEqual(receipt['errors'],[])
            self.assertEqual(state['cleanup_observation']['errors'],[])
            history=copy.deepcopy(state['post_unload_resolved_errors'])
            self.assertEqual({row['error']['action'] for row in history},{'enumerate_children','inspect_cleanup_candidate'})
            self.assertTrue(all(row['exit']['pid']==101 and row['exit']['created']==11. for row in history))
            proof=runner.pending_exit_proof(dict(state=state,observer=None))
            self.assertTrue(proof['complete']);self.assertTrue(proof['port_free'])
            self.assertEqual(proof['unknown'],[]);self.assertEqual(proof['errors'],[])
            self.assertEqual(state['post_unload_resolved_errors'],history)

    def test_unproven_reused_outside_authority_unknown_action_and_spawn_unknown_stay_blocked(self):
        from local_runtime import evaluate_r9700 as runner
        for fault in ('unproven','presence_unverifiable','reused_pid','outside_authority','unknown_action','unknown_type','spawn_unknown','spawn_error'):
            with self.subTest(fault=fault),self.race(fault) as (directory,state,child):
                with self.assertRaisesRegex(RuntimeError,'事前検査'):self.stop(state,child)
                child.terminate.assert_not_called()
                self.assertTrue(state['cleanup_observation']['errors'])
                proof=runner.pending_exit_proof(dict(state=state,observer=None))
                self.assertFalse(proof['complete']);self.assertTrue(proof['errors'] or proof['unknown'])

    def test_same_exit_race_without_official_unload_keeps_original_errors(self):
        with self.race() as (directory,state,child):
            with self.assertRaisesRegex(RuntimeError,'事前検査'):self.stop(state,child,post_unload=False)
            child.terminate.assert_not_called()
            self.assertEqual({row['action'] for row in state['cleanup_observation']['errors']},
                             {'enumerate_children','inspect_cleanup_candidate'})

    def serve_after_race(self, fault=None):
        from local_runtime import normal_runtime as normal
        with self.race(fault) as (directory,state,child),contextlib.ExitStack() as stack:
            state['kind']=normal.KIND
            held=[False];saved=[]
            @contextlib.contextmanager
            def locks():
                held[0]=True
                try:yield
                finally:held[0]=False
            monitor=Mock();monitor.check.side_effect=KeyboardInterrupt
            monitor.__enter__=Mock(return_value=monitor);monitor.__exit__=Mock(return_value=False)
            def start(pointer,value,monitor,retained):
                retained.update(state=state,observer=None,spawn_possible=True)
                return directory,state
            stop_owned=manager.stop_owned
            def cleanup(current):
                self.assertTrue(held[0]);return stop_owned(current,[child],official_first=False,post_unload=True)
            def hold(*args):
                self.assertTrue(held[0]);raise RuntimeError('fixture entered pending hold')
            for target,name,kw in ((normal,'selected',dict(return_value=({},{}))),(normal,'validate_assets',{}),
                    (normal.runner,'shared_operation',dict(side_effect=locks)),(normal.runner,'production_inactive',{}),
                    (normal,'NormalMonitor',dict(return_value=monitor)),(normal,'start',dict(side_effect=start)),
                    (normal.runner,'wait_request_release',{}),(manager,'stop_owned',dict(side_effect=cleanup)),
                    (normal,'positive_failed_cleanup_proof',dict(return_value=dict(complete=False))),
                    (normal.runner,'hold_pending_cleanup',dict(side_effect=hold)),
                    (manager,'save',dict(side_effect=lambda s:saved.append(copy.deepcopy(s))))):
                stack.enter_context(patch.object(target,name,**kw))
            # Keep the real stop routine behind the normal foreground cleanup call.
            if fault:
                with self.assertRaisesRegex(RuntimeError,'fixture entered pending hold'):normal.serve()
                normal.runner.hold_pending_cleanup.assert_called_once()
            else:
                normal.serve();normal.runner.hold_pending_cleanup.assert_not_called()
            result=json.loads((directory/'result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['generation_requests'],0)
            if fault:
                self.assertEqual(result['status'],'failed');self.assertTrue(saved[-1]['cleanup_pending'])
                self.assertEqual(state['phase'],'cleanup-pending');self.assertTrue(state['cleanup_observation']['errors'])
            else:
                self.assertEqual(result['status'],'stopped');self.assertTrue(result['cleanup']['complete'])
                self.assertFalse(saved[-1]['cleanup_pending']);self.assertTrue(saved[-1]['post_unload_resolved_errors'])
            self.assertFalse(held[0]);child.terminate.assert_not_called()

    def test_normal_serve_ctrl_c_finishes_after_actual_race_cleanup_and_pending_proof(self):
        self.serve_after_race()

    def test_normal_serve_unproven_exit_enters_existing_hold_with_locks(self):
        self.serve_after_race('unproven')


class StateSaveTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]/'records')
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'state.json';self.path.write_text('{"before":true}',encoding='utf-8')
        self.enterContext(patch.object(manager,'STATE',self.path))

    @staticmethod
    def denied(code):
        error=PermissionError(13,'test-owned reader blocks replace');error.winerror=code
        return error

    def test_short_actual_python_reader_release_allows_same_atomic_save(self):
        reader=self.path.open('r',encoding='utf-8')
        release=threading.Thread(target=lambda:(time.sleep(.1),reader.close()))
        release.start()
        try:
            manager.save(dict(after=True))
            self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')),dict(after=True))
        finally:release.join();reader.close()

    def test_persistent_win5_or_32_stops_at_deadline_and_keeps_original_state(self):
        for code in (5,32):
            with self.subTest(code=code):
                clock=[0.];error=self.denied(code);before=self.path.read_bytes()
                def sleep(seconds):clock[0]+=seconds
                with patch.object(Path,'replace',side_effect=error) as replace, \
                     patch.object(manager.time,'monotonic',side_effect=lambda:clock[0]), \
                     patch.object(manager.time,'sleep',side_effect=sleep):
                    with self.assertRaises(PermissionError) as caught:manager.save(dict(after=True))
                self.assertIs(caught.exception,error)
                self.assertGreaterEqual(clock[0],.5);self.assertLessEqual(clock[0],.525)
                self.assertGreater(replace.call_count,1)
                self.assertEqual(self.path.read_bytes(),before)
                self.assertEqual(json.loads(self.path.with_suffix('.tmp').read_text(encoding='utf-8')),dict(after=True))

    def test_non_matching_errors_do_not_retry_or_change_original(self):
        for error in (self.denied(1314),OSError('other IO failure')):
            with self.subTest(error=error),patch.object(Path,'replace',side_effect=error) as replace, \
                 patch.object(manager.time,'sleep') as sleep:
                before=self.path.read_bytes()
                with self.assertRaises(type(error)) as caught:manager.save(dict(after=True))
                self.assertIs(caught.exception,error);replace.assert_called_once();sleep.assert_not_called()
                self.assertEqual(self.path.read_bytes(),before)

    def test_cancel_during_replace_wait_propagates_without_replacing_original(self):
        for cancel in (KeyboardInterrupt(),SystemExit(7)):
            with self.subTest(cancel=type(cancel).__name__), \
                 patch.object(Path,'replace',side_effect=self.denied(5)), \
                 patch.object(manager.time,'sleep',side_effect=cancel):
                before=self.path.read_bytes()
                with self.assertRaises(type(cancel)):manager.save(dict(after=True))
                self.assertEqual(self.path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
