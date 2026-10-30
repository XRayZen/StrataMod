"""Opt-in HIP candidate regressions; no SDK, process or GPU required."""
import contextlib
import io
import unittest
import tempfile
import threading
import struct
import subprocess
import base64
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from serve import server


class HipReserve(unittest.TestCase):
    def resolve(self, extra=(), vision=True, backend="hip"):
        cfg = {"backend": backend, "args": ["--native", "huihui.pack", "--ctx", "262144", *extra]}
        if vision:
            cfg["vision"] = {"backend": backend, "gpu": True}
        with mock.patch.object(server.sys, "platform", "win32"), contextlib.redirect_stdout(io.StringIO()):
            return server.engine_args(cfg)

    def test_windows_hip_floor_with_and_without_existing_vision_flag(self):
        for extra in ([], ["--vision"]):
            with self.subTest(extra=extra):
                args = self.resolve(extra)
                self.assertEqual(args.count("--vision"), 1)
                self.assertEqual(args.count("--vram-reserve-mib"), 1)
                self.assertEqual(args[args.index("--vram-reserve-mib") + 1], "2560")

    def test_explicit_valid_reserve_is_preserved(self):
        for value in ("2560", "4096"):
            extra = ["--vision", "--vram-reserve-mib", value]
            self.assertEqual(self.resolve(extra)[-len(extra):], extra)

    def test_invalid_ambiguous_or_insufficient_reserve_is_rejected(self):
        for extra in (["--vram-reserve-mib"], ["--vram-reserve-mib", "--vision"],
                      ["--vram-reserve-mib", "abc"], ["--vram-reserve-mib", "700"],
                      ["--vram-reserve-mib", "2560", "--vram-reserve-mib", "4096"],
                      ["--vram-reserve-mib=700"]):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.resolve(extra)

    def test_text_and_cuda_defaults_are_unchanged(self):
        self.assertEqual(self.resolve(vision=False), ["--native", "huihui.pack", "--ctx", "262144"])
        self.assertEqual(self.resolve(backend="cuda")[-3:], ["--vision", "--vram-reserve-mib", "700"])


