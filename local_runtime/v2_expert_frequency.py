"""One predeclared frequency fallback; strict training-only trace validation."""
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys

DELTA_SHA = '6cbb09658df1e9411b3cb4e88487e9a3ce9f8e1b8007cd6aba5e320b293522e6'


def strict_trace(path):
    counts, layers = Counter(), Counter()
    size, records = Path(path).stat().st_size, 0
    with Path(path).open('rb') as stream:
        while stream.tell() < size:
            header = stream.read(8)
            if len(header) != 8: raise ValueError('Truncated trace header')
            layer, k = struct.unpack('<ii', header)
            if not 0 <= layer < 48 or k != 10: raise ValueError('Unexpected layer or routing width')
            payload = stream.read(k * 8)
            if len(payload) != k * 8: raise ValueError('Truncated trace payload')
            ids = struct.unpack_from('<10i', payload)
            weights = struct.unpack_from('<10f', payload, 40)
            if any(not 0 <= expert < 512 for expert in ids): raise ValueError('Invalid expert ID')
            if any(not math.isfinite(weight) for weight in weights): raise ValueError('Nonfinite trace weight')
            counts.update((layer, expert) for expert in ids)
            layers[layer] += 1
            records += 1
    if set(layers) != set(range(48)): raise ValueError('Empty or incomplete layer trace')
    return counts, dict(bytes=size, records=records, layer_records=dict(layers),
                        observed_pairs=len(counts), weight_semantics='serve dummy weights; IDs counted once per row; rejected verify rows included')


def lineage(experiment):
    from .v2_expert_experiment import digest
    inherited = experiment.get('lineage')
    if not inherited: return dict(starts=0, posts=0)
    if inherited['delta_sha256'] != DELTA_SHA: raise RuntimeError('Unexpected fallback plan')
    if digest(inherited['experiment']) != inherited['experiment_sha256']: raise RuntimeError('Parent experiment changed')
    starts, posts = 0, 0
    for reference in inherited['results']:
        if digest(reference['path']) != reference['sha256']: raise RuntimeError('Inherited result changed')
        result = json.loads(Path(reference['path']).read_text(encoding='utf-8'))
        if result['status'] != 'passed': raise RuntimeError('Inherited experiment did not pass')
        starts += result['start_count']; posts += result['post_count']
    if (starts, posts) != (5, 30): raise RuntimeError('Expected exactly five completed pilot/training starts and thirty POSTs')
    return dict(starts=starts, posts=posts)


def extend(parent, directory):
    from .v2_expert_experiment import digest, source_snapshot, write, SHARED, PLAIN
    parent, directory = Path(parent).resolve(), Path(directory).resolve()
    old = json.loads((parent / 'experiment.json').read_text(encoding='utf-8'))
    if digest(SHARED) != old['shared_sha256'] or digest(PLAIN) != old['normal_sha256']:
        raise RuntimeError('Normal or shared baseline changed')
    names = ('learn', 'pilot-A', 'pilot-P', 'pilot-R', 'pilot-PR')
    results = [dict(path=str(parent / name / 'result.json'), sha256=digest(parent / name / 'result.json')) for name in names]
    value = dict(old, sources=source_snapshot(), limits=dict(starts=11, posts=72), frequency_ram_gib=32,
                 lineage=dict(experiment=str(parent / 'experiment.json'), experiment_sha256=digest(parent / 'experiment.json'),
                              delta_sha256=DELTA_SHA, results=results))
    lineage(value)
    if (digest(parent / 'suite.json') != old['suite_sha256'] or
            digest(parent / 'normal-profile.json') != old['normal_sha256'] or
            digest(parent / 'base-profile.bin') != old['profile']['sha256']):
        raise RuntimeError('Parent frozen inputs changed')
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('suite.json', 'normal-profile.json', 'base-profile.bin'):
        shutil.copy2(parent / name, directory / name)
    value['profile'] = dict(value['profile'], path=str(directory / 'base-profile.bin'))
    write(directory / 'experiment.json', value)
    return value


def build(directory):
    from .v2_expert_experiment import digest, write, check_profile, ROOT, source_snapshot, SHARED
    directory = Path(directory).resolve()
    experiment = json.loads((directory / 'experiment.json').read_text(encoding='utf-8'))
    lineage(experiment)
    if source_snapshot() != experiment['sources']: raise RuntimeError('Reviewed frequency source changed')
    if digest(SHARED) != experiment['shared_sha256']: raise RuntimeError('Shared profile changed')
    result_path = directory / 'trace/result.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    suite = json.loads((directory / 'suite.json').read_text(encoding='utf-8'))
    if digest(directory / 'suite.json') != experiment['suite_sha256']: raise RuntimeError('Frozen suite changed')
    if (result['status'] != 'passed' or result['arm'] != 'trace' or result['post_count'] != 6 or
            [row['case'] for row in result['samples']] != [row['name'] for row in suite['training']]):
        raise RuntimeError('Exactly six successful frozen training requests required')
    trace = directory / 'trace/routing.bin'
    counts, stats = strict_trace(trace)
    offset = 0
    for row in result['samples']:
        if row['trace_before_bytes'] != offset or row['trace_after_bytes'] <= offset or row['trace_after_bytes'] % 88:
            raise RuntimeError('Training trace request boundaries are incomplete')
        offset = row['trace_after_bytes']
    if offset != stats['bytes']: raise RuntimeError('Trace contains bytes outside frozen training requests')
    target = directory / 'frequency-profile.bin'
    if target.exists() or (directory / 'frequency-proof.json').exists(): raise RuntimeError('Only one frozen frequency candidate is permitted')
    completed = subprocess.run([sys.executable, str(ROOT / 'tools/make_profile.py'), str(trace), '--no-base',
                                '--n-expert', '512', '--out', str(target)], cwd=str(ROOT),
                               check=True, capture_output=True, text=True, encoding='utf-8')
    (directory / 'frequency-build.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    info = check_profile(target)
    from tools.make_profile import rank_profile, read_profile
    expected, _ = rank_profile([], counts, no_base=True)
    if read_profile(target) != expected: raise RuntimeError('Official frequency rank roundtrip differs')
    proof = dict(profile=info, trace_path=str(trace), trace_sha256=digest(trace), trace=stats,
                 training_result_sha256=digest(result_path), ram_gib=32, delta_sha256=DELTA_SHA,
                 ranking='raw per-row ID frequency descending; tie (layer, expert); official interleaved unseen fill',
                 top_pairs=[dict(layer=l, expert=e, count=c) for (l, e), c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:50]])
    write(directory / 'frequency-proof.json', proof)
    return proof
