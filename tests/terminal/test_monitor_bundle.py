"""Packaged client smoke test without site packages, engine files or model weights."""

import io
import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from strata_cli.cli import main as source_main


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "packaging/monitor_bundle.py"
SPEC = importlib.util.spec_from_file_location("strata_monitor_bundle_builder", BUILDER)
assert SPEC is not None and SPEC.loader is not None
BUILDER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER_MODULE)
SMOKE_SPEC = importlib.util.spec_from_file_location("portable_smoke_fixture", ROOT / "tools/portable_monitor_smoke.py")
SMOKE = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(SMOKE)
build = BUILDER_MODULE.build
install = BUILDER_MODULE.install
uninstall = BUILDER_MODULE.uninstall
update = BUILDER_MODULE.update
rollback = BUILDER_MODULE.rollback
commit = BUILDER_MODULE.commit
verify = BUILDER_MODULE.verify


class MonitorBundleTests(unittest.TestCase):
    def test_smoke_operations_distinguish_primary_and_interactive_metrics(self):
        primary = ["GET /v1/telemetry"] * 3
        self.assertEqual(SMOKE._operations(primary, interactive=False)["metrics_gets"], 0)
        result = SMOKE._operations(primary + ["GET /v1/telemetry", "GET /metrics"], interactive=True)
        self.assertEqual((result["telemetry_gets"], result["metrics_gets"]), (4, 1))
        self.assertEqual(result["operations"], primary + ["GET /v1/telemetry", "GET /metrics"])

    def test_smoke_operations_reject_missing_metrics_unknown_get_or_nonget(self):
        primary = ["GET /v1/telemetry"] * 3
        for paths, interactive in ((primary, True), (primary + ["GET /v1/telemetry"], True),
                                   (primary + ["GET /metrics"], True),
                                   (primary + ["GET /v1/telemetry", "GET /other"], True),
                                   (primary + ["GET /v1/telemetry", "POST /metrics"], True),
                                   (primary + ["GET /metrics"], False),
                                   (["GET /metrics"] + primary, True)):
            with self.subTest(paths=paths, interactive=interactive), self.assertRaises(RuntimeError):
                SMOKE._operations(paths, interactive=interactive)

    def test_smoke_fixture_metrics_malformed_and_rejected_operations_are_real(self):
        server, paths, malformed = SMOKE._server()
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            try:
                response = urllib.request.urlopen(url + "/metrics", timeout=2)
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 200, "metrics fixture is missing")
                raise
            with response: metrics = json.load(response)
            self.assertEqual(metrics["engine"]["model"], "portable-smoke-model")
            self.assertEqual(metrics["live"]["state"], "generating")
            self.assertEqual(metrics["hardware"]["gpu_util"], 37)
            for request, code in ((url + "/unknown", 404),
                                  (urllib.request.Request(url + "/v1/telemetry", data=b"{}"), 405)):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(caught.exception.code, code)
            malformed.set()
            with urllib.request.urlopen(url + "/v1/telemetry", timeout=2) as response:
                body = response.read()
            with self.assertRaises(json.JSONDecodeError): json.loads(body)
            self.assertEqual(paths, ["GET /metrics", "GET /unknown", "POST /v1/telemetry", "GET /v1/telemetry"])
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_smoke_error_record_is_strict(self):
        message = "server returned malformed JSON telemetry"
        record = json.dumps({"schema_version": 1, "ok": False, "error": {"code": 3, "message": message}})
        good = subprocess.CompletedProcess([], 3, record, "")
        self.assertEqual(SMOKE._error_response(good)["error"]["message"], message)
        for result in (subprocess.CompletedProcess([], 0, record, ""),
                       subprocess.CompletedProcess([], 3, record, "Traceback\n"),
                       subprocess.CompletedProcess([], 3, record + "{}", ""),
                       subprocess.CompletedProcess([], 3, record.replace('"schema_version": 1', '"schema_version": true'), ""),
                       subprocess.CompletedProcess([], 3, record.replace('"code": 3', '"code": 4'), ""),
                       subprocess.CompletedProcess([], 3, record.replace(message, "other failure"), ""),
                       subprocess.CompletedProcess([], 3, "[]", "")):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                SMOKE._error_response(result)

    def test_deep_valid_array_has_a_bounded_exact_client_error_separate_from_malformed(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "monitor.pyz"; build(bundle)
            server, _, bad = SMOKE._server(bad_body=b"[" * 1100 + b"0" + b"]" * 1100)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start(); bad.set()
            try:
                value = SMOKE._malformed_response(bundle, f"http://127.0.0.1:{server.server_port}",
                    messages=("server returned malformed JSON telemetry", "server returned a non-object telemetry response"))
                self.assertIn(value["error"]["message"],
                              ("server returned malformed JSON telemetry", "server returned a non-object telemetry response"))
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_schema6_readonly_closure_is_zip_local_and_compiles_without_site(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "monitor.pyz"
            report = build(bundle)
            self.assertEqual(report["schema_version"], 6)
            self.assertIn("strata_cli/consoleinfo.py", report["files"])
            self.assertIn("strata_cli/overview.py", report["files"])
            program = ("import sys,json,zipfile; sys.path.insert(0,sys.argv[1]); "
                       "from strata_cli import consoleinfo; "
                       "z=zipfile.ZipFile(sys.argv[1]); "
                       "[compile(z.read(n),n,'exec') for n in z.namelist() if n.endswith('.py')]; "
                       "print(json.dumps({'origin':consoleinfo.__file__,'compiled':True}))")
            result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-S", "-c", program, str(bundle)],
                                    cwd=directory, capture_output=True, text=True, check=True)
            value = json.loads(result.stdout)
            self.assertTrue(value["compiled"])
            self.assertTrue(value["origin"].replace("\\", "/").startswith(str(bundle).replace("\\", "/") + "/"))

    def test_thin_bootstrap_explicitly_selects_portable_route(self):
        selected = mock.Mock(return_value=0)
        module = mock.Mock(main=selected)
        with mock.patch.dict(sys.modules, {"strata_cli.monitor_commands": module}), self.assertRaises(SystemExit):
            exec(compile(BUILDER_MODULE.BOOTSTRAP, "__main__.py", "exec"), {})
        selected.assert_called_once_with(portable=True)

    def test_schema_four_and_five_exact_members_update_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); modern = root / "modern.pyz"; built = build(modern)
            for version, members in ((4, BUILDER_MODULE.MEMBERS_V4), (5, BUILDER_MODULE.MEMBERS_V5)):
                with self.subTest(version=version):
                    old = root / f"v{version}.pyz"
                    with zipfile.ZipFile(modern) as source, zipfile.ZipFile(old, "w") as archive:
                        archive.writestr("strata_cli/", b"")
                        for name in members:
                            content = (b"from strata_cli.monitor_commands import main\nraise SystemExit(main())\n"
                                       if name == "__main__.py" else source.read(name))
                            archive.writestr(name, content)
                    report = dict(built, schema_version=version, bundle=old.name,
                                  sha256=hashlib.sha256(old.read_bytes()).hexdigest())
                    with zipfile.ZipFile(old) as archive:
                        report["files"] = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in members}
                    old.with_name(old.name + ".manifest.json").write_text(json.dumps(report))
                    self.assertEqual(verify(old)["schema_version"], version)
                    self.assertNotIn("strata_cli/consoleinfo.py", report["files"])
                    self.assertNotIn("strata_cli/overview.py", report["files"])
                    target = root / f"installed-v{version}"
                    install(old, target, if_candidate_sha256=report["sha256"])
                    update(modern, target, if_current_sha256=report["sha256"], if_candidate_sha256=built["sha256"])
                    self.assertEqual(verify(target / modern.name)["schema_version"], 6)
                    rollback(target, if_active_sha256=built["sha256"], if_rollback_sha256=report["sha256"])
                    self.assertEqual(verify(target / old.name)["schema_version"], version)

    def test_schema6_member_missing_extra_duplicate_or_tampered_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original = root / "original.pyz"; built = build(original)
            with zipfile.ZipFile(original) as archive:
                contents = {name: archive.read(name) for name in archive.namelist()}
            for kind in ("missing", "extra", "duplicate", "tampered", "old-schema", "unknown-schema"):
                with self.subTest(kind=kind):
                    bundle = root / (kind + ".pyz"); entries = dict(contents)
                    if kind == "missing": del entries["strata_cli/consoleinfo.py"]
                    if kind == "extra": entries["strata_cli/unknown.py"] = b"pass\n"
                    if kind == "tampered": entries["strata_cli/overview.py"] += b"\n# changed\n"
                    with zipfile.ZipFile(bundle, "w") as archive:
                        for name, content in entries.items(): archive.writestr(name, content)
                        if kind == "duplicate":
                            with self.assertWarns(UserWarning):
                                archive.writestr("strata_cli/consoleinfo.py", entries["strata_cli/consoleinfo.py"])
                    report = dict(built, bundle=bundle.name, sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())
                    if kind == "old-schema": report["schema_version"] = 5
                    if kind == "unknown-schema": report["schema_version"] = 7
                    bundle.with_name(bundle.name + ".manifest.json").write_text(json.dumps(report))
                    with self.assertRaises(ValueError): verify(bundle)

    def test_portable_help_leaves_source_seven_views_unchanged(self):
        from strata_cli import monitor_commands as commands
        source_help = commands.parser().format_help()
        portable_help = commands.parser(portable=True).format_help()
        self.assertIn("seven views", source_help)
        self.assertIn("Connect", source_help)
        self.assertIn("six views", portable_help)
        self.assertNotIn("Connect", portable_help)

    def test_portable_and_source_interactive_routes_stay_separate(self):
        from strata_cli import monitor_commands as commands
        # Validate the real constructor signature without importing optional
        # Textual or running any console/font setup in this stdlib fixture.
        tree = ast.parse((ROOT / "strata_cli/monitor.py").read_text(encoding="utf-8"))
        app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MonitorApp")
        constructor = copy.deepcopy(next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"))
        constructor.name = "readonly_constructor"; constructor.args.args.pop(0)
        constructor.body = [ast.Pass()]; constructor.decorator_list = []; constructor.returns = None
        for node in ast.walk(constructor):
            if isinstance(node, ast.arg): node.annotation = None
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[constructor], type_ignores=[])), "constructor-signature", "exec"), namespace)
        endpoint = {"url": "http://127.0.0.1:1", "credential_env": "TEST_UNUSED_KEY",
                    "timeout_s": 3, "prefix": ""}
        for portable in (False, True):
            with self.subTest(portable=portable):
                readonly = mock.create_autospec(namespace["readonly_constructor"], return_value=mock.Mock())
                launch = mock.Mock()
                with mock.patch.dict(sys.modules, {"strata_cli.monitor": mock.Mock(MonitorApp=readonly),
                                                   "strata_cli.launch.monitor_ext": mock.Mock(LaunchMonitor=launch)}), \
                        mock.patch.object(commands.connections, "resolve", return_value=endpoint), \
                        mock.patch.object(sys.stdout, "isatty", return_value=True):
                    args = ["monitor", "--url", endpoint["url"]]
                    self.assertEqual(commands.main(args, portable=True) if portable else commands.main(args), 0)
                chosen, unused = (readonly, launch) if portable else (launch, readonly)
                chosen.return_value.run.assert_called_once_with()
                unused.assert_not_called()
                if portable: self.assertIsNone(chosen.call_args.args[1])

    @staticmethod
    def _candidate(source: Path, destination: Path) -> Path:
        destination.parent.mkdir()
        destination.write_bytes(source.read_bytes())
        with zipfile.ZipFile(destination, "a") as archive:
            archive.comment = b"candidate client revision"
        report = json.loads(source.with_name(source.name + ".manifest.json").read_text())
        report["bundle"] = destination.name
        report["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_name(destination.name + ".manifest.json").write_text(json.dumps(report))
        verify(destination)
        return destination

    def test_crlf_license_checkout_still_verifies(self):
        """A Windows checkout (autocrlf) ships LICENSE with CRLF; the bundle must still verify."""
        real_copy = BUILDER_MODULE.shutil.copyfile

        def crlf_license(src, dst, *args, **kwargs):
            if Path(src).name != "LICENSE":
                return real_copy(src, dst, *args, **kwargs)
            text = Path(src).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            Path(dst).write_bytes(text)
            return dst

        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "monitor.pyz"
            with mock.patch.object(BUILDER_MODULE.shutil, "copyfile", crlf_license):
                build(bundle)
            with zipfile.ZipFile(bundle) as archive:
                self.assertIn(b"MIT License\r\n", archive.read("LICENSE"))
            self.assertEqual(verify(bundle)["schema_version"], 6)

    def test_update_rollback_and_commit_keep_one_verified_previous_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first" / "monitor.pyz"
            first.parent.mkdir()
            old = build(first)
            candidate = self._candidate(first, root / "second" / "next-monitor.pyz")
            next_sha = verify(candidate)["sha256"]
            target = root / "optional-monitor"
            install(first, target, if_candidate_sha256=old["sha256"])
            preview_run = subprocess.run([sys.executable, str(BUILDER), "update", str(candidate),
                                          "--target", str(target), "--plan"],
                                         capture_output=True, text=True, check=True)
            preview = json.loads(preview_run.stdout)
            self.assertEqual((preview["current_sha256"], preview["candidate_sha256"]),
                             (old["sha256"], next_sha))
            self.assertTrue(preview["would_update"])
            with self.assertRaisesRegex(ValueError, "preview again"):
                update(candidate, target, if_current_sha256=old["sha256"],
                       if_candidate_sha256="0" * 64)
            self.assertFalse((root / "optional-monitor.previous").exists())
            changed = subprocess.run([sys.executable, str(BUILDER), "update", str(candidate),
                                      "--target", str(target), "--if-current-sha256", old["sha256"],
                                      "--if-candidate-sha256", next_sha],
                                     capture_output=True, text=True, check=True)
            result = json.loads(changed.stdout)
            self.assertTrue(result["updated"])
            previous = root / "optional-monitor.previous"
            self.assertEqual(verify(target / "next-monitor.pyz")["sha256"], next_sha)
            self.assertEqual(verify(previous / "monitor.pyz")["sha256"], old["sha256"])
            with self.assertRaisesRegex(FileExistsError, "previous"):
                update(candidate, target, plan=True)
            preview_run = subprocess.run([sys.executable, str(BUILDER), "rollback", "--target",
                                          str(target), "--plan"], capture_output=True, text=True, check=True)
            preview = json.loads(preview_run.stdout)
            self.assertTrue(preview["would_rollback"])
            with self.assertRaisesRegex(ValueError, "preview again"):
                rollback(target, if_active_sha256=old["sha256"], if_rollback_sha256=old["sha256"])
            original = os.rename
            calls = 0

            def fail_last_exchange(source, destination):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("final exchange failed")
                return original(source, destination)

            with mock.patch.object(BUILDER_MODULE.os, "rename", side_effect=fail_last_exchange):
                with self.assertRaisesRegex(OSError, "final exchange failed"):
                    rollback(target, if_active_sha256=next_sha, if_rollback_sha256=old["sha256"])
            self.assertEqual(verify(target / "next-monitor.pyz")["sha256"], next_sha)
            self.assertEqual(verify(previous / "monitor.pyz")["sha256"], old["sha256"])
            self.assertFalse(list(root.glob(".strata-monitor-swap-*")))
            restored = subprocess.run([sys.executable, str(BUILDER), "rollback", "--target", str(target),
                                       "--if-active-sha256", next_sha,
                                       "--if-rollback-sha256", old["sha256"]],
                                      capture_output=True, text=True, check=True)
            result = json.loads(restored.stdout)
            self.assertTrue(result["rolled_back"])
            self.assertEqual(verify(target / "monitor.pyz")["sha256"], old["sha256"])
            self.assertEqual(verify(previous / "next-monitor.pyz")["sha256"], next_sha)
            with self.assertRaisesRegex(ValueError, "commit or rollback"):
                uninstall(target)
            planned = commit(target, plan=True)
            self.assertTrue(planned["would_commit"])
            accepted = subprocess.run([sys.executable, str(BUILDER), "commit", "--target", str(target),
                                       "--if-active-sha256", old["sha256"],
                                       "--if-previous-sha256", next_sha],
                                      capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(accepted.stdout)["committed"])
            self.assertFalse(previous.exists())
            self.assertTrue(uninstall(target, if_active_sha256=old["sha256"])["removed"])

    def test_update_activation_failure_restores_installed_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first" / "monitor.pyz"
            first.parent.mkdir()
            old = build(first)
            candidate = self._candidate(first, root / "second" / "monitor.pyz")
            next_sha = verify(candidate)["sha256"]
            target = root / "optional-monitor"
            install(first, target, if_candidate_sha256=old["sha256"])
            original = os.rename
            calls = 0

            def fail_activation(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("activation failed")
                return original(source, destination)

            with mock.patch.object(BUILDER_MODULE.os, "rename", side_effect=fail_activation):
                with self.assertRaisesRegex(OSError, "activation failed"):
                    update(candidate, target, if_current_sha256=old["sha256"],
                           if_candidate_sha256=next_sha)
            self.assertEqual(verify(target / "monitor.pyz")["sha256"], old["sha256"])
            self.assertFalse((root / "optional-monitor.previous").exists())
            self.assertFalse(list(root.glob(".strata-monitor-install-*")))

            original_stage = BUILDER_MODULE._stage_copy

            def change_active_during_copy(bundle, report, destination):
                stage = original_stage(bundle, report, destination)
                active_bundle = destination / "monitor.pyz"
                with zipfile.ZipFile(active_bundle, "a") as archive:
                    archive.comment = b"external owner edit"
                manifest = active_bundle.with_name(active_bundle.name + ".manifest.json")
                current = json.loads(manifest.read_text())
                current["sha256"] = hashlib.sha256(active_bundle.read_bytes()).hexdigest()
                manifest.write_text(json.dumps(current))
                return stage

            with mock.patch.object(BUILDER_MODULE, "_stage_copy", side_effect=change_active_during_copy):
                with self.assertRaisesRegex(ValueError, "changed during copy"):
                    update(candidate, target, if_current_sha256=old["sha256"],
                           if_candidate_sha256=next_sha)
            self.assertNotEqual(verify(target / "monitor.pyz")["sha256"], old["sha256"])
            self.assertFalse((root / "optional-monitor.previous").exists())
            self.assertFalse(list(root.glob(".strata-monitor-install-*")))

    def test_offline_install_plan_and_remove_touch_only_monitor_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "portable-client.pyz"
            built = build(bundle)
            target = root / "optional-monitor"
            preview = subprocess.run([sys.executable, str(BUILDER), "install", str(bundle),
                                      "--target", str(target), "--plan"],
                                     capture_output=True, text=True, check=True)
            planned = json.loads(preview.stdout)
            self.assertTrue(planned["would_install"])
            self.assertFalse(target.exists())
            with self.assertRaisesRegex(ValueError, "preview again"):
                install(bundle, target)
            with self.assertRaisesRegex(ValueError, "preview again"):
                install(bundle, target, if_candidate_sha256="0" * 64)
            self.assertFalse(target.exists())
            installed_run = subprocess.run([sys.executable, str(BUILDER), "install", str(bundle),
                                            "--target", str(target),
                                            "--if-candidate-sha256", planned["sha256"]],
                                           capture_output=True, text=True, check=True)
            installed = json.loads(installed_run.stdout)
            self.assertTrue(installed["installed"])
            self.assertEqual(verify(target / bundle.name)["sha256"], built["sha256"])
            self.assertEqual({p.name for p in target.iterdir()},
                             {bundle.name, bundle.name + ".manifest.json"})
            if os.name == "posix":
                self.assertEqual(target.stat().st_mode & 0o077, 0)
                self.assertEqual((target / bundle.name).stat().st_mode & 0o077, 0)
            portable = subprocess.run([sys.executable, "-I", "-X", "utf8", str(target / bundle.name), "logs", "--help"],
                                      cwd=directory, capture_output=True, text=True, check=True)
            self.assertIn("--follow", portable.stdout)
            extra = target / "user-notes.txt"
            extra.write_text("keep me")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                uninstall(target)
            self.assertTrue(extra.exists())
            extra.unlink()
            preview_remove = subprocess.run([sys.executable, str(BUILDER), "uninstall",
                                             "--target", str(target), "--plan"],
                                            capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(preview_remove.stdout)["would_remove"])
            self.assertTrue(target.exists())
            with self.assertRaisesRegex(ValueError, "preview again"):
                uninstall(target)
            with self.assertRaisesRegex(ValueError, "preview again"):
                uninstall(target, if_active_sha256="0" * 64)
            self.assertTrue(target.exists())
            removal = subprocess.run([sys.executable, str(BUILDER), "uninstall", "--target",
                                      str(target), "--if-active-sha256",
                                      json.loads(preview_remove.stdout)["sha256"]],
                                     capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(removal.stdout)["removed"])
            self.assertFalse(target.exists())

    def test_failed_copy_leaves_no_partial_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "monitor.pyz"
            built = build(bundle)
            target = root / "optional-monitor"
            with mock.patch.object(BUILDER_MODULE.shutil, "copyfile", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    install(bundle, target, if_candidate_sha256=built["sha256"])
            self.assertFalse(target.exists())
            self.assertFalse(list(root.glob(".strata-monitor-install-*")))

    def test_bundle_verification_rejects_large_or_linked_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "monitor.pyz"
            build(bundle)
            with bundle.open("ab") as stream:
                stream.write(b"x" * (1024 * 1024))
            with self.assertRaisesRegex(ValueError, "bounded regular"):
                verify(bundle)
            bundle = root / "unsigned.pyz"
            build(bundle)
            manifest = bundle.with_name(bundle.name + ".manifest.json")
            forged = json.loads(manifest.read_text())
            forged["publisher_signature"] = "pretend-signed"
            manifest.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "manifest or SHA-256"):
                verify(bundle)
            manifest.write_text("[]")
            with self.assertRaisesRegex(ValueError, "manifest or SHA-256"):
                verify(bundle)

    def test_actual_symlink_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = root / "monitor.pyz"; build(bundle)
            linked = root / "linked.pyz"
            try:
                linked.symlink_to(bundle)
            except OSError as error:
                if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows symlink creation privilege is unavailable; actual link not tested")
                raise
            with self.assertRaisesRegex(ValueError, "bounded regular"):
                verify(linked)

    def test_nonregular_input_is_rejected_without_symlink_privilege(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "monitor.pyz"; build(bundle)
            with mock.patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=0o120777)):
                with self.assertRaisesRegex(ValueError, "bounded regular"):
                    verify(bundle)

    def test_versioned_manifest_keeps_legacy_update_and_rollback_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "monitor.pyz"
            modern = root / "next-monitor.pyz"
            previous = root / "previous-monitor.pyz"
            build(modern)
            old_visual = root / "visual-monitor.pyz"
            for old_bundle, version in ((current, 1), (previous, 2), (old_visual, 3)):
                with zipfile.ZipFile(modern) as source, zipfile.ZipFile(old_bundle, "w", zipfile.ZIP_DEFLATED) as legacy:
                    for item in source.infolist():
                        if item.filename not in ("strata_cli/detail_dashboard.py", "strata_cli/nav.py", "strata_cli/consoleinfo.py", "strata_cli/overview.py") and \
                                (version >= 3 or item.filename != "strata_cli/dashboard.py") and \
                                (version != 1 or item.filename != "LICENSE"):
                            legacy.writestr(item, source.read(item.filename))
                report = json.loads((root / "next-monitor.pyz.manifest.json").read_text())
                report["schema_version"] = version
                report["bundle"] = old_bundle.name
                report["sha256"] = hashlib.sha256(old_bundle.read_bytes()).hexdigest()
                del report["files"]["strata_cli/detail_dashboard.py"]
                del report["files"]["strata_cli/nav.py"]
                del report["files"]["strata_cli/consoleinfo.py"]
                del report["files"]["strata_cli/overview.py"]
                if version < 3:
                    del report["files"]["strata_cli/dashboard.py"]
                if version == 1:
                    del report["files"]["LICENSE"]
                    for field in ("compatibility", "license", "license_file"):
                        del report[field]
                old_bundle.with_name(old_bundle.name + ".manifest.json").write_text(json.dumps(report))
            self.assertEqual(verify(current)["schema_version"], 1)
            self.assertEqual(verify(previous)["schema_version"], 2)
            self.assertEqual(verify(old_visual)["schema_version"], 3)
            self.assertEqual(verify(modern)["schema_version"], 6)
            with zipfile.ZipFile(modern) as archive:
                self.assertIn(b"MIT License", archive.read("LICENSE"))
                self.assertIn(b"render_dashboard", archive.read("strata_cli/dashboard.py"))
                self.assertIn(b"render_detail_dashboard", archive.read("strata_cli/detail_dashboard.py"))
            target = root / "optional-monitor"
            install(current, target, if_candidate_sha256=verify(current)["sha256"])
            preview = update(modern, target, plan=True)
            self.assertTrue(preview["would_update"])
            self.assertTrue(update(modern, target, if_current_sha256=preview["current_sha256"],
                                   if_candidate_sha256=preview["candidate_sha256"])["updated"])
            self.assertEqual(verify(target / modern.name)["schema_version"], 6)
            self.assertEqual(verify(root / "optional-monitor.previous" / current.name)["schema_version"], 1)
            planned = rollback(target, plan=True)
            self.assertTrue(rollback(target, if_active_sha256=planned["active_sha256"],
                                     if_rollback_sha256=planned["rollback_sha256"])["rolled_back"])
            self.assertEqual(verify(target / current.name)["schema_version"], 1)
            second_target = root / "optional-monitor-from-v2"
            install(previous, second_target, if_candidate_sha256=verify(previous)["sha256"])
            preview = update(modern, second_target, plan=True)
            self.assertTrue(update(modern, second_target,
                                   if_current_sha256=preview["current_sha256"],
                                   if_candidate_sha256=preview["candidate_sha256"])["updated"])
            self.assertEqual(verify(second_target / modern.name)["schema_version"], 6)
            planned = rollback(second_target, plan=True)
            self.assertTrue(rollback(second_target, if_active_sha256=planned["active_sha256"],
                                     if_rollback_sha256=planned["rollback_sha256"])["rolled_back"])
            self.assertEqual(verify(second_target / previous.name)["schema_version"], 2)
            third_target = root / "optional-monitor-from-v3"
            install(old_visual, third_target, if_candidate_sha256=verify(old_visual)["sha256"])
            preview = update(modern, third_target, plan=True)
            self.assertTrue(update(modern, third_target,
                                   if_current_sha256=preview["current_sha256"],
                                   if_candidate_sha256=preview["candidate_sha256"])["updated"])
            planned = rollback(third_target, plan=True)
            self.assertTrue(rollback(third_target, if_active_sha256=planned["active_sha256"],
                                     if_rollback_sha256=planned["rollback_sha256"])["rolled_back"])
            self.assertEqual(verify(third_target / old_visual.name)["schema_version"], 3)

    def test_manifest_compatibility_and_license_notice_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "monitor.pyz"
            built = build(bundle)
            self.assertEqual(built["compatibility"], {"python_min": "3.10", "telemetry_schema": [1]})
            self.assertEqual(built["license_file"], "LICENSE")
            manifest = bundle.with_name(bundle.name + ".manifest.json")
            edited = json.loads(manifest.read_text())
            edited["compatibility"]["telemetry_schema"] = [2]
            manifest.write_text(json.dumps(edited))
            with self.assertRaisesRegex(ValueError, "compatibility or license"):
                verify(bundle)
            edited["schema_version"] = True
            manifest.write_text(json.dumps(edited))
            with self.assertRaisesRegex(ValueError, "manifest or SHA-256"):
                verify(bundle)

    def test_thin_bundle_and_source_share_one_shot_contract(self):
        snapshot = {"schema_version": 1, "source": "test-server", "sampled_at": 1_790_000_000,
                    "instance": {"id": "test-instance", "state": "ready"},
                    "model": {"id": "fixture-model", "loaded": True},
                    "work": {"active": 2, "queued": 1, "slots_effective": 4,
                             "requests": [{"id": "r1", "state": "reading", "slot": 0,
                                           "prompt_tokens": 200, "prompt_read": 50}]}}
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                body = json.dumps(snapshot).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory) / "strata-monitor.pyz"
                subprocess.run([sys.executable, str(BUILDER), "build", str(bundle)], check=True,
                               capture_output=True, text=True)
                subprocess.run([sys.executable, str(BUILDER), "verify", str(bundle)], check=True,
                               capture_output=True, text=True)
                self.assertLessEqual(bundle.stat().st_size, BUILDER_MODULE.MAX_BUNDLE_BYTES)
                with zipfile.ZipFile(bundle) as archive:
                    self.assertIn(b"MIT License", archive.read("LICENSE"))
                    self.assertIn("strata_cli/dashboard.py", archive.namelist())
                if importlib.util.find_spec("textual") is not None:
                    import_check = subprocess.run(
                        [sys.executable, "-I", "-X", "utf8", "-c",
                         "import sys; sys.path.insert(0, " + repr(str(bundle)) + "); "
                         "from strata_cli.monitor import MonitorApp; print(MonitorApp.__name__)"],
                        cwd=directory, capture_output=True, text=True, check=True)
                    self.assertEqual(import_check.stdout.strip(), "MonitorApp")
                url = f"http://127.0.0.1:{server.server_port}"
                source_output = io.StringIO()
                with redirect_stdout(source_output):
                    self.assertEqual(source_main(["monitor", "--once", "--json", "--url", url]), 0)
                clean_env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
                clean_env["STRATA_CONNECTION_DIR"] = str(Path(directory) / "connections")
                portable = subprocess.run([sys.executable, "-S", str(bundle), "monitor", "--once", "--json",
                                           "--url", url], cwd=directory, env=clean_env, check=True,
                                          capture_output=True, text=True)
                self.assertEqual(json.loads(portable.stdout), json.loads(source_output.getvalue()))
                bare_source = subprocess.run([sys.executable, "-S", str(ROOT / "strata.py"), "monitor",
                                              "--once", "--json", "--url", url], cwd=directory, env=clean_env,
                                             check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(bare_source.stdout), json.loads(portable.stdout))
                status = subprocess.run([sys.executable, "-S", str(bundle), "status", "--json", "--url", url],
                                        cwd=directory, env=clean_env, check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(status.stdout)["snapshot"]["work"]["active"], 2)
                saved = subprocess.run([sys.executable, "-S", str(bundle), "connection", "list", "--json"],
                                       cwd=directory, env=clean_env, check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(saved.stdout)["connections"], [])
                quiet_saved = subprocess.run([sys.executable, "-S", str(bundle), "connection", "list", "--quiet"],
                                             cwd=directory, env=clean_env, check=True,
                                             capture_output=True, text=True)
                self.assertEqual((quiet_saved.stdout, quiet_saved.stderr), ("", ""))
                quiet_json = subprocess.run([sys.executable, "-S", str(bundle), "connection", "list",
                                             "--quiet", "--json"], cwd=directory, env=clean_env,
                                            check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(quiet_json.stdout)["connections"], [])
                self.assertEqual(paths, ["/v1/telemetry"] * 4)
                data = bytearray(bundle.read_bytes())
                data[-1] ^= 1
                bundle.write_bytes(data)
                broken = subprocess.run([sys.executable, str(BUILDER), "verify", str(bundle)],
                                        capture_output=True, text=True)
                self.assertEqual(broken.returncode, 1)
                self.assertIn("SHA-256 mismatch", broken.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
