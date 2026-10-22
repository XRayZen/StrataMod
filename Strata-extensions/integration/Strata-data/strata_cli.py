"""Local, single-model entry point. GPU work remains in the reviewed runtime manager."""
import argparse
import contextlib
import json
import msvcrt
import os
import pathlib
import signal
import subprocess
import sys
import time
import webbrowser

import psutil
import manage_runtime as runtime
import model_catalog as catalog
import official_runtime
from startup_progress import Tee

ROOT = pathlib.Path(__file__).resolve().parent
MODELS = catalog.ALIASES
CONTEXTS = catalog.CONTEXTS
URL = 'http://127.0.0.1:18080/'


def identity(state):
    return state.get('pid'), state.get('created'), state.get('config')


@contextlib.contextmanager
def operation_lock():
    """Serialize this CLI's mutations; the manager separately locks actual runtime state."""
    with (ROOT / 'records' / 'cli-operation.lock').open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('別のCLI起動/停止操作が進行中です。statusで確認してください。') from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class Runtime:
    def client_binding(self):
        from client_runtime import resolve_runtime
        def original():
            state = self.state()
            self.ready(state)
            return {key: state[key] for key in ('model', 'context', 'pid', 'created', 'config', 'owned_identities') if key in state}
        return resolve_runtime(legacy_probe=original)

    def state(self):
        return runtime.read_state()

    def active(self, state):
        return runtime.runtime_active(state)

    def ready(self, state):
        import huihui_authority as authority
        private = state.get('model') == authority.MODEL and not catalog.CATALOG[authority.MODEL].get('selectable')
        if private:
            authority.private_state(state)
            with authority.validation_scope():
                return self._ready(state, private=True)
        return self._ready(state)

    def _ready(self, state, private=False):
        family = catalog.CATALOG.get(state.get('model'),{}).get('family') == 'deepseek41'
        valid_context = type(state.get('context')) is int and 0 < state['context'] <= 1048576 if family else state.get('context') in CONTEXTS
        if state.get('phase') != 'ready' or (state.get('model') not in MODELS.values() and not private) or not valid_context:
            raise RuntimeError('対象モデルはREADYではありません。status/stopで確認してください。')
        expected = ROOT / 'profiles' / f"{state['model']}-{state['context']}.json"
        visible = state.get('effective_gpu_visibility', {})
        allowed_configs={expected.resolve()}
        if state.get('runtime_provider')=='official_mcp':
            allowed_configs.add(official_runtime.require_registration(state['model'],state['context']).resolve())
        if family:
            selected = runtime.startup_progress.family_launch(state['config'])
            if not selected or selected[2] != state.get('launch_binding'):
                raise RuntimeError('現在のfamily launch bindingが一致しません。')
            allowed_configs.add(pathlib.Path(selected[2]['config']).resolve())
        if (pathlib.Path(state.get('config', '')).resolve() not in allowed_configs
                or (any(visible.get(name) is not None for name in runtime.VISIBILITY) if family else
                    visible.get('HIP_VISIBLE_DEVICES') != '1' or any(visible.get(name) is not None for name in runtime.VISIBILITY[1:]))):
            raise RuntimeError('既存runtimeのprofile/GPUが検証済み設定と一致しません。')
        if private:
            self._validate_assets(state['model'], state['context'])
        else:
            self.validate(state['model'], state['context'])
        if state.get('runtime_provider')=='official_mcp':
            official_runtime.require_tracking(state)
        runtime.require_owned_listener(state)
        if family:runtime.require_family_ready(state)
        health = runtime.get_json('/health')
        if not (health.get('service') == 'strata' and health.get('status') == 'ok'
                and health.get('loaded') is True and health.get('model') == state['model']
                and health.get('max_context') == state['context']):
            raise RuntimeError('既存serverのhealth/model/contextが一致しません。自動再起動しません。')
        models = runtime.get_json('/v1/models').get('data', [])
        if len([row for row in models if row.get('id') == state['model']
                and row.get('status', {}).get('value') == 'loaded'
                and row.get('meta', {}).get('n_ctx') == state['context']]) != 1:
            raise RuntimeError('既存serverのモデル一覧が一致しません。')
        if identity(self.state()) != identity(state):
            raise RuntimeError('runtimeが変更されました。操作をやり直してください。')

    def validate(self, model, context):
        catalog.require_public_context(model, context, ROOT)
        self._validate_assets(model, context)

    def _validate_assets(self, model, context):
        if catalog.CATALOG.get(model,{}).get('family') == 'deepseek41':
            # Validate arbitrary selected context without requiring/publishing a default profile.
            path = ROOT / 'profiles' / f'{model}-{context}.json'
            cfg = (json.loads(path.read_text(encoding='utf-8-sig')) if path.exists()
                   else dict(catalog._family_profile(model,ROOT), context=context,
                             log=str(ROOT/'logs'/f'{model}-{context}-engine.log')))
            provider = catalog._family_provider(ROOT)
            cfg = provider.validate_profile(cfg,context)
            provider.assets(cfg)
            runtime.validate_profile(cfg,context)
            options = getattr(self,'launch_options',None)
            if options:
                module = runtime.startup_progress.family_helper()
                provider.validate_profile(module.overlay(cfg,options),context)
            return
        ple_shard = catalog.require_ready(model, ROOT)
        cfg = json.loads((ROOT / 'profiles' / f'{model}-{context}.json').read_text(encoding='utf-8-sig'))
        runtime.validate_profile(cfg, context)
        catalog.validate_layout(cfg, model, context, ple_shard, ROOT)
        if cfg['gpu'] != 1 or cfg['hip_ordinal'] != 1 or cfg['env']:
            raise RuntimeError('検証済みR9700単独profileではありません。')
        for flag, expected in [('--pack', ROOT / 'packs' / model), ('--mtp', ROOT / 'mtp' / 'rt')]:
            value = cfg['args'][cfg['args'].index(flag) + 1]
            if pathlib.Path(value).resolve() != expected.resolve():
                raise RuntimeError('profileのpack/MTPが一致しません。')
        if pathlib.Path(cfg['tokenizer']).resolve() != (ROOT / 'packs' / model / 'tokenizer').resolve():
            raise RuntimeError('profileのtokenizerが一致しません。')
        official_runtime.require_registration(model,context)

    def start(self, model, context):
        log = ROOT / 'records' / f'cli-start-{time.time_ns()}.log'
        print(f'起動中: {model} / {context}（readinessは公式engineの期限・再試行に従います）\n記録: {log}', flush=True)
        with log.open('w', encoding='utf-8') as output, \
                contextlib.redirect_stdout(Tee(sys.stdout, output)), \
                contextlib.redirect_stderr(Tee(sys.stderr, output)):
            options = getattr(self,'launch_options',None)
            return runtime.start(model, context, options=options) if options else runtime.start(model, context)

    def stop(self, expected):
        # Check confirmation's exact attempt while holding the manager's existing state lock.
        with runtime.state_lock():
            current = self.state()
            if identity(current) != identity(expected):
                raise RuntimeError('確認後にruntimeが変わったため停止しません。')
            if not current:
                return
            stopped = runtime.stop_owned(current)
            current.update(phase='stopped', stopped_pids=stopped,
                           stopped_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            runtime.save(current)


def describe(state):
    return f"{state.get('model', '不明')} / context {state.get('context', '不明')} / {state.get('phase', '不明')} / PID {state.get('pid', '不明')}"


def describe_execution(state):
    """Display fresh observed roles, never the saved recommendation as actual."""
    info=state.get('family_ready_observation',{}).get('native_info',{})
    if not info.get('configured_mode') or not info.get('effective_mode'):
        return None
    text=f"実行方式: {info['configured_mode']} → {info['effective_mode']} / primary {info.get('primary_pci')} / secondary {info.get('actual_secondary_pci')}"
    if info.get('secondary_experts')is not None:text+=' / secondary expert IDs '+','.join(map(str,info['secondary_experts']))
    if info.get('layer_cut')is not None:text+=' / cut '+str(info['layer_cut'])
    return text


def start_selected(rt, model, context, switch=False, confirmed_identity=None):
    rt.validate(model, context)  # Validate target before stopping a working model.
    with operation_lock():
        state = rt.state()
        if rt.active(state):
            print('現在: ' + describe(state))
            changed_overlay = False
            options = getattr(rt,'launch_options',None)
            if options and state.get('model') == model:
                selected = runtime.startup_progress.family_launch(state['config'])
                if not selected:raise RuntimeError('実launch設定を確認できません。')
                changed_overlay = selected[0].overlay(selected[1],options) != selected[1]
            if state.get('model') == model and state.get('context') == context and not changed_overlay:
                rt.ready(state)
                print('同じ設定のREADY serverを再利用します。')
                return
            if not switch:
                raise RuntimeError('別の設定が稼働中です。切替を承認する場合は start ... --switch を指定してください。')
            if confirmed_identity is not None and identity(state) != confirmed_identity:
                raise RuntimeError('切替確認後にruntimeが変わったため停止しません。')
            if state.get('phase') == 'loading':
                raise RuntimeError('load中です。完了を待つか明示stopしてください。')
            rt.stop(state)
            if rt.active(rt.state()):
                raise RuntimeError('owned processが残っているため次のモデルを起動しません。')
        state = rt.start(model, context)
        if (not isinstance(state, dict) or state.get('model') != model or state.get('context') != context
                or identity(rt.state()) != identity(state)):
            raise RuntimeError('新規起動attemptと現在stateが一致しません。他attemptは操作しません。')
        try:
            rt.ready(state)
        except BaseException as original:
            try:
                rt.stop(state)
            except BaseException as cleanup:
                print(f'新規起動後の確認失敗: {original}; owned cleanup失敗: {cleanup}', file=sys.stderr)
            raise
        print('READY: ' + describe(state))
        execution=describe_execution(state)
        if execution:print(execution)
        print('次: web / chat / pi。終了・モデル切替前には stop。')


def stop_current(rt, confirmed_identity=None):
    with operation_lock():
        state = rt.state()
        if confirmed_identity is not None and identity(state) != confirmed_identity:
            raise RuntimeError('停止確認後にruntimeが変わったため停止しません。')
        if not rt.active(state):
            print('現在のowned modelは停止済みです。')
            return
        print('停止: ' + describe(state))
        rt.stop(state)
        if rt.active(rt.state()):
            raise RuntimeError('owned processが残っています。次のモデルは起動しません。')
        print('owned modelの停止完了。')


def pi_command(state, workdir=None, native_args=None):
    path = ROOT / 'pi-action.json'
    if not path.is_file():
        raise RuntimeError('Pi連携は未設定です。pi-action.jsonのセットアップ完了後に使用してください。')
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg, dict) or set(cfg) != {'version', 'argv', 'cwd'} or type(cfg['version']) is not int or cfg['version'] != 1:
        raise RuntimeError('Pi actionのschemaが一致しません。')
    argv = cfg['argv']
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg and '\0' not in arg for arg in argv):
        raise RuntimeError('Pi argvは非空の文字列配列が必要です。')
    values = {'{model}': state['model'], '{context}': str(state['context'])}
    expanded = []
    for arg in argv:
        if arg in values:
            expanded.append(values[arg])
        elif '{' in arg or '}' in arg:
            raise RuntimeError('Pi placeholderは完全一致の{model}/{context}のみです。')
        else:
            expanded.append(arg)
    exe = pathlib.Path(expanded[0])
    if not isinstance(cfg['cwd'], str):
        raise RuntimeError('Pi cwdは絶対pathの文字列が必要です。')
    cwd = pathlib.Path(cfg['cwd'])
    if not (exe.is_absolute() and exe.suffix.lower() == '.exe' and exe.is_file()
            and cwd.is_absolute() and cwd.is_dir()):
        raise RuntimeError('Piには実在する絶対EXE pathと絶対cwdが必要です。')
    if workdir is not None:
        cwd = pathlib.Path(workdir).expanduser().resolve()
        if not cwd.is_dir():
            raise RuntimeError('指定したPi作業directoryが存在しません。')
    return [*expanded, *(native_args or [])], str(cwd)


