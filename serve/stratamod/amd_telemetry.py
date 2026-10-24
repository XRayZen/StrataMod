"""Windows AMD readings for the server's Monitor tab (StrataMod).

serve/telemetry.py reads an AMD card from the amdgpu driver's Linux sysfs files; Windows has no such files, so the
Monitor showed no load, VRAM or temperature there.  This reader fills them in with three Windows interfaces:

- DXGI: the card's name, its dedicated VRAM, and the LUID that the two counters below key on.  The engine itself
  finds its adapter by LUID too (src/core/device.cu).
- PDH: "\\GPU Engine(*)\\Utilization Percentage" and "\\GPU Adapter Memory(*)\\Total Committed" / "Shared Usage",
  read through PdhAddEnglishCounterW (the counter names are localized otherwise).  The instance names carry the
  adapter's LUID, so no index mapping is needed: `pid_123_luid_0x00000000_0x04A86516_phys_0_eng_1_engtype_3D` is
  this card's engine 1 of type 3D.  The load is the sum over the processes of each engine type (the engine types
  overlap, so they are not added together), then the largest type; a type can contain spaces (`Compute 0`,
  `Video Codec Engine`).  VRAM used is the card's committed dedicated memory, Total Committed minus Shared Usage
  (Task Manager's figure, stable while the card is idle); Dedicated Usage alone is residency and drops to ~0 when
  an idle card does not drive the display.
- ADL (atiadlxx.dll): the temperature.  The PMLog sensor block's `int iSize` must be set (2052 here) or the driver
  reads garbage; sensor 8 is the value this reader reports.  Which of sensors 8 and 9 is edge and which is hotspot
  is not documented here: on a Radeon AI PRO R9700 they read 66 and 70 °C.  The ADL adapter index counts display
  outputs, not cards, so the card is found by its adapter name; when no name matches, there is no temperature
  rather than another card's.

Power and the PCIe link have no counter or ADL sensor on this driver, so they stay None; the reader marks them in
`gpu_missing` for the Monitor.  Nothing here may raise: an unavailable library or counter is just a missing reading.
Measured on a Radeon AI PRO R9700, driver 32.0.31041.5005: 31,548,424,192 bytes of committed VRAM (Total Committed
minus Shared Usage), 66 °C.
"""
from __future__ import annotations

import ctypes
import os
import re
import threading
import uuid
from ctypes import wintypes

# The errors a ctypes/OS call here can raise.  TypeError joins the list for a call made with the wrong signature;
# OverflowError for a value too large for the conversion.  Every public method catches this tuple, because telemetry
# runs in the sampler thread and must not stop it.
_ERRORS = (OSError, AttributeError, ctypes.ArgumentError, ValueError, TypeError, OverflowError)

SENSOR_TEMP = 8               # ADL PMLog sensor 8; see the module docstring


def _normalize(name):
    """A card name comparable across DXGI, ADL and the registry ("AMD Radeon(TM) Graphics" -> "amdraedongraphics")."""
    text = str(name or "").casefold().replace("(tm)", "").replace("(r)", "")
    return re.sub(r"[^0-9a-z]+", "", text)


# ------------------------------------------------------------------------------------------------ DXGI
_IID_IDXGIFACTORY1 = "770aae78-f26f-4dba-a829-253c83d1b387"
_DXGI_ERROR_NOT_FOUND = 0x887A0002
_VENDOR_AMD = 0x1002


class _Guid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


def _guid(text):
    return _Guid((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))


