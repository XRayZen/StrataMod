#pragma once
#include "../quant/quant.hpp"
#include "../cache/lease_queue.hpp"
#include "../stats/measurement.hpp"
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>

namespace strata_ext::graph {
// One owner, one entry. Epoch/request generation belong to current Launch, not Key.
struct Key {
 std::string source,abi;
 uintptr_t packed=0,input=0,output=0,stream=0,slot=0;
 size_t packed_bytes=0,input_bytes=0,output_bytes=0,rows=0,k=0,batch=0,stride=0;
 uint32_t type=0;int device=-1;
 uint64_t resident_owner=0,slot_generation=0,activation_incarnation=0,activation_generation=0;
 auto fields()const{return std::tie(source,abi,packed,input,output,stream,slot,packed_bytes,input_bytes,output_bytes,rows,k,batch,stride,type,device,resident_owner,slot_generation,activation_incarnation,activation_generation);}
 bool operator==(const Key& other)const{return fields()==other.fields();}
};
struct Launch {
 Key key;
 const cache::ResidentLease* reader=nullptr;
 const quant::ProjectionLease* packed_lease=nullptr;
 const quant::ProjectionLease* activation=nullptr;
 const measurement::Identity* request=nullptr;
 const measurement::Identity* current=nullptr;
 bool resident_hit=false,cancelled=false;
};
enum class Decision { Cancelled,Eager,Prepare,Replay };
inline void require(bool v,const char*why){if(!v)throw std::runtime_error(why);}
inline size_t checked_mul(size_t a,size_t b){require(!a||b<=SIZE_MAX/a,"graph geometry overflow");return a*b;}
inline size_t checked_add(size_t a,size_t b){require(b<=SIZE_MAX-a,"graph geometry overflow");return a+b;}
inline bool same_identity(const measurement::Identity&a,const measurement::Identity&b){return std::tie(a.fixture_sha256,a.asset_sha256,a.bundle_sha256,a.request_id,a.epoch,a.phase)==std::tie(b.fixture_sha256,b.asset_sha256,b.bundle_sha256,b.request_id,b.epoch,b.phase);}
// Real replay preflight, also compiled and exercised without HIP by the host fixture.
inline Decision preflight(const Launch& r,const Key* cached,bool enabled){
 const auto&k=r.key;
 require(r.request&&r.current&&same_identity(*r.request,*r.current),"graph current request identity");
 if(r.cancelled)return Decision::Cancelled;
 require(!k.source.empty()&&!k.abi.empty()&&k.packed&&k.input&&k.output&&k.stream&&k.device>=0&&k.activation_incarnation,"graph launch declaration");
 require(r.reader&&r.reader->active&&!r.reader->writer&&r.reader->slot,"graph needs actual active reader");
 const auto&s=*r.reader->slot;
 require(k.slot==reinterpret_cast<uintptr_t>(&s)&&s.valid&&!s.quarantined&&!s.writer&&s.readers&&
  r.reader->owner==s.owner&&k.resident_owner==s.owner&&r.reader->generation==s.generation&&
  k.slot_generation==s.generation&&k.packed==s.address&&k.packed_bytes<=s.capacity,"graph reader slot ownership");
 require(r.packed_lease&&r.packed_lease->active&&r.packed_lease->generation&&r.activation&&r.activation->active&&
  r.activation->generation&&r.activation->generation==k.activation_generation,"graph projection/activation lease");
 require(k.rows&&k.k&&(k.batch==1||k.batch==2||k.batch==4||k.batch==8)&&k.stride>=k.rows,"graph full-K/batch/stride");
 const auto count=checked_mul(k.rows,k.k);
 size_t packed=0;
 if(k.type==0)packed=checked_mul(count,4);
 else {require(k.k%32==0&&(k.type==8||k.type==39||k.type==43),"graph native format");packed=checked_mul(count/32,k.type==8?34:k.type==39?17:33);}
 require(packed==k.packed_bytes,"graph packed byte geometry");
 const auto input=checked_mul(checked_mul(k.batch,k.k),4);
 require(input<=k.input_bytes&&checked_mul(checked_add(checked_mul(k.batch-1,k.stride),k.rows),4)<=k.output_bytes,"graph batch capacity");
 require(k.packed_bytes<=UINTPTR_MAX-k.packed&&k.input_bytes<=UINTPTR_MAX-k.input&&k.output_bytes<=UINTPTR_MAX-k.output,"graph pointer range overflow");
 auto overlap=[](uintptr_t a,size_t n,uintptr_t b,size_t m){return a<b?b-a<n:a-b<m;};
 for(size_t b=0;b<k.batch;++b){auto target=k.output+checked_mul(checked_mul(b,k.stride),4);auto bytes=checked_mul(k.rows,4);
  require(!overlap(target,bytes,k.packed,k.packed_bytes)&&!overlap(target,bytes,k.input,input),"graph output overlaps live packed/input");}
 if(!enabled||!r.resident_hit)return Decision::Eager;
 return cached&&*cached==k?Decision::Replay:Decision::Prepare;
}
inline bool clean_eager_fallback(bool may_have_submitted,bool capture_ended,bool stream_clean){return !may_have_submitted&&capture_ended&&stream_clean;}
struct Stats {
 uint64_t eager=0,replays=0,captures=0,recaptures=0,capture_fallbacks=0;
 uint64_t metadata_bytes=0,aliased_payload_bytes=0,explicit_device_owned_bytes=0;
 // metadata_bytes includes static object storage + string capacities, a
 // conservative accounting bound (SSO may reside inside the static object).
 bool metadata_is_upper_bound=true,hip_internal_bytes_known=false,retained=false;
};
// Serialized Primary owner supplies and retains ALL leases/storage until existing
// lastuse event. No request/lease pointers survive dispatch. reset before activation
// owner retirement; close before Primary stream/storage destruction. Failed close
// retains handles and requires the caller to retain original storage too.
class PrimaryProjection {
public:
 explicit PrimaryProjection(bool enabled=false);
 ~PrimaryProjection();
 PrimaryProjection(const PrimaryProjection&)=delete;
 PrimaryProjection&operator=(const PrimaryProjection&)=delete;
 Decision dispatch(const Launch&);
 bool close();
 Stats stats()const;
private:struct Impl;std::unique_ptr<Impl> p_;
};
}
