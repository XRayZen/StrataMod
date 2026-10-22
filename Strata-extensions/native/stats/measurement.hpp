#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace strata_ext::measurement {
enum class Phase { Startup, Prefill, Decode, DSpark };
struct Identity {
    std::string fixture_sha256,asset_sha256,bundle_sha256,request_id;
    uint64_t epoch=0;
    Phase phase=Phase::Startup;
};
struct ByteCounters {
    uint64_t logical_useful=0,read_requested=0;
    std::optional<uint64_t> physical_io;
    uint64_t h2d=0,d2h=0,p2p=0,host_bounce=0,failed_transfer=0;
};
// Cumulative counters from one caller-owned source, never additive snapshots.
// Sequence increases within that source/request/epoch; reset starts a new identity.
struct ByteSnapshot { Identity identity; uint64_t sequence=0; ByteCounters bytes; std::string counter_source; };
struct ByteDelta { Identity identity; uint64_t begin_sequence=0,end_sequence=0; ByteCounters bytes; std::string counter_source; };
ByteDelta counter_delta(const ByteSnapshot& before,const ByteSnapshot& after);
struct DeviceBytes { std::string identity; uint64_t owned=0; };
// One instant only. Pinned is part of owned_host; queue/lease are annotations,
// not additional allocations. OS observations have separate scope, never totals.
struct LedgerSnapshot {
    Identity identity;
    uint64_t owned_host=0,pinned_subset=0;
    std::vector<DeviceBytes> devices;
    uint64_t queue_bytes=0,lease_bytes=0;
    std::optional<uint64_t> os_physical,os_commit,wddm_local;
};
uint64_t owned_total(const LedgerSnapshot&);
struct HostStamp { int64_t nanoseconds=0; uint64_t resolution_ns=0; std::string domain; };
struct HostInterval { HostStamp start,end; bool completed=false; };
struct DeviceInterval { std::string start_device,end_device; double milliseconds=0; bool completed=false; };
struct Derived { std::optional<double> value; std::string reason; };
HostStamp host_now();
Derived host_seconds(const HostInterval&);
Derived device_seconds(const DeviceInterval&);
Derived bytes_per_second(const ByteDelta&,const HostInterval&);
Derived amplification(const ByteDelta&);
// No snapshot/delta merge, cross-device timing, thread-sum-to-wall conversion,
// token/SSE metrics, ownership registry, or runtime activation gate.
}
