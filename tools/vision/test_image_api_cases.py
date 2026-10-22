"""CPU-only contract tests; no server, SDK, processes or network."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest

from tools.vision.image_api_cases import fixed_cases, parse_sse, score_known_answer


def wire(*events):
    return ''.join(('data: [DONE]\n\n' if e == '[DONE]' else
                    ('event: ' + e['type'] + '\n' if 'type' in e else '')
                    + 'data: ' + json.dumps(e) + '\n\n') for e in events)


# Opaque signature sentinels test MIME/routing, not decoding or image meaning.
API_BYTES = b'\x89PNG\r\n\x1a\nsynthetic-non-decodable-payload'
UI_BYTES = b'\xff\xd8\xffsynthetic-non-decodable-payload'
API_SHA = hashlib.sha256(API_BYTES).hexdigest()
UI_SHA = hashlib.sha256(UI_BYTES).hexdigest()
EXPECTED_API07 = dict(people=1,
    hair=['明るい茶色', '明るい茶', '茶色', '茶', '金色', '金', 'ブロンド', '金髪', '薄茶色',
          'light brown', 'brown', 'blonde', 'blond', 'golden', 'golden brown'],
    top=['紺', '紺色', '濃紺', '濃紺色', '濃い青', '濃い青色', '濃青', '濃青色', 'ネイビー',
         'navy', 'navy blue', 'dark blue', 'dark navy', '紺色の制服', 'navy uniform', 'dark blue uniform'],
    scene=['教室', '学校の教室', 'classroom', 'a classroom', 'school classroom'],
    object=['机', 'デスク', '学習机', '学校の机', 'desk', 'school desk', 'table', 'school table'],
    position=['左', '画面左', '画面の左', '左側', '画面左側', '画像の左', '左手前', '画面左手前',
              '左下', '画面左下', '画像の左下', '手前', 'left', 'left side', 'left foreground',
              'lower left', 'bottom left', 'foreground', 'front', 'front left'])
EXPECTED_WEBUI484 = dict(people=1,
    hair=['橙', '橙色', 'オレンジ', 'オレンジ色', '赤茶', '赤茶色', '茶色', '茶',
          'orange', 'auburn', 'reddish brown', 'red brown', 'brown'],
    top=['白', '白色', '白い', '白い上着', '白いシャツ', 'white', 'white jacket', 'white shirt', 'white blouse'],
    scene=['寝室', 'ベッドのある部屋', 'ベッドがある部屋', 'bedroom', 'a bedroom', 'room with a bed', 'bed room'],
    object=['ベッド', 'bed', 'a bed'],
    position=['右', '画面右', '画面の右', '右側', '画面右側', '画像の右', '右下', '画面右下', '画像の右下',
              'right', 'right side', 'lower right', 'bottom right'])


class ImageCasesTests(unittest.TestCase):
    def test_fixed_payloads_embed_the_synthetic_bytes_exactly(self):
        png = API_BYTES
        encoded = base64.b64encode(png).decode('ascii')
        cases = fixed_cases(encoded, 'huihui-ud-iq4_xs')
        self.assertEqual([c['api'] for c in cases], ['openai', 'anthropic', 'responses'])
        for case in cases:
            body = case['body']
            self.assertTrue(body['stream'])
            self.assertEqual((body['temperature'], body['seed']), (0, 42))
            parts = (body.get('messages') or body['input'])[0]['content']
            prompt = parts[0]['text']
            for value in ['紺', '白色', '教室', '寝室', '机', 'ベッド', '画面左', '画面右']:
                self.assertNotIn(value, prompt)
            image = parts[1]
            actual = image['source']['data'] if case['api'] == 'anthropic' else (
                image['image_url']['url'] if case['api'] == 'openai' else image['image_url']).split(',', 1)[1]
            self.assertEqual(base64.b64decode(actual), png)
            self.assertEqual(case['image_sha256'], API_SHA)
            self.assertEqual(body.get('max_tokens', body.get('max_output_tokens')), 128)
        self.assertEqual(cases[1]['body']['thinking'], {'type': 'disabled'})
        self.assertEqual(cases[2]['body']['reasoning'], {'effort': 'none'})
        for cap in [0, 127, 129, True]:
            with self.assertRaises(ValueError):
                fixed_cases(encoded, 'model', cap)
        with self.assertRaises(ValueError):
            fixed_cases('not base64!', 'model')
        jpeg = base64.b64encode(UI_BYTES).decode('ascii')
        for case in fixed_cases(jpeg, 'model', image_mime='image/jpeg'):
            self.assertEqual(case['image_sha256'], UI_SHA)
        for mime, data in [('image/png', jpeg), ('image/jpeg', encoded), ('image/webp', encoded)]:
            with self.assertRaises(ValueError):
                fixed_cases(data, 'model', image_mime=mime)

    def streams(self):
        return {
            'openai': wire({'choices': [{'index': 0, 'delta': {'content': 'hello'}, 'finish_reason': None}]},
                           {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                            'usage': {'prompt_tokens': 9, 'completion_tokens': 2, 'total_tokens': 11},
                            'timings': {'prompt_n': 9, 'predicted_n': 2}}, '[DONE]'),
            'anthropic': wire({'type': 'message_start', 'message': {'usage': {'input_tokens': 9, 'output_tokens': 0}}},
                              {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                              {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'hello'}},
                              {'type': 'content_block_stop', 'index': 0},
                              {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'},
                               'usage': {'input_tokens': 8, 'cache_read_input_tokens': 1, 'output_tokens': 2}},
                              {'type': 'message_stop'}),
            'responses': wire({'type': 'response.created', 'response': {'status': 'in_progress'}},
                              {'type': 'response.output_text.delta', 'delta': 'hello'},
                              {'type': 'response.completed', 'response': {'status': 'completed', 'error': None,
                               'usage': {'input_tokens': 9, 'output_tokens': 2, 'total_tokens': 11}}})}

    def test_three_successful_sse_protocols_and_real_usage_only(self):
        for api, raw in self.streams().items():
            with self.subTest(api=api):
                result = parse_sse(api, raw.encode())
                self.assertEqual(result['text'], 'hello')
                self.assertTrue(result['terminal'])
                self.assertTrue(result['normal_terminal'], result['errors'])
                self.assertTrue(result['completed'])
                self.assertEqual(result['output_tokens'], 2)
                self.assertTrue(result['usage_sources'])
                self.assertEqual(result['timings'] is None, api != 'openai')
                # Removing the terminal marker or truncating its frame must fail.
                self.assertFalse(parse_sse(api, raw.rsplit('\n\n', 2)[0] + '\n\n')['normal_terminal'])
                self.assertFalse(parse_sse(api, raw[:-1])['normal_terminal'])
        result = parse_sse('openai', wire({'choices': [{'delta': {}, 'finish_reason': 'stop'}]}, '[DONE]'))
        self.assertIsNone(result['usage'])
        self.assertIsNone(result['output_tokens'])
        self.assertIsNone(result['timings'])

    def test_limits_are_terminal_but_never_natural_completion(self):
        streams = self.streams()
        streams['openai'] = streams['openai'].replace('"stop"', '"length"')
        streams['anthropic'] = streams['anthropic'].replace('"end_turn"', '"max_tokens"')
        streams['responses'] = streams['responses'].replace('response.completed', 'response.incomplete').replace(
            '"status": "completed"', '"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}')
        for api, raw in streams.items():
            result = parse_sse(api, raw)
            self.assertTrue(result['normal_terminal'], result['errors'])
            self.assertFalse(result['completed'])
            self.assertEqual(result['finish_reason'], 'length')

    def test_bad_sse_never_certifies_success_or_invents_counts(self):
        for api, raw in self.streams().items():
            for bad in [raw + raw, raw + 'data: {bad}\n\n', raw.replace('"output_tokens": 2', '"output_tokens": true').replace(
                    '"completion_tokens": 2', '"completion_tokens": true')]:
                self.assertFalse(parse_sse(api, bad)['normal_terminal'])
        failed = parse_sse('responses', wire({'type': 'response.created', 'response': {}},
                           {'type': 'response.failed', 'response': {'status': 'failed', 'error': {'message': 'broken'}}}))
        self.assertTrue(failed['terminal'])
        self.assertFalse(failed['normal_terminal'])
        self.assertIsNone(failed['output_tokens'])
        self.assertFalse(parse_sse('openai', 'data: {"choices":[],"choices":[]}\n\ndata: [DONE]\n\n')['normal_terminal'])

    def test_refimage_required_facts_and_auxiliary_hair_use_private_finite_rubrics(self):
        for expected in (EXPECTED_API07, EXPECTED_WEBUI484):
            answer = {key: values[0] if isinstance(values, list) else values for key, values in expected.items()}
            self.assertTrue(score_known_answer(json.dumps(answer), expected)['passed'])
            for key in ('top', 'scene', 'object', 'position'):
                for phrase in expected[key]:
                    changed = dict(answer, **{key: phrase})
                    self.assertTrue(score_known_answer(json.dumps(changed), expected)['passed'], phrase)
                changed = dict(answer, **{key: 'not ' + expected[key][0]})
                self.assertFalse(score_known_answer(json.dumps(changed), expected)['passed'])
                changed[key] = 'unknown'
                self.assertFalse(score_known_answer(json.dumps(changed), expected)['passed'])
            answer['hair'] = 'unknown auxiliary color'
            result = score_known_answer(json.dumps(answer), expected)
            self.assertTrue(result['passed'])
            self.assertFalse(result['auxiliary']['hair']['matched'])
            for count in (2, True, '1', 1.0):
                answer['people'] = count
                self.assertFalse(score_known_answer(json.dumps(answer), expected)['passed'])
        answer = dict(people=1, hair='brown', top='white', scene='bedroom', object='bed', position='right')
        self.assertFalse(score_known_answer(json.dumps(answer), EXPECTED_API07)['passed'])
        for key, wrong in [('top', 'navy'), ('scene', 'classroom'), ('object', 'desk'), ('position', 'left')]:
            changed = dict(answer, **{key: wrong})
            self.assertFalse(score_known_answer(json.dumps(changed), EXPECTED_WEBUI484)['passed'])
        for text in ['plain prose', '{"people":1,"people":1}', '```json\n' + json.dumps(answer) + '\n```']:
            self.assertFalse(score_known_answer(text, EXPECTED_WEBUI484)['passed'])

    def test_official_frontend_conversions_and_responses_assembler(self):
        from serve.frontend import (anthropic_to_messages, images_of, openai_to_messages, Event)
        from serve.responses import Assembler, input_messages, template_kwargs
        png = API_BYTES
        cases = fixed_cases(base64.b64encode(png).decode('ascii'), 'model')
        for case in cases:
            body, api = case['body'], case['api']
            if api == 'openai':
                messages, _, kwargs = openai_to_messages(body)
            elif api == 'anthropic':
                messages, _, kwargs = anthropic_to_messages(body)
            else:
                messages = input_messages(body)
                kwargs = template_kwargs(body, {})
            self.assertFalse(kwargs['enable_thinking'])
            self.assertEqual(images_of(messages), ['data:image/png;base64,' + base64.b64encode(png).decode('ascii')])
        assembler = Assembler(cases[-1]['body'], 'model', 9, {}, False)
        events = assembler.start() + assembler.feed(Event(kind='content', text='hello'))
        events += assembler.finish({'finish': 'stop', 'completion_tokens': 2, 'prompt_tokens': 9})
        result = parse_sse('responses', wire(*events))
        self.assertTrue(result['completed'], result['errors'])
        self.assertEqual((result['text'], result['output_tokens']), ('hello', 2))

    def test_nonfinite_timing_and_anthropic_provisional_usage(self):
        raw = self.streams()['openai'].replace('"prompt_n": 9', '"prompt_n": 1e999')
        self.assertFalse(parse_sse('openai', raw)['normal_terminal'])
        raw = wire({'type': 'message_start', 'message': {'usage': {'input_tokens': 9, 'output_tokens': 0}}})
        result = parse_sse('anthropic', raw)
        self.assertIsNone(result['output_tokens'])
        self.assertEqual(result['usage'], {'input_tokens': 9, 'output_tokens': 0})
        self.assertFalse(result['normal_terminal'])


if __name__ == '__main__':
    unittest.main()
