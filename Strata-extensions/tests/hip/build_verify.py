"""T07 isolated HIP fixture. Build never starts the fixture; GPU runs are explicit."""
import argparse
import base64
import csv
import email
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build-deepseek-t07"
BASE = "477ac13cbe8e582c20484871ce459d20d82df09d"
COMPILED = ["Strata-extensions/native/hip/runtime.hpp",
            "Strata-extensions/tests/hip/backend_fixture.hip"]
RECIPES = ["Strata-extensions/native/hip/CMakeLists.txt",
           "Strata-extensions/tests/hip/build_verify.py"]
SHARED = Path("C:/Develop/AI/StrataMod")
SDK = SHARED / ".vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel"
EXE = BUILD / "bundle/strata-ext-hip-fixture.exe"
MANIFEST = BUILD / "bundle/manifest.json"
DEVICE_WHEEL = BUILD / "downloads/rocm_sdk_device_gfx1100-10.1.0-py3-none-win_amd64.whl"
DEVICE_URL = "https://stable.repo.amd.com/rocm/core/whl-next/rocm-sdk-device-gfx1100/" + DEVICE_WHEEL.name


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(paths):
    return [{"path": p, "sha256": sha(ROOT / p)} for p in paths]


def aggregate(items):
    return hashlib.sha256("".join(f"{x['path']}|{x['sha256']}\n" for x in items).encode()).hexdigest()


def run(command, env=None, check=True, timeout=180):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"exit {result.returncode}: {command}\n{result.stdout}\n{result.stderr}")
    return result


def environment():
    vc = SHARED / ".vision-toolchain/vs/VC/Tools/MSVC/14.44.35207"
    win = SHARED / ".vision-toolchain/winsdk"
    inc = win / "microsoft.windows.sdk.cpp/c/Include/10.0.26100.0"
    lib = win / "microsoft.windows.sdk.cpp.x64/c"
    winbin = win / "microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64"
    tools = {"clang": SDK / "lib/llvm/bin/clang++.exe",
             "cmake": SHARED / ".vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe",
             "ninja": SHARED / ".vision-venv-10.1/Scripts/ninja.exe",
             "linker": vc / "bin/Hostx64/x64/link.exe",
             "dumpbin": vc / "bin/Hostx64/x64/dumpbin.exe",
             "rc": winbin / "rc.exe", "mt": winbin / "mt.exe",
             "objdump": SDK / "lib/llvm/bin/llvm-objdump.exe"}
    env = os.environ.copy()
    temporary = BUILD / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    env["TMP"] = env["TEMP"] = str(temporary)
    env["INCLUDE"] = os.pathsep.join(map(str, [vc / "include", inc / "ucrt", inc / "shared", inc / "um"]))
    env["LIB"] = os.pathsep.join(map(str, [vc / "lib/x64", lib / "ucrt/x64", lib / "um/x64", SDK / "lib"]))
    env["PATH"] = os.pathsep.join(map(str, [SDK / "bin", SDK / "lib/llvm/bin", vc / "bin/Hostx64/x64",
                                          winbin, os.environ.get("PATH", "")]))
    env["HIP_PATH"] = env["ROCM_PATH"] = str(SDK)
    env["HIP_PLATFORM"] = "amd"
    return tools, env


def binding(manifest, artifact=EXE):
    if manifest["compiled_sources"] != rows(COMPILED) or manifest["recipes"] != rows(RECIPES):
        raise ValueError("owned source/recipe changed")
    if manifest["compiled_sha256"] != aggregate(rows(COMPILED)) or sha(artifact) != manifest["artifact_sha256"]:
        raise ValueError("compiled identity/artifact changed")
    if (manifest["upstream_reference"]["base"] != BASE or manifest["upstream_reference"]["head"] != BASE
            or manifest["upstream_reference"]["tracked_diff"] or manifest["patches_applied"]):
        raise ValueError("upstream reference changed")
    for item in manifest["bundle_files"]:
        if sha(BUILD / "bundle" / item["path"]) != item["sha256"]:
            raise ValueError(f"bundle file changed: {item['path']}")


def safe_destination(bundle, relative):
    path = Path(relative)
    destination = (bundle / path).resolve()
    if path.is_absolute() or ".." in path.parts or not destination.is_relative_to(bundle.resolve()):
        raise ValueError("device ZIP path escapes owned bundle")
    return destination


