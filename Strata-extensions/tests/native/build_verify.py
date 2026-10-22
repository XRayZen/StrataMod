"""Build and verify the T06 Windows host fixture; never starts a GPU/runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE = "477ac13cbe8e582c20484871ce459d20d82df09d"
ROOT = Path(__file__).resolve().parents[3]
COMPILED = [
    "Strata-extensions/native/include/strata_ext/provenance.hpp",
    "Strata-extensions/native/provenance.cpp",
    "Strata-extensions/tests/native/host_fixture.cpp",
]
RECIPES = ["Strata-extensions/native/CMakeLists.txt",
           "Strata-extensions/tests/native/build_verify.py"]
SHARED = Path("C:/Develop/AI/StrataMod")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(paths):
    return [{"path": p, "sha256": sha(ROOT / p)} for p in paths]


def aggregate(source_rows):
    material = "".join(f"{r['path']}|{r['sha256']}\n" for r in source_rows)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def run(command, env=None, check=True):
    result = subprocess.run([str(x) for x in command], env=env, cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {command}\n"
                           f"{result.stdout}\n{result.stderr}")
    return result


def toolchain(build):
    vc = SHARED / ".vision-toolchain/vs/VC/Tools/MSVC/14.44.35207"
    sdk = SHARED / ".vision-toolchain/winsdk"
    include = sdk / "microsoft.windows.sdk.cpp/c/Include/10.0.26100.0"
    lib = sdk / "microsoft.windows.sdk.cpp.x64/c"
    tools = {"compiler": vc / "bin/Hostx64/x64/cl.exe",
             "linker": vc / "bin/Hostx64/x64/link.exe",
             "dumpbin": vc / "bin/Hostx64/x64/dumpbin.exe",
             "resource_compiler": sdk / "microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64/rc.exe",
             "manifest_tool": sdk / "microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64/mt.exe",
             "cmake": SHARED / ".vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe",
             "ninja": SHARED / ".vision-venv-10.1/Scripts/ninja.exe"}
    for path in tools.values():
        if not path.is_file():
            raise RuntimeError(f"missing read-only tool: {path}")
    env = os.environ.copy()
    temporary = build / "tmp"
    temporary.mkdir(exist_ok=True)
    env["TMP"] = env["TEMP"] = str(temporary)
    env["INCLUDE"] = os.pathsep.join(map(str, [vc / "include", include / "ucrt",
                                              include / "shared", include / "um"]))
    env["LIB"] = os.pathsep.join(map(str, [vc / "lib/x64", lib / "ucrt/x64", lib / "um/x64"]))
    env["PATH"] = os.pathsep.join([str(vc / "bin/Hostx64/x64"),
                                    str(tools["resource_compiler"].parent),
                                    str(tools["cmake"].parent), env.get("PATH", "")])
    return tools, env


def verify_binding(manifest, executable):
    if manifest["compiled_owned_sources"] != rows(COMPILED):
        raise ValueError("compiled source fingerprint changed")
    if manifest["build_recipe_sources"] != rows(RECIPES):
        raise ValueError("build recipe fingerprint changed")
    if manifest["compiled_owned_sha256"] != aggregate(rows(COMPILED)):
        raise ValueError("source aggregate changed")
    reference = manifest["upstream_reference"]
    if (reference["base_revision"] != BASE or reference["worktree_head"] != BASE
            or reference["base_tracked_diff"] or reference["vendor_sources_compiled"]
            or manifest["patches_applied"]):
        raise ValueError("upstream reference scope changed")
    if sha(executable) != manifest["artifact"]["sha256"]:
        raise ValueError("artifact hash changed")
    identity = json.loads(run([executable, "--identity"]).stdout)
    if identity != {"upstream_reference_base": BASE,
                    "compiled_owned_sha256": aggregate(rows(COMPILED))}:
        raise ValueError("compiled identity mismatch")


def verify_cases(executable, directory):
    data = bytes(range(256)) * 521 + b"\x00T06\xff"
    fixture = directory / "host-input.bin"
    fixture.write_bytes(data)
    results = []
    for offset, length in [(0, 0), (0, len(data)), (1, 65537), (len(data), 0), (255, 7)]:
        actual = run([executable, "--sha256", fixture, offset, length]).stdout.strip()
        expected = hashlib.sha256(data[offset:offset + length]).hexdigest()
        if actual != expected:
            raise AssertionError(f"native/hashlib mismatch at {offset}/{length}")
        results.append({"case": f"span-{offset}-{length}", "passed": True})
    unicode_fixture = directory / "host-input-日本語.bin"
    unicode_fixture.write_bytes(data)
    if run([executable, "--sha256", unicode_fixture, 0, len(data)]).stdout.strip() != hashlib.sha256(data).hexdigest():
        raise AssertionError("Unicode file path mismatch")
    results.append({"case": "unicode-file-path", "passed": True})
    for label, path, offset, length in [
        ("past-eof", fixture, len(data) + 1, 0),
        ("truncated-span", fixture, len(data) - 1, 2),
        ("overflow", fixture, "18446744073709551615", 1),
        ("integer-overflow", fixture, "18446744073709551616", 0),
        ("negative", fixture, "-1", 1),
        ("malformed", fixture, "1x", 1),
        ("missing-file", directory / "missing.bin", 0, 0),
    ]:
        outcome = run([executable, "--sha256", path, offset, length], check=False)
        if not outcome.returncode or outcome.stdout.strip():
            raise AssertionError(f"invalid fixture accepted: {label}")
        results.append({"case": label, "passed": True, "exit_code": outcome.returncode})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-deepseek-t06")
    args = parser.parse_args()
    build = args.build_dir.resolve()
    # This runner only writes generated data in its agreed task directory.
    if build != (ROOT / "build-deepseek-t06").resolve():
        raise ValueError("generated output must use the agreed T06 build directory")
    build.mkdir(parents=True, exist_ok=True)
    outcome = build / "verification.json"
    try:
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if head != BASE:
            raise ValueError("worktree HEAD differs from the agreed base")
        # The base has no owned extension tree. Restrict this diff to base-tracked
        # sources, so other agents' new owned files remain outside this assertion.
        base_paths = run(["git", "ls-tree", "-r", "--name-only", BASE]).stdout.splitlines()
        tracked_diff = run(["git", "diff", BASE, "--name-only", "--", ".",
                            ":(exclude)Strata-extensions"]).stdout.splitlines()
        if tracked_diff or any(p.startswith("Strata-extensions/") for p in base_paths):
            raise ValueError("upstream base-tracked sources changed")
        tools, env = toolchain(build)
        commands = [[tools["cmake"], "-S", ROOT / "Strata-extensions/native", "-B", build,
                     "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                     "-DCMAKE_TRY_COMPILE_CONFIGURATION=Release",
                     f"-DCMAKE_CXX_COMPILER={tools['compiler']}",
                     f"-DCMAKE_RC_COMPILER={tools['resource_compiler']}",
                     f"-DCMAKE_MT={tools['manifest_tool']}",
                     f"-DCMAKE_LINKER={tools['linker']}",
                     f"-DCMAKE_MAKE_PROGRAM={tools['ninja']}"],
                    [tools["cmake"], "--build", build, "--clean-first", "--verbose"]]
        for index, command in enumerate(commands):
            log = run(command, env)
            (build / f"build-step-{index}.txt").write_text(log.stdout + log.stderr, encoding="utf-8")
        executable = build / "bundle/strata-ext-host-fixture.exe"
        imports_output = run([tools["dumpbin"], "/dependents", executable], env).stdout
        (build / "direct-imports.txt").write_text(imports_output, encoding="utf-8")
        imports = sorted(set(re.findall(r"^\s+([\w.-]+\.dll)\s*$", imports_output, re.M | re.I)))
        if not imports:
            raise ValueError("PE direct imports were not found")
        dependencies = []
        for name in imports:
            path = Path(os.environ["SystemRoot"]) / "System32" / name
            if not path.is_file():
                raise ValueError(f"unresolved direct import: {name}")
            dependencies.append({"import": name, "disk_path": str(path), "sha256": sha(path),
                                 "loaded_path_verified": False})
        tool_rows = {}
        for name, path in tools.items():
            flag = "--version" if name in {"cmake", "ninja"} else "/?"
            version = run([path, flag], env, check=False)
            lines = [line for line in (version.stderr + version.stdout).splitlines()
                     if line.strip()]
            tool_rows[name] = {"path": str(path), "sha256": sha(path),
                               "version_first_lines": lines[:3]}
        manifest = {"schema": "strata-ext-t06-host-bundle/v1",
                    "scope": "early Windows CPU host fixture only",
                    "upstream_reference": {"base_revision": BASE, "worktree_head": head,
                                           "base_tracked_diff": tracked_diff,
                                           "vendor_sources_compiled": False},
                    "compiled_owned_sources": rows(COMPILED),
                    "compiled_owned_sha256": aggregate(rows(COMPILED)),
                    "build_recipe_sources": rows(RECIPES), "patches_applied": [],
                    "tools": tool_rows, "commands": [[str(x) for x in c] for c in commands],
                    "artifact": {"path": str(executable), "sha256": sha(executable)},
                    "direct_pe_imports": dependencies,
                    "crt_policy": "static /MT for this host fixture target only",
                    "not_verified": ["HIP build", "GPU initialization/execution", "GPU DLLs",
                                     "server/runtime bundle", "recursive DLL closure",
                                     "actual loaded DLL paths", "model/header/quant semantics"]}
        # Freeze the trial bundle before any native identity/hash case runs.
        manifest_path = build / "bundle/manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        frozen_manifest_sha256 = sha(manifest_path)
        verify_binding(manifest, executable)
        tests = verify_cases(executable, build)
        verify_binding(manifest, executable)
        tests.append({"case": "valid-source-artifact-binding", "passed": True})
        for section in ("compiled_owned_sources", "build_recipe_sources", "compiled_owned_sha256"):
            altered = json.loads(json.dumps(manifest))
            if section == "compiled_owned_sha256":
                altered[section] = "0" * 64
            else:
                altered[section][0]["sha256"] = "0" * 64
            try:
                verify_binding(altered, executable)
            except ValueError:
                tests.append({"case": f"{section}-tamper", "passed": True})
            else:
                raise AssertionError(f"changed {section} accepted")
        tampered = build / "tampered-fixture.exe"
        shutil.copyfile(executable, tampered)
        with tampered.open("ab") as stream:
            stream.write(b"tampered")
        # A PE with appended bytes can still run and report the same identity.
        # Reject it against the pre-test frozen bundle even if its behavior agrees.
        if json.loads(run([tampered, "--identity"]).stdout) != json.loads(run([executable, "--identity"]).stdout):
            raise AssertionError("tamper fixture did not retain its original identity")
        try:
            verify_binding(manifest, tampered)
        except ValueError:
            tests.append({"case": "binary-tamper", "passed": True})
        else:
            raise AssertionError("changed binary accepted")
        verify_binding(manifest, executable)
        if sha(manifest_path) != frozen_manifest_sha256:
            raise ValueError("frozen trial manifest changed during verification")
        result = {"status": "passed", "scope": manifest["scope"], "cases": tests,
                  "manifest_sha256": sha(manifest_path), "artifact_sha256": sha(executable),
                  "not_verified": manifest["not_verified"]}
        outcome.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    except Exception as error:
        outcome.write_text(json.dumps({"status": "failed", "error": str(error)}, indent=2) + "\n",
                           encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
