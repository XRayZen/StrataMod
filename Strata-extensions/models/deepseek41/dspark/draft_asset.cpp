#include "draft_asset.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <map>
#include <stdexcept>
namespace strata_ext::dspark::t38 {
namespace {
void need(bool x,const char*m){if(!x)throw std::invalid_argument(m);}
uint64_t add(uint64_t a,uint64_t b){need(a<=UINT64_MAX-b,"asset offset overflow");return a+b;}
uint64_t mul(uint64_t a,uint64_t b){need(!b||a<=UINT64_MAX/b,"asset size overflow");return a*b;}
struct Reader {
 const std::vector<uint8_t>&raw;size_t at=0;
 uint64_t integer(unsigned n){need(n<=8&&at<=raw.size()&&n<=raw.size()-at,"short GGUF header");uint64_t v=0;for(unsigned i=0;i<n;++i)v|=uint64_t(raw[at++])<<(8*i);return v;}
 std::string string(){auto n=integer(8);need(n<=65536&&at<=raw.size()&&n<=raw.size()-at,"GGUF string range");std::string s(reinterpret_cast<const char*>(raw.data()+at),size_t(n));at+=size_t(n);need(s.find('\0')==std::string::npos,"embedded NUL");return s;}
};
struct Meta {uint32_t type;std::string text;double number;uint32_t array_type;std::vector<double> array;};
double number(Reader&r,uint32_t t){
 switch(t){case 0:return double(r.integer(1));case 1:return double(int8_t(r.integer(1)));case 2:return double(r.integer(2));case 3:return double(int16_t(r.integer(2)));case 4:return double(r.integer(4));case 5:return double(int32_t(r.integer(4)));case 6:{uint32_t n=uint32_t(r.integer(4));float f;std::memcpy(&f,&n,4);need(std::isfinite(f),"nonfinite metadata");return f;}case 7:{auto v=r.integer(1);need(v<=1,"GGUF bool");return double(v);}default:throw std::invalid_argument("unsupported fixed metadata type");}
}
Meta metadata(Reader&r,uint32_t t){Meta m{t,"",0,0,{}};if(t==8)m.text=r.string();else if(t==9){m.array_type=uint32_t(r.integer(4));auto n=r.integer(8);need(n<=128,"metadata array bound");for(uint64_t i=0;i<n;++i)m.array.push_back(number(r,m.array_type));}else m.number=number(r,t);return m;}
const std::map<std::string,Meta>& expected_metadata(){static const std::map<std::string,Meta> result={
{"general.architecture",Meta{8,"deepseek41-dflash-draft",0,0,{}}},
{"general.name",Meta{8,"deepseek_v41-dspark-draft",0,0,{}}},
{"deepseek41-dflash-draft.block_count",Meta{4,"",3.0,0,{}}},
{"deepseek41-dflash-draft.embedding_length",Meta{4,"",5120.0,0,{}}},
{"deepseek41-dflash-draft.vocab_size",Meta{4,"",129280.0,0,{}}},
{"deepseek41-dflash-draft.attention.head_count",Meta{4,"",64.0,0,{}}},
{"deepseek41-dflash-draft.attention.head_count_kv",Meta{4,"",1.0,0,{}}},
{"deepseek41-dflash-draft.attention.key_length",Meta{4,"",512.0,0,{}}},
{"deepseek41-dflash-draft.attention.value_length",Meta{4,"",512.0,0,{}}},
{"deepseek41-dflash-draft.rope.dimension_count",Meta{4,"",64.0,0,{}}},
{"deepseek41-dflash-draft.rope.freq_base",Meta{6,"",10000.0,0,{}}},
{"deepseek41-dflash-draft.attention.q_lora_rank",Meta{4,"",1280.0,0,{}}},
{"deepseek41-dflash-draft.attention.output_lora_rank",Meta{4,"",1024.0,0,{}}},
{"deepseek41-dflash-draft.attention.output_group_count",Meta{4,"",8.0,0,{}}},
{"deepseek41-dflash-draft.attention.sliding_window",Meta{4,"",128.0,0,{}}},
{"deepseek41-dflash-draft.attention.layer_norm_rms_epsilon",Meta{6,"",9.999999682655225e-21,0,{}}},
{"deepseek41-dflash-draft.expert_count",Meta{4,"",128.0,0,{}}},
{"deepseek41-dflash-draft.expert_used_count",Meta{4,"",3.0,0,{}}},
{"deepseek41-dflash-draft.expert_shared_count",Meta{4,"",1.0,0,{}}},
{"deepseek41-dflash-draft.expert_feed_forward_length",Meta{4,"",2304.0,0,{}}},
{"deepseek41-dflash-draft.hash_layer_count",Meta{4,"",0.0,0,{}}},
{"deepseek41-dflash-draft.expert_weights_scale",Meta{6,"",1.5,0,{}}},
{"deepseek41-dflash-draft.expert_gating_func",Meta{8,"sqrtsoftplus",0,0,{}}},
{"deepseek41-dflash-draft.swiglu_clamp_exp",Meta{6,"",10.0,0,{}}},
{"deepseek41-dflash-draft.hyper_connection.count",Meta{4,"",4.0,0,{}}},
{"deepseek41-dflash-draft.hyper_connection.epsilon",Meta{6,"",9.999999974752427e-07,0,{}}},
{"deepseek41-dflash-draft.hyper_connection.sinkhorn_iterations",Meta{4,"",20.0,0,{}}},
{"deepseek41-dflash-draft.dflash.n_target_layers",Meta{4,"",3.0,0,{}}},
{"deepseek41-dflash-draft.dflash.block_size",Meta{4,"",5.0,0,{}}},
{"deepseek41-dflash-draft.dflash.mask_token_id",Meta{4,"",128799.0,0,{}}},
{"deepseek41-dflash-draft.dflash.target_layer_ids",Meta{9,"",0,5,{37,38,39}}},
{"deepseek41-dflash-draft.dflash.capture_layer_ids",Meta{9,"",0,5,{36,37,38}}},
{"deepseek41-dflash-draft.dflash.head_hc_enabled",Meta{4,"",0.0,0,{}}},
{"deepseek41-dflash-draft.dflash.dspark.enabled",Meta{4,"",1.0,0,{}}},
{"deepseek41-dflash-draft.dflash.dspark.markov_rank",Meta{4,"",256.0,0,{}}},
{"deepseek41-dflash-draft.dflash.dspark.vocab_size",Meta{4,"",129280.0,0,{}}},
{"deepseek41-dflash-draft.dflash.dspark.confidence_dim",Meta{4,"",5376.0,0,{}}},
{"deepseek41-dflash-draft.dflash.dspark.confidence.enabled",Meta{4,"",1.0,0,{}}}
};return result;}
const std::vector<Tensor>& expected_tensors(){static const std::vector<Tensor> result={
Tensor{"blk.0.attn_norm.weight",0,{5120},7296ull,20480ull,20480ull},
Tensor{"blk.0.attn_q_a.weight",8,{5120,1280},27776ull,6963200ull,5440ull},
Tensor{"blk.0.attn_q_a_norm.weight",0,{1280},6990976ull,5120ull,5120ull},
Tensor{"blk.0.attn_q_b.weight",8,{1280,32768},6996096ull,44564480ull,1360ull},
Tensor{"blk.0.attn_kv.weight",8,{5120,512},51560576ull,2785280ull,5440ull},
Tensor{"blk.0.attn_kv_a_norm.weight",0,{512},54345856ull,2048ull,2048ull},
Tensor{"blk.0.attn_sinks.weight",0,{64},54347904ull,256ull,256ull},
Tensor{"blk.0.attn_output_a.weight",8,{4096,8192},54348160ull,35651584ull,4352ull},
Tensor{"blk.0.attn_output_b.weight",8,{8192,5120},89999744ull,44564480ull,8704ull},
Tensor{"blk.0.hc_attn_fn.weight",1,{20480,24},134564224ull,983040ull,40960ull},
Tensor{"blk.0.hc_attn_scale.weight",0,{3},135547264ull,12ull,12ull},
Tensor{"blk.0.hc_attn_base.weight",0,{24},135547296ull,96ull,96ull},
Tensor{"blk.0.ffn_norm.weight",0,{5120},135547392ull,20480ull,20480ull},
Tensor{"blk.0.ffn_gate_inp.weight",0,{5120,128},135567872ull,2621440ull,20480ull},
Tensor{"blk.0.exp_probs_b.bias",0,{128},138189312ull,512ull,512ull},
Tensor{"blk.0.ffn_gate_shexp.weight",8,{5120,2304},138189824ull,12533760ull,5440ull},
Tensor{"blk.0.ffn_up_shexp.weight",8,{5120,2304},150723584ull,12533760ull,5440ull},
Tensor{"blk.0.ffn_down_shexp.weight",8,{2304,5120},163257344ull,12533760ull,2448ull},
Tensor{"blk.0.hc_ffn_fn.weight",1,{20480,24},175791104ull,983040ull,40960ull},
Tensor{"blk.0.hc_ffn_scale.weight",0,{3},176774144ull,12ull,12ull},
Tensor{"blk.0.hc_ffn_base.weight",0,{24},176774176ull,96ull,96ull},
Tensor{"blk.0.ffn_gate_exps.weight",39,{5120,2304,128},176774272ull,802160640ull,2720ull},
Tensor{"blk.0.ffn_up_exps.weight",39,{5120,2304,128},978934912ull,802160640ull,2720ull},
Tensor{"blk.0.ffn_down_exps.weight",39,{2304,5120,128},1781095552ull,802160640ull,1224ull},
Tensor{"blk.1.attn_norm.weight",0,{5120},2583256192ull,20480ull,20480ull},
Tensor{"blk.1.attn_q_a.weight",8,{5120,1280},2583276672ull,6963200ull,5440ull},
Tensor{"blk.1.attn_q_a_norm.weight",0,{1280},2590239872ull,5120ull,5120ull},
Tensor{"blk.1.attn_q_b.weight",8,{1280,32768},2590244992ull,44564480ull,1360ull},
Tensor{"blk.1.attn_kv.weight",8,{5120,512},2634809472ull,2785280ull,5440ull},
Tensor{"blk.1.attn_kv_a_norm.weight",0,{512},2637594752ull,2048ull,2048ull},
Tensor{"blk.1.attn_sinks.weight",0,{64},2637596800ull,256ull,256ull},
Tensor{"blk.1.attn_output_a.weight",8,{4096,8192},2637597056ull,35651584ull,4352ull},
Tensor{"blk.1.attn_output_b.weight",8,{8192,5120},2673248640ull,44564480ull,8704ull},
Tensor{"blk.1.hc_attn_fn.weight",1,{20480,24},2717813120ull,983040ull,40960ull},
Tensor{"blk.1.hc_attn_scale.weight",0,{3},2718796160ull,12ull,12ull},
Tensor{"blk.1.hc_attn_base.weight",0,{24},2718796192ull,96ull,96ull},
Tensor{"blk.1.ffn_norm.weight",0,{5120},2718796288ull,20480ull,20480ull},
Tensor{"blk.1.ffn_gate_inp.weight",0,{5120,128},2718816768ull,2621440ull,20480ull},
Tensor{"blk.1.exp_probs_b.bias",0,{128},2721438208ull,512ull,512ull},
Tensor{"blk.1.ffn_gate_shexp.weight",8,{5120,2304},2721438720ull,12533760ull,5440ull},
Tensor{"blk.1.ffn_up_shexp.weight",8,{5120,2304},2733972480ull,12533760ull,5440ull},
Tensor{"blk.1.ffn_down_shexp.weight",8,{2304,5120},2746506240ull,12533760ull,2448ull},
Tensor{"blk.1.hc_ffn_fn.weight",1,{20480,24},2759040000ull,983040ull,40960ull},
Tensor{"blk.1.hc_ffn_scale.weight",0,{3},2760023040ull,12ull,12ull},
Tensor{"blk.1.hc_ffn_base.weight",0,{24},2760023072ull,96ull,96ull},
Tensor{"blk.1.ffn_gate_exps.weight",39,{5120,2304,128},2760023168ull,802160640ull,2720ull},
Tensor{"blk.1.ffn_up_exps.weight",39,{5120,2304,128},3562183808ull,802160640ull,2720ull},
Tensor{"blk.1.ffn_down_exps.weight",39,{2304,5120,128},4364344448ull,802160640ull,1224ull},
Tensor{"blk.2.attn_norm.weight",0,{5120},5166505088ull,20480ull,20480ull},
Tensor{"blk.2.attn_q_a.weight",8,{5120,1280},5166525568ull,6963200ull,5440ull},
Tensor{"blk.2.attn_q_a_norm.weight",0,{1280},5173488768ull,5120ull,5120ull},
Tensor{"blk.2.attn_q_b.weight",8,{1280,32768},5173493888ull,44564480ull,1360ull},
Tensor{"blk.2.attn_kv.weight",8,{5120,512},5218058368ull,2785280ull,5440ull},
Tensor{"blk.2.attn_kv_a_norm.weight",0,{512},5220843648ull,2048ull,2048ull},
Tensor{"blk.2.attn_sinks.weight",0,{64},5220845696ull,256ull,256ull},
Tensor{"blk.2.attn_output_a.weight",8,{4096,8192},5220845952ull,35651584ull,4352ull},
Tensor{"blk.2.attn_output_b.weight",8,{8192,5120},5256497536ull,44564480ull,8704ull},
Tensor{"blk.2.hc_attn_fn.weight",1,{20480,24},5301062016ull,983040ull,40960ull},
Tensor{"blk.2.hc_attn_scale.weight",0,{3},5302045056ull,12ull,12ull},
Tensor{"blk.2.hc_attn_base.weight",0,{24},5302045088ull,96ull,96ull},
Tensor{"blk.2.ffn_norm.weight",0,{5120},5302045184ull,20480ull,20480ull},
Tensor{"blk.2.ffn_gate_inp.weight",0,{5120,128},5302065664ull,2621440ull,20480ull},
Tensor{"blk.2.exp_probs_b.bias",0,{128},5304687104ull,512ull,512ull},
Tensor{"blk.2.ffn_gate_shexp.weight",8,{5120,2304},5304687616ull,12533760ull,5440ull},
Tensor{"blk.2.ffn_up_shexp.weight",8,{5120,2304},5317221376ull,12533760ull,5440ull},
Tensor{"blk.2.ffn_down_shexp.weight",8,{2304,5120},5329755136ull,12533760ull,2448ull},
Tensor{"blk.2.hc_ffn_fn.weight",1,{20480,24},5342288896ull,983040ull,40960ull},
Tensor{"blk.2.hc_ffn_scale.weight",0,{3},5343271936ull,12ull,12ull},
Tensor{"blk.2.hc_ffn_base.weight",0,{24},5343271968ull,96ull,96ull},
Tensor{"blk.2.ffn_gate_exps.weight",39,{5120,2304,128},5343272064ull,802160640ull,2720ull},
Tensor{"blk.2.ffn_up_exps.weight",39,{5120,2304,128},6145432704ull,802160640ull,2720ull},
Tensor{"blk.2.ffn_down_exps.weight",39,{2304,5120,128},6947593344ull,802160640ull,1224ull},
Tensor{"dflash.fc.weight",8,{15360,5120},7749753984ull,83558400ull,16320ull},
Tensor{"dflash.hidden_norm.weight",0,{5120},7833312384ull,20480ull,20480ull},
Tensor{"output_norm.weight",0,{5120},7833332864ull,20480ull,20480ull},
Tensor{"dflash.dspark.markov.w1",1,{256,129280},7833353344ull,66191360ull,512ull},
Tensor{"dflash.dspark.markov.w2",1,{256,129280},7899544704ull,66191360ull,512ull},
Tensor{"dflash.dspark.confidence.weight",1,{5376,1},7965736064ull,10752ull,10752ull},
Tensor{"dflash.dspark.confidence.bias",0,{1},7965746816ull,4ull,4ull}
};return result;}
bool same(const Tensor&a,const Tensor&b){return a.name==b.name&&a.type==b.type&&a.dims==b.dims&&a.offset==b.offset&&a.bytes==b.bytes&&a.row_bytes==b.row_bytes;}
void asset_ok(const Asset&a){need(a.file_bytes==artifact_bytes&&a.data_start==7296&&a.tensors.size()==79,"fixed asset geometry");for(size_t i=0;i<79;++i)need(same(a.tensors[i],expected_tensors()[i]),"fixed tensor role/type/shape/offset");}
uint64_t packed(uint32_t t,uint64_t n){if(t==0)return mul(n,4);if(t==1)return mul(n,2);need((t==8||t==39)&&n%32==0,"quantized full-K block");return mul(n/32,t==8?34:17);}
}
Asset inspect_prefix(const std::vector<uint8_t>&raw,uint64_t bytes){
 need(bytes==artifact_bytes&&raw.size()<=65536,"fixed artifact size/prefix bound");Reader r{raw};need(r.integer(4)==0x46554747&&r.integer(4)==3,"GGUF magic/version");auto nt=r.integer(8),nm=r.integer(8);need(nt==79&&nm==expected_metadata().size(),"fixed metadata/tensor count");std::map<std::string,Meta> seen;
 for(uint64_t i=0;i<nm;++i){auto key=r.string();auto type=uint32_t(r.integer(4));auto value=metadata(r,type);need(seen.emplace(key,value).second,"duplicate metadata");auto it=expected_metadata().find(key);need(it!=expected_metadata().end(),"unexpected metadata");auto e=it->second;need(value.type==e.type&&value.text==e.text&&value.number==e.number&&value.array_type==e.array_type&&value.array==e.array,"fixed metadata value/type");}
 Asset a;a.file_bytes=bytes;
 for(uint64_t i=0;i<nt;++i){Tensor t;t.name=r.string();auto rank=r.integer(4);need(rank>=1&&rank<=3,"fixed tensor rank");uint64_t n=1;for(uint64_t d=0;d<rank;++d){auto dim=r.integer(8);need(dim>0,"zero dimension");t.dims.push_back(dim);n=mul(n,dim);}t.type=uint32_t(r.integer(4));auto relative=r.integer(8);need(relative%32==0,"tensor alignment");t.bytes=packed(t.type,n);t.row_bytes=packed(t.type,t.dims[0]);t.offset=relative;a.tensors.push_back(std::move(t));}
 a.data_start=(add(r.at,31)/32)*32;need(a.data_start<=raw.size(),"missing header padding");for(auto&t:a.tensors){t.offset=add(a.data_start,t.offset);need(t.offset<=bytes&&t.bytes<=bytes-t.offset,"tensor outside file");}asset_ok(a);return a;
}
Span required_span(const Asset&a,const std::string&name,uint64_t matrix,uint64_t first,uint64_t count){
 asset_ok(a);auto it=std::find_if(a.tensors.begin(),a.tensors.end(),[&](const auto&t){return t.name==name;});need(it!=a.tensors.end(),"unknown tensor role");const auto&t=*it;uint64_t rows=t.dims.size()>1?t.dims[1]:1,matrices=t.dims.size()>2?t.dims[2]:1;
 need(count&&matrix<matrices&&first<rows&&count<=rows-first,"full-K span matrix/row range");auto relative=mul(add(mul(matrix,rows),first),t.row_bytes);auto bytes=mul(count,t.row_bytes);need(relative<=t.bytes&&bytes<=t.bytes-relative,"span outside tensor");return {t,matrix,first,count,add(t.offset,relative),bytes};
}
std::vector<uint8_t> read_span(const std::string&path,const Span&s,uint64_t credit){
 Asset a{7296,artifact_bytes,expected_tensors()};auto expected=required_span(a,s.tensor.name,s.matrix,s.row,s.count);need(same(s.tensor,expected.tensor)&&s.offset==expected.offset&&s.bytes==expected.bytes,"forged span");need(s.bytes&&s.bytes<=credit&&s.bytes<=SIZE_MAX,"span byte credit");
 std::ifstream f(path,std::ios::binary|std::ios::ate);need(bool(f)&&uint64_t(f.tellg())==artifact_bytes,"artifact file size/open");std::vector<uint8_t> out(size_t(s.bytes));f.seekg(std::streamoff(s.offset));f.read(reinterpret_cast<char*>(out.data()),std::streamsize(out.size()));need(bool(f)&&size_t(f.gcount())==out.size(),"short bounded source span");return out;
}

std::vector<ProjectionWave> projection_wave_offsets(uint64_t batch,uint64_t k,uint64_t stride,uint64_t rows,uint64_t input_bytes,uint64_t output_bytes,const std::vector<uint32_t>&waves){
 need(batch&&k&&rows&&stride>=rows&&!waves.empty(),"projection wave geometry");std::vector<ProjectionWave> result;uint64_t first=0;
 for(auto n:waves){need((n==1||n==2||n==4||n==8)&&first<=batch&&n<=batch-first,"projection wave supported batch/coverage");auto in=mul(mul(first,k),4),out=mul(mul(first,stride),4);auto in_count=mul(mul(n,k),4),out_count=mul(add(mul(n-1,stride),rows),4);need(in<=input_bytes&&in_count<=input_bytes-in&&out<=output_bytes&&out_count<=output_bytes-out,"projection wave byte range");result.push_back({first,n,in,out});first+=n;}
 need(first==batch,"projection wave missing rows");return result;
}
}
