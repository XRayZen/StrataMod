"""Normal entry CPU contracts; no server, SDK or network execution."""
import contextlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from local_runtime import normal_runtime as normal,runtime_safety as safety,official_runtime as official


def normal_authorities(case):
    # Small test-owned full-proof/profile metadata; never a production receipt.
    root=Path(case.enterContext(tempfile.TemporaryDirectory()))
    image=root/'image';cal=root/'cal';image.mkdir();cal.mkdir()
    cfg=dict(exe=str(root/'text.exe'),env={},lib_dirs=[str(root)],
             args=['--max-context','262144','--resident-budget-gib','16','--spec','4','--spec-min-p','0.5',
                   '--pool-workers','3','--prompt-cache','0'],log=str(root/'full/engine.log'),
             shared=False,open_browser=False,
             vision=dict(exe=str(root/'image.exe'),max_tokens=300,threads=4,temp_dir=str(root/'full/tmp')))
    accepted=root/'accepted.json';normal.write(accepted,cfg)
    normal.write(image/'manifest.json',dict(config=str(accepted),config_sha256=normal.m.digest(accepted)))
    normal.write(image/'one-post-evidence-handoff.json',dict(image_loader_modules=[{'path':str(normal.image.SDK/'bin/amdhip64_7.dll')}]))
    normal.write(cal/'result.json',dict(status='passed',calibration=dict(settings={'--pool-workers':'3'},env={})))
    assets={}
    for name in ('model.gguf','text.exe','image.exe','unused.dll'):
        path=root/name;path.write_bytes(b'small synthetic asset: '+name.encode('ascii'))
        assets[str(path)]=dict(metadata=normal.metadata(path),sha256=normal.m.digest(path))
    original=root/'full/profile.json';original.parent.mkdir();normal.write(original,cfg)
    sources=normal.source_files()
    paths=('local_runtime/normal_runtime.py','Install-StrataMod.cmd','Install-StrataMod.ps1',
           'local_runtime/runtime_safety.py','serve/server.py','serve/test_hip_multi_images.py',
           'local_runtime/official_runtime.py','local_runtime/checked_job.py','local_runtime/manifest.py',
           'local_runtime/image_phase.py','local_runtime/webui_phase.py','tools/vision/webui_upload.mjs','StrataMod.cmd')
    old_sources=dict(sources)
    for name in paths:old_sources[str(normal.m.ROOT/name)]='0'*64
    value=dict(kind=normal.KIND,profile=str(original),profile_sha256=normal.m.digest(original),
               sources=old_sources,assets=assets,references={},full_content_verification_at=123.0)
    full=root/'full/receipt.json';normal.write(full,value)
    for target,name,value in ((normal,'IMAGE',image),(normal,'CAL',cal),(normal,'REFERENCES',{}),
                              (normal,'FULL_BASE',full),(normal,'FULL_BASE_SHA',normal.m.digest(full))):
        case.enterContext(patch.object(target,name,value))
    case.enterContext(patch.object(normal,'dependencies',return_value=[Path(name) for name in assets]))
    return root


