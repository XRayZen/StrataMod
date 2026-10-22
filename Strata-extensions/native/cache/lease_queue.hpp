#pragma once
#include "measurement.hpp"
#include <array>
#include <cstdint>
#include <optional>
#include <exception>

namespace strata_ext::cache {
// This is non-owning state attached to one existing owner instance. Caller keeps
// buffers, event/stream handles and immutable Identity alive through outstanding
// AND quarantined leases. Destruction of this sidecar never frees those owners.
// Calls are serialized by the existing owner coordinator/outer owner lock.
// This class alone has no thread-safety qualification; worker/consumer joining
// to that existing synchronization belongs to T17/T18, not a new worker system.
enum class Pool { Source, Stage, Device };
enum class Kind { Expert, Row, Prefetch };
// Ordering only: a caller advances the turn after a real successful issue.
// Zero-byte/denied candidates do not consume a turn or an ownership lease.
class DemandOrder {
public:
    std::array<Kind,3> candidates() const {return {next_,next_==Kind::Expert?Kind::Row:Kind::Expert,Kind::Prefetch};}
    void issued(Kind);
private:
    Kind next_=Kind::Expert;
};
static_assert(sizeof(DemandOrder)==sizeof(Kind)&&alignof(DemandOrder)==alignof(Kind),"ordering retains sidecar layout");
enum class State { Empty, Queued, Reading, Filled, Dma, Ready, Kernel, Quarantined };
struct Buffer { Pool pool; uintptr_t address; uint64_t capacity; bool registered_source=false; };
struct Token { uint32_t index=0; uint64_t generation=0,owner=0; };
struct View { Buffer source,stage,device; std::array<uint64_t,3> slot_generation; };
struct Config { uint32_t queue_jobs=8; uint64_t queue_bytes=524288,max_chunk=65536;uint32_t demand_reserved=1; };
// Resident descriptors belong to the caller's cache array; they are NOT entries
// in the fixed active-window buffers/jobs below. Serialized owner coordinator.
// Owner retains storage through readers/writer/quarantine, including late events.
struct ResidentSlot {
    uintptr_t address=0;uint64_t capacity=0,owner=0,generation=0;
    uint32_t readers=0;bool writer=false,valid=false,quarantined=false;
};
struct ResidentLease {
    ResidentSlot* slot=nullptr;uint64_t generation=0,owner=0;bool writer=false,active=false;
    ResidentLease()=default;
    ResidentLease(ResidentSlot* s,uint64_t g,uint64_t o,bool w,bool a):slot(s),generation(g),owner(o),writer(w),active(a){}
    ResidentLease(const ResidentLease&)=delete;ResidentLease& operator=(const ResidentLease&)=delete;
    ResidentLease(ResidentLease&& other) noexcept { *this=static_cast<ResidentLease&&>(other); }
    ResidentLease& operator=(ResidentLease&& other) noexcept {
        // Owner only moves into an inactive handle; never silently drop a lease.
        if(active)std::terminate();
        slot=other.slot;generation=other.generation;owner=other.owner;writer=other.writer;active=other.active;other.active=false;return *this;
    }
};
std::optional<ResidentLease> reserve_fill(ResidentSlot&,uint64_t owner,uint64_t bytes);
std::optional<ResidentLease> borrow_resident(ResidentSlot&,uint64_t owner);
// Completion must be the caller's matching event, never an inferred time delay.
// A cancelled fill drains without publishing; late reader completion still frees
// its ORIGINAL generation lease and cannot publish for a new request.
bool complete_resident(ResidentLease&,uint64_t owner,bool success,bool publish=true);
void quarantine_resident(ResidentLease&,uint64_t owner);
class LeaseQueue {
public:
    LeaseQueue(uint64_t owner,const Buffer* buffers,uint32_t count,Config config={});
    std::optional<Token> enqueue(const measurement::Identity&,Kind,uint64_t bytes);
    std::optional<Token> issue(uintptr_t existing_stage_choice=0);
    View view(Token) const;
    void stage_copied(Token);
    void begin_dma(Token,uint64_t event_owner);
    bool complete_dma(Token,uint64_t event_owner,bool success,const measurement::Identity& current);
    void begin_kernel(Token,uint64_t event_owner);
    bool complete_kernel(Token,uint64_t event_owner,bool success,const measurement::Identity& current);
    void cancel(const measurement::Identity&);
    void quarantine(Token);
    State state(Token) const;
    uint64_t queued_bytes() const {return bytes_;}
    uint32_t live_jobs() const;
    uint32_t quarantined_buffers() const;
    uint64_t leased_bytes() const;
    measurement::LedgerSnapshot snapshot(const measurement::Identity&,uint64_t owned_host,uint64_t pinned_subset,
                                          const char* device_identity,uint64_t owned_device) const;
    static constexpr uint32_t max_buffers=16,max_jobs=8;
private:
    struct Slot { Buffer buffer{};uint64_t generation=0;bool busy=false,quarantined=false; };
    struct Job {
        const measurement::Identity* identity=nullptr;
        uint64_t generation=0,bytes=0,sequence=0;
        Kind kind=Kind::Expert;State state=State::Empty;bool cancelled=false;
        std::array<int,3> slots{{-1,-1,-1}};
        std::array<uint64_t,3> slot_generation{};
    };
    Job& checked(Token);const Job& checked(Token) const;
    bool valid(Token) const;
    void release(Job&);
    bool reserve(Job&,uintptr_t existing_stage_choice);
    uint64_t owner_,bytes_=0,sequence_=0;uint32_t count_;DemandOrder demand_order_;Config config_;
    std::array<Slot,max_buffers> slots_{};
    std::array<Job,max_jobs> jobs_{};
};
}
