"""The Windows AMD reader (serve/stratamod/amd_telemetry.py) and its wiring into telemetry: no GPU, no network.

    python -m unittest serve.stratamod.test_amd_telemetry

The native seams are replaced: `_dxgi_amd_adapters` (names, LUIDs, dedicated VRAM), `_PdhSampler` (load and used
VRAM), `_adl_temperature` (temperature), and `serve.telemetry.windows_amd_cards` (the registry's card names).
"""
from __future__ import annotations

import contextlib
import copy
import os
import shutil
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

from serve import telemetry
from serve.stratamod import amd_telemetry as A

GB = 1 << 30
LOW, HIGH = 0x04A86516, 0
R9700 = {"name": "AMD Radeon AI PRO R9700", "luid_low": LOW, "luid_high": HIGH, "mem_total": 32 * GB,
         "vendor": 0x1002}
RX6900 = {"name": "AMD Radeon RX 6900 XT", "luid_low": 0x04A816A2, "luid_high": 0, "mem_total": 16 * GB,
          "vendor": 0x1002}
ADAPTERS = [RX6900, R9700]
CARDS = [{"name": RX6900["name"], "provider": "Advanced Micro Devices, Inc.", "driver": "32.0.21001.9024",
          "vram_bytes": 16 * GB},
         {"name": R9700["name"], "provider": "Advanced Micro Devices, Inc.", "driver": "32.0.31041.5005",
          "vram_bytes": 32 * GB + 4096}]
KEYS = {"util", "mem_used", "mem_total", "temp", "power", "power_limit", "pcie_gen", "pcie_gen_max",
        "pcie_width", "pcie_rx_mb", "pcie_tx_mb"}

READINGS = {"util": 37.4, "mem_used": 12 * GB}


def fake_pdh(*readings):
    """A _PdhSampler whose read() returns the scripted dicts in turn; records the LUID it was built for."""
    class FakePdh:
        made = []

        def __init__(self, luid_low, luid_high):
            self.luid = (luid_low, luid_high)
            self._readings = list(readings)
            FakePdh.made.append(self)

        def read(self):
            if self._readings:
                return dict(self._readings.pop(0))
            return {"util": None, "mem_used": None}
    return FakePdh


@contextlib.contextmanager
def temp_tree():
    """A temporary folder whose children can be created.  tempfile.mkdtemp makes its folder with mode 0700, and on
    this sandbox that folder denies creating anything inside it; os.mkdir's default mode does not."""
    path = os.path.join(tempfile.gettempdir(), "strata-amd-" + uuid.uuid4().hex[:8])
    os.mkdir(path)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class Base(unittest.TestCase):
    @contextlib.contextmanager
    def reader(self, index=0, adapters=None, cards=None, pdh=None, temp=43.0):
        cards = CARDS if cards is None else cards
        pdh = pdh or fake_pdh(READINGS)
        with mock.patch.object(A, "_dxgi_amd_adapters", return_value=copy.deepcopy(ADAPTERS if adapters is None
                                                                                  else adapters)), \
                mock.patch.object(A, "_PdhSampler", pdh), \
                mock.patch.object(A, "_adl_temperature", return_value=temp) as adl, \
                mock.patch.object(telemetry, "windows_amd_cards", return_value=copy.deepcopy(cards)):
            reader = A.AmdWindowsGpu(index)
            reader.adl = adl
            yield reader