class _Luid(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _AdapterDesc1(ctypes.Structure):
    """DXGI_ADAPTER_DESC1 (dxgi.h), the layout GetDesc1 writes."""
    _fields_ = [("Description", wintypes.WCHAR * 128),
                ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
                ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
                ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", _Luid), ("Flags", wintypes.UINT)]


def _com(obj, slot, restype, argtypes):
    """The function at a COM vtable slot.  ctypes has no COM support, so the slot's pointer is called by hand (the
    engine does the same through the C++ interfaces)."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[slot])


def _dxgi_amd_adapters():
    """Every AMD display adapter, in DXGI's order: [{"name", "luid_low", "luid_high", "mem_total", "vendor"}].
    [] off Windows, when DXGI is unavailable, or when it lists no AMD card."""
    if os.name != "nt":
        return []
    out = []
    factory = ctypes.c_void_p()
    try:
        dxgi = ctypes.WinDLL("dxgi")
        dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)]
        dxgi.CreateDXGIFactory1.restype = wintypes.LONG
        if dxgi.CreateDXGIFactory1(ctypes.byref(_guid(_IID_IDXGIFACTORY1)), ctypes.byref(factory)) < 0:
            return []
        enum = _com(factory, 12, wintypes.LONG, [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)])
        for index in range(32):
            adapter = ctypes.c_void_p()
            status = enum(factory, index, ctypes.byref(adapter))
            if (status & 0xFFFFFFFF) == _DXGI_ERROR_NOT_FOUND:
                break
            if status < 0 or not adapter:
                break
            try:
                desc = _AdapterDesc1()
                get_desc = _com(adapter, 10, wintypes.LONG, [ctypes.POINTER(_AdapterDesc1)])
                if get_desc(adapter, ctypes.byref(desc)) >= 0 and desc.VendorId == _VENDOR_AMD:
                    out.append({"name": desc.Description or "",
                                "luid_low": int(desc.AdapterLuid.LowPart) & 0xFFFFFFFF,
                                "luid_high": int(desc.AdapterLuid.HighPart) & 0xFFFFFFFF,
                                "mem_total": int(desc.DedicatedVideoMemory) or None,
                                "vendor": int(desc.VendorId)})
            finally:
                release = _com(adapter, 2, wintypes.ULONG, [])
                release(adapter)
    except _ERRORS:
        return out
    finally:
        if factory:
            try:
                _com(factory, 2, wintypes.ULONG, [])(factory)
            except _ERRORS:
                pass
    return out


# ------------------------------------------------------------------------------------------------ PDH
_LUID_RE = re.compile(r"luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys_\d+", re.I)
# The engine type is everything after "_engtype_": "3D", "Copy", "Compute 0", "Video Codec Engine", ...
_ENGINE_RE = re.compile(r"_engtype_(.+?)(?:#\d+)?$", re.I)


class _PdhValue(ctypes.Structure):
    # PDH_FMT_COUNTERVALUE: DWORD CStatus, then the union; DOUBLE was asked for, so only the double is read.
    _fields_ = [("status", wintypes.DWORD), ("value", ctypes.c_double)]


class _PdhItem(ctypes.Structure):
    _fields_ = [("name", wintypes.LPWSTR), ("value", _PdhValue)]


def _adapter_vram_used(dedicated, total, shared):
    """The adapter's committed dedicated VRAM in bytes: Total Committed minus Shared Usage, the figure Task Manager
    shows.  `dedicated` is the fallback when the adapter has no total/shared counters; None when no counter had a
    row.  Dedicated Usage alone is residency: on an idle card that does not drive the display it falls to ~0 while
    the model still holds ~30 GiB, so it must not be the primary reading."""
    if total is not None and shared is not None:
        return max(0, int(total - shared))
    if dedicated is not None:
        return max(0, int(dedicated))
    return None


class _PdhSampler:
    """The card's load and VRAM from Windows' own GPU counters.

    One query is opened in __init__ with the English counter paths and collected once.  read() collects again and
    parses every instance; the first read is None, before the one-second sampler has a settled interval.  The
    instance names are the only key to the card: PDH numbers adapters by LUID, as `luid_0x<high>_0x<low>_phys_0`."""

    UTIL_PATH = r"\GPU Engine(*)\Utilization Percentage"
    MEM_PATH = r"\GPU Adapter Memory(*)\Dedicated Usage"
    TOTAL_PATH = r"\GPU Adapter Memory(*)\Total Committed"
    SHARED_PATH = r"\GPU Adapter Memory(*)\Shared Usage"
    FMT = 0x8200                     # PDH_FMT_DOUBLE | PDH_FMT_NOCAP100: do not cap a process at 100%
    MORE_DATA = 0x800007D2

    def __init__(self, luid_low, luid_high):
        self.luid_low = int(luid_low) & 0xFFFFFFFF
        self.luid_high = int(luid_high) & 0xFFFFFFFF
        self.pdh = None
        self.query = None
        self.counters = {}
        self.first = True
        try:
            pdh = ctypes.WinDLL("pdh")
            pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
            pdh.PdhOpenQueryW.restype = wintypes.LONG
            pdh.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_size_t,
                                                  ctypes.POINTER(wintypes.HANDLE)]
            pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
            pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
            pdh.PdhCollectQueryData.restype = wintypes.LONG
            pdh.PdhGetFormattedCounterArrayW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                         ctypes.POINTER(wintypes.DWORD),
                                                         ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            pdh.PdhGetFormattedCounterArrayW.restype = wintypes.LONG
            pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
            query = wintypes.HANDLE()
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
                return
            counters = {}
            counter = wintypes.HANDLE()
            if pdh.PdhAddEnglishCounterW(query, self.UTIL_PATH, 0, ctypes.byref(counter)) != 0:
                pdh.PdhCloseQuery(query)
                return
            counters["util"] = counter
            # Optional: an adapter without Total Committed/Shared Usage keeps Dedicated Usage as its VRAM reading.
            for key, path in (("mem", self.MEM_PATH), ("total", self.TOTAL_PATH), ("shared", self.SHARED_PATH)):
                counter = wintypes.HANDLE()
                if pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)) == 0:
                    counters[key] = counter
            if pdh.PdhCollectQueryData(query) != 0:
                pdh.PdhCloseQuery(query)
                return
            self.pdh, self.query, self.counters = pdh, query, counters
        except _ERRORS:
            self.pdh = self.query = None
            self.counters = {}

    def close(self):
        try:
            if self.pdh is not None and self.query is not None:
                self.pdh.PdhCloseQuery(self.query)
        except _ERRORS:
            pass
        self.pdh = self.query = None

    def _luid(self, match):
        """The (high, low) pair an instance name carries; the first number is the LUID's HighPart."""
        return int(match.group(1), 16), int(match.group(2), 16)

    def _items(self, key):
        """[(instance name, status, value)] for one counter; the buffer is walked while it is alive."""
        size = wintypes.DWORD()
        count = wintypes.DWORD()
        status = self.pdh.PdhGetFormattedCounterArrayW(self.counters[key], self.FMT, ctypes.byref(size),
                                                       ctypes.byref(count), None) & 0xFFFFFFFF
        if status not in (0, self.MORE_DATA) or not 0 < size.value <= 8 << 20:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        status = self.pdh.PdhGetFormattedCounterArrayW(self.counters[key], self.FMT, ctypes.byref(size),
                                                       ctypes.byref(count), buffer) & 0xFFFFFFFF
        if status != 0:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhItem))
        return [(items[i].name or "", items[i].value.status, items[i].value.value) for i in range(count.value)]

    def _sum(self, key):
        """The counter's rows for this card, summed; None when the counter is absent or has no row."""
        if key not in self.counters:
            return None
        out, seen = 0.0, False
        for name, status, value in self._items(key):
            match = _LUID_RE.search(name)
            if not match or self._luid(match) != (self.luid_high, self.luid_low) or status not in (0, 1):
                continue
            out += value
            seen = True
        return out if seen else None

    def read(self):
        out = {"util": None, "mem_used": None}
        try:
            if self.pdh is None or self.query is None:
                return out
            if self.pdh.PdhCollectQueryData(self.query) != 0:
                return out
            if self.first:                    # __init__ collected once; this one needs a settled interval
                self.first = False
                return out
            engines = {}
            for name, status, value in self._items("util"):
                match = _LUID_RE.search(name)
                if not match or self._luid(match) != (self.luid_high, self.luid_low) or status not in (0, 1):
                    continue
                engine = _ENGINE_RE.search(name)
                kind = engine.group(1).strip().lower() if engine else ""
                engines[kind] = engines.get(kind, 0.0) + value
            if engines:
                out["util"] = int(round(max(engines.values())))
            used = _adapter_vram_used(self._sum("mem"), self._sum("total"), self._sum("shared"))
            if used is not None:
                out["mem_used"] = used
        except _ERRORS:
            return {"util": None, "mem_used": None}
        return out


