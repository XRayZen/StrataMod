#include "span_provider.hpp"
#include "strata/platform/direct_file.hpp"
#include <windows.h>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace strata_ext;
using namespace strata_ext::io;
using Direct=strata::platform::DirectFile;
namespace {
unsigned assertions=0;
void check(bool v,const char* why){++assertions;if(!v)throw std::runtime_error(why);}
template<class F>void rejects(F f){bool bad=false;try{f();}catch(const std::exception&){bad=true;}check(bad,"negative accepted");}
struct Aligned {void* p=Direct::alloc_aligned(4096);~Aligned(){Direct::free_aligned(p);} };
void write(const std::filesystem::path& p,const std::vector<uint8_t>& b){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(b.data()),b.size());if(!f)throw std::runtime_error("output write");}
measurement::Identity identity(){measurement::Identity x;x.fixture_sha256="fixture";x.asset_sha256="asset";x.bundle_sha256="bundle";x.request_id="T17";x.epoch=1;return x;}
void drain(SpanProvider& p,Ticket t){for(unsigned n=0;!p.done(t)&&n<10000;++n){p.issue();p.poll(10);}check(p.done(t),"finite drain");}
Config cfg(PathMode mode,uint32_t slots=2,uint64_t credits=8192){Config c;c.path=mode;c.request_slots=slots;c.max_outstanding=2;c.max_chunk=4096;c.max_outstanding_bytes=credits;return c;}
}
int main(int argc,char** argv){try{
 if(argc!=5)throw std::runtime_error("input/output directory and caller hashes required");
 std::filesystem::path input=argv[1],out=argv[2];std::filesystem::create_directories(out);
 std::vector<artifact::FixtureView> views;std::ifstream list(input/"sources.tsv",std::ios::binary);std::string line;
 while(std::getline(list,line)){std::istringstream s(line);std::string name,base,size;std::getline(s,name,'\t');std::getline(s,base,'\t');std::getline(s,size);views.push_back({std::filesystem::u8path(name),std::stoull(base),std::stoull(size)});}
 check(views.size()==6,"source inventory");Aligned a,b;check(a.p&&b.p,"aligned allocation");std::vector<Buffer> buffers{{a.p,4096},{b.p,4096}};auto id=identity();id.fixture_sha256=argv[3];id.asset_sha256=argv[3];id.bundle_sha256=argv[4];
 std::vector<Span> gather{{0,views[0].source_absolute_offset+13,10001,7},{1,views[1].source_absolute_offset+4095,8193,10008},{2,views[2].source_absolute_offset+8192,1,18201}};
 std::vector<Span> real{{3,views[3].source_absolute_offset+4093,5001,3},{4,views[4].source_absolute_offset+17,257,5004},{5,views[5].source_absolute_offset+6266879,1,5261}};
 std::ostringstream paths,counters;uint64_t peak=0,metadata=0,mapped=0,overread=0;unsigned pathIndex=0;
 for(auto mode:{PathMode::PreferDirect,PathMode::Buffered,PathMode::Mapped}){
   SpanProvider p(views,buffers,cfg(mode));std::vector<uint8_t> dst(18210,0xa5);auto t=p.enqueue(gather,{dst.data(),dst.size()},id);check(bool(t),"enqueue gather");
   HANDLE denied=CreateFileW(views[0].path.c_str(),GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr);check(denied==INVALID_HANDLE_VALUE,"source write not denied");if(denied!=INVALID_HANDLE_VALUE)CloseHandle(denied);check(!DeleteFileW(views[0].path.c_str()),"source delete not denied");
   p.issue();check(!p.try_close(),"closed outstanding");p.wake();drain(p,*t);check(p.take(*t,id).ok,"gather failure");write(out/("gather-"+std::to_string(pathIndex)+".bin"),dst);
   std::vector<uint8_t> rd(5270,0xa5);auto rt=p.enqueue(real,{rd.data(),rd.size()},id);drain(p,*rt);check(p.take(*rt,id).ok,"real read");write(out/("real-"+std::to_string(pathIndex)+".bin"),rd);
   auto stats=p.stats();check(stats.outstanding==0&&stats.outstanding_bytes==0&&stats.peak_bytes<=8192&&stats.peak_outstanding<=2,"credit accounting");
   measurement::ByteSnapshot before{id,1,{},"T17-owner"},after{id,2,{},"T17-owner"};after.bytes.logical_useful=stats.logical_delivered;after.bytes.read_requested=stats.read_requested;auto delta=measurement::counter_delta(before,after);check(delta.bytes.logical_useful==23454&&!delta.bytes.physical_io,"T34 byte scope");
   if(pathIndex)counters<<",";counters<<"{\"logical_useful\":"<<delta.bytes.logical_useful<<",\"read_requested\":"<<delta.bytes.read_requested<<",\"received\":"<<stats.received<<",\"physical_io\":null}";
   if(mode==PathMode::PreferDirect){check(stats.direct_reads>0,"actual direct path unavailable");p.wake();for(int i=0;i<10;++i)p.poll(1);check(p.stats().control>0,"actual wake missing");}
   if(mode==PathMode::Buffered)check(stats.buffered_reads>0,"buffered path");if(mode==PathMode::Mapped)check(stats.mapped_reads>0,"mapped path");
   if(pathIndex)paths<<",";paths<<"[";auto actual=p.source_paths();for(size_t i=0;i<actual.size();++i){if(i)paths<<",";paths<<"\""<<actual[i]<<"\"";}paths<<"]";
   peak=(std::max)(peak,stats.peak_bytes);metadata=(std::max)(metadata,stats.metadata_capacity);mapped=(std::max)(mapped,stats.mapped_peak);overread+=stats.overread_requested;check(p.try_close(),"final close");++pathIndex;
 }
 for(uint32_t capacity:{1u,2u,9u}){SpanProvider p(views,buffers,cfg(PathMode::Buffered,capacity));std::vector<std::vector<uint8_t>> dst(capacity,std::vector<uint8_t>(32,0xa5));std::vector<std::vector<Span>> spans(capacity);std::vector<Ticket> tickets;
   for(uint32_t n=0;n<capacity;++n){spans[n]={{0,views[0].source_absolute_offset+n,32,0}};auto t=p.enqueue(spans[n],{dst[n].data(),32},id);check(bool(t),"configured queue capacity");tickets.push_back(*t);}
   std::vector<uint8_t> extra(32);std::vector<Span> more{{0,views[0].source_absolute_offset,32,0}};check(!p.enqueue(more,{extra.data(),32},id),"bounded outstanding queue");
   for(auto t:tickets){drain(p,t);check(p.take(t,id).ok,"finite many requests");}check(p.try_close(),"capacity close");
 }
 {SpanProvider p(views,buffers,cfg(PathMode::PreferDirect,2,8191));std::vector<Span> many;for(unsigned n=0;n<23;++n)many.push_back({0,views[0].source_absolute_offset+4090+n,17,n*17});std::vector<uint8_t> dst(391);auto t=p.enqueue(many,{dst.data(),dst.size()},id);drain(p,*t);check(p.take(*t,id).ok&&p.stats().peak_outstanding==1,"byte credits cursor");write(out/"many.bin",dst);check(p.try_close(),"many close");}
 // A legal byte-credit window may be smaller than max_chunk and buffer capacity.
 {void* x=Direct::alloc_aligned(8192);void* y=Direct::alloc_aligned(8192);check(x&&y,"large actual buffers");
  for(uint64_t skip:{0ull,13ull}){SpanProvider p(views,{{x,8192},{y,8192}},Config{1,2,4096,8192,PathMode::PreferDirect});std::vector<uint8_t> dst(8192);std::vector<Span> spans{{0,views[0].source_absolute_offset+skip,8192,0}};auto t=p.enqueue(spans,{dst.data(),dst.size()},id);check(p.issue()>0,"legal small byte-credit window stalled");drain(p,*t);check(p.take(*t,id).ok&&p.stats().peak_bytes<=4096,"small-credit finite exact window");write(out/("credit-"+std::to_string(skip)+".bin"),dst);check(p.try_close(),"small-credit close");}
  Direct::free_aligned(x);Direct::free_aligned(y);}
 rejects([&]{SpanProvider p(views,buffers,cfg(PathMode::Buffered,2,4095));});
 rejects([&]{auto bad=buffers;bad[0].capacity=4095;SpanProvider p(views,bad,cfg(PathMode::Buffered));});
 rejects([&]{auto bad=buffers;bad[1]=bad[0];SpanProvider p(views,bad,cfg(PathMode::Buffered));});
 rejects([&]{auto bad=views;bad[0].source_absolute_offset=UINT64_MAX;SpanProvider p(bad,buffers,cfg(PathMode::Buffered));});
 {SpanProvider p(views,buffers,cfg(PathMode::Buffered));std::vector<uint8_t> dst(64);std::vector<Span> valid{{0,views[0].source_absolute_offset,64,0}};
   rejects([&]{auto bad=valid;bad[0].offset--;p.enqueue(bad,{dst.data(),64},id);});
   rejects([&]{auto bad=valid;bad[0].bytes=65;p.enqueue(bad,{dst.data(),64},id);});
   rejects([&]{auto bad=valid;bad.push_back(bad[0]);p.enqueue(bad,{dst.data(),64},id);});
   rejects([&]{p.enqueue(valid,buffers[0],id);});
   auto t=p.enqueue(valid,{dst.data(),64},id);rejects([&]{p.enqueue(valid,{dst.data(),64},id);});p.cancel(*t);check(p.done(*t)&&p.take(*t,id).cancelled&&p.stats().read_requested==0,"cancel unissued");check(p.try_close(),"negative close");
 }
 {SpanProvider p(views,buffers,cfg(PathMode::PreferDirect));std::vector<uint8_t> dst(8192,0xa5);std::vector<Span> spans{{0,views[0].source_absolute_offset,8192,0}};auto t=p.enqueue(spans,{dst.data(),dst.size()},id);check(p.issue()==2,"actual issued pair");p.cancel(*t);check(!p.done(*t)&&!p.try_close(),"cancel retained issued writer");drain(p,*t);check(p.take(*t,id).cancelled,"cancel result");check(std::all_of(dst.begin(),dst.end(),[](uint8_t v){return v==0xa5;}),"cancel publication");
   auto next=p.enqueue(spans,{dst.data(),dst.size()},id);drain(p,*next);auto old=id;old.epoch++;check(p.take(*next,old).cancelled,"late epoch publication");auto last=p.enqueue(spans,{dst.data(),dst.size()},id);drain(p,*last);check(p.take(*last,id).ok,"next operation");check(p.try_close(),"cancel drain close");}
 // Inject only after synchronous reads ended: never forge an OS writer's end.
 for(unsigned kind=0;kind<5;++kind){SpanProvider p(views,buffers,cfg(PathMode::Buffered));std::vector<uint8_t> dst(32,0xa5);std::vector<Span> spans{{0,views[0].source_absolute_offset,32,0}};auto t=p.enqueue(spans,{dst.data(),32},id);p.issue();auto tag=p.first_pending_tag();auto before=p.stats();
   check(!p.accept_completion(UINT64_MAX,0,true)&&p.stats().outstanding==before.outstanding,"control released credit");check(!p.accept_completion(UINT64_MAX,1,true),"malformed control");check(!p.accept_completion(tag+1000,0,true)&&p.stats().outstanding==before.outstanding,"unknown released credit");
   if(kind==0){check(!p.accept_completion(tag,33,true)&&p.stats().outstanding==1,"oversize completion");p.poll();}
   if(kind==1)check(p.accept_completion(tag,31,true),"short adapter");
   if(kind==2)check(p.accept_completion(tag,0,false),"error adapter");
   if(kind==3){p.mark_drain_failed();check(!p.try_close()&&p.issue()==0,"quarantine reuse");p.poll();}
   if(kind==4)p.poll();
   check(p.done(*t)&&p.stats().outstanding==0,"adapter drain");auto result=p.take(*t,id);check(result.ok==(kind==4),"adapter result");check(!p.accept_completion(tag,32,true)&&p.stats().outstanding==0,"duplicate released twice");check(p.try_close(),"adapter close");
 }
 {uint64_t tag=0;check(SpanProvider::next_data_tag(tag)==1,"tag start");tag=UINT64_MAX-2;check(SpanProvider::next_data_tag(tag)==UINT64_MAX-1,"tag last");rejects([&]{SpanProvider::next_data_tag(tag);});tag=UINT64_MAX;rejects([&]{SpanProvider::next_data_tag(tag);});}
 // Existing T16 owner-local lease crosses only the host source->stage boundary.
 // Device descriptor is synthetic and never accessed; no GPU/event claim.
 {std::vector<uint8_t> stage(4096);cache::Buffer declaration[]={{cache::Pool::Source,reinterpret_cast<uintptr_t>(a.p),4096,false},{cache::Pool::Stage,reinterpret_cast<uintptr_t>(stage.data()),4096,false},{cache::Pool::Device,1,4096,false}};
  cache::LeaseQueue owner(17,declaration,3);SpanProvider p(views,{{a.p,4096}},Config{1,1,4096,4096,PathMode::PreferDirect});std::vector<Span> spans{{0,views[0].source_absolute_offset+19,1024,0}};
  for(bool cancel:{false,true}){auto lease=owner.enqueue(id,cache::Kind::Expert,1024);check(bool(lease),"T16 lease enqueue");auto issued=owner.issue(reinterpret_cast<uintptr_t>(stage.data()));check(bool(issued),"T16 reserve actual stage");auto ticket=p.enqueue(spans,{stage.data(),stage.size()},id,*issued);p.issue();
   if(cancel){owner.cancel(id);p.cancel(*ticket);check(owner.live_jobs()==1,"T16 premature release");}
   drain(p,*ticket);auto result=p.take(*ticket,id);check(result.caller_lease.owner==issued->owner&&result.caller_lease.index==issued->index&&result.caller_lease.generation==issued->generation,"opaque lease return");check(result.ok!=cancel,"lease result");owner.stage_copied(result.caller_lease);
   if(!cancel){check(owner.state(*issued)==cache::State::Filled,"host stage callback");owner.cancel(id);}check(owner.live_jobs()==0&&owner.leased_bytes()==0,"T16 host drain credit");}
  check(p.try_close(),"T16 provider close");}
 unsigned eofData=0,eofControl=0;
 {Direct file;std::string why;check(file.open(views[2].path.u8string(),why),"EOF backend open");check(file.submit(12288,a.p,4096,101,why),"EOF submit");
   for(unsigned n=0;n<100&&!eofData;++n){strata::platform::Completion cs[8];int count=file.wait(cs,8,10);for(int i=0;i<count;++i){if(cs[i].tag==Direct::WAKE_TAG){check(cs[i].bytes==0&&cs[i].ok,"EOF control frame");++eofControl;}else{check(cs[i].tag==101&&cs[i].bytes==0&&cs[i].ok,"EOF data frame");++eofData;}}}check(eofData==1,"EOF data accounting");file.close();}
 wchar_t module[32768];DWORD moduleChars=GetModuleFileNameW(GetModuleHandleW(L"kernel32.dll"),module,32768);check(moduleChars&&moduleChars<32768,"actual system DLL path");
 std::cout<<"{\"source_id\":\""<<T17_SOURCE_ID<<"\",\"fixture_sha256\":\""<<id.fixture_sha256<<"\",\"bundle_sha256\":\""<<id.bundle_sha256<<"\",\"assertions\":"<<assertions<<",\"paths\":["<<paths.str()<<"],\"byte_counters\":["<<counters.str()<<"],\"peak_read_bytes\":"<<peak<<",\"read_buffer_capacity\":8192,\"wrapper_metadata_payload\":"<<metadata<<",\"mapped_window_peak\":"<<mapped<<",\"overread_requested\":"<<overread<<",\"physical_io\":null,\"direct_internal_metadata\":null,\"os_file_cache\":null,\"EOF_data\":"<<eofData<<",\"EOF_control\":"<<eofControl<<",\"kernel32_path\":\""<<std::filesystem::path(module).generic_u8string()<<"\",\"owner_drained\":true,\"T16_host_lease_cycles\":2,\"GPU_executed\":false}"<<std::endl;
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
