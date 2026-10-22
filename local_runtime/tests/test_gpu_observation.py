import unittest
from local_runtime import gpu_observation as gpu


class GpuObservation(unittest.TestCase):
    def test_unique_pci_adapter_and_counter_instance(self):
        rows=[dict(Name='AMD Radeon AI PRO R9700',PNPDeviceID='PCI\\VEN_1002&DEV_7551',
                   pci='0000:41:00.0',DriverVersion='test')]
        adapters=[dict(name='AMD Radeon AI PRO R9700',vendor=0x1002,device=0x7551,
                       luid_high=0,luid_low=123,dedicated_capacity_bytes=32*2**30)]
        selected=gpu.select_adapter(rows,adapters)
        values=[dict(name='pid_42_luid_0x00000000_0x0000007B_phys_0',value=300,status=0),
                dict(name='pid_43_luid_0x00000000_0x0000007B_phys_0',value=900,status=0),
                dict(name='pid_42_luid_0x00000000_0x0000007C_phys_0',value=800,status=0)]
        self.assertEqual(gpu.select_memory(values,selected,pid=42),300)
        self.assertIsNone(gpu.select_memory(values,selected,pid=44))
        with self.assertRaises(RuntimeError):gpu.select_adapter(rows,adapters*2)
        with self.assertRaises(RuntimeError):gpu.select_adapter(rows*2,adapters)

    def test_missing_or_invalid_counter_is_not_zero(self):
        adapter=dict(luid_high=0,luid_low=1)
        for status in (5,0xc0000bc6):
            self.assertIsNone(gpu.select_memory([dict(name='pid_3_luid_0x00000000_0x00000001_phys_0',
                                                     value=0,status=status)],adapter,pid=3))


if __name__=='__main__':unittest.main()
