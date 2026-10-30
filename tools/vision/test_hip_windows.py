"""Regression checks for the experimental HIP image path; no GPU, SDK or model downloads.

    python -m unittest tools.vision.test_hip_windows -v
"""
import io
import json
import tempfile
import unittest
from contextlib import chdir, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from serve import server
from serve.vision_hip import windows_hip_env
from tools.gguf_writer import GGUFWriter
from tools.vision import hip_windows as hip


class RuntimeEnvironment(unittest.TestCase):
    def setUp(self):
        self.vision = {"backend": "hip", "gpu": True, "rocm_root": r"C:\vision-sdk",
                       "exe": r"C:\vision-sdk\bin\strata-vision-hip.exe", "hip_device": 1}

    def test_old_sdk_and_gpu_filters_do_not_enter_encoder(self):
        old = {"Path": r"C:\Strata\engine\rocm\bin;C:\old-sdk\bin", "Hip_Path": r"C:\old-sdk",
               "ROCM_PATH": r"C:\old-sdk", "ROCBLAS_TENSILE_LIBPATH": r"C:\old-kernels",
               "HIPBLASLT_TENSILE_LIBPATH": r"C:\old-kernels", "CUDA_VISIBLE_DEVICES": "0",
               "ROCR_VISIBLE_DEVICES": "0", "HIP_VISIBLE_DEVICES": "0", "STRATA_ROCBLAS_TUNING": "old",
               "SYSTEMROOT": r"C:\Windows", "TEMP": r"C:\Temp", "AMD_COMGR_CACHE_DIR": r"C:\old-cache"}
        saved = dict(old)
        env = server.vision_env({"vision": self.vision}, old)
        self.assertEqual(old, saved)
        self.assertEqual(env["HIP_VISIBLE_DEVICES"], "1")
        self.assertEqual(env["HIP_PATH"], r"C:\vision-sdk")
        self.assertEqual(env["TEMP"], r"C:\vision-sdk\tmp")
        self.assertEqual(env["AMD_COMGR_CACHE_DIR"], r"C:\vision-sdk\tmp\comgr")
        for key in ("CUDA_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES", "ROCBLAS_TENSILE_LIBPATH",
                    "HIPBLASLT_TENSILE_LIBPATH", "STRATA_ROCBLAS_TUNING", "Hip_Path", "Path"):
            self.assertNotIn(key, env)
        self.assertNotIn("old", env["PATH"])
        self.assertNotIn("engine", env["PATH"])

    def test_legacy_configuration_is_the_same_object(self):
        old = {"PATH": "old", "HIP_VISIBLE_DEVICES": "1"}
        self.assertIs(server.vision_env({"vision": {"gpu": True}}, old), old)
        cuda = server.vision_env({"vision": {"cuda_device": 2}}, old)
        self.assertEqual(cuda["CUDA_VISIBLE_DEVICES"], "2")
        self.assertEqual(old, {"PATH": "old", "HIP_VISIBLE_DEVICES": "1"})

    def test_old_gpu_device_ordinal_is_removed_case_insensitively_without_mutating_parent(self):
        for key in ("GPU_DEVICE_ORDINAL", "Gpu_Device_Ordinal"):
            with self.subTest(key=key):
                parent = {key: "9", "HIP_VISIBLE_DEVICES": "0"}
                saved = dict(parent)
                env = windows_hip_env(self.vision, parent)
                self.assertNotIn("GPU_DEVICE_ORDINAL", {k.upper() for k in env})
                self.assertEqual(env["HIP_VISIBLE_DEVICES"], "1")
                self.assertEqual(parent, saved)

    def test_invalid_or_ambiguous_hip_configuration_is_rejected(self):
        for patch in ({"hip_device": True}, {"hip_device": -1}, {"hip_device": "0"},
                      {"exe": r"C:\Strata\engine\strata-vision.exe"}, {"rocm_root": "relative"}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                windows_hip_env({**self.vision, **patch}, {})

    def test_new_backend_passes_strict_flag_only_when_requested(self):
        base = {"exe": "image.exe", "model": "text.gguf", "mmproj": "image.gguf", "gpu": True}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(server.Vision, "work_dir", return_value=Path(d)):
            base['temp_dir'] = d  # The fake work_dir does not create its normal parent.
            old = server.Vision(base, lazy=True)
            new = server.Vision({**base, "backend": "hip"}, lazy=True)
            self.assertNotIn("--require-hip", old.spawn[0])
            self.assertIn("--require-hip", new.spawn[0])
            with self.assertRaises(ValueError):
                server.Vision({**base, "backend": "hip", "gpu": False}, lazy=True)


class ConfigCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.source, self.output = self.d / "source.json", self.d / "hip-test.json"
        self.cfg = {"backend": "hip", "exe": str(self.d / "engine/strata.exe"),
                    "args": ["--native", str(self.d / "model.gguf")],
                    "lib_dirs": [str(self.d / "engine/rocm/bin")], "env": {"SOME_TEXT_SETTING": "1"},
                    "vision": {"gpu": False, "cuda_device": 8, "elastic": True}, "lazy_load": True}
        self.source.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.image, self.model = self.d / "mmproj.gguf", self.d / "model.gguf"
        self.write_models()
        self.args = SimpleNamespace(config=self.source, out=self.output, rocm_root=self.d / "sdk", mmproj=self.image,
                                    model=self.model, hip_device=1, max_tokens=1024, dry_run=False)

    def write_models(self, width=2048, projection=2048, split=0, arch="qwen4exp",
                     projector="qwen3vl_merger", markers=True):
        w = GGUFWriter()
        w.add("general.architecture", arch)
        w.add(arch + ".embedding_length", width)
        w.add("tokenizer.ggml.tokens", ["<|vision_start|>", "<|vision_end|>", "<|image_pad|>"] if markers else ["token"])
        w.add("split.no", split)
        w.write(self.model)
        w = GGUFWriter()
        w.add("clip.vision.projection_dim", projection)
        w.add("clip.projector_type", projector)
        w.write(self.image)

    def copy(self):
        rocm = self.d / "sdk"
        # These checks target config transaction rules. Windows/SDK execution is a separate hardware gate.
        with mock.patch.object(hip, "encoder_files", return_value=(rocm, rocm / "bin" / hip.EXE)), \
             mock.patch.object(hip, "IS_WINDOWS", True), redirect_stdout(io.StringIO()):
            hip.config_copy(self.args)

    def test_copy_keeps_source_and_text_settings_but_not_old_vision_state(self):
        before = self.source.read_bytes()
        self.copy()
        self.assertEqual(self.source.read_bytes(), before)
        cfg = json.loads(self.output.read_text())
        for key in ("exe", "args", "backend", "lib_dirs", "env"):
            self.assertEqual(cfg[key], self.cfg[key])
        self.assertEqual(cfg["vision"]["hip_device"], 1)
        self.assertNotIn("cuda_device", cfg["vision"])
        self.assertNotIn("elastic", cfg["vision"])
        self.assertFalse(cfg["lazy_load"])

    def test_mismatched_projector_and_nonfirst_shard_never_write_config(self):
        for values in ({"projection": 4096}, {"split": 1}):
            with self.subTest(values=values):
                self.write_models(**values)
                with self.assertRaises(ValueError):
                    self.copy()
                self.assertFalse(self.output.exists())
                self.assertEqual(json.loads(self.source.read_text()), self.cfg)

    def test_same_width_wrong_family_or_missing_image_markers_is_rejected(self):
        for values in ({"arch": "llama"}, {"projector": "siglip"}, {"markers": False}):
            with self.subTest(values=values):
                self.write_models(**values)
                with self.assertRaises(ValueError):
                    self.copy()
                self.assertFalse(self.output.exists())

    def test_model_argument_must_be_the_text_engines_native_file(self):
        self.cfg["args"] = ["--native", str(self.d / "other-model.gguf")]
        self.source.write_text(json.dumps(self.cfg))
        with self.assertRaisesRegex(ValueError, "native"):
            self.copy()
        self.assertFalse(self.output.exists())

    def test_existing_destination_and_source_overwrite_are_rejected(self):
        self.output.write_text("existing")
        with self.assertRaises(ValueError):
            self.copy()
        self.assertEqual(self.output.read_text(), "existing")
        self.args.out = self.source
        with self.assertRaises(ValueError):
            self.copy()
        self.assertEqual(json.loads(self.source.read_text()), self.cfg)

    def test_relative_engine_is_resolved_from_its_cwd_before_sdk_isolation_check(self):
        self.cfg.update(exe="strata.exe", cwd=str(self.d))
        self.source.write_text(json.dumps(self.cfg))
        with self.assertRaisesRegex(ValueError, "separate"):
            self.copy()
        self.assertFalse(self.output.exists())

    def test_relative_engine_and_working_directory_are_made_absolute_in_copy(self):
        self.cfg.update(exe="strata.exe", cwd=str(self.d / "engine"))
        self.source.write_text(json.dumps(self.cfg))
        self.copy()
        cfg = json.loads(self.output.read_text())
        self.assertEqual(cfg["exe"], str(self.d / "engine/strata.exe"))
        self.assertEqual(cfg["cwd"], str(self.d / "engine"))

    def test_relative_libraries_and_tokenizer_keep_config_cwd_meaning(self):
        here, caller = self.d / "text-root", self.d / "caller" / "nested"
        here.mkdir()
        caller.mkdir(parents=True)
        self.cfg.update(cwd=str(here), exe="engine/strata.exe", lib_dirs=["engine/rocm/bin"],
                        tokenizer="packs/tokenizer")
        self.source.write_text(json.dumps(self.cfg))
        with chdir(caller):
            self.copy()
        cfg = json.loads(self.output.read_text())
        self.assertEqual(cfg["lib_dirs"], [str(here / "engine/rocm/bin")])
        self.assertEqual(cfg["tokenizer"], str(here / "packs/tokenizer"))

    def test_relative_library_is_normalized_before_sdk_isolation_check(self):
        here, caller = self.d / "text-root", self.d / "caller" / "nested"
        here.mkdir()
        caller.mkdir(parents=True)
        self.cfg.update(cwd=str(here), lib_dirs=["../sdk/bin"])
        self.source.write_text(json.dumps(self.cfg))
        with chdir(caller), self.assertRaisesRegex(ValueError, "already uses"):
            self.copy()
        self.assertFalse(self.output.exists())

    def test_dry_run_writes_nothing(self):
        self.args.dry_run = True
        self.copy()
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads(self.source.read_text()), self.cfg)


