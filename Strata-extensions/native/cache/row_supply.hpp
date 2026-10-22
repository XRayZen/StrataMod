#pragma once
#include "lease_queue.hpp"
#include "../../models/deepseek41/artifact.hpp"
#include <memory>
#include <vector>
namespace strata_ext::cache {
struct RowLookup { uint32_t layer=0,head=0;uint64_t row=0; };
struct RowBinding { deepseek41::Slice logical;artifact::FixtureView physical; };
// Shard-level logical source views; T05/T10 qualification remains caller-owned.
struct RowSourceView { deepseek41::SourceFile source;artifact::FixtureView full_file; };
struct RowSourceViews { std::vector<RowSourceView> files;explicit RowSourceViews(std::vector<RowSourceView> v):files(std::move(v)){} };
struct RowDeviceOutput {
 Token request{};RowLookup lookup{};uint64_t cursor=0,owner_generation=0;
 const float* fp32=nullptr;const uint16_t* bf16=nullptr;int device=-1;
};
struct RowConfig { size_t device_slots=8,ram_slots=16,request_slots=8,wave_requests=8;int device=0; };
struct RowResult { bool cancelled=false;std::vector<float> fp32;std::vector<uint16_t> bf16; };
enum class RowState { Queued,Ready,Kernel,Download,Done,Cancelled };
struct RowStats {
 uint64_t logical_read=0,requested_read=0,received=0,weight_h2d=0,index_h2d=0,output_d2h=0,control_d2h=0;
 uint64_t gpu_hits=0,ram_hits=0,ssd_misses=0,dedup=0,issued=0,issued_requested=0,outstanding_reads=0,outstanding_read_bytes=0;
 uint64_t device_owned=0,host_payload=0,stage_owned=0,pinned_subset=0,metadata_capacity=0;
 uint64_t observed_metadata_peak=0,observed_host_payload_peak=0,active_io_wrapper_metadata=0;
 uint64_t binding_heap=0,identity_heap=0,lookup_capacity=0,key_capacity=0;
 bool pinned_known=true,pinned_observed=false;std::vector<std::array<int64_t,4>> stages;
};
struct RowProgress { size_t slot=0;uint64_t generation=0;uint32_t readers=0;bool writer=false;uintptr_t address=0; };
// Serialized caller coordinator. Artifact stays immutable/alive through this
// owner, including quarantine. Bindings, request lookup/identity, and each shared
// fill's view/span/operational identity are owned value copies. Taking a cancelled
// waiter never destroys another waiter's in-flight source descriptor.
// Config describes finite active windows/cache capacities, not context limits.
class RowSupply {
public:
 RowSupply(RowConfig,const deepseek41::Artifact&,std::vector<RowBinding>);
 RowSupply(RowConfig,const deepseek41::Artifact&,RowSourceViews);
 // One current row only. Borrowed output is retained through return's actual
 // same-device stream event. Normal host download remains available otherwise.
 RowDeviceOutput borrow_device_output(Token);
 void return_device_output(Token,const RowDeviceOutput&,void* last_use_stream);
 ~RowSupply();
 RowSupply(const RowSupply&)=delete;RowSupply& operator=(const RowSupply&)=delete;
 std::optional<Token> enqueue(const std::vector<RowLookup>&,const measurement::Identity&);
 uint64_t issue_reads(uint32_t max_submissions,uint64_t max_requested_bytes);
 void poll_io(int timeout_ms=0); // never issues a new read
 void poll_device();             // never issues a new read
 RowState state(Token)const;
 void launch_gather(Token);
 void download(Token);
 RowResult take(Token,const measurement::Identity& current);
 void cancel(Token);
 std::vector<Token> cancel_all();
 bool evict(const RowLookup&);
 void evict_ram();
 bool try_close();
 RowStats stats()const;
 RowProgress progress(Token)const;
 // Readonly serialized-owner predicate; never progresses or cancels a request.
 bool request_idle()const;
 bool fill_pending()const;
 bool fill_dma()const;
 static std::array<uint64_t,6> metadata_layout(); // host ABI sizes, no HIP call
private:struct Impl;std::unique_ptr<Impl> p_;
};
}