class HipImageLimits(unittest.TestCase):
    def vision(self):
        return server.Vision({"exe": "encoder", "model": "m", "mmproj": "p", "gpu": True,
                              "backend": "hip"}, lazy=True)

    def png(self, size=(16, 16)):
        from PIL import Image
        data = io.BytesIO()
        Image.new("RGB", size, "blue").save(data, format="PNG")
        return data.getvalue()

    def test_limits_validate_real_image_before_child_io(self):
        v = self.vision()
        try:
            self.assertEqual(v.checked_image(self.png()), self.png())
            for data in (b"\x89PNG\r\n\x1a\nbroken", self.png((4097, 1)), self.png((2049, 2048)),
                         b"x" * ((20 << 20) + 1)):
                with self.subTest(size=len(data)), self.assertRaises(ValueError):
                    v.checked_image(data)
        finally:
            v.shutdown()

    def test_request_images_follow_existing_sequential_encode_and_keep(self):
        v = self.vision()
        try:
            first,second=Path('first.sve'),Path('second.sve')
            with mock.patch.object(v,"encode",side_effect=[(first,2),(second,3)]) as encode:
                self.assertEqual(v.encode_all(["one","two"]),[(first,2),(second,3)])
            self.assertEqual([call.args[0] for call in encode.call_args_list],["one","two"])
            self.assertEqual(encode.call_args_list[1].kwargs['keep'],[first])
        finally:
            v.shutdown()

    def test_hip_defaults_and_live_capability(self):
        v = self.vision()
        try:
            self.assertEqual(v.spawn[0][-2:], ["--max-tokens", "300"])
            self.assertFalse(v.capability()["available"])
            self.assertEqual(v.capability()["backend"], "hip")
        finally:
            v.shutdown()

    def test_invalid_explicit_token_caps_fail_before_allocating_scratch(self):
        for value in (0, -1, True, 1.5, "300", None):
            with self.subTest(value=value), mock.patch.object(server.Vision, "work_dir") as directory:
                with self.assertRaises(ValueError):
                    server.Vision({"exe": "encoder", "model": "m", "mmproj": "p", "gpu": True,
                                   "backend": "hip", "max_tokens": value}, lazy=True)
                directory.assert_not_called()

    def test_cancel_interrupts_child_wait_and_reaps_it(self):
        v = self.vision()
        proc = mock.Mock(stdout=io.StringIO(""))
        proc.poll.return_value = None
        proc.wait.return_value = 0
        v.proc = proc
        cancel = threading.Event()
        cancel.set()
        try:
            with self.assertRaises(server.ClientGone):
                v._readline(60, "encoding", cancel=cancel)
            proc.kill.assert_called_once()
            proc.wait.assert_called_once()
        finally:
            v.proc = None
            v.shutdown()

    def pending_proc(self, kill_fails=False):
        release = threading.Event()
        proc = mock.Mock(pid=12345)
        proc.stdout.readline.side_effect = lambda: release.wait(1) and ""
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired("encoder", 5)
        if kill_fails:
            proc.kill.side_effect = PermissionError("kill denied")
        return proc, release

    def pending_service(self, kill_fails=False):
        from serve.test_server import UnloadableEngine
        v = self.vision()
        proc, release = self.pending_proc(kill_fails)
        v.proc, v.stopped = proc, False
        (v.dir / "owned.img").write_bytes(b"owned")
        tok = server.ByteTokenizer()
        engine = UnloadableEngine(tok, "ok", max_context=4096)
        svc = server.Service(engine, tok, server.ChatTemplate(server.ROOT / "serve/chat_template.jinja"), vision=v)
        self.addCleanup(release.set)
        def cleanup():
            v.proc = None
            v.shutdown()
        self.addCleanup(cleanup)
        return svc, v, proc

    def control_http(self, svc, path):
        handler_type = server.make_handler(svc)
        handler = handler_type.__new__(handler_type)
        handler.path, handler.watch_done, handler.record = path, None, None
        handler._authorized = handler._control_body = handler._own_page = lambda *args: True
        handler._foreign_page = lambda: False
        handler._body = lambda: b"{}"
        handler._json = mock.Mock()
        handler.do_POST()
        handler._json.assert_called_once()
        return handler._json.call_args.args

    def test_service_unload_retains_pending_child_when_text_is_already_unloaded(self):
        for kill_fails in (False, True):
            with self.subTest(kill_fails=kill_fails):
                svc, v, proc = self.pending_service(kill_fails)
                with mock.patch.object(server, "popen") as spawn:
                    for unload in (svc.unload, svc.unload, lambda: svc.unload_waiting(1)):
                        with self.assertRaises(server.VisionCleanupPending):
                            unload()
                        self.assertFalse(svc.engine.alive())
                        self.assertIs(v.proc, proc)
                        self.assertTrue(v.cleanup_pending)
                        self.assertTrue((v.dir / "owned.img").exists())
                        self.assertTrue(svc.fifo.acquire(blocking=False))
                        svc.fifo.release()
                    spawn.assert_not_called()
                    proc.poll.return_value = 0
                    self.assertEqual(svc.unload(), "unloaded")
                    self.assertIsNone(v.proc)
                    self.assertFalse(v.cleanup_pending)
                    self.assertEqual(svc.unload(), "not loaded")
                    self.assertTrue(v.dir.exists())  # unload keeps the cache until shutdown
                    v.shutdown()
                    self.assertFalse(v.dir.exists())

    def test_http_unload_repeats_503_until_the_same_handle_confirms_exit(self):
        for path in ("/unload", "/unload?wait=1", "/v1/unload"):
            with self.subTest(path=path):
                svc, v, proc = self.pending_service(kill_fails=True)
                with mock.patch.object(server, "popen") as spawn:
                    for _ in range(2):
                        code, body = self.control_http(svc, path)
                        self.assertEqual(code, 503)
                        self.assertEqual(body["error"]["type"], "server_error")
                        self.assertIn("cleanup pending", body["error"]["message"])
                        self.assertIs(v.proc, proc)
                        self.assertTrue((v.dir / "owned.img").exists())
                    spawn.assert_not_called()
                    proc.poll.return_value = 0
                    code, body = self.control_http(svc, path)
                    self.assertEqual(code, 200)
                    self.assertEqual(body["status"], "unloaded")
                    self.assertIsNone(v.proc)

    def test_service_load_preserves_cleanup_pending_type_without_text_restart(self):
        for pending, elastic, text_loaded in ((False, False, False), (True, False, False),
                                             (True, True, False), (True, True, True)):
            with self.subTest(pending=pending, elastic=elastic, text_loaded=text_loaded):
                svc, v, proc = self.pending_service()
                v.cleanup_pending, v.stopped, v.elastic = pending, True, elastic
                if not text_loaded:
                    svc.engine.unload()
                with mock.patch.object(server, "popen") as spawn:
                    for load in (svc.load, svc.ensure_loaded):
                        with self.assertRaises(server.VisionCleanupPending):
                            load()
                        self.assertIs(v.proc, proc)
                        self.assertEqual(svc.engine.starts, 0)
                        self.assertEqual(svc.status["queued"], 0)
                    spawn.assert_not_called()

    def test_http_load_returns_pending_503_json_then_loads_after_exit(self):
        for path in ("/load", "/v1/load"):
            with self.subTest(path=path):
                svc, v, proc = self.pending_service()
                v.cleanup_pending, v.stopped = True, True
                svc.engine.unload()
                with mock.patch.object(server, "popen") as spawn:
                    for _ in range(2):
                        code, body = self.control_http(svc, path)
                        self.assertEqual(code, 503)
                        self.assertEqual(body["error"]["type"], "server_error")
                        self.assertIn("cleanup pending", body["error"]["message"])
                        self.assertIs(v.proc, proc)
                        self.assertTrue((v.dir / "owned.img").exists())
                        self.assertEqual(svc.engine.starts, 0)
                    spawn.assert_not_called()
                    proc.poll.return_value = 0
                    new_proc = mock.Mock(pid=23456)
                    new_proc.poll.return_value = None
                    new_proc.stdout = io.StringIO("READY 2\n")
                    spawn.return_value = new_proc
                    with mock.patch.object(server, "contain"):
                        code, body = self.control_http(svc, path)
                    self.assertEqual((code, body["status"]), (200, "loaded"))
                    self.assertIs(v.proc, new_proc)
                    spawn.assert_called_once()
                    self.assertEqual(svc.engine.starts, 1)

    def test_pending_timeout_retains_owner_and_refuses_respawn_or_successful_unload(self):
        for kill_fails in (False, True):
            with self.subTest(kill_fails=kill_fails):
                v = self.vision()
                proc, release = self.pending_proc(kill_fails)
                v.proc, v.stopped = proc, False
                try:
                    with self.assertRaises(RuntimeError) as caught:
                        v._readline(0.01, "encoding")
                    self.assertIsInstance(caught.exception, server.EngineStuck)
                    self.assertIs(v.proc, proc)
                    self.assertTrue(v.cleanup_pending)
                    self.assertFalse(v.capability()["available"])
                    self.assertIn("cleanup", v.capability()["error"])
                    with mock.patch.object(server, "popen") as spawn:
                        for action in (v.restart, v._start, v.unload, v.shutdown):
                            with self.assertRaises(RuntimeError):
                                action()
                        spawn.assert_not_called()
                    self.assertIs(v.proc, proc)
                    self.assertTrue(v.dir.exists())
                finally:
                    release.set()
                    v.proc = None
                    v.shutdown()

    def test_ready_timeout_retains_original_process(self):
        v = self.vision()
        proc, release = self.pending_proc()
        try:
            with mock.patch.object(server, "popen", return_value=proc), mock.patch.object(server, "contain"), \
                 mock.patch.object(server, "VISION_READY_S", 0.01), self.assertRaises(RuntimeError):
                v._start()
            self.assertIs(v.proc, proc)
            self.assertTrue(v.cleanup_pending)
        finally:
            release.set()
            v.proc = None
            v.shutdown()

    def test_cancel_keeps_owner_when_termination_cannot_be_proved(self):
        v = self.vision()
        proc, release = self.pending_proc(kill_fails=True)
        v.proc, v.stopped = proc, False
        cancel = threading.Event()
        cancel.set()
        try:
            with self.assertRaises(server.EngineStuck):
                v._readline(60, "encoding", cancel)
            self.assertIs(v.proc, proc)
            self.assertTrue(v.cleanup_pending)
            self.assertTrue(v.dir.exists())
        finally:
            release.set()
            v.proc = None
            v.shutdown()

    def test_pending_encode_keeps_files_until_the_owned_process_has_exited(self):
        v = self.vision()
        proc, release = self.pending_proc()
        proc.stdin.write.side_effect = lambda text: (v.dir / text.split()[2]).write_bytes(b"incomplete")
        v.proc, v.stopped, v.encode_timeout = proc, False, 0.01
        try:
            with self.assertRaises(server.EngineStuck):
                v.encode(self.png())
            self.assertEqual(len(list(v.dir.iterdir())), 2)
            self.assertIs(v.proc, proc)
            proc.poll.return_value = 0
            v.shutdown()
            self.assertFalse(v.dir.exists())
        finally:
            release.set()
            v.proc = None
            v.shutdown()

    def test_confirmed_exit_allows_exactly_one_new_process(self):
        v = self.vision()
        proc, release = self.pending_proc()
        v.proc, v.stopped = proc, False
        replacement = mock.Mock(pid=12346, stdout=io.StringIO("READY 2\n"))
        replacement.poll.return_value = None
        replacement.wait.return_value = 0
        try:
            with self.assertRaises(RuntimeError):
                v._readline(0.01, "encoding")
            release.set()
            proc.poll.return_value = 0
            with mock.patch.object(server, "popen", return_value=replacement) as spawn, \
                 mock.patch.object(server, "contain"):
                v.restart()
                spawn.assert_called_once()
            self.assertIs(v.proc, replacement)
            self.assertFalse(v.cleanup_pending)
        finally:
            release.set()
            v.shutdown()

    def test_constructor_error_exposes_retained_cleanup_owner(self):
        proc, release = self.pending_proc(kill_fails=True)
        proc.stdout.readline.side_effect = None
        proc.stdout.readline.return_value = "ERR warmup failed\n"
        try:
            with mock.patch.object(server, "popen", return_value=proc), mock.patch.object(server, "contain"), \
                 self.assertRaises(RuntimeError) as caught:
                server.Vision({"exe": "encoder", "model": "m", "mmproj": "p", "gpu": True, "backend": "hip"})
            owner = caught.exception.vision
            self.assertIs(owner.proc, proc)
            self.assertTrue(owner.dir.exists())
            owner.proc = None
            owner.shutdown()
        finally:
            release.set()

    def test_tool_image_cancel_after_encode_starts_reaps_child_and_releases_turn(self):
        v = self.vision()
        cancel = threading.Event()
        release = threading.Event()
        proc = mock.Mock(pid=12345)
        proc.poll.return_value = None
        proc.wait.return_value = 0
        proc.stdout.readline.side_effect = lambda: release.wait(1) and ""
        proc.stdin.write.side_effect = lambda text: cancel.set()
        proc.kill.side_effect = release.set
        v.proc, v.stopped, v.encode_timeout = proc, False, 0.01
        tok = server.ByteTokenizer()
        svc = server.Service(server.MockEngine(tok, "ok", max_context=4096), tok,
                             server.ChatTemplate(server.ROOT / "serve/chat_template.jinja"), vision=v)
        source = "data:image/png;base64," + base64.b64encode(self.png()).decode("ascii")
        messages = [{"role": "tool", "content": [{"type": "image", "source": source}]}]
        try:
            with self.assertRaises(server.ClientGone):
                svc._note_unreadable_tool_images(messages, cancel)
            proc.kill.assert_called_once()
            proc.wait.assert_called_once()
            self.assertIsNone(v.proc)
            self.assertTrue(svc.fifo.acquire(blocking=False))
            svc.fifo.release()
            self.assertEqual(list(v.dir.iterdir()), [])
        finally:
            release.set()
            v.proc = None
            v.shutdown()

    def test_legacy_unbounded_readline_still_accepts_no_deadline(self):
        v = self.vision()
        v.proc = SimpleNamespace(stdout=io.StringIO("READY 2\n"))
        try:
            self.assertEqual(v._readline(None, "ready"), "READY 2\n")
        finally:
            v.proc = None
            v.shutdown()

    def test_hip_uses_private_writable_temp_for_process_and_jit(self):
        with tempfile.TemporaryDirectory() as d:
            v = server.Vision({"exe": "encoder", "model": "m", "mmproj": "p", "gpu": True,
                               "backend": "hip", "temp_dir": d}, lazy=True)
            try:
                self.assertTrue(v.dir.is_relative_to(Path(d)))
                self.assertEqual(v.spawn[2]["TEMP"], d)
                self.assertEqual(v.spawn[2]["TMP"], d)
            finally:
                v.shutdown()

    def test_model_modalities_follow_actual_sidecar_health(self):
        v = self.vision()
        try:
            self.assertFalse(server.vision_capability(v)["available"])
            self.assertTrue(server.vision_capability(SimpleNamespace())["available"])
        finally:
            v.shutdown()

    def test_http_limit_rejects_before_reading_the_request(self):
        svc = SimpleNamespace(vision=SimpleNamespace(hip_required=True))
        handler = server.make_handler(svc).__new__(server.make_handler(svc))
        handler.headers = {"Content-Length": str((32 << 20) + 1)}
        handler.rfile = mock.Mock()
        with self.assertRaises(server.BadBody) as caught:
            handler._body()
        self.assertEqual(caught.exception.status, 413)
        handler.rfile.read.assert_not_called()

    def test_bad_embedding_output_is_removed_without_poisoning_cache(self):
        for header, values, reply in [((0x31455653, 1, 1, 1, 2), [float("nan"), 0.0], "OK 1 1 1 1"),
                                      ((0x31455653, 1, 1, 1, 3), [0.0, 0.0], "OK 1 1 1 1"),
                                      ((0x31455653, 301, 301, 1, 2), [0.0, 0.0], "OK 301 301 1 1")]:
            with self.subTest(header=header):
                v = self.vision()
                v.n_embd = 2
                v.proc = mock.Mock()
                def write_output(text):
                    out = v.dir / text.split()[2]
                    out.write_bytes(struct.pack("<5i", *header) + struct.pack("<2f", *values))
                v.proc.stdin.write.side_effect = write_output
                try:
                    with mock.patch.object(v, "_readline", return_value=reply), self.assertRaises(ValueError):
                        v.encode(self.png())
                    self.assertEqual(v.cache, {})
                    self.assertEqual(list(v.dir.iterdir()), [])
                finally:
                    v.proc = None
                    v.shutdown()


if __name__ == "__main__":
    unittest.main()
