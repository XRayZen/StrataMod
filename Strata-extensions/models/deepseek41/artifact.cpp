#include "artifact.hpp"
#include "strata/artifact/gguf_reader.hpp"
#include <set>
#include <limits>

namespace strata_ext::deepseek41 {
namespace {
uint64_t add(uint64_t a,uint64_t b){if(b>UINT64_MAX-a)throw std::runtime_error("span overflow");return a+b;}
uint64_t mul(uint64_t a,uint64_t b){if(a && b>UINT64_MAX/a)throw std::runtime_error("shape overflow");return a*b;}
bool integer_type(strata::MetaType type){return type==strata::MetaType::I8 || type==strata::MetaType::I16 || type==strata::MetaType::I32 || type==strata::MetaType::I64 || type==strata::MetaType::U8 || type==strata::MetaType::U16 || type==strata::MetaType::U32 || type==strata::MetaType::U64;}
const std::vector<std::pair<uint64_t,std::string>> fixed_sources={
{5780589,"cc15d470afcb030558bbc4d8e2ccd840182e2e95de1a95198138efe63a5fd99f"},
{48129640000,"17df217d8fc26a39f21ea40805dc6ab788c7ce8623a59a95c431051df7eafc94"},
{48129640000,"0c8065f620a049cb437024c54ff12c314c94603a1cc683f5191be4689d6d6d3b"},
{48129640000,"3bd8b2ebf8f51d8708a73ae0895f8d4acc7e4c983ba4e89d038492b203cc89ac"},
{48129640000,"929054a6bbf3701765779b58c37988b6c6284a3b8413901858b59c0e95f37cc3"},
{48129640000,"49d3de04bd6a09de786c9ef7db900eae02ee9fd391573f91a923013d7d5b24d3"},
{48129640000,"f18feae5878dd680f1ea87ecd1d84f4fb098480298b25a3162dcbdab8dc2ca5b"},
{202758032592,"12df293355efbd104b088a77e13ee22410fb1ec3f7ab3863947f09896e64bec7"},
{9165923392,"c21ad6105a780bc2f44eb7dd41f9b1a1efb4e8ec87618f60b733bc2652bd2ffe"}
};
const std::map<std::string,uint64_t> expected_ints={
 {"deepseek41.block_count",40},{"deepseek41.embedding_length",5120},{"deepseek41.embedding_length_out",20480},
 {"deepseek41.expert_count",384},{"deepseek41.expert_used_count",6},{"deepseek41.expert_feed_forward_length",2304},
 {"deepseek41.attention.head_count",64},{"deepseek41.attention.head_count_kv",1},{"deepseek41.attention.key_length",512},{"deepseek41.attention.value_length",512},
 {"deepseek41.attention.q_lora_rank",1280},{"deepseek41.attention.output_lora_rank",1024},{"deepseek41.attention.output_group_count",8},
 {"deepseek41.rope.dimension_count",64},{"deepseek41.attention.sliding_window",128},
 {"deepseek41.attention.indexer.head_count",32},{"deepseek41.attention.indexer.key_length",128},{"deepseek41.attention.indexer.top_k",512},
 {"deepseek41.hyper_connection.count",4},{"deepseek41.hyper_connection.sinkhorn_iterations",20},
 {"deepseek41.embedding_length_per_layer_input",256},{"deepseek41.ple.ngram_size",4},{"deepseek41.ple.heads_per_ngram",8},
 {"deepseek41.engram.pad_token_id",2},{"deepseek41.engram.compressed_vocab_size",99092},
 {"tokenizer.ggml.bos_token_id",0},{"tokenizer.ggml.eos_token_id",1},{"tokenizer.ggml.padding_token_id",1}
};
std::vector<std::string> array_keys={"deepseek41.attention.compress_ratios","deepseek41.attention.kv_source_layers","deepseek41.attention.indexer.source_layers","deepseek41.ple.layers","deepseek41.ple.head_offsets","deepseek41.ple.head_vocab_sizes","deepseek41.dspark.target_layers"};
void validate(const Metadata& m){
 if(m.architecture!="deepseek41" || m.tokenizer_model!="gpt2" || m.tokenizer_pre!="joyai-llm")throw std::runtime_error("wrong family/tokenizer mapping");
 for(const auto& [key,value]:expected_ints){auto i=m.integers.find(key);if(i==m.integers.end() || i->second!=value)throw std::runtime_error("config mismatch: "+key);}
 auto array=[&](const std::string& key,const std::vector<uint64_t>& expected){auto i=m.arrays.find(key);if(i==m.arrays.end() || i->second!=expected)throw std::runtime_error("config array mismatch: "+key);};
 array("deepseek41.attention.kv_source_layers",{2,8,14,20});array("deepseek41.attention.indexer.source_layers",{2,8,14,20,24,28,32,36});array("deepseek41.ple.layers",{1,14});array("deepseek41.dspark.target_layers",{37,38,39});
 std::vector<uint64_t> ratios(43,0);for(size_t i=2;i<20;++i)ratios[i]=2;for(size_t i=20;i<40;++i)ratios[i]=1;array("deepseek41.attention.compress_ratios",ratios);
 const auto& offsets=m.arrays.at("deepseek41.ple.head_offsets");const auto& sizes=m.arrays.at("deepseek41.ple.head_vocab_sizes");
 if(offsets.size()!=48 || sizes.size()!=48)throw std::runtime_error("Engram head count");uint64_t total=0;
 for(size_t i=0;i<48;++i){if(!sizes[i] || offsets[i]!=total)throw std::runtime_error("Engram concatenation");total=add(total,sizes[i]);if(i==23 && total!=384006168)throw std::runtime_error("first layer Engram rows");}
 if(total!=768022850)throw std::runtime_error("Engram total rows");
}
struct Spec {uint32_t type;std::vector<uint64_t> dims;};
std::map<std::string,Spec> expected_roles(){
 std::map<std::string,Spec> expected;
 auto put=[&](std::string name,uint32_t type,std::vector<uint64_t> dims){expected.emplace(std::move(name),Spec{type,std::move(dims)});};
 put("token_embd.weight",8,{5120,129280});put("output.weight",8,{5120,129280});put("output_norm.weight",0,{5120});put("per_layer_token_embd.weight",43,{256,768022850});
 for(unsigned l=0;l<40;++l){auto p="blk."+std::to_string(l)+".";
  put(p+"ffn_gate_exps.weight",39,{5120,2304,384});put(p+"ffn_up_exps.weight",39,{5120,2304,384});put(p+"ffn_down_exps.weight",39,{2304,5120,384});
  put(p+"attn_sinks.weight",0,{64});put(p+"attn_kv_a_norm.weight",0,{512});put(p+"attn_q_a_norm.weight",0,{1280});
  put(p+"attn_kv.weight",8,{5120,512});put(p+"attn_output_a.weight",8,{4096,8192});put(p+"attn_output_b.weight",8,{8192,5120});put(p+"attn_q_a.weight",8,{5120,1280});put(p+"attn_q_b.weight",8,{1280,32768});
  put(p+"attn_norm.weight",0,{5120});put(p+"exp_probs_b.bias",0,{384});put(p+"exp_probs_b_vl.bias",0,{384});put(p+"ffn_gate_inp.weight",0,{5120,384});
  put(p+"ffn_gate_shexp.weight",8,{5120,2304});put(p+"ffn_up_shexp.weight",8,{5120,2304});put(p+"ffn_down_shexp.weight",8,{2304,5120});put(p+"ffn_norm.weight",0,{5120});
  for(auto section:{"attn","ffn"}){put(p+"hc_"+section+"_base.weight",0,{24});put(p+"hc_"+section+"_fn.weight",0,{20480,24});put(p+"hc_"+section+"_scale.weight",0,{3});}
 }
 for(unsigned l:{2u,8u,14u,20u}){auto p="blk."+std::to_string(l)+".";put(p+"attn_compressor_norm.weight",0,{512});put(p+"attn_compressor_kv.weight",8,{5120,512});if(l!=20)put(p+"attn_compressor_gate.weight",8,{5120,512});put(p+"indexer.k_norm.weight",0,{128});put(p+"indexer.attn_k.weight",8,{512,128});}
 for(unsigned l:{2u,8u,14u,20u,24u,28u,32u,36u}){auto p="blk."+std::to_string(l)+".";put(p+"indexer.proj.weight",8,{5120,32});put(p+"indexer.attn_q_b.weight",8,{1280,4096});}
 for(unsigned l:{1u,14u}){auto p="blk."+std::to_string(l)+".";put(p+"engram_gate.weight",0,{5120,4});put(p+"engram_kv.weight",8,{6144,25600});}
 return expected;
}
}
Metadata inspect_metadata(const std::filesystem::path& prefix){
 strata::GgufFile f(prefix.string());Metadata result;
 auto text=[&](const char* key){auto v=f.get(key);if(!v || v->type!=strata::MetaType::STRING)throw std::runtime_error("metadata string required");return v->s;};
 result.architecture=text("general.architecture");result.tokenizer_model=text("tokenizer.ggml.model");result.tokenizer_pre=text("tokenizer.ggml.pre");
 for(const auto& [key,value]:expected_ints){(void)value;auto v=f.get(key.c_str());if(!v || !integer_type(v->type))throw std::runtime_error("integer metadata required: "+key);result.integers[key]=v->u;}
 for(const auto& key:array_keys){auto v=f.get(key.c_str());if(!v || v->type!=strata::MetaType::ARRAY || !integer_type(v->elem))throw std::runtime_error("integer array required: "+key);auto& out=result.arrays[key];for(const auto& item:v->items)out.push_back(item.u);if(out.size()!=v->count)throw std::runtime_error("array count mismatch");}
 auto tokens=f.get("tokenizer.ggml.tokens");if(!tokens || tokens->type!=strata::MetaType::ARRAY || tokens->count!=129280)throw std::runtime_error("tokenizer vocabulary size");
 return result;
}
Artifact::Artifact(std::vector<artifact::TensorSpan> tensors,Metadata metadata,SourceSet sources):tensors_(std::move(tensors)),metadata_(std::move(metadata)),sources_(std::move(sources)){
 if(sources_.files.size()!=9 || !sources_.root.is_absolute())throw std::runtime_error("nine source candidates required");
 std::set<uint32_t> source_ids;
 for(const auto& f:sources_.files){
  if(f.shard_index<1 || f.shard_index>9 || !source_ids.insert(f.shard_index).second)throw std::runtime_error("source shard identity");
  const auto& expected=fixed_sources[f.shard_index-1];
  auto number=std::to_string(f.shard_index);auto filename="DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-"+std::string(5-number.size(),'0')+number+"-of-00009.gguf";
  if(f.original_size!=expected.first || f.lfs_sha256!=expected.second || f.revision!="f924b94f19c1fea02c06a65c8475b0a45e2b88b1" || f.original_path.lexically_normal()!=(sources_.root/filename).lexically_normal())throw std::runtime_error("source path/size/revision/LFS identity");
 }
 std::sort(sources_.files.begin(),sources_.files.end(),[](const auto&a,const auto&b){return a.shard_index<b.shard_index;});
 validate(metadata_);auto expected=expected_roles();if(expected.size()!=1043 || tensors_.size()!=expected.size())throw std::runtime_error("trunk tensor coverage");
 for(size_t i=0;i<tensors_.size();++i){const auto& t=tensors_[i];auto spec=expected.find(t.name);
  if(spec==expected.end() || !names_.emplace(t.name,i).second || spec->second.type!=t.type_id || spec->second.dims!=t.dims_ggml)throw std::runtime_error("unknown/missing/duplicate/shape/layout role: "+t.name);
  if(t.shard_index<1 || t.shard_index>9)throw std::runtime_error("shard identity");
  const uint64_t block=t.type_id==0?1:32,bytes=t.type_id==0?4:t.type_id==8?34:t.type_id==39?17:33;
  auto row=mul(t.dims_ggml[0]/block,bytes);auto size=row;for(size_t d=1;d<t.dims_ggml.size();++d)size=mul(size,t.dims_ggml[d]);
  if(t.row_bytes!=row || t.bytes!=size || t.absolute_offset%32)throw std::runtime_error("native span geometry");if(add(t.absolute_offset,t.bytes)>sources_.files[t.shard_index-1].original_size)throw std::runtime_error("tensor outside bound original source");
 }
}
const artifact::TensorSpan& Artifact::get(const std::string& name)const{auto i=names_.find(name);if(i==names_.end())throw std::runtime_error("missing role");return tensors_[i->second];}
SourceTensor Artifact::source_tensor(const std::string& name)const{const auto& t=get(name);return {sources_.files[t.shard_index-1],t};}
Slice Artifact::expert(uint32_t layer,const std::string& role,uint32_t expert)const{
 if(layer>=40 || expert>=384 || (role!="gate" && role!="up" && role!="down"))throw std::runtime_error("expert index/role");
 const auto& t=get("blk."+std::to_string(layer)+".ffn_"+role+"_exps.weight");auto bytes=mul(t.row_bytes,t.dims_ggml[1]);return {source_tensor(t.name),add(t.absolute_offset,mul(expert,bytes)),bytes,{t.dims_ggml[0],t.dims_ggml[1]}};
}
uint64_t Artifact::head_rows(uint32_t layer,uint32_t head)const{if((layer!=1 && layer!=14) || head>=24)throw std::runtime_error("Engram layer/head");return metadata_.arrays.at("deepseek41.ple.head_vocab_sizes")[(layer==1?0:24)+head];}
Slice Artifact::engram_row(uint32_t layer,uint32_t head,uint64_t row)const{
 if(row>=head_rows(layer,head))throw std::runtime_error("Engram row outside head");auto i=(layer==1?0:24)+head;auto global=add(metadata_.arrays.at("deepseek41.ple.head_offsets")[i],row);const auto& t=get("per_layer_token_embd.weight");return {source_tensor(t.name),add(t.absolute_offset,mul(global,t.row_bytes)),t.row_bytes,{256}};
}
}