class Readings(Base):
    def test_load_vram_and_temperature(self):
        with self.reader(index=1) as g:
            self.assertTrue(g.ok())
            self.assertEqual(g.name(), "AMD Radeon AI PRO R9700")
            self.assertEqual(g.vram_total(), 32 * GB)          # DXGI's DedicatedVideoMemory
            self.assertEqual(g.pdh.luid, (LOW, HIGH))          # the instance names key on this LUID
            r = g.read()
            self.assertEqual(set(r), KEYS)
            self.assertEqual((r["util"], r["mem_used"], r["mem_total"]), (37, 12 * GB, 32 * GB))
            self.assertEqual(r["temp"], 43.0)
            self.assertEqual(r["power"], None)
            self.assertEqual(r["pcie_gen"], None)
            g.adl.assert_called_once_with("AMD Radeon AI PRO R9700", 1)

    def test_a_second_card_is_its_own_reader(self):
        with self.reader(index=0) as g:
            self.assertEqual(g.name(), "AMD Radeon RX 6900 XT")
            self.assertEqual(g.vram_total(), 16 * GB)
            self.assertEqual(g.pdh.luid, (RX6900["luid_low"], 0))

    def test_unknown_index_is_not_ok_and_reads_nothing(self):
        for index in (2, 7, -1):
            with self.subTest(index=index), self.reader(index=index) as g:
                self.assertFalse(g.ok())
                self.assertIsNone(g.name())
                self.assertIsNone(g.vram_total())
                r = g.read()
                self.assertEqual(set(r), KEYS)
                self.assertTrue(all(v is None for v in r.values()))

    def test_the_first_pdh_sample_is_none(self):
        with self.reader(index=1, pdh=fake_pdh({"util": None, "mem_used": None}), temp=None) as g:
            r = g.read()
            self.assertIsNone(r["util"])
            self.assertIsNone(r["mem_used"])
            self.assertEqual(r["mem_total"], 32 * GB)
            self.assertIsNone(r["temp"])

    def test_util_is_clamped_to_100(self):
        with self.reader(index=1, pdh=fake_pdh({"util": 160.0, "mem_used": 6 * GB})) as g:
            self.assertEqual(g.read()["util"], 100)

    def test_dxgi_failure_does_not_raise(self):
        with mock.patch.object(A, "_dxgi_amd_adapters", side_effect=OSError("no dxgi")):
            g = A.AmdWindowsGpu(0)
        self.assertFalse(g.ok())
        self.assertEqual(set(g.read()), KEYS)
        self.assertIsNone(g.read()["util"])

    def test_close_closes_the_pdh_query(self):
        with self.reader() as g:
            closed = []
            g.pdh.close = lambda: closed.append(True)
            g.close()
            self.assertEqual(closed, [True])

    def test_pdh_failure_still_leaves_name_vram_and_temperature(self):
        with mock.patch.object(A, "_dxgi_amd_adapters", return_value=copy.deepcopy(ADAPTERS)), \
                mock.patch.object(A, "_PdhSampler", side_effect=OSError("no pdh")), \
                mock.patch.object(A, "_adl_temperature", return_value=66.0), \
                mock.patch.object(telemetry, "windows_amd_cards", return_value=copy.deepcopy(CARDS)):
            g = A.AmdWindowsGpu(1)
            r = g.read()
        self.assertTrue(g.ok())
        self.assertIsNone(r["util"])
        self.assertIsNone(r["mem_used"])
        self.assertEqual(r["mem_total"], 32 * GB)
        self.assertEqual(r["temp"], 66.0)


