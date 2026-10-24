"""Import/lookup contracts of amdVision; no SDK, models or image files."""
import importlib
import inspect
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class ModuleCompatibility(unittest.TestCase):
    def test_old_imports_are_same_modules_and_preserve_patch_globals(self):
        for old,new in (
            ('serve.vision_hip','serve.stratamod.amd_vision.environment'),
            ('serve.vision_request','serve.stratamod.amd_vision.request'),
            ('tools.vision.hip_windows','tools.vision.amd_vision.cli')):
            with self.subTest(module=old):
                a,b=importlib.import_module(old),importlib.import_module(new)
                self.assertIs(a,b)
                with patch.object(a,'__doc__','patched'):
                    self.assertEqual(b.__doc__,'patched')

    def test_public_constructor_and_exception_identity(self):
        from serve import server as s
        from serve.stratamod.amd_vision import request
        self.assertIs(s.ImageRequestFatal,request.ImageRequestFatal)
        self.assertEqual(list(inspect.signature(s.HipImageRequest).parameters),['messages','cancel','vision'])
        self.assertEqual(list(inspect.signature(s.Vision).parameters),['cfg','log','env','lazy'])
        obj=s.HipImageRequest([],None,SimpleNamespace())
        self.assertIs(obj._cancelled_error,s.ClientGone)

    def test_new_modules_import_without_server_cycle(self):
        command=[sys.executable,'-c',
            "import sys; import serve.stratamod.amd_vision.encoder; "
            "import serve.stratamod.amd_vision.request; "
            "import tools.vision.amd_vision.cli; assert 'serve.server' not in sys.modules"]
        result=subprocess.run(command,cwd=Path(__file__).parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_module_and_script_cli_keep_same_help(self):
        root=Path(__file__).parents[1]
        outputs=[]
        for args in (['-m','tools.vision.hip_windows','--help'],['tools/vision/hip_windows.py','--help']):
            result=subprocess.run([sys.executable,*args],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('{build,probe,config}',result.stdout)
            outputs.append(result.stdout.split('positional arguments:')[-1])
        self.assertEqual(*outputs)
        from tools.vision.amd_vision import cli
        self.assertEqual(cli.ROOT,root.resolve())

    def test_standalone_and_module_server_entry(self):
        root=Path(__file__).parents[1]
        for args in (['-m','serve.server','--help'],['serve/server.py','--help']):
            result=subprocess.run([sys.executable,*args],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('--engine',result.stdout)

    def test_new_source_roots_are_bound_without_private_recursion(self):
        from local_runtime import manifest as m
        paths=m.source_files()
        for relative in ('serve/stratamod/__init__.py','serve/stratamod/amd_vision/encoder.py',
                         'serve/stratamod/amd_vision/request.py','serve/stratamod/amd_vision/environment.py',
                         'tools/vision/amd_vision/cli.py','tools/vision/amd_vision/__init__.py'):
            self.assertIn(str(m.ROOT/relative),paths)
        self.assertFalse(any('/records/' in p.replace('\\','/') for p in paths))

    def test_encoder_stop_preserves_original_owner_exception(self):
        from serve import server as s
        v=s.Vision.__new__(s.Vision)
        v.proc=Mock(pid=101);v.proc.poll.return_value=None
        v.proc.kill.side_effect=OSError('test');v.proc.wait.side_effect=subprocess.TimeoutExpired('test',5)
        with self.assertRaises(s.VisionCleanupPending) as caught:v._hip_stop(force=True)
        self.assertIs(caught.exception.vision,v)
        self.assertTrue(v.cleanup_pending)
        self.assertIsNotNone(v.proc)

    def test_checked_image_keeps_owner_normalize_lookup(self):
        from serve import server as s
        v=s.Vision.__new__(s.Vision)
        # Header/parser behavior is exercised by the existing HIP validation suite.
        with patch('serve.stratamod.amd_vision.encoder.checked_image',return_value=b'normalized') as checked:
            self.assertEqual(v.checked_image(b'opaque'),b'normalized')
            checked.assert_called_once_with(v,b'opaque')


if __name__=='__main__':unittest.main()
