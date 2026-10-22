#pragma once
#include "lease_queue.hpp"
#include "../../models/deepseek41/routing_policy.hpp"
#include "../quant/quant.hpp"
#include "../graph/primary_projection.hpp"
#include "../../models/deepseek41/artifact.hpp"
#include <memory>
#include <string>
#include <vector>
namespace strata_ext::cache {
namespace routing=deepseek41::routing;
struct SupplyMatrix { deepseek41::SourceTensor original;uint64_t offset=0,bytes=0;uint32_t type=0;size_t rows=0,k=0;std::string key() const;bool row_tile=false;uint64_t original_matrix=0,output_row_first=0; };
routing::Record routing_record(const SupplyMatrix&)noexcept;
routing::Span routing_span(const routing::Record&,routing::Tier);
routing::Span routing_span(const SupplyMatrix&,routing::Tier);
struct SupplyConfig { size_t device_slots=2,ram_slots=2;uint64_t weight_capacity=0,input_capacity=0,output_capacity=0;int device=0;bool permit_only=false;bool projection_graph=false;std::string projection_graph_abi; };
struct SupplyStage { uintptr_t address=0;uint64_t capacity=0;bool attempted=false;int status=-1,type=-1; };
struct SupplyStats { std::vector<SupplyStage> stages; uint64_t readback_capacity=0,event_not_ready=0,issued_read=0,issued_reads=0,outstanding_reads=0,outstanding_read_bytes=0,weight_read=0,aligned_read=0,weight_h2d=0,input_h2d=0,output_d2h=0,gpu_hits=0,ram_hits=0,ssd_misses=0,device_owned=0,host_owned=0,pinned_subset=0,metadata=0;bool pinned_known=true,pinned_observed=false;int attribute_status=-1; };
struct PrimaryGraphStats { graph::Stats module;uint64_t resident_fill_eager=0,prepare_eager=0,replayed=0,activation_scopes=0; };
enum class SupplyState { Idle, Reading, Dma, Ready, Kernel, Download, Done, Cancelled, Quarantined };
struct SupplyProgress {
 SupplyState consumer=SupplyState::Idle,fill=SupplyState::Idle;
 size_t consumer_slot=0,fill_slot=0;uint64_t consumer_generation=0,fill_generation=0;
 uint32_t consumer_readers=0;bool fill_writer=false;
 uintptr_t consumer_address=0,fill_address=0,consumer_stream=0,producer_stream=0,consumer_event=0,fill_event=0;
 uint64_t issued_read_bytes=0;bool permit_only=false,demand_fill=false;
};
// A value descriptor, not a transferred lease or fill writer. A serialized
// consumer must immediately acquire the actual resident source reader before
// moving the Primary request. Pointer/storage remain owned by PrimarySupply.
struct ReadyPackedDescriptor {
 SupplyMatrix matrix;measurement::Identity identity;
 const uint8_t* data=nullptr;uint64_t bytes=0,capacity=0,request_generation=0;
 int device=-1;void* stream=nullptr;ResidentSlot* resident=nullptr;
 uint64_t owner=0,slot_generation=0;
};
// One serialized owner, one actual input/output pair. Cache entry count follows
// caller capacity, independent of LeaseQueue's 16 buffers / 8 active jobs.
// Ready demand already holds its selected resident lease through launch or
// cancellation; another slot may still be prefetched.
// The owner must drain before destruction. A failed drain retains all storage;
// this fixture adapter never claims driver-fault recovery or thread safety.
struct SupplyIoSnapshot { uint64_t outstanding_reads=0,outstanding_read_bytes=0,issued_reads=0,issued_read=0; };
class PrimarySupply {
public:
    explicit PrimarySupply(SupplyConfig);
    ~PrimarySupply();
    PrimarySupply(const PrimarySupply&)=delete;PrimarySupply& operator=(const PrimarySupply&)=delete;
    bool begin(const SupplyMatrix&,const measurement::Identity&,bool prefetch=false);
    void advance();
    // New Core path: only this operation may issue SSD reads. Each issue uses
    // at most one bounded physical window and returns actual requested bytes.
    uint64_t issue_reads(uint32_t max_submissions,uint64_t max_requested_bytes);
    void poll_io(int timeout_ms=0);
    void poll_device();
    void launch_device(size_t batch,const float* input,uint64_t input_bytes,
      float* output,uint64_t output_bytes,size_t output_stride,void* stream,
      const quant::ProjectionLease& activation_lease,const measurement::Identity* graph_current=nullptr);
    uint64_t begin_graph_activation();
    bool end_graph_activation(uint64_t); // false retains graphs AND original activation storage
    PrimaryGraphStats projection_graph_stats()const;
    void decode_device(float* output,uint64_t output_bytes,void*stream,const quant::ProjectionLease&activation_lease);
    bool take_device(const measurement::Identity& current);
    // Progress the single producer window independently while the one consumer
    // I/O pair/last-use lease remains held. No worker or registry is introduced.
    void advance_fill();
    SupplyState prefetch_state()const;
    bool take_prefetch(const measurement::Identity& current);
    void cancel_prefetch();
    void launch(size_t batch,const std::vector<float>&);
    void download();
    void cancel();
    bool evict_device(size_t);
    void evict_ram();
    bool try_close();
    ReadyPackedDescriptor ready_packed_descriptor()const;
    SupplyState state()const;
    std::vector<float> take(const measurement::Identity& current);
    routing::Snapshot routing_snapshot()const; // serialized metadata only; no HIP/IO/counter mutation
    SupplyStats stats()const;
 SupplyIoSnapshot io_snapshot()const;
    SupplyProgress progress()const;
    void* stream_handle()const;
    uint64_t generation()const;
    uint64_t read_window_capacity()const; // actual retained physical read buffer; not a user/context limit
private:struct Impl;std::unique_ptr<Impl> p_;
};
}
