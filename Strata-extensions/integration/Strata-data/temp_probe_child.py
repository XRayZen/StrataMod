"""GPU-free, bounded official TEMP selection in the existing Low launcher context."""
import _thread
import time
import os

# Start the self-only deadline before pathlib/json/psutil or official imports.
def _deadline():
    time.sleep(15)
    try:
        os.write(2, b'Low TEMP probe self deadline exceeded\n')
    finally:
        os._exit(85)


if __name__ == '__main__':
    _thread.start_new_thread(_deadline, ())

import argparse
import contextlib
import huihui_authority as authority
import importlib
import json
from pathlib import Path
import sys

import psutil
import official_runtime as official
import startup_progress
from runtime_permissions import integrity_rid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--context', required=True, type=int)
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args(argv)
    config = Path(args.config)
    scope = authority.inspection_scope(args.model,args.context,config) if args.model == authority.MODEL else contextlib.nullcontext()
    with scope:
        return inspect(args,config)


def inspect(args,config):
    family = startup_progress.family_launch(config)
    if ((not family and official.require_registration(args.model, args.context) != config)
            or (family and not family[2])
            or official.digest(config) != args.config_sha256
            or official.digest(official.REPO / 'serve/server.py') != official.SERVER_SHA256):
        raise RuntimeError('Low TEMP probe pinned source/config mismatch')
    if family:
        helper = official.ROOT.parent / 'Strata-extensions/control/deepseek_bootstrap.py'
        spec = importlib.util.spec_from_file_location('strata_installed_deepseek_bootstrap', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        selected_scope = module.selected_server(family[1])
    else:
        sys.path.insert(0, str(official.REPO))
        selected_scope = contextlib.nullcontext(importlib.import_module('serve.server'))
    cfg = json.loads(config.read_text(encoding='utf-8-sig'))
    with selected_scope as server, official.windows_temp_probe(server,selected_config=cfg if family else None):
        effective = server.child_env(cfg)
    process, parent = psutil.Process(), psutil.Process(os.getppid())
    result = dict(version=1, attempt=args.attempt, config_sha256=official.digest(config),
                  server_sha256=(official.digest(Path(cfg['exe']).parent / 'server/serve/server.py') if family else official.SERVER_SHA256), mcp_sha256=official.MCP_SHA256,
                  setup_sha256=official.SETUP_SHA256, helper_sha256=official.digest(__file__),
                  identity=dict(pid=process.pid, created=process.create_time(), exe=process.exe()),
                  parent_identity=dict(pid=parent.pid, created=parent.create_time(), exe=parent.exe()),
                  sys_executable=sys.executable, prefix=sys.prefix, integrity_rid=integrity_rid(),
                  temporary_environment={key: effective[key] for key in ('TEMP', 'TMP', 'TMPDIR') if key in effective})
    print(json.dumps(result), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

