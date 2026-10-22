#include "measurement.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <vector>
using namespace strata_ext::measurement;
template<class T,class=void> struct Addable:std::false_type{};
template<class T> struct Addable<T,std::void_t<decltype(std::declval<T>()+std::declval<T>())>>:std::true_type{};
static_assert(!Addable<LedgerSnapshot>::value && !Addable<ByteSnapshot>::value);
void check(bool condition){if(!condition)throw std::runtime_error("fixture assertion");}
template<class F> void rejects(F action){bool rejected=false;try{action();}catch(const std::invalid_argument&){rejected=true;}catch(const std::overflow_error&){rejected=true;}check(rejected);}
Identity identity(){return {std::string(64,'a'),std::string(64,'b'),std::string(64,'c'),"fixture-request",7,Phase::Decode};}
int main(int argc,char** argv){try{
    if(argc==2 && std::string(argv[1])=="--identity"){std::cout<<"{\"source_sha256\":\""<<T34_SOURCE_SHA<<"\"}\n";return 0;}
    if(argc!=5)throw std::invalid_argument("expected bounded norm fixture and three hashes");
    std::vector<std::string> cases;
    auto test=[&](const char* name,auto action){action();cases.emplace_back(name);};
    auto id=identity();
    ByteSnapshot before{id,1,{100,200,std::nullopt,30,4,5,6,7},"synthetic-io"},after{id,2,{150,280,std::nullopt,50,7,9,11,13},"synthetic-io"};
    test("counter-delta",[&]{auto d=counter_delta(before,after);check(d.bytes.logical_useful==50 && d.bytes.read_requested==80 && d.bytes.h2d==20 && d.bytes.failed_transfer==6 && !d.bytes.physical_io);});
    test("physical-zero",[&]{auto a=before,b=after;a.bytes.physical_io=0;b.bytes.physical_io=0;auto d=counter_delta(a,b);check(d.bytes.physical_io && *d.bytes.physical_io==0);check(amplification(d).value && *amplification(d).value==0);});
    test("physical-unknown",[&]{check(!amplification(counter_delta(before,after)).value);auto a=before,b=after;a.bytes.physical_io=12;check(!counter_delta(a,b).bytes.physical_io);});
    test("same-sequence-rejected",[&]{rejects([&]{counter_delta(before,before);});});
    test("reverse-sequence-rejected",[&]{rejects([&]{counter_delta(after,before);});});
    test("counter-reset-rejected",[&]{auto b=after;b.bytes.h2d=0;rejects([&]{counter_delta(before,b);});});
    test("physical-reset-rejected",[&]{auto a=before,b=after;a.bytes.physical_io=10;b.bytes.physical_io=9;rejects([&]{counter_delta(a,b);});});
    test("counter-source-rejected",[&]{auto b=after;b.counter_source="other-io";rejects([&]{counter_delta(before,b);});});
    test("counter-source-missing",[&]{auto b=after;b.counter_source.clear();rejects([&]{counter_delta(before,b);});});
    for(int field=0;field<6;++field)test(("identity-mismatch-"+std::to_string(field)).c_str(),[&]{auto b=after;if(field==0)b.identity.fixture_sha256[0]='d';if(field==1)b.identity.asset_sha256[0]='d';if(field==2)b.identity.bundle_sha256[0]='d';if(field==3)b.identity.request_id="other";if(field==4)++b.identity.epoch;if(field==5)b.identity.phase=Phase::Prefill;rejects([&]{counter_delta(before,b);});});
    test("metadata-hash-rejected",[&]{auto b=before;b.identity.asset_sha256="wrong";rejects([&]{counter_delta(b,after);});});
    test("metadata-phase-rejected",[&]{auto b=before;b.identity.phase=static_cast<Phase>(99);rejects([&]{counter_delta(b,after);});});
    LedgerSnapshot ledger{id,100,20,{{"gpu-a",30},{"gpu-b",40}},10,15,std::nullopt,500,std::nullopt};
    test("ledger-single-gauge-total",[&]{check(owned_total(ledger)==170);});
    test("ledger-pinned-subset",[&]{auto s=ledger;s.pinned_subset=101;rejects([&]{owned_total(s);});});
    test("ledger-duplicate-device",[&]{auto s=ledger;s.devices[1].identity="gpu-a";rejects([&]{owned_total(s);});});
    test("ledger-overflow",[&]{auto s=ledger;s.owned_host=UINT64_MAX;rejects([&]{owned_total(s);});});
    test("ledger-no-implicit-add",[&]{check(!Addable<LedgerSnapshot>::value && !Addable<ByteSnapshot>::value);});
    HostInterval host{{100,1,"clock-A"},{200,1,"clock-A"},true};
    test("host-duration-and-byte-rate",[&]{auto duration=host_seconds(host);check(duration.value && *duration.value==1e-7);auto r=bytes_per_second(counter_delta(before,after),host);check(r.value && *r.value==500000000.0);});
    test("host-reverse",[&]{auto s=host;s.end.nanoseconds=99;check(!host_seconds(s).value);});
    test("host-zero-denominator",[&]{auto s=host;s.end.nanoseconds=100;check(!bytes_per_second(counter_delta(before,after),s).value);});
    test("host-low-resolution",[&]{auto s=host;s.start.resolution_ns=101;check(!host_seconds(s).value);});
    test("host-no-resolution",[&]{auto s=host;s.start.resolution_ns=0;check(!host_seconds(s).value);});
    test("host-domain-mismatch",[&]{auto s=host;s.end.domain="clock-B";check(!host_seconds(s).value);});
    test("host-incomplete",[&]{auto s=host;s.completed=false;check(!host_seconds(s).value);});
    test("host-negative-stamp",[&]{auto s=host;s.start.nanoseconds=-1;check(!host_seconds(s).value);});
    DeviceInterval event{"gpu-a","gpu-a",2.5,true};
    test("same-device-event",[&]{check(device_seconds(event).value && *device_seconds(event).value==0.0025);});
    test("cross-device-event",[&]{auto s=event;s.end_device="gpu-b";check(!device_seconds(s).value);});
    test("event-incomplete",[&]{auto s=event;s.completed=false;check(!device_seconds(s).value);});
    test("event-nan",[&]{auto s=event;s.milliseconds=std::numeric_limits<double>::quiet_NaN();check(!device_seconds(s).value);});
    test("event-inf",[&]{auto s=event;s.milliseconds=std::numeric_limits<double>::infinity();check(!device_seconds(s).value);});
    test("event-negative",[&]{auto s=event;s.milliseconds=-1;check(!device_seconds(s).value);});
    test("event-zero",[&]{auto s=event;s.milliseconds=0;check(!device_seconds(s).value);});
    test("amplification-zero-useful",[&]{auto b=after;b.bytes.logical_useful=before.bytes.logical_useful;check(!amplification(counter_delta(before,b)).value);});
    test("amplification-literal",[&]{auto a=before,b=after;a.bytes.physical_io=10;b.bytes.physical_io=110;check(*amplification(counter_delta(a,b)).value==2);});
    // Thread-summed read/copy seconds have no HostStamp/HostInterval conversion.
    static_assert(!std::is_convertible<double,HostInterval>::value);
    test("thread-sum-not-wall",[&]{check(!std::is_convertible<double,HostInterval>::value);});
    Identity actual_id{argv[2],argv[3],argv[4],"t34-host-read",0,Phase::Startup};
    ByteSnapshot read_before{actual_id,0,{},"bounded-ifstream"},read_after{actual_id,1,{20480,20480,std::nullopt,0,0,0,0,0},"bounded-ifstream"};
    const auto actual_delta=counter_delta(read_before,read_after);
    auto start=host_now();std::ifstream file(argv[1],std::ios::binary);std::vector<char> raw(20480);file.read(raw.data(),raw.size());auto end=host_now();
    if(file.gcount()!=20480 || file.peek()!=std::char_traits<char>::eof())throw std::invalid_argument("norm bounded fixture length");
    auto duration=host_seconds({start,end,true});
    std::cout<<"{\"cases\":[";for(size_t i=0;i<cases.size();++i){if(i)std::cout<<',';std::cout<<'\"'<<cases[i]<<'\"';}
    std::cout<<"],\"actual_read\":{\"bytes\":"<<actual_delta.bytes.read_requested<<",\"fixture_sha256\":\""<<actual_id.fixture_sha256<<"\",\"asset_sha256\":\""<<actual_id.asset_sha256<<"\",\"bundle_sha256\":\""<<actual_id.bundle_sha256<<"\",\"request_id\":\"t34-host-read\",\"epoch\":0,\"phase\":\"startup\",\"physical_io\":null,\"start_ns\":"<<start.nanoseconds<<",\"end_ns\":"<<end.nanoseconds<<",\"resolution_ns\":"<<start.resolution_ns<<",\"seconds\":";
    if(duration.value)std::cout.precision(17),std::cout<<*duration.value;else std::cout<<"null";
    std::cout<<"},\"count\":"<<cases.size()<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
