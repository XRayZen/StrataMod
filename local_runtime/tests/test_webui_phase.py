"""Fake WebUI pipes/lifecycle only; no Node, browser, HTTP, SDK or GPU."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import contextlib

from local_runtime import webui_phase as phase


def digest(value):
    return hashlib.sha256(value).hexdigest()


class Pipe(io.BytesIO):
    def close(self):
        self.was_closed = True


class FakeReader:
    def __init__(self, events, process):
        self.events, self.process = list(events), process
        self.close_reader = Mock(return_value=True)

    def read_event(self, timeout):
        if self.events:
            return dict(kind='webui', event=self.events.pop(0))
        self.process.returncode = 0
        return dict(kind='eof')


class WebUIPhaseTests(unittest.TestCase):
    SENTINEL=b'\xff\xd8\xffopaque-non-decodable-routing-sentinel'

    def setUp(self):
        self.enterContext(patch.object(phase,'REFERENCE_SHA',digest(self.SENTINEL)))

    def fixture(self, directory):
        image = self.SENTINEL
        config = dict(url='http://127.0.0.1:18080/', browser_exe='fixed-edge',
                      profile_dir=str(directory/'profile'), image_path=str(phase.REFERENCE_IMAGE),
                      image_sha256=digest(image), prompt='Read this image.', max_tokens=128, deadline_seconds=120)
        body = dict(stream=True, max_tokens=128, reasoning_effort='none', temperature=0, seed=42,
                    messages=[dict(role='user', content=[dict(type='text', text=config['prompt']),
                        dict(type='image_url', image_url=dict(url='data:image/jpeg;base64,' + base64.b64encode(image).decode()))])])
        request = json.dumps(body)
        usage = dict(prompt_tokens=9, completion_tokens=2, total_tokens=11)
        raw = 'data: ' + json.dumps(dict(choices=[dict(delta=dict(content='answer'), finish_reason=None)])) + '\n\n'
        raw += 'data: ' + json.dumps(dict(choices=[dict(delta={}, finish_reason='stop')], usage=usage)) + '\n\n'
        raw += 'data: [DONE]\n\n'
        events = [dict(type='attachment', file_input='#file', set_input_files_returned=True, selected_files=1,
                       image_path=config['image_path'], image_sha256=config['image_sha256'],
                       preview=dict(kind='filename_chip', text=phase.REFERENCE_IMAGE.name, image_thumbnail=False)),
                  dict(type='generation_request', url=config['url']+'v1/chat/completions', method='POST', count=1,
                       post_data_json=body, post_data_utf8=request, full_wire_sha256=digest(request.encode())),
                  dict(type='final_answer', text='answer', api_status=200, generation_count=1,
                       user_image_preview_sha256=config['image_sha256'], api_response=dict(content='answer',
                       finish_reason='stop', usage=usage, response_sha256=digest(raw.encode()), response_utf8=raw)),
                  dict(type='closed', context_close_returned=True, cleanup_verified=False,
                       process_proof_owner='runtime', generation_count=1)]
        return config, events

    @contextlib.contextmanager
    def harness(self, *, events=None, cleanup_complete=True):
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as stack:
            directory = Path(folder)
            config, defaults = self.fixture(directory)
            events = defaults if events is None else events(defaults)
            state = dict(manifest='fixed-manifest', manifest_sha256='fixed-sha')
            value = dict(config=str(directory/'server.json'), max_posts=7, webui_input=config)
            result = dict(post_count=4, browser_start_count=0)
            retained = {}
            process = Mock(returncode=None, stdin=Pipe(), stdout=Pipe())
            process.poll.side_effect = lambda: process.returncode
            rows = [dict(pid=101, created=1.0, exe='node.exe'), dict(pid=102, created=2.0, exe='driver.exe'),
                    dict(pid=103, created=3.0, exe='msedge.exe')]
            observation = dict(created=1.0, identities=rows, unknown=[], errors=[])
            observer = Mock()
            observer.snapshot.return_value = observation
            observer.finish_standalone.return_value = observation
            auxstate = dict(pid=101, created=1.0, owned_identities=rows, cleanup_pending=True)
            reader = FakeReader(events, process)

            def start(path, sha, *, parent_state, retained, before_spawn, persist_aux):
                self.assertIs(retained, harness.retained['auxiliary'])
                self.assertEqual((result['post_count'], result['browser_start_count']), (5, 1))
                before_spawn()
                retained.update(state=auxstate, process=process, observer=observer, spawn_possible=True)
                persist_aux(auxstate)
                return process, observer, auxstate

            for target, name, options in [
                (phase.official_runtime, 'start_webui', dict(side_effect=start, create=True)),
                (phase.runner, 'ready', dict()),
                (phase.runner, 'pending_exit_proof', dict(return_value=dict(complete=cleanup_complete, members=rows))),
                (phase.safety, 'save', dict()), (phase.safety, 'require_owned_listener', dict()),
                (phase.safety, 'get_json', dict(return_value=dict(busy=False, queued=0))),
                (phase.safety, 'process_identity_status', dict(return_value=Mock(status='verified'))),
                (phase.safety, 'stop_owned', dict()),
                (phase.official_runtime.checked_job, 'membership_pid', dict(return_value=True)),
                (phase, 'WebUIIO', dict(return_value=reader))]:
                stack.enter_context(patch.object(target, name, **options))
            harness = Mock(state=state, value=value, result=result, retained=retained, process=process,
                           observer=observer, auxstate=auxstate, reader=reader, events=events, monitor=Mock())
            yield harness

    def test_one_reserved_upload_validates_wire_and_separately_proves_all_births_gone(self):
        with self.harness() as h:
            result = phase.run(h.state, h.monitor, h.value, h.result, h.retained)
            self.assertEqual((h.result['post_count'], h.result['browser_start_count']), (5, 1))
            self.assertEqual(result['physical_aux_process_starts'], 3)
            self.assertTrue(result['protocol']['completed'])
            self.assertTrue(result['cleanup']['complete'])
            self.assertFalse(result['events'][-1]['cleanup_verified'])
            self.assertEqual(h.state['webui_auxiliary']['cleanup_pending'], False)
            self.assertTrue(h.process.stdin.was_closed)
            self.assertEqual(json.loads(h.process.stdin.getvalue()), h.value['webui_input'])
            phase.runner.pending_exit_proof.assert_called_with(h.retained['auxiliary'], require_port=False)
            phase.safety.save.assert_called()
            self.assertTrue(all(call.args[0] is h.state for call in phase.safety.save.call_args_list))

    def test_bad_order_extra_post_wrong_wire_or_script_error_never_passes(self):
        def wrong_wire(events):
            events[1]['full_wire_sha256'] = '0'*64
            return events
        variants = [lambda e: [e[1], e[0], *e[2:]], lambda e: [*e[:2], copy.deepcopy(e[1]), *e[2:]],
                    lambda e: e[:-1], wrong_wire,
                    lambda e: [e[0], dict(type='error', stage='generation', message='original failure')]]
        for change in variants:
            with self.subTest(change=change), self.harness(events=change) as h:
                with self.assertRaises((ValueError, RuntimeError)):
                    phase.run(h.state, h.monitor, h.value, h.result, h.retained)
                self.assertEqual(h.result['webui']['status'], 'failed')
                phase.safety.stop_owned.assert_called_once_with(h.auxstate, official_first=False)
                phase.runner.pending_exit_proof.assert_called_with(h.retained['auxiliary'], require_port=False)
                self.assertEqual(h.result['post_count'], 5)

    def test_reader_or_save_secondary_error_cannot_skip_stop_and_original_error(self):
        for secondary in ('reader', 'save'):
            with self.subTest(secondary=secondary), self.harness(events=lambda e: [dict(type='error', message='original failure')]) as h:
                if secondary == 'reader':
                    h.reader.close_reader.side_effect = SystemExit('reader failed')
                else:
                    def save(state):
                        if h.reader.close_reader.called:
                            raise OSError('save failed')
                    phase.safety.save.side_effect = save
                with self.assertRaisesRegex(RuntimeError, 'original failure'):
                    phase.run(h.state, h.monitor, h.value, h.result, h.retained)
                phase.safety.stop_owned.assert_called_once()
                phase.runner.pending_exit_proof.assert_called()
                self.assertTrue(h.auxstate['cleanup_pending'])
                self.assertTrue(h.result['webui']['cleanup_errors'])

    def test_early_launch_failure_retains_auxiliary_and_still_attempts_cleanup(self):
        with self.harness() as h:
            original = phase.official_runtime.start_webui.side_effect
            def start(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError('launch registration failed')
            phase.official_runtime.start_webui.side_effect = start
            with self.assertRaisesRegex(OSError, 'launch registration failed'):
                phase.run(h.state, h.monitor, h.value, h.result, h.retained)
            phase.safety.stop_owned.assert_called_once()
            self.assertIs(h.retained['auxiliary']['process'], h.process)

    def test_busy_budget_job_unknown_and_deadline_fail_closed(self):
        for failure in ('busy', 'budget', 'job', 'unknown', 'deadline'):
            with self.subTest(failure=failure), self.harness() as h, contextlib.ExitStack() as stack:
                if failure == 'busy':phase.safety.get_json.return_value = dict(busy=True, queued=0)
                if failure == 'budget':h.result['post_count'] = 5
                if failure == 'job':phase.official_runtime.checked_job.membership_pid.return_value = False
                if failure == 'unknown':h.observer.snapshot.return_value['unknown'] = [dict(pid=999)]
                if failure == 'deadline':stack.enter_context(patch.object(phase.time, 'monotonic', side_effect=[0, 121, 121, 121, 121]))
                with self.assertRaises((RuntimeError, TimeoutError)):
                    phase.run(h.state, h.monitor, h.value, h.result, h.retained)
                if failure in ('busy', 'budget'):
                    phase.official_runtime.start_webui.assert_not_called()
                elif failure == 'deadline':
                    self.assertNotIn('process', h.retained['auxiliary'])
                    self.assertTrue(h.result['webui']['cleanup']['zero_spawn'])
                else:
                    self.assertIsNotNone(h.retained['auxiliary']['process'])

    def test_closed_context_never_substitutes_for_reader_and_cohort_exit(self):
        for failure in ('reader', 'cohort'):
            with self.subTest(failure=failure), self.harness(cleanup_complete=failure != 'cohort') as h, contextlib.ExitStack() as stack:
                if failure == 'reader':
                    h.reader.close_reader.return_value = False
                clock = iter(range(1000))
                stack.enter_context(patch.object(phase.time, 'monotonic', side_effect=lambda: next(clock)))
                stack.enter_context(patch.object(phase.time, 'sleep'))
                with self.assertRaisesRegex(RuntimeError, 'cleanup remains pending'):
                    phase.run(h.state, h.monitor, h.value, h.result, h.retained)
                self.assertTrue(h.auxstate['cleanup_pending'])
                self.assertFalse(h.result['webui']['cleanup']['complete'])
                phase.safety.stop_owned.assert_called_once()

    def test_auxiliary_memory_is_measured_per_birth_or_explicitly_missing(self):
        for missing in (False, True):
            with self.subTest(missing=missing), self.harness() as h:
                process = Mock()
                if missing:
                    process.memory_info.side_effect = OSError('counter unavailable')
                else:
                    process.memory_info.return_value = Mock(rss=4096, private=8192)
                phase.safety.process_identity_status.return_value = Mock(status='verified', process=process)
                result = phase.run(h.state, h.monitor, h.value, h.result, h.retained)
                samples = result['auxiliary_memory_samples']
                self.assertEqual(samples[0]['label'], 'before-input')
                self.assertTrue({'attachment', 'generation_request', 'final_answer', 'closed'}.issubset({s['label'] for s in samples}))
                for sample in samples:
                    self.assertEqual(len(sample['processes']), 3)
                    for row in sample['processes']:
                        self.assertEqual(row['rss_bytes'], None if missing else 4096)
                        self.assertEqual(row['private_bytes'], None if missing else 8192)
                        self.assertEqual('error_type' in row, missing)

    def test_final_observer_birth_is_included_in_physical_process_count(self):
        with self.harness() as h:
            observation = copy.deepcopy(h.observer.snapshot.return_value)
            observation['identities'].append(dict(pid=104, created=4.0, exe='msedge.exe'))
            h.observer.finish_standalone.return_value = observation
            result = phase.run(h.state, h.monitor, h.value, h.result, h.retained)
            self.assertEqual(result['physical_aux_process_starts'], 4)
            self.assertEqual(h.result['physical_aux_process_starts'], 4)
            self.assertIn(104, [row['pid'] for row in result['auxiliary_identities']])

    def test_jsonl_reader_retains_large_valid_line_and_rejects_malformed_or_truncated(self):
        with tempfile.TemporaryDirectory() as folder:
            _, events = self.fixture(Path(folder))
            events[2]['text'] = events[2]['api_response']['content'] = 'x'*10000
            events[2]['api_response']['response_utf8'] = 'data: ' + json.dumps(dict(
                choices=[dict(delta=dict(content='x'*10000), finish_reason='stop')])) + '\n\ndata: [DONE]\n\n'
            line = b''.join(json.dumps(event).encode() + b'\n' for event in events)
            reader = phase.WebUIIO(None, io.BytesIO(line), Path(folder)/'valid.raw')
            self.assertTrue(reader.close_reader(2))
            for expected in events:
                self.assertEqual(reader.read_event(0)['event'], expected)
            self.assertEqual(reader.read_event(0), dict(kind='eof'))
            self.assertEqual((Path(folder)/'valid.raw').read_bytes(), line)
            for index, raw in enumerate([b'{bad}\n', b'{"type":"closed"}', b'{"type":"closed","type":"error"}\n']):
                reader = phase.WebUIIO(None, io.BytesIO(raw), Path(folder)/f'bad-{index}.raw')
                self.assertTrue(reader.close_reader(2))
                self.assertEqual(reader.read_event(0)['kind'], 'error')

    def test_jsonl_finite_line_and_total_boundaries_reject_overflow(self):
        self.assertEqual(phase.WebUIIO.MAX_LINE_BYTES, 32*1024*1024)
        self.assertEqual(phase.WebUIIO.MAX_TOTAL_BYTES, 40*1024*1024)
        class SmallBudget(phase.WebUIIO):
            MAX_LINE_BYTES = 1024
            MAX_TOTAL_BYTES = 2048
        def line(size):
            empty = b'{"type":"closed","padding":""}\n'
            return b'{"type":"closed","padding":"' + b'x'*(size-len(empty)) + b'"}\n'
        with tempfile.TemporaryDirectory() as folder:
            for index, (raw, good) in enumerate([(line(1024), True), (line(1024)*2, True),
                                                  (line(1025), False), (line(1024)*2+line(32), False)]):
                reader = SmallBudget(None, io.BytesIO(raw), Path(folder)/f'limit-{index}.raw')
                self.assertTrue(reader.close_reader(2))
                event = reader.read_event(0)
                self.assertEqual(event['kind'] != 'error', good)
                if not good:
                    self.assertEqual(reader.read_event(0)['kind'], 'error')  # sticky


if __name__ == '__main__':
    unittest.main()