class PdhParsing(unittest.TestCase):
    """The real _PdhSampler's array parsing, fed instance tuples instead of a PDH query."""

    def sampler(self, items, first=False, keys=("util", "mem")):
        s = object.__new__(A._PdhSampler)
        s.luid_low, s.luid_high = LOW, HIGH
        s.first = first
        s.counters = {key: object() for key in keys}
        s.query = object()
        s.pdh = types.SimpleNamespace(PdhCollectQueryData=lambda query: 0)
        s._items = lambda key: items[key]
        return s

    @staticmethod
    def engine(pid, engtype, value, low=LOW, status=0):
        return (f"pid_{pid}_luid_0x00000000_0x{low:08X}_phys_0_eng_1_engtype_{engtype}", status, value)

    @staticmethod
    def memory(value, low=LOW, status=0):
        return (f"luid_0x00000000_0x{low:08X}_phys_0", status, value)

    def test_util_is_the_sum_per_engine_type_then_the_max(self):
        items = {
            "util": [self.engine(1, "3D", 10.0), self.engine(2, "3D", 20.0),
                     self.engine(3, "Copy", 5.0), self.engine(4, "Copy", 7.0),
                     self.engine(5, "3D", 90.0, low=RX6900["luid_low"]),        # the other card
                     self.engine(6, "3D", 60.0, status=0xC0000BBA)],             # an invalid instance
            "mem": [self.memory(12 * GB), self.memory(20 * GB, low=RX6900["luid_low"])],
        }
        self.assertEqual(self.sampler(items).read(), {"util": 30, "mem_used": 12 * GB})

    def test_engine_types_with_spaces_stay_separate(self):
        """The R9700's instances include "Compute 0", "Timer 0", "Video JPEG 0" and "Video Codec Engine": each is
        its own type, so the reading is their max - not the sum that clamping to 100 would report."""
        items = {
            "util": [self.engine(1, "3D", 10.0), self.engine(2, "Copy", 5.0),
                     self.engine(3, "Compute 0", 50.0), self.engine(4, "Video Codec Engine", 30.0),
                     self.engine(5, "Video JPEG 0", 25.0), self.engine(6, "Timer 0", 5.0),
                     self.engine(7, "Security 1", 1.0)],
            "mem": [self.memory(12 * GB)],
        }
        self.assertEqual(self.sampler(items).read(), {"util": 50, "mem_used": 12 * GB})

    def test_the_first_read_waits_for_a_second_collection(self):
        items = {"util": [self.engine(1, "3D", 50.0)], "mem": [self.memory(6 * GB)]}
        s = self.sampler(items, first=True)
        self.assertEqual(s.read(), {"util": None, "mem_used": None})
        self.assertFalse(s.first)
        self.assertEqual(s.read(), {"util": 50, "mem_used": 6 * GB})

    def test_vram_is_the_committed_dedicated_memory(self):
        """Total Committed minus Shared Usage, the figure Task Manager shows; Dedicated Usage alone is residency and
        falls to ~0 on an idle card that does not drive the display."""
        items = {"util": [self.engine(1, "3D", 10.0)],
                 "mem": [self.memory(47_439_872)],
                 "total": [self.memory(50_853_351_424)],
                 "shared": [self.memory(19_304_927_232)]}
        self.assertEqual(self.sampler(items, keys=("util", "mem", "total", "shared")).read(),
                         {"util": 10, "mem_used": 31_548_424_192})

    def test_vram_falls_back_to_dedicated_without_total_and_shared(self):
        items = {"util": [], "mem": [self.memory(31_171_706_880)]}
        self.assertEqual(self.sampler(items).read()["mem_used"], 31_171_706_880)

    def test_vram_is_never_negative(self):
        items = {"util": [], "mem": [], "total": [self.memory(1 * GB)], "shared": [self.memory(2 * GB)]}
        self.assertEqual(self.sampler(items, keys=("util", "mem", "total", "shared")).read()["mem_used"], 0)


ADL_DISPLAY_OUTPUTS = ([(i, "AMD Radeon RX 7900 XTX") for i in range(5)]
                       + [(i, "AMD Radeon AI PRO R9700") for i in range(5, 10)])


class AdlMapping(unittest.TestCase):
    """ADL numbers display outputs, not cards; the index is the entry's own iAdapterIndex, never a fallback."""

    def test_a_name_match_returns_its_own_index_not_the_hint(self):
        self.assertEqual(A._adl_index(ADL_DISPLAY_OUTPUTS, "AMD Radeon AI PRO R9700", 1), 5)
        adl = object.__new__(A._Adl)
        adl.names = ADL_DISPLAY_OUTPUTS
        self.assertEqual(adl._index("AMD Radeon AI PRO R9700", 1), 5)

    def test_the_adapter_index_is_not_the_list_position(self):
        names = [(7, "Card A"), (3, "Card B")]
        self.assertEqual(A._adl_index(names, "Card B", 0), 3)
        self.assertEqual(A._adl_index(names, "Card A", 1), 7)

    def test_an_unknown_or_empty_name_is_none(self):
        for name in ("Other Card", "", None):
            self.assertIsNone(A._adl_index(ADL_DISPLAY_OUTPUTS, name, 1), name)
        self.assertIsNone(A._adl_index([], "AMD Radeon AI PRO R9700", 0))

    def test_no_name_means_no_temperature(self):
        adl = object.__new__(A._Adl)
        adl.lib, adl.context, adl.names = object(), object(), []
        self.assertIsNone(adl.temperature("AMD Radeon AI PRO R9700", 1))


