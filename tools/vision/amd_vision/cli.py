#!/usr/bin/env python3
"""Experimental Windows HIP vision build and config copy. No SDK download or engine replacement.

Use a private TheRock SDK, initialized by rocm-sdk init. Its bin directory holds the
encoder beside the matching DLLs, and its kernel data stays in the SDK's original layout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from serve.stratamod.amd_vision.environment import windows_hip_env  # noqa: E402
from tools.gguf_reader import GGUFFile  # noqa: E402

LLAMA_COMMIT = "3cf03257f219afbe7334045ff7c6a06ac68c627d"
EXE = "strata-vision-hip.exe"
STAMP = "strata-vision-hip.build.json"
IS_WINDOWS = os.name == "nt"


def under(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


def sdk_root(value: Path) -> Path:
    root = value.resolve()
    for engine in (ROOT / "engine", ROOT / "engine-cuda12"):
        if under(root, engine):
            raise ValueError("Use a private ROCm SDK outside the existing engine directory")
    required = ("bin/amdhip64_7.dll", "bin/hipblas.dll", "bin/rocblas.dll", "bin/amd_comgr.dll", "bin/rocm_kpack.dll",
                "lib/llvm/bin/clang.exe", "lib/llvm/bin/clang++.exe", "lib/llvm/amdgcn/bitcode", ".kpack")
    for name in required:
        if not (root / name).exists():
            raise ValueError(f"Incomplete initialized TheRock SDK: missing {root / name}")
    return root


def configure_command(rocm: Path, llama: Path, build: Path, arch: str) -> list[str]:
    return ["cmake", "-G", "Ninja", "-S", str(ROOT / "tools" / "vision"), "-B", str(build),
            "-DCMAKE_BUILD_TYPE=Release", f"-DLLAMA_DIR={llama.as_posix()}",
            "-DSTRATA_VISION_HIP=ON", "-DSTRATA_VISION_CUDA=OFF", "-DGGML_STATIC=OFF",
            "-DSTRATA_PORTABLE=ON", f"-DGPU_TARGETS={arch}", f"-DAMDGPU_TARGETS={arch}",
            f"-DCMAKE_C_COMPILER={rocm.as_posix()}/lib/llvm/bin/clang.exe",
            f"-DCMAKE_CXX_COMPILER={rocm.as_posix()}/lib/llvm/bin/clang++.exe",
            f"-DCMAKE_PREFIX_PATH={rocm.as_posix()}"]


def compiler_env(rocm: Path) -> dict:
    env = dict(os.environ)
    stale = {"HIP_ROOT", "HIPBLAS_ROOT", "ROCBLAS_ROOT", "HIP_DIR", "HIPBLAS_DIR", "ROCBLAS_DIR",
             "CMAKE_PREFIX_PATH", "ROCBLAS_TENSILE_LIBPATH", "HIPBLASLT_TENSILE_LIBPATH", "ROCM_HOME"}
    for key in list(env):
        if key.upper() in stale:
            del env[key]
    env.update(HIP_PLATFORM="amd", HIP_PATH=str(rocm), ROCM_PATH=str(rocm),
               HIP_DEVICE_LIB_PATH=str(rocm / "lib/llvm/amdgcn/bitcode"),
               LLVM_PATH=str(rocm / "lib/llvm"))
    env["PATH"] = os.pathsep.join([str(rocm / "bin"), str(rocm / "lib/llvm/bin"), env.get("PATH", "")])
    return env


def build_encoder(a) -> None:
    rocm, llama, build = sdk_root(a.rocm_root), a.llama_dir.resolve(), a.build_dir.resolve()
    pinned = re.search(r'LLAMA_CPP_COMMIT = "([0-9a-f]+)"', (ROOT / "setup.py").read_text(encoding="utf-8"))
    if not pinned or pinned.group(1) != LLAMA_COMMIT:
        raise ValueError("This experiment must be reviewed again for the repository's new llama.cpp revision")
    if not (llama / ".git").exists():
        raise ValueError("--llama-dir needs a git checkout, so its exact revision can be verified")
    actual = subprocess.check_output(["git", "-C", str(llama), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(llama), "status", "--porcelain"], text=True).strip()
    if actual != LLAMA_COMMIT or dirty:
        raise ValueError(f"llama.cpp must be clean at {LLAMA_COMMIT}; got {actual}, dirty={bool(dirty)}")
    if not re.fullmatch(r"gfx[0-9a-f]+", a.arch):
        raise ValueError("--arch must name one real GPU architecture, for example gfx1201")
    if not (rocm / ".kpack" / f"blas_lib_{a.arch}.kpack").is_file():
        raise ValueError(f"Missing SDK device kernels for {a.arch}; install device-{a.arch} and run rocm-sdk init")
    if build.exists() and any(build.iterdir()):
        raise ValueError("Use an empty --build-dir; cached CPU/CUDA/other SDK settings must not be reused")
    if a.jobs < 1:
        raise ValueError("--jobs must be positive")
    dest = rocm / "bin" / EXE
    if dest.exists():
        raise ValueError(f"Refusing to replace an existing encoder: {dest}; use a new private SDK")
    cmd = configure_command(rocm, llama, build, a.arch)
    compile_cmd = ["cmake", "--build", str(build), "--target", "strata-vision", "--parallel", str(a.jobs)]
    for command in (cmd, compile_cmd):
        print(subprocess.list2cmdline(command), flush=True)
    print(f"Encoder destination: {rocm / 'bin' / EXE}", flush=True)
    if a.dry_run:
        print("DRY RUN: no configure, compilation, SDK writes or config writes were performed")
        return
    if not IS_WINDOWS:
        raise ValueError("This builder needs Windows and an x64 Visual Studio developer prompt")
    if not os.environ.get("VCToolsInstallDir") or not os.environ.get("VCToolsRedistDir"):
        raise ValueError("Run from an x64 Visual Studio developer prompt (MSVC 19.43 or newer)")
    for tool in ("cmake", "ninja", "link.exe"):
        if not shutil.which(tool):
            raise ValueError(f"Missing {tool} in the developer prompt")
    env = compiler_env(rocm)
    compiler = subprocess.check_output([str(rocm / "lib/llvm/bin/clang++.exe"), "--version"], env=env, text=True)
    subprocess.run(cmd, check=True, env=env)
    subprocess.run(compile_cmd, check=True, env=env)
    built = build / "bin" / "strata-vision.exe"
    # The SDK uses the MSVC runtime. Add only missing redistributables, never replace SDK DLLs.
    crt_dirs = sorted((Path(os.environ["VCToolsRedistDir"]) / "x64").glob("Microsoft.VC*.CRT"))
    if not crt_dirs:
        raise ValueError("No x64 MSVC redistributable directory was found")
    for dll in crt_dirs[-1].glob("*.dll"):
        target = rocm / "bin" / dll.name
        if not target.exists():
            shutil.copy2(dll, target)
    shutil.copy2(built, dest)
    manifest = {"backend": "hip", "llama_commit": LLAMA_COMMIT, "arch": a.arch, "rocm_root": str(rocm),
                "encoder_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(), "compiler": compiler,
                "cmake_command": cmd, "validation": "compiled; GPU image execution not yet validated"}
    (rocm / "bin" / STAMP).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Build complete. Run the probe, then an image smoke test; a build is not a GPU execution result.")


def encoder_files(root: Path) -> tuple[Path, Path]:
    rocm = sdk_root(root)
    exe, stamp = rocm / "bin" / EXE, rocm / "bin" / STAMP
    meta = json.loads(stamp.read_text(encoding="utf-8"))
    if meta.get("backend") != "hip" or meta.get("llama_commit") != LLAMA_COMMIT:
        raise ValueError("The encoder build manifest does not match this experiment")
    if hashlib.sha256(exe.read_bytes()).hexdigest() != meta.get("encoder_sha256"):
        raise ValueError("The encoder differs from its build manifest")
    return rocm, exe


def probe(a) -> None:
    if not IS_WINDOWS:
        raise ValueError("The HIP device probe must run on Windows")
    rocm, exe = encoder_files(a.rocm_root)
    if not under(rocm, ROOT):
        raise ValueError("The probe SDK must be private to the StrataMod root")
    env = windows_hip_env({"rocm_root": str(rocm), "exe": str(exe), "hip_device": 0}, os.environ)
    temp, cache = Path(env["TEMP"]), Path(env["AMD_COMGR_CACHE_DIR"])
    if not temp.is_absolute() or not cache.is_absolute() or not under(temp, rocm) or not under(cache, temp):
        raise ValueError("The probe TEMP and COMGR cache must stay inside the private SDK")
    for directory in (temp, cache):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix="strata-probe-write-") as writable:
            writable.write(b"probe")
            writable.flush()
    env.pop("HIP_VISIBLE_DEVICES")  # list the private SDK's unfiltered device ordinals
    subprocess.run([str(exe), "--list-devices", "--require-hip"], check=True, env=env, cwd=rocm / "bin")


def check_models(mmproj: Path, model: Path) -> int:
    image, text = GGUFFile(mmproj).metadata, GGUFFile(model).metadata
    if text.get("split.no", 0) != 0:
        raise ValueError("--model must be the first GGUF shard (split.no=0)")
    arch = text.get("general.architecture")
    width, projection = text.get(f"{arch}.embedding_length"), image.get("clip.vision.projection_dim")
    if not isinstance(width, int) or width <= 0 or width != projection:
        raise ValueError(f"Model/projector dimensions do not match: model={width}, projector={projection}")
    if not text.get("tokenizer.ggml.tokens"):
        raise ValueError("The first model shard needs tokenizer.ggml.tokens")
    if arch != "qwen4exp" or image.get("clip.projector_type") != "qwen3vl_merger":
        raise ValueError("This candidate requires the Qwen3.8 qwen4exp text / qwen3vl_merger projector family")
    tokens = text["tokenizer.ggml.tokens"]
    if any(token not in tokens for token in ("<|vision_start|>", "<|vision_end|>", "<|image_pad|>")):
        raise ValueError("The first model shard is missing image marker tokens")
    return width


def config_copy(a) -> None:
    if not IS_WINDOWS and not a.dry_run:
        raise ValueError("Create the config on Windows so its absolute paths name the real SDK and models")
    source, output = a.config.resolve(), a.out.resolve()
    if source == output or output.exists():
        raise ValueError("--out must be a new file, different from the source config")
    cfg = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict) or cfg.get("backend") != "hip":
        raise ValueError("Start from a working HIP text-engine config")
    rocm, exe = encoder_files(a.rocm_root)
    here = Path(cfg.get("cwd") or ".").resolve()
    def configured_path(value):
        path = Path(value)
        return (path if path.is_absolute() else here / path).resolve()
    engine_exe = Path(cfg["exe"])
    engine_exe = (engine_exe if engine_exe.is_absolute() else here / engine_exe).resolve()
    engine = engine_exe.parent
    if under(rocm, engine) or under(engine, rocm):
        raise ValueError("The image SDK must be separate from the text engine and its DLLs")
    libraries = [configured_path(lib) for lib in cfg.get("lib_dirs") or []]
    for lib in libraries:
        if under(lib, rocm):
            raise ValueError("The source text config already uses this SDK; choose a private image SDK")
    if a.hip_device < 0 or not 1 <= a.max_tokens <= 1024:
        raise ValueError("Use a non-negative --hip-device and --max-tokens between 1 and 1024 (initially 300)")
    mmproj, model = a.mmproj.resolve(), a.model.resolve()
    args = cfg.get("args") or []
    if args.count("--native") != 1 or args.index("--native") + 1 >= len(args):
        raise ValueError("The text candidate needs one --native model file")
    native = Path(args[args.index("--native") + 1])
    native = (native if native.is_absolute() else here / native).resolve()
    if native != model:
        raise ValueError("--model must be the same first GGUF file as the text engine's --native")
    width = check_models(mmproj, model)
    # Preserve the server's path meanings even if the new JSON is saved in another directory.
    cfg["cwd"], cfg["exe"] = str(here), str(engine_exe)
    cfg["lib_dirs"] = [str(lib) for lib in libraries]
    if cfg.get("tokenizer"):
        cfg["tokenizer"] = str(configured_path(cfg["tokenizer"]))
    cfg["vision"] = {"backend": "hip", "exe": str(exe), "rocm_root": str(rocm), "hip_device": a.hip_device,
                     "mmproj": str(mmproj), "model": str(model), "gpu": True, "max_tokens": a.max_tokens}
    cfg["lazy_load"] = False
    cfg["log"] = str(output.with_suffix(".log"))
    print(f"New config: {output}; HIP device {a.hip_device}; projection width {width}; image tokens <= {a.max_tokens}")
    print("Matching dimensions are necessary; confirm that the projector and text model are the same model family.")
    if a.dry_run:
        print("DRY RUN: source, output and engine files were not modified")
        return
    with output.open("x", encoding="utf-8") as f:
        f.write(json.dumps(cfg, indent=2))
        f.write("\n")
    print("Use this config through StrataMod's reviewed candidate runtime, without rerunning standard setup.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="compile with an initialized private SDK; never rebuild the text engine")
    b.add_argument("--rocm-root", type=Path, required=True)
    b.add_argument("--llama-dir", type=Path, required=True)
    b.add_argument("--build-dir", type=Path, default=ROOT / "build-vision-hip-win")
    b.add_argument("--arch", default="gfx1201")
    b.add_argument("--jobs", type=int, default=4)
    b.add_argument("--dry-run", action="store_true")
    b.set_defaults(run=build_encoder)
    p = sub.add_parser("probe", help="list devices through the private SDK, without model loading")
    p.add_argument("--rocm-root", type=Path, required=True)
    p.set_defaults(run=probe)
    c = sub.add_parser("config", help="create a separate HIP image config; never overwrite the source")
    for name in ("rocm-root", "config", "mmproj", "model", "out"):
        c.add_argument("--" + name, type=Path, required=True)
    c.add_argument("--hip-device", type=int, required=True)
    c.add_argument("--max-tokens", type=int, default=300)
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(run=config_copy)
    a = ap.parse_args()
    try:
        a.run(a)
    except (OSError, ValueError, KeyError, struct.error, subprocess.CalledProcessError) as exc:
        print(f"HIP vision: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
