"""Read-only Windows display identity and PDH memory for the fixed image phase.

API definitions: Microsoft SetupDiGetDeviceRegistryPropertyW, IDXGIAdapter1::
GetDesc1, and PdhGetFormattedCounterArrayW. Missing counters remain unknown.
No shell, GPU workload, sampler subprocess, or fallback host-memory estimate.
"""
import ctypes as c
from ctypes import wintypes as w
import re
import uuid
import time
from pathlib import Path


class GUID(c.Structure):
    _fields_=[('bytes',c.c_ubyte*16)]
    @classmethod
    def of(cls,value):return cls((c.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le))


def select_adapter(windows,adapters):
    devices=[row for row in windows if 'R9700' in row.get('Name','')
             and 'VEN_1002&DEV_7551' in row.get('PNPDeviceID','').upper()]
    selected=[row for row in adapters if row.get('vendor')==0x1002 and row.get('device')==0x7551
              and 'R9700' in row.get('name','')]
    if len(devices)!=1 or len(selected)!=1 or not devices[0].get('pci'):
        raise RuntimeError('Unique Windows PCI identity and R9700 DXGI adapter are required')
    return dict(**selected[0],windows=devices[0])


def select_memory(rows,adapter,*,pid=None):
    selected=[]
    for row in rows:
        match=re.fullmatch(r'(?:pid_(\d+)_)?luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys_(\d+)(?:#\d+)?',row['name'],re.I)
        if not match:continue
        process,high,low,_=match.groups()
        if (int(high,16)!=adapter['luid_high'] or int(low,16)!=adapter['luid_low']
                or (pid is not None and process!=str(pid))):continue
        if row['status'] not in (0,1) or type(row['value']) is not int or row['value']<0:
            return None
        selected.append(row['value'])
    return sum(selected) if selected else None


def windows_displays():
    import winreg
    class Info(c.Structure):
        _fields_=[('size',w.DWORD),('guid',GUID),('devinst',w.DWORD),('reserved',c.c_size_t)]
    api=c.WinDLL('setupapi',use_last_error=True)
    api.SetupDiGetClassDevsW.argtypes=[c.POINTER(GUID),w.LPCWSTR,w.HWND,w.DWORD]
    api.SetupDiGetClassDevsW.restype=w.HANDLE
    api.SetupDiEnumDeviceInfo.argtypes=[w.HANDLE,w.DWORD,c.POINTER(Info)]
    api.SetupDiGetDeviceRegistryPropertyW.argtypes=[w.HANDLE,c.POINTER(Info),w.DWORD,c.POINTER(w.DWORD),
                                                   c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]
    api.SetupDiGetDeviceInstanceIdW.argtypes=[w.HANDLE,c.POINTER(Info),w.LPWSTR,w.DWORD,c.POINTER(w.DWORD)]
    api.SetupDiDestroyDeviceInfoList.argtypes=[w.HANDLE]
    guid=GUID.of('4d36e968-e325-11ce-bfc1-08002be10318')
    handle=api.SetupDiGetClassDevsW(c.byref(guid),None,None,2)
    if handle==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
    result=[]
    try:
        index=0
        while True:
            info=Info();info.size=c.sizeof(info)
            if not api.SetupDiEnumDeviceInfo(handle,index,c.byref(info)):
                if c.get_last_error()==259:break
                raise c.WinError(c.get_last_error())
            index+=1
            def prop(number):
                buffer=c.create_string_buffer(16384);kind=w.DWORD();size=w.DWORD()
                if not api.SetupDiGetDeviceRegistryPropertyW(handle,c.byref(info),number,c.byref(kind),buffer,len(buffer),c.byref(size)):
                    raise c.WinError(c.get_last_error())
                return int.from_bytes(buffer.raw[:4],'little') if kind.value==4 else c.wstring_at(buffer).split('\0')[0]
            name=prop(0)
            if 'R9700' not in name:continue
            ident=c.create_unicode_buffer(16384)
            if not api.SetupDiGetDeviceInstanceIdW(handle,c.byref(info),ident,len(ident),None):
                raise c.WinError(c.get_last_error())
            bus,address=prop(0x15),prop(0x1c)
            key='SYSTEM\\CurrentControlSet\\Control\\Class\\'+prop(9)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key) as registry:
                driver=winreg.QueryValueEx(registry,'DriverVersion')[0]
            result.append(dict(Name=name,PNPDeviceID=ident.value,DriverVersion=driver,
                               pci=f'0000:{bus:02x}:{address>>16:02x}.{address&0xffff:x}',
                               bus=bus,address=address,method='SetupAPI display class bus/address+driver registry'))
    finally:api.SetupDiDestroyDeviceInfoList(handle)
    return result


