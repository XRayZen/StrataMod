"""Finite native revision checks, using only tiny temporary assets."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from local_runtime import normal_runtime as n


class NativeRevision(unittest.TestCase):
    def setUp(self):
        from local_runtime import amd_vision_revision as r
        self.r=r;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.parents=self.root/'installations';self.parents.mkdir()
        cfg=dict(args=['--max-context','262144','--prompt-cache','6'],env={},log='old',vision=dict(exe='old.exe',temp_dir='old',max_tokens=300))
        parent_profile=self.parents/'parent-profile.json';n.write(parent_profile,cfg)
        self.model=self.root/'model.gguf';self.model.write_bytes(b'tiny test model; must not be rehashed')
        self.sdk=self.root/'sdk.dll';self.sdk.write_bytes(b'tiny unchanged SDK')
        self.cpp=self.root/'encoder.cpp';self.cpp.write_bytes(b'old source')
        old={str(p):dict(sha256=n.m.digest(p),metadata=n.metadata(p)) for p in (self.model,self.sdk,self.cpp)}
        full=dict(kind=n.KIND,assets=copy.deepcopy(old),references={},full_content_verification_at=123,sources={'s':'old'},profile=str(parent_profile),profile_sha256=n.m.digest(parent_profile))
        full_path=self.parents/'full.json';n.write(full_path,full)
        parent=copy.deepcopy(full);parent.update(full_verification_origin=dict(path=str(full_path),sha256=n.m.digest(full_path)))
        parent_path=self.parents/'parent.json';n.write(parent_path,parent)
        self.cpp.write_bytes(b'new source')
        self.exe=self.root/'new.exe';self.exe.write_bytes(b'tiny native output')
        changes={str(self.cpp):dict(before=old[str(self.cpp)],after=dict(sha256=n.m.digest(self.cpp),metadata=n.metadata(self.cpp)))}
        additions={str(self.exe):dict(sha256=n.m.digest(self.exe),metadata=n.metadata(self.exe))}
        self.build=dict(changed_assets=changes,added_assets=additions,roles={'hip_staged':dict(path=str(self.exe),sha256=n.m.digest(self.exe))})
        self.build_path=self.root/'build.json';n.write(self.build_path,self.build)
        self.enterContext(patch.object(r,'PARENT',parent_path));self.enterContext(patch.object(r,'PARENT_SHA',n.m.digest(parent_path)))
        self.enterContext(patch.object(n,'FULL_BASE',full_path));self.enterContext(patch.object(n,'FULL_BASE_SHA',n.m.digest(full_path)))
        self.enterContext(patch.object(n,'HOME',self.root/'normal'));n.HOME.mkdir()
        self.enterContext(patch.object(n.m,'local_path',side_effect=Path))
        self.enterContext(patch.object(n.image,'M3_BUILD',self.build_path));self.enterContext(patch.object(n.image,'M3_BUILD_SHA',n.m.digest(self.build_path)))
        self.enterContext(patch.object(n.image,'m3_native_manifest',side_effect=lambda:copy.deepcopy(self.build)))
        self.enterContext(patch.object(n,'source_files',return_value={'s':'new'}))
        self.enterContext(patch.object(r,'SOURCE_DELTA',{'s'}))
        self.enterContext(patch.object(n,'profile',side_effect=lambda d:dict(copy.deepcopy(cfg),log=str(Path(d)/'engine.log'),vision=dict(cfg['vision'],exe=str(self.exe),temp_dir=str(Path(d)/'tmp')))))
        self.enterContext(patch.object(n,'dependencies',return_value=[self.model,self.sdk,self.cpp,self.exe,self.build_path]))
        self.enterContext(patch.object(n,'references'))
        self.enterContext(patch.object(n.runner,'shared_operation'));self.enterContext(patch.object(n.runner,'production_inactive'))
        self.full,self.parent=full,parent

    def prepare(self):return self.r.prepare(n)
    def value(self):
        result=self.prepare();return n.m.read_json(result['receipt'])

    def test_revision_inherits_model_without_digest_and_never_activates(self):
        real=n.m.digest;calls=[]
        def digest(p):
            self.assertNotIn(Path(p),(self.model,self.sdk));calls.append(str(p));return real(p)
        with patch.object(n.m,'digest',side_effect=digest),patch.object(n,'publish') as publish:
            result=self.prepare()
        value=n.m.read_json(result['receipt']);self.r.validate(n,value)
        self.assertFalse(result['activated']);publish.assert_not_called()
        self.assertEqual(value['assets'][str(self.model)],self.parent['assets'][str(self.model)])
        self.assertEqual(value['full_content_verification_at'],123)
        self.assertFalse(value['assets_full_sha_read_this_revision']);self.assertTrue(calls)

    def test_declared_allowed_asset_bytes_cannot_authorize_replacement(self):
        value=self.value();value['assets'][str(self.exe)]['sha256']='f'*64
        with self.assertRaises(RuntimeError):self.r.validate(n,value)

    def test_foreign_asset_and_missing_inherited_asset_reject(self):
        value=self.value()
        for assets in ({**value['assets'],'foreign':{}},{k:v for k,v in value['assets'].items() if k!=str(self.model)}):
            with self.subTest(assets=len(assets)),self.assertRaises(RuntimeError):self.r.validate(n,dict(value,assets=assets))

    def test_parent_proof_tamper_rejects(self):
        self.r.PARENT.write_text('{}')
        with self.assertRaises(RuntimeError):self.prepare()

    def test_original_full_proof_tamper_rejects(self):
        n.FULL_BASE.write_text('{}')
        with self.assertRaises(RuntimeError):self.prepare()

    def test_metadata_change_rejects_without_model_hash(self):
        self.model.write_bytes(b'changed longer model')
        with self.assertRaises(RuntimeError):self.prepare()

    def test_allowed_native_file_body_change_rejects(self):
        self.exe.write_bytes(b'evil native replacement')
        with self.assertRaises(RuntimeError):self.prepare()

    def test_expected_parent_change_row_is_bound(self):
        self.build['changed_assets'][str(self.cpp)]['before']['sha256']='f'*64
        with self.assertRaises(RuntimeError):self.prepare()

    def test_context_profile_tamper_rejects_even_with_new_profile_hash(self):
        value=self.value();cfg=n.m.read_json(value['profile']);cfg['args'][1]='4096';n.write(value['profile'],cfg)
        value['profile_sha256']=n.m.digest(value['profile'])
        with self.assertRaises(RuntimeError):self.r.validate(n,value)

    def test_current_source_change_rejects(self):
        value=self.value()
        with patch.object(n,'source_files',return_value={'s':'foreign'}),self.assertRaises(RuntimeError):self.r.validate(n,value)

    def test_foreign_source_delta_rejects_even_when_declared_map_matches_current(self):
        value=self.value();value['sources']['foreign']='f'*64
        with patch.object(n,'source_files',return_value=value['sources']),self.assertRaises(RuntimeError):self.r.validate(n,value)

    def test_actual_receipt_reader_uses_native_validation_and_rejects_changed_source(self):
        result=self.prepare();n.read_receipt(result['receipt'])
        with patch.object(n,'source_files',return_value={'s':'foreign'}),self.assertRaises(RuntimeError):n.read_receipt(result['receipt'])

    def test_sdk_metadata_change_rejects_without_body_digest(self):
        self.sdk.write_bytes(b'modified SDK payload length')
        with self.assertRaises(RuntimeError):self.prepare()

    def test_current_inspection_or_reparse_error_rejects(self):
        with patch.object(n,'check_metadata',side_effect=RuntimeError('reparse/unknown')),self.assertRaises(RuntimeError):self.prepare()

    def test_preparation_does_not_publish_a_pointer(self):
        pointer=self.root/'installed.json'
        with patch.object(n,'SELECTION',pointer):self.prepare()
        self.assertFalse(pointer.exists())

    def test_after_new_source_copy_prepare_validates_saved_parent_without_current_selected(self):
        with patch.object(n,'selected',side_effect=RuntimeError('old receipt/source mismatch')) as selected:
            result=self.prepare()
        selected.assert_not_called();n.read_receipt(result['receipt'])

    def test_unknown_build_asset_overlap_rejects(self):
        self.build['added_assets'][str(self.model)]=copy.deepcopy(self.parent['assets'][str(self.model)])
        with self.assertRaises(RuntimeError):self.prepare()

    def test_inactive_guard_failure_prevents_directory_and_receipt_creation(self):
        with patch.object(n.runner,'production_inactive',side_effect=RuntimeError('busy/pending/port')),self.assertRaises(RuntimeError):self.prepare()
        self.assertFalse((n.HOME/'installations').exists())

    def test_save_failure_cannot_activate(self):
        with patch.object(n,'write',side_effect=OSError('disk full')),patch.object(n,'publish') as publish,self.assertRaises(OSError):self.prepare()
        publish.assert_not_called()

    def test_full_verify_still_hashes_fixture_model(self):
        value=self.value();seen=[];real=n.m.digest
        with patch.object(n,'critical_dlls',return_value=set()),patch.object(n.m,'digest',side_effect=lambda p:(seen.append(str(p)) or real(p))):n.validate_assets(value,full=True)
        self.assertIn(str(self.model),seen)

class BuildManifestContract(unittest.TestCase):
    def setUp(self):
        from local_runtime import image_phase as image
        self.image=image
        self.temp=tempfile.TemporaryDirectory(dir=image.manifest.LOCAL/'records');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'native-build.json'
        self.enterContext(patch.object(image,'M3_BUILD',self.path))
        root=image.manifest.ROOT
        inputs={str(root/name):'a'*64 for name in ('tools/vision/strata_vision.cpp','tools/vision/CMakeLists.txt','tools/vision/amd_vision/diagnostics.h','tools/vision/amd_vision/diagnostics.cpp')}
        roles={key:dict(path=str(root/(key+'.exe')),sha256='b'*64) for key in ('cpu','hip','cuda','sycl','hip_staged')}
        roles['cpu']=dict(path=str(image.CPU_EXE),sha256=image.CPU_SHA)
        roles['hip_staged']=dict(path=str(image.HIP_EXE),sha256=image.HIP_SHA)
        self.value=dict(version=3,kind='amd-vision-m3-native-build',llama_commit='3cf03257f219afbe7334045ff7c6a06ac68c627d',
              source_files=inputs,changed_assets={str(root/name):dict(after=dict(sha256='a'*64)) for name in ('tools/vision/strata_vision.cpp','tools/vision/CMakeLists.txt')},
              added_assets={row['path']:dict(sha256=row['sha256']) for row in roles.values()},roles=roles,
              builds={key:dict(actions=[dict(kind=k,exit_code=0) for k in ('configure','compile','compile','link')]) for key in ('cpu','hip','cuda','sycl')},sdk_root=str(image.SDK))
        for name in inputs:
            if name not in self.value['changed_assets']:self.value['added_assets'][name]=dict(sha256='a'*64)

    def read(self,value):
        n.write(self.path,value)
        with patch.object(self.image,'M3_BUILD_SHA',n.m.digest(self.path)):return self.image.m3_native_manifest()

    def test_fixed_manifest_contract_and_negative_roles_inputs_sdk_actions(self):
        self.assertEqual(self.read(self.value),self.value)
        bad=[]
        for key,value in (('version',2),('kind','foreign'),('sdk_root','foreign'),('llama_commit','f'*40)):
            row=copy.deepcopy(self.value);row[key]=value;bad.append(row)
        row=copy.deepcopy(self.value);row['source_files']['foreign']='x';bad.append(row)
        row=copy.deepcopy(self.value);row['roles'].pop('cuda');bad.append(row)
        row=copy.deepcopy(self.value);row['roles']['hip_staged']['sha256']='f'*64;bad.append(row)
        row=copy.deepcopy(self.value);row['builds']['hip']['actions'][-1]['exit_code']=1;bad.append(row)
        for value in bad:
            with self.subTest(value=str(value)[:60]),self.assertRaises(RuntimeError):self.read(value)

    def test_immutable_build_sha_tamper_rejects(self):
        n.write(self.path,self.value);expected=n.m.digest(self.path);self.path.write_text('{}')
        with patch.object(self.image,'M3_BUILD_SHA',expected),self.assertRaises(RuntimeError):self.image.m3_native_manifest()


if __name__=='__main__':unittest.main()
