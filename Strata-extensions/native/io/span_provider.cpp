#include "span_provider.hpp"
#include "strata/platform/direct_file.hpp"
#include <windows.h>
#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace strata_ext::io {
namespace {
uint64_t add(uint64_t a,uint64_t b){if(b>UINT64_MAX-a)throw std::overflow_error("span overflow");return a+b;}
void require(bool v,const char* reason){if(!v)throw std::invalid_argument(reason);}
bool same(const measurement::Identity& a,const measurement::Identity& b){return a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256&&a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase;}
bool map_copy(void* dst,const void* src,size_t bytes){
    __try {std::memcpy(dst,src,bytes);return true;}
    __except(GetExceptionCode()==EXCEPTION_IN_PAGE_ERROR?EXCEPTION_EXECUTE_HANDLER:EXCEPTION_CONTINUE_SEARCH){return false;}
}
}
struct SpanProvider::Impl {
    struct Source {
        artifact::FixtureView view;HANDLE guard=INVALID_HANDLE_VALUE;
        std::unique_ptr<strata::platform::DirectFile> direct;
        std::string path;
        ~Source(){if(guard!=INVALID_HANDLE_VALUE)CloseHandle(guard);}
        Source()=default;Source(Source&&)=default;Source& operator=(Source&&)=default;
        Source(const Source&)=delete;
    };
    struct Request {
        bool used=false,cancelled=false,error=false,finished=false;
        uint64_t generation=0,total=0,completed=0,position=0;size_t span=0;uint32_t pending=0;
        const std::vector<Span>* spans=nullptr;Buffer destination{};
        const measurement::Identity* identity=nullptr;cache::Token lease{};const char* reason="";
    };
    struct IoSlot {
        Buffer buffer;bool active=false,quarantined=false,sync_ready=false,sync_ok=false;
        uint64_t tag=0,request_generation=0,a0=0,skip=0,needed=0,destination=0,requested=0;
        uint32_t request=0,source=0,sync_bytes=0;
    };
    std::vector<Source> sources;std::vector<IoSlot> slots;std::vector<Request> requests;
    Config config;Stats counters;uint64_t tag=0;uint32_t next_request=0;bool closed=false;
    explicit Impl(Config c):config(c){}
    Request& checked(Ticket t){require(t.slot<requests.size()&&requests[t.slot].used&&requests[t.slot].generation==t.generation,"stale request ticket");return requests[t.slot];}
    const Request& checked(Ticket t)const{return const_cast<Impl*>(this)->checked(t);}
    void finish(Request& r){if((r.cancelled||r.error||r.span==r.spans->size())&&r.pending==0)r.finished=true;}
    void error(Request& r,const char* reason){r.error=true;r.reason=reason;finish(r);}
};
SpanProvider::SpanProvider(const std::vector<artifact::FixtureView>& views,const std::vector<Buffer>& buffers,Config config):impl_(new Impl(config)) {
    constexpr uint64_t alignment=strata::platform::DirectFile::alignment();
    require(!views.empty()&&!buffers.empty()&&config.request_slots&&config.max_outstanding,"empty provider declaration");
    require(config.max_outstanding<=buffers.size()&&config.max_chunk&&config.max_chunk<=UINT32_MAX&&config.max_chunk%alignment==0,"physical window configuration");
    auto& p=*impl_;p.requests.resize(config.request_slots);p.slots.reserve(buffers.size());p.sources.reserve(views.size());
    for(const auto& b:buffers){
        require(b.data&&reinterpret_cast<uintptr_t>(b.data)%alignment==0&&b.capacity>=config.max_chunk&&b.capacity<=UINTPTR_MAX-reinterpret_cast<uintptr_t>(b.data),"actual aligned buffer capacity");
        for(const auto& previous:p.slots){auto a=reinterpret_cast<uintptr_t>(previous.buffer.data),x=reinterpret_cast<uintptr_t>(b.data);require(a+previous.buffer.capacity<=x||x+b.capacity<=a,"overlapping read buffers");}
        Impl::IoSlot slot{};slot.buffer=b;p.slots.push_back(slot);p.counters.buffer_capacity=add(p.counters.buffer_capacity,b.capacity);
    }
    require(config.max_outstanding_bytes>=alignment&&config.max_outstanding_bytes<=p.counters.buffer_capacity,"physical byte credits/capacity");
    for(const auto& view:views){
        require(view.bytes&&add(view.source_absolute_offset,view.bytes)>=view.bytes,"source extent");
        p.sources.emplace_back();auto& source=p.sources.back();source.view=view;
        source.guard=CreateFileW(view.path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(source.guard==INVALID_HANDLE_VALUE)throw std::runtime_error("source guard open failed");
        LARGE_INTEGER size{};if(!GetFileSizeEx(source.guard,&size)||size.QuadPart<0||uint64_t(size.QuadPart)!=view.bytes)throw std::runtime_error("source physical identity/extent changed");
        if(config.path==PathMode::PreferDirect){
            source.direct=std::make_unique<strata::platform::DirectFile>();std::string why;
            if(source.direct->open(view.path.u8string(),why))source.path="direct";
            else{source.direct.reset();source.path="buffered: "+why;}
        }else source.path=config.path==PathMode::Mapped?"mapped: test-selected":"buffered: test-selected";
        source.path.reserve((std::max)(source.path.size(),size_t(64)));
    }
    p.counters.metadata_capacity=sizeof(Impl)+p.sources.capacity()*sizeof(Impl::Source)+p.slots.capacity()*sizeof(Impl::IoSlot)+p.requests.capacity()*sizeof(Impl::Request);
    for(const auto& source:p.sources)p.counters.metadata_capacity=add(p.counters.metadata_capacity,source.view.path.native().capacity()*sizeof(wchar_t)+source.path.capacity());
}
SpanProvider::~SpanProvider(){
    // Correct callers retain the provider until try_close succeeds. If that
    // contract is violated, never run DirectFile's unsafe outstanding close:
    // retain this bounded owner state until process error cleanup instead.
    if(impl_&&!try_close())impl_.release();
}
uint64_t SpanProvider::next_data_tag(uint64_t& counter){if(counter>=UINT64_MAX-1)throw std::overflow_error("data tag sentinel/generation exhausted");return ++counter;}
std::optional<Ticket> SpanProvider::enqueue(const std::vector<Span>& spans,Buffer destination,const measurement::Identity& id,cache::Token lease){
    auto& p=*impl_;require(!p.closed&&!spans.empty()&&destination.data&&destination.capacity,"gather declaration");
    require(!id.request_id.empty(),"caller request identity");
    uint64_t total=0;auto address=reinterpret_cast<uintptr_t>(destination.data);require(destination.capacity<=UINTPTR_MAX-address,"destination overflow");
    for(const auto& slot:p.slots){auto a=reinterpret_cast<uintptr_t>(slot.buffer.data);require(address+destination.capacity<=a||a+slot.buffer.capacity<=address,"destination aliases read buffers");}
    for(const auto& request:p.requests)if(request.used){auto a=reinterpret_cast<uintptr_t>(request.destination.data);require(address+destination.capacity<=a||a+request.destination.capacity<=address,"destination still leased by another request");}
    for(size_t i=0;i<spans.size();++i){const auto& s=spans[i];require(s.source<p.sources.size()&&s.bytes,"source span");const auto& view=p.sources[s.source].view;
        require(s.offset>=view.source_absolute_offset&&s.offset<=add(view.source_absolute_offset,view.bytes)&&s.bytes<=add(view.source_absolute_offset,view.bytes)-s.offset,"logical source bounds");
        require(s.destination<=destination.capacity&&s.bytes<=destination.capacity-s.destination,"gather destination bounds");total=add(total,s.bytes);
        for(size_t j=0;j<i;++j)require(add(spans[j].destination,spans[j].bytes)<=s.destination||add(s.destination,s.bytes)<=spans[j].destination,"overlapping gather destinations");
    }
    for(uint32_t i=0;i<p.requests.size();++i)if(!p.requests[i].used){auto& r=p.requests[i];if(r.generation==UINT64_MAX)throw std::overflow_error("request generation exhausted");
        auto generation=r.generation+1;r=Impl::Request{};r.used=true;r.generation=generation;r.spans=&spans;r.destination=destination;r.identity=&id;r.lease=lease;r.total=total;p.counters.logical_requested=add(p.counters.logical_requested,total);return Ticket{i,generation};}
    return std::nullopt;
}
uint32_t SpanProvider::issue(){
    auto& p=*impl_;require(!p.closed,"closed provider");uint32_t issued=0;
    for(auto& slot:p.slots){
        if(slot.active||slot.quarantined||p.counters.outstanding>=p.config.max_outstanding)continue;
        int chosen=-1;
        for(uint32_t n=0;n<p.requests.size();++n){uint32_t i=(p.next_request+n)%uint32_t(p.requests.size());auto& r=p.requests[i];if(r.used&&!r.cancelled&&!r.error&&r.span<r.spans->size()){chosen=int(i);break;}}
        if(chosen<0)break;
        auto& r=p.requests[chosen];const auto& span=(*r.spans)[r.span];auto& source=p.sources[span.source];
        uint64_t logical=add(span.offset,r.position),physical=logical-source.view.source_absolute_offset;
        bool direct=bool(source.direct);uint64_t a0=direct?physical/4096*4096:physical,skip=physical-a0;
        uint64_t available=p.config.max_outstanding_bytes-p.counters.outstanding_bytes;
        // Credits describe an independent finite window, not a minimum chunk.
        // Direct requests need an aligned physical window including prefix skip.
        uint64_t window=(std::min)(p.config.max_chunk,direct?available/4096*4096:available);
        if(window<=skip)continue;
        uint64_t needed=(std::min)(span.bytes-r.position,window-skip);
        uint64_t length=direct?add(skip+needed,4095)/4096*4096:needed;
        require(length<=slot.buffer.capacity&&length<=UINT32_MAX,"physical read capacity");
        if(length>p.config.max_outstanding_bytes-p.counters.outstanding_bytes)continue;
        uint64_t tag=next_data_tag(p.tag);slot.active=true;slot.sync_ready=false;slot.tag=tag;slot.request=uint32_t(chosen);slot.request_generation=r.generation;slot.source=span.source;slot.a0=a0;slot.skip=skip;slot.needed=needed;slot.requested=length;slot.destination=add(span.destination,r.position);
        ++r.pending;++p.counters.outstanding;p.counters.outstanding_bytes+=length;p.counters.read_requested=add(p.counters.read_requested,length);p.counters.overread_requested=add(p.counters.overread_requested,length-needed);
        p.counters.peak_outstanding=(std::max)(p.counters.peak_outstanding,p.counters.outstanding);p.counters.peak_bytes=(std::max)(p.counters.peak_bytes,p.counters.outstanding_bytes);
        r.position+=needed;if(r.position==span.bytes){++r.span;r.position=0;}p.next_request=(uint32_t(chosen)+1)%uint32_t(p.requests.size());
        if(direct){std::string why;if(!source.direct->submit(a0,slot.buffer.data,uint32_t(length),tag,why)){slot.sync_ready=true;slot.sync_ok=false;slot.sync_bytes=0;}++p.counters.direct_reads;}
        else {
            slot.sync_ready=true;slot.sync_ok=false;slot.sync_bytes=0;
            try{
                if(p.config.path==PathMode::Mapped){
                    SYSTEM_INFO info{};GetSystemInfo(&info);uint64_t granularity=info.dwAllocationGranularity;
                    uint64_t map_offset=physical/granularity*granularity,map_skip=physical-map_offset,map_bytes=add(map_skip,needed);
                    HANDLE mapping=CreateFileMappingW(source.guard,nullptr,PAGE_READONLY,0,0,nullptr);
                    if(!mapping)throw std::runtime_error("mapping creation failed");
                    void* view=MapViewOfFile(mapping,FILE_MAP_READ,DWORD(map_offset>>32),DWORD(map_offset),size_t(map_bytes));
                    bool ok=view&&map_copy(slot.buffer.data,static_cast<uint8_t*>(view)+map_skip,size_t(needed));
                    if(view)UnmapViewOfFile(view);CloseHandle(mapping);if(!ok)throw std::runtime_error("mapped read failed");
                    p.counters.mapped_peak=(std::max)(p.counters.mapped_peak,map_bytes);++p.counters.mapped_reads;
                }else{auto bytes=source.view.read_exact(logical,needed);std::memcpy(slot.buffer.data,bytes.data(),bytes.size());++p.counters.buffered_reads;}
                slot.sync_ok=true;slot.sync_bytes=uint32_t(needed);
            }catch(const std::exception&){slot.sync_ok=false;}
        }
        ++issued;
    }
    return issued;
}
bool SpanProvider::accept_completion(uint64_t tag,uint32_t bytes,bool ok){
    auto& p=*impl_;
    if(tag==strata::platform::DirectFile::WAKE_TAG){if(bytes||!ok){++p.counters.unknown;return false;}++p.counters.control;return false;}
    for(auto& slot:p.slots)if(slot.active&&slot.tag==tag){auto& r=p.requests[slot.request];
        if(r.generation!=slot.request_generation||!r.used||bytes>slot.requested){++p.counters.unknown;p.error(r,"invalid completion generation/length");return false;}
        // A matched backend completion certifies this exact buffer writer has
        // ended. Only then may a direct I/O error use the preserved buffered
        // fallback on that buffer. Outstanding reads in other buffers stay held.
        bool fallback_success=false;uint32_t received_bytes=bytes;
        if(!ok&&p.sources[slot.source].direct&&!r.cancelled&&!r.error&&!slot.quarantined){
            auto& source=p.sources[slot.source];
            try{auto raw=source.view.read_exact(add(source.view.source_absolute_offset,add(slot.a0,slot.skip)),slot.needed);
                std::memcpy(static_cast<uint8_t*>(slot.buffer.data)+slot.skip,raw.data(),raw.size());
                p.counters.received=add(p.counters.received,slot.needed);p.counters.read_requested=add(p.counters.read_requested,slot.needed);++p.counters.buffered_reads;
                source.path="direct + buffered after completed read error";bytes=uint32_t(slot.skip+slot.needed);ok=true;fallback_success=true;
            }catch(const std::exception&){ok=false;}
        }
        bool short_read=bytes<slot.skip+slot.needed||(!fallback_success&&bytes<slot.requested&&add(slot.a0,bytes)!=p.sources[slot.source].view.bytes);
        p.counters.received=add(p.counters.received,received_bytes);
        if(!ok){++p.counters.errors;p.error(r,"read error");}
        else if(short_read){++p.counters.short_reads;p.error(r,"short read");}
        else if(!r.cancelled&&!r.error){std::memcpy(static_cast<uint8_t*>(r.destination.data)+slot.destination,static_cast<uint8_t*>(slot.buffer.data)+slot.skip,size_t(slot.needed));r.completed+=slot.needed;}
        require(r.pending&&p.counters.outstanding&&p.counters.outstanding_bytes>=slot.requested,"completion credit underflow");
        --r.pending;--p.counters.outstanding;p.counters.outstanding_bytes-=slot.requested;slot.active=false;slot.sync_ready=false;p.finish(r);return true;
    }
    ++p.counters.unknown;return false;
}
uint32_t SpanProvider::poll(int timeout_ms){
    auto& p=*impl_;uint32_t count=0;
    for(auto& slot:p.slots)if(slot.active&&slot.sync_ready){auto tag=slot.tag;auto bytes=slot.sync_bytes;auto ok=slot.sync_ok;count+=accept_completion(tag,bytes,ok);}
    bool waited=false;
    for(auto& source:p.sources)if(source.direct){strata::platform::Completion out[64];bool active=false;for(const auto& slot:p.slots)active|=slot.active&&p.sources[slot.source].direct.get()==source.direct.get();int wait=!waited&&active?timeout_ms:0;if(active)waited=true;int n=source.direct->wait(out,64,wait);for(int i=0;i<n;++i)count+=accept_completion(out[i].tag,out[i].bytes,out[i].ok);}
    return count;
}
void SpanProvider::cancel(Ticket t){auto& r=impl_->checked(t);r.cancelled=true;impl_->finish(r);}
bool SpanProvider::done(Ticket t)const{return impl_->checked(t).finished;}
Result SpanProvider::take(Ticket t,const measurement::Identity& current){auto& p=*impl_;auto& r=p.checked(t);require(r.finished,"request has outstanding reads");bool cancelled=r.cancelled||!same(*r.identity,current);bool ok=!cancelled&&!r.error&&r.completed==r.total;
    Result result{ok,cancelled,ok?r.completed:0,r.lease,r.reason};if(ok)p.counters.logical_delivered=add(p.counters.logical_delivered,r.completed);r.used=false;r.identity=nullptr;r.spans=nullptr;return result;}
bool SpanProvider::try_close(){auto& p=*impl_;if(p.counters.outstanding)return false;for(const auto& r:p.requests)if(r.used&&!r.finished)return false;if(p.closed)return true;for(auto& source:p.sources){source.direct.reset();if(source.guard!=INVALID_HANDLE_VALUE){CloseHandle(source.guard);source.guard=INVALID_HANDLE_VALUE;}}p.closed=true;return true;}
void SpanProvider::wake(){for(auto& source:impl_->sources)if(source.direct)source.direct->wake();}
void SpanProvider::mark_drain_failed(){for(auto& slot:impl_->slots)if(slot.active){slot.quarantined=true;auto& r=impl_->requests[slot.request];impl_->error(r,"drain failure; buffer quarantined");}}
Stats SpanProvider::stats()const{return impl_->counters;}
std::vector<std::string> SpanProvider::source_paths()const{std::vector<std::string> paths;for(const auto& source:impl_->sources)paths.push_back(source.path);return paths;}
uint64_t SpanProvider::first_pending_tag()const{for(const auto& slot:impl_->slots)if(slot.active)return slot.tag;return 0;}
}
