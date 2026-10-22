"""One CPU observation, collection success is NOT a foreground Job gate PASS."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from local_runtime import manifest,runtime_safety as safety


class HandleObservation(unittest.TestCase):
    @unittest.skipUnless(all((manifest.DATA/'records'/n).is_file() for n in ('cli-operation.lock','runtime.lock')),'private original shared-lock observation prerequisites not distributed')
    def test_collect_one_authorized_parent_death_observation(self):
        output=manifest.LOCAL/'records/checked-job-handle-proof-1.json'
        if output.exists():
            self.skipTest('Authorized one-shot already recorded; no repeated parent kill')
        with tempfile.TemporaryDirectory(dir=manifest.LOCAL/'records') as folder:
            root=Path(folder);site=str(Path(sys.prefix)/'Lib/site-packages')
            def command(module,*args):
                code='import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module(sys.argv.pop(1),run_name="__main__")'
                return [str(Path(sys.base_prefix)/'python.exe'),'-B','-X','utf8','-c',code,site,module,*map(str,args)]
            parent=subprocess.Popen(command('local_runtime.tests.checked_job_fixture','parent',root),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            probe=None
            def wait(path,process):
                end=time.monotonic()+12
                while not path.exists():
                    if process.poll() is not None:
                        self.fail('CPU observation process failed: '+str(process.communicate()))
                    self.assertLess(time.monotonic(),end)
                    time.sleep(.01)
            try:
                wait(root/'ready.json',parent)
                probe=subprocess.Popen(command('local_runtime.tests.checked_job_handle_fixture',root),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                wait(root/'handles-ready.json',probe)
                parent.terminate();parent.wait(8)  # Exact retained test-owned manager only.
                out,err=probe.communicate(timeout=10)
                self.assertEqual(probe.returncode,0,(out,err))
                proof=json.loads((root/'handle-proof.json').read_text())
                self.assertEqual(proof['lock_bytes_before'],proof['lock_bytes_after'])
                output.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
                print(proof['decision'],flush=True)
            finally:
                if parent.poll() is None: parent.terminate();parent.wait(8)
                if probe is not None and probe.poll() is None: probe.wait(10)
                if (root/'ready.json').exists():
                    rows=json.loads((root/'ready.json').read_text())['cohort']
                    end=time.monotonic()+8
                    while any(safety.process_identity_status(row).status!='gone' or safety.process_presence(row['pid'])!='gone' for row in rows):
                        self.assertLess(time.monotonic(),end,'CPU observation cohort not independently gone')
                        time.sleep(.02)


if __name__=='__main__': unittest.main()
