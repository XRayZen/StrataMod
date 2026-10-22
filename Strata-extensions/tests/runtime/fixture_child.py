"""Finite CPU identity fixture. This is never a model or readiness producer."""
import json
import os
import sys
import psutil


def main():
    request = json.loads(sys.stdin.readline())
    process = psutil.Process()
    print(json.dumps(dict(kind='cpu_fixture', nonce=request['nonce'], pid=os.getpid(),
                          created=process.create_time(), exe=process.exe(),
                          parent_pid=os.getppid(), command=process.cmdline(),
                          sys_executable=sys.executable,prefix=sys.prefix, model_qualified=False)), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
