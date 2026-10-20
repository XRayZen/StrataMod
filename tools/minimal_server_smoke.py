#!/usr/bin/env python3
"""Exercise fake-engine serving from a clean runtime-only Python environment.

Create a fresh venv, install requirements.txt, then run this script with that
venv's Python. The runtime integration module exercises foreground and POSIX
owned serving; no GPU, model weights or optional terminal framework is needed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_MODULE = "tests.terminal.test_runtime"
MIN_TESTS = 32


def _summary(result: subprocess.CompletedProcess[str]) -> dict:
    text = result.stdout + result.stderr
    value = {"tests_run": None, "tests_skipped": None, "tests_passed": None,
             "passed": False, "summary_error": None}
    headers = re.findall(r"(?m)^Ran [^\r\n]*\r?$", text)
    match = re.search(r"(?m)^Ran (\d+) tests? in [0-9]+(?:\.[0-9]+)?s\r?\n"
                      r"\s*OK(?: \(skipped=(\d+)\))?\s*\Z", text)
    if len(headers) != 1 or match is None:
        value["summary_error"] = "missing, ambiguous or unsupported terminal unittest summary"
        return value
    run, skipped = int(match[1]), int(match[2] or 0)
    if skipped > run:
        value["summary_error"] = "skipped tests exceed tests run"
        return value
    value.update(tests_run=run, tests_skipped=skipped, tests_passed=run - skipped)
    if result.returncode != 0:
        value["summary_error"] = "unittest exited nonzero"
    elif run - skipped < MIN_TESTS:
        value["summary_error"] = "too few actual passing tests"
    else:
        value["passed"] = True
    return value


def smoke() -> dict:
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("run with a dedicated virtual environment")
    if os.name != "posix":
        raise RuntimeError("this owned-runtime check currently requires POSIX")
    visible = {name: importlib.util.find_spec(name) is not None
               for name in ("rich", "textual", "numpy", "jinja2", "requests")}
    if visible != {"rich": False, "textual": False, "numpy": True,
                   "jinja2": True, "requests": True}:
        raise RuntimeError(f"runtime-only dependency set was not isolated: {visible}")
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-m", "unittest", TEST_MODULE], cwd=ROOT,
                            capture_output=True, text=True, timeout=240, check=False)
    summary = result.stdout + result.stderr
    counts = _summary(result)
    return {"schema_version": 1, "scope": "source_checkout_fake_engine_runtime_only",
            "platform": platform.platform(), "python": platform.python_version(),
            "requirements_sha256": hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest(),
            "optional_packages_visible": {name: visible[name] for name in ("rich", "textual")},
            "server_packages_visible": {name: visible[name] for name in ("numpy", "jinja2", "requests")},
            "test_module": TEST_MODULE, **counts,
            "duration_s": round(time.monotonic() - started, 2),
            "test_exit_code": result.returncode, "actual_gpu_engine": False,
            "test_summary": summary[-1000:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="new absolute JSON report path")
    args = parser.parse_args()
    report = args.report.expanduser()
    if not report.is_absolute() or report.exists():
        parser.error("--report must be an absolute new file")
    result = smoke()
    report.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(report), "passed": result["passed"]}), flush=True)
    if not result["passed"]:
        print(json.dumps({"test_exit_code": result["test_exit_code"],
                          "summary_error": result["summary_error"]}), file=sys.stderr)
        print(result["test_summary"], file=sys.stderr)
    return 0 if result["passed"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
