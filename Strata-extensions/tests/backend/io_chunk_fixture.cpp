#include "span_provider.hpp"
#include "strata/platform/direct_file.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <fcntl.h>
#include <io.h>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <vector>
using namespace strata_ext;
using namespace strata_ext::io;
using Clock=std::chrono::steady_clock;
using Direct=strata::platform::DirectFile;
constexpr uint64_t bytes=2097152;
void require(bool x,const char* why){if(!x)throw std::runtime_error(why);}
double seconds(Clock::time_point start){return std::chrono::duration<double>(Clock::now()-start).count();}
std::string sha(const std::vector<unsigned char>& data){
 BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;DWORD needed=0,size=0;unsigned char digest[32];
 require(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0,"SHA provider");
 auto status=BCryptGetProperty(alg,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&size),sizeof(size),&needed,0);
 std::vector<unsigned char> object(size);
 if(status>=0)status=BCryptCreateHash(alg,&hash,object.data(),size,nullptr,0,0);
 if(status>=0)status=BCryptHashData(hash,const_cast<PUCHAR>(data.data()),ULONG(data.size()),0);
 if(status>=0)status=BCryptFinishHash(hash,digest,sizeof(digest),0);
 if(hash)BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(alg,0);require(status>=0,"SHA failed");
 std::ostringstream s;s<<std::hex<<std::setfill('0');for(auto x:digest)s<<std::setw(2)<<unsigned(x);return s.str();
}
int main(int argc,char** argv){try{
 require(argc==5||(argc==6&&(std::string(argv[5])=="reuse64"||std::string(argv[5])=="policy")),"source path, physical size, expected SHA, seal SHA, optional reuse64/policy required");
 bool reuse_mode=argc==6&&std::string(argv[5])=="reuse64";
 std::filesystem::path source=std::filesystem::u8path(argv[1]);auto extent=std::stoull(argv[2]);
 require(extent==std::filesystem::file_size(source)&&extent>=bytes,"source extent");
 _setmode(_fileno(stdin),_O_BINARY);std::vector<unsigned char> expected(bytes);
 std::cin.read(reinterpret_cast<char*>(expected.data()),bytes);require(std::cin.gcount()==bytes,"expected stdin length");
 require(std::cin.peek()==EOF&&sha(expected)==argv[3],"expected stdin hash/trailing bytes");
 std::vector<artifact::FixtureView> views{{source,0,extent}};
 measurement::Identity id;id.fixture_sha256=argv[3];id.asset_sha256=argv[3];id.bundle_sha256=argv[4];id.request_id="T35-host-io";id.epoch=1;
 if(argc==6&&std::string(argv[5])=="policy"){
  void* aligned=Direct::alloc_aligned(65536);require(aligned!=nullptr,"policy allocation");
  std::vector<Buffer> buffers{{aligned,65536}};std::vector<unsigned char> destination(65536,0xa5);
  std::vector<Span> spans{{0,0,65536,0}};
  SpanProvider p(views,buffers,Config{1,1,65536,65536,PathMode::PreferDirect});
  auto wait=[&](Ticket ticket){auto start=Clock::now();while(!p.done(ticket)){p.issue();p.poll(10);if(seconds(start)>30){std::cerr<<"policy drain timeout\n"<<std::flush;ExitProcess(3);}}};
  auto first=p.enqueue(spans,{destination.data(),destination.size()},id);require(bool(first),"policy first enqueue");p.issue();p.cancel(*first);wait(*first);
  require(p.take(*first,id).cancelled,"cancel completion");
  auto second=p.enqueue(spans,{destination.data(),destination.size()},id);require(bool(second)&&second->generation!=first->generation,"generation reuse");
  bool stale=false,borrow=false,bounds=false;
  try{p.done(*first);}catch(const std::exception&){stale=true;}require(stale,"stale generation rejected");
  try{p.enqueue(spans,{destination.data(),destination.size()},id);}catch(const std::exception&){borrow=true;}require(borrow,"borrow protected");
  wait(*second);auto changed=id;changed.epoch=2;require(p.take(*second,changed).cancelled,"identity not adopted");
  std::vector<Span> bad{{0,extent,65536,0}};
  try{p.enqueue(bad,{destination.data(),destination.size()},id);}catch(const std::exception&){bounds=true;}require(bounds,"invalid source bounds rejected");
  auto third=p.enqueue(spans,{destination.data(),destination.size()},id);require(bool(third),"next after error");p.issue();auto late=p.first_pending_tag();wait(*third);
  auto result=p.take(*third,id);require(result.ok&&result.bytes==65536,"fresh success");
  require(std::equal(destination.begin(),destination.end(),expected.begin()),"policy raw bytes");
  require(late>0&&!p.accept_completion(late,65536,true),"late completion rejected");require(p.try_close(),"policy terminal close");
  require(p.stats().outstanding==0,"policy drain complete");Direct::free_aligned(aligned);
  std::cout<<"{\"schema\":\"T35-lifecycle-policy/v1\",\"cancel_then_next\":true,\"identity_rejected\":true,\"stale_rejected\":true,\"borrow_rejected\":true,\"bounds_error_then_next\":true,\"late_rejected\":true,\"raw_exact\":true,\"closed\":true}\n";return 0;
 }
 std::cout<<std::setprecision(17)<<"{\"schema\":\""<<(reuse_mode?"T35-host-lifecycle/v1":"T35-host-io/v1")<<"\",\"expected_sha256\":\""<<argv[3]<<"\",\"seal_sha256\":\""<<argv[4]<<"\",\"physical_io\":null,\"GPU\":0,\"destination_bytes\":"<<bytes<<",\"expected_ram_bytes\":"<<bytes<<",\"arms\":[";
 unsigned index=0;
 for(char label:std::string(reuse_mode?"ACCA":"ABBA")){
  auto begun=Clock::now();uint64_t chunk=label=='B'?bytes:65536;void* aligned=Direct::alloc_aligned(chunk);require(aligned!=nullptr,"aligned buffer allocation");
  std::vector<unsigned char> destination(bytes,0xa5);std::vector<Buffer> buffers{{aligned,chunk}};
  Stats sum{},previous{};uint64_t peak=0,metadata=0;double io_time=0,construct_time=0,close_time=0;bool closed=true;
  std::unique_ptr<SpanProvider> provider;
  // No buffer/descriptor reuse is permitted until the active provider drains.
  // A failed drain terminates this isolated fixture rather than freeing live IO memory.
  for(uint64_t offset=0;offset<bytes;offset+=chunk){
   if(!provider){auto start=Clock::now();provider=std::make_unique<SpanProvider>(views,buffers,Config{1,1,chunk,chunk,PathMode::PreferDirect});construct_time+=seconds(start);previous={};}
   auto& p=*provider;
   std::vector<Span> spans{{0,offset,chunk,offset}};auto io_begin=Clock::now();
   auto ticket=p.enqueue(spans,{destination.data(),destination.size()},id);require(bool(ticket),"enqueue");
   bool taken=false;
   try{
    while(!p.done(*ticket)){p.issue();p.poll(10);if(seconds(io_begin)>30)throw std::runtime_error("finite host read deadline");}
    auto result=p.take(*ticket,id);taken=true;require(result.ok&&result.bytes==chunk,"read completion");
   }catch(...){
    if(!taken){p.cancel(*ticket);auto cleanup=Clock::now();while(!p.done(*ticket)&&seconds(cleanup)<30)p.poll(10);}
    if(!p.try_close()){std::cerr<<"IO drain failed; isolated process exit without buffer reuse\n"<<std::flush;ExitProcess(3);}throw;
   }
   io_time+=seconds(io_begin);auto s=p.stats();
#define ADD(field) require(s.field>=previous.field,"counter regression");sum.field+=s.field-previous.field
   ADD(logical_requested);ADD(logical_delivered);ADD(read_requested);ADD(received);ADD(direct_reads);ADD(buffered_reads);ADD(mapped_reads);ADD(errors);ADD(short_reads);ADD(unknown);ADD(overread_requested);ADD(control);ADD(outstanding);ADD(outstanding_bytes);
#undef ADD
   peak=(std::max)(peak,s.peak_bytes);metadata=(std::max)(metadata,s.metadata_capacity);sum.peak_outstanding=(std::max)(sum.peak_outstanding,s.peak_outstanding);
   previous=s;
   if(label!='C'||offset+chunk==bytes){auto start=Clock::now();require(p.try_close(),"close after completion");provider.reset();close_time+=seconds(start);}
  }
  Direct::free_aligned(aligned);double elapsed=seconds(begun);
  require(destination==expected,"raw destination byte mismatch");auto digest=sha(destination);require(digest==argv[3],"destination SHA mismatch");
  if(index++)std::cout<<",";
  std::cout<<"{\"arm\":\""<<label<<"\",\"chunk\":"<<chunk<<",\"lifecycles\":"<<(label=='C'?1:bytes/chunk);
#define FIELD(name) std::cout<<",\"" #name "\":"<<sum.name
  FIELD(logical_requested);FIELD(logical_delivered);FIELD(read_requested);FIELD(received);FIELD(direct_reads);FIELD(buffered_reads);FIELD(mapped_reads);FIELD(errors);FIELD(short_reads);FIELD(unknown);FIELD(overread_requested);FIELD(control);FIELD(outstanding);FIELD(outstanding_bytes);FIELD(peak_outstanding);
#undef FIELD
  std::cout<<",\"peak_bytes\":"<<peak<<",\"buffer_capacity\":"<<chunk<<",\"metadata_capacity\":"<<metadata<<",\"host_lifecycle_seconds\":"<<elapsed<<",\"enqueue_drain_seconds\":"<<io_time<<",\"construct_seconds\":"<<construct_time<<",\"close_seconds\":"<<close_time<<",\"exact_bytes\":true,\"sha256\":\""<<digest<<"\",\"closed\":"<<(closed?"true":"false")<<"}";
 }
 std::cout<<"]}\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}}
