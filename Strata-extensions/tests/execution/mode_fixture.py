"""Controlled CPU entry helpers; never invokes an engine or SDK transport."""
import importlib.util,sys,types
import contextlib,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
OWN=Path(__file__).resolve().parents[2]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def hooks():
 # native_args does not call the Recipe; isolate that import for this CPU unit.
 with patch.dict(sys.modules,{'deepseek_recipe':types.ModuleType('deepseek_recipe')}):return load('t46_test_hooks',OWN/'models/deepseek41/server_hooks.py')
def cli():
 data=Path('C:/Develop/AI/Strata-data');sys.path.insert(0,str(data))
 try:return load('t46_test_cli',data/'strata_cli.py')
 finally:sys.path.remove(str(data))

@contextlib.contextmanager
def declared_mode_package(profile):
 with tempfile.TemporaryDirectory()as temp:
  root=Path(temp)/('a'*64);hook=root/'Strata-extensions/models/deepseek41/server_hooks.py';hook.parent.mkdir(parents=True);hook.write_bytes((OWN/'models/deepseek41/server_hooks.py').read_bytes())
  manifest=root/'evidence/package-manifest.json';manifest.parent.mkdir();manifest.write_text(json.dumps(dict(schema='strata-t29-runtime-package/v1',id=root.name,files=[dict(path=str(hook),bytes=hook.stat().st_size,sha256=hashlib.sha256(hook.read_bytes()).hexdigest())],execution_extension=dict(abi='strata-deepseek-execution/v1'))),encoding='utf8')
  yield dict(profile,runtime_package=dict(id=root.name,manifest=str(manifest)))
