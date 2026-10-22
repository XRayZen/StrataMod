"""T30 pure launch contracts; no listener, model, or native process."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import shutil
import sys
import subprocess
import os
import types
import contextlib
from unittest.mock import patch, Mock

OWN = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location('t30_launch', OWN / 'control/deepseek_launch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LaunchTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,'C:/Develop/AI/Strata-data')
        self.m = load()
        self.cfg = json.loads(Path('C:/Develop/AI/Strata-data/profiles/deepseek-v4.1-flash-1017-ud-q4_k_xl-4096.json').read_text(encoding='utf-8'))

    def test_overlay_does_not_mutate_saved_profile(self):
        before = json.dumps(self.cfg, sort_keys=True)
        value = self.m.overlay(self.cfg, {'auto_cache_fraction': 0, 'ram_cache_payload_bytes': 123456})
        self.assertEqual(value['auto_cache_fraction'], 0)
        self.assertEqual(value['cache_budget']['ram_cache_payload_bytes'], 123456)
        self.assertEqual(json.dumps(self.cfg, sort_keys=True), before)

    def test_fraction_and_payload_domains(self):
        for value in (False, -1, float('nan'), 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.m.overlay(self.cfg, {'auto_row_fraction': value})
        for value in (0, True, -1, '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.m.overlay(self.cfg, {'device_cache_payload_bytes': value})
        for value in (0, .5, 1):
            self.assertEqual(self.m.overlay(self.cfg, {'auto_row_fraction': value})['auto_row_fraction'], value)

    def test_unknown_overlay_is_rejected(self):
        with self.assertRaises(ValueError):
            self.m.overlay(self.cfg, {'args': ['--context', '3']})

    def test_epoch_and_resolved_source_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'
            source.write_text(json.dumps(self.cfg), encoding='utf-8')
            attempt = str(uuid.uuid4())
            path, binding = self.m.resolve(source, root, attempt, 12)
            actual = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(actual['runtime_epoch'], 12)
            self.assertNotIn('runtime_epoch', json.loads(source.read_text(encoding='utf-8')))
            self.assertEqual(self.m.verify_binding(path, binding), actual)
            actual['runtime_epoch'] = 13
            path.write_text(json.dumps(actual), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                self.m.verify_binding(path, binding)

    def test_resolved_collision_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            source.write_text(json.dumps(self.cfg), encoding='utf-8')
            args = (source, Path(directory), str(uuid.uuid4()), 1)
            self.m.resolve(*args)
            with self.assertRaises(FileExistsError):
                self.m.resolve(*args)

    def test_invalid_epoch_and_attempt(self):
        for value in (0, True, -1, 2**64):
            with self.assertRaises(ValueError):
                self.m.positive_epoch(value)
        with self.assertRaises(ValueError):
            self.m.canonical_attempt('not-an-attempt')

    def test_bootstrap_parent_requires_fresh_birth_and_executable(self):
        current=dict(pid=123,created=15.,exe='C:/selected/python.exe')
        with patch.object(self.m,'current_identity',return_value=current):
            self.assertEqual(self.m.verify_parent({'parent':dict(current)}),current)
            for change in ({'pid':124},{'created':16.},{'created':True},{'exe':'C:/foreign/python.exe'}):
                with self.subTest(change=change),self.assertRaises(RuntimeError):
                    self.m.verify_parent({'parent':dict(current,**change)})

    def test_selected_command_and_installed_path(self):
        cmd = self.m.server_command(self.cfg, Path('C:/resolved/config.json'))
        self.assertEqual(cmd[:6], [self.cfg['python'], '-E', '-s', '-B', '-X', 'utf8'])
        self.assertEqual(cmd[6], self.cfg['server_entry'])
        self.assertIn(str(Path('C:/resolved/config.json')), cmd)
        self.assertEqual(self.m.helper_path(Path('C:/Develop/AI/Strata-data')).as_posix(),
                         'C:/Develop/AI/Strata-extensions/control/deepseek_launch.py')

    def test_native_command_matches_selected_adapter(self):
        # Parse the pinned adapter's pure function only: no Recipe import or model.
        import ast
        source = Path(self.cfg['server_entry']).parents[1] / 'models/deepseek41/server_hooks.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='native_args')
        scope = {}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),scope)
        cfg = dict(self.cfg,runtime_epoch=12)
        self.assertEqual(self.m.native_command(cfg),[cfg['exe'],'--serve',*scope['native_args'](cfg)])

    def test_installed_helper_and_bootstrap_exact_commands(self):
        sys.path.insert(0,'C:/Develop/AI/Strata-data')
        import startup_progress as progress
        import manage_runtime as manager
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)/'Strata-data'
            data.mkdir()
            control = data.parent/'Strata-extensions/control'
            control.mkdir(parents=True)
            for name in ('deepseek_launch.py','deepseek_bootstrap.py'):
                shutil.copyfile(OWN/'control'/name,control/name)
            spec = importlib.util.spec_from_file_location('t30_installed_launch',control/'deepseek_launch.py')
            installed = importlib.util.module_from_spec(spec);spec.loader.exec_module(installed)
            source = data/'source.json';source.write_text(json.dumps(self.cfg),encoding='utf-8')
            attempt = str(uuid.uuid4())
            config,binding = installed.resolve(source,data,attempt,123)
            with patch.object(progress,'ROOT',data):
                command = progress.bootstrap_command(config,attempt)
                self.assertEqual(command[0],str(progress.BASE_PYTHON))
                self.assertTrue(progress.is_bootstrap_command(command,config))
                self.assertFalse(progress.is_bootstrap_command([*command[:-1],'foreign'],config))
                cfg = progress.family_launch(config)[1]
                native = installed.native_command(cfg)
                self.assertTrue(manager.allowed_child(Path(cfg['exe']).resolve(),native,config))
                self.assertFalse(manager.allowed_child(Path(cfg['exe']).resolve(),native+['--context','3'],config))
                self.assertFalse(manager.allowed_child(control/'foreign.exe',[],config))
                (control/'deepseek_launch.py').write_text('# changed',encoding='utf-8')
                with self.assertRaises((RuntimeError,AttributeError)):
                    progress.family_launch(config)

    def test_current_huihui_profiles_and_defaults_preserved(self):
        sys.path.insert(0,'C:/Develop/AI/Strata-data')
        import manage_runtime as manager
        import model_catalog as catalog
        import hashlib
        baseline=json.loads((OWN.parent/'build-deepseek-t30/baseline-r1.json').read_text(encoding='utf-8'))
        rows=[row for row in baseline['profile_before'] if 'huihui-ud-q4_k_xl_v2-' in row['path']]
        self.assertEqual(len(rows),4)
        for row in rows:
            path=Path(row['path']);value=json.loads(path.read_text(encoding='utf-8'))
            context=int(path.stem.rsplit('-',1)[1])
            manager.validate_profile(value,context)
            catalog.validate_layout(value,'huihui-ud-q4_k_xl_v2',context,2)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),row['sha256'])
        self.assertEqual(catalog.public_contexts('huihui-ud-q4_k_xl_v2'),(262144,))

    def test_cli_family_options_and_legacy_rejection(self):
        import strata_cli as cli
        runtime=Mock()
        with patch.object(cli,'start_selected') as selected:
            self.assertEqual(cli.main(['start','--model',self.cfg['model_name'],'--context','524289',
                                      '--auto-cache-fraction','0','--device-cache-payload-bytes','auto'],runtime),0)
            self.assertEqual(runtime.launch_options,{'device_cache_payload_bytes':'auto','auto_cache_fraction':0.0})
            self.assertEqual(selected.call_args.args[2],524289)
        with patch.object(cli,'start_selected') as selected:
            self.assertEqual(cli.main(['start','--model','huihui-ud-q4_k_xl_v2','--device-cache-payload-bytes','100'],Mock()),1)
            selected.assert_not_called()

    def test_current_family_assets_and_arbitrary_context_validate_without_publish(self):
        import strata_cli as cli
        model=self.cfg['model_name']
        target=Path('C:/Develop/AI/Strata-data/profiles')/(model+'-524289.json')
        self.assertFalse(target.exists())
        with patch.object(cli.official_runtime,'require_registration',side_effect=AssertionError('validation must not register')):
            cli.Runtime().validate(model,4096)
            cli.Runtime().validate(model,524289)
        self.assertFalse(target.exists())

    def test_selected_low_result_keeps_identity_and_unknown_guards(self):
        import startup_progress as progress
        import runtime_temp_probe as probe
        import official_runtime as official
        python=Path(self.cfg['python'])
        root=dict(pid=100,created=10.,exe=str(python))
        child=dict(pid=101,created=11.,exe=str(progress.BASE_PYTHON))
        result=dict(version=1,attempt='probe-attempt',config_sha256='config',
                    server_sha256=official.digest(Path(self.cfg['exe']).parent/'server/serve/server.py'),
                    mcp_sha256=official.MCP_SHA256,setup_sha256=official.SETUP_SHA256,
                    helper_sha256='helper',identity=child,parent_identity=root,
                    sys_executable=str(python),prefix=str(python.parent.parent),integrity_rid=4096,
                    temporary_environment={'TMP':'C:/selected/temporary'})
        self.assertEqual(probe.validate_result(result,root,'probe-attempt','config','helper',(self.m,self.cfg,None)),result['temporary_environment'])
        for change in ({'integrity_rid':8192},{'prefix':'C:/foreign'},{'identity':dict(child,pid=100)},
                       {'parent_identity':dict(root,created=99.)},{'server_sha256':'foreign'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                probe.validate_result(dict(result,**change),root,'probe-attempt','config','helper',(self.m,self.cfg,None))

    def test_selected_python_cpu_child_has_exact_parent_and_exits(self):
        from runtime_permissions import handle_identity
        import manage_runtime as manager
        command=[self.cfg['python'],'-E','-s','-B','-X','utf8',str(Path(__file__).with_name('fixture_child.py'))]
        nonce=str(uuid.uuid4())
        with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              text=True,encoding='utf-8',cwd=Path(self.cfg['python']).parent) as process:
            identity=handle_identity(process._handle)
            stdout,stderr=process.communicate(json.dumps({'nonce':nonce})+'\n',timeout=15)
            self.assertEqual(process.returncode,0,stderr)
            actual=json.loads(stdout)
            self.assertEqual(actual['nonce'],nonce)
            if actual['pid']==identity['pid']:
                self.assertEqual(actual['parent_pid'],os.getpid())
            else:
                self.assertEqual(actual['parent_pid'],identity['pid'])
                self.assertEqual(Path(actual['exe']).resolve(),Path(manager.startup_progress.BASE_PYTHON).resolve())
            self.assertFalse(actual['model_qualified'])
        self.assertEqual(manager.process_identity_status(identity).status,'gone')
        self.assertEqual(manager.process_identity_status({key:actual[key] for key in ('pid','created','exe')}).status,'gone')

    def test_base_bootstrap_uses_selected_venv_without_redirector_pid(self):
        import startup_progress as progress
        from runtime_permissions import handle_identity
        env=dict(os.environ,__PYVENV_LAUNCHER__=self.cfg['python'])
        command=[str(progress.BASE_PYTHON),'-E','-s','-B','-X','utf8',str(Path(__file__).with_name('fixture_child.py'))]
        with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              text=True,encoding='utf-8',env=env) as process:
            identity=handle_identity(process._handle)
            output,errors=process.communicate('{"nonce":"base-bootstrap"}\n',timeout=15)
            self.assertEqual(process.returncode,0,errors)
            actual=json.loads(output)
            self.assertEqual(actual['pid'],identity['pid'])
            self.assertEqual(actual['parent_pid'],os.getpid())
            self.assertEqual(Path(actual['sys_executable']),Path(self.cfg['python']))
            self.assertEqual(Path(actual['prefix']),Path(self.cfg['python']).parent.parent)

    def test_native_info_rejects_unknown_and_mismatched_capacity(self):
        cfg=self.cfg
        good=dict(family='deepseek41',context=4096,device_slots=1,ram_slots=1,row_device_slots=1,row_ram_slots=1,
                  device_cache_payload_bytes=2097416,ram_cache_payload_bytes=2097416,
                  declared_device_cache_payload_bytes=None,declared_ram_cache_payload_bytes=None,
                  auto_cache_fraction=.5,auto_row_fraction=1/64)
        self.assertEqual(self.m.validate_ready_info(cfg,good),good)
        for change in ({'context':16},{'family':'foreign'},{'device_slots':None},{'ram_slots':True},
                       {'declared_device_cache_payload_bytes':1},{'auto_row_fraction':False}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                self.m.validate_ready_info(cfg,dict(good,**change))
        missing=dict(good);missing.pop('declared_ram_cache_payload_bytes')
        with self.assertRaises(RuntimeError):self.m.validate_ready_info(cfg,missing)

    def test_ready_uses_metrics_native_info_not_busy_status(self):
        import manage_runtime as manager
        cfg=dict(self.cfg);binding={'test':'bound'}
        native=dict(exe=cfg['exe'],pid=123,created=1.)
        state=dict(config='resolved',launch_binding=binding,owned_identities=[native])
        process=Mock();process.cmdline.return_value=self.m.native_command(dict(cfg,runtime_epoch=1))
        cfg['runtime_epoch']=1
        good=dict(family='deepseek41',context=4096,device_slots=1,ram_slots=1,row_device_slots=1,row_ram_slots=1,
                  device_cache_payload_bytes=2097416,ram_cache_payload_bytes=2097416,
                  declared_device_cache_payload_bytes=None,declared_ram_cache_payload_bytes=None,
                  auto_cache_fraction=.5,auto_row_fraction=1/64)
        def response(path):return {'engine':good}if path=='/metrics' else {'busy':False,'queued':0}
        with patch.object(manager.startup_progress,'family_launch',return_value=(self.m,cfg,binding)), \
             patch.object(manager,'process_identity_status',return_value={}), \
             patch.object(manager,'require_identity',return_value=process), \
             patch.object(manager,'get_json',side_effect=response)as fetch:
            actual=manager.require_family_ready(state)
            fetch.assert_called_once_with('/metrics')
            self.assertEqual(actual['native_info'],good)
            self.assertEqual(actual['native_INFO_identity_fields'],dict(bundle_id=None,runtime_epoch=None,primary_pci=None))
        with patch.object(manager.startup_progress,'family_launch',return_value=(self.m,cfg,binding)), \
             patch.object(manager,'process_identity_status',return_value={}), \
             patch.object(manager,'require_identity',return_value=process), \
             patch.object(manager,'get_json',return_value={'busy':False}):
            with self.assertRaises(RuntimeError):manager.require_family_ready(state)

    def test_optional_spawn_diagnostics_do_not_lose_returned_process(self):
        import psutil
        spec=importlib.util.spec_from_file_location('t30_bootstrap',OWN/'control/deepseek_bootstrap.py')
        bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
        process=Mock(pid=123,_handle=123)
        class Engine:
            def __init__(self):self.max_context=0
        original=Mock(return_value=process)
        server=types.SimpleNamespace(FAMILY_TOKENIZER_FACTORY=lambda value:value,child_env=lambda cfg:cfg,
                                     popen=original,StrataEngine=Engine)
        official=types.SimpleNamespace(windows_temp_probe=lambda server:contextlib.nullcontext())
        writer=Mock()
        with patch('psutil.Process',side_effect=psutil.AccessDenied(123)), \
             patch('runtime_permissions.integrity_rid',side_effect=TypeError('unobserved')):
            with bootstrap.hooks(server,writer,official):
                self.assertIs(server.popen('the Strata engine',[]),process)
        self.assertIs(server.popen,original)
        self.assertFalse(any(call.args[0]=='engine_started' for call in writer.emit.call_args_list))

    def test_selected_import_restores_legacy_modules_paths_and_environment(self):
        import importlib
        spec=importlib.util.spec_from_file_location('t30_scoped_bootstrap',OWN/'control/deepseek_bootstrap.py')
        bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
        before_path=list(sys.path)
        before_env=os.environ.get('STRATA_FAMILY_SOURCE_ROOT')
        try:
            sys.path.insert(0,'C:/Develop/AI/Strata')
            legacy=importlib.import_module('serve.server')
            original={key:value for key,value in sys.modules.items() if key=='serve' or key.startswith('serve.')}
            expected_path=list(sys.path)
            with bootstrap.selected_server(self.cfg) as selected:
                self.assertNotEqual(Path(selected.__file__).resolve(),Path(legacy.__file__).resolve())
                self.assertEqual(Path(selected.__file__).resolve(),Path(self.cfg['exe']).parent/'server/serve/server.py')
                self.assertEqual(os.environ['STRATA_FAMILY_SOURCE_ROOT'],self.cfg['upstream_root'])
            self.assertIs(importlib.import_module('serve.server'),legacy)
            self.assertEqual(sys.path,expected_path)
            self.assertEqual({key:value for key,value in sys.modules.items() if key=='serve' or key.startswith('serve.')},original)
            self.assertEqual(os.environ.get('STRATA_FAMILY_SOURCE_ROOT'),before_env)
            broken=dict(self.cfg,exe='C:/not-a-selected-runtime/Strata-deepseek.exe')
            with self.assertRaises(FileNotFoundError):
                with bootstrap.selected_server(broken):raise AssertionError('missing source must not load')
            self.assertIs(importlib.import_module('serve.server'),legacy)
            self.assertEqual(sys.path,expected_path)
            self.assertEqual(os.environ.get('STRATA_FAMILY_SOURCE_ROOT'),before_env)
        finally:
            sys.path[:]=before_path

    def test_selected_temp_guard_keeps_package_source_pin(self):
        import official_runtime as official
        path=Path(self.cfg['exe']).parent/'server/serve/server.py'
        original=lambda name:False
        server=types.SimpleNamespace(__file__=str(path),_dir_writable=original)
        with official.windows_temp_probe(server,selected_config=self.cfg):
            self.assertIs(server._dir_writable,official.directory_writable_once)
        self.assertIs(server._dir_writable,original)
        for cfg in (dict(self.cfg,bundle_id='0'*64),dict(self.cfg,family='foreign')):
            with self.assertRaises(RuntimeError):
                with official.windows_temp_probe(server,selected_config=cfg):
                    raise AssertionError('wrong selected package accepted')
        with patch.object(official,'digest',return_value='bad'):
            with self.assertRaises(RuntimeError):
                with official.windows_temp_probe(server,selected_config=self.cfg):
                    raise AssertionError('changed prepared source accepted')
        self.assertIs(server._dir_writable,original)


if __name__ == '__main__':
    unittest.main()