def overlay_device_wheel(path, bundle):
    if Path(path).resolve() != DEVICE_WHEEL.resolve() or DEVICE_WHEEL.stat().st_size != 201201815:
        raise ValueError("unexpected owned device archive path/size")
    acquisition = json.loads((DEVICE_WHEEL.parent / "acquisition.json").read_text(encoding="utf-8"))
    archive_sha256 = sha(DEVICE_WHEEL)
    if (acquisition["source_url"] != DEVICE_URL or acquisition["size"] != 201201815
            or acquisition["sha256"] != archive_sha256):
        raise ValueError("device archive differs from its official acquisition receipt")
    with zipfile.ZipFile(path) as archive:
        metadata_root = "rocm_sdk_device_gfx1100-10.1.0.dist-info/"
        metadata = email.message_from_bytes(archive.read(metadata_root + "METADATA"))
        if (metadata["Name"] != "rocm-sdk-device-gfx1100" or metadata["Version"] != "10.1.0"
                or metadata.get_all("Requires-Dist") != ["rocm-sdk-libraries==10.1.0"]):
            raise ValueError("device wheel metadata differs from same-version host libraries")
        host = importlib.metadata.Distribution.at(SDK.parent / "rocm_sdk_libraries-10.1.0.dist-info")
        if host.version != "10.1.0":
            raise ValueError("host library version mismatch")
        record = {row[0]: row[1:] for row in csv.reader(io.StringIO(archive.read(metadata_root + "RECORD").decode()))}
        selected = []
        for item in archive.infolist():
            if item.filename.startswith("_rocm_sdk_libraries/bin/rocblas/library/"):
                relative = Path("rocblas/library") / item.filename.split("/library/", 1)[1]
            elif item.filename.startswith("_rocm_sdk_libraries/bin/hipblaslt/library/"):
                relative = Path("hipblaslt/library") / item.filename.split("/library/", 1)[1]
            elif item.filename in {"_rocm_sdk_libraries/.kpack/blas_lib_gfx1100.kpack",
                                   "_rocm_sdk_libraries/.kpack/solver_lib_gfx1100.kpack"}:
                relative = Path(".kpack") / Path(item.filename).name
            else:
                continue
            destination = safe_destination(bundle, relative)
            if (".." in Path(item.filename).parts or Path(item.filename).is_absolute() or item.is_dir()):
                raise ValueError("device ZIP path escapes owned bundle")
            selected.append((item, relative, destination))
        if len(selected) != 250 or sum(x[0].file_size for x in selected) != 74377625:
            raise ValueError("device asset selection changed from reviewed size/count")
        hashes = []
        for item, relative, destination in selected:
            digest = hashlib.sha256()
            destination.parent.mkdir(parents=True, exist_ok=True)
            expected_hash, expected_size = record[item.filename]
            if not expected_hash.startswith("sha256=") or int(expected_size) != item.file_size:
                raise ValueError("invalid selected RECORD entry")
            with archive.open(item) as source, destination.open("wb") as output:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                    output.write(block)
            actual = base64.urlsafe_b64encode(digest.digest()).decode().rstrip("=")
            if "sha256=" + actual != expected_hash:
                raise ValueError("selected asset RECORD hash mismatch")
            hashes.append({"archive_path": item.filename, "bundle_path": relative.as_posix(),
                           "size": item.file_size, "sha256": digest.hexdigest()})
    return {"source_url": DEVICE_URL, "archive_path": str(DEVICE_WHEEL), "archive_size": DEVICE_WHEEL.stat().st_size,
            "archive_sha256": archive_sha256, "publisher_checksum_verified": False,
            "name": "rocm-sdk-device-gfx1100", "version": "10.1.0", "requires": "rocm-sdk-libraries==10.1.0",
            "wheel_license_notice_entries": [], "wheel_specific_license": "unknown",
            "selected_file_count": len(hashes), "selected_bytes": 74377625, "selected_files": hashes}


