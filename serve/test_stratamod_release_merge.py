"""Release integration contracts with synthetic processes; no runtime or SDK use."""
import io
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from serve import server as s
from serve.frontend import ChatTemplate


class ReleaseOwnership(unittest.TestCase):
    def vision(self, directory, *, pending=False):
        v = s.Vision(dict(exe='gpu-reader', cpu_exe='cpu-reader', gpu=True,
                          mmproj='projection', model='text', max_tokens=2048), lazy=True)
        original_dir = v.dir
        self.addCleanup(lambda: __import__('shutil').rmtree(original_dir, ignore_errors=True))
        v.dir = directory
        v.proc = Mock(pid=123, stdin=io.StringIO(), stdout=io.StringIO('ERR GPU unavailable\n'))
        v.proc.poll.return_value = None
        v.proc.wait.side_effect = subprocess.TimeoutExpired('synthetic reader', 5)
        v.proc.kill.side_effect = OSError('synthetic kill refusal')
        v.cleanup_pending = pending
        return v

    def service(self, v):
        tok = s.ByteTokenizer()
        engine = s.MockEngine(tok, "synthetic", max_context=4096)
        engine.alive = Mock(return_value=False)
        engine.restart = Mock()
        engine.unload = Mock()
        engine.alive.return_value = False
        engine.max_context = 4096
        svc = s.Service(engine, tok, ChatTemplate(s.ROOT / 'serve/chat_template.jinja'), vision=v)
        return svc

    def test_existing_owner_exit_failure_prevents_replacement_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d)); original = v.proc
            with patch.object(s, 'popen', return_value=original) as spawn:
                with self.assertRaises(s.VisionCleanupPending):
                    v._start()
            self.assertIs(v.proc, original)
            self.assertTrue(v.cleanup_pending)
            self.assertEqual(spawn.call_count, 0)  # an existing pending owner is retried first
            self.assertIsNotNone(v.fallback)

    def test_fresh_gpu_spawn_containment_failure_keeps_owner_and_blocks_cpu(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d)); original = v.proc; v.proc = None
            with patch.object(s.subprocess, 'Popen', return_value=original) as spawn, \
                    patch.object(s.lifeline, 'mechanism', return_value='job'), \
                    patch.object(s.lifeline.winjob, 'contain', side_effect=OSError('synthetic containment fault')):
                with self.assertRaises(s.VisionCleanupPending):
                    v._start()
            self.assertIs(v.proc, original)
            self.assertTrue(v.cleanup_pending)
            self.assertEqual(spawn.call_count, 1)
            self.assertIsNotNone(v.fallback)

    def test_fresh_gpu_bad_ready_unknown_exit_blocks_cpu(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d)); original = v.proc; v.proc = None
            with patch.object(s, 'popen', return_value=original) as spawn:
                with self.assertRaises(s.VisionCleanupPending):
                    v._start()
            self.assertIs(v.proc, original)
            self.assertTrue(v.cleanup_pending)
            self.assertEqual(spawn.call_count, 1)

    def test_fresh_gpu_bad_ready_confirmed_exit_allows_cpu_once(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d)); original = v.proc; v.proc = None
            original.kill.side_effect = None; original.wait.side_effect = None
            original.wait.return_value = 0
            cpu = Mock(stdin=io.StringIO(), stdout=io.StringIO('READY 2048\n'))
            with patch.object(s, 'popen', side_effect=[original, cpu]) as spawn:
                v._start()
            self.assertIs(v.proc, cpu)
            self.assertFalse(v.cleanup_pending)
            self.assertEqual(spawn.call_count, 2)
            self.assertIsNone(v.fallback)

    def test_failed_cpu_shutdown_retains_owner_and_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d)); original = v.proc
            marker = v.dir / 'in-use.sve'; marker.write_bytes(b'synthetic')
            with self.assertRaises(s.VisionCleanupPending):
                v.shutdown()
            self.assertIs(v.proc, original)
            self.assertTrue(marker.is_file())

    def test_service_cannot_skip_pending_cpu_unload_or_load(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d), pending=True)
            svc = self.service(v)
            for action in (svc.unload, svc.load):
                with self.subTest(action=action.__name__), self.assertRaises(s.VisionCleanupPending):
                    action()
            svc.engine.restart.assert_not_called()

    def test_official_reader_keeps_2048_tokens_and_cpu_fallback_without_private_flag(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d))
            self.assertEqual(v.max_tokens, 2048)
            self.assertNotIn('--require-hip', v.spawn[0])
            self.assertNotIn('--require-hip', v.fallback[0])
            self.assertNotIn('--gpu', v.fallback[0])

    def test_pending_cpu_encode_retains_output_and_rejects_before_input(self):
        with tempfile.TemporaryDirectory() as d:
            v = self.vision(Path(d), pending=True)
            with patch.object(v, 'normalize') as normalize:
                with self.assertRaises(s.VisionCleanupPending):
                    v.encode(b'synthetic')
                normalize.assert_not_called()

    def test_guarded_raw_spawn_retains_owner_before_containment(self):
        proc = Mock()
        with patch.object(s.subprocess, 'Popen', return_value=proc), patch.object(s.lifeline, 'popen') as ordinary:
            self.assertIs(s.popen('engine', ['synthetic'], _guarded=True), proc)
        ordinary.assert_not_called()

    def test_authority_binds_new_official_imports_and_native_build_inputs(self):
        from local_runtime import manifest
        sources = manifest.source_files()
        for relative in ('strata_control/vision_reader.py', 'strata_control/procs.py',
                         'tools/calibrate.py',
                         'strata_cli/client.py', 'strata_cli/launch/__init__.py',
                         'tools/vision/CMakeLists.txt', 'tools/vision/gpu_arch.h',
                         'tools/vision/strata_vision.cpp', 'tools/vision/amd_vision/diagnostics.cpp'):
            self.assertIn(str(manifest.ROOT / relative), sources)


if __name__ == '__main__':
    unittest.main()
