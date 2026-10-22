#pragma once
#include "device_ops.hpp"
#include "core.hpp"
namespace strata_ext::deepseek41 {
// Fixed1017 Engram gate formula: model.py 350-365. q_weight*k_weight is
// the GGUF F32 fused gate tensor [5120,4]. Key AND residual RMS are per HC.
struct EngramAuditViews { DeviceView inverse_h,inverse_key,dot,signed_sqrt;
 // Optional pre-transcendental FP32 audit taps. Null views are not written.
 DeviceView sum_h{},sum_key{},weighted_dot{}; };
// kv is native-wkv projection after BF16 cast: B x(4*5120+5120), not raw
// embedding rows. Caller performs the independently qualified FP8 input QDQ
// and original-bound Q8 projection. No allocations/transfers/synchronization.
void engram_gate_device(const DeviceView& residual,const DeviceView& kv,
 const DeviceView& fused_gate,const DeviceView& token_mask,const DeviceView& gates,
 const DeviceView& output,void* stream,EngramAuditViews* audit=nullptr);
struct EngramWorkspace {
 DeviceView activation_qdq,kv_dot,kv_bf16,gates;
 DeviceView* qdq_scales=nullptr;DeviceView* qdq_codes=nullptr;
 EngramAuditViews* gate_audit=nullptr;
};
// Bounded full forward after the real row gather. Embedding is Bx6144, with
// 24 native MXFP8 rows decoded and BF16-cast in head order. Caller/source owner
// supplies the original-bound wkv tile projection; no host intermediates.
void engram_forward_device(const DeviceView&residual,const DeviceView&embedding,
 const SourceTensor&wkv,const DeviceView&fused_gate,const DeviceView&token_mask,
 const DeviceView&output,EngramWorkspace&,const CoreConfig&,void* stream,const DeviceProject&);
}
