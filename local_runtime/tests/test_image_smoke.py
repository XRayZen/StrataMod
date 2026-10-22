"""Image first fixed-flow ownership/evidence, CPU fakes only."""
import copy
import contextlib
import json
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from local_runtime import image_phase as image,evaluate_r9700 as runner,manifest


_actual_smoke_protocol=image.smoke_protocol

def synthetic_protocol():
    # Only the actual protocol's file/hash boundaries are replaced, never a user image.
    with patch.object(manifest,'digest',return_value=image.IMAGES[0][2]), \
         patch.object(Path,'read_bytes',return_value=b'\x89PNG\r\n\x1a\nopaque-non-decodable-synthetic-sentinel'):
        return _actual_smoke_protocol()

def synthetic_rubrics():
    a=dict(people=1,hair=['fixture-hair-a'],top=['fixture-top-a'],scene=['fixture-room-a'],object=['fixture-desk-a'],position=['fixture-position-a'])
    b=dict(people=2,hair=['fixture-hair-b'],top=['fixture-top-b'],scene=['fixture-room-b'],object=['fixture-desk-b'],position=['fixture-position-b'])
    return dict(expected=a,expected_api07=a,expected_webui484=b)


class ImageSmoke(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(image,'smoke_protocol',side_effect=synthetic_protocol))

    def test_actual_webui_bad_display_cannot_pass_using_good_api_answer(self):
        expected=synthetic_rubrics()['expected']
        correct=json.dumps({key:(value[0] if isinstance(value,list) else value) for key,value in expected.items()})
        output=dict(protocol=dict(normal_terminal=True,output_tokens=12,text=correct),final_answer=dict(text='画像を読み取れません'))
        with self.assertRaisesRegex(RuntimeError,'rendered WebUI'):image.require_webui_answer(output,expected)
        self.assertTrue(output['protocol']['semantic']['passed']);self.assertFalse(output['ui_semantic']['passed'])

    def test_image_smoke_uses_encode_identity_without_extra_probe_reference(self):
        from local_runtime import gpu_observation
        with tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
            log=Path(folder)/'engine.log';log.write_text('',encoding='utf-8')
            value=dict(suite='vision-smoke',max_posts=7,max_starts=1,probe_reference=None,
                       config=str(Path(folder)/'config.json'),dependencies={})
            state=dict(startup_seconds=1)
            def start(path,sha,monitor,*,retained,_image):
                retained.update(state=state,spawn_possible=True);return state
            for target,name,kwargs in (
                (manifest,'_verify_authority',dict(return_value=value)),(manifest,'read_json',dict(return_value={'log':str(log)})),
                (runner,'shared_operation',dict(return_value=contextlib.nullcontext())),(runner,'production_inactive',dict()),
                (runner,'preflight_budget',dict(return_value={})),(runner,'MemoryMonitor',dict()),
                (runner,'start_session',dict(side_effect=start)),(image,'require_image_ready',dict(return_value={})),
                (runner,'loader_observation',dict(return_value=({},{}))),(manifest,'require_loader_binding',dict()),
                (gpu_observation,'loaded_modules',dict(return_value=[])),(manifest,'encoder_reference',dict(return_value={'ordinal':1})),
                (manifest,'image_reference',dict(side_effect=AssertionError('extra probe reference not permitted'))),
                (image,'match_encoder_identity',dict(return_value={})),(image,'probe_modules',dict(return_value={})),
                (image,'smoke_requests',dict()),(runner,'wait_request_release',dict()),(runner.safety,'save',dict()),
                (runner.safety,'stop_owned',dict(return_value=[])),(runner,'pending_exit_proof',dict(return_value={'complete':True}))):
                stack.enter_context(patch.object(target,name,**kwargs))
            self.assertEqual(image.run_smoke('fixed','sha')['status'],'passed')
            image.match_encoder_identity.assert_called_once_with('',{'ordinal':1})

    def test_image_identity_loss_aborts_even_with_live_text_engine(self):
        monitor=runner.MemoryMonitor('unused');monitor.images=[dict(pid=7,created=1)]
        with patch.object(runner.safety,'process_identity_status',return_value=Mock(status='gone')):
            with self.assertRaisesRegex(RuntimeError,'image encoder identity'):monitor.check()
        monitor.expect_engine_exit()
        self.assertEqual(monitor.images,[])

    def test_existing_three_sse_transports_preserve_actual_wire_and_planned_cancel_disconnects(self):
        from tools.vision.test_image_api_cases import ImageCasesTests
        streams=ImageCasesTests().streams()
        for api in (*streams,'cancel','cancel-idle','cancel-finish','cancel-done','cancel-owner'):
            with self.subTest(api=api):
                canceled=api.startswith('cancel')
                closed=threading.Event();connection=Mock()
                connection.sock.shutdown.side_effect=lambda *args:closed.set()
                connection.close.side_effect=closed.set
                raw=streams['openai' if canceled else api]
                class Response:
                    status=200
                    def __enter__(self):return self
                    def __exit__(self,*args):pass
                    def __iter__(self):
                        if canceled:
                            first=raw.split('\n')[0]
                            if api=='cancel-finish':first=first.replace('"finish_reason": null','"finish_reason": "stop"')
                            yield (first+'\n').encode()
                            if api=='cancel-done':yield b'data: [DONE]\n\n'
                            closed.wait(3)
                        else:yield from (part.encode() for part in raw.splitlines(keepends=True))
                connection.getresponse.return_value=Response();sample={}
                protocol='openai' if canceled else api
                path={'openai':'/v1/chat/completions','anthropic':'/v1/messages','responses':'/v1/responses'}[protocol]
                statuses=iter([dict(busy=False,queued=0),dict(busy=api!='cancel-idle',queued=0)])
                with patch.object(runner,'ready',side_effect=[None,RuntimeError('owner changed')] if api=='cancel-owner' else None),\
                     patch.object(runner.safety,'get_json',side_effect=lambda path:next(statuses)),\
                     patch.object(runner.http.client,'HTTPConnection',return_value=connection):
                    args=dict(partial=sample,api=protocol,request_body={'fixed':'actual'},pathname=path,cancel_after_answer=canceled)
                    if canceled:
                        with self.assertRaises(runner.FixedRequestCancelled if api=='cancel' else RuntimeError):
                            runner.stream_request({},Mock(),'fixed',128,2,**args)
                        self.assertTrue(closed.is_set());self.assertTrue(sample['reader_stopped'])
                        self.assertEqual(sample.get('planned_cancel',False),api=='cancel')
                        if api!='cancel-owner':self.assertIn('cancel_trigger',sample)
                        self.assertIn('transport_cut_at',sample)
                    else:
                        runner.stream_request({},Mock(),'fixed',128,2,**args)
                        self.assertEqual(sample['raw_sse'],raw);self.assertTrue(sample['normal_terminal'])
                        self.assertEqual(sample['output_tokens'],2)
                self.assertEqual(connection.request.call_count,1)

    def test_webui_shared_launcher_keeps_handles_and_job_or_guard_failures_are_zero_spawn(self):
        from local_runtime import official_runtime as official
        for failure in ('job','guard','observer',False):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
                cfg=dict(log=str(Path(folder)/'webui.log'),commands=[['node','fixed-script']],cwd=folder)
                env=dict(TEMP=folder,TMP=folder)
                value=dict(suite='vision-smoke',config='server',webui_config='webui',webui_environment=env)
                parent=dict(manifest='manifest',manifest_sha256='sha');retained={};saved=[]
                process=Mock(pid=123);observer=Mock();observer.snapshot.return_value=dict(created=1,identities=[dict(pid=123,created=1,exe='node')])
                for target,name,kwargs in (
                    (manifest,'_verify_authority',dict(return_value=value)),(manifest,'read_json',dict(return_value=cfg)),
                    (official,'require_tracking',dict()),(runner.safety,'require_owned_listener',dict()),
                    (image,'webui_environment',dict(return_value=env)),(runner,'preflight_budget',dict(return_value={})),
                    (official.checked_job,'ensure_parent_job',dict(side_effect=RuntimeError('job') if failure=='job' else None)),
                    (official.checked_job,'require_child',dict()),(official.subprocess,'Popen',dict(return_value=process)),
                    (official,'SpawnObserver',dict(side_effect=RuntimeError('observer') if failure=='observer' else None,return_value=observer))):
                    stack.enter_context(patch.object(target,name,**kwargs))
                guard=Mock(side_effect=KeyboardInterrupt('guard') if failure=='guard' else None)
                if failure:
                    with self.assertRaises((RuntimeError,KeyboardInterrupt)):
                        official.start_webui('manifest','sha',parent_state=parent,retained=retained,before_spawn=guard,persist_aux=saved.append)
                    if failure in ('job','guard'):
                        official.subprocess.Popen.assert_not_called();self.assertNotIn('spawn_possible',retained)
                    else:self.assertIs(retained['process'],process);self.assertTrue(retained['spawn_possible'])
                else:
                    official.start_webui('manifest','sha',parent_state=parent,retained=retained,before_spawn=guard,persist_aux=saved.append)
                    self.assertTrue(retained['spawn_possible']);self.assertEqual(len(saved),2)
                    self.assertEqual(official.subprocess.Popen.call_args.kwargs['creationflags'],official.subprocess.CREATE_NO_WINDOW)

    def test_seven_existing_api_ui_flows_are_reserved_once_and_first_failure_stops(self):
        from local_runtime import webui_phase
        rubrics=synthetic_rubrics()
        expected=rubrics['expected_api07']
        answer=json.dumps({key:(value[0] if isinstance(value,list) else value) for key,value in expected.items()})
        ui_answer=json.dumps({key:(value[0] if isinstance(value,list) else value)
                              for key,value in rubrics['expected_webui484'].items()})
        for fail in (False,'anthropic','cancel','uiwrong'):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
                value=dict(config=str(Path(folder)/'config.json'),protocol=image.smoke_protocol())
                result=dict(post_count=0);native=[];calls=[]
                def stream(state,monitor,content,max_tokens,deadline_s,*,partial,api,request_body,pathname,cancel_after_answer):
                    calls.append(api)
                    if fail==api:raise RuntimeError('fixture API failure')
                    partial.update(text=answer,normal_terminal=True,output_tokens=12,reader_stopped=True)
                    native.append(dict(time=20.+len(native),prompt_read=100,reused=0,engine_generated=12,
                                       finish='cancel' if cancel_after_answer else 'stop'))
                    if cancel_after_answer:
                        if fail=='cancel':raise RuntimeError('no actual cancel')
                        raise runner.FixedRequestCancelled('actual delta disconnected')
                    return partial
                def ui(state,monitor,value,result,retained):
                    self.assertEqual(result['post_count'],4);result['post_count']=5;calls.append('webui')
                    native.append(dict(time=24.,prompt_read=100,reused=0,engine_generated=12,finish='stop'))
                    return dict(protocol=dict(text=ui_answer,normal_terminal=True,output_tokens=12),
                                final_answer=dict(text='画像を読み取れません' if fail=='uiwrong' else ui_answer))
                for target,name,kwargs in (
                    (manifest,'read_json',dict(side_effect=lambda path: rubrics if Path(path)==image.API_BINDING else {})),
                    (image,'require_image_ready',dict()),(image,'history',dict(side_effect=lambda state:list(native))),
                    (image,'image_cache_evidence',dict(return_value=dict(shape=[240,20,12,2560],finite=True))),
                    (runner,'stream_request',dict(side_effect=stream)),(runner,'wait_request_release',dict()),
                    (webui_phase,'run',dict(side_effect=ui)),(image.time,'time',dict(return_value=10.))):
                    stack.enter_context(patch.object(target,name,**kwargs))
                if fail:
                    with self.assertRaises(RuntimeError):image.smoke_requests({},Mock(),value,result,{})
                    self.assertEqual(result['post_count'],3 if fail=='anthropic' else 5 if fail=='uiwrong' else 6)
                    self.assertFalse(result['requests'][-1]['valid'])
                else:
                    image.smoke_requests({},Mock(),value,result,{})
                    self.assertEqual(result['post_count'],7)
                    self.assertEqual(len(result['requests']),7)
                    self.assertTrue(all(row['valid'] for row in result['requests']))

    def test_smoke_failure_cleanup_save_and_aux_reader_failure_reaches_locked_barrier(self):
        from local_runtime import official_runtime as official
        for failure in ('request','cleanup'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
                value=dict(suite='vision-smoke',max_posts=7,max_starts=1,config=str(Path(folder)/'config.json'),dependencies={})
                held=[False];calls=[];state=dict(startup_seconds=1,cleanup_pending=True)
                @contextlib.contextmanager
                def locks():
                    held[0]=True
                    try:yield
                    finally:held[0]=False
                def start(path,sha,monitor,*,retained,_image):
                    retained.update(state=state,process=Mock(),observer=Mock(),spawn_possible=True,
                                    auxiliary=dict(spawn_possible=True,state=dict(cleanup_pending=True),reader=Mock()))
                    return state
                def barrier(retained,result,directory):
                    self.assertTrue(held[0]);self.assertTrue(retained['auxiliary']['spawn_possible']);calls.append('barrier')
                for target,name,kwargs in (
                    (manifest,'_verify_authority',dict(return_value=value)),(runner,'shared_operation',dict(side_effect=locks)),
                    (runner,'production_inactive',dict()),(runner,'preflight_budget',dict(return_value={})),
                    (runner,'MemoryMonitor',dict()),(runner,'start_session',dict(side_effect=start)),
                    (image,'require_image_ready',dict()),(runner,'loader_observation',dict(return_value=({},{}))),
                    (manifest,'require_loader_binding',dict()),(official,'require_tracking',dict())):
                    stack.enter_context(patch.object(target,name,**kwargs))
                # Failure occurs after successful ownership entry; no actual loader/HTTP.
                stack.enter_context(patch('local_runtime.gpu_observation.loaded_modules',side_effect=RuntimeError('original request failure')))
                stack.enter_context(patch.object(runner,'wait_request_release',side_effect=OSError('cleanup failure')))
                stack.enter_context(patch.object(runner,'hold_pending_cleanup',side_effect=barrier))
                with self.assertRaisesRegex(RuntimeError,'original request failure'):image.run_smoke(Path('fixed'),'sha')
                self.assertEqual(calls,['barrier'])
                self.assertEqual(json.loads((Path(folder)/'result.json').read_text())['status'],'failed')

    def test_history_is_exact_new_row_not_fallback_or_expected_input(self):
        old=[dict(time=10.,prompt_read=2,reused=0)]
        row=dict(time=12.,prompt_read=100,reused=4,finish='stop',engine_generated=9)
        self.assertEqual(image.correlate_history(old,old+[row],11.,False)['native_input_tokens'],104)
        for changed in (old,old+[row,row],old+[dict(row,time=9)],old+[dict(row,prompt_read=None)],
                        old+[dict(row,reused=True)],old+[dict(row,finish='disconnect')]):
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):
                image.correlate_history(old,changed,11.,False)
        canceled=dict(row,finish='cancel',engine_generated=None)
        self.assertIsNone(image.correlate_history(old,old+[canceled],11.,True)['native_output_tokens'])

    def test_zero_spawn_aux_does_not_make_main_exit_unprovable(self):
        state=dict(config='test',owned_identities=[dict(pid=99,created=1,exe='cpu')],
                   spawn_observation=dict(created=1,identities=[],unknown=[],errors=[]))
        with patch.object(runner.safety,'process_identity_status',return_value=Mock(status='gone')),\
             patch.object(runner.safety,'process_presence',return_value='gone'),patch.object(runner.safety,'check_port_available'):
            self.assertTrue(runner.pending_exit_proof(dict(state=state,auxiliary={}))['complete'])

    def test_coexistence_uses_actual_peak_and_strict_residual_not_future_constant(self):
        peak=2**30
        encode=dict(status='passed',cleanup=dict(status='passed'),parity_passed=True,coverage_passed=True,
                    memory_observation_ready=True,graph=dict(passed=True),identity=dict(pci='07',ordinal=1),
                    sampled_gpu_peaks=dict(process_dedicated_bytes=peak),arms=[{}, {},dict(
                        cohort=[dict(pid=7,created=1.,exe=str(image.HIP_EXE))],memory_samples=[dict(gpu=dict(
                            adapter=dict(luid_high=0,luid_low=2,dedicated_capacity_bytes=32*2**30)))])])
        budget=dict(version=1,encode_result_sha256='fixed',pci='07',luid_high=0,luid_low=2,encoder_pid=7,
                    encoder_created=1.,sampled_peak_process_dedicated_bytes=peak,residual_mib=2048,reserve_mib=3072)
        self.assertEqual(image.coexistence(encode,budget)['reserve_mib'],3072)
        for key,value in [('residual_mib',True),('encoder_created',float('nan')),('reserve_mib',2560),('luid_low',3)]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):image.coexistence(encode,dict(budget,**{key:value}))

    def test_fixed_smoke_budget_order_a_config_and_wire_semantic_are_distinct(self):
        protocol=image.smoke_protocol()
        self.assertEqual(protocol['order'],['text-before','openai','anthropic','responses','webui','cancel','text-after'])
        self.assertEqual(manifest.SUITES['vision-smoke'],dict(max_posts=7,max_tokens=128,max_starts=1,max_browser_starts=1))
        output=dict(normal_terminal=True,output_tokens=12,text='wrong',finish_reason='stop')
        with self.assertRaises(RuntimeError):image.require_image_answer(output,synthetic_rubrics()['expected_api07'])
        self.assertFalse(output['semantic']['passed'])


if __name__=='__main__':unittest.main()
