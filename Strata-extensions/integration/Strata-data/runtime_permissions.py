"""Read identities and integrity from handles already owned by this process."""
import ctypes
from ctypes import wintypes


def _apis():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessId.argtypes, kernel.GetProcessId.restype = [wintypes.HANDLE], wintypes.DWORD
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


def handle_identity(handle):
    kernel = _apis()
    handle = wintypes.HANDLE(int(handle))
    created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                  ctypes.byref(system), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    size, path = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
    if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return dict(pid=kernel.GetProcessId(handle),
                created=((created.dwHighDateTime << 32) | created.dwLowDateTime) / 10000000 - 11644473600,
                exe=path.value)


def integrity_rid(handle=None):
    kernel = _apis()
    process = kernel.GetCurrentProcess() if handle is None else int(handle)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
    advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    token, size = wintypes.HANDLE(), wintypes.DWORD()
    if not advapi.OpenProcessToken(process, 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 25, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        count = advapi.GetSidSubAuthorityCount(sid)[0]
        if not count:
            raise RuntimeError('Process integrity SID has no RID')
        return advapi.GetSidSubAuthority(sid, count - 1)[0]
    finally:
        kernel.CloseHandle(token)

