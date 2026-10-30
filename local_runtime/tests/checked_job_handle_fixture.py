"""One authorized CPU observation; process handles only, never duplicate Job."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import time
import sys

from local_runtime import evaluate_r9700 as runner,manifest,runtime_safety as safety


def observe(root):
    ready=json.loads((root/'ready.json').read_text())
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD);k.OpenProcess.restype=wintypes.HANDLE
    k.CloseHandle.argtypes=(wintypes.HANDLE,)
    k.GetProcessTimes.argtypes=(wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4))
    k.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD);k.WaitForSingleObject.restype=wintypes.DWORD
    k.GetExitCodeProcess.argtypes=(wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD))
    handles=[];births=[];attempts=[]
    try:
        for row in ready['cohort']:
            h=k.OpenProcess(0x00100000|0x1000,False,row['pid'])
            if not h: raise ctypes.WinError(ctypes.get_last_error())
            handles.append((row,h))
            creation,exit,kernel,user=(wintypes.FILETIME() for _ in range(4))
            if not k.GetProcessTimes(h,ctypes.byref(creation),ctypes.byref(exit),ctypes.byref(kernel),ctypes.byref(user)):
                raise ctypes.WinError(ctypes.get_last_error())
            ticks=(creation.dwHighDateTime<<32)|creation.dwLowDateTime
            created=ticks/10000000-11644473600
            if abs(created-row['created'])>=safety.IDENTITY_TOLERANCE:
                raise RuntimeError('Saved birth and retained process handle birth mismatch')
            births.append(dict(row,handle_creation_filetime=ticks,handle_created_unix=created))
        def snapshot():
            output=[]
            for row,h in handles:
                begin=time.monotonic_ns();ctypes.set_last_error(0)
                wait=int(k.WaitForSingleObject(h,0));wait_error=ctypes.get_last_error()
                code=wintypes.DWORD();ctypes.set_last_error(0)
                code_ok=bool(k.GetExitCodeProcess(h,ctypes.byref(code)));code_error=ctypes.get_last_error()
                queried=time.monotonic_ns()
                identity=safety.process_identity_status(row).status
                presence=safety.process_presence(row['pid'])
                output.append(dict(pid=row['pid'],begin_ns=begin,handle_queries_end_ns=queried,
                    end_ns=time.monotonic_ns(),wait_raw=wait,wait_error=wait_error,
                    get_exit_code_ok=code_ok,exit_code_raw=code.value,exit_code_error=code_error,
                    metadata_identity_status=identity,independent_presence=presence))
            return output
        (root/'handles-ready.json').write_text(json.dumps(births))
        end=time.monotonic()+10
        while True:
            before=snapshot();started=time.monotonic_ns()
            try:
                with runner.shared_operation():
                    acquired=time.monotonic_ns();after=snapshot()
                attempt=dict(before=before,attempt_begin_ns=started,acquired_ns=acquired,after=after,acquired=True)
                attempts.append(attempt)
                if any(row['wait_raw']==258 for row in after):
                    decision='FAIL: original child handle still unsignaled after old lock boundary'
                elif any(row['wait_raw']==0xffffffff or not row['get_exit_code_ok'] for row in before+after):
                    decision='INCONCLUSIVE: handle query failed'
                elif all(row['wait_raw']==0 for row in before):
                    decision='ORDER PROVED FOR THIS OBSERVATION: all original handles signaled before first successful old lock attempt'
                else:
                    decision='INCONCLUSIVE: pre-attempt unsignaled to post-acquire signaled interval crosses boundary'
                result=dict(decision=decision,births=births,job=ready['job'],attempts=attempts,
                    lock_bytes_before=ready['lock_bytes_before'],lock_bytes_after={name:manifest.digest(manifest.DATA/'records'/name) for name in ready['lock_bytes_before']},
                    scope='One CPU-only authorized observation. Does not independently authorize foreground serve.')
                (root/'handle-proof.json').write_text(json.dumps(result,indent=2))
                return
            except RuntimeError as error:
                attempts.append(dict(before=before,attempt_begin_ns=started,end_ns=time.monotonic_ns(),acquired=False,error=str(error)))
                if time.monotonic()>end: raise
                time.sleep(.001)
    finally:
        for _,h in handles: k.CloseHandle(h)


if __name__=='__main__': observe(Path(sys.argv[1]))