class Selection(Base):
    def test_the_registry_name_wins_over_the_index(self):
        """DXGI lists the cards in another order than the registry: the name, not the index, finds the R9700."""
        adapters = [copy.deepcopy(RX6900), copy.deepcopy(R9700)]
        cards = [copy.deepcopy(CARDS[1]), copy.deepcopy(CARDS[0])]     # registry: R9700 at 0, the 6900 XT at 1
        with self.reader(index=0, adapters=adapters, cards=cards) as g:
            self.assertEqual(g.name(), "AMD Radeon AI PRO R9700")
            self.assertEqual(g.vram_total(), 32 * GB)
            self.assertEqual(g.pdh.luid, (LOW, HIGH))

    def test_without_a_matching_name_the_same_index_is_used(self):
        adapters = [dict(copy.deepcopy(RX6900), name="AMD Radeon Graphics 1"),
                    dict(copy.deepcopy(R9700), name="AMD Radeon Graphics 2")]
        with self.reader(index=1, adapters=adapters) as g:
            self.assertEqual(g.name(), "AMD Radeon Graphics 2")
            self.assertEqual(g.vram_total(), 32 * GB)

    def test_vram_total_falls_back_to_the_registry(self):
        adapters = [copy.deepcopy(RX6900), dict(copy.deepcopy(R9700), mem_total=None)]
        with self.reader(index=1, adapters=adapters) as g:
            self.assertEqual(g.vram_total(), 32 * GB + 4096)

    def test_two_cards_of_one_model_keep_their_own_luid(self):
        second = dict(copy.deepcopy(RX6900), luid_low=0x04A8FFFF)
        adapters = [copy.deepcopy(RX6900), second]
        cards = [copy.deepcopy(CARDS[0]), copy.deepcopy(CARDS[0])]
        with self.reader(index=1, adapters=adapters, cards=cards) as g:
            self.assertEqual(g.pdh.luid, (0x04A8FFFF, 0))


class Dispatch(unittest.TestCase):
    """gpu_reader prefers the sysfs reader when it finds a card, and only then falls back to the Windows one."""

    def tree(self, d):
        nodes = Path(d) / "class/kfd/kfd/topology/nodes/0"
        nodes.mkdir(parents=True)
        (nodes / "properties").write_text("simd_count 128\ngfx_target_version 120001\ndrm_render_minor 128\n")
        dev = Path(d) / "class/drm/renderD128/device"
        dev.mkdir(parents=True)
        (dev / "gpu_busy_percent").write_text("37\n")

    def test_a_sysfs_tree_is_read_on_windows_too(self):
        with temp_tree() as d:
            self.tree(d)
            with mock.patch.object(telemetry, "SYSFS", d), mock.patch.object(telemetry.os, "name", "nt"), \
                    mock.patch.object(A, "AmdWindowsGpu") as windows:
                g = telemetry.gpu_reader(0, amd=True)
        self.assertIsInstance(g, telemetry._Amd)
        self.assertTrue(g.ok())
        windows.assert_not_called()

    def test_windows_without_sysfs_uses_the_windows_reader(self):
        sentinel = object()
        with temp_tree() as d, mock.patch.object(telemetry, "SYSFS", d), \
                mock.patch.object(telemetry.os, "name", "nt"), \
                mock.patch.object(A, "AmdWindowsGpu", return_value=sentinel) as windows:
            self.assertIs(telemetry.gpu_reader(1, amd=True), sentinel)
        windows.assert_called_once_with(1)

    def test_posix_without_sysfs_stays_with_the_sysfs_reader(self):
        with temp_tree() as d, mock.patch.object(telemetry, "SYSFS", d), \
                mock.patch.object(telemetry.os, "name", "posix"):
            g = telemetry.gpu_reader(0, amd=True)
        self.assertIsInstance(g, telemetry._Amd)
        self.assertFalse(g.ok())


class FakeReader:
    gpu_missing = ("power", "pcie")

    def ok(self):
        return True

    def name(self):
        return "AMD Radeon AI PRO R9700"

    def vram_total(self):
        return 32 * GB

    def read(self):
        return {"util": 42, "mem_used": 12 * GB, "mem_total": 32 * GB, "temp": 66.0, "power": None,
                "power_limit": None, "pcie_gen": None, "pcie_gen_max": None, "pcie_width": None,
                "pcie_rx_mb": None, "pcie_tx_mb": None}


class NotOkReader:
    def ok(self):
        return False

    def name(self):
        return None

    def read(self):
        return {}


