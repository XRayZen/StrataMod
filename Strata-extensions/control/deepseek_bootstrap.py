"""Selected family entry instrumentation; owns neither listener nor model code."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


launch = load(Path(__file__).with_name('deepseek_launch.py'), 'strata_selected_deepseek_launch')


@contextlib.contextmanager
def selected_server(cfg):
    """GPU-free inspection scoped away from the manager's legacy import state."""
    import os
    root = Path(cfg['upstream_root'])
    package = Path(cfg['runtime_package']['manifest']).parent.parent.resolve()
    names = {path.stem for path in (root/'tools').glob('*.py')}
    def scoped(name, module):
        if name=='serve' or name.startswith('serve.') or name in names or name=='strata_selected_deepseek_entry':
            return True
        path=getattr(module,'__file__',None)
        return bool(path) and Path(path).resolve().is_relative_to(package)
    modules=dict(sys.modules)
    path_before=list(sys.path)
    missing=object()
    source_before=os.environ.get('STRATA_FAMILY_SOURCE_ROOT',missing)
    try:
        for name,module in list(sys.modules.items()):
            if scoped(name,module):sys.modules.pop(name,None)
        entry=load(Path(cfg['server_entry']),'strata_selected_deepseek_entry')
        sys.path[:0]=[str(root),str(root/'tools')]
        os.environ['STRATA_FAMILY_SOURCE_ROOT']=str(root)
        yield entry.load(Path(cfg['exe']).parent/'server/serve/server.py','serve.server')
    finally:
        for name,module in list(sys.modules.items()):
            if scoped(name,module):
                if name in modules:sys.modules[name]=modules[name]
                else:sys.modules.pop(name,None)
        for name,module in modules.items():
            if scoped(name,module):sys.modules[name]=module
        sys.path[:]=path_before
        if source_before is missing:os.environ.pop('STRATA_FAMILY_SOURCE_ROOT',None)
        else:os.environ['STRATA_FAMILY_SOURCE_ROOT']=source_before


@contextlib.contextmanager
def hooks(server, writer, official, selected_config=None):
    original_factory = server.FAMILY_TOKENIZER_FACTORY
    original_env, original_popen = server.child_env, server.popen
    engine_type = server.StrataEngine
    original_init = engine_type.__init__
    engine_attempt = 0

    def tokenizer(*args, **kwargs):
        writer.emit('tokenizer_begin')
        value = original_factory(*args, **kwargs)
        writer.emit('tokenizer_end')
        return value

    def child_env(cfg):
        writer.emit('temp_begin')
        value = original_env(cfg)
        writer.emit('temp_end')
        return value

    def popen(what, argv, **kwargs):
        nonlocal engine_attempt
        engine = what == 'the Strata engine'
        if engine:
            engine_attempt += 1
            writer.emit('engine_spawn_begin')
        process = original_popen(what, argv, **kwargs)
        if engine:
            import psutil
            from runtime_permissions import integrity_rid
            token = None
            try:
                token = integrity_rid(process._handle)
            except (OSError,RuntimeError,TypeError,ValueError) as error:
                print('[startup diagnostic] engine integrity unverified: '+type(error).__name__,flush=True)
            try:
                identity = psutil.Process(process.pid)
                writer.emit('engine_started', engine_pid=process.pid,
                            engine_created=identity.create_time(), engine_exe=identity.exe(),
                            engine_attempt=engine_attempt, engine_integrity_rid=token)
            except psutil.Error as error:
                print('[startup diagnostic] engine identity unavailable: '+type(error).__name__,flush=True)
        return process

    def engine_init(self, *args, **kwargs):
        value = original_init(self, *args, **kwargs)
        if getattr(self, 'max_context', 0) > 0 and getattr(self, 'proc', None):
            writer.emit('engine_ready')
        return value

    server.FAMILY_TOKENIZER_FACTORY, server.child_env = tokenizer, child_env
    server.popen, engine_type.__init__ = popen, engine_init
    try:
        with (official.windows_temp_probe(server,selected_config=selected_config) if selected_config is not None
              else official.windows_temp_probe(server)):
            yield
    finally:
        server.FAMILY_TOKENIZER_FACTORY, server.child_env = original_factory, original_env
        server.popen, engine_type.__init__ = original_popen, original_init


def run(args, writer, official):
    config = Path(args.config)
    binding = json.loads(config.with_suffix('.launch.json').read_text(encoding='utf-8'))
    cfg = launch.verify_binding(config, binding)
    if binding['attempt'] != args.attempt:
        raise RuntimeError('Family bootstrap attempt mismatch')
    launch.verify_parent(binding)
    if args.verify_only:
        return 0
    entry = load(Path(cfg['server_entry']), 'strata_selected_deepseek_entry')
    original_load = entry.load

    def observed_load(path, name):
        server = original_load(path, name)
        if name == 'serve.server':
            original_main = server.main

            def main():
                writer.emit('server_import_end')
                # entry.main installs the family hook after load() returns.
                with hooks(server, writer, official, cfg):
                    return original_main()

            server.main = main
        return server

    entry.load = observed_load
    writer.emit('server_import_begin')
    try:
        return entry.main(launch.server_command(cfg, config)[7:])
    finally:
        entry.load = original_load