# ------------------------------------------------------------------------------------------------ ADL
_ADL_MAX_PATH = 256


class _AdlAdapterInfo(ctypes.Structure):
    """ADLAdapterInfo (adl_sdk.h).  ADL 7.26 fills it at this size (1572 bytes) and one entry per display output."""
    _fields_ = [("iSize", ctypes.c_int), ("iAdapterIndex", ctypes.c_int),
                ("strUDID", ctypes.c_char * _ADL_MAX_PATH),
                ("iBusNumber", ctypes.c_int), ("iDeviceNumber", ctypes.c_int), ("iFunctionNumber", ctypes.c_int),
                ("iVendorID", ctypes.c_int), ("strAdapterName", ctypes.c_char * _ADL_MAX_PATH),
                ("strDisplayName", ctypes.c_char * _ADL_MAX_PATH), ("iPresent", ctypes.c_int),
                ("iExist", ctypes.c_int), ("strDriverPath", ctypes.c_char * _ADL_MAX_PATH),
                ("strDriverPathExt", ctypes.c_char * _ADL_MAX_PATH), ("strPNPString", ctypes.c_char * _ADL_MAX_PATH),
                ("iOSDisplayIndex", ctypes.c_int)]


class _PmLogSensor(ctypes.Structure):
    _fields_ = [("supported", ctypes.c_int), ("value", ctypes.c_int)]


