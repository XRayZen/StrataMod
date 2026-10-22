#pragma once
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
#include <cmath>

namespace strata_ext::deepseek41 {
// Exact mathematical identity, deliberately excluding request ID and sampler.
// Caller derives these fields from immutable source/config and actual owners.
struct PrefixMathKey {
 std::string asset,bundle,mode,primary,secondary,math="canonical";
 uint64_t epoch=0,context=0;
 std::vector<uint32_t> assignment;
 std::optional<uint32_t> cut;
 bool operator==(const PrefixMathKey&o)const {
  return asset==o.asset&&bundle==o.bundle&&mode==o.mode&&primary==o.primary&&secondary==o.secondary&&math==o.math&&epoch==o.epoch&&context==o.context&&assignment==o.assignment&&cut==o.cut;
 }
};
enum class PrefixAction { Fresh,Append,Logits };
struct PrefixDecision {PrefixAction action=PrefixAction::Fresh;uint64_t reused=0;};
inline PrefixDecision prefix_decision(const PrefixMathKey&prior,const PrefixMathKey&next,
 const std::vector<uint32_t>&processed,const std::vector<uint8_t>&mask,
 const std::vector<uint32_t>&prompt,const std::vector<uint8_t>&incoming_mask,
 uint64_t cursor,bool healthy,bool has_logits,bool full_logits,bool reset=false) {
 auto need=[](bool b,const char*s){if(!b)throw std::invalid_argument(s);};
 need(next.epoch&&next.context&&next.context<=1048576,"prefix capacity/epoch");
 need(processed.size()==mask.size()&&prompt.size()==incoming_mask.size(),"prefix explicit mask geometry");
 need(prompt.size()<=next.context,"prefix prompt exceeds capacity");
 for(auto x:processed)need(x<129280,"prefix original token ID");
 for(auto x:prompt)need(x<129280,"prefix original token ID");
 for(auto x:mask)need(x<=1,"prefix image mask");
 for(auto x:incoming_mask)need(x<=1,"prefix image mask");
 const auto n=processed.size();
 if(!healthy||!has_logits||full_logits||reset||!n||cursor!=n||!(prior==next)||next.math!="canonical"||prompt.size()<n)return {};
 for(size_t i=0;i<n;++i)if(processed[i]!=prompt[i]||mask[i]!=incoming_mask[i])return {};
 return {prompt.size()==n?PrefixAction::Logits:PrefixAction::Append,uint64_t(n)};
}
// Host metadata for one live mathematical sequence. There is no state snapshot.
// Caller invalidates the Core if a post-operation metadata commit ever fails.
class PrefixState {
 PrefixMathKey key_;
 std::vector<uint32_t> ids_;
 std::vector<uint8_t> mask_;
 std::vector<float> logits_;
 bool reusable_=false;uint64_t logical_capacity_=0;
 static void need(bool b,const char*s){if(!b)throw std::invalid_argument(s);}
public:
 void allocate(uint64_t context){
  invalidate();logical_capacity_=0;
  need(context&&context<=1048576,"prefix storage capacity");
  // Touch the real metadata allocation before owner budget measurement; it is
  // already in fresh available and must not be deducted a second time.
  try{ids_.resize(size_t(context));mask_.resize(size_t(context));logits_.resize(129280);}
  catch(...){invalidate();throw;}
  ids_.clear();mask_.clear();logits_.clear();logical_capacity_=context;
 }
 // Key string/assignment heap is separately unknown until ABI-bound accounting.
 uint64_t host_known_subset_bytes()const{return sizeof(*this)+ids_.capacity()*sizeof(uint32_t)+mask_.capacity()+logits_.capacity()*sizeof(float);}
 PrefixDecision decide(const PrefixMathKey&key,const std::vector<uint32_t>&prompt,
  const std::vector<uint8_t>&mask,uint64_t cursor,bool healthy,bool full_logits=false,bool reset=false)const{
  return prefix_decision(key_,key,ids_,mask_,prompt,mask,cursor,healthy&&reusable_,logits_.size()==129280,full_logits,reset);
 }
 void begin_fresh(PrefixMathKey key){
  reusable_=false;key_=std::move(key);ids_.clear();mask_.clear();logits_.clear();
 }
 void begin_append()noexcept{reusable_=false;}
 void processed(const std::vector<uint32_t>&ids,const std::vector<uint8_t>&mask){
  reusable_=false;
  need(ids_.size()<=logical_capacity_&&ids.size()<=logical_capacity_-ids_.size()&&ids.size()==mask.size()&&ids.size()<=ids_.capacity()-ids_.size()&&mask.size()<=mask_.capacity()-mask_.size(),"prefix committed ID capacity");
  for(auto x:ids)need(x<129280,"prefix committed original ID");for(auto x:mask)need(x<=1,"prefix committed mask");
  ids_.insert(ids_.end(),ids.begin(),ids.end());mask_.insert(mask_.end(),mask.begin(),mask.end());
 }
 void processed(uint32_t id,bool image=false){
  reusable_=false;
  need(id<129280&&ids_.size()<logical_capacity_&&ids_.size()<ids_.capacity()&&mask_.size()<mask_.capacity(),"prefix committed token capacity");
  ids_.push_back(id);mask_.push_back(image?1:0);
 }
 void publish(const std::vector<float>&logits,uint64_t cursor){
  reusable_=false;
  need(cursor==ids_.size()&&cursor&&!ids_.empty()&&logits.size()==129280&&logits_.capacity()>=129280,"prefix raw logit position");
  for(auto x:logits)need(std::isfinite(x),"prefix finite raw logits");
  if(&logits!=&logits_)logits_.assign(logits.begin(),logits.end());
  reusable_=key_.math=="canonical";
 }
 void invalidate()noexcept{reusable_=false;ids_.clear();mask_.clear();logits_.clear();}
 const std::vector<float>&logits()const{return logits_;}
 uint64_t processed_count()const{return ids_.size();}
};
}
