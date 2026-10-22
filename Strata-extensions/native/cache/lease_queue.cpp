#include "lease_queue.hpp"
#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace strata_ext::cache {
namespace {
bool same(const measurement::Identity& a,const measurement::Identity& b) {
    return a.request_id==b.request_id && a.epoch==b.epoch && a.phase==b.phase &&
           a.fixture_sha256==b.fixture_sha256 && a.asset_sha256==b.asset_sha256 && a.bundle_sha256==b.bundle_sha256;
}
void require(bool value,const char* message) {if(!value)throw std::invalid_argument(message);}
uint64_t add(uint64_t a,uint64_t b) {if(b>UINT64_MAX-a)throw std::overflow_error("lease bytes overflow");return a+b;}
}
void DemandOrder::issued(Kind kind) {
    require(kind==Kind::Expert||kind==Kind::Row||kind==Kind::Prefetch,"issued demand kind");
    if(kind!=Kind::Prefetch)next_=kind==Kind::Expert?Kind::Row:Kind::Expert;
}
std::optional<ResidentLease> reserve_fill(ResidentSlot& s,uint64_t owner,uint64_t bytes) {
    require(owner && s.owner==owner && s.address && s.capacity && bytes && bytes<=s.capacity,"resident declaration/owner");
    if(s.writer||s.readers||s.quarantined)return std::nullopt;
    if(s.generation==UINT64_MAX)throw std::overflow_error("resident generation exhausted");
    ++s.generation;s.writer=true;s.valid=false;return ResidentLease{&s,s.generation,owner,true,true};
}
std::optional<ResidentLease> borrow_resident(ResidentSlot& s,uint64_t owner) {
    require(owner && s.owner==owner,"resident owner");
    if(!s.valid||s.writer||s.quarantined)return std::nullopt;
    if(s.readers==UINT32_MAX)throw std::overflow_error("resident readers exhausted");
    ++s.readers;return ResidentLease{&s,s.generation,owner,false,true};
}
namespace {
void resident_checked(const ResidentLease& l,uint64_t owner) {
    require(l.active&&l.slot&&l.owner==owner&&l.slot->owner==owner&&l.slot->generation==l.generation,"resident stale/duplicate/foreign lease");
    require(l.writer?l.slot->writer:l.slot->readers!=0,"resident lease state");
}
}
bool complete_resident(ResidentLease& l,uint64_t owner,bool success,bool publish) {
    resident_checked(l,owner);
    if(!success){quarantine_resident(l,owner);return false;}
    auto& s=*l.slot;
    if(s.quarantined)return false; // unprovable drain retains owner capacity
    if(l.writer){s.writer=false;s.valid=publish;}else --s.readers;
    l.active=false;return publish;
}
void quarantine_resident(ResidentLease& l,uint64_t owner) {
    resident_checked(l,owner);l.slot->quarantined=true;l.slot->valid=false;
}
LeaseQueue::LeaseQueue(uint64_t owner,const Buffer* buffers,uint32_t count,Config config)
 :owner_(owner),count_(count),config_(config) {
    require(owner && buffers && count && count<=max_buffers,"owner/buffer declaration");
    require(config.queue_jobs && config.queue_jobs<=max_jobs && config.queue_bytes && config.max_chunk,"queue declaration");
    for(uint32_t i=0;i<count;++i) {
        auto b=buffers[i];require(b.address && b.capacity && b.capacity<=UINTPTR_MAX-b.address,"buffer range");
        require(b.pool==Pool::Source||b.pool==Pool::Stage||b.pool==Pool::Device,"buffer pool");
        for(uint32_t j=0;j<i;++j) {
            const auto& a=slots_[j].buffer;
            // Host pools share one address space; device and host may use UVA
            // values without making them interchangeable ownership ranges.
            bool shared_space=(a.pool==Pool::Device)==(b.pool==Pool::Device);
            require(!shared_space || a.address+a.capacity<=b.address || b.address+b.capacity<=a.address,"overlapping owner ranges");
        }
        slots_[i].buffer=b;
    }
}
bool LeaseQueue::valid(Token t) const {
    return t.owner==owner_ && t.index<config_.queue_jobs && jobs_[t.index].state!=State::Empty && jobs_[t.index].generation==t.generation;
}
const LeaseQueue::Job& LeaseQueue::checked(Token t) const {require(valid(t),"stale/duplicate/foreign token");return jobs_[t.index];}
LeaseQueue::Job& LeaseQueue::checked(Token t) {return const_cast<Job&>(static_cast<const LeaseQueue*>(this)->checked(t));}
std::optional<Token> LeaseQueue::enqueue(const measurement::Identity& id,Kind kind,uint64_t bytes) {
    for(const auto* h:{&id.fixture_sha256,&id.asset_sha256,&id.bundle_sha256})require(h->size()==64&&h->find_first_not_of("0123456789abcdef")==std::string::npos,"caller measurement identity hash");
    require(!id.request_id.empty()&&id.phase>=measurement::Phase::Startup&&id.phase<=measurement::Phase::DSpark,"caller request identity/phase");
    require(kind==Kind::Expert||kind==Kind::Row||kind==Kind::Prefetch,"job kind");
    require(bytes && bytes<=config_.max_chunk,"declared chunk size");
    for(unsigned p=0;p<3;++p) {
        bool fits=false;for(uint32_t i=0;i<count_;++i)fits|=unsigned(slots_[i].buffer.pool)==p&&!slots_[i].quarantined&&slots_[i].buffer.capacity>=bytes;
        if(!fits)return std::nullopt;
    }
    if(bytes>config_.queue_bytes || bytes_>config_.queue_bytes-bytes)return std::nullopt;
    if(kind==Kind::Prefetch) {
        if(config_.queue_jobs<=config_.demand_reserved || live_jobs()>=config_.queue_jobs-config_.demand_reserved)return std::nullopt;
        if(config_.queue_bytes<config_.max_chunk || bytes_+bytes>config_.queue_bytes-config_.max_chunk)return std::nullopt;
    }
    for(uint32_t i=0;i<config_.queue_jobs;++i)if(jobs_[i].state==State::Empty) {
        auto& j=jobs_[i];if(j.generation==UINT64_MAX || sequence_==UINT64_MAX)throw std::overflow_error("generation exhausted");
        uint64_t generation=j.generation+1;j=Job{};j.generation=generation;j.identity=&id;j.kind=kind;j.bytes=bytes;j.sequence=++sequence_;j.state=State::Queued;
        bytes_+=bytes;return Token{i,generation,owner_};
    }
    return std::nullopt;
}
bool LeaseQueue::reserve(Job& job,uintptr_t existing_stage_choice) {
    std::array<int,3> chosen{{-1,-1,-1}};
    for(unsigned p=0;p<3;++p) {
        unsigned eligible=0;
        for(uint32_t i=0;i<count_;++i) {auto& s=slots_[i];
            if(unsigned(s.buffer.pool)==p && !s.busy && !s.quarantined && s.buffer.capacity>=job.bytes && s.generation!=UINT64_MAX) {
                ++eligible;if(chosen[p]<0 && (p!=unsigned(Pool::Stage)||!existing_stage_choice||s.buffer.address==existing_stage_choice))chosen[p]=int(i);
            }
        }
        if(chosen[p]<0 || (job.kind==Kind::Prefetch && eligible<=config_.demand_reserved))return false;
    }
    // Reservation is all-or-none. Failure above leaves no partial reservation.
    for(unsigned p=0;p<3;++p) {auto& s=slots_[chosen[p]];s.busy=true;++s.generation;job.slot_generation[p]=s.generation;}
    job.slots=chosen;job.state=State::Reading;return true;
}
std::optional<Token> LeaseQueue::issue(uintptr_t existing_stage_choice) {
    for(Kind kind:demand_order_.candidates()) {
        int first=-1;
        for(uint32_t i=0;i<config_.queue_jobs;++i)if(jobs_[i].state==State::Queued && jobs_[i].kind==kind && (first<0||jobs_[i].sequence<jobs_[first].sequence))first=int(i);
        if(first>=0 && reserve(jobs_[first],existing_stage_choice)) {
            demand_order_.issued(kind);
            return Token{uint32_t(first),jobs_[first].generation,owner_};
        }
    }
    return std::nullopt;
}
View LeaseQueue::view(Token t) const {
    const auto& j=checked(t);require(j.state!=State::Queued,"job has no reserved buffers");
    return {slots_[j.slots[0]].buffer,slots_[j.slots[1]].buffer,slots_[j.slots[2]].buffer,j.slot_generation};
}
void LeaseQueue::stage_copied(Token t) {
    auto& j=checked(t);require(j.state==State::Reading,"source copy order");
    auto& source=slots_[j.slots[0]];
    if(!source.buffer.registered_source)source.busy=false;
    j.state=State::Filled;if(j.cancelled)release(j);
}
void LeaseQueue::begin_dma(Token t,uint64_t event_owner) {auto& j=checked(t);require(event_owner==owner_&&j.state==State::Filled,"DMA owner/order");j.state=State::Dma;}
void LeaseQueue::release(Job& j) {
    for(unsigned p=0;p<3;++p)if(j.slots[p]>=0) {auto& s=slots_[j.slots[p]];if(s.generation==j.slot_generation[p])s.busy=false;}
    require(bytes_>=j.bytes,"credit underflow");bytes_-=j.bytes;j.state=State::Empty;j.identity=nullptr;
}
bool LeaseQueue::complete_dma(Token t,uint64_t event_owner,bool success,const measurement::Identity& current) {
    if(!valid(t))return false;
    auto& j=checked(t);require(event_owner==owner_&&j.state==State::Dma,"DMA completion owner/order");
    if(!success){quarantine(t);return false;}
    for(unsigned p:{0u,1u}) {auto& s=slots_[j.slots[p]];if(s.generation==j.slot_generation[p])s.busy=false;}
    if(j.cancelled||!same(*j.identity,current)){release(j);return false;}
    j.state=State::Ready;return true;
}
void LeaseQueue::begin_kernel(Token t,uint64_t event_owner) {auto& j=checked(t);require(event_owner==owner_&&j.state==State::Ready,"kernel before fill/owner");j.state=State::Kernel;}
bool LeaseQueue::complete_kernel(Token t,uint64_t event_owner,bool success,const measurement::Identity& current) {
    if(!valid(t))return false;
    auto& j=checked(t);require(event_owner==owner_&&j.state==State::Kernel,"kernel completion owner/order");
    if(!success){quarantine(t);return false;}
    bool adopt=!j.cancelled&&same(*j.identity,current);release(j);return adopt;
}
void LeaseQueue::cancel(const measurement::Identity& id) {
    for(auto& j:jobs_)if(j.state!=State::Empty && same(*j.identity,id)) {
        j.cancelled=true;if(j.state==State::Queued)release(j);
        else if(j.state==State::Filled||j.state==State::Ready)release(j);
    }
}
void LeaseQueue::quarantine(Token t) {
    auto& j=checked(t);require(j.state!=State::Queued,"unissued reservation can be cancelled");
    for(unsigned p=0;p<3;++p) {auto& s=slots_[j.slots[p]];if(s.generation==j.slot_generation[p]&&s.busy)s.quarantined=true;}
    j.state=State::Quarantined;
}
State LeaseQueue::state(Token t) const {return valid(t)?jobs_[t.index].state:State::Empty;}
uint32_t LeaseQueue::live_jobs() const {uint32_t n=0;for(const auto& j:jobs_)n+=j.state!=State::Empty;return n;}
uint32_t LeaseQueue::quarantined_buffers() const {uint32_t n=0;for(const auto& s:slots_)n+=s.quarantined;return n;}
uint64_t LeaseQueue::leased_bytes() const {uint64_t n=0;for(const auto& s:slots_)if(s.busy)n=add(n,s.buffer.capacity);return n;}
measurement::LedgerSnapshot LeaseQueue::snapshot(const measurement::Identity& id,uint64_t host,uint64_t pinned,const char* device,uint64_t device_bytes) const {
    measurement::LedgerSnapshot s{};s.identity=id;s.owned_host=add(host,sizeof(*this));s.pinned_subset=pinned;s.devices.push_back({device,device_bytes});s.queue_bytes=bytes_;s.lease_bytes=leased_bytes();measurement::owned_total(s);return s;
}
}
