import unittest
from local_runtime import timing_parser as p


HEADER='strata prefill timing: 4095 tokens, GPU timeline 100 ms, wall 110 ms, host staging 20 ms: qsa attn 20 (20.0%) wait copy 80 (80.0%)\n'
HOST='strata prefill timing: host: chunk setup (PLE rows, the expert stream plan) 1 ms, waiting for each chunk 2 ms, after each chunk (the draft layer, progress) 3 ms, PLE 4 ms\n'


class TimingParser(unittest.TestCase):
    def test_last_prompt_token_may_be_verified_outside_batched_timer(self):
        value=p.parse(HEADER+HOST,timing=True,prompt_tokens=4096,quantitative=True)
        self.assertEqual(value['timer_tokens'],4095)
        self.assertEqual(value['blocks'][0]['phases_ms']['qsa attn'],20)
        self.assertIsNone(value['blocks'][0]['phases_ms']['gemm down'])
        self.assertEqual(value['scope'],'request log offset; prefill timer blocks, not kernel-exclusive')

    def test_rounded_zero_is_legal_and_missing_is_not_zero(self):
        text=HEADER.replace('qsa attn 20 (20.0%)','qsa attn 0 (0.1%)').replace('wait copy 80 (80.0%)','wait copy 100 (99.9%)')+HOST
        value=p.parse(text,timing=True,prompt_tokens=4096,quantitative=True)
        self.assertEqual(value['blocks'][0]['phases_ms']['qsa attn'],0)
        self.assertIsNone(value['blocks'][0]['phases_ms']['gdn'])

    def test_multiple_blocks_keep_all_token_and_host_rows(self):
        value=p.parse((HEADER+HOST)*2,timing=True,prompt_tokens=20480,quantitative=True)
        self.assertEqual(value['timer_tokens'],8190)
        self.assertEqual(len(value['blocks']),2)

    def test_timed_quantitative_missing_or_broken_header_host_is_not_zero(self):
        for text in ('',HEADER,HOST,HEADER+HOST+HOST,HEADER.replace('100 ms','nan ms')+HOST,
                     HEADER.replace('100 ms','-1 ms')+HOST,HEADER.replace('100 ms','inf ms')+HOST,
                     HEADER.replace('qsa attn 20 (20.0%)','new phase 20 (20.0%)')+HOST,
                     HEADER.replace('wait copy 80 (80.0%)','qsa attn 80 (80.0%)')+HOST):
            with self.subTest(text=text),self.assertRaises(p.TimingSchemaError):
                p.parse(text,timing=True,prompt_tokens=4096,quantitative=True)

    def test_warmup_may_have_no_timer_and_off_must_have_no_timer(self):
        value=p.parse('',timing=True,prompt_tokens=63,quantitative=False)
        self.assertEqual(value['status'],'not_observed_warmup')
        self.assertIsNone(value['gpu_timeline_ms'])
        self.assertEqual(p.parse('',timing=False,prompt_tokens=4096,quantitative=True)['status'],'disabled')
        with self.assertRaises(p.TimingSchemaError):
            p.parse(HEADER+HOST,timing=False,prompt_tokens=4096,quantitative=True)

    def test_stale_or_impossible_timer_token_count_is_rejected(self):
        for text in (HEADER.replace('4095 tokens','0 tokens')+HOST,
                     HEADER.replace('4095 tokens','20480 tokens')+HOST):
            with self.assertRaises(p.TimingSchemaError):
                p.parse(text,timing=True,prompt_tokens=4096,quantitative=True)
