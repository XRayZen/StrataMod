"""Clean saved-adoption contracts; synthetic assets and no native runtime."""
import contextlib,copy,errno,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from local_runtime import normal_runtime as n,manifest as m,normal_performance_revision as p


class CleanAdoption(unittest.TestCase):
    def fixture(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()));home=root/'normal';home.mkdir()
        data=root/'data';data.mkdir();model=data/'model';model.write_bytes(b'anchored model')
        runtime=root/'runtime';runtime.mkdir();binary=runtime/'strata.exe';binary.write_bytes(b'signed binary')
        component=runtime/'engine-component.json'
        n.write(component,dict(schema_version=2,id='strata-engine',version='0.1.45.3',
            platform='windows-x86_64',backend='hip',entrypoint='strata.exe',build_id='synthetic-fixture',
            archs=['gfx1201'],files=[dict(path='strata.exe',sha256=m.digest(binary),bytes=binary.stat().st_size)]))
        python=root/'python.exe';python.write_bytes(b'python closure')
        full_profile=root/'full-profile.json'
        n.write(full_profile,dict(exe='old.exe',env={},args=['--expert-profile',str(model),'--prompt-cache','6','--max-context','262144'],
            lib_dirs=[],log='old.log',max_tokens=900,vision=dict(backend='hip',gpu=True,exe='old-image.exe',rocm_root='old',hip_device=1,threads=4,max_tokens=300)))
        row=lambda path:dict(sha256=m.digest(path),metadata=n.metadata(path))
        full=dict(profile=str(full_profile),assets={str(model):row(model)},full_content_verification_at=123)
        full_ref=root/'full-receipt.json';n.write(full_ref,full)
        for obj,key,value in ((m,'ROOT',root),(m,'DATA',data),(m,'PYTHON',python),(n,'HOME',home),(n,'SELECTION',home/'installed.json'),
                (p.release,'RUNTIME',runtime),(p.release,'PARENT',full_ref),(p.release,'PARENT_SHA',m.digest(full_ref)),
                (p.release,'MANIFEST_SHA',m.digest(component))):
            self.enterContext(patch.object(obj,key,value))
        self.enterContext(patch.object(p.release,'parent',return_value=full))
        self.enterContext(patch.object(p.release,'bundle',return_value=[binary,component]))
        self.enterContext(patch.object(p.release,'python_paths',return_value=[python]))
        from strata_control import engine_component as ec
        self.enterContext(patch.object(ec,'MANIFEST',component.name))
        def local(path):
            path=Path(path)
            if not path.is_absolute() or not path.is_relative_to(root) or '..' in path.parts:raise RuntimeError('fixture path escape')
            return path
        self.enterContext(patch.object(m,'local_path',side_effect=local))
        sources={str(root/'source.py'):'current'}
        self.enterContext(patch.object(n,'source_files',return_value=sources))
        self.enterContext(patch.object(p,'revision',return_value=dict(baseline=p.BASELINE,commit='a'*40,tree='b'*40)))
        directory=home/'installations/release';directory.mkdir(parents=True)
        profile=directory/'profile.json';n.write(profile,p.release.profile(n,directory,full))
        assets={str(path):row(path) for path in (model,binary,component,python)}
        base=dict(kind=n.KIND,profile=str(profile),profile_sha256=m.digest(profile),sources={'old':'source'},
            assets=assets,full_content_verification_at=123,assets_full_sha_read_this_revision=False,
            release_revision=dict(version=1,parent=dict(path=str(full_ref),sha256=p.release.PARENT_SHA,full_at=123),
                source={'declared':'old immutable source'},bundle=dict(archive_sha256=p.release.ARCHIVE_SHA,
                    manifest_sha256=p.release.MANIFEST_SHA,root=str(runtime)),
                asset_proof=dict(inherited=[str(model)],full_hashed=[str(binary),str(component),str(python)])))
        parent_path=directory/'receipt.json';n.write(parent_path,base)
        parent_ref=dict(path=str(parent_path),sha256=m.digest(parent_path))
        prior_dir=home/'installations/prior';prior_dir.mkdir();prior_profile=prior_dir/'profile.json';n.write(prior_profile,p.profile(base))
        old=copy.deepcopy(base);old.pop('release_revision')
        old.update(profile=str(prior_profile),profile_sha256=m.digest(prior_profile),sources={'old raw':'proof'},
            normal_performance_adoption=dict(version=1,flags=dict(p.FLAGS),
                parent=dict(path=str(parent_path),sha256=parent_ref['sha256'],profile_sha256=base['profile_sha256'])))
        old_path=prior_dir/'receipt.json';n.write(old_path,old)
        old_ref=dict(path=str(old_path),sha256=m.digest(old_path));n.write(n.SELECTION,dict(receipt=str(old_path),sha256=old_ref['sha256']))
        descriptor=dict(release_parent=parent_ref,prior_installation=old_ref,
                        selection_before=dict(path=str(n.SELECTION),sha256=m.digest(n.SELECTION)))
        new_dir=home/'installations/new';new_dir.mkdir();new_profile=new_dir/'profile.json';n.write(new_profile,p.profile(base))
        value=copy.deepcopy(base);value.pop('release_revision')
        value.update(profile=str(new_profile),profile_sha256=m.digest(new_profile),sources=sources,
                     normal_performance_adoption=dict(version=2,flags=dict(p.FLAGS),source=p.revision(),**copy.deepcopy(descriptor)))
        return root,base,value,descriptor

    def test_real_manifest_tuple_keeps_digest_and_byte_count_in_the_official_order(self):
        root,base,value,desc=self.fixture()
        from strata_control import engine_component as ec
        row=ec.read_manifest(root/'runtime').files[0]
        self.assertEqual(row,('strata.exe',m.digest(root/'runtime/strata.exe'),len(b'signed binary')))
        self.assertIsInstance(row[1],str);self.assertIs(type(row[2]),int)
        self.assertEqual(p.parent(n,desc['release_parent']),base)

    def test_clean_v2_dispatch_does_not_apply_legacy_current_source_validator(self):
        root,base,value,desc=self.fixture();path=Path(value['profile']).parent/'receipt.json';n.write(path,value)
        with patch.object(p.release,'validate',side_effect=AssertionError('old validator must remain separate')),\
             patch.object(n,'references',side_effect=AssertionError('new v2 reached old legacy route')):
            self.assertEqual(n.read_receipt(path),value)

    def test_exact_parent_and_profile_preserve_saved_values_and_post_activation_validation(self):
        root,base,value,desc=self.fixture();p.validate(n,value)
        cfg=m.read_json(value['profile']);old=m.read_json(base['profile'])
        self.assertEqual(cfg,dict(old,env=p.FLAGS));p.activation_precondition(n,value)
        n.write(n.SELECTION,dict(receipt='new'))
        p.validate(n,value)
        with self.assertRaisesRegex(RuntimeError,'Selection'):p.activation_precondition(n,value)

    def test_self_hashed_fake_parent_cannot_replace_anchored_model_full_at_or_partition(self):
        root,base,value,desc=self.fixture();path=Path(desc['release_parent']['path'])
        original=path.read_bytes();model=str(root/'data/model');python=str(root/'python.exe')
        changes=[lambda b:b['assets'][model].update(sha256='0'*64),
                 lambda b:b['assets'][model]['metadata'].update(size=999),
                 lambda b:b.update(full_content_verification_at=456),
                 lambda b:b['release_revision']['asset_proof']['inherited'].append(python),
                 lambda b:b['release_revision']['asset_proof']['full_hashed'].remove(python),
                 lambda b:b['release_revision'].update(version=2),
                 lambda b:b['assets'].update(unrelated=dict(sha256='0'*64,metadata={})),
                 lambda b:b['release_revision']['bundle'].update(manifest_sha256='0'*64)]
        for change in changes:
            bad=copy.deepcopy(base);change(bad);n.write(path,bad)
            ref=dict(path=str(path),sha256=m.digest(path))
            with self.subTest(change=change),self.assertRaises(RuntimeError):p.parent(n,ref)
        path.write_bytes(original)

    def test_self_hashed_signed_bundle_row_tamper_and_unverified_signature_rejected(self):
        root,base,value,desc=self.fixture();path=Path(desc['release_parent']['path'])
        base['assets'][str(root/'runtime/strata.exe')]['sha256']='0'*64;n.write(path,base)
        with self.assertRaisesRegex(RuntimeError,'signed component'):p.parent(n,dict(path=str(path),sha256=m.digest(path)))
        with patch.object(p.release,'bundle',side_effect=RuntimeError('signature unverified')):
            with self.assertRaisesRegex(RuntimeError,'signature'):p.parent(n,dict(path=str(path),sha256=m.digest(path)))

    def test_other_root_receipt_and_profile_substitution_rejected(self):
        root,base,value,desc=self.fixture()
        foreign=root/'foreign/receipt.json';foreign.parent.mkdir();n.write(foreign,base)
        with self.assertRaisesRegex(RuntimeError,'installation root'):p.receipt(n,dict(path=str(foreign),sha256=m.digest(foreign)))
        path=Path(desc['release_parent']['path']);base['profile']=str(root/'full-profile.json');base['profile_sha256']=m.digest(base['profile']);n.write(path,base)
        with self.assertRaisesRegex(RuntimeError,'exact installation'):p.parent(n,dict(path=str(path),sha256=m.digest(path)))

    def test_profile_source_receipt_and_extra_flags_refused(self):
        root,base,value,desc=self.fixture();cfg=m.read_json(value['profile'])
        changes=[lambda c:c['env'].update(STRATA_PREFILL_TIMING='0'),lambda c:c['env'].update(AMD_LOG_LEVEL='5'),
            lambda c:c['env'].pop('STRATA_HIP_WMMA'),lambda c:c['args'].__setitem__(3,'0'),
            lambda c:c.update(max_tokens=128),lambda c:c.update(log='other')]
        for change in changes:
            bad=copy.deepcopy(cfg);change(bad);n.write(value['profile'],bad);value['profile_sha256']=m.digest(value['profile'])
            with self.assertRaises(RuntimeError):p.validate(n,value)
        n.write(value['profile'],cfg);value['profile_sha256']=m.digest(value['profile'])
        for change in (lambda v:v.update(release_revision={}),lambda v:v['sources'].update(extra='x'),
                       lambda v:v['normal_performance_adoption']['source'].update(tree='wrong'),
                       lambda v:v['normal_performance_adoption'].update(version=1)):
            bad=copy.deepcopy(value);change(bad)
            with self.assertRaises(RuntimeError):p.validate(n,bad)

    def test_prepare_checks_new_python_hash_before_any_new_profile_or_pointer_write(self):
        root,base,value,desc=self.fixture();path=Path(desc['release_parent']['path'])
        base['assets'][str(root/'python.exe')]['sha256']='0'*64;n.write(path,base)
        desc['release_parent']['sha256']=m.digest(path)
        # Also self-hash the prior reference, keeping its identical forged assets.
        prior_path=Path(desc['prior_installation']['path']);prior=m.read_json(prior_path)
        prior['assets']=copy.deepcopy(base['assets']);prior['normal_performance_adoption']['parent']['sha256']=desc['release_parent']['sha256']
        n.write(prior_path,prior);desc['prior_installation']['sha256']=m.digest(prior_path)
        n.write(n.SELECTION,dict(receipt=str(prior_path),sha256=desc['prior_installation']['sha256']))
        desc['selection_before']['sha256']=m.digest(n.SELECTION);before=n.SELECTION.read_bytes()
        with patch.object(p,'require_lock_parent',return_value={}),patch.object(n.runner,'production_inactive'),\
             patch.object(n,'status',return_value=dict(running=False,cleanup_pending=False)),patch.object(n,'write') as write:
            with self.assertRaisesRegex(RuntimeError,'contents changed'):p.prepare_locked(n,desc,{})
            write.assert_not_called();self.assertEqual(n.SELECTION.read_bytes(),before)

    def test_lock_parent_identity_and_each_actual_lock_are_required(self):
        root,base,value,desc=self.fixture();records=root/'data/records';records.mkdir()
        for name in ('cli-operation.lock','runtime.lock'):(records/name).write_bytes(b'0')
        owner=dict(pid=123,created=456.0,exe='python.exe',argv=['coordinator'],session=7)
        process=Mock();process.cmdline.return_value=owner['argv']
        with patch.object(os,'getppid',return_value=123),patch.object(p,'session_id',return_value=7),\
             patch.object(n.safety,'require_identity',return_value=process):
            with patch.object(p.msvcrt,'locking',side_effect=OSError(errno.EACCES,'locked')):
                self.assertTrue(p.require_lock_parent(n,owner)['both_locks_exclusive'])
            with patch.object(p.msvcrt,'locking'):
                with self.assertRaisesRegex(RuntimeError,'both shared locks'):p.require_lock_parent(n,owner)
            with patch.object(p,'session_id',return_value=9):
                with self.assertRaisesRegex(RuntimeError,'session'):p.require_lock_parent(n,owner)
        with self.assertRaisesRegex(RuntimeError,'parent'):p.require_lock_parent(n,owner)

    def test_prepare_and_publish_keep_pointer_CAS_and_do_not_reenter_parent_locks(self):
        root,base,value,desc=self.fixture();before=n.SELECTION.read_bytes()
        with patch.object(p,'require_lock_parent',return_value={'both_locks_exclusive':True}),\
             patch.object(n.runner,'production_inactive'),patch.object(n,'status',return_value=dict(running=False,cleanup_pending=False)),\
             patch.object(n,'validate_assets'),patch.object(n.runner,'shared_operation',side_effect=AssertionError('nested locks')):
            prepared=p.prepare_locked(n,desc,{})
        self.assertEqual(n.SELECTION.read_bytes(),before)
        with patch.object(n.runner,'shared_operation',return_value=contextlib.nullcontext()),\
             patch.object(n.runner,'production_inactive'),patch.object(n,'validate_assets'):
            n.publish(prepared['receipt'],prepared['sha256'])
        self.assertEqual(n.shim_receipt()[0]['sha256'],prepared['sha256'])

    def test_active_pending_or_selection_drift_has_zero_writes(self):
        root,base,value,desc=self.fixture()
        for state in (dict(running=True,cleanup_pending=False),dict(running=False,cleanup_pending=True)):
            with patch.object(p,'require_lock_parent',return_value={}),patch.object(n.runner,'production_inactive'),\
                 patch.object(n,'status',return_value=state),patch.object(n,'write') as write:
                with self.assertRaisesRegex(RuntimeError,'stopped'):p.prepare_locked(n,desc,{})
                write.assert_not_called()
        n.write(n.SELECTION,dict(drift=True))
        with patch.object(n.runner,'shared_operation',return_value=contextlib.nullcontext()),patch.object(n.runner,'production_inactive'),\
             patch.object(n,'read_receipt',return_value=value),patch.object(n,'validate_assets'),patch.object(n,'atomic') as atomic:
            path=Path(value['profile']).parent/'receipt.json';n.write(path,value)
            with self.assertRaisesRegex(RuntimeError,'Selection'):n.publish(path,m.digest(path))
            atomic.assert_not_called()

    def test_text_flags_only_and_normal_defaults_are_not_trial_limits(self):
        from serve import server
        root,base,value,desc=self.fixture();cfg=m.read_json(value['profile'])
        cfg.update(backend='hip',gpu=0,hip_ordinal=1)
        env=m.normalized_environment(cfg,dict(STRATA_PREFILL_TIMING='1',AMD_LOG_LEVEL='5'))
        with patch.dict(server.os.environ,env,clear=True),patch.object(server,'hip_env_guard'):
            text=server.child_env(cfg)
        self.assertEqual({k:v for k,v in text.items() if k.startswith('STRATA_')},p.FLAGS)
        self.assertNotIn('AMD_LOG_LEVEL',text);self.assertNotIn('STRATA_PREFILL_TIMING',text)
        self.assertFalse(any(k.startswith('STRATA_') for k in server.vision_env(cfg,text)))
        self.assertEqual(n.cal.arg_value(cfg['args'],'--prompt-cache'),'6');self.assertEqual(cfg['max_tokens'],900)


class GitContract(unittest.TestCase):
    def test_clean_commit_tracks_index_but_ignores_unrelated_untracked_notes(self):
        # Use the production Git argument contract, not a fake clean return in a
        # CLI wrapper. The real clean B/Q commit is also checked by the operator.
        for dirty in ('',' M tracked.py','M  staged.py'):
            def git(*args):
                if args[0]=='status':
                    self.assertIn('--untracked-files=no',args);return dirty
                return 'a'*40 if args[-1]=='HEAD' else 'b'*40
            with patch.object(p,'git',side_effect=git),patch.object(p.subprocess,'run'):
                if dirty:
                    with self.assertRaisesRegex(RuntimeError,'tracked/index'):p.revision()
                else:self.assertEqual(p.revision()['baseline'],p.BASELINE)

    def test_wrong_release_ancestry_is_not_silently_adopted(self):
        with patch.object(p.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['git'])):
            with self.assertRaises(subprocess.CalledProcessError):p.revision()
