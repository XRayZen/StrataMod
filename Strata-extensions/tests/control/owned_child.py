"""Exclusively test-owned process/listener fixture; never an official engine."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import psutil

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--snapshot');p.add_argument('--ready');p.add_argument('--release',required=True);p.add_argument('--child',action='store_true');p.add_argument('--unknown-child',action='store_true');a=p.parse_args()
    release=Path(a.release)
    if a.child:
        while not release.exists():time.sleep(.02)
        return
    path=Path(__file__).resolve().parents[2]/'control/bootstrap_binding.py';spec=importlib.util.spec_from_file_location('binding',path);b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
    snapshot=json.loads(Path(a.snapshot).read_text(encoding='utf-8-sig'))
    proc=psutil.Process();q=proc.parent();parents=[dict(pid=q.pid,created=q.create_time(),exe=q.exe())]
    b.verify_bootstrap(snapshot,proc.cmdline(),parents)
    command=[sys.executable,'-B','-m','serve.server','--config',a.config,'--child','--release',a.release]
    if a.unknown_child:command=[sys.executable,'-B','-c','import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); exec("while not p.exists(): time.sleep(.02)")',a.release]
    child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);listener.bind(('127.0.0.1',0));listener.listen()
            t=snapshot['target'];hello=dict(scope='t24-owner-fixture',generation_qualified=False,snapshot_id=snapshot['snapshot_id'],attempt=snapshot['attempt'],runtime_epoch=t['runtime_epoch'],bundle_id=t['bundle_id'],model=t['model_id'],context=t['context'],pid=proc.pid,created=proc.create_time(),exe=proc.exe(),port=listener.getsockname()[1])
            ready=Path(a.ready);temporary=ready.with_suffix('.tmp');temporary.write_text(json.dumps(hello),encoding='utf-8');temporary.replace(ready)
            while not release.exists():time.sleep(.02)
    finally:
        if child.poll() is None:child.terminate()
        child.wait(timeout=8)
if __name__=='__main__':main()


