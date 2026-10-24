import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from local_runtime import runtime_safety as safety,official_runtime as official,standalone_phase as phase


class Standalone(unittest.TestCase):
    def test_exact_standalone_root_does_not_claim_server_or_other_command(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            command=[str(Path(folder)/'strata-vision-hip.exe'),'--list-devices','--require-hip']
            path.write_text(json.dumps(dict(phase='vision-probe',commands=[command])),encoding='utf-8')
            self.assertTrue(safety.standalone_command(command,str(path)))
            self.assertFalse(safety.standalone_command(command+['--gpu'],str(path)))
            self.assertFalse(safety.server_command(command,str(path)))
            self.assertFalse(safety.allowed_child(Path(command[0]),command+['--gpu'],str(path)))
            self.assertTrue(safety.allowed_child(Path(command[0]),command,str(path)))

    def test_standalone_launch_keeps_popen_when_observer_construction_fails(self):
        process=mock.Mock(pid=123);retained={}
        value=dict(config='config',suite='vision-probe',environment={'fixed':'yes'})
        cfg=dict(commands=[['exe','--list-devices']],cwd='cwd',log='log',phase='vision-probe')
        with mock.patch.object(official.manifest,'verify',return_value=value),\
             mock.patch.object(official.manifest,'_verify_authority',return_value=value),\
             mock.patch.object(official.manifest,'read_json',return_value=cfg),\
             mock.patch.object(official,'standalone_environment',return_value={'fixed':'yes'}),\
             mock.patch.object(official.checked_job,'ensure_parent_job'),\
             mock.patch.object(official.checked_job,'require_child'),\
             mock.patch.object(safety,'save'),\
             mock.patch.object(official.subprocess,'Popen',return_value=process),\
             mock.patch.object(official,'SpawnObserver',side_effect=KeyboardInterrupt),\
             mock.patch('builtins.open',mock.mock_open()),\
             self.assertRaises(official.LaunchFailure) as raised:
            official.start_standalone('manifest','sha',retained=retained)
        self.assertIs(raised.exception.process,process)
        self.assertIs(retained['process'],process)
        self.assertTrue(retained['spawn_possible'])

    def test_job_failure_is_zero_spawn_and_no_pending_interlock(self):
        retained={}
        value=dict(config='config',suite='vision-probe',environment={'fixed':'yes'})
        cfg=dict(commands=[['exe','--list-devices']],cwd='cwd',log='log',phase='vision-probe')
        with mock.patch.object(official.manifest,'verify',return_value=value),\
             mock.patch.object(official.manifest,'_verify_authority',return_value=value),\
             mock.patch.object(official.manifest,'read_json',return_value=cfg),\
             mock.patch.object(official,'standalone_environment',return_value={}),\
             mock.patch.object(official.checked_job,'ensure_parent_job',side_effect=RuntimeError('zero spawn')),\
             mock.patch.object(safety,'save') as save,\
             mock.patch.object(official.subprocess,'Popen') as spawn,\
             self.assertRaisesRegex(RuntimeError,'zero spawn'):
            official.start_standalone('manifest','sha',retained=retained)
        spawn.assert_not_called();save.assert_not_called()
        self.assertFalse(retained.get('spawn_possible'))

    def test_probe_unknown_or_deadline_stops_without_http_or_extra_process(self):
        for unknown,clock in (([dict(pid=999)],[0,1]),([],[0,31])):
            with self.subTest(unknown=unknown),tempfile.TemporaryDirectory() as folder:
                path=Path(folder);(path/'native-0.log').write_text('',encoding='utf-8')
                state={};process=mock.Mock();process.poll.return_value=None
                observer=mock.Mock();observer.snapshot.return_value=dict(identities=[],unknown=unknown,errors=[])
                with mock.patch.object(safety,'save'),mock.patch.object(safety,'get_json') as http,\
                     mock.patch.object(phase.gpu_observation,'loaded_modules',return_value=[]),\
                     mock.patch.object(phase.time,'monotonic',side_effect=clock),\
                     self.assertRaises((RuntimeError,TimeoutError)):
                    phase.wait_probe(process,observer,state,mock.Mock(),dict(config=str(path/'cfg'),dependencies={}),dict())
                http.assert_not_called()

    def test_probe_missing_standard_loader_keeps_raw_and_refuses_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'native-0.log').write_text('DEVICE HIP HIP0 R9700 PCI=0000:41:00.0\n',encoding='utf-8')
            process=mock.Mock(returncode=0);process.poll.return_value=0
            observer=mock.Mock();observer.snapshot.return_value=dict(identities=[],unknown=[],errors=[])
            observer.finish_standalone.return_value=observer.snapshot.return_value
            result={}
            with mock.patch.object(safety,'save'),self.assertRaisesRegex(RuntimeError,'standard loader snapshot'):
                phase.wait_probe(process,observer,{},mock.Mock(),dict(config=str(path/'cfg')),result)
            self.assertIn('DEVICE HIP',result['native_log'])
            self.assertNotIn('identity',result)

    def test_normal_exit_waits_for_all_saved_gone_before_sticky_failure_proof(self):
        from local_runtime import evaluate_r9700 as runner
        retained=dict(state=dict(owned_identities=[dict(pid=7,created=1)]))
        with mock.patch.object(safety,'process_identity_status',return_value=safety.IdentityStatus('verified')),\
             mock.patch.object(safety,'process_presence',return_value='present'),\
             mock.patch.object(runner,'pending_exit_proof') as proof:
            self.assertFalse(phase.native_exit_proof(retained)['complete'])
            proof.assert_not_called()
        with mock.patch.object(safety,'process_identity_status',return_value=safety.IdentityStatus('gone')),\
             mock.patch.object(safety,'process_presence',return_value='gone'),\
             mock.patch.object(runner,'pending_exit_proof',return_value=dict(complete=True)) as proof:
            self.assertTrue(phase.native_exit_proof(retained)['complete'])
            proof.assert_called_once_with(retained)

    def test_standalone_config_edit_cannot_expand_cleanup_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg=root/'cfg.json';path=root/'manifest.json'
            cfg.write_text('{"phase":"vision-probe","commands":[["fixed"]]}',encoding='utf-8')
            value=dict(suite='vision-probe',config=str(cfg),config_sha256=official.manifest.digest(cfg))
            path.write_text(json.dumps(value),encoding='utf-8')
            state=dict(config=str(cfg),manifest=str(path),manifest_sha256=official.manifest.digest(path))
            safety.standalone_authority(state)
            cfg.write_text('{"phase":"vision-probe","commands":[["fixed"],["foreign"]]}',encoding='utf-8')
            with self.assertRaises(safety.OwnershipUnverifiable):safety.standalone_authority(state)

    def test_capture_unknown_and_known_birth_survive_later_metadata_loss_and_root_exit(self):
        import psutil
        process=mock.Mock(pid=1);process.poll.return_value=0
        observer=official.SpawnObserver(process,'fixture')
        observer.data=dict(created=10,identities=[dict(pid=1,created=10,exe='root')],unknown=[],errors=[])
        parent=mock.Mock(pid=1);parent.cmdline.return_value=['fixed'];parent.create_time.return_value=10;parent.exe.return_value='root'
        known=mock.Mock(pid=2);known.create_time.return_value=11;known.exe.return_value='known'
        missing=mock.Mock(pid=3);missing.create_time.side_effect=psutil.NoSuchProcess(3)
        def children(*args,**kwargs):
            kwargs['unrecognized'].append(mock.Mock(pid=99))
            kwargs['errors'].append(dict(action='partial_inspection',error_type='AccessDenied'))
            return [known,missing]
        with mock.patch.object(official.psutil,'Process',return_value=parent),\
             mock.patch.object(safety,'server_command',return_value=False),\
             mock.patch.object(safety,'standalone_command',return_value=True),\
             mock.patch.object(safety,'descendants',side_effect=children),\
             self.assertRaises(psutil.NoSuchProcess):
            observer.capture()
        data=observer.snapshot()
        self.assertIn(dict(pid=2,created=11,exe='known'),data['identities'])
        self.assertEqual(data['unknown'],[dict(pid=99)])
        self.assertEqual(len(data['errors']),2)
        self.assertEqual(observer.finish_standalone(),data)

    def test_known_native_root_exit_before_any_new_observation_is_expected(self):
        import psutil
        observer=official.SpawnObserver(mock.Mock(pid=1,poll=mock.Mock(return_value=0)),'fixture')
        observer.data=dict(created=10,identities=[dict(pid=1,created=10,exe='root')],unknown=[],errors=[])
        with mock.patch.object(official.psutil,'Process',side_effect=psutil.NoSuchProcess(1)),\
             mock.patch.object(official.manifest,'read_json',return_value=dict(phase='vision-probe')):
            observer.capture()
        self.assertEqual(observer.snapshot()['errors'],[])


if __name__=='__main__':unittest.main()
