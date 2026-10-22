#pragma once
#include "device_ops.hpp"
#include "../../native/stats/measurement.hpp"
#include <memory>
#include <array>
#include <stdexcept>
#include "engram.hpp"
#include "../../native/cache/primary_supply.hpp"
#include "../../native/cache/row_supply.hpp"
namespace strata_ext::cache {class SecondaryCache;}
namespace strata_ext::deepseek41 {
struct CoreAttentionRole { uint32_t ratio=0,kv_writer=40,index_writer=40; };
CoreAttentionRole attention_role(uint32_t layer);
struct AllocationLife { std::string name;uint64_t begin=0,end=0,bytes=0; };
uint64_t concurrent_peak(const std::vector<AllocationLife>&);
class ExpertDispatch;struct ExpertFrame;
struct CoreConfig {
 int device=0;uint64_t tile_bytes=2*1024*1024,tile_rows=256,active_batch=8;
 // These are caller-sized finite windows, never model/context/output limits.
 bool full_logits=false;DeviceAudit* audit=nullptr;
 cache::SecondaryCache* secondary_cache=nullptr; // optional storage-only provider; owner outlives this Core
 ExpertDispatch* experts=nullptr; // optional expert-only placement; caller retains through Core drain
 DeviceView routing_delta;bool routing_decode=false;std::shared_ptr<routing::Policy> routing_policy;
};
struct CoreMemory {
 uint64_t weights=0,residual_state=0,activations=0,scratch=0,row_output=0,audit=0;
 uint64_t explicit_owned()const;
 // Driver/context and OS physical cache are separately unknown unless measured.
};
struct CoreIoGrant { uint32_t max_outstanding=1;uint64_t max_outstanding_bytes=4096; };
struct CoreIoIssue { uint64_t operations=0,requested_bytes=0; };
// Polls actual owners without issuing, then grants bounded reads in the existing
// demand order. Only a positive actual requested delta advances that order.
CoreIoIssue advance_core_io(cache::PrimarySupply&,cache::RowSupply&,cache::DemandOrder&,
 const CoreIoGrant&,cache::Kind weight_kind=cache::Kind::Expert,int timeout_ms=0);
// Connects the existing resident-weight owner to full-K row-tile math. The
// activation owner and stream remain caller-owned through actual last-use.
// No activation upload/readback is performed by this callback.
class CoreProjection {
 friend class CoreSequence;
 cache::PrimarySupply& weight_;cache::RowSupply* rows_=nullptr;cache::DemandOrder order_;
 uint64_t graph_activation_=0;
 measurement::Identity identity_;CoreIoGrant grant_;cache::SecondaryCache* cache_=nullptr;
public:
 CoreProjection(cache::PrimarySupply&,cache::RowSupply&,measurement::Identity,CoreIoGrant,cache::SecondaryCache* cache=nullptr);
 CoreProjection(cache::PrimarySupply&,cache::RowSupply*,measurement::Identity,CoreIoGrant,cache::SecondaryCache* cache=nullptr);
 CoreProjection(cache::PrimarySupply&,measurement::Identity,CoreIoGrant,cache::SecondaryCache* cache=nullptr); // expert-only secondary, no dummy row owner
 ~CoreProjection();
 CoreProjection(const CoreProjection&)=delete;CoreProjection&operator=(const CoreProjection&)=delete;
 bool retire_graph();
 uint64_t graph_activation()const noexcept{return graph_activation_;}
 void operator()(const SourceTile&,const DeviceView&,const DeviceView&,uint64_t,void*);
 DeviceProject callback();
 // Uses only this instance bound permit/actual byte credits.
 void advance(int timeout_ms=0);
};
struct ExpertWorkspace { DeviceView input_qdq,gate,up,hidden,down_qdq,down_dot; };
// Identical local/secondary expert primitive. Original router and ID-order
// accumulation remain outside; route is applied exactly once inside SwiGLU.
void expert_forward_device(const Artifact&,uint32_t layer,uint32_t expert,
 const DeviceView&input,const DeviceView&route,const DeviceView&down,
 ExpertWorkspace&,const CoreConfig&,void*stream,const DeviceProject&);
struct FfnWorkspace {
 DeviceView input_qdq,logits,scores,corrected,ids,weights,accumulated;
 DeviceView selected_input,selected_route,selected_pairs,gate,up,hidden,down_qdq,down_dot,down_bf16;
};
// Only the selected IDs are returned to the host for finite expert dispatch;
// activations/routes/combine stay on device. Audit writes/downloads are optional.
void ffn_forward_device(const Artifact&,uint32_t layer,const DeviceView&input,
 const DeviceView&image_mask,const DeviceView&bias,const DeviceView&bias_vl,
 const DeviceView&output,FfnWorkspace&,const CoreConfig&,void*stream,const DeviceProject&,std::vector<uint32_t>* actual_dispatch_ids=nullptr,const ExpertFrame*frame=nullptr);
// Explicit lookups are derived from the current request's History hashes. Each
// borrowed 256-element row is consumed on Core's stream before cursor reuse.
void gather_engram_device(cache::PrimarySupply&,cache::RowSupply&,cache::DemandOrder&,
 const std::vector<cache::RowLookup>&,const measurement::Identity&,const CoreIoGrant&,
 const DeviceView&embedding,void*stream);
struct CoreConstant { SourceTensor original;DeviceView value; };
struct MhcWorkspace { DeviceView inverse,dot,mixed,pre,post,comb;MhcSplitAuditViews* audit=nullptr; };
struct BlockWorkspace { MhcWorkspace attention,ffn;DeviceView collapsed,norm_inverse,normalized,subblock,after_attention; };
struct BlockConstants { CoreConstant attention_scale,attention_base,attention_norm,ffn_scale,ffn_base,ffn_norm; };
// This is the real staggered block composition. A subblock callback must invoke
// its actual source-bound operator; injected callbacks qualify only a fixture,
// never a real attention/FFN connection. The normal path retains device state.
using CoreSubblock=std::function<void(const DeviceView&,const DeviceView&,void*)>;
void core_block_device(const Artifact&,uint32_t layer,const DeviceView&residual,
 const DeviceView&incoming_pre,const DeviceView&output,BlockWorkspace&,const BlockConstants&,
 const CoreConfig&,void*stream,const DeviceProject&,const CoreSubblock&attention,const CoreSubblock&ffn);
struct SwaState { DeviceView ring;uint64_t position=0,epoch=0;bool valid=true; };
struct SwaWorkspace {
 DeviceView input_qdq,qa_dot,qa_bf16,qr,qr_qdq,q_dot,q_bf16,q_rotated;
 DeviceView kv_dot,kv_bf16,kv_normalized,kv_rotated,kv_qdq;
 DeviceView positions,head_positions,frequencies,ids,error,attended,inverse,output_qdq;
 DeviceView group_input,group_dot,group_bf16,out_qdq,out_dot;
};
struct SwaConstants { CoreConstant q_norm,kv_norm,sink; };
// Actual ratio0 single-token append operator. Prefill may stream tokens through
// this causal path; compressed/shared attention uses its separate state path.
// This helper is not a qualification of the compressed 20->24 connection.
void attention_swa_device(const Artifact&,uint32_t layer,const DeviceView&input,
 const DeviceView&output,SwaState&,SwaWorkspace&,const SwaConstants&,uint64_t epoch,
 const CoreConfig&,void*stream,const DeviceProject&);
// One caller-coordinated device owner. Named allocations expose actual owned
// bytes; driver/context/allocator overhead remain separate unknown quantities.
class CoreStorage {
 friend class CoreSequence;
 struct Impl;std::unique_ptr<Impl> p_;
 bool optional_workspace(uint64_t,const std::function<void(const DeviceView&)>&);
public:
 explicit CoreStorage(int device);~CoreStorage();
 CoreStorage(const CoreStorage&)=delete;CoreStorage&operator=(const CoreStorage&)=delete;
 DeviceView allocate(const std::string&name,uint64_t rows,uint64_t columns,DeviceScalar);
 void upload(const DeviceView&,const void*host,uint64_t bytes);
 void download(const DeviceView&,void*host,uint64_t bytes); // requested outputs/audit only
 void drain();void* stream()const;const quant::ProjectionLease& lease()const;
 uint64_t explicit_owned_bytes()const;uint64_t upload_bytes()const;uint64_t download_bytes()const;
};
struct CompressionState {
 uint32_t writer=2,ratio=2;uint64_t position=0,published_rows=0,epoch=0;bool valid=true;
 DeviceView pending_kv,pending_score,cache;
};
struct CompressionWorkspace { DeviceView kv_dot,gate_dot,pooled,pooled_bf16,latent,position,frequencies,rotated,quantized; };
// Produce the normalized pre-RoPE latent first, so the actual indexer consumes
// that latent before publication of post-RoPE block16/E4M3 compressed KV.
bool compression_latent_device(const Artifact&,const DeviceView&input,CompressionState&,
 CompressionWorkspace&,const CoreConstant&norm,uint64_t epoch,const CoreConfig&,void*stream,const DeviceProject&);
void compression_publish_device(CompressionState&,CompressionWorkspace&,uint64_t epoch,void*stream);
struct IndexKeyState { uint32_t writer=2,ratio=2;uint64_t rows=0,epoch=0;bool valid=true;DeviceView keys; };
struct CandidateState { uint64_t position=0,rows=0,epoch=0;bool valid=false;DeviceView scores; };
struct IndexWorkspace {
 DeviceView key_dot,key_bf16,key_norm,key_padded,key_rotated_padded,key_rotated,key_quantized;
 DeviceView query_dot,query_bf16,query_padded,query_rotated_padded,query_rotated,query_quantized;
 DeviceView query_input_qdq,weight_dot,weight_bf16,weight_scaled;
 DeviceView position,query_positions,frequencies,scores,visible,mask,selected,blocks,work,error;
};
void index_key_device(const Artifact&,IndexKeyState&,const DeviceView&pre_rope_latent,
 IndexWorkspace&,const CoreConstant&norm,uint64_t group_position,uint64_t epoch,
 const CoreConfig&,void*stream,const DeviceProject&);
// Actual current-query index selection. Source20 publishes candidates before
// source24/28/32/36 consume them; their own learned scores still rank candidates.
void index_query_device(const Artifact&,uint32_t layer,const DeviceView&input,const DeviceView&qr,
 const IndexKeyState&,CandidateState&,IndexWorkspace&,uint64_t position,uint64_t epoch,
 uint64_t window_payload_rows,const CoreConfig&,void*stream,const DeviceProject&);
struct SharedAttentionFrame { DeviceView compressed,selected;uint64_t position=0,epoch=0;bool has_compressed=false; };
// This callback performs the actual source's latent/index/publish operations;
// it never fabricates cache contents or qualifies an injected fixture as Core.
using SharedAttentionUpdate=std::function<SharedAttentionFrame(const DeviceView&qr,void*stream)>;
void attention_step_device(const Artifact&,uint32_t layer,const DeviceView&input,
 const DeviceView&output,SwaState&,SwaWorkspace&,const SwaConstants&,uint64_t epoch,
 bool compressed_rope,const SharedAttentionUpdate&,const CoreConfig&,void*stream,const DeviceProject&);
// One sequence of the actual 40-layer trunk. Caller selects its context storage
// capacity; finite operator waves do not reduce the model/context/output API.
// Original-source qualification is the existing T05/T10 caller responsibility.
struct CoreOutput;
// Optional host control at completed-token boundaries. Caller owns callback and
// captures for this synchronous call. False/exception invalidates this sequence;
// caller must drain/drop it before constructing the next request sequence.
// Real finite-operation notifications may repeat the same completed-token count.
using PrefillControl=std::function<bool(uint64_t processed,uint64_t total)>;
struct CorePrefillPreparation {uint32_t max_batch=1;std::vector<std::string> required_f32_names;};
enum class CorePrefillReason {Unprepared,SerialCompatibility,SerialBatchOne,OptionalReady,OptionalOutOfMemory};
struct CorePrefillPreparationResult {uint32_t requested_capacity=1,selected_capacity=1;uint64_t context_capacity=0,workspace_payload_bytes=0,constant_miss_bytes=0;CorePrefillReason reason=CorePrefillReason::Unprepared;};
struct CoreRuntimeStats { uint64_t storage_device_owned=0,constant_source_bytes=0,storage_upload_bytes=0,requested_output_or_fixture_download_bytes=0;std::array<std::array<uint64_t,6>,40> route_union{};std::array<uint64_t,40> routed_tokens{};uint64_t route_metadata_bytes=0;std::array<uint64_t,40> state_positions{};std::array<uint64_t,4> compressed_rows{},key_rows{};CorePrefillPreparationResult prefill_preparation; };
struct CoreLayerCapture {std::vector<float> residual,pre;uint32_t first=0,end=0;uint64_t position=0;};
// Only the owning Core/partition can prepare or publish this local transaction.
// Allocating copies/tokens are prepared before any request identity is changed.
// Intentional prepublication refusal, distinct from an actual owner drain error.
class RequestAdoptionRefused final:public std::runtime_error {
public:explicit RequestAdoptionRefused(const char*message):std::runtime_error(message){}
};
class CoreRequestBinding {
 friend class CoreSequence;friend class CorePartition;
 measurement::Identity core,projection;
 std::shared_ptr<const uint8_t> instance;
};
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
// Synchronous qualification-only borrow. Sink copies/serializes before return;
// it must not retain pointers, reenter Core, adopt, reset or mutate state.
struct FixtureStateRecord {
 const char*kind=nullptr;uint32_t writer=0,ratio=0;
 uint64_t position=0,epoch=0,rows=0;bool valid=false;
 DeviceView value;const void*host=nullptr;uint64_t host_bytes=0;
 const measurement::Identity*identity=nullptr;uint32_t first=0,end=0;
};
using FixtureStateVisitor=std::function<void(const FixtureStateRecord&,void*stream)>;
#endif
// Opt-in per-call taps. The opaque token identifies the Core instance, not an
// allocation lease. Residual views are borrowed only during capture().
class CoreTapBinding {
 friend class CoreSequence;
 CoreTapBinding()=default;
 measurement::Identity identity_;
 std::shared_ptr<const uint8_t> instance_;
 uint64_t position_=0;
 int device_=-1;
public:
 CoreTapBinding(const CoreTapBinding&)=default;
 CoreTapBinding&operator=(const CoreTapBinding&)=default;
};
struct CoreTapFrame {
 measurement::Identity identity;
 std::shared_ptr<const uint8_t> instance;
 uint64_t position=0;
 uint32_t target_layer=0,capture_after_layer=0;
 uint32_t hc=4,hidden=5120;
 uint32_t partition_first=0,partition_end=40;uint64_t activation_generation=0;
 DeviceView residual;
 void* stream=nullptr;
};
struct CoreTapToken {
 measurement::Identity identity;
 std::shared_ptr<const uint8_t> instance;
 uint64_t position=0,cursor_after=0;
 void* stream=nullptr;
};
struct CoreTapSink {
 virtual ~CoreTapSink()=default;
 virtual void capture(const CoreTapFrame&)=0;
 // Core producer writes have drained. Consumer must drain its own last-use
 // before returning, so the next token may reuse its destination safely.
 virtual void processed(const CoreTapToken&)=0;
};
// Capture-only helper: no allocation, upload or download. Caller validates its
// expected identity/position/order and retains destination through consumer drain.
// Enqueues HC mean into the layer's 5120-column slice of [1,15360], same stream.
void core_tap_mean_device(const CoreTapFrame&,const DeviceView& destination);
class CoreSequence {
 friend class CorePartition;
 struct Impl;std::unique_ptr<Impl> p_;
 CoreSequence() noexcept;
 void validate_tap(const CoreTapBinding&,uint64_t)const;
 void request_preflight()const;
 CoreRequestBinding prepare_request(const measurement::Identity&,uint64_t position);
 void adopt_request(CoreRequestBinding&&) noexcept;
public:
 CoreSequence(const Artifact&,const engram::Config&,cache::PrimarySupply&,cache::RowSupply&,
   measurement::Identity,CoreConfig,uint64_t context_capacity);
 ~CoreSequence();
 void attach_prefill_preparation(CorePrefillPreparation);
 void routing_policy(std::shared_ptr<routing::Policy>);
 bool retire_projection_graph(); // call before explicit Core destruction; false retains storage
 CoreSequence(const CoreSequence&)=delete;CoreSequence&operator=(const CoreSequence&)=delete;
 CoreTapBinding prepare_tap(uint64_t expected_position);
 std::vector<float> step_tapped(uint32_t raw_token,uint64_t position,const CoreTapBinding&,CoreTapSink&);
 CoreOutput prefill_tapped(const std::vector<uint32_t>& raw_tokens,uint64_t position,
   const std::vector<uint8_t>& image_mask,const CoreTapBinding&,CoreTapSink&,const PrefillControl& control={});
 std::vector<float> step(uint32_t raw_token,uint64_t position,bool image_token=false);
 // Explicit qualification-only capture. Uses the SAME actual connected block
 // implementation as step; normal step/prefill never downloads these payloads.
 CoreLayerCapture audit_layers(uint32_t first,uint32_t end,uint32_t raw_token,uint64_t position,
   const std::vector<float>& residual,const std::vector<float>& incoming_pre,bool image_token=false);
 CoreOutput prefill(const std::vector<uint32_t>&raw_tokens,uint64_t position,const std::vector<uint8_t>&image_mask={},const PrefillControl&control={});
 // Healthy request adoption preserves mathematical state; cancel is separate.
 void continue_request(const measurement::Identity&,uint64_t expected_position);
 // Mathematical validity only; never proves shared-owner quiescence.
 bool request_valid()const noexcept;
 void quiesce();void invalidate_and_drain();
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 void fixture_visit_state(const FixtureStateVisitor&);
#endif
 uint64_t position()const;uint64_t explicit_device_owned()const;CoreRuntimeStats runtime_stats()const;
};
struct CoreOutput { std::vector<float> logits;uint64_t rows=0,vocabulary=0,processed=0;bool cancelled=false; };
// Specific contiguous-layer reuse of the same CoreSequence implementation.
// Boundary views are borrowed until retire_boundary; source storage/streams
// remain alive through actual CopyTask/consumer last use. No new executor.
struct PartitionSpec { uint32_t first=0,end=40; };
enum class PartitionDataKind { Compressed,IndexKeys,Selection,Candidates };
struct PartitionShared {
 PartitionDataKind kind=PartitionDataKind::Compressed;
 uint32_t writer=0,compressor=0,ratio=0;
 uint64_t position=0,epoch=0,published_rows=0;bool valid=false;
 DeviceView value;
};
struct PartitionBoundary {
 std::shared_ptr<const uint8_t> instance;measurement::Identity identity;uint64_t generation=0,position=0;uint32_t raw_token=0,next_layer=0;bool image=false;
 DeviceView residual,pre,logits;std::vector<PartitionShared> shared;
 void*stream=nullptr;
};
struct CorePartitionTapBinding {
 measurement::Identity identity;std::shared_ptr<const uint8_t> instance;
 PartitionSpec range;uint64_t position=0,activation_generation=0,owner_generation=0;
 int device=-1;void*stream=nullptr;const quant::ProjectionLease*owner=nullptr;
};
class CorePartition {
 friend class LayerSplit;
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 friend struct T36PairFixture;
#endif
 std::unique_ptr<CoreSequence> sequence_;PartitionSpec spec_;
 uint64_t generation_=0;bool borrowed_=false;
 std::shared_ptr<const uint8_t> instance_=std::make_shared<const uint8_t>(0);
 const CorePartition*upstream_=nullptr;PartitionBoundary current_;
 void request_preflight()const;void quiesce_request();bool request_valid()const;
 CoreRequestBinding prepare_request(const measurement::Identity&,uint64_t position);
 void adopt_request(CoreRequestBinding&&) noexcept;
public:
 CorePartition(const Artifact&,const engram::Config&,cache::PrimarySupply&,cache::RowSupply*,measurement::Identity,CoreConfig,uint64_t context,PartitionSpec,const CorePartition*upstream=nullptr);
 ~CorePartition();
 void routing_policy(std::shared_ptr<routing::Policy>);
 void routing_decode(bool)noexcept;
 CorePartition(const CorePartition&)=delete;CorePartition&operator=(const CorePartition&)=delete;
 // targets validates all metadata/geometry before any upload/mutation. The
 // returned descriptor views use destination-owned allocations only.
 PartitionBoundary targets(const PartitionBoundary&)const;
 PartitionBoundary advance(uint32_t raw_token,uint64_t position,bool image,const PartitionBoundary* incoming=nullptr,bool emit_logits=true,const std::function<void()>&safe_operation={});
 // advance returns after actual producer drain. Caller retains both owners
 // through all cross-device CopyTask consumer returns before retiring here;
 // synchronizing this owner stream alone is not proof of a peer consumer.
 void retire_boundary(uint64_t generation,void*actual_last_use_stream);
 std::vector<float> download_logits(const PartitionBoundary&);
 CorePartitionTapBinding prepare_partition_tap(uint64_t expected_position)const;
 PartitionBoundary advance_tapped(uint32_t,uint64_t,bool,const PartitionBoundary*,bool,const std::function<void()>&,const CorePartitionTapBinding&,CoreTapSink&);
 bool retire_projection_graph();
 void invalidate_and_drain();void drain();
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 void fixture_visit_state(const FixtureStateVisitor&);
#endif
 uint64_t position()const;uint64_t explicit_device_owned()const;CoreRuntimeStats runtime_stats()const;
};

// Output-row projection retains original rank/expert coordinates. Scatter is
// batch-major and handles the last ragged row tile without K splitting.
void tiled_projection(const SourceTensor&,uint64_t matrix,const DeviceView& input,
 const DeviceView& output,uint64_t batch,const CoreConfig&,void* stream,const DeviceProject&);
}
