"""Official no-site CLI smoke contracts; no engine or dependency acquisition."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

TOOLS=Path(__file__).resolve().parents[2]/'tools'
sys.path.insert(0,str(TOOLS))
try:
    import minimal_cli_smoke as smoke
finally:
    sys.path.remove(str(TOOLS))

class OfficialCliSmoke(unittest.TestCase):
    def test_one_json_record_with_expected_exit(self):
        result=subprocess.CompletedProcess([],5,'{"schema_version":1,"ok":false}','')
        self.assertFalse(smoke._record(result,5)['ok'])

    def test_wrong_exit_or_stderr_is_not_a_json_success(self):
        for result in (subprocess.CompletedProcess([],1,'{"schema_version":1}',''),
                       subprocess.CompletedProcess([],0,'{"schema_version":1}','unexpected')):
            with self.subTest(result=result),self.assertRaises(RuntimeError):smoke._record(result,0)

    def test_malformed_extra_or_nonobject_json_is_rejected(self):
        for text in ('', '{}', '[]', '{"schema_version":1}{}', 'not JSON'):
            with self.subTest(text=text),self.assertRaises(RuntimeError):
                smoke._record(subprocess.CompletedProcess([],0,text,''),0)

    def test_no_site_subprocess_does_not_inherit_python_path_or_install(self):
        with mock.patch.dict(os.environ,{'PYTHONPATH':'fixture','PYTHONHOME':'fixture'}), \
                mock.patch.object(smoke.subprocess,'run') as run:
            smoke._run('--help')
        args,kwargs=run.call_args
        self.assertEqual(args[0],[sys.executable,'-S','--help'])
        self.assertNotIn('PYTHONPATH',kwargs['env']);self.assertNotIn('PYTHONHOME',kwargs['env'])
        self.assertEqual(kwargs['env']['PYTHONNOUSERSITE'],'1')
        self.assertEqual(kwargs['timeout'],20);self.assertFalse(kwargs['check'])