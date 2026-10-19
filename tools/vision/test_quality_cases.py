"""Fixed quality fixture/helper checks; no model, GPU or API."""
import json
import copy
import tempfile
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / 'tools/vision/quality_cases_spec.json'


class FixtureSchema(unittest.TestCase):
    def test_empty_array_uses_valid_fixed_dialect_shape(self):
        value = json.loads(DRAFT.read_text(encoding='utf-8'))
        case = next(c for c in value['cases'] if c['id'] == 'JS09')
        empty = case['scoring']['schema']['properties']['empty']
        self.assertNotIn('prefixItems', empty)
        self.assertEqual(empty, {'type': 'array', 'minItems': 0, 'maxItems': 0})
        self.assertEqual(case['scoring']['expected'], {'empty': []})
        self.assertEqual(value['json_schema_dialect'], 'https://json-schema.org/draft/2020-12/schema')


class QualityHelper(unittest.TestCase):
    def setUp(self):
        from tools.vision import quality_cases
        self.q = quality_cases
        self.draft = json.loads(DRAFT.read_text(encoding='utf-8'))

    def case(self, cid):
        case=copy.deepcopy(next(c for c in self.draft['cases'] if c['id'] == cid))
        # Small synthetic materialized counts for response/protocol unit fixtures.
        case['turns']=[{'input_tokens':1,'body':{'max_tokens':case['max_tokens_per_post']}}
                       for _ in range(case['max_posts'])]
        return case

    def response(self, text='', **extra):
        return dict(text=text, finish_reason='stop', usage={'prompt_tokens': 1, 'completion_tokens': 1},
                    timings={'prompt_n': 1, 'predicted_n': 1}, **extra)

    def test_exact_answer_and_missing_evidence(self):
        case = self.case('JP01')
        self.assertTrue(self.q.score_case(case, self.response('青葉駅'))['passed'])
        self.assertFalse(self.q.score_case(case, self.response('出発駅は青葉駅です'))['passed'])
        response = self.response('青葉駅'); response['timings'] = None
        self.assertFalse(self.q.score_case(case, response)['passed'])

    def test_json_rejects_duplicate_keys_prose_bool_as_int_and_empty_shape_error(self):
        case = self.case('JS09')
        self.assertTrue(self.q.score_case(case, self.response('{"empty": []}'))['passed'])
        for text in ('{"empty": [], "empty": []}', '```json\n{"empty": []}\n```', '{"empty": [1]}'):
            self.assertFalse(self.q.score_case(case, self.response(text))['passed'])
        self.assertFalse(self.q.score_case(self.case('JS11'), self.response('{"value": true}'))['passed'])

    def test_json_schema_numeric_semantics_but_code_vector_types_remain_strict(self):
        case=self.case('JS01')
        for number in ('3','3.0','3e0'):
            with self.subTest(valid=number):
                self.assertTrue(self.q.score_case(case,self.response('{"name":"青葉","count":'+number+'}'))['passed'])
        for number in ('true','3.5','"3"','1e999'):
            with self.subTest(invalid=number):
                self.assertFalse(self.q.score_case(case,self.response('{"name":"青葉","count":'+number+'}'))['passed'])
        result=self.q.check_code_input({'case_id':'type-fixture','code':'def solve(): return 3.0',
                                       'vectors':[{'args':[],'expected':3}]*4})
        self.assertFalse(result['passed'])

    def test_json_preserves_decimal_value_before_comparison(self):
        for cid,text in [('JS15','{"zero":1e-400,"label":"0"}'),
                         ('JS01','{"name":"青葉","count":3.0000000000000001}'),
                         ('JS12','{"value":1.2500000000000000000000000000000001}'),
                         ('JS12','{"value":1e999999999999999999999999999}')]:
            with self.subTest(invalid=text):
                self.assertFalse(self.q.score_case(self.case(cid),self.response(text))['passed'])
        for text in ('{"value":1.25}','{"value":1.250}','{"value":125e-2}'):
            with self.subTest(valid=text):
                self.assertTrue(self.q.score_case(self.case('JS12'),self.response(text))['passed'])
        case=self.case('TL01')
        response=self.response(tool_calls=[{'function':{'name':'add_numbers','arguments':'{"a":7.0,"b":5}'}}])
        response['finish_reason']='tool_calls'
        self.assertFalse(self.q.score_case(case,response)['passed'])

    def test_actual_prompt_count_matches_materialized_case_and_each_turn(self):
        def counted(text,count,**extra):
            response=self.response(text,**extra)
            response['usage']['prompt_tokens']=count
            response['timings']['prompt_n']=count
            return response
        case=self.case('LR100K-18');case['turns'][0]['input_tokens']=102400
        expected=case['scoring']['expected']
        self.assertTrue(self.q.score_case(case,counted(expected,102400))['passed'])
        self.assertFalse(self.q.score_case(case,counted(expected,4096))['passed'])
        self.assertFalse(self.q.score_case(case,counted(expected,True))['passed'])
        case['turns'][0]['input_tokens']=True
        self.assertFalse(self.q.score_case(case,counted(expected,True))['passed'])
        del case['turns']
        self.assertFalse(self.q.score_case(case,counted(expected,102400))['passed'])
        for cid in ('TL01','ST01'):
            with self.subTest(case=cid):
                case=self.case(cid)
                case['turns'][0]['input_tokens']=7;case['turns'][1]['input_tokens']=11
                expected=case['scoring']['second']['expected']
                response=counted(expected,11,turn_index=1)
                if case['scoring']['second']['method'].startswith('SSE_'):
                    response['stream_events']=[{'text':expected},{'done':True}]
                self.assertTrue(self.q.score_case(case,response)['passed'])
                response['usage']['prompt_tokens']=response['timings']['prompt_n']=7
                self.assertFalse(self.q.score_case(case,response)['passed'])

    def test_actual_output_count_must_be_positive_and_within_fixed_cap(self):
        case=self.case('JP01')
        for count in (0,case['max_tokens_per_post']+1,True):
            with self.subTest(count=count):
                response=self.response('青葉駅')
                response['usage']['completion_tokens']=response['timings']['predicted_n']=count
                self.assertFalse(self.q.score_case(case,response)['passed'])
        case['turns'][0]['body']['max_tokens']=1
        response=self.response('青葉駅')
        response['usage']['completion_tokens']=response['timings']['predicted_n']=2
        self.assertFalse(self.q.score_case(case,response)['passed'])

    def test_tool_call_requires_exact_name_arguments_and_valid_continuation(self):
        case = self.case('TL01')
        response = self.response(tool_calls=[{'function': {'name': 'add_numbers', 'arguments': '{"a":7,"b":5}'}}])
        response['finish_reason'] = 'tool_calls'
        self.assertTrue(self.q.score_case(case, response)['passed'])
        response['tool_calls'][0]['function']['arguments'] = '{"a":true,"b":5}'
        self.assertFalse(self.q.score_case(case, response)['passed'])
        response = self.response('12', turn_index=1)
        self.assertTrue(self.q.score_case(case, response)['passed'])

    def test_stream_reassembled_content_and_terminal_are_required(self):
        case = self.case('ST01')
        good = self.response('青葉', stream_events=[{'text':'青'}, {'text':'葉'}, {'done':True}])
        self.assertTrue(self.q.score_case(case, good)['passed'])
        good['stream_events'][-1] = {'text':'駅'}
        self.assertFalse(self.q.score_case(case, good)['passed'])
        good['stream_events'] = [{'done':True}, {'text':'青葉'}]
        self.assertFalse(self.q.score_case(case, good)['passed'])

    def test_intentional_cancel_requires_all_recovery_and_not_normal_finish(self):
        case = self.case('CA01')
        proof = dict(trigger_events=1, preclose_busy=True, owner_verified=True, terminal_before_cut=False,
                     reader_exited=True, same_cohort=True, busy=False, queued=0, release_seconds=1.,
                     posthoc_cancelled=True, normal_finish=False)
        proof['native_input_evidence']=dict(source='metrics.requests.prompt_read+reused',prompt_read=1,reused=0,
             request_started_at=100.,owner_verified=True,
             history_row={'time':101.,'finish':'cancel','prompt_read':1,'reused':0})
        self.assertTrue(self.q.score_case(case, self.response(cancel_proof=proof))['passed'])
        pending_proof=copy.deepcopy(proof);pending_proof.pop('native_input_evidence')
        pending=self.q.score_case(case, {'cancel_proof':pending_proof})
        self.assertFalse(pending['passed'])
        self.assertTrue(pending['recovery_passed'])
        for key,value in [('normal_finish',True), ('reader_exited',False), ('posthoc_cancelled',None),
                          ('queued',1), ('release_seconds',31), ('terminal_before_cut',True)]:
            changed=dict(proof); changed[key]=value
            self.assertFalse(self.q.score_case(case, self.response(cancel_proof=changed))['passed'])

    def test_cancel_input_uses_native_read_plus_reused_and_never_len_fallback(self):
        case=self.case('CA01');case['turns'][0]['input_tokens']=10
        proof=dict(trigger_events=1,preclose_busy=True,owner_verified=True,terminal_before_cut=False,
                   reader_exited=True,same_cohort=True,busy=False,queued=0,release_seconds=1.,
                   posthoc_cancelled=True,normal_finish=False,
                   native_input_evidence={'source':'metrics.requests.prompt_read+reused',
                       'prompt_read':7,'reused':3,'request_started_at':100.,'owner_verified':True,
                       'history_row':{'time':101.,'finish':'cancel','prompt_read':7,'reused':3,
                                      'prompt_tokens':999,'prompt_total':999}})
        result=self.q.score_case(case,{'cancel_proof':proof})
        self.assertTrue(result['passed'])
        self.assertTrue(result['input_verified'])
        for key,value in [('prompt_read',None),('prompt_read',True),('reused',2),
                          ('owner_verified',False),('source','expected'),('request_started_at',102.)]:
            with self.subTest(key=key,value=value):
                changed=copy.deepcopy(proof);changed['native_input_evidence'][key]=value
                self.assertFalse(self.q.score_case(case,{'cancel_proof':changed})['passed'])
        for key,value in [('prompt_read',None),('finish','stop'),('time',float('nan'))]:
            changed=copy.deepcopy(proof);changed['native_input_evidence']['history_row'][key]=value
            self.assertFalse(self.q.score_case(case,{'cancel_proof':changed})['passed'])

    def test_code_descriptor_is_one_worker_four_vectors_and_helper_never_spawns(self):
        code='def solve(a,b):\n while b:\n  a,b=b,a%b\n return a\n'
        with mock.patch('subprocess.Popen', side_effect=AssertionError('helper must not spawn')):
            tasks=self.q.code_check_tasks(self.case('CD01'), self.response(code))
            self.assertEqual(len(tasks),1)
            self.assertEqual(tasks[0]['vectors_count'],4)
            self.assertEqual(tasks[0]['timeout_seconds'],2)
            self.assertEqual(tasks[0]['memory_limit_bytes'],268435456)
            self.assertEqual(tasks[0]['max_child_processes'],0)
            result=self.q.check_code_input(tasks[0]['stdin_json'])
        self.assertTrue(result['passed'])
        self.assertEqual(result['vectors_passed'],4)

    def test_code_rejects_external_operations_and_wrong_answers(self):
        for code in ('import os\ndef solve(a,b): return 6', 'def solve(a,b):\n return open("x").read()',
                     'def solve(a,b):\n return ().__class__', 'def solve(a,b):\n return 0'):
            task=self.q.code_check_tasks(self.case('CD01'),self.response(code))[0]
            self.assertFalse(self.q.check_code_input(task['stdin_json'])['passed'])

    def test_code_result_is_bound_to_exact_code_and_vectors(self):
        case=self.case('CD01')
        code='def solve(a,b):\n while b:\n  a,b=b,a%b\n return a\n'
        response=self.response(code)
        result=self.q.check_code_input(self.q.code_check_tasks(case,response)[0]['stdin_json'])
        response['code_check']=result
        self.assertTrue(self.q.score_case(case,response)['passed'])
        response['text']='def solve(a,b): return 0'
        self.assertFalse(self.q.score_case(case,response)['passed'])

    def test_bool_turn_or_timing_counts_cannot_be_success(self):
        response=self.response('12',turn_index=True)
        self.assertFalse(self.q.score_case(self.case('TL01'),response)['passed'])
        response=self.response('青葉駅');response['timings']['prompt_n']=True
        self.assertFalse(self.q.score_case(self.case('JP01'),response)['passed'])

    def test_fill_accounts_for_token_boundary_before_digit_padding(self):
        class Tokens:
            def encode(self,text): return list(text)
        # The real tokenizer splits the preceding newline differently when digits follow it.
        measure=lambda s: 17+len(s)+(1 if '0' in s else 0)
        self.assertEqual(measure(self.q._fill(737,measure,'u'*25,Tokens())),737)

    def test_malformed_response_fails_closed_and_missing_code_has_no_worker(self):
        self.assertFalse(self.q.score_case(self.case('ST01'),self.response('青葉',stream_events=[None]))['passed'])
        self.assertFalse(self.q.score_case(self.case('CA01'),{'cancel_proof': ['bad']})['passed'])
        with self.assertRaisesRegex(ValueError,'code'):
            self.q.code_check_tasks(self.case('CD01'),{})

    def test_all_ten_algorithms_execute_the_fixed_forty_vectors(self):
        references=[
            'def solve(a,b):\n while b: a,b=b,a%b\n return a',
            'def solve(s):\n stack=[]\n pairs={")":"(","]":"[","}":"{"}\n for c in s:\n  if c in "([{": stack.append(c)\n  elif not stack or stack.pop()!=pairs[c]: return False\n return not stack',
            'def solve(s):\n out=[]\n for c in s:\n  if out and out[-1][0]==c: out[-1][1]+=1\n  else: out.append([c,1])\n return out',
            'def solve(xs,k):\n if not xs: return []\n k%=len(xs)\n return xs[-k:]+xs[:-k] if k else xs[:]',
            'def solve(xs,target):\n for i in range(len(xs)):\n  for j in range(i+1,len(xs)):\n   if xs[i]+xs[j]==target: return [i,j]\n return []',
            'def solve(intervals):\n out=[]\n for a,b in sorted(intervals):\n  if out and a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)\n  else: out.append([a,b])\n return out',
            'def solve(xs,target):\n lo,hi=0,len(xs)\n while lo<hi:\n  mid=(lo+hi)//2\n  if xs[mid]<target: lo=mid+1\n  else: hi=mid\n return lo if lo<len(xs) and xs[lo]==target else -1',
            'def solve(s):\n return sum(c in "aeiou" for c in s.lower())',
            'def solve(n):\n if n<2: return False\n d=2\n while d*d<=n:\n  if n%d==0: return False\n  d+=1\n return True',
            'def solve(s):\n for c in s:\n  if s.count(c)==1: return c\n return ""',
        ]
        total=0
        for index,code in enumerate(references,1):
            with self.subTest(case=index):
                case=self.case(f'CD{index:02}')
                response=self.response(code)
                result=self.q.check_code_input(self.q.code_check_tasks(case,response)[0]['stdin_json'])
                self.assertTrue(result['passed'],result)
                total+=result['vectors_passed']
                response['code_check']=result
                self.assertTrue(self.q.score_case(case,response)['passed'])
        self.assertEqual(total,40)

    def test_materialize_80_case_count_hashes_and_long_positions_without_spawn(self):
        class Tokens:
            def encode(self,text,**kwargs): return list(text.encode('utf-8'))
        class Template:
            def render(self,messages,**kwargs):
                return '<user>\n'+messages[0]['content']+'\n<assistant>'
        with tempfile.TemporaryDirectory(dir=ROOT/'.vision-tmp') as directory, \
             mock.patch.object(self.q,'_load_tokenizer',return_value=(Tokens(),Template())), \
             mock.patch('subprocess.Popen',side_effect=AssertionError('no spawn')):
            # Use real 80 cases but small long targets for an inexpensive offline fixture.
            value=copy.deepcopy(self.draft)
            for c in value['cases']:
                if c['group']=='long_recall': c['body']['target_rendered_input_tokens']=2048
                c.pop('case_spec_sha256')
                c['case_spec_sha256']=self.q.object_sha(c)
            source=Path(directory)/'draft.json'; source.write_text(json.dumps(value),encoding='utf-8')
            path=self.q.materialize_cases(source,Path(directory),Path(directory)/'materialized')
            ready=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(len(ready['cases']),80)
            self.assertEqual(ready['max_posts'],100)
            self.assertEqual(ready['max_cpu_code_starts'],10)
            for c in ready['cases']:
                for turn in c['turns']:
                    if turn['wire_bindings_pending']:
                        self.assertIsNone(turn['payload_sha256'])
                    else:
                        self.assertEqual(turn['payload_sha256'],self.q.object_sha(turn['body']))
                if c['group']=='long_recall':
                    self.assertEqual(c['turns'][0]['input_tokens'],2048)
                    self.assertEqual(c['fact_token_position'],2048*c['body']['fact_token_position_target']['numerator']//100)

    def test_materialize_rejects_changed_case_hash_and_external_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.vision-tmp') as directory:
            bad=copy.deepcopy(self.draft); bad['cases'][0]['body']['prompt']='changed'
            source=Path(directory)/'draft.json';source.write_text(json.dumps(bad),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'hash'):
                self.q.materialize_cases(source,Path(directory),Path(directory)/'out')
            with self.assertRaisesRegex(ValueError,'StrataMod'):
                self.q.materialize_cases(DRAFT,Path(directory),ROOT.parent/'outside')


if __name__ == '__main__':
    unittest.main()
