#include "../../native/cache/primary_supply.hpp"
#include <chrono>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "key-definition.inc"
#include "key-metadata.inc"

using strata_ext::cache::SupplyMatrix;
struct Slot {std::string key;bool valid=true,busy=false,quarantine=false;};
struct Result {long long index=-1;size_t key_calls=0,comparisons=0;long long elapsed_ns=0;};
Result lookup(const SupplyMatrix&m,const std::vector<Slot>&slots,bool ram,bool hoist){
 Result r;auto start=std::chrono::steady_clock::now();
 auto key=[&](){++r.key_calls;return m.key();};
 const std::string fixed=hoist?key():std::string();
 for(size_t i=0;i<slots.size();++i){
  const auto&s=slots[i];
  if(ram&&(s.busy||!s.valid))continue;
  ++r.comparisons;
  bool equal=hoist?(s.key==fixed):(s.key==key());
  if(equal&&(ram||(s.valid&&!s.quarantine))){r.index=static_cast<long long>(i);break;}
 }
 r.elapsed_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();return r;
}
std::string hex(const std::string&s){static const char*h="0123456789abcdef";std::string out;for(unsigned char c:s){out+=h[c>>4];out+=h[c&15];}return out;}
int main(){try{
 const auto m=metadata_matrix();const auto expected=m.key();metadata_check();
 if(hex(expected)!=metadata_key_hex())throw std::runtime_error("independent key bytes differ");
 std::cout<<"{\"schema\":\"T35-key-lookup/v1\",\"key_hex\":\""<<hex(expected)<<"\",\"cases\":[";
 bool comma=false;
 for(bool ram:{false,true})for(size_t count:ram?std::vector<size_t>{2,8768,15262}:std::vector<size_t>{2,7745}){
  for(const std::string kind:{"cold","first","middle","last","miss","blocked"}){
   std::vector<Slot> slots(count);for(auto&s:slots){s.key=expected+"!";s.valid=kind!="cold";}
   if(kind=="first")slots.front().key=expected;
   if(kind=="middle")slots[count/2].key=expected;
   if(kind=="last")slots.back().key=expected;
   if(kind=="blocked"){slots[0].key=expected;slots[0].busy=ram;slots[0].quarantine=!ram;slots[1].key=expected;}
   const long long wanted=kind=="first"?0:kind=="middle"?static_cast<long long>(count/2):kind=="last"?static_cast<long long>(count-1):kind=="blocked"?1:-1;
   for(char arm:std::string("ABBA")){
    auto result=lookup(m,slots,ram,arm=='B');if(result.index!=wanted)throw std::runtime_error("lookup result differs");
    if(comma)std::cout<<',';comma=true;
    std::cout<<"{\"ram\":"<<(ram?"true":"false")<<",\"slots\":"<<count<<",\"kind\":\""<<kind<<"\",\"arm\":\""<<arm<<"\",\"index\":"<<result.index<<",\"key_calls\":"<<result.key_calls<<",\"comparisons\":"<<result.comparisons<<",\"elapsed_ns\":"<<result.elapsed_ns<<'}';
   }
  }
 }
 std::cout<<"],\"original_weight_read_bytes\":0,\"GPU\":0,\"physical_io\":null,\"model_performance_qualified\":false}\n";
 return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
