"""Attempt-bound startup diagnostics; never decides readiness or terminates a process."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import time
import uuid

import psutil

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent / 'Strata'
BASE_PYTHON = Path('C:/Users/yaruo/AppData/Local/Programs/Python/Python312/python.exe')
VENV_PYTHON = REPO / '.venv/Scripts/python.exe'
BOOTSTRAP = ROOT / 'server_bootstrap.py'
PHASES = ('bootstrap_started', 'server_import_begin', 'server_import_end',
          'tokenizer_begin', 'tokenizer_end', 'temp_begin', 'temp_end',
          'engine_spawn_begin', 'engine_started', 'engine_ready')
LABELS = dict(zip(PHASES, ('起動準備', '公式server読込開始', '公式server読込完了',
                          'tokenizer準備開始', 'tokenizer準備完了', 'TEMP検査開始', 'TEMP検査完了',
                          'engine起動開始', 'engine起動済み・モデル読込中', 'モデル読込完了・API検証中')))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stage_path(attempt):
    if str(uuid.UUID(attempt)) != attempt:
        raise ValueError('Noncanonical startup attempt UUID')
    return ROOT / 'records' / f'startup-{attempt}.jsonl'


def bootstrap_command(config, attempt):
    family = family_launch(config)
    if family and not family[2]:
        raise RuntimeError('A saved family declaration is not a resolved bootstrap launch')
    # Keep the existing retained root/stage-writer PID identical. The spawn
    # boundary sets __PYVENV_LAUNCHER__ to the selected package interpreter.
    return [str(BASE_PYTHON), '-E', '-s', '-B', '-X', 'utf8', str(BOOTSTRAP),
            '--config', str(config), '--attempt', attempt, '--stage', str(stage_path(attempt))]


def family_launch(config):
    """Installed helper only; legacy config paths preserve their original branch."""
    path = Path(config)
    if not path.is_file():
        return None
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if cfg.get('family') != 'deepseek41':
        return None
    module = family_helper()
    binding_path = path.with_suffix('.launch.json')
    if not binding_path.is_file():
        return module, cfg, None  # Saved declaration; never a bootstrap authorization.
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    return module, module.verify_binding(path, binding), binding


def family_helper():
    """Resolve installed code independently of any default context declaration."""
    helper = ROOT.parent / 'Strata-extensions/control/deepseek_launch.py'
    spec = importlib.util.spec_from_file_location('strata_installed_deepseek_launch', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.ABI != 'strata-deepseek-launch/v1':
        raise RuntimeError('Installed family launch ABI mismatch')
    return module


def is_bootstrap_command(command, config):
    try:
        return (isinstance(command, (list, tuple)) and len(command) == 13
                and list(command) == bootstrap_command(config, command[10]))
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
        return False


class Tee:
    """Forward every write and flush to both the existing console and UTF-8 record."""
    def __init__(self, console, record):
        self.console, self.record = console, record

    def write(self, value):
        self.record.write(value)
        self.console.write(value)
        self.flush()
        return len(value)

    def flush(self):
        self.record.flush()
        self.console.flush()

    def isatty(self):
        return self.console.isatty()


class StageWriter:
    def __init__(self, path, attempt, config_sha256, phase_changed=None):
        self.path, self.attempt, self.config_sha256 = Path(path), attempt, config_sha256
        self.pid, self.created = os.getpid(), psutil.Process().create_time()
        self.seq, self.index = 0, -1
        self.phase_changed = phase_changed

    def emit(self, phase, **details):
        index = PHASES.index(phase)
        if index <= self.index and not (phase == 'engine_started' and index == self.index):
            return  # Official engine retry/reload must not regress pre-engine phases.
        self.index, self.seq = index, self.seq + 1
        row = dict(version=1, attempt=self.attempt, config_sha256=self.config_sha256,
                   pid=self.pid, created=self.created, seq=self.seq, phase=phase, **details)
        try:
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=True) + '\n')
                stream.flush()
        except OSError as error:
            print(f'[startup diagnostic] stage write failed: {type(error).__name__}', flush=True)
        if self.phase_changed:
            self.phase_changed(phase)


class StageMonitor:
    def __init__(self, path, attempt, config, config_sha256, pid, created, engine_exe,
                 output=print, clock=time.monotonic):
        self.path, self.attempt, self.config = Path(path), attempt, Path(config)
        if self.path != stage_path(attempt):
            raise ValueError('Startup stage path does not match attempt')
        self.config_sha256, self.pid, self.created = config_sha256, pid, created
        self.engine_exe, self.output, self.clock = Path(engine_exe).resolve(), output, clock
        self.offset, self.seq, self.index = 0, 0, -1
        self.started = clock()
        self.phase, self.changed, self.warned = 'spawned', self.started, self.started
        self.heartbeat = self.started
        self.engine_event, self.engine_confirmed = None, False
        self.errors = set()

    def diagnostic(self, message):
        if message not in self.errors:
            self.errors.add(message)
            self.output('[startup diagnostic] ' + message, flush=True)

    def accept(self, row, now):
        required = {'version', 'attempt', 'config_sha256', 'pid', 'created', 'seq', 'phase'}
        if (not isinstance(row, dict) or not required.issubset(row)
                or type(row.get('version')) is not int or row['version'] != 1
                or row['attempt'] != self.attempt or row['config_sha256'] != self.config_sha256
                or type(row['pid']) is not int or row['pid'] != self.pid
                or type(row['created']) not in (int, float) or not math.isfinite(row['created'])
                or abs(row['created'] - self.created) >= .00001
                or type(row['seq']) is not int or row['seq'] != self.seq + 1
                or row['phase'] not in PHASES):
            raise ValueError('stage authority, sequence, or phase mismatch')
        index = PHASES.index(row['phase'])
        repeat_engine = row['phase'] == 'engine_started' and index == self.index
        if index <= self.index and not repeat_engine:
            raise ValueError('stage phase regressed')
        if row['phase'] == 'engine_started':
            if (type(row.get('engine_pid')) is not int or row['engine_pid'] <= 0
                    or type(row.get('engine_created')) not in (int, float)
                    or not math.isfinite(row['engine_created'])
                    or not isinstance(row.get('engine_exe'), str)
                    or Path(row['engine_exe']).resolve() != self.engine_exe
                    or type(row.get('engine_attempt', 1)) is not int
                    or row.get('engine_attempt', 1) <= (self.engine_event.get('engine_attempt', 1) if self.engine_event else 0)):
                raise ValueError('engine event identity is incomplete')
            self.engine_event = row
        self.index, self.seq = index, row['seq']
        self.phase = row['phase']
        if not repeat_engine:
            self.changed, self.warned = now, now
        self.output(f'[起動] {LABELS[self.phase]}: 経過 {now-self.started:.0f}秒', flush=True)

    def update(self, identities=(), now=None):
        now = self.clock() if now is None else now
        try:
            if sha256(self.config) != self.config_sha256:
                raise ValueError('startup config changed')
            with self.path.open('rb') as stream:
                if stream.seek(0, 2) < self.offset:
                    raise ValueError('stage record was truncated')
                stream.seek(self.offset)
                content = stream.read()
            complete = content.rfind(b'\n') + 1
            self.offset += complete  # A partial final JSON line is still being written.
            for line in content[:complete].splitlines():
                self.accept(json.loads(line), now)
            if self.engine_event and not self.engine_confirmed:
                event = self.engine_event
                for row in identities:
                    if (row.get('pid') == event['engine_pid']
                            and abs(row.get('created', 0) - event['engine_created']) < .00001
                            and Path(row.get('exe', '')).resolve() == self.engine_exe):
                        process = psutil.Process(row['pid'])
                        if (abs(process.create_time() - row['created']) < .00001
                                and Path(process.exe()).resolve() == self.engine_exe):
                            self.engine_confirmed = True
                            self.heartbeat = now
                            self.output('[起動] 所有engine確認済み。モデル読込は公式READY期限・再試行に従います。', flush=True)
        except (OSError, ValueError, TypeError, KeyError, psutil.Error) as error:
            self.diagnostic(f'{type(error).__name__}: {error}')
        if not self.engine_confirmed and now - self.changed >= 30 and now - self.warned >= 30:
            self.warned = now
            self.output(f'[startup warning] pre-engine phase {self.phase} unchanged for {now-self.changed:.0f}s; '
                        f'waiting without termination (stage: {self.path}; stack: official server.log)', flush=True)
        if self.engine_confirmed and self.phase != 'engine_ready' and now - self.heartbeat >= 30:
            self.heartbeat = now
            self.output(f'[起動] GPUモデル読込中: 経過 {now-self.started:.0f}秒（公式READY期限・再試行で継続）', flush=True)