class BuildPlan(unittest.TestCase):
    def test_compiler_keeps_vs_environment_but_clears_package_overrides(self):
        values = {"INCLUDE": "msvc-include", "LIB": "msvc-lib", "PATH": "msvc-bin",
                  "hip_ROOT": "old-sdk", "HIPBLAS_DIR": "old-sdk", "CMAKE_PREFIX_PATH": "old-sdk"}
        with mock.patch.dict(hip.os.environ, values, clear=True):
            env = hip.compiler_env(Path("sdk"))
        self.assertEqual(env["INCLUDE"], values["INCLUDE"])
        self.assertEqual(env["LIB"], values["LIB"])
        self.assertNotIn("hip_ROOT", env)
        self.assertNotIn("HIPBLAS_DIR", env)
        self.assertNotIn("CMAKE_PREFIX_PATH", env)

    def test_windows_ggml_hip_receives_legacy_gpu_targets_and_one_sdk_compiler(self):
        cmd = hip.configure_command(Path("sdk"), Path("llama"), Path("build"), "gfx1201")
        self.assertIn("-DGPU_TARGETS=gfx1201", cmd)
        self.assertIn("-DSTRATA_VISION_HIP=ON", cmd)
        self.assertIn("-DSTRATA_VISION_CUDA=OFF", cmd)
        self.assertIn("-DGGML_STATIC=OFF", cmd)
        self.assertIn("-DCMAKE_CXX_COMPILER=sdk/lib/llvm/bin/clang++.exe", cmd)
        self.assertNotIn("-DCMAKE_HIP_ARCHITECTURES=gfx1201", cmd)


