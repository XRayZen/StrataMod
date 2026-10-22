#include "native_reader.hpp"
#include <iostream>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <cstring>
#include <cmath>

using namespace strata_ext::artifact;
uint64_t number(const char* s) {
    if(!*s || *s=='-') throw std::runtime_error("invalid unsigned number");
    size_t n=0;const auto v=std::stoull(s,&n);if(s[n])throw std::runtime_error("trailing integer text");return v;
}
std::string quote(const std::string& s) {
    std::string out="\"";
    for(unsigned char c:s) {if(c=='"' || c=='\\')out+='\\';if(c<32)throw std::runtime_error("control character in tensor name");out+=static_cast<char>(c);}
    return out+"\"";
}
int main(int argc,char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="--identity") {std::cout<<"{\"source_sha256\":\""<<T08_SOURCE_SHA<<"\"}";return 0;}
        if(argc==3 && std::string(argv[1])=="--index") {
            std::ifstream list(argv[2]);if(!list)throw std::runtime_error("missing prefix list");
            std::vector<PrefixIndex> indexes;std::string line;
            while(std::getline(list,line)) {
                if(!line.empty() && line.back()=='\r')line.pop_back();
                const auto tab=line.find('\t');if(tab==std::string::npos)throw std::runtime_error("invalid prefix list row");
                indexes.push_back(inspect_prefix(line.substr(tab+1),number(line.substr(0,tab).c_str())));
            }
            const auto spans=merge_prefixes(indexes);std::cout<<"{\"tensors\":[";bool first=true;
            for(const auto& t:spans) {
                if(!first)std::cout<<",";first=false;
                std::cout<<"{\"shard_index\":"<<t.shard_index<<",\"name\":"<<quote(t.name)<<",\"type_id\":"<<t.type_id<<",\"dims_ggml\":[";
                for(size_t i=0;i<t.dims_ggml.size();++i){if(i)std::cout<<",";std::cout<<t.dims_ggml[i];}
                std::cout<<"],\"row_bytes\":"<<t.row_bytes<<",\"absolute_offset\":"<<t.absolute_offset<<",\"bytes\":"<<t.bytes<<"}";
            }
            std::cout<<"]}";return 0;
        }
        if(argc==8 && std::string(argv[1])=="--decode") {
            const auto type=number(argv[2]);if(type>UINT32_MAX)throw std::runtime_error("type id overflow");
            FixtureView view{argv[3],number(argv[4]),number(argv[5])};
            const auto decoded=decode_blocks(static_cast<uint32_t>(type),view.read_exact(number(argv[6]),number(argv[7])));
            std::cout<<"{\"bits\":[";
            for(size_t i=0;i<decoded.size();++i) {uint32_t b;std::memcpy(&b,&decoded[i],4);if(i)std::cout<<",";std::cout<<"\""<<std::hex<<std::setw(8)<<std::setfill('0')<<b<<"\"";}
            std::cout<<"],\"classes\":[";
            for(size_t i=0;i<decoded.size();++i){if(i)std::cout<<",";std::cout<<quote(std::isnan(decoded[i])?"nan":std::isinf(decoded[i])?(std::signbit(decoded[i])?"-inf":"+inf"):"finite");}
            std::cout<<"]}";return 0;
        }
        if(argc==8 && std::string(argv[1])=="--copy") {
            FixtureView view{argv[2],number(argv[3]),number(argv[4])};
            const auto raw=view.read_exact(number(argv[5]),number(argv[6]));
            std::ofstream out(argv[7],std::ios::binary);out.write(reinterpret_cast<const char*>(raw.data()),raw.size());if(!out)throw std::runtime_error("output write failed");
            std::cout<<"{}";return 0;
        }
        throw std::runtime_error("invalid invocation");
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 2;}
}
