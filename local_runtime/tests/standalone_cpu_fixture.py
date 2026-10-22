"""CPU-only adapter/Job/observer/normal-exit proof; never an image receipt."""
import json
from pathlib import Path
import sys
import time
from unittest import mock
from local_runtime import manifest,official_runtime as official,runtime_safety as safety,evaluate_r9700 as runner,standalone_phase


def main(folder):
    folder=Path(folder)
    sentinel=folder/'quit'
    command=[str(manifest.PYTHON),'-B','-X','utf8','-c',
             "import pathlib,time; print('CPU ONLY READY',flush=True)\nwhile not pathlib.Path("+repr(str(sentinel))+").exists(): time.sleep(.02)"]
    config=folder/'config.json'
    cfg=dict(phase='vision-probe',commands=[command],cwd=str(manifest.ROOT),log=str(folder/'cpu.log'),ordinal=None)
    config.write_text(json.dumps(cfg),encoding='utf-8')
    value=dict(suite='vision-probe',config=str(config),config_sha256=manifest.digest(config),environment={})
    authority=folder/'manifest.json'
    authority.write_text(json.dumps(value),encoding='utf-8')
    retained={};result=dict(scope='CPU-only isolated config; real adapter/Job/old locks; no SDK/GPU/API')
    with mock.patch.object(manifest,'verify',return_value=value),\
         mock.patch.object(manifest,'_verify_authority',return_value=value),\
         mock.patch.object(official,'standalone_environment',return_value=dict(runner.os.environ)),\
         mock.patch.object(safety,'STATE',folder/'state.json'),\
         runner.shared_operation(),runner.candidate_interrupts(retained):
        process,observer,state=official.start_standalone(authority,manifest.digest(authority),retained=retained)
        result['owned_before_quit']=bool(safety.owned(state))
        result['job_member']=official.checked_job.require_child(process)
        # Exact cooperative CPU root; no termination request and no abnormal
        # parent kill/atomic-boundary trial is performed by this fixture.
        sentinel.write_text('CPU fixture cooperative exit',encoding='utf-8')
        process.wait(timeout=5)
        state['spawn_observation']=observer.finish_standalone()
        result['returncode']=process.returncode
        deadline=time.monotonic()+3
        while True:
            proof=standalone_phase.native_exit_proof(retained)
            if proof['complete'] or time.monotonic()>deadline:break
            time.sleep(.05)
        result['proof']=proof
        if not proof['complete']:
            # This test-owned retained handle has already signaled exit. Record
            # metadata status before closing, then independently inspect again.
            process._handle.Close()
            result['after_reaped_handle_close']=standalone_phase.native_exit_proof(retained)
        else:
            process._handle.Close()
        result['cohort']=state['owned_identities']
        (folder/'proof.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        if not result.get('after_reaped_handle_close',proof)['complete']:
            raise RuntimeError('CPU fixture independent exit remains unverified')
    (folder/'proof.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main(sys.argv[1])
