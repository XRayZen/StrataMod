#pragma once
#include "native_reader.hpp"
#include "lease_queue.hpp"
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace strata_ext::io {
enum class PathMode { PreferDirect, Buffered, Mapped };
struct Buffer { void* data=nullptr;uint64_t capacity=0; };
struct Span { uint32_t source=0;uint64_t offset=0,bytes=0,destination=0; };
struct Config { uint32_t request_slots=2,max_outstanding=2;uint64_t max_outstanding_bytes=32768,max_chunk=16384;PathMode path=PathMode::PreferDirect; };
struct Ticket { uint32_t slot=0;uint64_t generation=0; };
struct Result { bool ok=false,cancelled=false;uint64_t bytes=0;cache::Token caller_lease{};std::string reason; };
struct Stats {
    uint64_t logical_requested=0,logical_delivered=0,read_requested=0,received=0;
    uint64_t control=0,unknown=0,short_reads=0,errors=0,overread_requested=0;
    uint64_t outstanding=0,outstanding_bytes=0,peak_outstanding=0,peak_bytes=0;
    uint64_t buffer_capacity=0,metadata_capacity=0,mapped_peak=0,direct_reads=0,buffered_reads=0,mapped_reads=0;
};
// Non-owning destination/descriptor/Identity/buffer references. Caller retains
// them and this provider through every issued completion or quarantined slot.
// Calls run under the existing owner coordinator/outer lock. This class neither
// replaces request identity nor frees caller buffers. try_close must succeed
// before normal destruction; a failed drain is never converted to buffer reuse.
class SpanProvider {
public:
    SpanProvider(const std::vector<artifact::FixtureView>& sources,const std::vector<Buffer>&,Config);
    ~SpanProvider();
    SpanProvider(const SpanProvider&)=delete;SpanProvider& operator=(const SpanProvider&)=delete;
    std::optional<Ticket> enqueue(const std::vector<Span>&,Buffer destination,const measurement::Identity&,cache::Token caller_lease={});
    uint32_t issue();
    uint32_t poll(int timeout_ms=0);
    // Trusted backend completion adapter: a matched frame certifies its buffer
    // writer has ended. Not an untrusted external-message ingestion API.
    bool accept_completion(uint64_t tag,uint32_t bytes,bool ok);
    void cancel(Ticket);
    bool done(Ticket) const;
    Result take(Ticket,const measurement::Identity& current);
    bool try_close();
    void wake();
    void mark_drain_failed();
    Stats stats() const;
    std::vector<std::string> source_paths() const;
    uint64_t first_pending_tag() const;
    // Used by completion producers and the same boundary negative fixture.
    // UINT64_MAX is DirectFile's reserved WAKE control, never a data tag.
    static uint64_t next_data_tag(uint64_t& counter);
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
