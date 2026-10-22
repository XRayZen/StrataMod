from pathlib import Path
import copy,json,tempfile,unittest
from unittest.mock import patch
from local_runtime import pilot_authority as a


class PilotAuthority(unittest.TestCase):
    def test_only_five_inherited_wheel_spellings_allow_dotdot_with_both_prefixes_checked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ctx=a.PilotContext(root/'source',root/'pilot',root/'normal',root/'original',root/'data')
            site=ctx.original/'.venv/Lib/site-packages';site.mkdir(parents=True)
            scripts=ctx.original/'.venv/Scripts';scripts.mkdir();(scripts/'f2py.exe').write_bytes(b'fixture')
            inherited=site/'../../Scripts/f2py.exe'
            self.assertEqual(a.parent_asset_path(ctx,str(inherited)),inherited)
            for bad in (site/'../../Scripts/foreign.exe',site/'../../../Scripts/f2py.exe',ctx.normal/'Lib/site-packages/../../Scripts/f2py.exe'):
                with self.assertRaises(RuntimeError):a.parent_asset_path(ctx,str(bad))
            real=a.no_links
            def reparse(path):
                if path==site:raise RuntimeError('reparse prefix')
                return real(path)
            with patch.object(a,'no_links',side_effect=reparse),self.assertRaisesRegex(RuntimeError,'reparse prefix'):
                a.parent_asset_path(ctx,str(inherited))
            with self.assertRaises(RuntimeError):ctx.local(ctx.pilot/'../outside')

    def test_immutable_normal_data_proof_rejects_source_selection_asset_metadata_or_new_dependency_tamper(self):
        from local_runtime import manifest as m
        for changed in ('normal-source','selection','model-metadata','new-dependency'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as td:
                root=Path(td);ctx=a.PilotContext(root/'source',root/'pilot',root/'normal',root/'original',root/'data')
                paths=[ctx.normal/'local_runtime/normal/installed.json',ctx.normal/'receipt.json',ctx.normal/'profile.json',
                       ctx.normal/'serve.py',ctx.data/'large-model-fixture.bin',ctx.runtime/'new.dll']
                for path in paths:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
                def metadata(path):
                    st=path.stat();return dict(path=str(path),size=st.st_size,mtime_ns=st.st_mtime_ns,reparse=False)
                assets={str(path):dict(sha256=m.digest(path),metadata=metadata(path)) for path in paths[4:]}
                parent=dict(pointer=dict(receipt=str(paths[1])),selection_sha256=m.digest(paths[0]),
                    receipt=dict(profile=str(paths[2]),sources={str(paths[3]):m.digest(paths[3])},assets=assets,
                                 release_revision=dict(asset_proof=dict(full_hashed=[str(paths[5])]))))
                with patch.object(a,'PARENT_SHA',m.digest(paths[1])),patch.object(a,'PROFILE_SHA',m.digest(paths[2])):
                    a.verify_parent(ctx,parent,full=True)
                    path=paths[{'normal-source':3,'selection':0,'model-metadata':4,'new-dependency':5}[changed]]
                    st=path.stat();path.write_bytes(b'changed')
                    if changed=='new-dependency':
                        import os
                        os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
                    with self.assertRaises(RuntimeError):a.verify_parent(ctx,parent,full=True)

    def test_source_inventory_requires_every_added_module_and_refuses_foreign_dirty_path(self):
        from local_runtime import manifest as m
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ctx=a.PilotContext(root/'source',root/'pilot',root/'normal',root/'original',root/'data')
            ctx.source.mkdir();ctx.pilot.mkdir();ctx.operator.write_text('harness',encoding='utf-8')
            def git(ctx,*args):
                if args==('rev-parse','HEAD'):return a.BASE_HEAD.encode()
                if args==('rev-parse','HEAD^{tree}'):return a.BASE_TREE.encode()
                return b''
            with patch.object(a,'git',side_effect=git),self.assertRaisesRegex(RuntimeError,'incomplete'):
                a.source_proof(ctx)
            def dirty(ctx,*args):return b'foreign.py' if args==('diff','--name-only','HEAD') else git(ctx,*args)
            with patch.object(a,'git',side_effect=dirty),self.assertRaisesRegex(RuntimeError,'finite paths'):
                a.source_proof(ctx)

    def test_private_load_rejects_harness_changed_after_approved_hash_before_parent_use(self):
        from local_runtime import manifest as m
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ctx=a.PilotContext(root/'source',root/'pilot',root/'normal',root/'original',root/'data')
            ctx.pilot.mkdir();ctx.operator.write_text('reviewed harness',encoding='utf-8')
            def proof(ctx,**kw):return dict(operator_sha256=m.digest(ctx.operator))
            fixed=dict(kind=a.KIND,version=1,limits=a.LIMITS,arms=a.ARMS,order=list(a.ORDER),normal_unchanged=dict(env={},prompt_cache=6),
                       trial_prompt_cache=0,plan_sha256=a.PLAN_SHA,research_sha256=a.RESEARCH_SHA,source=proof(ctx),
                       roots=dict(source=str(ctx.source),pilot=str(ctx.pilot),normal=str(ctx.normal),original=str(ctx.original),data=str(ctx.data)))
            a.write(ctx.authority,fixed);sha=m.digest(ctx.authority);ctx.operator.write_text('changed harness',encoding='utf-8')
            with patch.object(a,'source_proof',side_effect=proof),patch.object(a,'verify_parent') as parent,\
                 self.assertRaisesRegex(RuntimeError,'operator bytes'):a.load(ctx,sha)
            parent.assert_not_called()

    def test_protocol_has_only_approved_four_arms_and_twelve_posts(self):
        self.assertEqual(a.ORDER,('00-unset','00-timing1','11-timing1','11-unset'))
        self.assertEqual(a.LIMITS,dict(starts=4,requests=12,request_seconds=120,max_tokens=128))
        self.assertEqual(a.ARMS['00-unset'],dict(STRATA_HIP_WMMA='0',STRATA_PF_FUSED='0'))
        self.assertEqual(a.ARMS['11-timing1'],dict(STRATA_HIP_WMMA='1',STRATA_PF_FUSED='1',STRATA_PREFILL_TIMING='1'))
        self.assertNotIn('STRATA_PREFILL_TIMING',a.ARMS['11-unset'])

    def test_profile_delta_only_relocates_cwd_log_temp_and_trial_cache_flags(self):
        base=dict(cwd='old',log='old.log',env={},args=['--prompt-cache','6','--spec','4','--pool-workers','3'],
                  vision=dict(temp_dir='oldtmp',max_tokens=300,threads=4))
        original=copy.deepcopy(base)
        cfg=a.arm_config(base,Path('C:/source'),Path('C:/pilot/run'),'00-timing1')
        self.assertEqual(base,original)
        self.assertEqual(cfg['env'],a.ARMS['00-timing1'])
        self.assertEqual(cfg['args'],['--spec','4','--pool-workers','3','--prompt-cache','0'])
        self.assertEqual(cfg['vision'],dict(temp_dir=str(Path('C:/pilot/run/tmp')),max_tokens=300,threads=4))
        for arm in ('U','10','01','00-timing0'):
            with self.assertRaises(RuntimeError):a.arm_config(base,Path('C:/source'),Path('C:/pilot/run'),arm)

    def test_private_root_contains_writes_and_refuses_traversal_or_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ctx=a.PilotContext(root/'source',root/'pilot',root/'normal',root/'original',root/'data')
            ctx.pilot.mkdir();ctx.source.mkdir();ctx.normal.mkdir();ctx.original.mkdir();ctx.data.mkdir()
            self.assertEqual(ctx.local(ctx.pilot/'runs'/'one.json'),ctx.pilot/'runs'/'one.json')
            for path in (ctx.normal/'file.json',ctx.pilot/'..'/'outside',Path('relative')):
                with self.assertRaises(RuntimeError):ctx.local(path)
            try:(ctx.pilot/'link').symlink_to(ctx.normal,target_is_directory=True)
            except OSError:return
            with self.assertRaises(RuntimeError):ctx.local(ctx.pilot/'link'/'file.json')

    def test_claims_are_ordered_exclusive_and_aborted_cannot_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaises(RuntimeError):a.reserve_start(root,1)
            a.reserve_start(root,0)
            with self.assertRaises(RuntimeError):a.reserve_start(root,0)
            with self.assertRaises(RuntimeError):a.reserve_request(root,0,1)
            a.reserve_request(root,0,0)
            with self.assertRaises(RuntimeError):a.reserve_request(root,0,0)
            with self.assertRaises(RuntimeError):a.reserve_request(root,0,3)
            a.write(root/'aborted.json',dict(reason='timeout'))
            with self.assertRaises(RuntimeError):a.reserve_request(root,0,1)
            with self.assertRaises(RuntimeError):a.reserve_start(root,1)

    def test_prior_valid_sample_and_full_cohort_exit_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a.reserve_start(root,0);a.reserve_request(root,0,0)
            a.write(root/'request-0-0.sample.json',dict(valid=True))
            a.reserve_request(root,0,1)
            for slot in (1,2):a.write(root/f'request-0-{slot}.sample.json',dict(valid=True))
            a.write(root/'completion-0.json',dict(complete=False))
            with self.assertRaises(RuntimeError):a.reserve_start(root,1)
            from local_runtime import manifest as m
            a.write(root/'completion-0.json',dict(complete=True,
                    samples={str(s):m.digest(root/f'request-0-{s}.sample.json') for s in range(3)},
                    cleanup=dict(complete=True,port_free=True)))
            a.reserve_start(root,1)
            with self.assertRaises(RuntimeError):a.reserve_start(root,4)

    def test_next_start_rejects_changed_sample_or_unproved_cleanup(self):
        from local_runtime import manifest as m
        for corrupted in ('sample','cleanup'):
            with self.subTest(corrupted=corrupted),tempfile.TemporaryDirectory() as td:
                root=Path(td);a.reserve_start(root,0)
                for slot in range(3):a.write(root/f'request-0-{slot}.sample.json',dict(valid=True))
                complete=dict(complete=True,samples={str(s):m.digest(root/f'request-0-{s}.sample.json') for s in range(3)},
                              cleanup=dict(complete=True,port_free=True))
                if corrupted=='sample':a.write(root/'request-0-1.sample.json',dict(valid=True,tampered=True))
                else:complete['cleanup']['complete']=False
                a.write(root/'completion-0.json',complete)
                with self.assertRaises(RuntimeError):a.reserve_start(root,1)