class _PmLogData(ctypes.Structure):
    """ADLPMLogDataOutput: int iSize, then 256 {int supported; int value}.  iSize must be set (2052) or the
    readings are garbage."""
    _fields_ = [("iSize", ctypes.c_int), ("sensors", _PmLogSensor * 256)]


def _adl_index(adapters, name, index_hint=0):
    """The ADL adapter index of the card named `name` in [(iAdapterIndex, name), ...], or None.

    ADL numbers display outputs, not cards (ten entries for two cards on the measured machine), so its index is
    the entry's own iAdapterIndex - never the list position and never the HIP/DXGI index.  `index_hint` is kept
    for the caller's shape and deliberately not a fallback: another card's temperature is worse than none."""
    wanted = _normalize(name)
    if not wanted:
        return None
    for index, adapter_name in adapters:
        if _normalize(adapter_name) == wanted:
            return int(index)
    return None


class _Adl:
    """AMD's Display Library: the card's temperature from its PMLog sensors, and the adapter names that map ADL's
    display-output numbering to a card name."""

    def __init__(self):
        self.lib = None
        self.context = None
        self.names = []
        self._blocks = []             # the malloc callback's buffers: ADL keeps the pointers
        self._callback = None
        try:
            lib = ctypes.WinDLL("atiadlxx.dll")
            lib.ADL2_Main_Control_Create.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                     ctypes.POINTER(ctypes.c_void_p)]
            lib.ADL2_Main_Control_Create.restype = ctypes.c_int
            self._callback = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)(self._malloc)
            context = ctypes.c_void_p()
            if lib.ADL2_Main_Control_Create(self._callback, 1, ctypes.byref(context)) != 0:
                return
            self.lib, self.context = lib, context
            self.names = self._read_names()
        except _ERRORS:
            self.lib = self.context = None
            self.names = []

    def _malloc(self, size):
        if not 0 < size <= 1 << 20:
            return None
        block = ctypes.create_string_buffer(size)
        self._blocks.append(block)
        return ctypes.addressof(block)

    def _read_names(self):
        try:
            number = ctypes.c_int()
            self.lib.ADL2_Adapter_NumberOfAdapters_Get.argtypes = [ctypes.c_void_p,
                                                                   ctypes.POINTER(ctypes.c_int)]
            self.lib.ADL2_Adapter_NumberOfAdapters_Get.restype = ctypes.c_int
            if self.lib.ADL2_Adapter_NumberOfAdapters_Get(self.context, ctypes.byref(number)) != 0:
                return []
            if not 0 < number.value <= 64:
                return []
            infos = (_AdlAdapterInfo * number.value)()
            for info in infos:
                info.iSize = ctypes.sizeof(_AdlAdapterInfo)
            self.lib.ADL2_Adapter_AdapterInfo_Get.argtypes = [ctypes.c_void_p, ctypes.POINTER(_AdlAdapterInfo),
                                                              ctypes.c_int]
            self.lib.ADL2_Adapter_AdapterInfo_Get.restype = ctypes.c_int
            if self.lib.ADL2_Adapter_AdapterInfo_Get(self.context, infos, ctypes.sizeof(infos)) != 0:
                return []
            return [(int(info.iAdapterIndex),
                     bytes(info.strAdapterName).decode("utf-8", "replace")) for info in infos]
        except _ERRORS:
            return []

    def _index(self, name, index_hint=0):
        """The ADL adapter index of this card, or None when its name is not among ADL's adapters."""
        return _adl_index(self.names, name, index_hint)

    def temperature(self, name=None, index_hint=0):
        if self.lib is None or self.context is None:
            return None
        try:
            index = self._index(name, index_hint)
            if index is None:
                return None
            data = _PmLogData()
            data.iSize = ctypes.sizeof(_PmLogData)
            self.lib.ADL2_New_QueryPMLogData_Get.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                             ctypes.POINTER(_PmLogData)]
            self.lib.ADL2_New_QueryPMLogData_Get.restype = ctypes.c_int
            if self.lib.ADL2_New_QueryPMLogData_Get(self.context, index, ctypes.byref(data)) != 0:
                return None
            sensor = data.sensors[SENSOR_TEMP]
            if not sensor.supported or not 0 < sensor.value <= 200:
                return None
            return float(sensor.value)
        except _ERRORS:
            return None


_ADL = None
_ADL_LOCK = threading.Lock()          # the context is shared by the sampler thread and any free_vram_mib() caller