def build(device_wheel=None):
    tools, env = environment()
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    diff = run(["git", "diff", BASE, "--name-only", "--", ".", ":(exclude)Strata-extensions"]).stdout.splitlines()
    if head != BASE or diff:
        raise ValueError("upstream reference changed")
    commands = [[tools["cmake"], "--fresh", "-S", ROOT / "Strata-extensions/native/hip", "-B", BUILD,
                 "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_TRY_COMPILE_CONFIGURATION=Release",
                 f"-DCMAKE_CXX_COMPILER={tools['clang'].as_posix()}", f"-DCMAKE_HIP_COMPILER={tools['clang'].as_posix()}",
                 f"-DCMAKE_HIP_COMPILER_ROCM_ROOT={SDK.as_posix()}",
                 f"-DCMAKE_PREFIX_PATH={SDK.as_posix()}", "-DCMAKE_HIP_ARCHITECTURES=gfx1100;gfx1201",
                 f"-DCMAKE_HIP_FLAGS=--rocm-path={SDK.as_posix()} --rocm-device-lib-path={SDK.as_posix()}/lib/llvm/amdgcn/bitcode",
                 f"-DCMAKE_MAKE_PROGRAM={tools['ninja'].as_posix()}", f"-DCMAKE_RC_COMPILER={tools['rc'].as_posix()}",
                 f"-DCMAKE_MT={tools['mt'].as_posix()}", f"-DCMAKE_LINKER={tools['linker'].as_posix()}"],
                [tools["cmake"], "--build", BUILD, "--clean-first", "--verbose"]]
    for index, command in enumerate(commands):
        result = run(command, env)
        (BUILD / f"build-{index}.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    bundle = BUILD / "bundle"
    # Pin the HIP/BLAS DLL family beside this test executable, avoiding System32's
    # different HIP driver DLL. Shared SDK files are only read, never modified.
    dll_names = ["amdhip64_7.dll", "amd_comgr.dll", "hipblas.dll", "rocblas.dll", "rocsolver.dll",
                 "libhipblaslt.dll", "origami.dll", "rocm_kpack.dll", "msvcp140.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll"]
    origin = []
    for name in dll_names:
        source = SDK / "bin" / name
        shutil.copyfile(source, bundle / name)
        origin.append({"source": str(source), "path": name, "sha256": sha(source)})
    for relative in ["bin/rocblas", "bin/hipblaslt"]:
        source = SDK / relative
        destination = bundle / Path(relative).name
        shutil.copytree(source, destination, dirs_exist_ok=True)
    pack_dir = bundle / ".kpack"
    pack_dir.mkdir(exist_ok=True)
    for name in ["blas_lib_gfx1201.kpack", "solver_lib_gfx1201.kpack"]:
        shutil.copyfile(SDK / ".kpack" / name, pack_dir / name)
    for component in ["amd_comgr", "hipblas", "hipblas-common", "hipblaslt", "origami", "rocblas", "rocsolver", "rocm-core"]:
        folder = SDK / "share/doc" / component
        for source in folder.rglob("*"):
            if source.is_file() and any(term in source.name.lower() for term in ["license", "notice", "copying"]):
                destination = bundle / "licenses" / component / source.relative_to(folder)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
    device_overlay = overlay_device_wheel(device_wheel, bundle) if device_wheel else None
    if not device_overlay and any((bundle / "rocblas/library").glob("*gfx1100*")):
        raise ValueError("existing gfx1100 assets require their explicit owned wheel provenance")
    tool_info = {}
    for name, path in tools.items():
        flag = "--version" if name in {"clang", "cmake", "ninja", "objdump"} else "/?"
        version = run([path, flag], env, check=False)
        tool_info[name] = {"path": str(path), "sha256": sha(path),
                           "version_first_lines": [line for line in (version.stderr + version.stdout).splitlines() if line.strip()][:3]}
    imported = run([tools["dumpbin"], "/dependents", EXE], env).stdout
    (BUILD / "direct-imports.txt").write_text(imported, encoding="utf-8")
    offload = run([tools["objdump"], "--offloading", EXE], env, check=False)
    (BUILD / "offloading.txt").write_text(offload.stdout + offload.stderr, encoding="utf-8")
    manifest = {"schema": "strata-ext-t07-trial/v1", "scope": "HIP backend microfixture only",
                "upstream_reference": {"base": BASE, "head": head, "tracked_diff": diff,
                                       "vendor_sources_compiled": False}, "patches_applied": [],
                "compiled_sources": rows(COMPILED), "compiled_sha256": aggregate(rows(COMPILED)),
                "recipes": rows(RECIPES), "artifact_sha256": sha(EXE),
                "bundle_files": [{"path": p.relative_to(bundle).as_posix(), "sha256": sha(p)}
                                 for p in sorted(bundle.rglob("*")) if p.is_file() and p != MANIFEST],
                "dll_origins": origin,
                "owned_device_overlay": device_overlay,
                "direct_imports": sorted(set(re.findall(r"^\s+([\w.-]+\.dll)\s*$", imported, re.M | re.I))),
                "tools": tool_info,
                "commands": [[str(x) for x in c] for c in commands],
                "target_architectures": ["gfx1100", "gfx1201"],
                "package_inventory": {d.metadata['Name']: d.version for d in importlib.metadata.distributions(path=[str(SDK.parent)])
                                      if d.metadata.get('Name', '').lower().startswith('rocm')},
                "license_scope": "available adopted SDK component notices copied; no redistribution qualification of the full toolchain",
                "not_verified": ["DeepSeek numerical operations", "model inference", "peer/multi-GPU execution",
                                 "server/runtime integration", "full DLL closure", "individual BLAS kernel asset read paths"]}
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    binding(manifest)
    result = {"status": "built_no_gpu_execution", "manifest_sha256": sha(MANIFEST),
              "artifact_sha256": sha(EXE), "scope": manifest["scope"]}
    (BUILD / "build-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


def execute(args):
    tools, env = environment()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    frozen = sha(MANIFEST)
    binding(manifest)
    env["PATH"] = str(EXE.parent) + os.pathsep + env["PATH"]
    env["ROCBLAS_TENSILE_LIBPATH"] = str(EXE.parent / "rocblas/library")
    # The library's default resolver appends its architecture subdirectory.
    # A parent-directory override suppresses that behavior and causes false misses.
    env.pop("HIPBLASLT_TENSILE_LIBPATH", None)
    formatted = json.loads(run([EXE, "--budget-format-selftest"], env).stdout)
    for key, failed, successful in [("local_ok_shared_failed", "shared", "local"),
                                    ("local_failed_shared_ok", "local", "shared")]:
        fields = formatted[key]
        if (fields[failed + "_hresult"] >= 0 or fields[failed + "_budget"] is not None
                or fields[failed + "_usage"] is not None
                or fields[failed + "_available_for_reservation"] is not None
                or fields[successful + "_hresult"] != 0 or fields[successful + "_budget"] != 1234):
            raise AssertionError("budget failure formatted as an observed numeric value")
    if args.inventory:
        command = [EXE, "--inventory"]
        result = run(command, env, check=False)
        (BUILD / "inventory.stdout.json").write_text(result.stdout, encoding="utf-8")
        (BUILD / "inventory.stderr.txt").write_text(result.stderr, encoding="utf-8")
        binding(manifest)
        if sha(MANIFEST) != frozen:
            raise ValueError("trial manifest changed")
        print(json.dumps({"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}))
        return
    results = {}
    for role, pci in [("primary", args.primary_pci), ("secondary", args.secondary_pci)]:
        if not pci:
            results[role] = {"status": "not_requested"}
            continue
        result = run([EXE, "--probe", pci], env, check=False)
        (BUILD / f"{role}.stdout.json").write_text(result.stdout, encoding="utf-8")
        (BUILD / f"{role}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        record = {"exit_code": result.returncode, "selected_pci": pci, "stderr": result.stderr}
        try:
            record["native"] = json.loads(result.stdout)
        except json.JSONDecodeError:
            record["invalid_native_output"] = result.stdout
        record["status"] = "passed" if not result.returncode else "not_established"
        native = record.get("native", {})
        if (native.get("status") != "passed" or native.get("compiled_sha256") != manifest["compiled_sha256"]
                or native.get("device", {}).get("pci") != pci):
            record["status"] = "not_established"
        # Capture actual module locations observed after GPU work, independently
        # hashing them after exit against the pre-test pinned DLL family.
        loaded = record.get("native", {}).get("loaded_modules", {})
        if not {"amdhip64_7.dll", "hipblas.dll", "rocblas.dll"}.issubset(loaded):
            record["status"] = "not_established"
        record["loaded_dlls"] = []
        for name, path in loaded.items():
            actual = Path(path)
            expected = EXE.parent / name
            same = actual.resolve() == expected.resolve() and sha(actual) == sha(expected)
            record["loaded_dlls"].append({"name": name, "path": path, "sha256": sha(actual), "pinned_match": same})
            if not same:
                record["status"] = "not_established"
        results[role] = record
        binding(manifest)
    binding(manifest)
    negative_cases = []
    for key in ["compiled_sources", "recipes", "compiled_sha256"]:
        changed = json.loads(json.dumps(manifest))
        if key == "compiled_sha256":
            changed[key] = "0" * 64
        else:
            changed[key][0]["sha256"] = "0" * 64
        try:
            binding(changed)
        except ValueError:
            negative_cases.append(key + " rejected")
        else:
            raise AssertionError("binding tamper accepted")
    tampered = BUILD / "tampered-fixture.exe"
    shutil.copyfile(EXE, tampered)
    with tampered.open("ab") as stream:
        stream.write(b"changed")
    try:
        binding(manifest, tampered)
    except ValueError:
        negative_cases.append("binary tamper rejected")
    else:
        raise AssertionError("binary tamper accepted")
    if sha(MANIFEST) != frozen:
        raise ValueError("trial manifest changed")
    receipt = {"schema": "strata-ext-t07-observation/v1", "manifest_sha256": frozen,
               "artifact_sha256": manifest["artifact_sha256"], "devices": results,
               "primary_core_status": results["primary"]["status"],
               "secondary_additional_status": results["secondary"]["status"],
               "binding_negative_cases": negative_cases,
               "budget_format_negative_cases": formatted,
               "not_verified": manifest["not_verified"]}
    (BUILD / "verification.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="GPU inventory; needs Main's execution go-ahead")
    parser.add_argument("--primary-pci")
    parser.add_argument("--secondary-pci")
    parser.add_argument("--gfx1100-wheel", type=Path, help="reviewed same-version archive in the owned downloads directory")
    args = parser.parse_args()
    if args.inventory or args.primary_pci or args.secondary_pci:
        execute(args)
    else:
        build(args.gfx1100_wheel)
