"""CPU fakes only: optional calibration lifecycle and pre-READY failures."""
import queue
import threading
import unittest
from unittest import mock

from tools import calibrate as cal
from tools.test_calibrate import FakeEngine
from serve import server


class Abort(BaseException):
    pass


class CalibrationLifecycle(unittest.TestCase):
    def test_close_hook_keeps_official_choice_and_every_trial_context(self):
        base = ['--max-context', '262144', '--spec', '4']
        created, closed = [], []

        def start(args, env=None):
            self.assertEqual(cal.arg_value(args, '--max-context'), '262144')
            engine = FakeEngine(args, lambda f, p, w: 50, info_workers=2)
            created.append(engine)
            return engine

        with mock.patch.object(cal, 'close', side_effect=AssertionError('raw close')):
            result = cal.measure(base, [[1]] * 3, start, say=lambda *_: None,
                                 hip=True, close_engine=closed.append)
        self.assertEqual(result['settings'], {})
        self.assertEqual(result['env'], {})
        self.assertEqual(closed, created)

    def test_abort_from_constructor_stops_before_next_candidate(self):
        starts, closed = [], []

        def start(args, env=None):
            starts.append(args)
            if len(starts) == 2:
                raise Abort('pre-READY failure retained by lifecycle')
            return FakeEngine(args, lambda f, p, w: 50, info_workers=2)

        with self.assertRaises(Abort):
            cal.measure(['--max-context', '262144'], [[1]], start,
                        say=lambda *_: None, close_engine=closed.append)
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(closed), 1)


class ConstructorLifecycle(unittest.TestCase):
    def request_engine(self):
        engine=self.make_engine()
        engine.proc=self.process
        engine.lifecycle=mock.Mock()
        engine.alive=lambda:True
        engine.batch=0
        engine.silence_s=0
        engine.lines=queue.Queue()
        engine.can_stop=True
        return engine

    def test_request_guard_rejects_before_any_gen_write(self):
        engine=self.request_engine()
        failure=Abort('cancel already latched')
        engine.lifecycle.check.side_effect=failure
        with self.assertRaises(Abort) as caught:
            list(engine.generate([1],128,{},threading.Event()))
        self.assertIs(caught.exception,failure)
        self.process.stdin.write.assert_not_called()
        self.process.stdin.flush.assert_not_called()

    def test_request_partial_failure_preserves_original_exception(self):
        engine=self.request_engine()
        failure=Abort('collector original')
        engine.lifecycle.check.side_effect=[None,failure]
        engine.lifecycle.failed.side_effect=lambda e,error: (_ for _ in ()).throw(error)
        with self.assertRaises(Abort) as caught:
            list(engine.generate([1],128,{},threading.Event()))
        self.assertIs(caught.exception,failure)
        engine.lifecycle.failed.assert_called_once_with(engine,failure)
        self.process.kill.assert_not_called()

    def make_engine(self):
        engine = server.StrataEngine.__new__(server.StrataEngine)
        engine.proc = None
        engine.log = None
        engine.info = {}
        engine.max_context = 0
        return engine

    def call(self, engine, lifecycle, lines):
        ready = queue.Queue()
        for line in lines:
            ready.put(line)
        with mock.patch.object(server, 'popen', return_value=self.process) as spawn, \
             mock.patch.object(server, 'contain') as contain, \
             mock.patch.object(server.threading, 'Thread'), \
             mock.patch.object(server.queue, 'Queue', return_value=ready):
            engine._guarded_start('engine', [], None, {}, {}, lifecycle, threading.Event())
        return spawn, contain

    def setUp(self):
        self.process = mock.Mock()

    def test_original_popen_is_retained_before_contain_and_ready(self):
        engine = self.make_engine()
        lifecycle = mock.Mock()
        lifecycle.spawned.side_effect = lambda e: self.assertIs(e.proc, self.process)
        spawn, contain = self.call(engine, lifecycle, ['INFO context=262144', 'READY 262144 stop'])
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(engine.max_context, 262144)
        lifecycle.before_spawn.assert_called_once_with(engine)
        lifecycle.spawned.assert_called_once_with(engine)
        lifecycle.ready.assert_called_once_with(engine)
        lifecycle.failed.assert_not_called()
        self.process.kill.assert_not_called()

    def test_pre_ready_failure_uses_retained_process_and_never_raw_kill_or_wait(self):
        for failure in (RuntimeError('collector/OOM'), KeyboardInterrupt('cancel')):
            with self.subTest(failure=failure):
                engine = self.make_engine()
                lifecycle = mock.Mock()
                lifecycle.check.side_effect = failure
                lifecycle.failed.side_effect = Abort('latched')
                with self.assertRaises(Abort):
                    self.call(engine, lifecycle, [])
                self.assertIs(engine.proc, self.process)
                lifecycle.failed.assert_called_once_with(engine, failure)
                self.process.kill.assert_not_called()
                self.process.wait.assert_not_called()

    def test_early_exit_and_timeout_do_not_retry(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                engine = self.make_engine()
                lifecycle = mock.Mock()
                lifecycle.failed.side_effect = Abort('retained cleanup')
                with mock.patch.object(server, 'ENGINE_READY_S', -1 if timeout else 900), \
                     self.assertRaises(Abort):
                    self.call(engine, lifecycle, [] if timeout else [None])
                lifecycle.spawned.assert_called_once_with(engine)
                lifecycle.failed.assert_called_once()
                self.process.kill.assert_not_called()
                self.process.wait.assert_not_called()

    def test_auto_restart_cannot_leave_guarded_lifecycle(self):
        engine = self.make_engine()
        engine.lifecycle = mock.Mock()
        engine.lifecycle.failed.side_effect = Abort('restart forbidden')
        with self.assertRaises(Abort):
            engine.restart()
        engine.lifecycle.failed.assert_called_once()
        self.process.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