def _adl_temperature(name, index=0):
    """The card's GPU temperature in °C (ADL PMLog sensor 8), or None.  `index` is the card's HIP/DXGI index; ADL
    numbers display outputs, so the adapter name decides, and a name ADL does not list is None rather than another
    card's sensor.  Off Windows, ADL is absent and this is None."""
    global _ADL
    if os.name != "nt":
        return None
    try:
        with _ADL_LOCK:
            if _ADL is None:
                _ADL = _Adl()
            return _ADL.temperature(name, index)
    except _ERRORS:
        return None


# ------------------------------------------------------------------------------------------------ the reader
def _registry_cards():
    """The AMD cards the display driver's registry lists (serve.telemetry.windows_amd_cards), or []."""
    try:
        from serve.telemetry import windows_amd_cards
        return windows_amd_cards()
    except (ImportError, *_ERRORS):
        return []


def _pick_adapter(adapters, index, cards):
    """The AMD adapter for the requested card.  DXGI's order is usually the registry's, but when the registry names
    the card at `index`, its name is what decides - DXGI and HIP need not number the cards alike.  Same-named cards
    (two of one model) keep the index's own adapter."""
    if not 0 <= index < len(adapters):
        return None
    adapter = adapters[index]
    if 0 <= index < len(cards):
        wanted = _normalize(cards[index].get("name"))
        if wanted and _normalize(adapter.get("name")) != wanted:
            matches = [candidate for candidate in adapters if _normalize(candidate.get("name")) == wanted]
            if len(matches) == 1:
                return matches[0]
            if matches:                         # two cards of one model: keep the registry's order among them
                rank = sum(1 for card in cards[:index] if _normalize(card.get("name")) == wanted)
                if rank < len(matches):
                    return matches[rank]
    return adapter


class AmdWindowsGpu:
    """#1587 follow-up: a Windows AMD card's readings, with _Nvml/_Amd's interface: load, VRAM (used and total),
    temperature, and None for power and the PCIe link, which this driver's counters do not have.  The load and the
    used VRAM come from PDH, the name and total VRAM from DXGI (falling back to the registry's memory size), and
    the temperature from ADL.  Any of them may be missing; ok() is about the card being found, not every reading."""

    gpu_missing = ("power", "pcie")   # the Monitor's two tiles Windows AMD cannot fill

    def __init__(self, index=0):
        self.index = index
        self.adapter = None
        self.card = None
        self.pdh = None
        try:
            adapters = _dxgi_amd_adapters() or []
            cards = _registry_cards()
            adapter = _pick_adapter(adapters, index, cards)
            if adapter is None:
                return
            self.adapter = adapter
            self.card = cards[index] if 0 <= index < len(cards) else None
        except _ERRORS:
            self.adapter = None
            return
        try:
            self.pdh = _PdhSampler(self.adapter["luid_low"], self.adapter["luid_high"])
        except _ERRORS:
            self.pdh = None

    def ok(self):
        return self.adapter is not None

    def name(self):
        try:
            if self.adapter and self.adapter.get("name"):
                return self.adapter["name"]
            if self.card and self.card.get("name"):
                return self.card["name"]
        except _ERRORS:
            pass
        return None

    def vram_total(self):
        """The card's dedicated VRAM in bytes: DXGI's DedicatedVideoMemory, else the registry's size."""
        try:
            if self.adapter and self.adapter.get("mem_total"):
                return int(self.adapter["mem_total"])
            if self.card and self.card.get("vram_bytes"):
                return int(self.card["vram_bytes"])
        except _ERRORS:
            pass
        return None

    def close(self):
        """Closes this reader's PDH query.  Telemetry keeps its reader for the process; a one-shot reader
        (free_vram_mib) closes it so every call does not leave a query handle behind."""
        try:
            if self.pdh is not None:
                self.pdh.close()
        except Exception:  # noqa: BLE001 - closing must never raise into the caller
            pass

    def read(self):
        out = {"util": None, "mem_used": None, "mem_total": None, "temp": None, "power": None,
               "power_limit": None, "pcie_gen": None, "pcie_gen_max": None, "pcie_width": None,
               "pcie_rx_mb": None, "pcie_tx_mb": None}
        if self.adapter is None:
            return out
        try:
            values = self.pdh.read() if self.pdh is not None else {}
        except _ERRORS:
            values = {}
        try:
            if values.get("util") is not None:
                out["util"] = max(0, min(100, int(round(float(values["util"])))))
            if values.get("mem_used") is not None:
                out["mem_used"] = int(values["mem_used"])
        except _ERRORS:
            pass
        out["mem_total"] = self.vram_total()
        try:
            out["temp"] = _adl_temperature(self.name(), self.index)
        except _ERRORS:
            out["temp"] = None
        return out
