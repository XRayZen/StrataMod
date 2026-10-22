#include "dspark_contract.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace strata_ext::dspark {
namespace {
void need(bool ok,const char* message) {if(!ok) throw std::runtime_error(message);}
uint64_t mul(uint64_t a,uint64_t b) {need(!a || b<=UINT64_MAX/a,"shape overflow");return a*b;}
void probability(const std::vector<double>& p) {
    need(!p.empty(),"empty effective distribution");double sum=0;
    for(double x:p) {need(std::isfinite(x)&&x>=0,"effective probability");sum+=x;}
    need(std::abs(sum-1)<=1e-12,"unnormalized effective probability");
}
}
void validate(const SourceSpan& s) {
    need(!s.name.empty()&&s.revision=="ba58445f0818edfc69e680390bc9b4873af8a621"&&
         s.lfs=="02468aa72b7233d50696682817b66ea661ebf387a0b6beecf6954febd8680b1e","source identity");
    need(!s.dims.empty()&&s.dims.size()<=3,"tensor rank");
    const uint64_t block=s.type==0||s.type==1?1:32;
    const uint64_t bytes=s.type==0?4:s.type==1?2:s.type==8?34:s.type==39?17:0;
    need(bytes&&s.dims[0]&&s.dims[0]%block==0,"type/block geometry");
    uint64_t total=mul(s.dims[0]/block,bytes);
    for(size_t i=1;i<s.dims.size();++i) {need(s.dims[i]>0,"zero dimension");total=mul(total,s.dims[i]);}
    need(total==s.tensor_bytes&&s.file_bytes==7965746848ull,"original tensor/file geometry");
    need(s.tensor_offset>=7296&&s.tensor_offset%32==0&&s.tensor_offset<=s.file_bytes&&
         s.tensor_bytes<=s.file_bytes-s.tensor_offset,"original tensor bounds");
    need(s.offset>=s.tensor_offset&&s.offset-s.tensor_offset<=s.tensor_bytes&&s.bytes&&
         s.bytes<=s.tensor_bytes-(s.offset-s.tensor_offset)&&
         (s.offset-s.tensor_offset)%bytes==0&&s.bytes%bytes==0,"fixture block span");
}
void validate(const Request& r) {
    need(r.owner&&r.epoch&&r.width&&r.width<=std::numeric_limits<size_t>::max(),"request geometry/identity");
    need(r.position<=UINT64_MAX-r.width,"position overflow");
    need(r.original_ids.size()==r.width,"original ID payload shape");
    for(auto id:r.original_ids) need(id<129280,"original ID outside vocabulary");
}
void validate(const Request& r,const std::vector<Tap>& taps) {
    validate(r);need(taps.size()==3,"three target taps, not block width");
    for(size_t i=0;i<3;++i) {const auto& t=taps[i];
        need(t.target_layer==37+i&&t.capture_layer==36+i&&t.hc==4&&t.hidden==5120,
             "attention-input tap location/geometry");
        need(t.owner==r.owner&&t.epoch==r.epoch&&t.position==r.position,"tap lifetime provenance");
    }
}
uint32_t widen_f16(uint16_t h) {
    const uint32_t sign=uint32_t(h&0x8000)<<16,exp=(h>>10)&31,frac=h&1023;
    if(exp==31) return sign|0x7f800000u|(frac<<13);
    if(exp) return sign|((exp+112)<<23)|(frac<<13);
    if(!frac) return sign;
    uint32_t f=frac;int exponent=-14;
    while(!(f&1024)) {f<<=1;--exponent;}
    return sign|(uint32_t(exponent+127)<<23)|((f&1023)<<13);
}
std::vector<uint16_t> hc_mean(const std::vector<float>& h) {
    need(h.size()==4*5120,"HC tap geometry");std::vector<uint16_t> out(5120);
    for(size_t d=0;d<5120;++d) {float sum=0;
        for(size_t i=0;i<4;++i) sum=sum+h[i*5120+d];
        float value=sum*0.25f;uint32_t bits;std::memcpy(&bits,&value,4);
        out[d]=uint16_t((bits+0x7fffu+((bits>>16)&1))>>16);
    }return out;
}
float confidence_dot(const std::vector<float>& h,const std::vector<float>& m,const std::vector<float>& w) {
    need(h.size()==5120&&m.size()==256&&w.size()==5376,"confidence concat geometry");float sum=0;
    for(size_t i=0;i<w.size();++i) {float product=(i<h.size()?h[i]:m[i-h.size()])*w[i];sum=sum+product;}
    return sum;
}
double accept(const std::vector<double>& p,const std::vector<double>& q,uint32_t id) {
    probability(p);probability(q);need(p.size()==q.size()&&id<p.size()&&q[id]>0,"actual proposal support");
    return (std::min)(1.,p[id]/q[id]);
}
std::vector<double> residual(const std::vector<double>& p,const std::vector<double>& q) {
    probability(p);probability(q);need(p.size()==q.size(),"p/q vocabulary");std::vector<double> out(p.size());double sum=0;
    for(size_t i=0;i<p.size();++i) {out[i]=(std::max)(0.,p[i]-q[i]);sum+=out[i];}
    need(sum>0,"zero residual cannot follow valid rejection");for(auto& x:out)x/=sum;return out;
}
std::vector<uint32_t> verified_prefix(const std::vector<uint32_t>& ids,const std::vector<bool>& accepted,
                                    uint32_t replacement,uint32_t bonus,bool cancelled) {
    need(ids.size()==accepted.size()&&replacement<129280&&bonus<129280,"verification shape/ID");
    for(auto id:ids)need(id<129280,"proposal original ID");
    if(cancelled)return {};std::vector<uint32_t> out;
    for(size_t i=0;i<ids.size();++i) {out.push_back(accepted[i]?ids[i]:replacement);
        if(!accepted[i]||out.back()==1)return out;}
    out.push_back(bonus);return out;
}
}
