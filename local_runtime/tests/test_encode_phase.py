"""Finite encoder exchanges with fake stdio, never native/SDK/GPU."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import contextlib
import json
from local_runtime import standalone_phase as phase,image_phase,manifest


class EncodePhase(unittest.TestCase):
    def test_three_starts_are_strictly_separated_by_complete_exit_and_failure_never_starts_next(self):
        from local_runtime import evaluate_r9700 as runner,official_runtime as official,gpu_observation
        for fail in (False,'cohort','reader','reader-save'):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
                directory=Path(folder)
                value=dict(suite='vision-encode',config=str(directory/'config.json'),max_starts=3,max_encodes=6,max_posts=0,dependencies={})
                calls=[];retained_states=[];held=[False]
                @contextlib.contextmanager
                def locks():
                    held[0]=True
                    try:yield
                    finally:held[0]=False
                def hold(retained,result,directory):
                    self.assertTrue(held[0]);calls.append('barrier')
                    self.assertIsNotNone(retained['process'])
                    self.assertIsNotNone(retained['observer'])
                    retained['state']['cleanup_pending']=False
                def start(path,sha,*,retained,index,before_spawn):
                    before_spawn();calls.append('start'+str(index))
                    state=dict(pid=index+100,created=1,owned_identities=[],cleanup_pending=True)
                    retained.update(process=Mock(),observer=Mock(),state=state,spawn_possible=True)
                    retained_states.append(state)
                    return retained['process'],retained['observer'],state
                def exchange(process,observer,state,monitor,v,result,index,io,meter):
                    result['encode_count']+=2
                    arm=dict(images=[],valid=True)
                    result['arms'].append(arm)
                    (directory/f'native-{index}.log').write_text('',encoding='utf-8')
                    return arm
                def finish(*args):
                    calls.append('gone'+str(len(retained_states)-1))
                    if fail:raise RuntimeError('cohort not gone')
                    return dict(complete=True)
                for target,name,kwargs in (
                    (manifest,'_verify_authority',dict(return_value=value)),(manifest,'verify',dict(return_value=value)),
                    (manifest,'image_reference',dict(return_value=dict(pci='07'))),
                    (runner,'shared_operation',dict(side_effect=locks)),(runner,'production_inactive',dict()),
                    (runner,'preflight_budget',dict(return_value={})),(runner,'MemoryMonitor',dict()),
                    (runner,'cleanup_failed_start',dict(side_effect=OSError('cleanup save failed') if fail in ('reader','reader-save') else lambda p,o,s:s.update(cleanup_pending=False))),
                    (runner,'hold_pending_cleanup',dict(side_effect=hold)),
                    (official,'_start_standalone',dict(side_effect=start)),(phase,'encode_exchanges',dict(side_effect=exchange)),
                    (phase,'finish_encoder',dict(side_effect=finish)),(phase,'encode_result',dict()),
                    (phase.safety,'save',dict()),(gpu_observation,'windows_displays',dict()),(gpu_observation,'dxgi_adapters',dict()),
                    (gpu_observation,'select_adapter',dict(return_value=dict(windows=dict(pci='07')))),
                    (gpu_observation,'EncodeMemory',dict()),(gpu_observation,'loaded_modules',dict(return_value=[])),
                    (image_phase,'match_encoder_identity',dict(return_value={})),(image_phase,'probe_modules',dict(return_value={}))):
                    stack.enter_context(patch.object(target,name,**kwargs))
                io=Mock();io.close_reader.return_value=True
                if fail=='reader':io.close_reader.side_effect=SystemExit('reader failed')
                if fail=='reader-save':
                    io.close_reader.return_value=False
                    phase.safety.save.side_effect=OSError('pending save failed')
                stack.enter_context(patch('tools.vision.encode_io.EncodeIO',return_value=io))
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'cohort not gone'):phase.run_encode(directory/'manifest.json','fixed')
                    self.assertEqual(calls,['start0','gone0','barrier'])
                    saved=json.loads((directory/'result.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['status'],'failed');self.assertEqual(saved['start_count'],1)
                else:
                    saved=phase.run_encode(directory/'manifest.json','fixed')
                    self.assertEqual(calls,['start0','gone0','start1','gone1','start2','gone2'])
                    self.assertEqual((saved['start_count'],saved['encode_count'],saved['post_count']),(3,6,0))
    def test_exact_two_encodes_reserve_before_send_and_validate_header_and_ok(self):
        with tempfile.TemporaryDirectory() as folder:
            value=dict(config=str(Path(folder)/'config.json'),max_encodes=6)
            result=dict(encode_count=0,arms=[])
            process,observer,monitor,io,meter=Mock(),Mock(),Mock(),Mock(),Mock()
            process.poll.return_value=None
            io.read_event.side_effect=[dict(kind='ready',width=2560),*[dict(kind='ok',n=2,nx=1,ny=2,ms=1) for _ in range(2)]]
            io.send_encode.side_effect=lambda *args:self.assertEqual(result['encode_count'],io.send_encode.call_count)
            with patch.object(phase,'check_native_live'),patch.object(image_phase,'read_sve',return_value=dict(shape=[2,1,2,2560],sha256='fixed')):
                arm=phase.encode_exchanges(process,observer,{},monitor,value,result,0,io,meter)
            self.assertEqual(result['encode_count'],2)
            self.assertEqual(len(arm['images']),2)
            self.assertEqual(io.send_encode.call_count,2)
            io.send_quit.assert_not_called()  # Loader/PCI capture precedes caller's QUIT.

    def test_wrong_ready_or_ok_shape_or_write_failure_stops_extra_enc(self):
        for kind in ('ready','shape','write','eof'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                value=dict(config=str(Path(folder)/'config.json'),max_encodes=6)
                result=dict(encode_count=0,arms=[]);io=Mock();process=Mock();process.poll.return_value=None
                io.read_event.side_effect=[dict(kind='ready',width=1 if kind=='ready' else 2560),
                                          dict(kind='eof') if kind=='eof' else dict(kind='ok',n=3,nx=1,ny=3,ms=1)]
                if kind=='write':io.send_encode.side_effect=OSError('short write')
                with patch.object(phase,'check_native_live'),patch.object(image_phase,'read_sve',return_value=dict(shape=[2,1,2,2560],sha256='fixed')),\
                     self.assertRaises((RuntimeError,OSError)):
                    phase.encode_exchanges(process,Mock(),{},Mock(),value,result,0,io,Mock())
                self.assertLessEqual(io.send_encode.call_count,1)
                self.assertEqual(len(result['arms']),1)
                self.assertFalse(result['arms'][0]['valid'])

    def test_masked_encoder_identity_is_physical_pci_not_unfiltered_ordinal(self):
        probe=dict(ordinal=1,pci='0000:07:00.0',arch='gfx1201',name='AMD Radeon AI PRO R9700')
        raw='strata-vision: HIP identity logical=0 PCI=0000:07:00.0 arch=gfx1201 name=AMD Radeon AI PRO R9700 mask=1\n'
        self.assertEqual(image_phase.match_encoder_identity(raw,probe)['ordinal'],0)
        with self.assertRaises(RuntimeError):image_phase.match_encoder_identity(raw.replace('07:00.0','03:00.0'),probe)


if __name__=='__main__':unittest.main()
