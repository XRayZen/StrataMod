"""Finite CPU parent/child/grandchild abnormal-exit proof; never native/GPU/HTTP."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

from local_runtime import checked_job,evaluate_r9700 as runner,manifest,runtime_safety as safety


def identity(process):
    return dict(pid=process.pid,created=process.create_time(),exe=process.exe(),command=process.cmdline())


def command(action,root):
    return [sys.executable,'-B','-X','utf8',__file__,action,str(root)]


def parent(root):
    status=checked_job.ensure_parent_job()
    # Site-packages remains available to each direct base-Python CPU worker.
    env=dict(os.environ,PYTHONPATH=os.pathsep.join(sys.path))
    before={name:manifest.digest(manifest.DATA/'records'/name) for name in ('cli-operation.lock','runtime.lock')}
    with runner.shared_operation():
        child=subprocess.Popen(command('child',root),close_fds=True,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        checked_job.require_child(child)
        end=time.monotonic()+8
        while not (root/'grandchild.json').exists():
            if child.poll() is not None or time.monotonic()>end:
                raise RuntimeError('CPU fixture child did not establish its grandchild')
            time.sleep(.01)
        rows=[identity(psutil.Process(child.pid)),json.loads((root/'grandchild.json').read_text())]
        for row in rows: row['member']=checked_job.membership_pid(row['pid'])
        (root/'ready.json').write_text(json.dumps(dict(parent=identity(psutil.Process()),job=status,cohort=rows,lock_bytes_before=before)))
        # The outer test owns the exact Popen and intentionally terminates this
        # manager, exercising OS handle close rather than graceful shutdown.
        while True: time.sleep(1)


def child(root):
    process=subprocess.Popen(command('grandchild',root),close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
    (root/'grandchild.json').write_text(json.dumps(identity(psutil.Process(process.pid))))
    while True: time.sleep(1)


def probe(root):
    ready=json.loads((root/'ready.json').read_text())
    before=ready['lock_bytes_before']
    (root/'probing').touch()
    blocked=0;end=time.monotonic()+10
    while True:
        try:
            with runner.shared_operation():
                rows=[dict(row,identity_status=safety.process_identity_status(row).status,
                           presence=safety.process_presence(row['pid'])) for row in ready['cohort']]
                result=dict(job=ready['job'],cohort_at_first_old_lock_boundary=rows,blocked_attempts=blocked,
                            all_cohort_gone_at_old_boundary=all(row['identity_status']=='gone' and row['presence']=='gone' for row in rows),
                            lock_bytes_before=before)
            result['lock_bytes_after']={name:manifest.digest(manifest.DATA/'records'/name) for name in before}
            (root/'proof.json').write_text(json.dumps(result,indent=2))
            return
        except RuntimeError:
            blocked+=1
            if time.monotonic()>end: raise
            time.sleep(.001)


if __name__=='__main__':
    action,root=sys.argv[1],Path(sys.argv[2])
    if action=='parent': parent(root)
    elif action=='child': child(root)
    elif action=='grandchild':
        while True: time.sleep(1)
    elif action=='probe': probe(root)
