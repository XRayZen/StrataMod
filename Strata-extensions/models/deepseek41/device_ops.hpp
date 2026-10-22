#pragma once
#include "artifact.hpp"
#include "../../native/quant/quant.hpp"
#include <functional>
namespace strata_ext::deepseek41 {
// Borrowed device views are operational descriptors, not process authorities.
enum class DeviceScalar { Float32, Bfloat16, Bfloat16InFloat32, UInt8, UInt32, Int32, Int64 };
struct DeviceView {
 void* data=nullptr;uint64_t bytes=0,rows=0,columns=0;DeviceScalar scalar=DeviceScalar::Float32;
 int device=-1;const quant::ProjectionLease* owner=nullptr;uint64_t generation=0;
};
uint64_t scalar_bytes(DeviceScalar);
void validate_device_view(const DeviceView&,int expected_device);
void check_device_stream(void*,int expected_device);
DeviceView checked_device_view(void*,uint64_t bytes,uint64_t rows,uint64_t columns,DeviceScalar,int device,const quant::ProjectionLease&);
struct SourceTile {
 SourceTensor original;uint64_t matrix=0,row_first=0,row_count=0;
 uint64_t absolute_offset=0,bytes=0,k=0;uint32_t type=0;
};
SourceTile source_tile(const SourceTensor&,uint64_t matrix,uint64_t first,uint64_t count);
std::vector<SourceTile> row_tiles(const SourceTensor&,uint64_t matrix,uint64_t byte_budget,uint64_t row_budget);
std::vector<uint32_t> batch_waves(uint64_t batch,uint32_t maximum=8);
// Each callback consumes the original-bound FULL-K output-row tile. Completion
// and lease ownership remain on the supplied stream; no implicit host readback.
using DeviceProject=std::function<void(const SourceTile&,const DeviceView&,const DeviceView&,uint64_t,void*)>;
struct DeviceAudit {
 virtual ~DeviceAudit()=default;
 virtual void stage(const std::string&,const DeviceView&,void* stream)=0;
 virtual void frame(uint64_t position,uint32_t layer) {}
};
struct SwiGluAuditViews { DeviceView clamp_gate,clamp_up,silu; };
void ffn_bf16_device(const DeviceView&,const DeviceView&,void* stream);
void ffn_qdq_device(const DeviceView&,const DeviceView&,void* stream,DeviceView* scales=nullptr,DeviceView* codes=nullptr);
void ffn_router_device(const DeviceView&logits,const DeviceView&bias,const DeviceView&bias_vl,
 const DeviceView&mask,const DeviceView&scores,const DeviceView&corrected,
 const DeviceView&ids,const DeviceView&weights,void* stream);
void ffn_router_biased_device(const DeviceView&logits,const DeviceView&bias,const DeviceView&bias_vl,
 const DeviceView&mask,const DeviceView&delta,const DeviceView&scores,const DeviceView&corrected,
 const DeviceView&ids,const DeviceView&weights,void* stream);
void ffn_swiglu_device(const DeviceView&gate,const DeviceView&up,const DeviceView* route,
 const DeviceView&output,void* stream,SwiGluAuditViews* audit=nullptr);
void ffn_add_device(const DeviceView&,const DeviceView&,const DeviceView&,void* stream);
struct MhcSplitAuditViews { DeviceView logits,centered,exponent,all_rows,all_columns; };
void mhc_rms_device(const DeviceView&,const DeviceView& inverse,void* stream);
void mhc_mix_device(const DeviceView& dot,const DeviceView& inverse,const DeviceView& out,void* stream);
void mhc_split_device(const DeviceView& mixes,const DeviceView&scale,const DeviceView&base,
 const DeviceView&pre,const DeviceView&post,const DeviceView&comb,void* stream,MhcSplitAuditViews* audit=nullptr);
void mhc_pre_device(const DeviceView& residual,const DeviceView& pre,const DeviceView&out,void* stream);
void mhc_post_device(const DeviceView& subblock,const DeviceView& residual,const DeviceView&post,const DeviceView&comb,const DeviceView&out,void* stream);
void mhc_norm_device(const DeviceView& collapsed,const DeviceView& inverse,const DeviceView&weight,const DeviceView&out,void* stream);
void kv_quantize_device(const DeviceView&,const DeviceView& decoded,bool compressed_fp4,void* stream,
 DeviceView* scales=nullptr,DeviceView* codes=nullptr,DeviceView* packed=nullptr);
void kv_norm_device(const DeviceView&,const DeviceView&weight,const DeviceView&out,void* stream,DeviceView* inverse=nullptr);
void kv_pool_device(const DeviceView&kv,const DeviceView&score,const DeviceView&out,void* stream);
void kv_frequency_device(const DeviceView&out,bool compressed,void* stream);
void kv_rope_device(const DeviceView&,const DeviceView&positions,const DeviceView&frequencies,const DeviceView&out,bool inverse,void* stream);
struct IndexAuditViews {DeviceView raw,dot,relu,weighted,reduced;};
struct OnlineAuditViews {DeviceView score,maximum,alpha,probability,prob_bf16,sum,accumulator,denominator;};
void attention_bf16_device(const DeviceView&,const DeviceView&,float scale,void* stream);
void attention_rms_device(const DeviceView&,const DeviceView&weight,const DeviceView&out,void* stream,DeviceView* inverse=nullptr);
void attention_fp4_device(const DeviceView&,const DeviceView&out,void* stream,DeviceView* scales=nullptr,DeviceView* codes=nullptr);
void attention_index_device(const DeviceView&q,const DeviceView&keys,const DeviceView&weight,const DeviceView&score,void* stream,IndexAuditViews* audit=nullptr);
void attention_select_device(const DeviceView&source,const DeviceView&scores,const DeviceView&visible,
 const DeviceView&mask,const DeviceView&selected,const DeviceView&blocks,const DeviceView&work,
 const DeviceView&error,int writer,int offset,void* stream);
void attention_online_device(const DeviceView&q,const DeviceView&kv,const DeviceView&ids,const DeviceView&sink,
 const DeviceView&out,const DeviceView&error,void* stream,OnlineAuditViews* audit=nullptr);
void attention_online_split_device(const DeviceView&q,const DeviceView&window,const DeviceView&compressed,
 const DeviceView&ids,const DeviceView&sink,const DeviceView&out,const DeviceView&error,void*stream,
 OnlineAuditViews* audit=nullptr);
// Null audit is the normal path. Implementations never create hidden trace copies.
void audit_stage(DeviceAudit*,const std::string&,const DeviceView&,void* stream);
}