def process_identity(process):
    return dict(pid=process.pid, created=process.create_time(), exe=str(pathlib.Path(process.exe()).resolve()))


def matching_process(row):
    try:
        process = psutil.Process(row['pid'])
        if (abs(process.create_time() - row['created']) < .05
                and pathlib.Path(process.exe()).resolve() == pathlib.Path(row['exe']).resolve()):
            return process
    except psutil.NoSuchProcess:
        pass
    return None


def collect_client_tree(root_identity, known, excluded, errors):
    try:
        process = matching_process(root_identity)
        children = process.children(recursive=True) if process else []
    except psutil.NoSuchProcess:
        return
    except psutil.Error as error:
        errors.append(dict(pid=root_identity['pid'], action='inspect_tree', error_type=type(error).__name__))
        return
    if not process:
        return
    for child in [process, *children]:
        try:
            row = process_identity(child)
            key = (row['pid'], row['created'])
            if key not in excluded:
                known[key] = row
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as error:
            errors.append(dict(pid=child.pid, action='inspect_descendant_not_touched', error_type=type(error).__name__))


def cleanup_client(known, excluded):
    """Only saved, identity-matching client descendants. Never touch an excluded server."""
    errors = []
    victims = []
    preserved = []
    for key, row in reversed(list(known.items())):
        if key in excluded:
            preserved.append(dict(**row, reason='preexisting_server'))
            continue
        try:
            process = matching_process(row)
            if process:
                process.terminate()
                victims.append(process)
            elif psutil.pid_exists(row['pid']):
                preserved.append(dict(**row, reason='identity_changed_not_touched'))
        except psutil.Error as error:
            errors.append(dict(pid=row['pid'], error_type=type(error).__name__))
    try:
        _, alive = psutil.wait_procs(victims, timeout=3)
    except psutil.Error as error:
        alive = victims
        errors.append(dict(action='wait', error_type=type(error).__name__))
    return dict(known_alive=[p.pid for p in alive], preserved=preserved, errors=errors)


