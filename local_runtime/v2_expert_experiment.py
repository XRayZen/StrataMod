"""Private V2 profile/RAM experiment; normal launching and defaults are untouched."""
import argparse
import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import sys
import time
import urllib.request

import psutil

from . import benchmark, checked_job, evaluate_r9700 as runner, manifest
from . import official_runtime, runtime_safety as safety

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'huihui-ud-q4_k_xl_v2'
GIB = 2 ** 30
PLAIN = ROOT / 'local_runtime/normal/plain-profile.json'
SHARED = ROOT.parent / 'Strata/data/expert-profile.bin'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    def safe(item):
        if isinstance(item, float) and not math.isfinite(item):
            return {'invalid_nonfinite_number': str(item)}
        if isinstance(item, dict): return {key: safe(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)): return [safe(child) for child in item]
        return item
    path.write_text(json.dumps(safe(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def option(args, name):
    if args.count(name) != 1 or args.index(name) + 1 == len(args):
        raise ValueError('Expected one option: ' + name)
    return args[args.index(name) + 1]


def set_option(args, name, value):
    i = args.index(name) if name in args else len(args)
    if args.count(name) > 1:
        raise ValueError('Repeated option: ' + name)
    if i == len(args): args.extend([name, str(value)])
    else: args[i + 1] = str(value)


def write_profile(path, pairs):
    from tools.make_profile import write_profile as official_write
    official_write(path, pairs)


def check_profile(path):
    data = Path(path).read_bytes()
    if len(data) != 24 + 8 * 24576 or struct.unpack_from('<4s5I', data) != (b'STRP', 1, 48, 512, 24576, 24576):
        raise ValueError('Wrong full V2 profile shape')
    pairs = list(struct.iter_unpack('<HH', data[24:24 + 4 * 24576]))
    if set(pairs) != {(l, e) for l in range(48) for e in range(512)}:
        raise ValueError('Missing, invalid or duplicate profile pairs')
    table = struct.unpack_from('<24576i', data, 24 + 4 * 24576)
    if any(table[l * 512 + e] != rank for rank, (l, e) in enumerate(pairs)):
        raise ValueError('Profile reverse index disagrees with ranking')
    return dict(path=str(Path(path).resolve()), sha256=digest(path), pairs=len(pairs), layers=48)


def trial_config(base, directory, arm, profile):
    if arm not in ('learn', 'trace', 'F', 'A', 'P', 'R', 'PR'):
        raise ValueError('Unknown finite arm')
    cfg = copy.deepcopy(base)
    if any(key.startswith('expert_profile_save') for key in cfg) or any(
            arg.startswith('--expert-profile-save') for arg in cfg['args']):
        raise ValueError('Normal profile unexpectedly enables profile saving')
    if cfg['model_name'] != MODEL or option(cfg['args'], '--max-context') != '262144':
        raise ValueError('Wrong V2 model/context')
    set_option(cfg['args'], '--expert-profile', profile)
    set_option(cfg['args'], '--resident-budget-gib', 32 if arm in ('R', 'PR', 'F') else 16)
    set_option(cfg['args'], '--prompt-cache', 0)
    cfg['log'] = str(directory / 'engine.log')
    cfg['vision']['temp_dir'] = str(directory / 'tmp')
    if arm == 'learn':
        target = directory / 'learned-profile.bin'
        if target.exists(): raise ValueError('Learning output must be fresh, never substituted on startup')
        cfg['expert_profile_save'] = str(target)
        cfg['expert_profile_save_every'] = 0
    if arm == 'trace':
        target = directory / 'routing.bin'
        if target.exists() or '--dump-routing' in cfg['args']:
            raise ValueError('Routing trace must be a fresh training-only output')
        cfg['args'] += ['--dump-routing', str(target)]
    return cfg


def ram32_fits(row, baseline_resident=0):
    # Trial-only conservative estimate: observed nonresident peaks are recorded,
    # not a universal guarantee. Ten GiB covers checkpoint/load and unknown peaks.
    increment = max(0, 32 - baseline_resident)
    return dict(available_gib=row['available_bytes'] / GIB,
                commit_margin_gib=row['commit_margin_bytes'] / GIB,
                increment_gib=increment, transient_unknown_gib=10,
                fits=(row['available_bytes'] >= (increment + 10 + 4) * GIB and
                      row['commit_margin_bytes'] >= (increment + 10 + 8) * GIB))


def tokenizer(path):
    from tools.strata_tokenizer import Tokenizer
    from serve.frontend import ChatTemplate
    path = Path(path)
    vocab = json.loads((path / 'vocab.json').read_text(encoding='utf-8'))
    words = [None] * len(vocab)
    for word, index in vocab.items(): words[index] = word
    tok = Tokenizer(words, (path / 'merges.txt').read_text(encoding='utf-8').split('\n'),
                    json.loads((path / 'token_type.json').read_text(encoding='utf-8')))
    template = ChatTemplate(path / 'chat_template.jinja')
    def encode(text):
        return tok.encode(template.render([dict(role='user', content=text)], enable_thinking=False), parse_special=True)
    return encode


def freeze_suite(directory, cfg):
    from .v2_expert_suite import TRAINING, EVALUATION, QUALITY
    encode = tokenizer(cfg['tokenizer'])
    def make(name, instruction, corpus, target):
        # Freeze the exact tokenizer result; aim near target without requiring
        # corpus token boundaries to make an exact-length synthetic sentence.
        text = instruction + '\n資料:\n'
        while len(encode(text)) < target - 150: text += corpus
        text += '\n' + instruction + '\n途中で結論をまとめず、項目ごとに十分な説明を続けてください。'
        tokens = encode(text)
        return dict(name=name, content=text, prompt_tokens=len(tokens),
                    input_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                    token_sha256=hashlib.sha256(json.dumps(tokens, separators=(',', ':')).encode()).hexdigest(),
                    deadline_s=1800 if name == 'long' else 600)
    image = ROOT.parent / 'RefImage/07.png'
    suite = dict(training=[make(n, p, c, 1024 + i % 3 * 1024) for i, (n, p, c) in enumerate(TRAINING)],
                 evaluation=[make(n, p, c, 32768 if n == 'long' else 4096) for n, p, c in EVALUATION],
                 quality=[dict(name=n, content=p, expected=expected) for n, p, expected in QUALITY],
                 image=dict(path=str(image), sha256=digest(image),
                            prompt='画像の人数、髪色、服装、場所、主要な物体、人物の位置を日本語で説明してください。'),
                 settings=dict(seed=42, temperature=0, top_k=1, reasoning_effort='none',
                               evaluation_max_tokens=128, training_max_tokens=256))
    write(directory / 'suite.json', suite)
    return suite


def prepare(directory):
    directory = Path(directory).resolve()
    directory.mkdir(exist_ok=False, parents=True)
    cfg = json.loads(PLAIN.read_text(encoding='utf-8'))
    shutil.copy2(PLAIN, directory / 'normal-profile.json')
    shutil.copy2(SHARED, directory / 'base-profile.bin')
    suite = freeze_suite(directory, cfg)
    evidence = dict(model=MODEL, context=262144, profile=check_profile(directory / 'base-profile.bin'),
                    shared_sha256=digest(SHARED), normal_sha256=digest(PLAIN),
                    suite_sha256=digest(directory / 'suite.json'), created=time.time(),
                    sources=source_snapshot(),
                    heads=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).decode().strip())
    write(directory / 'experiment.json', evidence)
    return evidence


def source_snapshot():
    names = ['local_runtime/v2_expert_experiment.py', 'local_runtime/v2_expert_suite.py',
             'local_runtime/v2_expert_frequency.py', 'tools/make_profile.py',
             'local_runtime/evaluate_r9700.py', 'local_runtime/official_runtime.py',
             'local_runtime/runtime_safety.py', 'local_runtime/checked_job.py',
             'local_runtime/manifest.py', 'serve/server.py', 'serve/winjob.py',
             'tools/strata_tokenizer.py', 'serve/frontend.py']
    return {name: digest(ROOT / name) for name in names}


def frozen_inputs(directory, experiment, arm):
    if digest(directory / 'normal-profile.json') != experiment['normal_sha256']:
        raise RuntimeError('Frozen normal profile snapshot changed')
    profile = directory / ('learn/learned-profile.bin' if arm in ('P', 'PR') else 'base-profile.bin')
    expected = experiment['profile']['sha256']
    if arm == 'F':
        proof = json.loads((directory / 'frequency-proof.json').read_text(encoding='utf-8'))
        profile, expected = directory / 'frequency-profile.bin', proof['profile']['sha256']
        if digest(directory / 'trace/routing.bin') != proof['trace_sha256']:
            raise RuntimeError('Frozen frequency training trace changed')
        if digest(directory / 'trace/result.json') != proof['training_result_sha256']:
            raise RuntimeError('Frozen frequency training result changed')
    if arm in ('P', 'PR'):
        learned = json.loads((directory / 'learn/result.json').read_text(encoding='utf-8'))
        if learned.get('status') != 'passed': raise RuntimeError('Learning did not complete successfully')
        expected = learned['saved_profile']['sha256']
    info = check_profile(profile)
    if info['sha256'] != expected: raise RuntimeError('Frozen profile changed between arms')
    return profile, info


def ready(state):
    safety.require_owned_listener(state)
    health, models = safety.get_json('/health'), safety.get_json('/v1/models')
    if not (health.get('loaded') is True and health.get('model') == MODEL and health.get('max_context') == 262144
            and health.get('images') is True):
        raise RuntimeError('V2/context/vision health mismatch')
    matches = [row for row in models.get('data', []) if row.get('id') == MODEL
               and row.get('meta', {}).get('n_ctx') == 262144
               and row.get('status', {}).get('value') == 'loaded']
    if len(matches) != 1: raise RuntimeError('Model list does not match running V2')
    return health, models


def post_unload(state):
    safety.require_owned_listener(state)
    status = safety.get_json('/status')
    if status.get('busy') is not False or status.get('queued') != 0:
        raise RuntimeError('Busy/queued; unload refused')
    request = urllib.request.Request('http://127.0.0.1:18080/unload', data=b'{}',
                                     headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=180) as response: result = json.load(response)
    if result.get('status') != 'unloaded': raise RuntimeError('Model unload was not confirmed')
    return result


def confirm_unloaded(state, engine_rows, *, authority=None):
    for row in engine_rows:
        proof = checked_job.original_birth_exit(row)
        if not proof['original_gone']: raise RuntimeError('Engine/vision original birth still alive or unknown')
    (authority or safety.require_owned_listener)(state)
    status, health = safety.get_json('/status'), safety.get_json('/health')
    if status.get('busy') is not False or status.get('queued') != 0 or health.get('loaded') is not False:
        raise RuntimeError('Client arrived or model reloaded after unload; server is retained')
    if authority is None:
        cfg = json.loads(Path(state['config']).read_text(encoding='utf-8'))
        engines = {Path(cfg['exe']).resolve(), Path(cfg['vision']['exe']).resolve()}
        if any(Path(p.exe()).resolve() in engines for p in safety.verified_cohort(state)):
            raise RuntimeError('A new engine/encoder appeared after unload; server is retained')


def validate_performance(sample, case, log):
    return benchmark.validate_sample(sample, case, log)


def start(cfg_path, monitor, retained, result):
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    runner.production_inactive()
    checked_job.ensure_parent_job()
    command = [sys.executable, str(ROOT / 'serve/server.py'), '--engine', 'strata', '--config', str(cfg_path), '--port', '18080']
    monitor.check()
    retained['spawn_possible'] = True
    with (cfg_path.parent / 'server.log').open('wb') as output:
        process = subprocess.Popen(command, cwd=str(ROOT), env=manifest.normalized_environment(cfg, os.environ),
                                   stdout=output, stderr=subprocess.STDOUT)
    retained['process'] = process
    checked_job.require_child(process)
    observer = official_runtime.SpawnObserver(process, cfg_path)
    retained['observer'] = observer
    observer.begin()
    observation = observer.snapshot()
    state = dict(pid=process.pid, created=observation['created'], exe=observation['identities'][0]['exe'],
                 config=str(cfg_path), engine_log=cfg['log'], owned_identities=observation['identities'],
                 spawn_observation=observation, phase='loading', cleanup_pending=True)
    retained['state'] = state
    safety.save(state)
    began = time.monotonic()
    while True:
        monitor.check()
        observation = observer.snapshot()
        state.update(owned_identities=observation['identities'], spawn_observation=observation)
        safety.save(state)
        if observation['unknown'] or observation['errors']: raise RuntimeError('Incomplete startup cohort')
        if process.poll() is not None: raise RuntimeError('Server died before READY')
        if time.monotonic() - began > 900: raise TimeoutError('Official 900-second READY deadline')
        if safety.require_owned_listener(state, allow_absent=True):
            try: health, models = ready(state)
            except (OSError, RuntimeError): pass
            else:
                observation = observer.finish()
                retained['observer'] = None
                if observation['unknown'] or observation['errors']: raise RuntimeError('Incomplete READY cohort')
                state.update(owned_identities=observation['identities'], spawn_observation=observation)
                engine = [row for row in state['owned_identities'] if Path(row['exe']).resolve() == Path(cfg['exe']).resolve()]
                images = [row for row in state['owned_identities'] if Path(row['exe']).resolve() == Path(cfg['vision']['exe']).resolve()]
                if len(engine) != 1 or len(images) != 1: raise RuntimeError('Exact engine/vision cohort missing')
                for row in engine + images:
                    if not checked_job.membership_pid(row['pid']): raise RuntimeError('Child escaped trial Job')
                from serve.server import engine_args
                expected = ['--serve'] + engine_args(cfg)
                actual = psutil.Process(engine[0]['pid']).cmdline()
                if actual[1:] != expected: raise RuntimeError('Actual engine arguments differ from frozen trial')
                result.update(engine_identity=engine[0],
                              vision_identity=images[0], engine_argv=actual, health=health, models=models)
                monitor.engine, monitor.images = engine[0], images
                state.update(phase='ready', startup_seconds=time.monotonic() - began)
                result['startup_seconds'] = state['startup_seconds']
                safety.save(state)
                return state
        time.sleep(.25)


def run(directory, arm, label, quality=False):
    directory = Path(directory).resolve()
    experiment = json.loads((directory / 'experiment.json').read_text(encoding='utf-8'))
    if digest(SHARED) != experiment['shared_sha256'] or digest(PLAIN) != experiment['normal_sha256']:
        raise RuntimeError('Shared or normal configuration changed during experiment')
    if digest(directory / 'suite.json') != experiment['suite_sha256']: raise RuntimeError('Frozen suite changed')
    if source_snapshot() != experiment['sources']: raise RuntimeError('Reviewed trial source changed')
    from .v2_expert_frequency import lineage
    inherited = lineage(experiment)
    limits = experiment.get('limits', dict(starts=9, posts=60))
    prior = list(directory.glob('*/result.json'))
    if any(json.loads(p.read_text(encoding='utf-8')).get('status') not in ('passed', 'skipped') for p in prior):
        raise RuntimeError('A prior trial failed; all further trials are stopped')
    if inherited['starts'] + sum(json.loads(p.read_text(encoding='utf-8')).get('start_count', 0) for p in prior) >= limits['starts']:
        raise RuntimeError('Experiment start budget exhausted')
    trial = directory / label
    trial.mkdir(exist_ok=False)
    (trial / 'tmp').mkdir()
    profile, profile_info = frozen_inputs(directory, experiment, arm)
    cfg = trial_config(json.loads((directory / 'normal-profile.json').read_text(encoding='utf-8')), trial, arm, profile)
    cfg_path = trial / 'trial-config.json'
    write(cfg_path, cfg)
    suite = json.loads((directory / 'suite.json').read_text(encoding='utf-8'))
    training = arm in ('learn', 'trace')
    cases = suite['training'] if training else [row for row in suite['evaluation'] if row['name'] != 'cold' or label.startswith('pilot')]
    result = dict(status='failed', arm=arm, label=label, profile=profile_info,
                  config_sha256=digest(cfg_path), post_count=0, start_count=0, samples=[])
    # A crash/cancellation or later serialization error must never make a spent
    # trial disappear from the next invocation's failure interlock.
    write(trial / 'result.json', result)
    retained = {}
    state, failure = None, None
    with runner.shared_operation(), runner.candidate_interrupts(retained):
        try:
            with runner.MemoryMonitor(trial / 'memory.jsonl') as monitor:
                monitor.cancel_requested = lambda: retained.get('cancel_requested', False)
                result['memory_before'] = runner.memory_sample()
                result['startup_advisory'] = runner.preflight_budget()
                if arm in ('R', 'PR', 'F'):
                    result['ram32_budget'] = ram32_fits(result['memory_before'])
                    if not result['ram32_budget']['fits']:
                        result.update(status='skipped', reason='Fresh RAM32 forecast does not fit; zero spawn/POST', comparison_eligible=False)
                        return result
                result['start_count'] = 1
                try:
                    state = start(cfg_path, monitor, retained, result)
                    for case in cases:
                        result['post_count'] += 1
                        if inherited['posts'] + sum(json.loads(p.read_text(encoding='utf-8')).get('post_count', 0) for p in prior) + result['post_count'] > limits['posts']:
                            raise RuntimeError('Experiment POST budget exhausted')
                        log_path = Path(cfg['log'])
                        before = log_path.stat().st_size
                        partial = {}
                        row = dict(case=case['name'], partial=partial)
                        result['samples'].append(row)
                        disk = runner.memory_sample()
                        trace = trial / 'routing.bin'
                        if arm == 'trace': row['trace_before_bytes'] = trace.stat().st_size
                        sample = runner.stream_request(state, monitor, case['content'], 256 if training else 128,
                                                       case['deadline_s'], partial=partial, ready_check=ready)
                        runner.wait_request_release(state, ready_check=ready)
                        with log_path.open('rb') as stream:
                            stream.seek(before)
                            log = stream.read().decode('utf-8', errors='strict')
                        (trial / (case['name'] + '.log')).write_text(log, encoding='utf-8')
                        row.update(sample=sample, disk_before=disk, disk_after=runner.memory_sample())
                        if arm == 'trace':
                            row.update(trace_after_bytes=trace.stat().st_size,
                                       trace_flush_contract='native generate.cpp:15119 fflush before terminal request stats')
                        row['request_metrics'] = safety.get_json('/metrics')['requests'][0]
                        row['hit_counts'] = re.findall(r'\((\d+) hits / (\d+) lookups\)', log)
                        if not training:
                            row['invalid_reasons'] = validate_performance(sample, case, log)
                            if row['invalid_reasons']: raise RuntimeError('Ineligible performance sample: ' + str(row['invalid_reasons']))
                        if not math.isfinite(sample['timings']['predicted_per_second']): raise RuntimeError('Nonfinite generation')
                        write(trial / 'progress.json', result)
                    if quality:
                        if training: raise ValueError('Quality is evaluated on frozen profiles only')
                        image = suite['image']
                        if digest(image['path']) != image['sha256']: raise RuntimeError('Frozen reference image changed')
                        content = [dict(type='text', text=image['prompt']),
                                   dict(type='image_url', image_url=dict(url='data:image/png;base64,' +
                                        base64.b64encode(Path(image['path']).read_bytes()).decode('ascii')))]
                        quality_cases = suite['quality'] + [dict(name='quality-image', content=content, expected=[])]
                        for case in quality_cases:
                            result['post_count'] += 1
                            if inherited['posts'] + sum(json.loads(p.read_text(encoding='utf-8')).get('post_count', 0) for p in prior) + result['post_count'] > limits['posts']:
                                raise RuntimeError('Experiment POST budget exhausted')
                            partial = {}
                            row = dict(case=case['name'], partial=partial, expected=case['expected'])
                            result['samples'].append(row)
                            row['sample'] = runner.stream_request(state, monitor, case['content'], 256, 600,
                                                                  partial=partial, ready_check=ready)
                            runner.wait_request_release(state, ready_check=ready)
                            row['expected_fragments_present'] = all(x.lower() in row['sample']['text'].lower() for x in case['expected'])
                            write(trial / 'progress.json', result)
                    monitor.check()
                finally:
                    state = state or retained.get('state')
                    if state and state.get('phase') == 'ready':
                        runner.wait_request_release(state, ready_check=ready)
                        monitor.expect_engine_exit()
                        post_unload(state)
                        confirm_unloaded(state, [result['engine_identity'], result['vision_identity']])
                        stopped = safety.stop_owned(state, official_first=False, post_unload=True)
                        safety.check_port_available()
                        proof = runner.pending_exit_proof(retained)
                        proof['job_members'] = list(checked_job.active_members())
                        if not proof['complete'] or set(proof['job_members']) != {os.getpid()}:
                            raise RuntimeError('Trial cohort exit was not independently proved')
                        state.update(cleanup_pending=False, phase='stopped')
                        safety.save(state)
                        result['cleanup'] = dict(status='passed', proof=proof, stopped=stopped)
                    elif retained.get('process'):
                        # Reuse existing exact-Popen failure cleanup rather than
                        # inventing permission to terminate an unknown process.
                        failed = retained.setdefault('state', dict(config=str(cfg_path), cleanup_pending=True,
                                                                  owned_identities=[], phase='failed'))
                        runner.cleanup_failed_start(retained['process'], retained.get('observer'), failed)
                if arm == 'learn':
                    result['saved_profile'] = check_profile(trial / 'learned-profile.bin')
                    if 'expert profile saved to' not in Path(cfg['log']).read_text(encoding='utf-8'):
                        raise RuntimeError('Engine profile-save success log missing')
                if digest(profile) != profile_info['sha256']: raise RuntimeError('Frozen input profile changed')
                result['memory_after'] = runner.memory_sample()
                result['status'] = 'passed'
        except BaseException as error:
            result.update(status='failed', error_type=type(error).__name__, reason=str(error))
            if retained.get('spawn_possible') and retained.get('state', {}).get('cleanup_pending', True):
                runner.hold_pending_cleanup(retained, result, trial)
            raise
        finally:
            result['shared_profile_unchanged'] = digest(SHARED) == experiment['shared_sha256']
            write(trial / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'extend', 'build-frequency', 'run'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--arm', choices=('learn', 'trace', 'F', 'A', 'P', 'R', 'PR'))
    parser.add_argument('--parent', type=Path)
    parser.add_argument('--label')
    parser.add_argument('--quality', action='store_true', help='Five frozen quality cases in this same start')
    args = parser.parse_args()
    if args.action == 'prepare': result = prepare(args.directory)
    elif args.action == 'extend':
        from .v2_expert_frequency import extend
        result = extend(args.parent, args.directory)
    elif args.action == 'build-frequency':
        from .v2_expert_frequency import build
        result = build(args.directory)
    else: result = run(args.directory, args.arm, args.label, args.quality)
    print(json.dumps(dict(status=result['status'], arm=result['arm']) if args.action == 'run' else result, indent=2))


if __name__ == '__main__':
    main()