@unittest.skipUnless(os.name == "nt", "Windows AMD reader")
class TelemetryWiring(unittest.TestCase):
    def telemetry(self, reader, index=0):
        with mock.patch.object(telemetry, "gpu_reader", return_value=reader), \
                mock.patch.object(telemetry, "windows_amd_cards", return_value=copy.deepcopy(CARDS)), \
                mock.patch.object(telemetry.os, "name", "nt"), \
                mock.patch.object(telemetry.threading, "Thread"):
            return telemetry.Telemetry(gpu_index=index, amd=True)

    def test_static_values_and_the_missing_tiles(self):
        t = self.telemetry(FakeReader())
        try:
            self.assertEqual(t.static["gpu_name"], "AMD Radeon AI PRO R9700")
            self.assertEqual(t.static["gpu_vram_total_mib"], 32 * 1024)
            self.assertEqual(t.static["gpu_missing"], ["power", "pcie"])
            self.assertIsNone(t.static["gpu_note"])
            s = t.sample()
            self.assertEqual(s["gpu_util"], 42)
            self.assertEqual(s["gpu_mem_used"], 12 * GB)
            self.assertEqual(s["gpu_mem_total"], 32 * GB)
            self.assertEqual(s["gpu_temp"], 66.0)
            self.assertIsNone(s.get("gpu_power"))
        finally:
            t.close()

    def test_a_layer_split_sums_both_cards(self):
        second = FakeReader()
        second.name = lambda: "AMD Radeon RX 6900 XT"
        second.vram_total = lambda: 16 * GB
        with mock.patch.object(telemetry, "gpu_reader", side_effect=[FakeReader(), second]), \
                mock.patch.object(telemetry, "windows_amd_cards", return_value=copy.deepcopy(CARDS)), \
                mock.patch.object(telemetry.os, "name", "nt"), \
                mock.patch.object(telemetry.threading, "Thread"):
            t = telemetry.Telemetry(gpu_index=0, gpu_indices=[0, 1], amd=True)
        try:
            self.assertEqual(t.static["gpu_vram_total_mib"], (32 + 16) * 1024)
            self.assertEqual(t.static["gpu_name"], "AMD Radeon AI PRO R9700 + AMD Radeon RX 6900 XT")
        finally:
            t.close()

    def test_a_reader_vram_overflow_does_not_raise(self):
        class Overflow(FakeReader):
            def vram_total(self):
                raise OverflowError("too large for the conversion")
        t = self.telemetry(Overflow())
        try:
            self.assertIsNone(t.static["gpu_vram_total_mib"])
        finally:
            t.close()

    def test_a_failed_reader_keeps_the_registry_name_and_the_old_note(self):
        t = self.telemetry(NotOkReader(), index=1)
        try:
            self.assertEqual(t.static["gpu_name"], "AMD Radeon AI PRO R9700")
            self.assertEqual(t.static["gpu_vram_total_mib"], 32 * 1024)
            self.assertEqual(t.static["gpu_missing"], [])
            self.assertIn("AMD cards on Windows", t.static["gpu_note"])
        finally:
            t.close()


class ReaderClose(unittest.TestCase):
    def test_free_vram_closes_a_one_shot_reader(self):
        closed = []

        class Reader:
            def ok(self):
                return True

            def read(self):
                return {"mem_total": 8 * GB, "mem_used": 2 * GB}

            def close(self):
                closed.append(True)
        with mock.patch.object(telemetry, "gpu_reader", return_value=Reader()):
            self.assertEqual(telemetry.free_vram_mib(0, amd=True), 6 * 1024)
        self.assertEqual(closed, [True])

    def test_free_vram_closes_a_down_reader_and_ignores_a_raising_close(self):
        closed = []

        class Down:
            def ok(self):
                return False

            def close(self):
                closed.append(True)

        class BadClose(Down):
            def close(self):
                raise RuntimeError("close failed")
        with mock.patch.object(telemetry, "gpu_reader", return_value=Down()):
            self.assertIsNone(telemetry.free_vram_mib(0, amd=True))
        with mock.patch.object(telemetry, "gpu_reader", return_value=BadClose()):
            self.assertIsNone(telemetry.free_vram_mib(0, amd=True))
        self.assertEqual(closed, [True])


class WebText(unittest.TestCase):
    def test_the_monitor_explains_the_two_tiles(self):
        js = (Path(telemetry.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('st.gpu_missing', js)
        self.assertIn('"Windows AMD: no reading"', js)
        self.assertIn('"Windows AMD: no counter"', js)


if __name__ == "__main__":
    unittest.main()
