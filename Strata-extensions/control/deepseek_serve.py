"""Normal family entry into the existing Strata HTTP server and owner controls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
OWN=Path(__file__).resolve().parents[1]
ROOT=OWN.parent
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def main(argv=None):
    argv=list(sys.argv[1:]if argv is None else argv)
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--config',required=True);parser.add_argument('--server-module')
    selected,rest=parser.parse_known_args(argv)
    config=json.loads(Path(selected.config).read_text(encoding='utf-8-sig'))
    # Prepared server is a build artifact adjacent to the native executable.
    path=Path(selected.server_module)if selected.server_module else Path(config['exe']).parent/'server/serve/server.py'
    upstream=Path(config.get('upstream_root',str(ROOT)))
    if not upstream.is_absolute()or not(upstream/'serve/frontend.py').is_file():raise ValueError('upstream_root must name the existing Strata source directory')
    upstream=upstream.resolve()
    sys.path.insert(0,str(upstream));sys.path.insert(0,str(upstream/'tools'))
    os.environ['STRATA_FAMILY_SOURCE_ROOT']=str(upstream) # this normal child only
    server=load(path,'serve.server')
    hook=load(OWN/'models/deepseek41/server_hooks.py','deepseek_normal_server_hooks')
    hook.install(server,config)
    forwarded=rest+['--config',selected.config]
    sys.argv=[str(path),*forwarded]
    server.main()
if __name__=='__main__':main()
