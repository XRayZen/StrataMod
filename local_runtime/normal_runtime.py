"""StrataMod plain launcher: prepared profile, foreground ownership, no receipts or hashes."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

import psutil

from . import manifest as m

KIND = 'stratamod-plain-v1'
HOME = m.LOCAL / 'normal'
RUNS = HOME / 'runs'
PLAIN = HOME / 'plain-profile.json'
STATE = HOME / 'run-state.json'
PORT = 18080
URL = f'http://127.0.0.1:{PORT}'


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def loaded_health():
    try:
        with urllib.request.urlopen(URL + '/health', timeout=2) as response:
            return json.loads(response.read().decode('utf-8'))
    except (OSError, ValueError):
        return None


def ready_health(health):
    return bool(health and health.get('service') == 'strata' and health.get('status') == 'ok'
                and health.get('loaded') is True and health.get('model') == m.MODEL
                and health.get('max_context') == m.CONTEXT)


def identity(pid):
    try:
        process = psutil.Process(pid)
        return process.create_time()
    except psutil.Error:
        return None


def descendants(pid):
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []


def _stop_members(members):
    seen, unique = set(), []
    for member in members:
        if member.pid not in seen and member.is_running():
            seen.add(member.pid)
            unique.append(member)
    for member in reversed(unique):
        try:
            member.terminate()
        except psutil.Error:
            pass
    gone, alive = psutil.wait_procs(unique, timeout=20)
    for member in alive:
        try:
            member.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=10)
    return dict(stopped=True, remaining=[row.pid for row in alive if row.is_running()])


def stop_tree(pid, created, captured=()):
    if identity(pid) != created:
        return _stop_members(list(captured)) if captured else \
            dict(stopped=False, reason='process identity changed')
    return _stop_members(descendants(pid) + [psutil.Process(pid)])


def log_tail(path, count=20):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace').splitlines()[-count:]
    except OSError:
        return []


def plain_config():
    cfg = m.read_json(PLAIN)
    directory = RUNS / str(time.time_ns())
    directory.mkdir(parents=True)
    (directory / 'tmp').mkdir()
    cfg = copy.deepcopy(cfg)
    cfg['log'] = str(directory / 'engine.log')
    if isinstance(cfg.get('vision'), dict):
        cfg['vision']['temp_dir'] = str(directory / 'tmp')
    cfg['shared'] = False
    cfg['open_browser'] = False
    cfg['port'] = PORT
    config_path = directory / 'strata-StrataMod.json'
    write(config_path, cfg)
    return directory, config_path, cfg


def serve():
    if not PLAIN.is_file():
        raise RuntimeError('Prepared profile is missing: ' + str(PLAIN))
    directory, config_path, cfg = plain_config()
    environment = m.normalized_environment(cfg, os.environ)
    command = [sys.executable, str(m.ROOT / 'serve/server.py'), '--engine', 'strata',
               '--config', str(config_path), '--port', str(PORT)]
    print('[StrataMod] starting ' + m.MODEL + ' / ' + str(m.CONTEXT) + ' (plain, unverified)', flush=True)
    process = subprocess.Popen(command, cwd=str(m.ROOT), env=environment)
    created = identity(process.pid)
    write(STATE, dict(kind=KIND, pid=process.pid, created=created, config=str(config_path),
                      log=cfg['log'], started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    deadline = time.monotonic() + 900
    try:
        while True:
            if process.poll() is not None:
                raise RuntimeError('StrataMod server exited before READY: ' + str(process.returncode))
            if ready_health(loaded_health()):
                break
            if time.monotonic() > deadline:
                raise TimeoutError('StrataMod startup 900-second deadline')
            time.sleep(1)
        write(STATE, dict(kind=KIND, pid=process.pid, created=created, config=str(config_path),
                          log=cfg['log'], phase='ready',
                          started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        print(f'StrataMod READY {URL}/ - stop with Ctrl+C in this terminal', flush=True)
        while process.poll() is None:
            time.sleep(1)
        print('[StrataMod] server exited: ' + str(process.returncode), flush=True)
    except KeyboardInterrupt:
        print('[StrataMod] stopping...', flush=True)
    except BaseException:
        stop_tree(process.pid, created, descendants(process.pid))
        raise
    finally:
        members = descendants(process.pid)
        if process.poll() is None:
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                pass
        stop_tree(process.pid, created, members)
        state = m.read_json(STATE) if STATE.is_file() else {}
        if state.get('pid') == process.pid:
            write(STATE, dict(state, phase='stopped', stopped_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))


def status():
    if not STATE.is_file():
        return dict(running=False)
    state = m.read_json(STATE)
    alive = identity(state.get('pid')) == state.get('created')
    return dict(running=alive, state=state, health=loaded_health() if alive else None)


def stop():
    if not STATE.is_file():
        return dict(stopped=False, reason='no saved run')
    state = m.read_json(STATE)
    if identity(state.get('pid')) != state.get('created'):
        return dict(stopped=False, reason='process not running or identity changed')
    result = stop_tree(state['pid'], state['created'])
    write(STATE, dict(state, phase='stopped', stopped_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='serve', choices=('serve', 'status', 'stop'))
    args = parser.parse_args()
    if args.action == 'serve':
        serve()
        return
    print(json.dumps(status() if args.action == 'status' else stop(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
