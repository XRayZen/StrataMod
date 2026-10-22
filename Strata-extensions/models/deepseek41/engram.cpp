#include "engram.hpp"
#include "strata/artifact/gguf_reader.hpp"
#include <algorithm>
#include <limits>
#include <fstream>
#include <set>
#include <stdexcept>
namespace strata_ext::deepseek41::engram {
namespace {
void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
bool prime(uint64_t n){if(n<2)return false;for(uint64_t d=2;d<=n/d;++d)if(n%d==0)return false;return true;}
bool integer(strata::MetaType t){using T=strata::MetaType;return t==T::U8||t==T::I8||t==T::U16||t==T::I16||t==T::U32||t==T::I32||t==T::U64||t==T::I64;}
}
void Config::validate() const {
    require(token_map.size()==129280&&compressed_size==99092,"Engram compressed vocabulary");
    require(multipliers.size()==8&&primes.size()==48&&offsets.size()==48,"Engram layer/head count");
    for(auto x:token_map)require(x<compressed_size,"compressed ID outside vocabulary");
    require(pad==token_map[2],"Engram PAD must be compressed raw ID2");
    const uint64_t max=uint64_t((std::numeric_limits<int64_t>::max)());
    for(auto m:multipliers)require(m>0&&(m&1)&&m<=max/(compressed_size-1),"hash product outside signed int64");
    std::set<uint64_t> seen;uint64_t total=0;
    for(size_t i=0;i<48;++i){require(prime(primes[i])&&seen.insert(primes[i]).second,"nonunique/nonprime bucket");require(offsets[i]==total&&total<=max-primes[i],"Engram offsets overflow/order");total+=primes[i];if(i==23)require(total==384006168,"first layer row count");}
    require(total==768022850,"combined Engram row count");
}
Config inspect_metadata(const std::filesystem::path& path){
    strata::GgufFile f(path.string());Config c;
    auto scalar=[&](const char* key){auto v=f.get(key);require(v&&integer(v->type),"integer Engram metadata required");return v->u;};
    auto array=[&](const char* key){auto v=f.get(key);require(v&&v->type==strata::MetaType::ARRAY&&integer(v->elem),"integer Engram array required");std::vector<uint64_t> r;for(const auto& item:v->items)r.push_back(item.u);require(r.size()==v->count,"Engram metadata count");return r;};
    require(array("deepseek41.ple.layers")==std::vector<uint64_t>({1,14}),"Engram layer order");
    require(scalar("deepseek41.ple.ngram_size")==4&&scalar("deepseek41.ple.heads_per_ngram")==8&&scalar("deepseek41.embedding_length_per_layer_input")==256,"Engram geometry");
    auto compressed=scalar("deepseek41.engram.compressed_vocab_size");require(compressed==99092&&scalar("deepseek41.engram.pad_token_id")==2,"Engram vocabulary/pad");c.compressed_size=uint32_t(compressed);
    // The generic reader intentionally retains only 64 array samples. Reuse
    // its checked Cursor/read_value on this strict PREFIX to retain this one
    // full integer array. No alternate GGUF parser or original tensor mapping.
    require(f.file_size()<=(std::numeric_limits<size_t>::max)(),"prefix size overflow");
    std::vector<uint8_t> bytes(size_t(f.file_size()));std::ifstream input(path,std::ios::binary);input.read(reinterpret_cast<char*>(bytes.data()),std::streamsize(bytes.size()));require(bool(input),"prefix short read");
    strata::Cursor cursor(bytes.data(),bytes.size());require(cursor.read<uint32_t>()==0x46554747&&cursor.read<uint32_t>()==3,"GGUF prefix version");cursor.read<uint64_t>();auto count=cursor.read<uint64_t>();
    for(uint64_t k=0;k<count;++k){auto name=cursor.str();auto type=static_cast<strata::MetaType>(cursor.read<uint32_t>());
        if(name!="deepseek41.engram.token_map"){strata::read_value(cursor,type);continue;}
        require(type==strata::MetaType::ARRAY,"token map must be array");auto element=static_cast<strata::MetaType>(cursor.read<uint32_t>());auto size=cursor.read<uint64_t>();require(element==strata::MetaType::I32&&size==129280,"token map fixed I32 type/count");cursor.need(size_t(size)*sizeof(int32_t));
        for(uint64_t i=0;i<size;++i){auto x=strata::read_value(cursor,element).u;require(x<compressed,"Engram token map range");c.token_map.push_back(uint32_t(x));}
    }
    c.multipliers=array("deepseek41.ple.layer_multipliers");c.primes=array("deepseek41.ple.head_vocab_sizes");c.offsets=array("deepseek41.ple.head_offsets");require(c.token_map.size()>2,"missing PAD mapping");c.pad=c.token_map[2];c.validate();return c;
}
History::History(const Config& c):config_(c){c.validate();}
std::vector<uint64_t> History::append(uint64_t start,const std::vector<uint32_t>& raw,const std::vector<uint8_t>& mask){
    require(start==position_&&raw.size()==mask.size()&&!raw.empty(),"append position/shape");
    require(raw.size()<=(std::numeric_limits<uint64_t>::max)()-position_&&raw.size()<=(std::numeric_limits<size_t>::max)()/48,"hash output overflow");
    for(size_t i=0;i<raw.size();++i)require(raw[i]<config_.token_map.size()&&mask[i]<=1,"raw ID/mask outside contract");
    std::vector<uint64_t> result;result.reserve(raw.size()*48);
    for(size_t i=0;i<raw.size();++i){
        int64_t current=mask[i]?int64_t(config_.token_map[raw[i]]):-1;
        uint64_t tokens[4];bool blocked=false;
        for(size_t s=0;s<4;++s){int64_t value=s==0?current:s<=recent_.size()?recent_[recent_.size()-s]:-1;blocked=blocked||value<0;tokens[s]=blocked?config_.pad:uint64_t(value);}
        for(size_t layer=0;layer<2;++layer){uint64_t rolling=tokens[0]*config_.multipliers[layer*4];for(size_t n=1;n<4;++n){rolling^=tokens[n]*config_.multipliers[layer*4+n];for(size_t h=0;h<8;++h){size_t j=layer*24+(n-1)*8+h;result.push_back(rolling%config_.primes[j]+config_.offsets[j]);}}}
        recent_.push_back(current);if(recent_.size()>3)recent_.erase(recent_.begin());++position_;
    }
    return result;
}
void validate_indices(uint64_t rows,const std::vector<uint32_t>& indices){require(rows>0&&!indices.empty()&&rows<=(std::numeric_limits<uint64_t>::max)()/264&&indices.size()<=(std::numeric_limits<size_t>::max)()/256/4,"gather shape/overflow");for(auto index:indices)require(index<rows,"gather row out of bank");}
}
