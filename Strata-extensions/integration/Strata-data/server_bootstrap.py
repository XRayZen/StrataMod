"""Pinned external bootstrap for official Strata; no source or permission changes."""
import argparse
import contextlib
import faulthandler
import importlib
import os
from pathlib import Path
import sys

import psutil
import huihui_authority as authority
import official_runtime as official
from startup_progress import StageWriter, stage_path, sha256, family_launch
from runtime_permissions import integrity_rid


@contextlib.contextmanager
def startup_hooks(server, writer):
    """Instrument exact startup calls while leaving official load/retry behavior intact."""
    tokenizer = importlib.import_module('strata_tokenizer').Tokenizer
    original_tokenizer, original_env = tokenizer.__init__, server.child_env
    original_popen, original_engine = server.popen, server.StrataEngine.__init__
    engine_attempt = 0

    def token_init(self, *args, **kwargs):
        writer.emit('tokenizer_begin')
        result = original_tokenizer(self, *args, **kwargs)
        writer.emit('tokenizer_end')
        return result

    def child_env(cfg):
        writer.emit('temp_begin')
        result = original_env(cfg)
        writer.emit('temp_end')
        return result

    def popen(what, args, **kwargs):
        nonlocal engine_attempt
        engine = what == 'the Strata engine'
        if engine:
            engine_attempt += 1
            writer.emit('engine_spawn_begin')
        process = original_popen(what, args, **kwargs)
        if engine:
            engine_token = None
            try:
                engine_token = integrity_rid(process._handle)
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                print(f'[startup diagnostic] engine integrity unverified: {type(error).__name__}', flush=True)
            try:
                identity = psutil.Process(process.pid)
                writer.emit('engine_started', engine_pid=process.pid,
                            engine_created=identity.create_time(), engine_exe=identity.exe(),
                            engine_attempt=engine_attempt, engine_integrity_rid=engine_token)
            except psutil.Error as error:
                print(f'[startup diagnostic] engine identity unavailable: {type(error).__name__}', flush=True)
        return process

    def engine_init(self, *args, **kwargs):
        result = original_engine(self, *args, **kwargs)
        if getattr(self, 'max_context', 0) > 0 and getattr(self, 'proc', None):
            writer.emit('engine_ready')
        return result

    tokenizer.__init__, server.child_env = token_init, child_env
    server.popen, server.StrataEngine.__init__ = popen, engine_init
    try:
        with official.windows_temp_probe(server):
            yield
    finally:
        tokenizer.__init__, server.child_env = original_tokenizer, original_env
        server.popen, server.StrataEngine.__init__ = original_popen, original_engine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--verify-only',action='store_true',help='Verify parent/config binding and exit before official server import')
    args = parser.parse_args(argv)
    config = Path(args.config)
    model, context = config.stem.removeprefix('strata-').rsplit('-', 1)
    with authority.bootstrap_scope(model,int(context),config,args.attempt,args.stage,args.verify_only):
        return run_verified(args,config,model,int(context))


def run_verified(args,config,model,context):
    family = family_launch(config)
    if family:
        if not family[2] or family[2]['attempt'] != args.attempt or Path(args.stage) != stage_path(args.attempt):
            raise RuntimeError('Family bootstrap config/attempt/stage mismatch')
        from importlib.util import spec_from_file_location, module_from_spec
        helper = official.ROOT.parent / 'Strata-extensions/control/deepseek_bootstrap.py'
        spec = spec_from_file_location('strata_installed_deepseek_bootstrap', helper)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        writer = StageWriter(args.stage, args.attempt, sha256(config))
        writer.emit('bootstrap_started')
        return module.run(args, writer, official)
    if (config != official.registered_path(model, int(context))
            or official.require_registration(model, int(context)) != config
            or Path(args.stage) != stage_path(args.attempt)
            or official.digest(official.REPO / 'serve/server.py') != official.SERVER_SHA256):
        raise RuntimeError('Bootstrap config, attempt, or pinned official source mismatch')
    config_sha = sha256(config)
    if args.verify_only:
        print('Bootstrap binding verified; official server was not imported or started.',flush=True)
        return 0

    def phase_changed(phase):
        faulthandler.cancel_dump_traceback_later()
        if phase not in ('engine_started', 'engine_ready'):
            faulthandler.dump_traceback_later(30, repeat=True)

    writer = StageWriter(args.stage, args.attempt, config_sha, phase_changed)
    writer.emit('bootstrap_started')
    try:
        writer.emit('server_import_begin')
        sys.path.insert(0, str(official.REPO))
        server = importlib.import_module('serve.server')
        writer.emit('server_import_end')
        # The unchanged official main uses the same argument vector as its MCP entry.
        sys.argv = [str(official.REPO / 'serve/server.py'), '--engine', 'strata',
                    '--config', str(config), '--port', '18080']
        if sha256(config) != config_sha:
            raise RuntimeError('Bootstrap config changed before official main')
        with startup_hooks(server, writer):
            return server.main()
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    raise SystemExit(main())
