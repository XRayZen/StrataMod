#include "native_reader.hpp"
#include "strata/artifact/dequant.hpp"
#include <fstream>
#include <limits>
#include <map>
#include <set>
#include <algorithm>

namespace strata_ext::artifact {
namespace {
uint64_t add(uint64_t a, uint64_t b) {
    if (b > UINT64_MAX - a) throw std::runtime_error("offset overflow");
    return a+b;
}
uint64_t multiply(uint64_t a, uint64_t b) {
    if (a && b > UINT64_MAX/a) throw std::runtime_error("shape overflow");
    return a*b;
}
std::pair<uint64_t,uint64_t> geometry(uint32_t type) {
    switch(type) {
    case 0:return {1,4}; case 8:return {32,34}; case 39:return {32,17}; case 43:return {32,33};
    default:throw std::runtime_error("unqualified native layout");
    }
}
uint64_t integer(const strata::GgufFile& f, const char* key) {
    const auto* v=f.get(key);
    if (!v || !v->is_num() || v->type==strata::MetaType::BOOL || v->type==strata::MetaType::F32 || v->type==strata::MetaType::F64)
        throw std::runtime_error(std::string("missing/noninteger ")+key);
    return v->u;
}
float from_bits(uint32_t bits) {
    float out;std::memcpy(&out,&bits,4);return out;
}
float e4m3(uint8_t code) {
    const unsigned exponent=(code>>3)&15, fraction=code&7;
    float magnitude;
    if(exponent==15 && fraction==7) return std::numeric_limits<float>::quiet_NaN();
    if(exponent==0) magnitude=std::ldexp(static_cast<float>(fraction),-9);
    else magnitude=std::ldexp(static_cast<float>(8+fraction),static_cast<int>(exponent)-10);
    return code&128 ? -magnitude : magnitude;
}
}

PrefixIndex inspect_prefix(const std::filesystem::path& path, uint64_t source_bytes) {
    // Base currently uses CreateFileA: only the supplied staging paths are
    // exercised. No general Unicode/path compatibility is asserted here.
    strata::GgufFile f(path.string());
    PrefixIndex result{integer(f,"split.no"),integer(f,"split.count"),integer(f,"split.tensors.count"),{}};
    if (!result.split_count || result.split_no>=result.split_count || !result.split_total)
        throw std::runtime_error("invalid split identity");
    const uint64_t alignment=f.alignment(), start=f.data_start();
    if (!alignment || (alignment&(alignment-1)) || start>source_bytes)
        throw std::runtime_error("invalid alignment/source header bound");
    for(const auto& t:f.tensors()) {
        const auto [elements,block_bytes]=geometry(t.type);
        if(t.shape.empty() || t.shape.size()>4 || !t.shape[0] || t.shape[0]%elements)
            throw std::runtime_error("invalid native shape/block");
        TensorSpan span;
        span.shard_index=static_cast<uint32_t>(result.split_no+1);span.type_id=t.type;span.name=t.name;span.dims_ggml=t.shape;
        span.row_bytes=multiply(t.shape[0]/elements,block_bytes);span.bytes=span.row_bytes;
        for(size_t i=1;i<t.shape.size();++i) {
            if(!t.shape[i]) throw std::runtime_error("zero tensor dimension");
            span.bytes=multiply(span.bytes,t.shape[i]);
        }
        if(t.offset%alignment) throw std::runtime_error("unaligned tensor offset");
        span.absolute_offset=add(start,t.offset);
        if(add(span.absolute_offset,span.bytes)>source_bytes) throw std::runtime_error("tensor outside logical source");
        result.tensors.push_back(std::move(span));
    }
    auto sorted=result.tensors;
    std::sort(sorted.begin(),sorted.end(),[](const auto& a,const auto& b){return a.absolute_offset<b.absolute_offset;});
    uint64_t end=start;
    for(const auto& span:sorted) {
        if(span.absolute_offset<end) throw std::runtime_error("tensor overlap");
        end=add(span.absolute_offset,span.bytes);
    }
    return result;
}

std::vector<TensorSpan> merge_prefixes(const std::vector<PrefixIndex>& indexes) {
    if(indexes.empty()) throw std::runtime_error("no shards");
    const uint64_t count=indexes.size(), total=indexes.front().split_total;
    std::set<uint64_t> shards;std::set<std::string> names;std::vector<TensorSpan> result;
    for(const auto& index:indexes) {
        if(index.split_count!=count || index.split_total!=total || index.split_no>=count || !shards.insert(index.split_no).second)
            throw std::runtime_error("missing/duplicate/mixed split identity");
        for(const auto& tensor:index.tensors) {
            if(!names.insert(tensor.name).second) throw std::runtime_error("duplicate tensor across shards");
            result.push_back(tensor);
        }
    }
    if(result.size()!=total) throw std::runtime_error("incomplete tensor coverage");
    return result;
}

std::vector<uint8_t> FixtureView::read_exact(uint64_t offset,uint64_t count) const {
    const uint64_t end=add(source_absolute_offset,bytes);
    if(offset<source_absolute_offset || offset>end || count>end-offset || !count)
        throw std::runtime_error("read outside logical fixture view");
    if(std::filesystem::file_size(path)!=bytes) throw std::runtime_error("physical short/changed fixture view");
    const uint64_t physical=offset-source_absolute_offset;
    if(count>static_cast<uint64_t>((std::numeric_limits<std::streamsize>::max)()) || physical>static_cast<uint64_t>((std::numeric_limits<std::streamoff>::max)()))
        throw std::runtime_error("read exceeds native stream range");
    std::ifstream stream(path,std::ios::binary);
    if(!stream || !stream.seekg(static_cast<std::streamoff>(physical))) throw std::runtime_error("file open/seek failure");
    std::vector<uint8_t> raw(static_cast<size_t>(count));
    stream.read(reinterpret_cast<char*>(raw.data()),static_cast<std::streamsize>(count));
    if(stream.gcount()!=static_cast<std::streamsize>(count)) throw std::runtime_error("physical short read");
    return raw;
}

std::vector<float> decode_blocks(uint32_t type,const std::vector<uint8_t>& raw) {
    const auto [values,bytes]=geometry(type);
    if(raw.empty() || raw.size()%bytes) throw std::runtime_error("partial native block");
    std::vector<float> out(raw.size()/bytes*values);
    static constexpr int8_t doubled[16]={0,1,2,3,4,6,8,12,0,-1,-2,-3,-4,-6,-8,-12};
    for(size_t block=0;block<raw.size()/bytes;++block) {
        const auto* p=raw.data()+block*bytes;auto* dst=out.data()+block*values;
        if(type==0) std::memcpy(dst,p,4);
        else if(type==8) strata::dequantize_q8_0(p,dst);
        else if(type==39) {
            // FP32 half-scale times integer doubled E2M1; zero indices0/8
            // are canonical +0, independently of ideal signed E2M1.
            const uint32_t e=p[0];
            const float scale=from_bits(e<2 ? (0x00200000u<<e) : ((e-1)<<23));
            for(size_t i=0;i<16;++i) {dst[i]=scale*doubled[p[1+i]&15];dst[i+16]=scale*doubled[p[1+i]>>4];}
        } else {
            // Explicit native FP32 scale stage, including e255 -> +inf.
            const float scale=p[0]==0 ? from_bits(0x00400000u) : from_bits(static_cast<uint32_t>(p[0])<<23);
            for(size_t i=0;i<32;++i) dst[i]=e4m3(p[1+i])*scale;
        }
    }
    return out;
}
}
