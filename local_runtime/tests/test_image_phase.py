"""Fixed image phase inputs/parity/identity gates, no encoder or GPU launches."""
from array import array
import copy
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from local_runtime import image_phase as image


class ImagePhaseTests(unittest.TestCase):
    def test_versioned_native_receipt_cannot_substitute_the_selected_executable_role(self):
        paths={'cpu':image.CPU_EXE,'hip':image.manifest.ROOT/'hip.exe',
               'cuda':image.manifest.ROOT/'cuda.exe','sycl':image.manifest.ROOT/'sycl.exe','hip_staged':image.HIP_EXE}
        roles={key:dict(path=path.relative_to(image.manifest.ROOT).as_posix(),
                       sha256=image.CPU_SHA if key=='cpu' else image.HIP_SHA if key=='hip_staged' else 'a'*64)
               for key,path in paths.items()}
        receipt=dict(version=2,head=image.manifest.HEAD,sdk_files={'a':{}},
                     builds={key:{} for key in ('cpu','hip','cuda','sycl')},roles=roles,
                     executables={value['path']:value['sha256'] for value in roles.values()})
        original={'sdk_files':{'a':{}}}
        for kind in ('role','sdk','selected_sha'):
            changed=copy.deepcopy(receipt)
            if kind=='role':changed['roles']['hip_staged']['sha256']='0'*64
            elif kind=='sdk':changed['sdk_files'].pop(next(iter(changed['sdk_files'])))
            else:changed['executables'][str(image.HIP_EXE.relative_to(image.manifest.ROOT)).replace('\\','/')]='0'*64
            with self.subTest(kind=kind),patch.object(image.manifest,'digest',return_value=image.REPAIR_SHA),\
                 patch.object(image.manifest,'local_path',side_effect=Path),\
                 patch.object(image.manifest,'read_json',side_effect=lambda path:changed if Path(path)==image.REPAIR else original),\
                 self.assertRaisesRegex(RuntimeError,'role|inventory'):image.native_repair_pins()

    def test_phase_config_is_standalone_and_encode_requires_validated_probe(self):
        base=dict(args=['--native','C:/assets/model-00001-of-00003.gguf'])
        cfg=image.phase_config('vision-probe',image.manifest.LOCAL/'runs/fixture',base)
        self.assertEqual(cfg['commands'],[image.probe_command()])
        self.assertEqual(cfg['phase'],'vision-probe')
        with self.assertRaises(RuntimeError):
            image.phase_config('vision-encode',Path('C:/fixture'),base)
        cfg=image.phase_config('vision-encode',Path('C:/fixture'),base,dict(ordinal=7,arch='gfx1201',pci='0000:41:00.0'))
        self.assertEqual(len(cfg['commands']),3)
        self.assertEqual(cfg['ordinal'],7)
        self.assertEqual(cfg['commands'][2][-2:],['--gpu','--require-hip'])

    def test_manifest_has_only_finite_standalone_limits_and_arm(self):
        m=image.manifest
        self.assertEqual(m.SUITES['vision-probe'],dict(max_posts=0,max_tokens=0,max_starts=1,max_encodes=0))
        self.assertEqual(m.SUITES['vision-encode'],dict(max_posts=0,max_tokens=0,max_starts=3,max_encodes=6))
        cfg=m.expected_config('vision-hip10.1',Path('C:/fixture'),dict(args=['--native','C:/model.gguf']),'vision-probe')
        self.assertEqual(cfg['commands'],[image.probe_command()])
        with self.assertRaises(RuntimeError):
            m.expected_config('baseline',Path('C:/fixture'),dict(args=[]),'vision-probe')

    def test_probe_has_no_inherited_visibility_and_encode_order_is_finite(self):
        env=image.environment(image.manifest.LOCAL/'runs/fixture',None,
            dict(GPU_DEVICE_ORDINAL='9',HIP_VISIBLE_DEVICES='8',PYTHONPATH='foreign',SystemRoot='C:/Windows'))
        self.assertNotIn('GPU_DEVICE_ORDINAL',env)
        self.assertNotIn('HIP_VISIBLE_DEVICES',env)
        self.assertNotIn('PYTHONPATH',env)
        self.assertEqual(image.probe_command(),[str(image.HIP_EXE),'--list-devices','--require-hip'])
        phases=image.encode_protocol()
        self.assertEqual([row['arm'] for row in phases],['cpu-aa1','cpu-aa2','hip'])
        self.assertEqual(sum(len(row['encodes']) for row in phases),6)
        self.assertTrue(all(row['ready_deadline_seconds']==300 for row in phases))
        self.assertTrue(all(case['deadline_seconds']==60 for row in phases for case in row['encodes']))

    def test_sve_shape_length_nonfinite_and_parity_are_failclosed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'out.sve'
            header=struct.pack('<5i',0x31455653,2,1,2,2560)
            floats=array('f',[1.]*(2*2560))
            p.write_bytes(header+floats.tobytes())
            a=image.read_sve(p)
            self.assertEqual(a['shape'],[2,1,2,2560])
            self.assertEqual(image.compare_sve(a,a)['cosine'],1.)
            for body in (header+floats.tobytes()[:-1],struct.pack('<5i',0x31455653,301,1,301,2560),
                         header+struct.pack('<f',float('nan'))+floats.tobytes()[4:]):
                p.write_bytes(body)
                with self.assertRaises(ValueError): image.read_sve(p)

    def test_probe_matches_ordinal_from_device_name_not_row_number(self):
        raw=('strata-vision: HIP identity logical=7 PCI=0000:41:00.0 arch=gfx1201 name=AMD Radeon AI PRO R9700 mask=unfiltered\n'
             'DEVICE CPU CPU Intel PCI=unavailable\nDEVICE ROCm ROCm7 AMD Radeon AI PRO R9700 PCI=0000:41:00.0\n')
        windows=[dict(Name='AMD Radeon AI PRO R9700',pci='0000:41:00.0',PNPDeviceID='PCI\\VEN_1002&DEV_7551',DriverVersion='fixed')]
        self.assertEqual(image.match_probe(raw,windows)['ordinal'],7)
        with self.assertRaises(RuntimeError): image.match_probe(raw,windows*2)
        with self.assertRaises(RuntimeError): image.match_probe(raw.replace('gfx1201','gfx0000'),windows)

    def test_all_sdk_rows_match_names_and_conflicting_target_rows_are_refused(self):
        raw=('strata-vision: HIP identity logical=0 PCI=0000:03:00.0 arch=gfx1100 name=AMD Radeon RX 7900 XTX mask=unfiltered\n'
             'strata-vision: HIP identity logical=1 PCI=0000:07:00.0 arch=gfx1201:sramecc- name=AMD Radeon AI PRO R9700 mask=unfiltered\n'
             'DEVICE ROCm ROCm0 AMD Radeon RX 7900 XTX PCI=0000:03:00.0\n'
             'DEVICE ROCm ROCm1 AMD Radeon AI PRO R9700 PCI=0000:07:00.0\n')
        windows=[dict(Name='AMD Radeon AI PRO R9700',pci='0000:07:00.0',PNPDeviceID='PCI\\VEN_1002&DEV_7551',DriverVersion='fixed')]
        actual=image.match_probe(raw,windows)
        self.assertEqual(actual['ordinal'],1)
        self.assertEqual(actual['arch'],'gfx1201')
        self.assertEqual(actual['actual_arch'],'gfx1201:sramecc-')
        for changed in (raw.replace('arch=gfx1201:sramecc- name=AMD Radeon AI PRO R9700','arch=gfx1201 name=OTHER'),
                        raw+'strata-vision: HIP identity logical=1 PCI=0000:08:00.0 arch=gfx1201 name=AMD Radeon AI PRO R9700 mask=unfiltered\n',
                        raw.replace('logical=1 PCI=0000:07:00.0','logical=3 PCI=0000:07:00.0'),
                        raw.replace('arch=gfx1100 name=AMD Radeon RX 7900 XTX','arch=gfx1100 name=OTHER')):
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):image.match_probe(changed,windows)

    def test_probe_used_modules_require_private_path_standard_snapshot_and_hash(self):
        runtime=image.HIP_EXE.parent/'amdhip64_7.dll'
        raw=f'strata-vision: HIP runtime version 71626385\nstrata-vision: HIP runtime DLL {runtime}\n'
        modules=[dict(path=str(runtime),sha256='fixed',matched=True)]
        with patch.object(image.manifest,'digest',return_value='fixed'),patch.object(Path,'read_text',return_value='HIP header'):
            self.assertEqual(image.probe_modules(raw,modules,{str(runtime):'fixed'})['sdk_package_version'],'10.1.0')
            with self.assertRaises(RuntimeError):image.probe_modules(raw,[],{str(runtime):'fixed'})
            with self.assertRaises(RuntimeError):image.probe_modules(raw,modules,{str(runtime):'other'})
            with self.assertRaises(RuntimeError):image.probe_modules(raw.replace(str(runtime),'C:/foreign/amdhip64_7.dll'),modules,{str(runtime):'fixed'})

    def test_exe_runtime_self_line_is_not_repaired_by_a_correct_loaded_dll_line(self):
        runtime=image.HIP_EXE.parent/'amdhip64_7.dll'
        raw=(f'strata-vision: HIP runtime version 71626385\nstrata-vision: HIP runtime DLL {image.HIP_EXE}\n'
             f'strata-vision: LOADED_DLL {runtime}\n')
        modules=[dict(path=str(path),sha256='fixed',matched=True) for path in (runtime,image.HIP_EXE)]
        fixed={str(path):'fixed' for path in (runtime,image.HIP_EXE)}
        with patch.object(image.manifest,'digest',return_value='fixed'),patch.object(Path,'read_text',return_value='header'),\
             self.assertRaises(RuntimeError):image.probe_modules(raw,modules,fixed)


if __name__=='__main__': unittest.main()