class ProbeTemp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)
        self.sdk = self.d / "sdk"
        self.sdk.mkdir()
        self.exe = self.sdk / "bin" / hip.EXE
        patcher = mock.patch.object(hip.subprocess, "run")
        self.launch = patcher.start()
        self.addCleanup(patcher.stop)

    def run_probe(self, env=None):
        with mock.patch.object(hip, "ROOT", self.d), mock.patch.object(hip, "IS_WINDOWS", True), \
             mock.patch.object(hip, "encoder_files", return_value=(self.sdk, self.exe)):
            if env is None:
                hip.probe(SimpleNamespace(rocm_root=self.sdk))
            else:
                with mock.patch.object(hip, "windows_hip_env", return_value=dict(env)):
                    hip.probe(SimpleNamespace(rocm_root=self.sdk))
            return self.launch

    def test_probe_creates_and_checks_private_temp_before_launch(self):
        launch = self.run_probe()
        self.assertTrue((self.sdk / "tmp" / "comgr").is_dir())
        self.assertEqual(list((self.sdk / "tmp" / "comgr").iterdir()), [])
        self.assertEqual([p.name for p in (self.sdk / "tmp").iterdir()], ["comgr"])
        launch.assert_called_once()
        env = launch.call_args.kwargs["env"]
        self.assertEqual(Path(env["TEMP"]), self.sdk / "tmp")
        self.assertNotIn("HIP_VISIBLE_DEVICES", env)

    def test_probe_removes_parent_ordinal_and_all_visibility_masks_before_mock_launch(self):
        for key in ("GPU_DEVICE_ORDINAL", "Gpu_Device_Ordinal"):
            with self.subTest(key=key):
                parent = {key: "9", "HIP_VISIBLE_DEVICES": "8", "ROCR_VISIBLE_DEVICES": "7",
                          "CUDA_VISIBLE_DEVICES": "6"}
                saved = dict(parent)
                self.launch.reset_mock()
                with mock.patch.object(hip.os, "environ", parent):
                    launch = self.run_probe()
                launch.assert_called_once()
                names = {k.upper() for k in launch.call_args.kwargs["env"]}
                for variable in ("GPU_DEVICE_ORDINAL", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES",
                                 "CUDA_VISIBLE_DEVICES"):
                    self.assertNotIn(variable, names)
                self.assertEqual(parent, saved)

    def assert_rejected_without_launch(self, env=None):
        with self.assertRaises((ValueError, OSError)):
            self.run_probe(env)
        self.launch.assert_not_called()

    def test_external_sdk_is_rejected(self):
        self.sdk = self.d.parent / "outside-sdk"
        self.exe = self.sdk / "bin" / hip.EXE
        self.assert_rejected_without_launch()

    def test_external_temp_is_rejected_before_creation(self):
        external = self.d / "outside-temp"
        self.assert_rejected_without_launch({"TEMP": str(external), "TMP": str(external),
                                            "AMD_COMGR_CACHE_DIR": str(external / "comgr")})
        self.assertFalse(external.exists())

    def test_external_cache_is_rejected_before_creation(self):
        external = self.d / "outside-cache"
        self.assert_rejected_without_launch({"TEMP": str(self.sdk / "tmp"), "TMP": str(self.sdk / "tmp"),
                                            "AMD_COMGR_CACHE_DIR": str(external)})
        self.assertFalse(external.exists())

    def test_corrupt_temp_is_rejected(self):
        (self.sdk / "tmp").write_text("not a directory")
        self.assert_rejected_without_launch()

    def test_corrupt_cache_is_rejected(self):
        (self.sdk / "tmp").mkdir()
        (self.sdk / "tmp" / "comgr").write_text("not a directory")
        self.assert_rejected_without_launch()

    def test_unwritable_temp_is_rejected(self):
        with mock.patch.object(hip.tempfile, "NamedTemporaryFile", side_effect=PermissionError("denied")):
            self.assert_rejected_without_launch()


if __name__ == "__main__":
    unittest.main()