def dxgi_adapters():
    class Luid(c.Structure):_fields_=[('low',w.DWORD),('high',w.LONG)]
    class Desc(c.Structure):
        _fields_=[('name',w.WCHAR*128),('vendor',w.UINT),('device',w.UINT),('subsystem',w.UINT),
                  ('revision',w.UINT),('dedicated',c.c_size_t),('system',c.c_size_t),('shared',c.c_size_t),
                  ('luid',Luid),('flags',w.UINT)]
    def method(obj,index,result,*args):
        address=c.cast(obj,c.POINTER(c.POINTER(c.c_void_p))).contents[index]
        return c.WINFUNCTYPE(result,c.c_void_p,*args)(address)
    dxgi=c.WinDLL('dxgi',use_last_error=True)
    dxgi.CreateDXGIFactory1.argtypes=[c.POINTER(GUID),c.POINTER(c.c_void_p)]
    dxgi.CreateDXGIFactory1.restype=w.LONG
    guid=GUID.of('770aae78-f26f-4dba-a829-253c83d1b387');factory=c.c_void_p()
    if dxgi.CreateDXGIFactory1(c.byref(guid),c.byref(factory))<0:raise RuntimeError('DXGI factory failed')
    rows=[]
    try:
        for index in range(32):
            adapter=c.c_void_p()
            status=method(factory,12,w.LONG,w.UINT,c.POINTER(c.c_void_p))(factory,index,c.byref(adapter))
            if status&0xffffffff==0x887a0002:break
            if status<0:raise RuntimeError('DXGI adapter enumeration failed')
            try:
                desc=Desc()
                if method(adapter,10,w.LONG,c.POINTER(Desc))(adapter,c.byref(desc))<0:
                    raise RuntimeError('DXGI adapter description failed')
                rows.append(dict(name=desc.name,vendor=desc.vendor,device=desc.device,
                                 luid_high=desc.luid.high&0xffffffff,luid_low=desc.luid.low,
                                 dedicated_capacity_bytes=desc.dedicated,shared_capacity_bytes=desc.shared))
            finally:method(adapter,2,w.ULONG)(adapter)
        else:raise RuntimeError('DXGI adapter bound exceeded')
    finally:method(factory,2,w.ULONG)(factory)
    return rows


