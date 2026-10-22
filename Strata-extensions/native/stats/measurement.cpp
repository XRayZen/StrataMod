#include "measurement.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <set>
#include <stdexcept>
#define NOMINMAX
#include <Windows.h>

namespace strata_ext::measurement {
namespace {
void validate(const Identity& id){
    for(const auto* hash:{&id.fixture_sha256,&id.asset_sha256,&id.bundle_sha256})
        if(hash->size()!=64 || hash->find_first_not_of("0123456789abcdef")!=std::string::npos)
            throw std::invalid_argument("invalid measurement hash");
    if(id.request_id.empty() || id.phase<Phase::Startup || id.phase>Phase::DSpark)
        throw std::invalid_argument("invalid request/phase");
}
bool same(const Identity& a,const Identity& b){
    return a.fixture_sha256==b.fixture_sha256 && a.asset_sha256==b.asset_sha256 && a.bundle_sha256==b.bundle_sha256
        && a.request_id==b.request_id && a.epoch==b.epoch && a.phase==b.phase;
}
uint64_t subtract(uint64_t a,uint64_t b){if(b<a)throw std::invalid_argument("counter reset/decrease");return b-a;}
uint64_t add(uint64_t a,uint64_t b){if(b>UINT64_MAX-a)throw std::overflow_error("owned bytes overflow");return a+b;}
void validate(const ByteDelta& d){validate(d.identity);if(d.counter_source.empty() || d.end_sequence<=d.begin_sequence)throw std::invalid_argument("invalid delta source/sequence");}
Derived unknown(const char* reason){return {std::nullopt,reason};}
Derived finite(double v){return std::isfinite(v)?Derived{v,""}:unknown("nonfinite derived value");}
}
ByteDelta counter_delta(const ByteSnapshot& a,const ByteSnapshot& b){
    validate(a.identity);validate(b.identity);
    if(!same(a.identity,b.identity) || a.counter_source.empty() || a.counter_source!=b.counter_source || b.sequence<=a.sequence)
        throw std::invalid_argument("counter identity/source/sequence mismatch");
    const auto& x=a.bytes;const auto& y=b.bytes;
    ByteCounters delta{subtract(x.logical_useful,y.logical_useful),subtract(x.read_requested,y.read_requested),std::nullopt,
        subtract(x.h2d,y.h2d),subtract(x.d2h,y.d2h),subtract(x.p2p,y.p2p),subtract(x.host_bounce,y.host_bounce),subtract(x.failed_transfer,y.failed_transfer)};
    if(x.physical_io && y.physical_io)delta.physical_io=subtract(*x.physical_io,*y.physical_io);
    return {a.identity,a.sequence,b.sequence,delta,a.counter_source};
}
uint64_t owned_total(const LedgerSnapshot& s){
    validate(s.identity);if(s.pinned_subset>s.owned_host)throw std::invalid_argument("pinned is not host subset");
    uint64_t total=s.owned_host;std::set<std::string> devices;
    for(const auto& device:s.devices){
        if(device.identity.empty() || !devices.insert(device.identity).second)throw std::invalid_argument("duplicate/unknown device gauge");
        total=add(total,device.owned);
    }
    return total;
}
HostStamp host_now(){
    LARGE_INTEGER count{},frequency{};
    if(!QueryPerformanceFrequency(&frequency) || frequency.QuadPart<=0 || !QueryPerformanceCounter(&count) || count.QuadPart<0)
        return {-1,0,"Windows/QPC/current-process"};
    const long double ns=static_cast<long double>(count.QuadPart)*1000000000.0L/frequency.QuadPart;
    if(ns>INT64_MAX)return {-1,0,"Windows/QPC/current-process"};
    return {static_cast<int64_t>(ns),static_cast<uint64_t>(std::ceil(1000000000.0L/frequency.QuadPart)),"Windows/QPC/current-process"};
}
Derived host_seconds(const HostInterval& s){
    if(!s.completed)return unknown("incomplete host operation");
    if(s.start.domain.empty() || s.start.domain!=s.end.domain)return unknown("host clock domain mismatch");
    if(s.start.nanoseconds<0 || s.end.nanoseconds<=s.start.nanoseconds)return unknown("nonpositive/invalid host interval");
    const auto ns=static_cast<uint64_t>(s.end.nanoseconds-s.start.nanoseconds);
    if(!s.start.resolution_ns || !s.end.resolution_ns || ns<std::max(s.start.resolution_ns,s.end.resolution_ns))return unknown("insufficient clock resolution");
    return finite(static_cast<double>(ns)/1e9);
}
Derived device_seconds(const DeviceInterval& s){
    if(!s.completed)return unknown("incomplete device operation");
    if(s.start_device.empty() || s.start_device!=s.end_device)return unknown("cross-device/unknown event interval");
    if(!std::isfinite(s.milliseconds) || s.milliseconds<=0)return unknown("invalid event duration");
    return finite(s.milliseconds/1000);
}
Derived bytes_per_second(const ByteDelta& d,const HostInterval& s){
    validate(d);auto seconds=host_seconds(s);if(!seconds.value)return seconds;
    return finite(static_cast<double>(d.bytes.logical_useful)/ *seconds.value);
}
Derived amplification(const ByteDelta& d){
    validate(d);if(!d.bytes.physical_io)return unknown("physical I/O not observed");
    if(!d.bytes.logical_useful)return unknown("zero useful denominator");
    return finite(static_cast<double>(*d.bytes.physical_io)/static_cast<double>(d.bytes.logical_useful));
}
}
