"""Bounded screen protocol: real tokenizer, fresh validation, and comparable arms."""
import copy
import json
import time
from pathlib import Path
import tempfile
import unittest
import psutil
from unittest.mock import Mock,patch

from local_runtime import benchmark,manifest,evaluate_r9700 as runner
from local_runtime.tests.test_decode_arms import unit_base


class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.has_private_tokenizer=manifest.BASE_PROFILE.is_file()
        if cls.has_private_tokenizer:
            directory=Path(manifest.read_json(manifest.BASE_PROFILE)['tokenizer'])
            cls.has_private_tokenizer=all((directory/name).is_file() for name in ('vocab.json','merges.txt','token_type.json','chat_template.jinja'))
        if cls.has_private_tokenizer:
            cls.prompts=benchmark.prompts(directory)
        else:
            cls.prompts=[dict(name=name,content='synthetic '+name,prompt_tokens=target,
                             initial_deadline_seconds=deadline,input_sha256=benchmark.sha(name.encode()),
                             token_sha256=benchmark.sha(str(target).encode()))
                         for name,target,deadline in benchmark.LENGTHS]

    def sample(self,case):
        return dict(text='answer',reasoning='',finish_reason='length',wall_seconds=10.,
                    first_sse_seconds=.01,first_answer_seconds=5.,
                    usage=dict(prompt_tokens=case['prompt_tokens'],completion_tokens=128,
                               prompt_tokens_details=dict(cached_tokens=0)),
                    timings=dict(cache_n=0,prompt_n=case['prompt_tokens'],predicted_n=128,
                                 prompt_ms=5000.,prompt_per_second=case['prompt_tokens']/5,
                                 predicted_ms=5000.,predicted_per_second=25.6,draft_n=10,draft_n_accepted=8))

    def test_real_rendered_prompts_have_exact_tokens_and_stable_hash(self):
        if not self.has_private_tokenizer:self.skipTest('private canonical tokenizer/profile not distributed')
        self.assertEqual([p['prompt_tokens'] for p in self.prompts],[256,4096,32768])
        repeated = benchmark.prompts(manifest.read_json(manifest.BASE_PROFILE)['tokenizer'])
        self.assertEqual(self.prompts,repeated)
        self.assertEqual(len({p['token_sha256'] for p in self.prompts}),3)

    def test_plan_is_three_excluded_warmups_then_three_per_length(self):
        plan = benchmark.requests(self.prompts,'screen')
        self.assertEqual(len(plan),12)
        self.assertEqual([row['phase'] for row in plan[:3]],['warmup']*3)
        self.assertEqual([row['case']['name'] for row in plan[3:]],['short']*3+['4k']*3+['32k']*3)
        self.assertEqual(len(benchmark.requests(self.prompts,'diagnostic')),3)

    def test_cache_early_stop_reasoning_mismatched_count_or_nonfinite_is_invalid(self):
        case = self.prompts[0]
        good = self.sample(case)
        log = 'strata serve: prompt 256 tokens = 0 reused + 256 read in 5000 ms'
        self.assertEqual(benchmark.validate_sample(good,case,log),[])
        changes = [('cached',lambda s:s['timings'].update(cache_n=1)),
                   ('early',lambda s:s['usage'].update(completion_tokens=127)),
                   ('reasoning',lambda s:s.update(reasoning='hidden')),
                   ('nan',lambda s:s['timings'].update(prompt_per_second=float('nan')))]
        for name,change in changes:
            value = copy.deepcopy(good)
            change(value)
            with self.subTest(name=name):
                self.assertTrue(benchmark.validate_sample(value,case,log))
        self.assertTrue(benchmark.validate_sample(good,case,log.replace('0 reused','1 reused')))
        self.assertTrue(benchmark.validate_sample(good,case,''))

    def test_summary_excludes_warmups_and_incomplete_or_invalid_cannot_pass(self):
        rows = []
        for request in benchmark.requests(self.prompts,'screen'):
            rows.append(dict(phase=request['phase'],case=request['case']['name'],valid=True,
                             sample=self.sample(request['case'])))
        rows[0]['sample']['wall_seconds'] = 10000.
        summary = benchmark.summarize(rows)
        self.assertEqual(summary['short']['wall_seconds'],10.)
        rows[-1]['valid'] = False
        with self.assertRaisesRegex(RuntimeError,'complete'):
            benchmark.summarize(rows)

    def test_verbose_is_common_only_for_diagnostic_and_t2_changes_only_chunk(self):
        base = unit_base()
        for suite in ('screen','diagnostic'):
            baseline = manifest.expected_config('baseline',Path('fixture'),base,suite)
            table = manifest.expected_config('t1-table',Path('fixture'),base,suite)
            self.assertEqual(baseline['args'],table['args'])
            self.assertEqual(baseline['env'].get('STRATA_HIPBLASLT_VERBOSE'),
                             table['env'].get('STRATA_HIPBLASLT_VERBOSE'))
            self.assertEqual(baseline['env'].get('STRATA_HIPBLASLT_VERBOSE'),'1' if suite == 'diagnostic' else None)
            for arm in ('t2-2048','t2-4096','t2-6144'):
                cfg = manifest.expected_config(arm,Path('fixture'),base,suite)
                index = cfg['args'].index('--prefill')+1
                cfg['args'][index] = 'auto'
                self.assertEqual(cfg,baseline)

    def test_screen_invalid_sample_is_persisted_and_stops_additional_posts(self):
        with tempfile.TemporaryDirectory() as folder:
            value = dict(suite='screen',arm='baseline',config=str(Path(folder)/'config.json'),
                         max_posts=12,max_tokens=128,protocol=benchmark.protocol(self.prompts))
            result = dict(post_count=0)
            state = dict(engine_log=str(Path(folder)/'engine.log'))
            Path(state['engine_log']).write_text('',encoding='utf-8')
            with patch.object(benchmark,'prompts',return_value=self.prompts), \
                    patch.object(manifest,'read_json',return_value=dict(tokenizer='fixture')), \
                    patch.object(runner,'stream_request',return_value=self.sample(self.prompts[0])), \
                    patch.object(runner,'wait_request_release'):
                with self.assertRaisesRegex(RuntimeError,'invalid'):
                    runner.screen(state,Mock(),value,result)
            self.assertEqual(result['post_count'],1)
            self.assertFalse(result['samples'][0]['valid'])
            self.assertTrue((Path(folder)/'samples.jsonl').read_text(encoding='utf-8'))

    def test_same_day_baseline_binding_rejects_edits_failed_old_day_source_or_dependencies(self):
        with tempfile.TemporaryDirectory(dir=manifest.LOCAL/'records') as folder:
            directory = Path(folder)
            rows = [dict(phase=row['phase'],case=row['case']['name'],valid=True,sample=self.sample(row['case']))
                    for row in benchmark.requests(self.prompts,'screen')]
            original = dict(arm='baseline',suite='screen',source_files={'fixed':'sha'},dependencies={'sdk':'sha'},
                            protocol=benchmark.protocol(self.prompts),memory_budget=manifest.BUDGET)
            source = directory/'manifest.json'
            source.write_text(json.dumps(original),encoding='utf-8')
            result = dict(manifest=str(source),manifest_sha256=manifest.digest(source),status='passed',
                          cleanup=dict(status='passed'),completed_date=time.strftime('%Y-%m-%d'),
                          post_count=12,start_count=1,samples=rows,summary=benchmark.summarize(rows))
            path = directory/'result.json'
            value = dict(original,arm='t1-table',dependencies={'sdk':'sha',
                str(manifest.ORIGINAL/'tools/hip/gfx1201-hipblaslt-100500.txt'):'table'})
            for changed in (None,'failed','old_day','source','protocol','budget','dependencies','edit'):
                candidate,receipt = copy.deepcopy(value),copy.deepcopy(result)
                if changed == 'failed':
                    receipt['status'] = 'failed'
                if changed == 'old_day':
                    receipt['completed_date'] = '2000-01-01'
                if changed == 'source':
                    candidate['source_files']['fixed'] = 'other'
                if changed == 'protocol':
                    candidate['protocol']['seed'] = 43
                if changed == 'budget':
                    candidate['memory_budget']['resident_gib'] = 24
                if changed == 'dependencies':
                    candidate['dependencies']['sdk'] = 'other'
                path.write_text(json.dumps(receipt),encoding='utf-8')
                candidate['baseline_reference'] = dict(path=str(path),sha256=manifest.digest(path))
                if changed == 'edit':
                    path.write_text('{}',encoding='utf-8')
                with self.subTest(changed=changed),patch.object(manifest,'verify',return_value=original), \
                        patch.object(manifest,'require_loader_binding'):
                    if changed is None:
                        self.assertEqual(manifest.baseline_reference(candidate),result)
                    else:
                        with self.assertRaises(RuntimeError):
                            manifest.baseline_reference(candidate)
            with self.assertRaisesRegex(RuntimeError,'same-day'):
                manifest.baseline_reference(dict(arm='t1-table'))

    def test_success_screen_has_twelve_posts_derived_deadline_and_excluded_warmups(self):
        with tempfile.TemporaryDirectory() as folder:
            value = dict(suite='screen',arm='baseline',config=str(Path(folder)/'config.json'),
                         max_posts=12,max_tokens=128,protocol=benchmark.protocol(self.prompts))
            result,state = dict(post_count=0),dict(engine_log=str(Path(folder)/'engine.log'))
            Path(state['engine_log']).write_text('',encoding='utf-8')
            requests = benchmark.requests(self.prompts,'screen')
            calls = []
            def stream(*args,**kwargs):
                case = requests[len(calls)]['case']
                calls.append(args)
                with Path(state['engine_log']).open('a',encoding='utf-8') as log:
                    log.write(f"prompt {case['prompt_tokens']} tokens = 0 reused + {case['prompt_tokens']} read\n")
                return self.sample(case)
            baseline = dict(samples=[dict(case=case['name'],sample=dict(wall_seconds=100.)) for case in self.prompts])
            with patch.object(benchmark,'prompts',return_value=self.prompts), \
                    patch.object(manifest,'read_json',return_value=dict(tokenizer='fixture')), \
                    patch.object(manifest,'baseline_reference',return_value=baseline), \
                    patch.object(runner,'stream_request',side_effect=stream),patch.object(runner,'wait_request_release'):
                baseline['summary'] = benchmark.summarize([dict(phase='measured',case=case['name'],valid=True,
                    sample=self.sample(case)) for case in self.prompts for _ in range(3)])
                runner.screen(state,Mock(),value,result)
            self.assertEqual(result['post_count'],12)
            self.assertEqual([args[-1] for args in calls],[260.]*12)
            self.assertEqual(result['summary']['short']['measured_samples'],3)

    def test_nonbaseline_screen_missing_reference_fails_semantically_before_spawn(self):
        # Test the boundary called by manifest.verify, without starting any runtime.
        with self.assertRaisesRegex(RuntimeError,'same-day'):
            manifest.baseline_reference(dict(arm='t2-2048',suite='screen'))

    def test_standard_windows_loader_query_on_cpu_python_process(self):
        # Read this CPU-only test process. No server, engine, DLL load or GPU call.
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'engine.log'
            log.write_text('',encoding='utf-8')
            process = psutil.Process()
            identity = dict(pid=process.pid,created=process.create_time(),exe=process.exe())
            state = dict(owned_identities=[identity],engine_log=str(log))
            value = dict(config='fixture',dependencies={str(manifest.PYTHON):manifest.digest(manifest.PYTHON)})
            with patch.object(manifest,'read_json',side_effect=[dict(exe=process.exe()),dict(rocm='fixture')]), \
                    patch.object(runner.subprocess,'run',return_value=Mock(stdout='[]')):
                observation,engine = runner.loader_observation(state,value)
            self.assertEqual(engine,identity)
            self.assertTrue(any(Path(row['path']) == Path(process.exe()) for row in observation['modules']))
            self.assertEqual(observation['method'],'EnumProcessModulesEx/GetModuleFileNameExW')

    def test_diagnostics_keep_activation_and_fallback_counts_outside_measurements(self):
        result = benchmark.tuning_observation('prefill gemm: hipBLASLt tuning enabled (12 rows, gfx1201, version 100500)\n'
            'prefill gemm: hipBLASLt summary launches=17 fallbacks=4 unique_fallback_shapes=2\n')
        self.assertEqual(result['enabled'],[('12','gfx1201','100500')])
        self.assertEqual(result['summaries'],[dict(launches=17,fallbacks=4,unique_fallback_shapes=2)])


if __name__ == '__main__':
    unittest.main()