def loaded_modules(identity,dependencies,*,hash_files=True):
    """Standard loader paths, bounded to a saved native birth on both sides."""
    from . import manifest,runtime_safety as safety
    if safety.require_identity(safety.process_identity_status(identity)) is None:
        raise RuntimeError('Native root exited before loader query')
    kernel=c.WinDLL('kernel32',use_last_error=True);psapi=c.WinDLL('psapi',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    psapi.EnumProcessModulesEx.argtypes=[w.HANDLE,c.POINTER(w.HMODULE),w.DWORD,c.POINTER(w.DWORD),w.DWORD]
    psapi.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
    handle=kernel.OpenProcess(0x0400|0x0010,False,identity['pid'])
    if not handle:raise c.WinError(c.get_last_error())
    rows=[]
    try:
        modules=(w.HMODULE*4096)();needed=w.DWORD()
        if not psapi.EnumProcessModulesEx(handle,modules,c.sizeof(modules),c.byref(needed),3):
            raise c.WinError(c.get_last_error())
        if needed.value>c.sizeof(modules):raise RuntimeError('Loader query exceeds fixed capacity')
        for module in modules[:needed.value//c.sizeof(w.HMODULE)]:
            buffer=c.create_unicode_buffer(32768)
            count=psapi.GetModuleFileNameExW(handle,module,buffer,len(buffer))
            if not count or count==len(buffer):raise c.WinError(c.get_last_error())
            path=Path(buffer.value)
            if path.is_relative_to(Path('C:/Windows')):continue
            expected=next((sha for name,sha in dependencies.items() if Path(name)==path),None)
            rows.append(dict(path=str(path),manifest_sha256=expected))
    finally:kernel.CloseHandle(handle)
    if safety.require_identity(safety.process_identity_status(identity)) is None:
        raise RuntimeError('Native root exited during loader query')
    if hash_files:
        bind_module_hashes(rows)
    return rows


def bind_module_hashes(rows):
    from . import manifest
    for row in rows:
        path=Path(row['path']);actual=manifest.digest(path) if path.is_file() else None
        row.update(sha256=actual,matched=actual is not None and row['manifest_sha256']==actual)
    return rows


class GpuMemory:
    """One caller-owned query, sampled with the existing one-second monitor."""
    PATHS={kind:'\\GPU '+group+'(*)\\'+metric for kind,group,metric in (
        ('adapter_dedicated','Adapter Memory','Dedicated Usage'),('adapter_shared','Adapter Memory','Shared Usage'),
        ('process_dedicated','Process Memory','Dedicated Usage'),('process_shared','Process Memory','Shared Usage'))}
    def __init__(self,adapter):
        self.adapter=adapter;self.api=c.WinDLL('pdh',use_last_error=True);self.handle=w.HANDLE();self.counters={}
        self.api.PdhOpenQueryW.argtypes=[w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
        self.api.PdhAddEnglishCounterW.argtypes=[w.HANDLE,w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
        self.api.PdhCollectQueryData.argtypes=[w.HANDLE]
        self.api.PdhGetFormattedCounterArrayW.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.DWORD),c.POINTER(w.DWORD),c.c_void_p]
        self.api.PdhCloseQuery.argtypes=[w.HANDLE]
    def __enter__(self):
        if self.api.PdhOpenQueryW(None,0,c.byref(self.handle)):raise RuntimeError('PDH query unavailable')
        try:
            for key,path in self.PATHS.items():
                counter=w.HANDLE()
                if self.api.PdhAddEnglishCounterW(self.handle,path,0,c.byref(counter)):
                    raise RuntimeError('Required PDH GPU memory counter unavailable: '+key)
                self.counters[key]=counter
            if self.api.PdhCollectQueryData(self.handle):raise RuntimeError('PDH initial collect failed')
        except BaseException:
            self.__exit__();raise
        return self
    def sample(self,pid):
        class Value(c.Structure):_fields_=[('status',w.DWORD),('value',c.c_longlong)]
        class Item(c.Structure):_fields_=[('name',w.LPWSTR),('counter',Value)]
        if self.api.PdhCollectQueryData(self.handle):raise RuntimeError('PDH collect failed')
        raw={};observed={}
        for key,counter in self.counters.items():
            size=w.DWORD();count=w.DWORD()
            status=self.api.PdhGetFormattedCounterArrayW(counter,0x400,c.byref(size),c.byref(count),None)&0xffffffff
            if status not in (0,0x800007d2):raise RuntimeError('PDH wildcard size failed: '+hex(status))
            if not 0<size.value<=4*1024*1024:raise RuntimeError('PDH wildcard buffer unavailable/over bound')
            buffer=c.create_string_buffer(size.value)
            status=self.api.PdhGetFormattedCounterArrayW(counter,0x400,c.byref(size),c.byref(count),buffer)&0xffffffff
            if status:raise RuntimeError('PDH wildcard values failed: '+hex(status))
            if count.value*c.sizeof(Item)>size.value:raise RuntimeError('PDH array bound invalid')
            items=c.cast(buffer,c.POINTER(Item))
            raw[key]=[dict(name=items[i].name,status=items[i].counter.status,value=items[i].counter.value)
                      for i in range(count.value)]
            observed[key+'_bytes']=select_memory(raw[key],self.adapter,pid=pid if key.startswith('process') else None)
        return dict(pid=pid,adapter=self.adapter,raw=raw,**observed)
    def __exit__(self,*args):
        if self.handle:self.api.PdhCloseQuery(self.handle);self.handle=w.HANDLE()


class EncodeMemory:
    """Fixed encoder arm: real process/host values and optional same-LUID PDH."""
    def __init__(self,state,rows,adapter=None):
        self.state,self.rows,self.adapter=state,rows,adapter
        self.query=None;self.last=0
    def __enter__(self):
        if self.adapter is not None:self.query=GpuMemory(self.adapter).__enter__()
        return self
    def sample(self,label):
        from . import runtime_safety as safety,evaluate_r9700 as runner
        process=safety.require_identity(safety.process_identity_status(self.state))
        if process is None:raise RuntimeError('Encoder exited before memory collection')
        info=process.memory_info()
        row=dict(at=time.time(),label=label,pid=self.state['pid'],created=self.state['created'],host=runner.memory_sample(),
                 process={key:getattr(info,key,None) for key in ('rss','private','peak_wset','peak_pagefile')},gpu=None)
        if self.query is not None:row['gpu']=self.query.sample(process.pid)
        self.rows.append(row);self.last=time.monotonic()
        return row
    def periodic(self):
        if time.monotonic()-self.last>=1:self.sample('periodic')
    def __exit__(self,*args):
        if self.query is not None:self.query.__exit__(*args)
