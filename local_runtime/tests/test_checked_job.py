"""Checked parent Job and no-breakaway launch, without GPU or HTTP."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock

from local_runtime import checked_job,manifest,runtime_safety as safety
from local_runtime import official_runtime as official


class CheckedJobTests(unittest.TestCase):
    def test_optional_native_launcher_disables_breakaway_without_changing_default(self):
        module = official.native()
        with tempfile.TemporaryDirectory(dir=manifest.LOCAL/'records') as folder, \
                patch.object(module.subprocess,'Popen') as spawn:
            module.spawn_detached(['CPU-only'],Path(folder),Path(folder)/'log',{},allow_breakaway=False)
            self.assertFalse(spawn.call_args.kwargs['creationflags'] & module.CREATE_BREAKAWAY_FROM_JOB)
            module.spawn_detached(['CPU-only'],Path(folder),Path(folder)/'log',{})
            self.assertTrue(spawn.call_args.kwargs['creationflags'] & module.CREATE_BREAKAWAY_FROM_JOB)

    def test_job_creation_failure_is_explicit_zero_spawn(self):
        with patch.object(checked_job,'_parent_job',None),patch.object(checked_job.winjob,'_make_job',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'zero spawn'):
                checked_job.ensure_parent_job()

    @unittest.skipUnless(all((manifest.DATA/'records'/n).is_file() for n in ('cli-operation.lock','runtime.lock')),'private original shared-lock integration prerequisites not distributed')
    def test_parent_death_cohort_and_old_lock_boundary_cpu_proof(self):
        with tempfile.TemporaryDirectory(dir=manifest.LOCAL/'records') as folder:
            root = Path(folder)
            site = str(Path(sys.prefix)/'Lib/site-packages')
            boot = ('import sys,runpy;sys.path.insert(0,sys.argv.pop(1));'
                    'runpy.run_module("local_runtime.tests.checked_job_fixture",run_name="__main__")')
            cmd = [str(Path(sys.base_prefix)/'python.exe'),'-B','-X','utf8','-c',boot,site]
            parent = subprocess.Popen([*cmd,'parent',str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            probe = None
            try:
                end=time.monotonic()+12
                while not (root/'ready.json').exists():
                    if parent.poll() is not None:
                        out,err=parent.communicate()
                        self.fail('Checked Job zero-spawn failure: '+out+err)
                    self.assertLess(time.monotonic(),end)
                    time.sleep(.02)
                ready=json.loads((root/'ready.json').read_text())
                self.assertTrue(all(row['member'] for row in ready['cohort']))
                probe=subprocess.Popen([*cmd,'probe',str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                end=time.monotonic()+12
                while not (root/'probing').exists():
                    if probe.poll() is not None:
                        self.fail('CPU boundary probe failed: '+str(probe.communicate()))
                    self.assertLess(time.monotonic(),end)
                    time.sleep(.01)
                # Exact retained test-owned parent only. Kill-on-close must end
                # its complete CPU-only child/grandchild cohort.
                parent.terminate();parent.wait(8)
                out,err=probe.communicate(timeout=8)
                self.assertEqual(probe.returncode,0,(out,err))
                result=json.loads((root/'proof.json').read_text())
                (manifest.LOCAL/'records/checked-job-cpu-proof.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                self.assertTrue(result['all_cohort_gone_at_old_boundary'],result)
            finally:
                # The Job must reap every known descendant, including fixture
                # failures. Never kill an unknown external process here.
                if parent.poll() is None:
                    parent.terminate();parent.wait(8)
                if probe is not None and probe.poll() is None:
                    probe.wait(8)
                if (root/'ready.json').exists():
                    rows=json.loads((root/'ready.json').read_text())['cohort']
                    end=time.monotonic()+8
                    while any(safety.process_presence(row['pid'])!='gone' for row in rows):
                        self.assertLess(time.monotonic(),end,'Job did not reap CPU fixture cohort')
                        time.sleep(.02)


if __name__=='__main__': unittest.main()