class NormalEntryTests(unittest.TestCase):
    def setUp(self):
        normal_authorities(self)

    def test_python_external_writer_is_disabled(self):
        with patch.object(normal.runner,'shared_operation') as locks:
            with self.assertRaisesRegex(RuntimeError,'native'):normal.install_shim()
            locks.assert_not_called()

    def test_native_parent_guard_is_read_only_and_never_reenters_parent_locks(self):
        with patch.object(normal,'shim_receipt',return_value=({},dict(sources={}))), \
             patch.object(normal.runner,'production_inactive'),patch.object(normal,'check_shim_collision'), \
             patch.object(normal.runner,'shared_operation',side_effect=AssertionError('lock reentry')), \
             patch.object(normal,'publish',side_effect=AssertionError('activation forbidden')), \
             patch.object(normal,'write',side_effect=AssertionError('write forbidden')):
            self.assertEqual(normal.readonly_shim_guard()['status'],'checked')

    def inherited_fixture(self,root):
        base=normal.revision_base()
        value=dict(base,sources=normal.source_files(),source_revision_at=123,
                   full_verification_origin=dict(path=str(normal.FULL_BASE),sha256=normal.FULL_BASE_SHA),
                   assets_full_sha_read_this_revision=False,normal_profile_revision=dict(
                       prompt_cache='official-default-6',original_profile=base['profile'],
                       original_profile_sha256=base['profile_sha256'],private_log_temp_paths=True))
        path=root/'installations/revision/receipt.json';path.parent.mkdir(parents=True)
        cfg=normal.profile(path.parent);profile_path=path.parent/'profile.json';normal.write(profile_path,cfg)
        value.update(profile=str(profile_path),profile_sha256=normal.m.digest(profile_path))
        normal.write(path,value)
        pointer=root/'installed.json';normal.write(pointer,dict(receipt=str(path),sha256=normal.m.digest(path)))
        self.enterContext(patch.object(normal,'HOME',root))
        self.enterContext(patch.object(normal,'SELECTION',pointer))
        self.enterContext(patch.object(normal.m,'local_path',side_effect=Path))
        return value,path,pointer

    def test_source_only_revision_preserves_original_full_origin_and_rejects_changed_map_or_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            value,path,pointer=self.inherited_fixture(Path(tmp))
            normal.check_inheritance(value)
            base=normal.revision_base()
            self.assertEqual(value['full_content_verification_at'],base['full_content_verification_at'])
            self.assertEqual(value['assets'],base['assets'])
            for key,bad in (('assets',{}),('profile_sha256','changed'),('full_content_verification_at',0),
                            ('assets_full_sha_read_this_revision',True),('sources',dict(value['sources'],foreign='changed'))):
                with self.subTest(key=key),self.assertRaises(RuntimeError):normal.check_inheritance(dict(value,**{key:bad}))

    def test_allowed_source_hash_tamper_missing_and_extra_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            value,receipt,_=self.inherited_fixture(Path(tmp))
            normal.read_receipt(receipt)
            path=str(normal.m.ROOT/'local_runtime/manifest.py')
            for sources in (dict(value['sources'],**{path:'f'*64}),
                            {key:sha for key,sha in value['sources'].items() if key!=path},
                            dict(value['sources'],foreign='f'*64)):
                with self.subTest(kind='declared map'),self.assertRaises(RuntimeError):
                    normal.write(receipt,dict(value,sources=sources))
                    normal.read_receipt(receipt)
            # Simulate a physical source read at the I/O boundary after receipt creation.
            body=Path(tmp)/'source-bytes';body.write_bytes(b'approved synthetic source')
            source_map=dict(value['sources']);source_map[path]=normal.m.digest(body)
            approved=dict(value,sources=source_map)
            with patch.object(normal,'source_files',side_effect=lambda:dict(source_map,**{path:normal.m.digest(body)})):
                normal.write(receipt,approved)
                normal.read_receipt(receipt)
                body.write_bytes(b'unapproved source replacement')
                with self.assertRaises(RuntimeError):normal.read_receipt(receipt)

    def test_revision_creation_inherits_model_hashes_without_rereading_model_or_dll_bodies(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(normal,'HOME',Path(tmp)), \
             patch.object(normal.runner,'shared_operation'),patch.object(normal.runner,'production_inactive'), \
             patch.object(normal.m,'local_path',side_effect=Path):
            original_digest=normal.m.digest;calls=[]
            def digest(p):
                self.assertNotIn(Path(p).suffix.lower(),('.gguf','.bin','.kpack','.dll','.exe'))
                calls.append(str(p));return original_digest(p)
            with patch.object(normal.m,'digest',side_effect=digest):result=normal.revise_install()
            value=normal.m.read_json(result['receipt']);base=normal.revision_base()
            self.assertEqual(value['assets'],base['assets']);self.assertEqual(result['new_full_asset_passes'],0)
            self.assertEqual(value['full_content_verification_at'],base['full_content_verification_at'])
            self.assertNotEqual(value['profile'],base['profile']);self.assertTrue(calls)
            cfg=normal.m.read_json(value['profile'])
            self.assertEqual(cfg['args'][cfg['args'].index('--prompt-cache')+1],'6')
            self.assertEqual(value['normal_profile_revision']['original_profile_sha256'],base['profile_sha256'])

    def test_revised_profile_accepts_only_cache_default_and_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            value,path,pointer=self.inherited_fixture(Path(tmp))
            cfg=normal.m.read_json(value['profile'])
            for field in ('cache','context','vision','env','log'):
                changed=json.loads(json.dumps(cfg))
                if field in ('cache','context'):
                    flag='--prompt-cache' if field=='cache' else '--max-context'
                    changed['args'][changed['args'].index(flag)+1]='0' if field=='cache' else '4096'
                elif field=='vision':changed['vision']['threads']=1
                elif field=='env':changed['env']=dict(changed.get('env',{}),UNAPPROVED='value')
                else:changed['log']='foreign.log'
                normal.write(value['profile'],changed)
                candidate=dict(value,profile_sha256=normal.m.digest(value['profile']))
                with self.subTest(field=field),self.assertRaises(RuntimeError):normal.check_inheritance(candidate)
            normal.write(value['profile'],cfg)


    def test_real_helper_checks_all_asset_metadata_but_reads_no_asset_body_or_writes_in_check_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value,path,pointer=self.inherited_fixture(root)
            original_digest=normal.m.digest;digests=[];assets={Path(p).resolve() for p in value['assets']}
            def digest(p):
                self.assertNotIn(Path(p).resolve(),assets,'manual helper read an asset body')
                digests.append(str(p));return original_digest(p)
            before={p:p.read_bytes() for p in (path,pointer)}
            with patch.object(normal.m,'digest',side_effect=digest), \
                 patch.object(normal.runner,'shared_operation'),patch.object(normal.runner,'production_inactive'), \
                 patch.object(normal,'check_shim_collision'), \
                 patch.object(normal,'read_receipt',side_effect=AssertionError('asset path forbidden')), \
                 patch.object(normal,'profile',side_effect=AssertionError('asset path forbidden')), \
                 patch.object(normal,'references',side_effect=AssertionError('asset path forbidden')), \
                 patch.object(normal,'publish',side_effect=AssertionError('activation forbidden')), \
                 patch.object(normal,'write',side_effect=AssertionError('write forbidden')):
                result=normal.install_shim(check=True)
                self.assertEqual(result['status'],'checked');self.assertTrue(digests)
            self.assertEqual(before,{p:p.read_bytes() for p in before})
            asset=next(iter(value['assets']));bad=normal.m.read_json(path)
            bad['assets'][asset]['metadata']['size']+=1;normal.write(path,bad)
            normal.write(pointer,dict(receipt=str(path),sha256=original_digest(path)))
            with self.assertRaises(RuntimeError):normal.shim_receipt()


    def test_unused_image_miopen_is_metadata_only_but_used_critical_dlls_remain_hashed(self):
        cfg=dict(exe='C:/text.exe',lib_dirs=['C:/text-sdk'],vision={'exe':'C:/image.exe'})
        self.assertFalse(normal.critical(normal.image.SDK/'bin/MIOpen.dll',cfg))
        self.assertTrue(normal.critical(Path('C:/text-sdk/amdhip64_7.dll'),cfg))
        self.assertTrue(normal.critical(normal.image.SDK/'bin/amdhip64_7.dll',cfg))

    def test_manual_helper_never_calls_asset_hashing_or_activation(self):
        with patch.object(normal,'shim_receipt',return_value=({},dict(sources={}))), \
             patch.object(normal.runner,'shared_operation'),patch.object(normal.runner,'production_inactive'), \
             patch.object(normal,'check_shim_collision'),patch.object(normal,'publish',side_effect=AssertionError('activation forbidden')), \
             patch.object(normal,'validate_assets',side_effect=AssertionError('asset validator forbidden')), \
             patch.object(normal,'write',side_effect=AssertionError('write forbidden')):
            self.assertEqual(normal.install_shim(check=True)['status'],'checked')

    def test_source_inventory_binds_executed_calibration_helper(self):
        path=normal.m.ROOT/'tools/calibrate.py'
        sources=normal.source_files()
        self.assertEqual(sources[str(path)],normal.m.digest(path))
        with patch.object(normal.m,'digest',side_effect=lambda p:'same-size-changed' if Path(p)==path else sources[str(p)]):
            self.assertNotEqual(normal.source_files(),sources)
            with patch.object(normal.m,'local_path',side_effect=Path), \
                 patch.object(normal.m,'read_json',return_value=dict(kind=normal.KIND,sources=sources)), \
                 patch.object(official.native(),'spawn_detached') as spawn:
                with self.assertRaisesRegex(RuntimeError,'source changed'):normal.read_receipt('receipt')
                spawn.assert_not_called()

    def test_initial_mutable_copy_changes_are_refused_before_popen(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(normal.m,'local_path',side_effect=Path):
            state,value,cfg=self.authority(Path(tmp))
            for key,changed in (('args',['--foreign']),('env',{'FOREIGN':'1'}),('vision',{'exe':'foreign'})):
                with self.subTest(key=key):
                    normal.write(state['config'],dict(cfg,**{key:changed}))
                    with patch.object(official.native(),'spawn_detached') as spawn:
                        with self.assertRaisesRegex(RuntimeError,'startup copy'):normal.require_startup_copy(state)
                        spawn.assert_not_called()
            normal.write(state['config'],cfg);normal.require_startup_copy(state)

    def test_mutated_initial_copy_is_rejected_by_actual_launcher_before_popen(self):
        for key,changed in (('args',['--foreign']),('env',{'FOREIGN':'1'}),('vision',{'exe':'foreign'})):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(normal.m,'local_path',side_effect=Path))
                state,value,cfg=self.authority(Path(tmp));directory=Path(state['config']).parent
                tools=Mock();strata=Mock()
                def request_start(**kwargs):
                    normal.write(state['config'],dict(cfg,**{key:changed}))
                    return kwargs['launcher'](value['command'],normal.m.ROOT,directory/'native/server.log',{})
                tools.strata_start.side_effect=request_start
                for target,name,options in (
                    (normal,'new_run',dict(return_value=(directory,state,cfg))),
                    (normal,'manager',dict(return_value=(strata,tools))),
                    (normal,'read_receipt',dict()),(normal,'validate_assets',dict()),
                    (official,'clean_environment',dict(return_value={})),
                    (normal.checked_job,'ensure_parent_job',dict()),
                    (normal.runner,'preflight_budget',dict()),(safety,'save',dict())):
                    stack.enter_context(patch.object(target,name,**options))
                retained={}
                with patch.object(official.native(),'spawn_detached') as spawn:
                    with self.assertRaisesRegex(RuntimeError,'startup copy'):normal.start({'receipt':'receipt'},{},Mock(),retained)
                    spawn.assert_not_called();self.assertFalse(retained.get('spawn_possible',False))

    def test_observed_child_argv_is_not_promoted_to_authority(self):
        cfg=dict(exe='C:/fixed-text.exe',args=['--max-context','262144'],vision=dict(
            exe='C:/fixed-image.exe',mmproj='C:/mmproj',model='C:/native',backend='hip',gpu=True,threads=4,max_tokens=300))
        expected=normal.expected_child_commands(cfg)
        for exe,command in expected.items():
            normal.require_child_command(cfg,exe,command)
            with self.assertRaisesRegex(RuntimeError,'argv'):normal.require_child_command(cfg,exe,[*command,'--foreign'])

    def test_expected_encoder_argv_matches_existing_lazy_vision_builder_without_spawn(self):
        from serve.server import Vision
        with tempfile.TemporaryDirectory() as tmp:
            cfg=dict(exe=str(Path(tmp)/'text.exe'),args=[],vision=dict(
                exe=str(Path(tmp)/'image.exe'),mmproj=str(Path(tmp)/'mmproj'),model=str(Path(tmp)/'native'),
                backend='hip',gpu=True,threads=4,max_tokens=300,temp_dir=tmp))
            with patch('serve.server.popen') as spawn:
                vision=Vision(cfg['vision'],env={},lazy=True)
                self.assertEqual(normal.expected_child_commands(cfg)[str(Path(cfg['vision']['exe']).resolve())],vision.spawn[0])
                spawn.assert_not_called()

    def test_fresh_status_does_not_use_parent_job_or_write(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(normal.m,'local_path',side_effect=Path))
            state,value,cfg=self.authority(Path(tmp));state['job_at_launch']={'parent_member':True}
            proc=Mock(pid=7);proc.cmdline.return_value=value['command']
            strata=Mock();strata.state.return_value=state['official_tracking']
            module=Mock();module.proc_alive.return_value=True
            for target,name,options in (
                (safety,'read_state',dict(return_value=state)),(safety,'runtime_active',dict(return_value=True)),
                (safety,'owned',dict(return_value=proc)),(normal,'manager',dict(return_value=(strata,Mock()))),
                (official,'native',dict(return_value=module)),(safety,'require_owned_listener',dict(return_value=True)),
                (safety,'get_json',dict(return_value=dict(service='strata',model=normal.m.MODEL,max_context=262144))),
                (normal.checked_job,'_parent_job',dict(new=None))):stack.enter_context(patch.object(target,name,**options))
            before=Path(state['authority']).read_bytes()
            with patch.object(normal.checked_job,'membership_pid',side_effect=RuntimeError('No checked parent Job')) as member, \
                 patch.object(normal.checked_job,'ensure_parent_job') as newjob,patch.object(safety,'save') as save, \
                 patch.object(safety,'stop_owned') as stop:
                result=normal.status()
                self.assertTrue(result['running']);self.assertFalse(result['job_current_verified'])
                self.assertEqual(result['job_at_launch'],state['job_at_launch'])
                member.assert_not_called();newjob.assert_not_called();save.assert_not_called();stop.assert_not_called()
            self.assertEqual(Path(state['authority']).read_bytes(),before)

    def test_metadata_change_refuses_without_accepting_new_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'model.gguf';p.write_bytes(b'initial')
            before=normal.metadata(p);p.write_bytes(b'changed-length')
            with self.assertRaisesRegex(RuntimeError,'metadata'):normal.check_metadata(p,before)

    def test_large_files_are_metadata_only_and_native_executables_are_critical(self):
        cfg={'exe':'C:/text.exe','lib_dirs':['C:/bin'],'vision':{'exe':'C:/vision.exe'}}
        self.assertTrue(normal.critical(Path('C:/text.exe'),cfg))
        self.assertTrue(normal.critical(Path('C:/bin/amdhip64_7.dll'),cfg))
        for p in ('C:/model.gguf','C:/pack/dense.bin','C:/a.kpack'):
            self.assertFalse(normal.critical(Path(p),cfg))

    def test_daily_large_metadata_mode_and_explicit_full_verify_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.gguf';path.write_bytes(b'original')
            value=dict(profile='profile',assets={str(path):dict(metadata=normal.metadata(path),sha256='original')})
            with patch.object(normal.m,'read_json',return_value=dict(exe='text',vision={'exe':'image'})), \
                 patch.object(normal,'critical_dlls',return_value=set()), \
                 patch.object(normal.m,'digest',return_value='changed') as digest:
                normal.validate_assets(value);digest.assert_not_called()
                with self.assertRaisesRegex(RuntimeError,'contents changed'):normal.validate_assets(value,full=True)
                digest.assert_called_once_with(str(path))

    def test_next_run_recreates_mutable_copy_from_immutable_installed_profile(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(normal,'RUNS',Path(tmp)/'runs'):
            root=Path(tmp);original=root/'profile.json'
            normal.write(original,dict(log='unused',vision={'temp_dir':'unused'},temperature=0.2))
            before=original.read_bytes();pointer=dict(receipt='receipt',sha256='fixed')
            first,state,_=normal.new_run(pointer,dict(profile=str(original),verification_mode='installed-receipt-plus-metadata'))
            normal.write(state['config'],{'temperature':0.9,'exe':'foreign'})
            second,following,cfg=normal.new_run(pointer,dict(profile=str(original),verification_mode='installed-receipt-plus-metadata'))
            self.assertNotEqual(first,second);self.assertEqual(cfg['temperature'],0.2)
            self.assertEqual(normal.m.read_json(following['config'])['temperature'],0.2)
            self.assertEqual(original.read_bytes(),before)

    def authority(self,folder):
        self.enterContext(patch.object(normal,'HOME',folder))
        self.enterContext(patch.object(normal,'RUNS',folder/'runs'))
        directory=folder/'runs/1';directory.mkdir(parents=True)
        snapshot=directory/'startup.json';mutable=directory/'strata-StrataMod.json'
        cfg={'exe':'fixed-text','vision':{'exe':'fixed-image'},'temperature':0}
        normal.write(snapshot,cfg);normal.write(mutable,cfg)
        receipt=folder/'installations/1/receipt.json';receipt.parent.mkdir(parents=True)
        normal.write(receipt,{'kind':normal.KIND})
        value=dict(kind=normal.KIND,receipt=str(receipt),receipt_sha256=normal.m.digest(receipt),
                   snapshot=str(snapshot),snapshot_sha256=normal.m.digest(snapshot),config=str(mutable),
                   command=['python','server','--config',str(mutable)],environment={})
        path=directory/'authority.json';normal.write(path,value)
        state=dict(kind=normal.KIND,authority=str(path),authority_sha256=normal.m.digest(path),
                   config=str(mutable),pid=7,created=1,model=normal.m.MODEL,context=262144,
                   official_tracking={'pid':7,'ident':'birth','port':18080,'config':mutable.name})
        return state,value,cfg

    def test_mutable_apply_corrupt_or_missing_does_not_change_stop_child_authority(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(normal.m,'local_path',side_effect=Path):
            state,value,cfg=self.authority(Path(tmp))
            before=Path(value['snapshot']).read_bytes();receipt=Path(value['receipt']).read_bytes()
            for content in ('{"temperature":0.7,"exe":"foreign"}','broken-json',None):
                mutable=Path(state['config'])
                if content is None:mutable.unlink()
                else:mutable.write_text(content,encoding='utf-8')
                self.assertEqual(normal.authority(state)['snapshot_config'],cfg)
                with patch.object(safety,'read_state',return_value=state):
                    self.assertEqual(safety.family_config(state['config']),cfg)
            self.assertEqual(Path(value['snapshot']).read_bytes(),before)
            self.assertEqual(Path(value['receipt']).read_bytes(),receipt)

    def test_immutable_snapshot_receipt_authority_tamper_refuses(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(normal.m,'local_path',side_effect=Path):
            state,value,cfg=self.authority(Path(tmp))
            for target in (Path(value['snapshot']),Path(value['receipt']),Path(state['authority'])):
                original=target.read_bytes();target.write_bytes(b'{}')
                with self.assertRaises(RuntimeError):normal.authority(state)
                target.write_bytes(original)

    def test_benchmark_tracking_keeps_its_config_sha_gate(self):
        with patch.object(official.manifest,'digest',return_value='changed'):
            with self.assertRaisesRegex(RuntimeError,'manifest changed'):
                official.require_tracking(dict(manifest='old',manifest_sha256='expected'))

    def test_install_verify_and_publish_refuse_active_before_mutation(self):
        for full in (False,True):
            with patch.object(normal.runner,'shared_operation'), \
                 patch.object(normal.runner,'production_inactive',side_effect=RuntimeError('busy')), \
                 patch.object(normal,'selected') as select:
                with self.assertRaisesRegex(RuntimeError,'busy'):normal.verify(full=full)
                select.assert_not_called()

    def test_normal_tracking_checks_immutable_authority_and_original_birth_argv(self):
        state=dict(kind=normal.KIND,config='mutable',official_tracking=dict(pid=7,ident='birth',port=18080),
                   pid=7,created=1,model=normal.m.MODEL,context=262144)
        process=Mock();process.cmdline.return_value=['foreign']
        with patch.object(normal,'authority',return_value={'command':['exact']}), \
             patch.object(safety,'owned',return_value=process),patch.object(normal,'manager') as manager:
            with self.assertRaises(RuntimeError):normal.require_tracking(state)
            manager.assert_not_called()

    def test_ui_apply_or_missing_copy_still_uses_guarded_unload_and_saved_tracking(self):
        for changed in ('{"temperature":0.7,"exe":"foreign"}',None):
            with self.subTest(copy=changed),tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(normal.m,'local_path',side_effect=Path))
                state,value,cfg=self.authority(Path(tmp));original=Path(value['snapshot']).read_bytes()
                if changed is None:Path(state['config']).unlink()
                else:Path(state['config']).write_text(changed,encoding='utf-8')
                proc=Mock(pid=7);proc.cmdline.return_value=value['command']
                strata=Mock();strata.state.return_value=state['official_tracking']
                module=Mock();module.proc_alive.return_value=True
                module.http_json.side_effect=[(200,dict(busy=False,queued=0)),(200,dict(status='unloaded'))]
                def stop(**kwargs):
                    kwargs['request']('http://127.0.0.1:18080/status')
                    kwargs['request']('http://127.0.0.1:18080/unload','POST')
                    kwargs['terminate'](7,'birth')
                    return dict(ended_cleanly=True,engine_unloaded='unloaded')
                tools=Mock();tools.strata_stop.side_effect=stop
                for target,name,options in (
                    (normal,'manager',dict(return_value=(strata,tools))),
                    (normal.checked_job,'membership_pid',dict(return_value=True)),
                    (safety,'owned',dict(return_value=proc)),(safety,'require_owned_listener',dict(return_value=True)),
                    (safety,'get_json',dict(return_value=dict(service='strata',model=normal.m.MODEL,max_context=262144))),
                    (official,'native',dict(return_value=module))):stack.enter_context(patch.object(target,name,**options))
                result=official.stop(state)
                self.assertTrue(result['ended_cleanly']);module.proc_terminate.assert_called_once_with(7,'birth')
                self.assertEqual(Path(value['snapshot']).read_bytes(),original)

    def test_foreign_listener_or_job_or_tracking_never_sends_unload_or_terminate(self):
        for changed in ('listener','job','tracking','argv','birth'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(normal.m,'local_path',side_effect=Path))
                state,value,cfg=self.authority(Path(tmp));proc=Mock(pid=7)
                proc.cmdline.return_value=['foreign'] if changed=='argv' else value['command']
                strata=Mock();strata.state.return_value={} if changed=='tracking' else state['official_tracking']
                module=Mock();module.proc_alive.return_value=True
                for target,name,options in (
                    (normal,'manager',dict(return_value=(strata,Mock()))),
                    (normal.checked_job,'membership_pid',dict(return_value=changed!='job')),
                    (safety,'owned',dict(side_effect=RuntimeError('birth changed') if changed=='birth' else None,return_value=proc)),
                    (safety,'require_owned_listener',dict(side_effect=RuntimeError('foreign listener') if changed=='listener' else None)),
                    (safety,'get_json',dict(return_value=dict(service='strata',model=normal.m.MODEL,max_context=262144))),
                    (official,'native',dict(return_value=module))):stack.enter_context(patch.object(target,name,**options))
                with self.assertRaises(RuntimeError):official.stop(state)
                module.http_json.assert_not_called();module.proc_terminate.assert_not_called()

    def test_ctrlc_clean_stop_and_secondary_cleanup_failure_hold_locks_and_original_error(self):
        for failure in (False,True):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
                directory=Path(tmp);held=[False];calls=[]
                @contextlib.contextmanager
                def locks():
                    held[0]=True
                    try:yield
                    finally:held[0]=False
                state=dict(config=str(directory/'strata-StrataMod.json'),cleanup_pending=True,phase='ready')
                process=Mock()
                def start(pointer,value,monitor,retained):
                    retained.update(state=state,process=process,spawn_possible=True);return directory,state
                def barrier(retained,result,path):
                    self.assertTrue(held[0]);self.assertIs(retained['process'],process);calls.append('barrier')
                monitor=Mock();monitor.check.side_effect=RuntimeError('original collector failure') if failure else KeyboardInterrupt()
                cm=Mock();cm.__enter__=Mock(return_value=monitor);cm.__exit__=Mock(return_value=False)
                for target,name,options in (
                    (normal,'selected',dict(return_value=({},{}))),(normal,'validate_assets',dict()),
                    (normal.runner,'shared_operation',dict(side_effect=locks)),(normal.runner,'production_inactive',dict()),
                    (normal,'NormalMonitor',dict(return_value=cm)),(normal,'start',dict(side_effect=start)),
                    (normal.runner,'wait_request_release',dict()),
                    (safety,'save',dict(side_effect=OSError('secondary save failure') if failure else None)),
                    (safety,'stop_owned',dict()),(normal.runner,'pending_exit_proof',dict(return_value=dict(complete=True,port_free=True))),
                    (normal.runner,'hold_pending_cleanup',dict(side_effect=barrier))):stack.enter_context(patch.object(target,name,**options))
                if failure:
                    with self.assertRaisesRegex(RuntimeError,'original collector'):normal.serve()
                    self.assertEqual(calls,['barrier'])
                else:
                    normal.serve();self.assertEqual(state['phase'],'stopped');self.assertFalse(state['cleanup_pending'])
                result=json.loads((directory/'result.json').read_text(encoding='utf-8'))
                self.assertEqual(result['generation_requests'],0)
                self.assertFalse(held[0])

    def test_pre_ready_failures_reach_existing_cleanup_and_barrier_under_locks(self):
        state_error=PermissionError(13,'state replace denied');state_error.winerror=5
        for original in (KeyboardInterrupt(),TimeoutError('startup deadline'),RuntimeError('collector'),
                         RuntimeError('observer begin'),RuntimeError('Job child membership'),state_error):
            for save_failure in (False,True):
                with self.subTest(error=type(original).__name__,save_failure=save_failure), \
                     tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
                    held=[False];directory=Path(tmp);proc=Mock();proc.poll.return_value=None
                    state=dict(config=str(directory/'strata-StrataMod.json'),phase='spawning',cleanup_pending=True)
                    observer=Mock();observer.finish.return_value=dict(created=1,identities=[dict(pid=7)],unknown=[],errors=[])
                    @contextlib.contextmanager
                    def locks():
                        held[0]=True
                        try:yield
                        finally:held[0]=False
                    def start(pointer,value,monitor,retained):
                        retained.update(state=state,process=proc,observer=observer,spawn_possible=True)
                        raise original
                    def barrier(retained,result,path):
                        self.assertTrue(held[0]);self.assertIs(retained['process'],proc)
                        self.assertIs(retained['observer'],observer)
                    cm=Mock();cm.__enter__=Mock(return_value=Mock());cm.__exit__=Mock(return_value=False)
                    for target,name,options in (
                        (normal,'selected',dict(return_value=({},{}))),(normal,'validate_assets',dict()),
                        (normal.runner,'shared_operation',dict(side_effect=locks)),(normal.runner,'production_inactive',dict()),
                        (normal,'NormalMonitor',dict(return_value=cm)),(normal,'start',dict(side_effect=start)),
                        (safety,'save',dict(side_effect=OSError('disk full') if save_failure else None)),
                        (safety,'stop_owned',dict()),(safety,'check_port_available',dict()),
                        (normal.runner,'pending_exit_proof',dict(return_value=dict(complete=False))),
                        (normal.runner,'hold_pending_cleanup',dict(side_effect=barrier))):stack.enter_context(patch.object(target,name,**options))
                    with patch.object(normal.runner,'cleanup_failed_start',wraps=normal.runner.cleanup_failed_start) as cleanup, \
                         patch.object(normal.runner,'wait_request_release') as release:
                        with self.assertRaises(type(original)):normal.serve()
                        cleanup.assert_called_once_with(proc,observer,state);release.assert_not_called()
                    if save_failure:proc.terminate.assert_called_once();proc.wait.assert_called_once()
                    else:safety.stop_owned.assert_called_once_with(state,official_first=False)
                    self.assertFalse(held[0])


if __name__=='__main__':unittest.main()
