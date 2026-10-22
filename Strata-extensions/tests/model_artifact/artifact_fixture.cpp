#include "artifact.hpp"
#include <fstream>
#include <iostream>
#include <functional>
using namespace strata_ext;
unsigned checks=0;
void require(bool value){++checks;if(!value)throw std::runtime_error("fixture assertion failed");}
void rejects(const std::function<void()>& f){bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}require(rejected);}
int main(int argc,char** argv){try{
 if(argc==2 && std::string(argv[1])=="--identity"){std::cout<<"{\"source_sha256\":\""<<T10_SOURCE_SHA<<"\"}";return 0;}
 if(argc!=4)throw std::runtime_error("need prefix-list, source table, output TSV");
 deepseek41::SourceSet sources;std::ifstream table(argv[2]);std::string row;
 while(std::getline(table,row)){std::vector<std::string> fields;size_t from=0;while(true){auto tab=row.find('\t',from);fields.push_back(row.substr(from,tab-from));if(tab==std::string::npos)break;from=tab+1;}if(fields.size()!=5)throw std::runtime_error("source table columns");deepseek41::SourceFile f;f.shard_index=std::stoul(fields[0]);f.original_size=std::stoull(fields[1]);f.lfs_sha256=fields[2];f.revision=fields[3];f.original_path=fields[4];if(sources.root.empty())sources.root=f.original_path.parent_path();sources.files.push_back(f);}

 std::ifstream input(argv[1]);std::string line,first;std::vector<artifact::PrefixIndex> prefixes;
 while(std::getline(input,line)){auto tab=line.find('\t');if(tab==std::string::npos)throw std::runtime_error("prefix list");auto path=line.substr(tab+1);if(first.empty())first=path;prefixes.push_back(artifact::inspect_prefix(path,std::stoull(line.substr(0,tab))));}
 auto spans=artifact::merge_prefixes(prefixes);auto metadata=deepseek41::inspect_metadata(first);deepseek41::Artifact index(spans,metadata,sources);require(index.tensors().size()==1043);
 std::ofstream out(argv[3]);
 for(const auto& t:index.tensors()){out<<t.shard_index<<'\t'<<t.name<<'\t'<<t.type_id<<'\t'<<t.absolute_offset<<'\t'<<t.bytes<<'\t'<<t.row_bytes;for(auto d:t.dims_ggml)out<<'\t'<<d;auto source=index.source_tensor(t.name);out<<'\t'<<source.source.original_path.generic_string()<<'\t'<<source.source.original_size<<'\t'<<source.source.lfs_sha256<<'\t'<<source.source.revision<<'\n';}
 for(unsigned layer=0;layer<40;++layer)for(const auto& role:{"gate","up","down"})for(unsigned expert:{0u,383u}){
   auto view=index.expert(layer,role,expert);const auto& t=view.original.span;uint64_t bytes=t.row_bytes*t.dims_ggml[1];
   require(view.absolute_offset==t.absolute_offset+expert*bytes && view.bytes==bytes && t.dims_ggml[2]==384);
   out<<"expert\t"<<layer<<'\t'<<role<<'\t'<<expert<<'\t'<<view.absolute_offset<<'\t'<<view.bytes<<'\n';
 }
 for(unsigned layer:{1u,14u})for(unsigned head=0;head<24;++head){auto count=index.head_rows(layer,head);for(uint64_t row:{uint64_t(0),count-1}){
   auto view=index.engram_row(layer,head,row);require(view.bytes==264 && view.original.span.dims_ggml==std::vector<uint64_t>({256,768022850}));
   out<<"slice\t"<<layer<<'\t'<<head<<'\t'<<row<<'\t'<<view.absolute_offset<<'\t'<<view.bytes<<'\n';
 }rejects([&]{index.engram_row(layer,head,count);});}
 rejects([&]{index.expert(40,"gate",0);});rejects([&]{index.expert(0,"bad",0);});rejects([&]{index.expert(0,"gate",384);});
 rejects([&]{index.engram_row(0,0,0);});rejects([&]{index.engram_row(1,24,0);});rejects([&]{index.engram_row(1,0,UINT64_MAX);});
 for(unsigned mode=0;mode<8;++mode){auto wrong=spans;switch(mode){case 0:wrong.pop_back();break;case 1:wrong.push_back(wrong.front());break;case 2:wrong.front().name="blk.0.ple.weight";break;case 3:wrong.front().type_id=117;break;case 4:wrong.front().dims_ggml[0]=5119;break;case 5:wrong.front().absolute_offset=UINT64_MAX;break;case 6:wrong.front().bytes--;break;case 7:wrong.front().absolute_offset=sources.files[1].original_size-32;break;}rejects([&]{deepseek41::Artifact bad(wrong,metadata,sources);});}
 for(unsigned mode=0;mode<9;++mode){auto m=metadata;switch(mode){case 0:m.architecture="qwen4exp";break;case 1:m.integers["deepseek41.block_count"]=43;break;case 2:m.integers["deepseek41.expert_used_count"]=8;break;case 3:m.arrays["deepseek41.ple.layers"]={0,1};break;case 4:m.arrays["deepseek41.attention.kv_source_layers"]={2,8,14};break;case 5:m.arrays["deepseek41.ple.head_offsets"][1]++;break;case 6:m.tokenizer_pre="deepseek3";break;case 7:m.integers["tokenizer.ggml.padding_token_id"]=2;break;case 8:m.arrays["deepseek41.dspark.target_layers"]={40,41,42};break;}rejects([&]{deepseek41::Artifact bad(spans,m,sources);});}
 for(unsigned mode=0;mode<6;++mode){auto wrong=sources;switch(mode){case 0:wrong.files[1].original_size--;break;case 1:wrong.files[1].revision="other";break;case 2:wrong.files[1].lfs_sha256=std::string(64,'0');break;case 3:wrong.files[1].original_path=wrong.files[0].original_path;break;case 4:wrong.files[1].shard_index=1;break;case 5:wrong.files.pop_back();break;}rejects([&]{deepseek41::Artifact bad(spans,metadata,wrong);});}
 auto expert_source=index.expert(0,"gate",383).original.source;require(expert_source.shard_index==2 && expert_source.original_path==sources.files[1].original_path);
 auto row_source=index.engram_row(14,23,index.head_rows(14,23)-1).original.source;require(row_source.shard_index==8 && row_source.original_path==sources.files[7].original_path);
 std::cout<<"{\"assertions\":"<<checks<<",\"tensor_count\":1043,\"full_source_qualified\":false}";return 0;
 }catch(const std::exception& e){std::cerr<<e.what();return 2;}}
