#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
namespace strata_ext::deepseek41::routing {
struct Config {
 float primary=0,secondary=0,ssd=0;
 bool exact()const noexcept{return primary==0&&secondary==0&&ssd==0;}
};
inline float coefficient(const std::string&s){
 if(s.empty()||s.find_first_not_of("0123456789.eE+-")!=std::string::npos)throw std::invalid_argument("routing coefficient decimal in [0,1]");
 size_t n=0;double v;try{v=std::stod(s,&n);}catch(...){throw std::invalid_argument("routing coefficient decimal in [0,1]");}
 if(n!=s.size()||!std::isfinite(v)||v<0||v>1)throw std::invalid_argument("routing coefficient decimal in [0,1]");
 return v==0?0.f:float(v);
}
enum class Tier:uint8_t {Primary,Secondary,Ram};
// No heap storage or allocation at zero-mode slot publication. Source identity is
// exact immutable revision/LFS bytes + shard/size, not a probabilistic hash.
struct Record {
 std::array<char,65> revision{},lfs{};uint64_t source_size=0,offset=0,bytes=0,k=0,generation=0;
 uint32_t shard=0,type=0,layer=0,kind=0;bool relevant=false,known=false;
};
struct Span {std::string source,tensor;uint64_t offset=0,bytes=0;Tier tier=Tier::Primary;};
struct Snapshot {std::vector<Span> spans;bool complete=true;uint64_t owner=0,generation=0;};
struct Expected {std::array<Span,3> spans;};
enum class Coverage:uint8_t {Primary,Secondary,Ram,Partial,None,Unknown};
struct Policy {
 Config config;std::array<float,40*384> delta{};std::array<bool,40> active{};
 std::array<uint64_t,6> counts{};std::array<uint8_t,40*384> coverage{};std::string binding,digest;
 // Observation only, never an input to selection. All target calls are serialized.
 bool decode_used=false;
 bool neutral()const noexcept{return std::none_of(active.begin(),active.end(),[](bool b){return b;});}
};
using Intervals=std::vector<std::pair<uint64_t,uint64_t>>;
using Index=std::map<std::pair<std::string,std::string>,std::array<Intervals,3>>;
inline Index index(const std::vector<Snapshot>&snapshots){
 Index out;for(const auto&s:snapshots)for(const auto&v:s.spans){
  if(unsigned(v.tier)>=3||!v.bytes||v.offset>UINT64_MAX-v.bytes)throw std::invalid_argument("routing span extent");
  out[{v.source,v.tensor}][unsigned(v.tier)].emplace_back(v.offset,v.offset+v.bytes);
 }
 for(auto&item:out)for(auto&v:item.second){std::sort(v.begin(),v.end());Intervals merged;for(auto x:v){if(!merged.empty()&&x.first<=merged.back().second)merged.back().second=std::max(merged.back().second,x.second);else merged.push_back(x);}v.swap(merged);}return out;
}
inline std::pair<bool,bool> covered(const Index&idx,const Span&s,Tier tier){
 if(!s.bytes||s.offset>UINT64_MAX-s.bytes)throw std::invalid_argument("routing expected extent");
 auto f=idx.find({s.source,s.tensor});if(f==idx.end())return {false,false};auto&v=f->second[unsigned(tier)];auto end=s.offset+s.bytes;
 auto i=std::lower_bound(v.begin(),v.end(),s.offset,[](auto x,uint64_t n){return x.second<=n;});
 bool any=i!=v.end()&&i->first<end;return {any&&i->first<=s.offset&&i->second>=end,any};
}
inline Coverage classify(const Index&idx,const Expected&e,bool complete){
 if(!complete)return Coverage::Unknown;
 bool any=false;std::array<bool,3>full{true,true,true};for(auto&s:e.spans)for(unsigned t=0;t<3;++t){auto q=covered(idx,s,Tier(t));full[t]=full[t]&&q.first;any|=q.second;}
 // Unavailable owners may contain bytes changing tier priority; fail neutral.
 if(full[0])return Coverage::Primary;if(full[1])return Coverage::Secondary;if(full[2])return Coverage::Ram;return any?Coverage::Partial:Coverage::None;
}
inline float correction(Coverage c,const Config&p){return c==Coverage::Primary?p.primary:c==Coverage::Secondary?p.secondary:c==Coverage::None?-p.ssd:0.f;}
inline std::shared_ptr<Policy> derive(const Config&c,const std::vector<Snapshot>&s,const std::array<Expected,40*384>&expected,const std::string&binding){
 if(c.exact())return {};auto p=std::make_shared<Policy>();p->config=c;p->binding=binding;auto idx=index(s);bool complete=true;for(auto&x:s)complete&=x.complete;
 for(unsigned i=0;i<p->delta.size();++i){auto v=classify(idx,expected[i],complete);++p->counts[unsigned(v)];p->coverage[i]=uint8_t(v);p->delta[i]=correction(v,c);p->active[i/384]=p->active[i/384]||p->delta[i]!=0;}return p;
}
}
