import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from local_runtime import v2_expert_experiment as exp
from local_runtime import v2_expert_frequency as freq


def record(layer, ids=tuple(range(10)), weights=(0.,) * 10):
    return struct.pack('<ii10i10f', layer, 10, *ids, *weights)


class FrequencyTests(unittest.TestCase):
    def test_strict_complete_records_and_all_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'routing.bin'
            valid = b''.join(record(layer) for layer in range(48))
            path.write_bytes(valid)
            counts, stats = freq.strict_trace(path)
            self.assertEqual(stats['records'], 48)
            self.assertEqual(counts[(47, 9)], 1)
            for broken in (b'', valid + b'x', valid[:-1], valid[88:],
                           record(48) + valid, record(0, ids=(512,) * 10) + valid,
                           record(0, weights=(float('nan'),) * 10) + valid,
                           struct.pack('<ii', 0, 8) + valid):
                path.write_bytes(broken)
                with self.assertRaises(ValueError): freq.strict_trace(path)

    def test_only_trace_adds_dump_without_save_and_F_is_fixed_32(self):
        base = dict(model_name=exp.MODEL, args=['--expert-profile', 'base.bin', '--resident-budget-gib', '16',
                    '--prompt-cache', '6', '--max-context', '262144'], vision={'temp_dir': 'old'})
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            trace = exp.trial_config(base, directory, 'trace', Path('base.bin'))
            self.assertEqual(exp.option(trace['args'], '--dump-routing'), str(directory / 'routing.bin'))
            self.assertEqual(exp.option(trace['args'], '--resident-budget-gib'), '16')
            self.assertNotIn('expert_profile_save', trace)
            candidate = exp.trial_config(base, directory, 'F', Path('freq.bin'))
            self.assertEqual(exp.option(candidate['args'], '--resident-budget-gib'), '32')
            self.assertNotIn('--dump-routing', candidate['args'])

    def test_sha_lineage_preserves_five_starts_thirty_posts_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            parent = directory / 'parent.json'
            exp.write(parent, {'old': True})
            refs = []
            for index in range(5):
                path = directory / f'result-{index}.json'
                exp.write(path, dict(status='passed', start_count=1, post_count=6))
                refs.append(dict(path=str(path), sha256=exp.digest(path)))
            value = dict(lineage=dict(experiment=str(parent), experiment_sha256=exp.digest(parent),
                                     delta_sha256=freq.DELTA_SHA, results=refs))
            self.assertEqual(freq.lineage(value), {'starts': 5, 'posts': 30})
            exp.write(Path(refs[0]['path']), dict(status='passed', start_count=0, post_count=0))
            with self.assertRaisesRegex(RuntimeError, 'Inherited result changed'): freq.lineage(value)

    def test_official_no_base_frequency_build_is_unique_and_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'trace').mkdir()
            trace = directory / 'trace/routing.bin'
            blob = b''.join(record(layer) for _ in range(6) for layer in range(48))
            trace.write_bytes(blob)
            samples = [dict(case=f'learn-{i}', trace_before_bytes=i * 48 * 88,
                            trace_after_bytes=(i + 1) * 48 * 88) for i in range(6)]
            exp.write(directory / 'trace/result.json', dict(status='passed', arm='trace', post_count=6, samples=samples))
            exp.write(directory / 'suite.json', {'training': [{'name': f'learn-{i}'} for i in range(6)]})
            exp.write(directory / 'experiment.json', dict(sources=exp.source_snapshot(),
                      suite_sha256=exp.digest(directory / 'suite.json'), shared_sha256=exp.digest(exp.SHARED)))
            proof = freq.build(directory)
            self.assertEqual(proof['profile']['pairs'], 24576)
            self.assertEqual(proof['ram_gib'], 32)
            self.assertEqual(proof['top_pairs'][0], {'layer': 0, 'expert': 0, 'count': 6})
            with self.assertRaisesRegex(RuntimeError, 'Only one'): freq.build(directory)

    def test_new_directory_does_not_reset_consumed_start_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            shared = directory / 'shared.bin'
            normal = directory / 'normal-profile.json'
            shared.write_bytes(b'shared')
            exp.write(normal, {})
            exp.write(directory / 'suite.json', {})
            exp.write(directory / 'experiment.json', dict(normal_sha256=exp.digest(normal),
                      shared_sha256=exp.digest(shared), suite_sha256=exp.digest(directory / 'suite.json'),
                      sources={}, limits={'starts': 11, 'posts': 72}))
            for index in range(6):
                trial = directory / f'new-trial-{index}'
                trial.mkdir()
                exp.write(trial / 'result.json', dict(status='passed', start_count=1, post_count=6))
            with patch.object(exp, 'SHARED', shared), patch.object(exp, 'PLAIN', normal), \
                 patch.object(exp, 'source_snapshot', return_value={}), \
                 patch.object(freq, 'lineage', return_value={'starts': 5, 'posts': 30}):
                with self.assertRaisesRegex(RuntimeError, 'start budget exhausted'):
                    exp.run(directory, 'A', 'forbidden-seventh-new-start')
            self.assertFalse((directory / 'forbidden-seventh-new-start').exists())


if __name__ == '__main__': unittest.main()
