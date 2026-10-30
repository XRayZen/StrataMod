"""Windows token defaults: real child identity and file privacy in a disposable process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROOF = r'''
import ctypes, json, os, subprocess, sys
from ctypes import wintypes as w
from pathlib import Path
from strata_control import private_files as pf, procs
from tools import strata_mcp as manager

def token_dacl():
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.InitializeSecurityDescriptor.argtypes = [ctypes.c_void_p, w.DWORD]
    adv.SetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, w.BOOL, ctypes.c_void_p, w.BOOL]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), ctypes.c_void_p]
    handle = w.HANDLE()
    assert adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(handle))
    try:
        size = w.DWORD()
        adv.GetTokenInformation(handle, 6, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        assert adv.GetTokenInformation(handle, 6, data, size, ctypes.byref(size))
        acl = ctypes.c_void_p.from_buffer(data).value
        sd = ctypes.create_string_buffer(64)
        assert adv.InitializeSecurityDescriptor(sd, 1)
        assert adv.SetSecurityDescriptorDacl(sd, True, acl, False)
        text = w.LPWSTR()
        assert adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 4, ctypes.byref(text), None)
        try:
            return text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(handle)

def child(label, record=False):
    proc = subprocess.Popen([sys.executable, '-c',
        "import sys; print('READY', flush=True); sys.stdin.readline()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == 'READY'
        identity = manager.proc_identity(proc.pid)
        token = procs.start_token(proc.pid)
        print(label, 'identity', identity, 'token', token, flush=True)
        assert identity is not None, 'new child cannot be queried after adopting token defaults'
        assert token is not None, 'new child has no independently verified birth token'
        assert manager.proc_identity(proc.pid) == identity
        if record:
            assert procs.write_record(proc.pid, 'vision') == token
            saved = json.loads((procs.procs_dir() / f'{proc.pid}.json').read_text())
            assert (saved['pid'], saved['token'], saved['parent']['pid']) == (proc.pid, token, os.getpid())
        proc.stdin.write('QUIT\n')
        proc.stdin.flush()
        assert proc.wait(timeout=10) == 0
        assert manager.proc_identity(proc.pid) is None
        assert procs.start_token(proc.pid) is None
        if record:
            procs.drop_record(proc.pid, token)
            assert not (procs.procs_dir() / f'{proc.pid}.json').exists()
        print(label, 'record/exit proof complete', flush=True)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        proc.stdin.close()
        proc.stdout.close()

print('before DACL', token_dacl(), flush=True)
child('before')
assert pf.adopt_user_defaults()
assert pf.adopt_user_defaults(), 'adoption must remain idempotent'
after = token_dacl()
print('after DACL', after, flush=True)
child('after', record=True)
sid = pf.current_user_sid()
assert after == f'D:(A;;GA;;;{sid})(A;;GA;;;SY)(A;;GA;;;BA)', after
folder = pf.private_mkdir(Path(os.environ['LOCALAPPDATA']) / 'private-files')
assert pf.is_private(folder)
path = folder / 'owned.json'
path.write_text('{}')
pf.restrict_to_current_user(path)
assert path.read_text() == '{}'
assert pf.is_private(path)
assert pf.dacl_sddl(path) == f'D:PAI(A;;FA;;;{sid})'
print('same three principals; owner-only file/directory privacy preserved', flush=True)
'''


@unittest.skipUnless(os.name == 'nt', 'Windows token DACL and process identity')
class TokenDefaults(unittest.TestCase):
    def test_adoption_preserves_real_child_identity_record_exit_and_private_files(self):
        with tempfile.TemporaryDirectory(prefix='token-defaults-') as folder:
            env = dict(os.environ, LOCALAPPDATA=folder, APPDATA=folder, XDG_STATE_HOME=folder,
                       PYTHONPATH=os.pathsep.join(filter(None, (str(ROOT), os.environ.get('PYTHONPATH')))))
            result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', textwrap.dedent(PROOF)],
                                    env=env, cwd=folder, capture_output=True, text=True, encoding='utf-8', timeout=30)
            print(result.stdout, end='')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
