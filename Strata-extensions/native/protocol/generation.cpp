#include "generation.hpp"
#define NOMINMAX
#include <Windows.h>
#include <bcrypt.h>
#include <array>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <set>
namespace strata_ext::protocol {
namespace {
std::string quote(const std::string& value){
    const char* hex="0123456789abcdef";std::string out="\"";
    for(unsigned char c:value){
        if(c=='\"' || c=='\\'){out+='\\';out+=static_cast<char>(c);}
        else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}
        else out+=static_cast<char>(c);
    }
    return out+'\"';
}
bool hex(const std::string& s,size_t n){return s.size()==n && s.find_first_not_of("0123456789abcdef")==std::string::npos;}
void check(NTSTATUS s){if(s<0)throw std::runtime_error("native protocol SHA256 failure");}
const char* finish_name(Finish f){switch(f){case Finish::Stop:return "stop";case Finish::Length:return "length";case Finish::Cancel:return "cancel";case Finish::NonFinite:return "nonfinite";case Finish::Error:return "error";}throw std::invalid_argument("unknown finish");}
}
struct GenerationEmitter::State {
    bool metadata=false;
    BCRYPT_HASH_HANDLE meta_hash=nullptr;std::vector<unsigned char> meta_object;
    Context context;uint64_t sequence=0,count=0;bool begun=false,ended=false;
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;std::vector<unsigned char> object;
    explicit State(Context c,bool m):metadata(m),context(std::move(c)){
        if(context.request_id.empty() || !hex(context.bundle_id,64) || !hex(context.asset_revision,40) || !hex(context.tokenizer_identity,64)
            || context.model_family!="deepseek41" || context.tokenizer_model!="gpt2" || context.tokenizer_pre!="joyai-llm" || context.vocab_size!=129280)
            throw std::invalid_argument("invalid generation context");
        try{
            check(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0));
            ULONG size=0,read=0;check(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&size),sizeof(size),&read,0));
            if(read!=sizeof(size))throw std::runtime_error("invalid SHA object property");object.resize(size);
            check(BCryptCreateHash(algorithm,&hash,object.data(),size,nullptr,0,0));
            meta_object.resize(size);check(BCryptCreateHash(algorithm,&meta_hash,meta_object.data(),size,nullptr,0,0));
            const char domain[]="strata-generation-metadata/v1";check(BCryptHashData(meta_hash,reinterpret_cast<PUCHAR>(const_cast<char*>(domain)),sizeof(domain),0));
        }catch(...){if(meta_hash)BCryptDestroyHash(meta_hash);if(hash)BCryptDestroyHash(hash);if(algorithm)BCryptCloseAlgorithmProvider(algorithm,0);throw;}
    }
    ~State(){if(meta_hash)BCryptDestroyHash(meta_hash);if(hash)BCryptDestroyHash(hash);if(algorithm)BCryptCloseAlgorithmProvider(algorithm,0);}
    std::string common(const char* kind)const{
        return "{\"schema\":\"strata-generation/v1\",\"kind\":"+quote(kind)+",\"request_id\":"+quote(context.request_id)+",\"runtime_epoch\":"+std::to_string(context.runtime_epoch);
    }
    void active()const{if(!begun || ended)throw std::invalid_argument("generation frame outside active request");}
};
GenerationEmitter::GenerationEmitter(Context c,bool m):state_(std::make_unique<State>(std::move(c),m)){}
GenerationEmitter::~GenerationEmitter()=default;
std::string GenerationEmitter::begin(){
    auto& s=*state_;if(s.begun)throw std::invalid_argument("duplicate begin");s.begun=true;const auto& c=s.context;
    return s.common("begin")+",\"bundle_id\":"+quote(c.bundle_id)+",\"asset_revision\":"+quote(c.asset_revision)+",\"model_family\":"+quote(c.model_family)
        +",\"tokenizer_identity\":"+quote(c.tokenizer_identity)+",\"tokenizer_model\":"+quote(c.tokenizer_model)+",\"tokenizer_pre\":"+quote(c.tokenizer_pre)+",\"vocab_size\":"+std::to_string(c.vocab_size)+(s.metadata?",\"metadata_schema\":\"strata-generation-metadata/v1\"}":"}");
}
std::string GenerationEmitter::tokens(const std::vector<uint32_t>&ids){return tokens(ids,{});}
std::string GenerationEmitter::tokens(const std::vector<uint32_t>& ids,const std::vector<TokenLogprob>&lp){
    auto& s=*state_;s.active();if(ids.empty() || ids.size()>UINT64_MAX-s.count || s.sequence==UINT64_MAX)throw std::invalid_argument("invalid token batch size");
    if(!lp.empty()&&(!s.metadata||lp.size()!=ids.size()))throw std::invalid_argument("LP count/negotiation");
    for(const auto&record:lp){if(!std::isfinite(record.logprob)||record.logprob>0||record.alternatives.size()>20)throw std::invalid_argument("LP value/count");std::set<uint32_t>seen;for(auto [id,p]:record.alternatives)if(id>=s.context.vocab_size||!seen.insert(id).second||!std::isfinite(p)||p>0)throw std::invalid_argument("LP alternative");}
    for(auto id:ids)if(id>=s.context.vocab_size)throw std::invalid_argument("native token ID outside vocabulary");
    std::string out=s.common("token_batch")+",\"sequence\":"+std::to_string(s.sequence)+",\"origin\":\"native-generated\",\"ids\":[";
    for(size_t i=0;i<ids.size();++i){
        if(i)out+=',';out+=std::to_string(ids[i]);const auto id=ids[i];
        std::array<unsigned char,4> bytes{static_cast<unsigned char>(id),static_cast<unsigned char>(id>>8),static_cast<unsigned char>(id>>16),static_cast<unsigned char>(id>>24)};
        check(BCryptHashData(s.hash,bytes.data(),4,0));
        check(BCryptHashData(s.meta_hash,bytes.data(),4,0));unsigned char present=lp.empty()?0:1;check(BCryptHashData(s.meta_hash,&present,1,0));
        if(present){const auto&record=lp[i];float value=record.logprob;uint32_t n=uint32_t(record.alternatives.size());check(BCryptHashData(s.meta_hash,reinterpret_cast<PUCHAR>(&value),4,0));check(BCryptHashData(s.meta_hash,reinterpret_cast<PUCHAR>(&n),4,0));for(auto [other,p]:record.alternatives){check(BCryptHashData(s.meta_hash,reinterpret_cast<PUCHAR>(&other),4,0));check(BCryptHashData(s.meta_hash,reinterpret_cast<PUCHAR>(&p),4,0));}}
    }
    ++s.sequence;s.count+=ids.size();out+="]";
    if(!lp.empty()){out+=",\"logprobs\":[";for(size_t i=0;i<lp.size();++i){if(i)out+=',';std::ostringstream f;f<<std::setprecision(9)<<std::showpoint<<"{\"logprob\":"<<lp[i].logprob<<",\"top_logprobs\":[";for(size_t j=0;j<lp[i].alternatives.size();++j){if(j)f<<',';f<<"{\"token_id\":"<<lp[i].alternatives[j].first<<",\"logprob\":"<<lp[i].alternatives[j].second<<'}';}f<<"]}";out+=f.str();}out+=']';}
    return out+"}";
}
std::string GenerationEmitter::finish(Finish f,const std::string& origin){
    auto& s=*state_;s.active();const auto* name=finish_name(f);
    if(!origin.empty()&&(!s.metadata||!((origin=="eos"||origin=="recipe")&&f==Finish::Stop)&&!(origin=="limit"&&f==Finish::Length)&&!(origin=="user_cancel"&&f==Finish::Cancel)&&!(origin=="nonfinite"&&f==Finish::NonFinite)&&!(origin=="error"&&f==Finish::Error)))throw std::invalid_argument("stop origin/finish");std::array<unsigned char,32> bytes{};
    check(BCryptFinishHash(s.hash,bytes.data(),static_cast<ULONG>(bytes.size()),0));s.ended=true;
    const char* hexchars="0123456789abcdef";std::string digest;for(auto byte:bytes){digest+=hexchars[byte>>4];digest+=hexchars[byte&15];}
    std::string extra;
    if(s.metadata){uint32_t n=uint32_t(origin.size());check(BCryptHashData(s.meta_hash,reinterpret_cast<PUCHAR>(&n),4,0));if(n)check(BCryptHashData(s.meta_hash,reinterpret_cast<PUCHAR>(const_cast<char*>(origin.data())),n,0));std::array<unsigned char,32>meta{};check(BCryptFinishHash(s.meta_hash,meta.data(),32,0));std::string value;for(auto b:meta){value+=hexchars[b>>4];value+=hexchars[b&15];}extra=",\"stop_origin\":"+quote(origin)+",\"metadata_sha256\":"+quote(value);}
    return s.common("finish")+",\"sequence\":"+std::to_string(s.sequence)+",\"generated_count\":"+std::to_string(s.count)+",\"finish\":"+quote(name)+",\"ids_sha256\":"+quote(digest)+extra+"}";
}
}
