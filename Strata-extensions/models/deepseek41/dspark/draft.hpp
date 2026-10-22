#pragma once
#include <array>
#include <cstdint>
#include <optional>
#include <functional>
#include <memory>
#include <vector>
#include <stdexcept>
#include "draft_asset.hpp"
#include "target_adapter.hpp"
namespace strata_ext::deepseek41 { class Artifact; struct SamplingOptions; struct DeviceView; struct BlockWorkspace; struct FfnWorkspace; enum class DeviceScalar; }
namespace strata_ext::dspark::t38 {
using strata_ext::deepseek41::DeviceView;
// Pure preflight; reject invalid F16 alignment before any HIP API or cast.
inline void validate_f16_alignment(const void* pointer) {
 if(!pointer || reinterpret_cast<uintptr_t>(pointer)%alignof(uint16_t))
  throw std::invalid_argument("F16 source alignment");
}

// One fixed allocation per stage/width, with a separate contiguous logical prefix.
struct NoiseIndexExtent {uint64_t capacity=0,valid=0,capacity_bytes=0,valid_bytes=0;};
inline NoiseIndexExtent noise_index_extent(uint64_t position,uint64_t width){
 if(!width||width>UINT64_MAX/8-128)throw std::invalid_argument("noise index capacity overflow");
 uint64_t prefix=position>=127?128:position+1;
 return {128+width,prefix+width,(128+width)*8,(prefix+width)*8};
}
template<class View> View noise_index_logical(View storage,uint64_t position,uint64_t width){
 auto e=noise_index_extent(position,width);
 if(storage.rows!=1||storage.columns!=e.capacity||storage.bytes<e.capacity_bytes)
  throw std::invalid_argument("noise index storage capacity");
 storage.columns=e.valid;storage.bytes=e.valid_bytes;return storage;
}

// Runtime query failure invalidates; healthy argument/device mismatch does not.
// Query callbacks return the native status code (HIP success is0).
template<class CurrentQuery,class StreamQuery>
void target_stream_preflight(bool&valid,void* stream,int expected,CurrentQuery&&current_query,StreamQuery&&stream_query){
 if(!valid)throw std::invalid_argument("invalid target supply");
 if(!stream||expected<0)throw std::invalid_argument("target explicit stream/device");
 int current=-1,stream_device=-1,status=0;
 try{status=current_query(current);}catch(...){valid=false;throw;}
 if(status){valid=false;throw std::runtime_error("target current device query status "+std::to_string(status));}
 try{status=stream_query(stream,stream_device);}catch(...){valid=false;throw;}
 if(status){valid=false;throw std::runtime_error("target stream device query status "+std::to_string(status));}
 if(current!=expected||stream_device!=expected)throw std::invalid_argument("target current/stream device mismatch");
}

// Public target descriptors are validated structurally; receipt authority is caller-owned.
struct TargetMatrixExtent {uint64_t k=0,rows=0,row_bytes=0,offset=0,bytes=0,file_bytes=0;};
struct TargetMatrixTile {uint64_t offset=0,bytes=0;};
inline void validate_target_matrix(const TargetMatrixExtent&m,uint64_t native_row_bytes,uint64_t credit){
 if(m.k!=5120||m.rows!=129280||!native_row_bytes||m.row_bytes!=native_row_bytes||
    m.row_bytes>UINT64_MAX/m.rows||m.bytes!=m.rows*m.row_bytes||
    m.offset>m.file_bytes||m.bytes>m.file_bytes-m.offset||credit<m.row_bytes||credit>SIZE_MAX)
  throw std::invalid_argument("target matrix native geometry/range/credit");
}
inline TargetMatrixTile target_matrix_tile(const TargetMatrixExtent&m,uint64_t first,uint64_t count,uint64_t credit){
 validate_target_matrix(m,m.row_bytes,credit);
 if(!count||first>=m.rows||count>m.rows-first||count>credit/m.row_bytes)
  throw std::invalid_argument("target bounded row tile");
 return {m.offset+first*m.row_bytes,count*m.row_bytes};
}
struct RequestBinding;
// Caller supplies an accepted T03/T05 receipt-bound Artifact and retains originals.
// Private Core cache is not used; all borrowed views live through actual same-stream last use.
class TargetWeightSupply {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 TargetWeightSupply(const strata_ext::deepseek41::Artifact&,const RequestBinding&,int device,uint64_t packed_credit);
 ~TargetWeightSupply();TargetWeightSupply(const TargetWeightSupply&)=delete;
 void* stream() const;
 void set_control(ContinueWork) noexcept;
 void embedding(const std::vector<uint32_t>& original_ids,const DeviceView& hc_residual,const RequestBinding& current);
 void head(const DeviceView& normalized,const DeviceView& logits,const RequestBinding& current);
 void drain();uint64_t explicit_owned_bytes() const;uint64_t source_read_bytes() const;
};

struct DraftState {
 uint64_t owner=0,epoch=0,cursor=0;bool valid=true;
 std::array<std::vector<uint8_t>,3> ring;
 std::array<uint64_t,3> stage_cursor{};
 std::vector<float> main_features;
 std::optional<uint32_t> processed_prior;
};
// CPU-owned mathematical checkpoint only; no Core snapshot qualification.
class DraftTransaction {
 DraftState& state_;DraftState saved_;bool closed_=false;
public:
 explicit DraftTransaction(DraftState&);
 ~DraftTransaction() noexcept;
 DraftTransaction(const DraftTransaction&)=delete;
 void restore();void commit(const DraftState& processed);
};
// HIP primitive sources only until GPU Q qualification; no three-stage network claim.
// All views are caller-owned and retained through actual last use on stream.
void hc_mean_device(const DeviceView& residual,const DeviceView& mean,void* stream);
void f16_projection_device(const Span& source,const DeviceView& packed,
 const DeviceView& input,const DeviceView& output,void* stream,uint64_t output_stride=0);
void confidence_device(const DeviceView& hidden,const DeviceView& markov,
 const Span& source,const DeviceView& packed_weights,const DeviceView& output,void* stream);
void router128_device(const DeviceView& logits,const DeviceView& learned_bias,
 const DeviceView& scores,const DeviceView& corrected,const DeviceView& ids,const DeviceView& weights,void* stream);
void noise_input_ids_device(const DeviceView& ids,uint32_t previous_id,void* stream);
void seed_main_kv_device(const DeviceView& key,const DeviceView& ring,uint64_t position,void* stream);
void noise_attention_device(const DeviceView& queries,const DeviceView& prefix_ring,
 const DeviceView& noise_keys,const DeviceView& sinks,const DeviceView& output,
 const DeviceView& indices,const DeviceView& error,uint64_t start_position,void* stream);
// Finite source-bound provider. One weight window, no whole draft asset residency.
// Host transfer destinations/sources live with the provider, through positive drain.
struct DraftHostScratch {
 std::vector<uint32_t> ids,pairs;std::vector<float> logits;
 float raw_confidence=0;uint32_t attention_error=0;bool valid=true,pending=false;
};
class DraftWeights {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 DraftWeights(const std::string& path,const Asset&,int device,uint64_t byte_credit);
 ~DraftWeights();
 DraftWeights(const DraftWeights&)=delete;
 void* stream() const;
 void set_control(ContinueWork) noexcept;
 DraftHostScratch& host_scratch();void prepare_host(uint64_t width);
 // Borrowed packed window: consume on provider stream before the next load/project.
 DeviceView load_packed(const Span&);
 DeviceView constant(const Span&); // F32 only, owned through provider drain/destruction
 void project(const Span&,const DeviceView& input,const DeviceView& output,uint64_t output_stride=0);
 DeviceView workspace(const std::string&,uint64_t rows,uint64_t columns,strata_ext::deepseek41::DeviceScalar);
 void upload(const DeviceView&,const void*,uint64_t bytes);
 void drain();uint64_t explicit_owned_bytes() const;
};
using DraftProjection=std::function<void(const Span&,const DeviceView&,const DeviceView&,void*)>;
using DraftConstantLookup=std::function<DeviceView(const Span&)>;
using DraftSubblock=std::function<void(const DeviceView&,const DeviceView&,void*)>;
void draft_block_device(const Asset&,uint32_t stage,const DeviceView& residual,
 const DeviceView& incoming_pre,const DeviceView& output,
 strata_ext::deepseek41::BlockWorkspace&,const DraftProjection&,const DraftConstantLookup&,
 const DraftSubblock& attention,const DraftSubblock& ffn,void* stream);
// Composes three actual blocks only when actual attention/FFN callbacks are supplied.
// No injected-callback fixture qualifies a real three-stage network.
void draft_three_blocks_device(const Asset&,DeviceView residual_a,DeviceView residual_b,
 const DeviceView& incoming_pre,strata_ext::deepseek41::BlockWorkspace&,
 const DraftProjection&,const DraftConstantLookup&,
 const std::array<DraftSubblock,3>& attention,const std::array<DraftSubblock,3>& ffn,void* stream
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
 ,const std::function<void(uint32_t,const DeviceView&,void*)>* stage_completed=nullptr
#endif
 );
void draft_ffn_device(const Asset&,uint32_t stage,const DeviceView& input,const DeviceView& output,
 strata_ext::deepseek41::FfnWorkspace&,const DraftProjection&,const DraftConstantLookup&,void* stream,DraftHostScratch* host=nullptr);
struct DraftDeviceMetadata {
 uint64_t owner=0,epoch=0,cursor=0;std::array<uint64_t,3> stage_cursor{};
 std::optional<uint32_t> processed_prior;bool valid=true;
};
#ifdef STRATA_T28_CONSTRUCTION_TEST
using FixtureSeedObserver=std::function<void(uint64_t,const RequestBinding&,
 const DraftDeviceMetadata&,const DeviceView&,const DeviceView&,
 const std::array<DeviceView,3>&,void*)>;
#endif
#ifdef STRATA_T38_GLOBAL_FIXTURE
// Mathematical checkpoint payload only: derived main is not valid after restore
// until record_processed/propose has recomputed it. No pointers may escape.
using FixtureMathVisitor=std::function<void(const RequestBinding&,const DraftDeviceMetadata&,
 const DeviceView& features,const std::array<DeviceView,3>& rings,void*)>;
#endif
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
enum class FixtureProposalField {Stage0Residual,Stage1Residual,Stage2Residual,
 TailCollapsed,HeadNormalized,HeadPreMarkov};
using FixtureProposalObserver=std::function<void(FixtureProposalField,
 const RequestBinding&,uint64_t,const DeviceView&,void*)>;
#endif
// Extend the existing query classification to the checkpoint's shared state.
// Healthy preflight rejection leaves both fields; runtime query failure closes it.
template<class CurrentQuery,class StreamQuery>
void checkpoint_restore_stream_preflight(DraftDeviceMetadata& actual,bool&closed,
 void* stream,int device,CurrentQuery&&current_query,StreamQuery&&stream_query){
 try{target_stream_preflight(actual.valid,stream,device,current_query,stream_query);}
 catch(...){if(!actual.valid)closed=true;throw;}
}
// Caller completes all identity/view preflight first. Any operation failure after
// this boundary invalidates the actual state and permanently closes this snapshot.
// The same helper is exercised with CPU fault callbacks; no device math claim.
template<class ProducerDrain,class CopyOne,class SnapshotDrain>
void restore_checkpoint_operations(DraftDeviceMetadata& actual,
 const DraftDeviceMetadata& saved,bool& closed,ProducerDrain&& producer_drain,
 CopyOne&& copy_one,SnapshotDrain&& snapshot_drain) {
 if(closed)throw std::invalid_argument("closed device checkpoint");
 actual.valid=false;
 try {
  producer_drain();
  for(unsigned i=0;i<4;++i)copy_one(i);
  snapshot_drain();
 } catch(...) {closed=true;throw;}
 actual=saved; // Publish valid metadata only after every copy and drain succeeded.
}
// Explicit mathematical checkpoint of3rings+main feature tail. Primary same-device only.
// Caller retains all source owners/leases and uses one actual owner stream.
class DraftDeviceCheckpoint {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 DraftDeviceCheckpoint(const DraftDeviceMetadata&,const std::array<const DeviceView*,4>&,
                       void* actual_owner_stream);
 ~DraftDeviceCheckpoint();
 DraftDeviceCheckpoint(const DraftDeviceCheckpoint&)=delete;
 void restore(DraftDeviceMetadata&,const std::array<const DeviceView*,4>& current,void* actual_owner_stream);
 void commit(const DraftDeviceMetadata&,const std::array<const DeviceView*,4>& current,void* actual_owner_stream);
 uint64_t explicit_owned_bytes() const;
};
// Source-bound draft-only main/tail/Markov operators, not shared target head supply.
void draft_main_features_device(const Asset&,const std::array<const DeviceView*,3>& means,
 const DeviceView& main_hidden,DraftWeights&);
void draft_tail_device(const Asset&,const DeviceView& residual,const DeviceView& pre,
 const DeviceView& collapsed,const DeviceView& normalized,DraftWeights&);
// Adds sequential previous-original-ID Markov bias to one supplied F32 head row.
// raw confidence uses the unnormalized weighted HC collapse, not head-normalized hidden.
void draft_markov_device(const Asset&,uint32_t previous_original_id,const DeviceView& logits,
 const DeviceView& collapsed,const DeviceView& raw_confidence,DraftWeights&);
class NamespaceRng;
struct TapProof;
struct DraftProposal {std::vector<uint32_t> ids;std::vector<std::vector<double>> q;std::vector<float> raw_confidence;bool seed_only=false;};
// Actual source-bound draft operator composition; real Core capture/request actor remain external.
class DraftNetwork {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 DraftNetwork(const std::string& draft_path,const Asset&,const strata_ext::deepseek41::Artifact&,
              const RequestBinding&,int device,uint64_t draft_credit,uint64_t target_credit);
 ~DraftNetwork();DraftNetwork(const DraftNetwork&)=delete;
#ifdef STRATA_T28_CONSTRUCTION_TEST
 void set_fixture_seed_observer(uint64_t selected_position,FixtureSeedObserver);
#ifdef STRATA_T38_GLOBAL_FIXTURE
 void set_fixture_seed_observer(const std::array<uint64_t,5>& selected_positions,FixtureSeedObserver);
 void fixture_visit_math(const FixtureMathVisitor&);
#endif
#endif
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
 void set_fixture_proposal_observer(FixtureProposalObserver);
#endif
 void record_processed(uint32_t original_id,uint64_t position,const RequestBinding&,
   const std::array<TapProof,3>&,const std::array<const DeviceView*,3>& means,void* means_producer_stream);
 void record_processed(uint32_t,uint64_t,const RequestBinding&,const std::array<TapProof,3>&,const std::array<const DeviceView*,3>&,void*,const ContinueWork&);
 DraftProposal propose(uint64_t width,const strata_ext::deepseek41::SamplingOptions&,
   const std::vector<uint32_t>& processed_history,NamespaceRng&);
 DraftProposal propose(uint64_t,const strata_ext::deepseek41::SamplingOptions&,const std::vector<uint32_t>&,NamespaceRng&,const ContinueWork&);
 void drain();void invalidate_and_drain();
 void begin_checkpoint();void restore_checkpoint();void commit_checkpoint();
 // Allocation/constant upload only: make normal width residency visible before cache budgeting.
 void prepare_workspace(uint64_t width);
 uint64_t processed_cursor() const;uint64_t explicit_owned_bytes() const;
};
// Explicit no-activation-QDQ candidate. Native weight types/BF16 casts/RoPE preserved.
// Includes no FP8 activation/KV quantization call; numerical policy awaits Main review.
void draft_attention_no_qdq_device(const Asset&,uint32_t stage,const DeviceView& input,
 const DeviceView& output,const DeviceView& prefix_ring,DraftWeights&,uint64_t start_position);
void draft_seed_main_no_qdq_device(const Asset&,uint32_t stage,const DeviceView& main_hidden,
 const DeviceView& prefix_ring,DraftWeights&,uint64_t position);
}





