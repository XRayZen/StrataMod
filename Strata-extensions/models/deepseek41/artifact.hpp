#pragma once
#include "../../native/artifact/native_reader.hpp"
#include <map>
namespace strata_ext::deepseek41 {
// Caller supplies only T03 strict/SHA-bound prefixes. This is structural indexing,
// never full-source acquisition, tokenizer compatibility or execution authority.
struct Metadata {
 std::string architecture,tokenizer_model,tokenizer_pre;
 std::map<std::string,uint64_t> integers;
 std::map<std::string,std::vector<uint64_t>> arrays;
};
Metadata inspect_metadata(const std::filesystem::path& prefix);
struct SourceFile { uint32_t shard_index=0; std::filesystem::path original_path; uint64_t original_size=0; std::string revision,lfs_sha256; };
struct SourceTensor { SourceFile source; artifact::TensorSpan span; };
// Offline files are candidate paths/planned sizes; this type does not grant
// acquisition/full-source qualification. T05 receipt binding is the caller's.
struct SourceSet { std::filesystem::path root; std::vector<SourceFile> files; };
struct Slice { SourceTensor original; uint64_t absolute_offset=0,bytes=0; std::vector<uint64_t> dims_ggml; };
class Artifact {
 std::vector<artifact::TensorSpan> tensors_;
 std::map<std::string,size_t> names_;
 Metadata metadata_;
 SourceSet sources_;
 const artifact::TensorSpan& get(const std::string&) const;
public:
 Artifact(std::vector<artifact::TensorSpan>,Metadata,SourceSet);
 SourceTensor source_tensor(const std::string& name)const;
 const std::vector<artifact::TensorSpan>& tensors()const{return tensors_;}
 Slice expert(uint32_t layer,const std::string& matrix,uint32_t expert)const;
 uint64_t head_rows(uint32_t layer,uint32_t head)const;
 Slice engram_row(uint32_t layer,uint32_t head,uint64_t row)const;
 // GGUF pad1 is kept distinct from official/Engram pad2; no compatibility claim.
 uint64_t gguf_padding_id()const{return 1;}
 uint64_t official_padding_id()const{return 2;}
};
}