def run_client(argv, cwd, server_state):
    """Keep a client handle and observe its real descendants before a parent can disappear."""
    excluded = {(row['pid'], row['created']) for row in server_state.get('owned_identities', [])}
    excluded.add((server_state.get('pid'), server_state.get('created')))
    # Strip Node startup hooks before Node itself can interpret them. Do not inspect/log their values.
    env = {key: os.environ[key] for key in os.environ if not key.upper().startswith('NODE_')}
    process = subprocess.Popen(argv, cwd=cwd, shell=False, env=env,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    known = {}
    root_identity = None
    interrupted = False
    reason = None
    cleanup = None
    collection_errors = []
    try:
        try:
            root_identity = process_identity(psutil.Process(process.pid))
        except psutil.NoSuchProcess:
            return process.wait(timeout=3)
        known[(root_identity['pid'], root_identity['created'])] = root_identity
        while True:
            collect_client_tree(root_identity, known, excluded, collection_errors)
            try:
                return process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
    except BaseException as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        reason = type(error).__name__
        if root_identity:
            collect_client_tree(root_identity, known, excluded, collection_errors)
            try:
                root_matches = matching_process(root_identity) is not None
            except psutil.Error as inspect_error:
                root_matches = False
                collection_errors.append(dict(action='inspect_before_signal', error_type=type(inspect_error).__name__))
            if process.poll() is None and root_matches:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                except OSError:
                    pass
                deadline = time.monotonic() + 2
                while process.poll() is None and time.monotonic() < deadline:
                    collect_client_tree(root_identity, known, excluded, collection_errors)
                    time.sleep(.1)
        elif process.poll() is None:
            # The Popen handle refers to this exact created process even if identity inspection failed.
            try:
                process.terminate()
            except OSError as cleanup_error:
                collection_errors.append(dict(action='terminate_created_handle', error_type=type(cleanup_error).__name__))
        raise
    finally:
        cleanup = cleanup_client(known, excluded)
        cleanup['errors'].extend(collection_errors)
        receipt = ROOT / 'records' / f"cli-client-{process.pid}-{time.time_ns()}.json"
        try:
            receipt.write_text(json.dumps(dict(root=root_identity, created_handle_pid=process.pid, reason=reason,
                interrupted=interrupted, saved_identities=list(known.values()), cleanup=cleanup), indent=2), encoding='utf-8')
        except OSError as error:
            cleanup['errors'].append(dict(action='receipt_write', error_type=type(error).__name__))
        if cleanup['known_alive'] or cleanup['errors'] or cleanup['preserved']:
            print('client cleanupは確認が必要です: ' + json.dumps(cleanup), file=sys.stderr)
            if sys.exc_info()[0] is None:
                raise RuntimeError('client終了後のcleanup/記録確認が必要です。自動再試行しません。')


def use_ready(rt, action, workdir=None, native_args=None):
    client_binding = getattr(rt, 'client_binding', None) if action == 'pi' else None
    state = client_binding() if client_binding else rt.state()
    if not client_binding:
        rt.ready(state)
    if action == 'web':
        if not webbrowser.open(URL):
            print('ブラウザを開けませんでした。手動で開いてください: ' + URL)
        else:
            print(URL)
        return 0
    if action == 'chat':
        argv = [sys.executable, '-X', 'utf8', str(ROOT.parent / 'Strata' / 'chat.py'),
                '--host', '127.0.0.1', '--port', '18080']
        cwd = str(ROOT.parent / 'Strata')
        family = runtime.startup_progress.family_launch(state['config']) if state.get('config') else None
        if family and family[1].get('family') == 'deepseek41':
            cfg = family[1]
            manifest_path = pathlib.Path(cfg['runtime_package']['manifest'])
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('id') != cfg['runtime_package']['id']:
                raise RuntimeError('Selected chat package identity changed.')
            # Accepted pre-client packages retain their original chat behavior.
            # A declared client extension must supply its own exact entry/helpers.
            if 'client_extension' in manifest:
                if not isinstance(manifest['client_extension'], dict):
                    raise RuntimeError('Invalid selected client extension declaration.')
                package = manifest_path.parent.parent.resolve()
                chat = package / 'clients' / 'chat.py'
                relatives = ('clients/chat.py', 'Strata-extensions/clients/chat_adapter.py',
                             'Strata-extensions/clients/stream_contract.py')
                if 'identity_extension' in manifest:
                    identity = manifest['identity_extension']
                    if not isinstance(identity, dict) or identity.get('schema') != 'strata-runtime-identity/v1':
                        raise RuntimeError('Invalid selected runtime identity extension.')
                    relatives += ('Strata-extensions/clients/runtime_identity.py',)
                for relative in relatives:
                    path = package / relative
                    rows = [r for r in manifest.get('files', []) if pathlib.Path(r['path']).resolve() == path.resolve()]
                    if len(rows) != 1 or not path.is_file() or path.stat().st_size != rows[0]['bytes'] or official_runtime.digest(path) != rows[0]['sha256']:
                        raise RuntimeError('Selected client entry/helper is missing or changed: ' + relative)
                argv = [cfg['python'], '-E', '-s', '-B', '-X', 'utf8', str(chat),
                        '--host', str(cfg.get('host', '127.0.0.1')), '--port', str(cfg.get('port', 18080))]
                cwd = str(package)
            elif manifest.get('schema') != 'strata-t29-runtime-package/v1':
                raise RuntimeError('Unknown selected chat package declaration.')
    else:
        argv, cwd = pi_command(state, workdir, native_args)
    if client_binding:
        if client_binding()['fingerprint'] != state['fingerprint']:
            raise RuntimeError('Strata/StrataMod runtime authority changed; retry the Pi connection. No runtime was changed.')
    else:
        rt.ready(state)
    print('client終了後もモデルは残ります。停止には stop を使用してください。', flush=True)
    return run_client(argv, cwd, state)


def choose(prompt, choices, default=None):
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            return default
        if value in choices:
            return value
        print('表示された番号を入力してください。')


def finish_with_dsh():
    manager = ROOT.parent / 'Harness' / 'web_instances.py'
    if not manager.is_file():
        return True
    command = [sys.executable, '-I', '-B', '-X', 'utf8', str(manager)]
    try:
        result = subprocess.run([*command, 'list'], capture_output=True, text=True,
                                encoding='utf-8', timeout=15)
        if result.returncode:
            raise RuntimeError('DSH status unavailable.')
        instances = json.loads(result.stdout)
        if not isinstance(instances, list) or any(not isinstance(row, dict)
                or not isinstance(row.get('id'), str) or type(row.get('pid')) is not int
                or type(row.get('port')) is not int for row in instances):
            raise ValueError('Invalid DSH status.')
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print('DSHの状態を確認できません。DSHは停止していません。')
        return choose('1 DSHを残してCLIだけ終了  0 メニューに戻る [既定]> ', {'0', '1'}, '0') == '1'
    if not instances:
        return True
    print('起動中のDSH: ' + ', '.join(f"port {row['port']} / PID {row['pid']}" for row in instances))
    selected = choose('1 DSHを残して終了 [既定]  2 DSHも終了  0 戻る> ', {'0', '1', '2'}, '1')
    if selected == '0':
        return False
    if selected == '2':
        for row in instances:
            stopped = subprocess.run([*command, 'stop', '--instance', row['id']], timeout=20)
            if stopped.returncode:
                raise RuntimeError('DSHの終了を確認できませんでした。メニューに戻ります。')
    return True


def interactive(rt):
    while True:
        print('\nStrata: 1 モデル選択/起動  2 状態  3 停止  4 WebUI  5 端末chat  6 Pi  0 終了')
        action = choose('選択> ', {'0', '1', '2', '3', '4', '5', '6'})
        try:
            if action == '0':
                if finish_with_dsh():
                    return 0
                continue
            if action == '1':
                show_models()
                choices = {str(index): name for index, (name, item) in enumerate(catalog.CATALOG.items(), 1)
                           if item.get('selectable', True)}
                model = choices[choose('モデル番号 [1]> ', set(choices), '1')]
                contexts = catalog.public_contexts(model)
                labels = ' / '.join(f'{index} {value // 1024}K' for index, value in enumerate(contexts, 1))
                family = catalog.CATALOG[model].get('family') == 'deepseek41'
                default = str(contexts.index(catalog.CATALOG[model].get('default_context',contexts[-1]))+1)
                choice = choose(f'context: {labels}' + (' / c 任意context' if family else '') + f' [{default}]> ',
                                {str(index) for index in range(1,len(contexts)+1)} | ({'c'} if family else set()), default)
                ctx = int(input('context tokens (1..1048576)> ').strip()) if choice == 'c' else contexts[int(choice)-1]
                rt.validate(model, ctx)
                state = rt.state()
                switch = False
                if rt.active(state) and (state.get('model'), state.get('context')) != (model, ctx):
                    print('現在: ' + describe(state))
                    print(f'選択: {model} / context {ctx}')
                    if input('現在のowned modelを停止して切替える場合だけ SWITCH と入力> ').strip() != 'SWITCH':
                        print('切替を取り消しました。')
                        continue
                    switch = True
                start_selected(rt, model, ctx, switch, identity(state) if switch else None)
            elif action == '2':
                show_status(rt)
            elif action == '3':
                state = rt.state()
                print('現在: ' + describe(state))
                if input('owned modelを停止する場合だけ STOP と入力> ').strip() == 'STOP':
                    stop_current(rt, identity(state))
                else:
                    print('停止を取り消しました。')
            else:
                workdir = None
                if action == '6':
                    workdir = input('Pi作業directory（空欄=専用既定directory）> ').strip() or None
                code = use_ready(rt, {'4': 'web', '5': 'chat', '6': 'pi'}[action], workdir)
                if code:
                    print(f'client終了コード: {code}')
        except (OSError, ValueError, KeyError, RuntimeError, psutil.Error, subprocess.SubprocessError) as error:
            print('エラー: ' + str(error), file=sys.stderr)


def show_status(rt):
    state = rt.state()
    if not rt.active(state):
        print('owned model: 停止済み。')
        return
    print('現在: ' + describe(state))
    rt.ready(state)
    execution=describe_execution(state)
    if execution:print(execution)
    print('起動管理: ' + ('公式Strata MCP' if state.get('runtime_provider')=='official_mcp' else '従来経路（公式metadata未採用）'))
    print('health/model/context/port owner一致。 ' + URL)


def show_models():
    for index, model in enumerate(catalog.CATALOG, 1):
        ready, reason = catalog.availability(model, ROOT)
        print(f"{index} {catalog.CATALOG[model]['label']} [{model}] {'準備済み' if ready else '起動不可'}: {reason}")


def parser():
    ap = argparse.ArgumentParser(description='Strata: HuiHui UD-IQ4_XS選択、起動・切替・停止とclient入口')
    sub = ap.add_subparsers(dest='action')
    start = sub.add_parser('start', help='指定model/contextを起動（同じREADYなら再利用）')
    start.add_argument('--model', required=True, choices=MODELS)
    start.add_argument('--context', type=int, default=262144)
    for flag in ('device-cache-payload-bytes','ram-cache-payload-bytes','primary-pci'):
        start.add_argument('--'+flag)
    for flag in ('auto-cache-fraction','auto-row-fraction'):
        start.add_argument('--'+flag,type=float)
    start.add_argument('--mode',choices=('single','cache-only','expert-assist','layer-split'))
    start.add_argument('--secondary-pci')
    start.add_argument('--expert-ids',help='expert-assistのsecondary expert IDs（カンマ区切り）')
    start.add_argument('--cut',type=int,help='layer-splitの連続区間境界')
    start.add_argument('--switch', action='store_true', help='現在のowned model停止後に指定設定へ明示切替')
    for action in ['models', 'status', 'stop', 'web', 'chat']:
        sub.add_parser(action)
    pi = sub.add_parser('pi')
    pi.add_argument('--workdir', help='Piが操作する既存directory（省略時は専用workspace）')
    return ap


def main(argv=None, rt=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    native_args = []
    if raw and raw[0] == 'pi':
        # The common CLI owns one transport separator. Native -- remains in
        # the suffix untouched (the public pi wrapper inserts this boundary).
        tail = raw[1:]
        prefix = []
        while tail and (tail[0] == '--workdir' or tail[0].startswith('--workdir=')):
            value = tail.pop(0)
            prefix.append(value)
            if value == '--workdir' and tail:
                prefix.append(tail.pop(0))
        if tail and tail[0] == '--':
            tail.pop(0)
        native_args = tail
        raw = ['pi', *prefix]
    ap = parser()
    args = ap.parse_args(raw)
    if args.action == 'pi' and native_args:
        pi_root = ROOT.parent / 'Pi'
        sys.path.insert(0, str(pi_root))
        from native_arguments import native_kind, native_command, clean_native_environment
        env = clean_native_environment(os.environ)
        try:
            kind = native_kind(native_args, env)
        except RuntimeError:
            print('Pi command classification failed; no client was started.', file=sys.stderr)
            return 1
        if kind != 'agent':
            directory = pathlib.Path(args.workdir or pi_root / 'workspace').resolve()
            return subprocess.run(native_command(native_args), cwd=directory, env=env).returncode
    rt = rt or Runtime()
    try:
        if args.action is None:
            if not sys.stdin.isatty():
                ap.print_help()
                print('非対話入力では start/status/stop/web/chat/pi を明示してください。', file=sys.stderr)
                return 2
            return interactive(rt)
        if args.action == 'start':
            options = {key:getattr(args,key) for key in ('device_cache_payload_bytes','ram_cache_payload_bytes','auto_cache_fraction','auto_row_fraction','primary_pci','mode','secondary_pci','cut') if getattr(args,key) is not None}
            if args.expert_ids is not None:
                if not args.expert_ids or any(not value.isascii() or not value.isdecimal() for value in args.expert_ids.split(',')):
                    raise ValueError('expert IDsは0..383の整数をカンマで区切ってください。')
                options['assignment']=[int(value) for value in args.expert_ids.split(',')]
            for key in ('device_cache_payload_bytes','ram_cache_payload_bytes'):
                if key in options and options[key] != 'auto':options[key] = int(options[key])
            if options and catalog.CATALOG[MODELS[args.model]].get('family') != 'deepseek41':
                raise ValueError('cache/PCI overlayはDeepSeek family用です。')
            if options:rt.launch_options = options
            start_selected(rt, MODELS[args.model], args.context, args.switch)
        elif args.action == 'stop':
            stop_current(rt)
        elif args.action == 'status':
            show_status(rt)
        elif args.action == 'models':
            show_models()
        else:
            return use_ready(rt, args.action, getattr(args, 'workdir', None), native_args)
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\n操作を中断しました。既存モデルは自動停止しません。status/stopで確認してください。', file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, RuntimeError, psutil.Error, subprocess.SubprocessError) as error:
        print('エラー: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
