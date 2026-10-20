#!/usr/bin/env python3
"""Check packaged Monitor detach and terminal restoration on a POSIX PTY.

Run with the Python environment that has the optional Textual dependency.
This exercises an actual terminal session against loopback fake telemetry; it
does not qualify a physical terminal, Windows console or inference engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import select
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from portable_monitor_smoke import _server


def _http_counts(operations: list[str], *, require_both: bool = True) -> dict:
    operations = list(operations)
    if any(op not in ("GET /v1/telemetry", "GET /metrics") for op in operations):
        raise RuntimeError(f"Unexpected PTY HTTP operations: {operations!r}")
    telemetry = operations.count("GET /v1/telemetry")
    metrics = operations.count("GET /metrics")
    if require_both and (not telemetry or not metrics):
        raise RuntimeError(f"PTY case lacks telemetry or metrics: {operations!r}")
    return {"operations": operations, "telemetry_gets": telemetry,
            "metrics_gets": metrics, "http_gets": len(operations)}


def _case_http_ready(paths: list[str], start: int) -> bool:
    counts = _http_counts(paths[start:], require_both=False)
    return bool(counts["telemetry_gets"] and counts["metrics_gets"])


def _http_report(cases: list[dict], alive_operations: list[str],
                 operations: list[str], server_alive: bool) -> dict:
    if [case["key"] for case in cases] != ["q", "ctrl-c"]:
        raise RuntimeError(f"Unexpected PTY cases: {cases!r}")
    case_operations = []
    for case in cases:
        counts = _http_counts(case["operations"])
        if any(case.get(key) != counts[key] for key in counts):
            raise RuntimeError(f"PTY case HTTP counts disagree: {case!r}")
        case_operations.extend(counts["operations"])
    if not server_alive or alive_operations != ["GET /v1/telemetry"] or \
            operations != case_operations + alive_operations:
        raise RuntimeError(f"PTY HTTP boundary/server mismatch: cases={cases!r}, "
                           f"alive={alive_operations!r}, all={operations!r}, server_alive={server_alive}")
    return {**_http_counts(operations), "alive_probe_operations": list(alive_operations),
            "other_http_methods": 0}


def _case(bundle: Path, url: str, paths: list[str], key: bytes) -> dict:
    import fcntl
    import pty
    import termios

    master, slave = pty.openpty()
    process = None
    before_count = len(paths)
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
        before = termios.tcgetattr(slave)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        process = subprocess.Popen(
            [sys.executable, "-I", str(bundle), "monitor", "--url", url,
             "--interval", "0.5", "--glyphs", "ascii"],
            stdin=slave, stdout=slave, stderr=slave, close_fds=True, env=env)
        output = bytearray()
        bytes_read = 0
        sent = False
        active_raw = False
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                bytes_read += len(chunk)
                output.extend(chunk)
                if len(output) > 65536:
                    del output[:-65536]
            if not sent and _case_http_ready(paths, before_count) and b"STRATA" in output:
                active = termios.tcgetattr(slave)
                active_raw = not bool(active[3] & termios.ICANON) and not bool(active[3] & termios.ECHO)
                if active_raw:
                    os.write(master, key)
                    sent = True
            if process.poll() is not None:
                break
        if process.poll() is None:
            process.kill()
        exit_code = process.wait(timeout=3)
        restored = termios.tcgetattr(slave) == before
        if exit_code != 0 or not sent or not active_raw or not restored:
            raise RuntimeError(f"PTY detach failed: key={key!r}, exit={exit_code}, "
                               f"sent={sent}, raw={active_raw}, restored={restored}, "
                               f"operations={paths[before_count:]!r}")
        return {"key": "ctrl-c" if key == b"\x03" else "q", "exit_code": exit_code,
                "terminal_went_raw": active_raw, "terminal_restored": restored,
                **_http_counts(paths[before_count:]), "terminal_output_bytes": bytes_read}
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def smoke(bundle: Path) -> dict:
    bundle = bundle.resolve(strict=True)
    server, paths, _ = _server()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    cases = []
    alive_operations = []
    server_alive = False
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        for key in (b"q", b"\x03"):
            cases.append(_case(bundle, url, paths, key))
        alive_start = len(paths)
        with urllib.request.urlopen(url + "/v1/telemetry", timeout=3) as response:
            server_alive = response.status == 200
        alive_operations = list(paths[alive_start:])
        http = _http_report(cases, alive_operations, list(paths), server_alive)
    except Exception as error:
        raise RuntimeError(f"PTY smoke failed: cases={cases!r}, operations={paths!r}, "
                           f"alive={alive_operations!r}, server_alive={server_alive}: {error}") from error
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    return {"schema_version": 1, "scope": "portable_monitor_posix_pty_smoke",
            "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "python": platform.python_version(), "platform": platform.platform(),
            "cases": cases, "server_alive_after_detach": True,
            **http, "passed": True}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True, help="new absolute JSON report file")
    args = ap.parse_args()
    if os.name != "posix":
        ap.error("this pseudo-terminal check requires a POSIX host")
    if not args.report.is_absolute() or args.report.exists():
        ap.error("--report must be a new absolute file path")
    report = smoke(args.bundle)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"report": str(args.report), "passed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
