"""Compile the actual diagnostic function against CPU-only fake HIP/Windows APIs.

The harness does not include or link HIP/ggml, enumerate hardware, or run an encoder.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get('STRATAMOD_TEST_MSVC', ROOT / '.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe'))

PRELUDE = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <string>
#include <vector>
#define STRATA_VISION_HIP 1
#define CP_UTF8 65001
#define GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS 4
#define GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT 2
using HMODULE=void*;
using LPCWSTR=const wchar_t*;
using DWORD=unsigned long;
const int hipSuccess=0;
std::string mode;
int switches=0;
struct hipDeviceProp_t {char gcnArchName[256]={};char name[256]={};};
int hipRuntimeGetVersion(int* v){*v=71626385;return 0;}
int hipGetDevice(int* v){*v=0;return 0;}
int hipGetDeviceCount(int* v){*v=mode=="zero"?0:2;return mode=="countfail"?1:0;}
int hipGetDeviceProperties(hipDeviceProp_t* p,int i){
 if(i==1&&mode=="propsfail")return 1;
 std::strcpy(p->name,i==0?"AMD Radeon RX 7900 XTX":"AMD Radeon AI PRO R9700");
 std::strcpy(p->gcnArchName,i==0?"gfx1100":"gfx1201");
 if(i==1&&mode=="emptyarch")p->gcnArchName[0]=0;
 if(i==1&&mode=="emptyname")p->name[0]=0;
 return 0;
}
int hipDeviceGetPCIBusId(char* out,int,int i){
 if(i==1&&mode=="pcifail")return 1;
 std::strcpy(out,i==0?"0000:03:00.0":"0000:07:00.0");
 if(i==1&&mode=="emptypci")out[0]=0;
 return 0;
}
int hipSetDevice(int){++switches;return 0;}
int GetModuleHandleExW(int,LPCWSTR,HMODULE* out){*out=reinterpret_cast<void*>(1);return mode!="modulemissing";}
HMODULE GetModuleHandleW(LPCWSTR name){
 return mode!="modulemissing" && std::wcscmp(name,L"amdhip64_7.dll")==0 ? reinterpret_cast<void*>(2):nullptr;
}
DWORD GetModuleFileNameW(HMODULE module,wchar_t* out,DWORD size){
 const wchar_t* value=module==reinterpret_cast<void*>(2)?L"C:\\private\\bin\\amdhip64_7.dll":L"C:\\private\\bin\\strata-vision-hip.exe";
 if(mode=="modulepathfail")return 0;
 std::wcsncpy(out,value,size);return static_cast<DWORD>(std::wcslen(value));
}
int WideCharToMultiByte(int,int,const wchar_t* value,int,char* out,int,void*,void*){
 const int n=static_cast<int>(std::wcslen(value))+1;
 if(out){for(int i=0;i<n;i++)out[i]=static_cast<char>(value[i]);}
 return n;
}
'''


class NativeDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'nt' or not COMPILER.is_file():
            raise RuntimeError('This required Windows CPU harness needs the pinned private MSVC')
        cls.folder = tempfile.TemporaryDirectory(dir=ROOT / '.vision-tmp', prefix='native-diagnostic-mock-')
        directory = Path(cls.folder.name)
        source = (ROOT / 'tools/vision/strata_vision.cpp').read_text(encoding='utf-8')
        function = source[source.index('bool hip_diagnostics() {'):source.index('\nstruct graph_proof')]
        harness = directory / 'test.cpp'
        harness.write_text(PRELUDE + '\n' + function + r'''
int main(int argc,char** argv){
 mode=argc>1?argv[1]:"normal";
 const bool result=hip_diagnostics();
 std::printf("RESULT=%d SWITCH_CALLS=%d\n",result?1:0,switches);
 return 0;
}
''', encoding='utf-8')
        cls.executable = directory / 'test.exe'
        built = subprocess.run([str(COMPILER), '/nologo', '/EHsc', '/std:c++17', '/MT', '/utf-8',
                                str(harness), '/Fe:' + str(cls.executable), '/Fo:' + str(directory / 'test.obj'),
                                '/link', '/INCREMENTAL:NO'], capture_output=True, timeout=60)
        if built.returncode:
            raise AssertionError('CPU mock compile failed: ' + (built.stdout + built.stderr).decode('utf-8', 'replace'))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_mock(self, mode='normal'):
        env = dict(os.environ)
        env.pop('HIP_VISIBLE_DEVICES', None)
        result = subprocess.run([str(self.executable), mode], capture_output=True, timeout=5, env=env)
        self.assertEqual(result.returncode, 0)
        return (result.stdout + result.stderr).decode('utf-8')

    def test_all_sdk_identities_are_actual_ordinal_pci_arch_name(self):
        text = self.run_mock()
        self.__class__.normal_sample = text
        self.assertIn('logical=0 PCI=0000:03:00.0 arch=gfx1100 name=AMD Radeon RX 7900 XTX mask=unfiltered', text)
        self.assertIn('logical=1 PCI=0000:07:00.0 arch=gfx1201 name=AMD Radeon AI PRO R9700 mask=unfiltered', text)
        self.assertEqual(text.count('HIP identity logical='), 2)
        self.assertIn('RESULT=1 SWITCH_CALLS=0', text)

    def test_runtime_dll_uses_loaded_module_not_exe_import_thunk(self):
        text = self.run_mock()
        line = next(line for line in text.splitlines() if 'HIP runtime DLL ' in line)
        self.assertTrue(line.endswith('amdhip64_7.dll'), line)
        self.assertNotIn('.exe', line)

    def test_zero_devices_or_failed_count_cannot_succeed(self):
        for mode in ('zero', 'countfail'):
            with self.subTest(mode=mode):
                self.assertIn('RESULT=0 SWITCH_CALLS=0', self.run_mock(mode))

    def test_any_missing_second_device_attribute_cannot_succeed(self):
        for mode in ('propsfail', 'pcifail', 'emptyarch', 'emptyname', 'emptypci'):
            with self.subTest(mode=mode):
                self.assertIn('RESULT=0 SWITCH_CALLS=0', self.run_mock(mode))

    def test_absent_loaded_runtime_or_module_path_cannot_succeed(self):
        for mode in ('modulemissing', 'modulepathfail'):
            with self.subTest(mode=mode):
                self.assertIn('RESULT=0 SWITCH_CALLS=0', self.run_mock(mode))


if __name__ == '__main__':
    unittest.main()
