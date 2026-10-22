"""Checked parent-lifetime Windows Job for this foreground candidate only."""
import ctypes
import os
from pathlib import Path
from ctypes import wintypes

from serve import winjob

_parent_job = None


def _api():
    if os.name != 'nt':
        raise RuntimeError('Checked candidate Job requires Windows')
    kernel = winjob._k32
    kernel.QueryInformationJobObject.argtypes = (wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD,wintypes.LPVOID)
    kernel.GetHandleInformation.argtypes = (wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD))
    kernel.IsProcessInJob.argtypes = (wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL))
    kernel.OpenProcess.argtypes = (wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel


def membership(handle,job=None):
    job = _parent_job if job is None else job
    if not job:
        raise RuntimeError('No checked parent Job')
    value = wintypes.BOOL()
    if not _api().IsProcessInJob(handle,job,ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return bool(value.value)


def ensure_parent_job():
    """Assign before any child spawn. Keep the non-inherited handle until OS exit.

    Closing it here would also kill this assigned parent. It is deliberately not
    a context-manager close: normal return requires prior independent child exit.
    """
    global _parent_job
    kernel = _api()
    if _parent_job is None:
        job = winjob._make_job()
        if not job:
            raise RuntimeError('Checked Job creation/configuration failed; zero spawn')
        assigned = False
        try:
            limits = winjob._ExtendedLimits()
            flags = wintypes.DWORD()
            if not kernel.QueryInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.GetHandleInformation(job,ctypes.byref(flags)):
                raise ctypes.WinError(ctypes.get_last_error())
            if limits.BasicLimitInformation.LimitFlags != 0x2000 or flags.value & 1:
                raise RuntimeError('Checked Job must kill on close, forbid breakaway and have a non-inherited handle')
            if not kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess()):
                raise ctypes.WinError(ctypes.get_last_error())
            assigned = True
            _parent_job = job  # Never close an assigned parent Job in Python.
            if not membership(kernel.GetCurrentProcess(),job):
                raise RuntimeError('Checked parent Job membership not confirmed; zero spawn')
        finally:
            if not assigned:
                kernel.CloseHandle(job)
    if not membership(kernel.GetCurrentProcess()):
        raise RuntimeError('Parent left the checked Job; zero spawn')
    return dict(kill_on_close=True,handle_inherited=False,breakaway_allowed=False,parent_member=True)


def require_child(process):
    if not membership(int(process._handle)):
        raise RuntimeError('Candidate child is not a member of the checked parent Job')
    return True


def membership_pid(pid):
    kernel = _api()
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return membership(handle)
    finally:
        kernel.CloseHandle(handle)


def active_members():
    """Read the original checked foreground Job; never create or close a Job."""
    if not _parent_job:raise RuntimeError('No checked parent Job')
    kernel=_api();size=4096
    while True:
        buffer=ctypes.create_string_buffer(size)
        if kernel.QueryInformationJobObject(_parent_job,3,buffer,size,None):break
        error=ctypes.get_last_error()
        if error not in (122,234) or size>=16*1024*1024:raise ctypes.WinError(error)
        size*=2
    assigned=ctypes.c_ulong.from_buffer(buffer,0).value
    count=ctypes.c_ulong.from_buffer(buffer,4).value
    if count!=assigned or 8+count*ctypes.sizeof(ctypes.c_size_t)>size:
        raise RuntimeError('Checked Job member list incomplete')
    members=list((ctypes.c_size_t*count).from_buffer(buffer,8))
    if any(not pid for pid in members) or len(set(members))!=count:
        raise RuntimeError('Checked Job member list invalid')
    return set(members)


def _birth_windows(row):
    from . import runtime_safety as safety
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, row['pid'])
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return dict(status='absent', winerror=87)
        raise ctypes.WinError(error)
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times]):
            raise ctypes.WinError(ctypes.get_last_error())
        created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)/10**7 - 11644473600
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        wait = kernel.WaitForSingleObject(handle, 0)
        if wait not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        value = dict(created=created, exit_code=code.value, signaled=wait == 0)
        name = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(name))
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
            error=ctypes.WinError(ctypes.get_last_error())
            if abs(created-row['created']) < safety.IDENTITY_TOLERANCE and wait == 0:
                return dict(value,status='exited',exe=None,image_unavailable=dict(
                    operation='QueryFullProcessImageNameW',error_type=type(error).__name__,
                    winerror=getattr(error,'winerror',None),errno=getattr(error,'errno',None)))
            raise error
        value['exe']=name.value
        if abs(created-row['created']) >= safety.IDENTITY_TOLERANCE:
            return dict(value, status='different_birth')
        if row.get('exe') and Path(name.value).resolve() != Path(row['exe']).resolve():
            return dict(value, status='unverifiable', error_type='SameBirthExecutableMismatch')
        if wait == 0:
            return dict(value, status='exited')
        if code.value != 259:
            return dict(value, status='unverifiable', error_type='ExitCodeWaitDisagreement')
        return dict(value, status='alive')
    finally:
        kernel.CloseHandle(handle)


def original_birth_exit(row):
    from . import runtime_safety as safety
    # The existing identity validator rejects malformed PID/birth metadata.
    identity = safety.process_identity_status(row)
    if identity.status == 'unverifiable' and identity.reason == 'Invalid saved process identity.':
        raise ValueError(identity.reason)
    try:
        windows = _birth_windows(row)
    except Exception as error:
        windows = dict(status='unverifiable', error_type=type(error).__name__,
                       winerror=getattr(error, 'winerror', None), errno=getattr(error, 'errno', None))
    status = windows['status']
    original_gone = ((identity.status == 'gone' and status in ('absent', 'different_birth', 'exited'))
                     or (identity.status == 'verified' and status == 'exited'))
    return dict(pid=row['pid'], saved_created=row['created'], identity_status=identity.status,
                windows=windows, original_gone=original_gone)
