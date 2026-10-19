"""Offline invariants for the approved official bundle deployment."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_runtime import normal_runtime as n, manifest as m
from serve.server import Vision, vision_env


class OfficialReader(unittest.TestCase):
    def test_quiet_reader_identity_and_reject_wrong_mask_or_native_argv(self):
        from unittest.mock import Mock
        from local_runtime import release_revision as r
        for backend,mutation in (('hip',None),('cpu',None),('hip','mask'),('hip','argv'),('hip','device')):
            with self.subTest(backend=backend,mutation=mutation),tempfile.TemporaryDirectory() as td:
                root=Path(td);cfg=dict(exe=str(root/'strata.exe'),backend='hip',gpu=0,hip_ordinal=1,args=[],
                    log=str(root/'engine.log'),vision=self.config())
                cfg['vision'].update(exe=str(root/'strata-vision-hip.exe'),cpu_exe=str(root/'strata-vision.exe'))
                raw='GPU 0: AMD Radeon AI PRO R9700 (gfx1201)\nstrata-vision: warmed up at 289 image tokens in 1.2 s\n'
                # A supplementary line cannot excuse wrong mask/argv.
                if mutation:raw+=('  Device 0: wrong GPU, gfx1100\n' if mutation=='device' else '  Device 0: AMD Radeon AI PRO R9700, gfx1201\n')
                Path(cfg['log']).write_text(raw,encoding='utf-8')
                chosen=cfg['vision']['exe'] if backend=='hip' else cfg['vision']['cpu_exe']
                commands=n.expected_child_commands(cfg)
                identities=[dict(exe=cfg['exe'],argv=commands[str(Path(cfg['exe']).resolve())]),
                            dict(exe=chosen,argv=commands[str(Path(chosen).resolve())])]
                if mutation=='mask':cfg['hip_ordinal']=0
                if mutation=='argv':identities[1]['argv']=identities[1]['argv']+['--require-hip']
                dlls=[dict(path=str(root/name),sha256='signed') for name in ('amdhip64_7.dll','hipblas.dll','rocblas.dll')]
                assets={row['path']:dict(sha256='signed') for row in dlls};state={}
                with patch.object(r,'RUNTIME',root),patch.object(n.safety,'get_json',return_value=dict(vision=dict(available=True,backend=backend,cleanup_pending=False,error=None))),\
                     patch.object(n.safety,'process_identity_status'),patch.object(n.safety,'require_identity',return_value=object()),\
                     patch.object(n.gpu_observation,'loaded_modules',return_value=dlls),patch.object(n.gpu_observation,'bind_module_hashes'),\
                     patch.object(m,'CRITICAL_DLLS',('amdhip64_7.dll',)),patch.object(n.gpu_observation,'windows_displays',return_value=[]),\
                     patch.object(n.gpu_observation,'dxgi_adapters',return_value=[]),patch.object(n.gpu_observation,'select_adapter',return_value=dict(name='R9700')),\
                     patch.object(m,'read_json',return_value={}):
                    if mutation:
                        with self.assertRaises(RuntimeError):r.ready(n,state,cfg,dict(assets=assets),Mock(),dict(identities=identities))
                    else:
                        r.ready(n,state,cfg,dict(assets=assets),Mock(),dict(identities=identities))
                        self.assertEqual(state['loader']['reader_backend'],backend)
                        self.assertEqual(state['loader']['reader_device_lines'],[])
                        self.assertEqual(state['loader']['reader_binding']['graph_observation'],'not available in signed official reader')

    def test_public_service_status_health_models_props_and_ready_gate_use_actual_reader(self):
        import json,urllib.request
        from unittest.mock import Mock
        from serve import server as s
        from local_runtime import release_revision as r
        for backend,pending in (('hip',False),('cpu',False),('hip',True)):
            with self.subTest(backend=backend,pending=pending),tempfile.TemporaryDirectory() as td:
                cfg=self.config();cfg['temp_dir']=td
                with patch.object(Vision,'work_dir',return_value=Path(td)):
                    vision=Vision(cfg,lazy=True)
                vision.reader_backend=backend;vision.cleanup_pending=pending;vision.stopped=pending
                vision.proc=Mock();vision.proc.poll.return_value=None
                tok=s.ByteTokenizer();svc=s.Service(s.MockEngine(tok,'fixture',max_context=4096),tok,s.ChatTemplate(s.ROOT/'serve/chat_template.jinja'),vision=vision)
                httpd=s.serve(svc,port=0)
                try:
                    def get(path):
                        with urllib.request.urlopen(f'http://127.0.0.1:{httpd.server_address[1]}'+path,timeout=3) as response:return json.load(response)
                    public=get('/v1/status')['vision']
                    self.assertEqual(public.get('backend'),backend)
                    self.assertEqual(public['cleanup_pending'],pending)
                    self.assertEqual(get('/health')['images'],not pending)
                    self.assertEqual('image' in get('/v1/models')['data'][0]['architecture']['input_modalities'],not pending)
                    self.assertEqual(get('/props')['modalities']['vision'],not pending)
                    config=dict(exe='text.exe',vision=cfg)
                    selected=cfg['exe'] if backend=='hip' else cfg['cpu_exe']
                    observation=dict(identities=[dict(exe='text.exe'),dict(exe=selected)])
                    with patch.object(n.safety,'get_json',return_value=dict(vision=public)),patch.object(n.safety,'process_identity_status'),\
                         patch.object(n.safety,'require_identity',return_value=object()),patch.object(n.gpu_observation,'loaded_modules',side_effect=ValueError('passed capability gate')) as loader:
                        if pending:
                            with self.assertRaisesRegex(RuntimeError,'capability'):r.ready(n,{},config,dict(assets={}),Mock(),observation)
                            loader.assert_not_called()
                        else:
                            with self.assertRaisesRegex(ValueError,'passed capability'):r.ready(n,{},config,dict(assets={}),Mock(),observation)
                finally:httpd.shutdown();httpd.server_close()

    def test_fresh_official_gpu_failure_needs_exit_before_cpu_and_reports_actual_backend(self):
        import io,subprocess
        from unittest.mock import Mock
        from serve import server as s
        for pending in (False,True):
            with self.subTest(pending=pending),tempfile.TemporaryDirectory() as td:
                cfg=self.config();cfg['temp_dir']=td
                with patch.object(Vision,'work_dir',return_value=Path(td)):
                    v=Vision(cfg,lazy=True)
                gpu=Mock(stdin=io.StringIO(),stdout=io.StringIO('ERR GPU unavailable\n'))
                gpu.poll.return_value=None
                cpu=Mock(stdin=io.StringIO(),stdout=io.StringIO('READY 2048\n'));cpu.poll.return_value=None
                gpu.wait.side_effect=subprocess.TimeoutExpired('fixture',5) if pending else None
                with patch.object(s,'popen',side_effect=[gpu,cpu]) as spawn:
                    if pending:
                        with self.assertRaises(s.VisionCleanupPending):v._start()
                        self.assertIs(v.proc,gpu);self.assertEqual(spawn.call_count,1)
                        self.assertTrue(v.cleanup_pending)
                    else:
                        v._start();self.assertIs(v.proc,cpu);self.assertEqual(spawn.call_count,2)
                        self.assertEqual(v.capability()['backend'],'cpu')

    def config(self):
        return dict(reader_mode='official-bundle', backend='hip', gpu=True,
                    exe='C:/sidecar/strata-vision-hip.exe', cpu_exe='C:/sidecar/strata-vision.exe',
                    model='C:/model.gguf', mmproj='C:/mmproj.gguf', threads=4, max_tokens=300,
                    temp_dir='C:/private/tmp')

    def test_official_mode_has_cpu_and_gpu_exact_commands_without_private_flags(self):
        cfg=dict(exe='C:/sidecar/strata.exe',args=[],vision=self.config())
        commands=n.expected_child_commands(cfg)
        self.assertEqual(len(commands),3)
        gpu=commands[str(Path(cfg['vision']['exe']).resolve())]
        cpu=commands[str(Path(cfg['vision']['cpu_exe']).resolve())]
        self.assertIn('--gpu',gpu)
        self.assertNotIn('--gpu',cpu)
        self.assertNotIn('--require-hip',gpu)

    def test_official_mode_does_not_apply_private_sdk_contract_or_cap(self):
        cfg=self.config();cfg['max_tokens']=2048
        with tempfile.TemporaryDirectory() as td,patch.object(Vision,'work_dir',return_value=Path(td)):
            cfg['temp_dir']=td
            vision=Vision(cfg,lazy=True)
            self.assertFalse(vision.hip_required)
            self.assertEqual(vision.max_tokens,2048)
            self.assertEqual(vision.capability()['backend'],'hip')
            vision.reader_backend='cpu'
            self.assertEqual(vision.capability()['backend'],'cpu')
        clean=vision_env(dict(vision=cfg),dict(SystemRoot='C:/Windows',HIP_VISIBLE_DEVICES='1',STRATA_HIP_WMMA='1'))
        self.assertEqual(clean['HIP_VISIBLE_DEVICES'],'1')
        self.assertNotIn('STRATA_HIP_WMMA',clean)


class ReleaseAssets(unittest.TestCase):
    def fixture(self):
        from local_runtime import release_revision as r
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        parent_profile=root/'parent.json'
        n.write(parent_profile,dict(exe='old.exe',args=['--max-context','262144'],env={},lib_dirs=[],
                                   vision=dict(backend='hip',gpu=True,exe='old-image.exe',rocm_root='old',hip_device=1,threads=4,max_tokens=300)))
        asset=root/'model';asset.write_bytes(b'fixture model')
        base=dict(profile=str(parent_profile),full_content_verification_at=123,
                  assets={str(asset):dict(metadata=n.metadata(asset),sha256=m.digest(asset))})
        self.enterContext(patch.object(r,'parent',return_value=base))
        self.enterContext(patch.object(r,'bundle',return_value=[]))
        self.enterContext(patch.object(r,'python_paths',return_value=[]))
        self.enterContext(patch.object(r,'dependencies',return_value=[asset]))
        self.enterContext(patch.object(r,'revision',return_value={'commit':'fixed','tree':'tree'}))
        self.enterContext(patch.object(n,'source_files',return_value={'source':'exact'}))
        self.enterContext(patch.object(m,'local_path',side_effect=lambda p:p))
        path=root/'profile.json';n.write(path,r.profile(n,root,base))
        value=dict(profile=str(path),profile_sha256=m.digest(path),sources=n.source_files(),assets=copy.deepcopy(base['assets']),
            full_content_verification_at=123,assets_full_sha_read_this_revision=False,
            release_revision=dict(version=1,parent=dict(path=str(r.PARENT),sha256=r.PARENT_SHA,full_at=123),
                source=r.revision(),bundle=dict(archive_sha256=r.ARCHIVE_SHA,manifest_sha256=r.MANIFEST_SHA,root=str(r.RUNTIME)),
                asset_proof=dict(inherited=[str(asset)],full_hashed=[])))
        return r,value

    def test_finite_receipt_rejects_parent_source_bundle_and_inherited_hash_tamper(self):
        r,value=self.fixture();r.validate(n,value)
        changes=[lambda v:v['release_revision']['parent'].update(sha256='foreign'),
                 lambda v:v['sources'].update(source='foreign'),
                 lambda v:v['release_revision']['source'].update(commit='foreign'),
                 lambda v:v['release_revision']['bundle'].update(archive_sha256='foreign'),
                 lambda v:next(iter(v['assets'].values())).update(sha256='foreign'),
                 lambda v:v.update(assets_full_sha_read_this_revision=True)]
        for change in changes:
            bad=copy.deepcopy(value);change(bad)
            with self.assertRaises(RuntimeError):r.validate(n,bad)

    def test_profile_cannot_import_a_performance_flag_or_change_saved_settings(self):
        r,value=self.fixture();path=Path(value['profile']);cfg=m.read_json(path)
        cfg['env']={'STRATA_HIP_WMMA':'1'};n.write(path,cfg);value['profile_sha256']=m.digest(path)
        with self.assertRaisesRegex(RuntimeError,'profile'):r.validate(n,value)

    def test_metadata_changed_asset_is_rehashed_and_never_claims_inheritance(self):
        from local_runtime import release_revision as r
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'asset';p.write_bytes(b'old');prior={str(p):dict(metadata=n.metadata(p),sha256=m.digest(p))}
            p.write_bytes(b'new content')
            assets,proof=r.prove_assets(n,[p],prior,new_paths=set())
            self.assertEqual(assets[str(p)]['sha256'],m.digest(p))
            self.assertEqual(proof['inherited'],[])
            self.assertEqual(proof['full_hashed'],[str(p)])

    def test_metadata_matching_asset_inherits_only_its_original_hash(self):
        from local_runtime import release_revision as r
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'asset';p.write_bytes(b'old');prior={str(p):dict(metadata=n.metadata(p),sha256=m.digest(p))}
            with patch.object(m,'digest',side_effect=AssertionError('body must not be read')):
                assets,proof=r.prove_assets(n,[p],prior,new_paths=set())
            self.assertEqual(assets,prior)
            self.assertEqual(proof['inherited'],[str(p)])

    def test_source_inventory_excludes_private_runtime_and_includes_release_adapter(self):
        paths=m.source_files()
        self.assertIn(str(m.LOCAL/'release_revision.py'),paths)
        self.assertFalse(any('/runtimes/' in p.replace('\\','/') for p in paths))


if __name__=='__main__':unittest.main()
