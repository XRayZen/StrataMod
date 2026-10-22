#include "dspark_contract.hpp"
#include "native_reader.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <cstring>
#include <functional>
#include <algorithm>

using namespace strata_ext;
template<class T>void write(const std::filesystem::path& p,const std::vector<T>& x) {
 std::ofstream f(p,std::ios::binary);if(!f||!f.write(reinterpret_cast<const char*>(x.data()),x.size()*sizeof(T)))throw std::runtime_error("output write");
}
int main(int argc,char** argv) {
 try {
  if(argc==2&&std::string(argv[1])=="--identity"){std::cout<<"{\"source_sha256\":\""<<T37_SOURCE_SHA<<"\"}";return 0;}
  if(argc!=2)throw std::runtime_error("fixture directory required");
  const auto dir=std::filesystem::u8path(argv[1]);int rejected=0,positive=0;
  auto bad=[&](std::function<void()> fn){try{fn();}catch(const std::exception&){++rejected;return;}throw std::runtime_error("invalid contract accepted");};
  dspark::Request request{1,1,7,6,{3,128799,128799,128799,128799,128799}};
  std::vector<dspark::Tap> taps;for(uint32_t i=0;i<3;++i)taps.push_back({37+i,36+i,4,5120,1,1,7});
  for(uint64_t width:{1ull,5ull,6ull}){auto r=request;r.width=width;r.original_ids.resize(size_t(width));dspark::validate(r,taps);++positive;}
  for(int which=0;which<8;++which)bad([&]{auto r=request;auto t=taps;
   if(which==0)r.epoch=2;if(which==1)r.owner=2;if(which==2)t[1].target_layer=37;
   if(which==3)t[2].capture_layer=39;if(which==4)t[0].hc=1;if(which==5)r.original_ids[0]=129280;
   if(which==6)r.width=5;if(which==7)r.position=UINT64_MAX;dspark::validate(r,t);});
  const std::vector<uint16_t> codes{0,32768,1,1023,1024,15360,48128,31743,64511};std::vector<uint32_t> bits;
  for(auto c:codes)bits.push_back(dspark::widen_f16(c));write(dir/"f16-literal.out",bits);
  std::vector<float> hc(4*5120);for(size_t i=0;i<4;++i)std::fill(hc.begin()+i*5120,hc.begin()+(i+1)*5120,std::vector<float>{0,2,4,10}[i]);
  write(dir/"tap.out",dspark::hc_mean(hc));
  std::vector<float> h(5120),m(256),w(5376);h[0]=2;h.back()=-1;m[0]=.5f;m.back()=-4;w[0]=1;w[5119]=3;w[5120]=4;w.back()=-2;
  std::vector<float> confidence{dspark::confidence_dot(h,m,w)};
  for(auto& x:w)x=-x;confidence.push_back(dspark::confidence_dot(h,m,w));
  std::fill(w.begin(),w.end(),0);confidence.push_back(dspark::confidence_dot(h,m,w));
  std::fill(h.begin(),h.end(),0);std::fill(m.begin(),m.end(),0);h[0]=1000;w[0]=1;
  confidence.push_back(dspark::confidence_dot(h,m,w));write(dir/"confidence-literal.out",confidence);
  const std::vector<double> p{.5,.25,.125,.125},q{.25,.25,.25,.25};std::vector<double> probs;
  for(uint32_t i=0;i<4;++i)probs.push_back(dspark::accept(p,q,i));auto res=dspark::residual(p,q);probs.insert(probs.end(),res.begin(),res.end());write(dir/"pq.out",probs);
  bad([&]{dspark::accept({1,0},{1,0},1);});bad([&]{dspark::accept({.5,.5},{.5,.4},0);});bad([&]{dspark::residual(p,p);});
  write(dir/"first-reject.out",dspark::verified_prefix({5,6,7},{true,false,true},37,1024,false));
  write(dir/"all-accept.out",dspark::verified_prefix({5,6},{true,true},37,1024,false));
  write(dir/"eos.out",dspark::verified_prefix({5,1,7},{true,true,true},37,1024,false));
  write(dir/"cancel.out",dspark::verified_prefix({5},{true},37,1024,true));
  std::ifstream list(dir/"spans.tsv");std::string line;size_t decoded=0;
  while(std::getline(list,line)) {
   std::istringstream input(line);std::string key,dims;dspark::SourceSpan s;
   input>>key>>s.name>>s.type>>dims>>s.tensor_offset>>s.tensor_bytes>>s.offset>>s.bytes;
   s.file_bytes=7965746848ull;s.revision="ba58445f0818edfc69e680390bc9b4873af8a621";s.lfs="02468aa72b7233d50696682817b66ea661ebf387a0b6beecf6954febd8680b1e";
   std::istringstream ds(dims);std::string d;while(std::getline(ds,d,','))s.dims.push_back(std::stoull(d));
   if(!input)throw std::runtime_error("span descriptor parse");dspark::validate(s);++positive;
   for(int which=0;which<6;++which)bad([&]{auto t=s;if(which==0)t.revision="wrong";if(which==1)t.lfs="wrong";if(which==2)t.offset=t.tensor_offset+t.tensor_bytes;if(which==3)++t.tensor_bytes;if(which==4)t.type=43;if(which==5)t.dims[0]=0;dspark::validate(t);});
   artifact::FixtureView view{dir/(key+".raw"),s.offset,s.bytes};auto raw=view.read_exact(s.offset,s.bytes);std::vector<float> values;
   if(s.type==1){for(size_t i=0;i<raw.size();i+=2){uint16_t code;std::memcpy(&code,raw.data()+i,2);auto b=dspark::widen_f16(code);float x;std::memcpy(&x,&b,4);values.push_back(x);}}
   else values=artifact::decode_blocks(s.type,raw);
   write(dir/(key+".out"),values);decoded+=values.size();
  }
  if(!positive||!decoded)throw std::runtime_error("no real span fixtures");
  std::ifstream controls(dir/"controls.tsv");
  while(std::getline(controls,line)) {std::istringstream row(line);std::string key;uint32_t type;uint64_t size;
   row>>key>>type>>size;if(!row)throw std::runtime_error("control descriptor");
   auto raw=artifact::FixtureView{dir/(key+".raw"),0,size}.read_exact(0,size);
   write(dir/(key+".out"),artifact::decode_blocks(type,raw));}
  std::cout<<"{\"native_rejections\":"<<rejected<<",\"native_positives\":"<<positive<<",\"decoded_values\":"<<decoded<<"}";
 }catch(const std::exception& e){std::cerr<<e.what();return 2;}
}
