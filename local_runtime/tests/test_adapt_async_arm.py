"""D3 exact flag, common extra allowance, and fixed two-warmup evidence gates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from local_runtime import manifest,benchmark,evaluate_r9700 as runner
from local_runtime.tests.test_decode_arms import unit_base

PIN = 'FileExpertSource: mapped pinned cache complement ready: resident 16.00 GiB, pinned 16.00 GiB in 2 s\n'
ENABLE = 'strata serve: adaptive tier asynchronous (--adapt-async 1): up to 96 swaps per round, a round every 4 windows\n'


class AdaptAsyncTests(unittest.TestCase):
    def test_exact_async_flag_only_and_common_budget_has_extra_one_gib(self):
        base = unit_base()
        baseline = manifest.expected_config('baseline',Path('fixture'),base,'screen')
        self.assertIn('d3-adapt-async1',manifest.ARMS)
        cfg = manifest.expected_config('d3-adapt-async1',Path('fixture'),base,'screen')
        self.assertEqual(cfg['args'][:-2],baseline['args'])
        self.assertEqual(cfg['args'][-2:],['--adapt-async','1'])
        self.assertEqual(dict(cfg,args=cfg['args'][:-2]),baseline)
        self.assertEqual(manifest.BUDGET['uncertainty_gib'],9)
        good = dict(available_bytes=68*runner.GIB,commit_margin_bytes=67*runner.GIB)
        with patch.object(runner,'memory_sample',return_value=good):
            result = runner.preflight_budget()
            self.assertEqual((result['required_available_gib'],result['required_commit_gib']),(68,67))
        for key in ('available_bytes','commit_margin_bytes'):
            with self.subTest(key=key),patch.object(runner,'memory_sample',return_value=dict(good,**{key:good[key]-1})):
                advisory=runner.preflight_budget()
                self.assertFalse(advisory['predicted_fits'])
                self.assertTrue(advisory['startup_prediction_advisory'])
        self.assertEqual((manifest.BUDGET['available_floor_gib'],manifest.BUDGET['commit_floor_gib']),(4,8))

    def test_fixed_stage_gates_allow_short_zero_but_stop_on_fallback_or_no_primary_work(self):
        cases = [dict(name=n,prompt_tokens=t,initial_deadline_seconds=d,content='input',
                      input_sha256='input',token_sha256='tokens') for n,t,d in benchmark.LENGTHS]
        # No extra request/case is added to make an inactive arm look successful.
        for kind,expected in [('active',12),('zero',2),('missing',2),('rounds_only',2),
                              ('fallback',1),('no_enable',1),('not_pinned',1)]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                log = directory/'engine.log'
                log.write_text(('' if kind == 'not_pinned' else PIN)+('' if kind == 'no_enable' else ENABLE)+
                               ('strata generate: --adapt-async 1 is off (pin failed)\n' if kind == 'fallback' else ''),
                               encoding='utf-8')
                state,value,result = dict(engine_log=str(log)),dict(config=str(directory/'config.json'),
                    suite='screen',arm='d3-adapt-async1',protocol=benchmark.protocol(cases),max_posts=12,max_tokens=128),dict(post_count=0)
                requests = benchmark.requests(cases,'screen')
                sent = []
                def stream(*args,partial=None):
                    case = requests[len(sent)]['case']
                    sent.append(case['name'])
                    with log.open('a',encoding='utf-8') as f:
                        f.write(f"prompt {case['prompt_tokens']} tokens = 0 reused + {case['prompt_tokens']} read\n")
                        if kind != 'missing':
                            rounds,swapped = ((2,5) if kind == 'active' and len(sent) >= 2 else
                                              (2,0) if kind == 'rounds_only' else (0,0))
                            f.write(f'asynchronous adaptive tier: {rounds} rounds, {swapped} experts swapped in, 1.0 ms per round\n')
                    return dict(text='answer',reasoning='',finish_reason='length',wall_seconds=1.,
                        first_sse_seconds=0.,first_answer_seconds=.5,
                        usage=dict(prompt_tokens=case['prompt_tokens'],completion_tokens=128,
                                   prompt_tokens_details=dict(cached_tokens=0)),
                        timings=dict(cache_n=0,prompt_n=case['prompt_tokens'],predicted_n=128,
                            prompt_ms=500.,prompt_per_second=100.,predicted_ms=500.,predicted_per_second=256.))
                with patch.object(manifest,'read_json',return_value=dict(tokenizer='fixture')), \
                        patch.object(manifest,'baseline_reference',return_value=None), \
                        patch.object(benchmark,'prompts',return_value=cases), \
                        patch.object(runner,'wait_request_release'),patch.object(runner,'stream_request',side_effect=stream):
                    if kind == 'active':
                        runner.screen(state,Mock(),value,result)
                    else:
                        with self.assertRaisesRegex(RuntimeError,'invalid'):
                            runner.screen(state,Mock(),value,result)
                self.assertEqual(len(sent),expected)
                rows = [json.loads(s) for s in (directory/'samples.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(rows[-1]['valid'],kind == 'active')
                if kind in ('active','zero','missing','rounds_only'):
                    self.assertTrue(rows[0]['valid'])
                    self.assertEqual(sent[:2],['short','4k'])
                    self.assertEqual(rows[0]['async_observation']['work_required'],False)
                    self.assertEqual(rows[1]['async_observation']['work_required'],True)


if __name__ == '__main__':
    unittest.main()
