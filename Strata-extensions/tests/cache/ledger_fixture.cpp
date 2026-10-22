#include "lease_queue.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace strata_ext;
using namespace strata_ext::cache;
namespace {
unsigned assertions=0;
void expect(bool value,const char* name) {if(!value)throw std::runtime_error(name);++assertions;}
template<class F>void rejects(F f,const char* name){try{f();}catch(const std::exception&){++assertions;return;}throw std::runtime_error(name);}
measurement::Identity identity(uint64_t epoch=1) {return {std::string(64,'1'),std::string(64,'2'),std::string(64,'3'),"caller-request",epoch,measurement::Phase::Decode};}
std::array<Buffer,6> buffers(bool registered=false,uint64_t capacity=65536) {
    return {{{Pool::Source,0x10000,capacity,registered},{Pool::Source,0x30000,capacity,registered},
             {Pool::Stage,0x50000,capacity},{Pool::Stage,0x70000,capacity},
             {Pool::Device,0x100000,capacity},{Pool::Device,0x120000,capacity}}};
}
Token push(LeaseQueue& q,const measurement::Identity& id,Kind kind=Kind::Expert,uint64_t bytes=65536) {
    auto t=q.enqueue(id,kind,bytes);expect(bool(t),"enqueue");return *t;
}
Token start(LeaseQueue& q) {auto t=q.issue();expect(bool(t),"issue");return *t;}
void finish(LeaseQueue& q,Token t,const measurement::Identity& id) {
    q.stage_copied(t);q.begin_dma(t,7);expect(q.complete_dma(t,7,true,id),"fill ready");q.begin_kernel(t,7);expect(q.complete_kernel(t,7,true,id),"single adopt");
}
void fixture() {
    auto id=identity(),next=identity(2);auto b=buffers();
    {
      LeaseQueue q(7,b.data(),6);auto before=sizeof(q);auto queued=push(q,id);auto t=start(q);
      expect(t.generation==queued.generation&&q.queued_bytes()==65536,"queue bytes");
      expect(q.leased_bytes()==3*65536,"source/stage/device held");
      rejects([&]{q.begin_kernel(t,7);},"kernel before fill accepted");
      rejects([&]{q.begin_dma(t,7);},"DMA before stage accepted");
      q.stage_copied(t);expect(q.leased_bytes()==2*65536,"source copy release");
      rejects([&]{q.begin_dma(t,8);},"foreign stream owner accepted");
      q.begin_dma(t,7);expect(!q.issue(),"no second queued work");
      expect(q.complete_dma(t,7,true,id),"DMA ready");expect(q.leased_bytes()==65536,"staging DMA release");
      q.begin_kernel(t,7);expect(q.leased_bytes()==65536,"kernel retains device");
      expect(q.complete_kernel(t,7,true,id),"kernel adopt");expect(q.leased_bytes()==0&&q.queued_bytes()==0,"end release");
      expect(!q.complete_kernel(t,7,true,id),"duplicate adopted");
      auto newer=push(q,next);auto nt=start(q);expect(newer.generation!=t.generation,"slot generation");
      auto live=q.leased_bytes();expect(!q.complete_dma(t,7,true,next)&&q.leased_bytes()==live,"stale completion freed new buffers");
      finish(q,nt,next);expect(sizeof(q)==before,"metadata growth");
    }
    {
      auto registered=buffers(true);LeaseQueue q(7,registered.data(),6);push(q,id);auto t=start(q);q.stage_copied(t);
      expect(q.leased_bytes()==3*65536,"registered source released before DMA");q.begin_dma(t,7);q.complete_dma(t,7,true,id);
      expect(q.leased_bytes()==65536,"registered source DMA release");q.begin_kernel(t,7);q.complete_kernel(t,7,true,id);
    }
    {
      LeaseQueue q(7,b.data(),6);push(q,id);auto t=start(q);q.cancel(id);expect(q.live_jobs()==1,"issued read freed on cancel");q.stage_copied(t);
      expect(q.live_jobs()==0&&q.leased_bytes()==0,"cancelled read not retired after completion");
      push(q,id);t=start(q);q.stage_copied(t);q.begin_dma(t,7);q.cancel(id);
      expect(q.leased_bytes()==2*65536,"cancel DMA freed early");
      expect(!q.complete_dma(t,7,true,next)&&q.leased_bytes()==0,"old DMA published");
      push(q,id);t=start(q);q.stage_copied(t);q.begin_dma(t,7);q.complete_dma(t,7,true,id);q.begin_kernel(t,7);q.cancel(id);
      expect(q.leased_bytes()==65536,"cancel kernel freed early");expect(!q.complete_kernel(t,7,true,next),"old kernel adopted");
      push(q,id);q.cancel(id);expect(q.live_jobs()==0&&q.queued_bytes()==0,"unissued cancellation");
    }
    {
      LeaseQueue q(7,b.data(),6);push(q,id);auto t=start(q);q.stage_copied(t);q.begin_dma(t,7);
      expect(!q.complete_dma(t,7,false,id),"failed drain succeeded");expect(q.quarantined_buffers()==2,"drain buffers not quarantined");
      auto retained=q.leased_bytes();expect(retained==2*65536&&q.queued_bytes()==65536,"quarantine capacity disappeared");
      push(q,next);auto healthy=start(q);finish(q,healthy,next);expect(q.leased_bytes()==retained&&q.live_jobs()==1,"next request reused quarantine");
      rejects([&]{q.begin_kernel(t,7);},"quarantine reused");
    }
    {
      LeaseQueue q(7,b.data(),6);push(q,id,Kind::Prefetch);auto pf=start(q);push(q,id,Kind::Prefetch);
      expect(!q.issue(),"prefetch consumed demand reservation");auto demand=push(q,id,Kind::Row);auto got=start(q);expect(got.index==demand.index,"row demand blocked by prefetch");
      finish(q,got,id);finish(q,pf,id);auto last=start(q);finish(q,last,id);expect(q.live_jobs()==0,"prefetch finite completion");
    }
    {
      LeaseQueue q(7,b.data(),6);std::array<Token,3> expert{},row{};
      for(int i=0;i<3;++i){expert[i]=push(q,id,Kind::Expert);row[i]=push(q,id,Kind::Row);}
      for(int i=0;i<3;++i){auto e=start(q);expect(e.index==expert[i].index,"expert fairness/order");finish(q,e,id);auto r=start(q);expect(r.index==row[i].index,"row fairness/order");finish(q,r,id);}
      expect(q.live_jobs()==0,"declared finite progress");
    }
    {
      LeaseQueue q(7,b.data(),6,Config{2,131072,65536,1});push(q,id,Kind::Prefetch);
      expect(!q.enqueue(id,Kind::Prefetch,65536),"prefetch took demand queue/byte credit");
      auto demand=push(q,id);auto got=start(q);expect(got.index==demand.index,"reserved demand admission");finish(q,got,id);finish(q,start(q),id);
    }
    {
      std::array<Buffer,3> minimal{{b[0],b[2],b[4]}};
      LeaseQueue q(7,minimal.data(),3);push(q,id);push(q,id,Kind::Row);auto one=start(q);
      auto held=q.leased_bytes();expect(!q.issue()&&q.leased_bytes()==held,"failed reservation left partial lease");
      finish(q,one,id);finish(q,start(q),id);expect(q.live_jobs()==0,"minimal atomic declared set failed finite progress");
    }
    {
      LeaseQueue q(7,b.data(),6);push(q,id);expect(!q.issue(0xdead)&&q.leased_bytes()==0,"foreign ring slot created partial reservation");
      auto picked=q.issue(b[3].address);expect(bool(picked),"existing ring choice not reserved");
      expect(q.view(*picked).stage.address==b[3].address,"existing stage pointer changed");finish(q,*picked,id);
    }
    {
      LeaseQueue q(7,b.data(),6,Config{1,65536,65536,1});push(q,id);expect(!q.enqueue(id,Kind::Row,1),"queue count exceeded");q.cancel(id);
      rejects([&]{q.enqueue(id,Kind::Expert,65537);},"chunk cap exceeded");rejects([&]{q.enqueue(id,Kind::Expert,0);},"empty job");
      auto short_b=buffers(false,65535);LeaseQueue short_q(7,short_b.data(),6);expect(!short_q.enqueue(id,Kind::Expert,65536),"one-byte short declared set accepted");
      LeaseQueue bytes_q(7,b.data(),6,Config{8,65536,65536,1});push(bytes_q,id);expect(!bytes_q.enqueue(id,Kind::Row,1),"queue byte cap exceeded");
      auto invalid=id;invalid.request_id="";rejects([&]{bytes_q.enqueue(invalid,Kind::Row,1);},"missing caller ID");
      auto overlap=b;overlap[1].address=overlap[0].address;rejects([&]{LeaseQueue bad(7,overlap.data(),6);},"overlapping buffer owner");
      overlap=b;overlap[0].capacity=UINT64_MAX;rejects([&]{LeaseQueue bad(7,overlap.data(),6);},"range overflow");
      auto snapshot=q.snapshot(id,4*65536,2*65536,"PCI-fixture",2*65536);
      expect(measurement::owned_total(snapshot)==6*65536+sizeof(q),"ledger double-counts pinned/queue/lease");
      rejects([&]{q.snapshot(id,UINT64_MAX,0,"fixture",1);},"metadata gauge overflow");
    }
    std::cout<<"{\"source_id\":\""<<T16_SOURCE_ID<<"\",\"assertions\":"<<assertions<<",\"synthetic_declared_set\":true,\"hardware_completion_claim\":false,\"metadata_bytes\":"<<sizeof(LeaseQueue)<<"}"<<std::endl;
}
}
int main() {
    try { fixture(); }
    catch(const std::exception& e) { std::cerr<<e.what()<<std::endl;return 2; }
}
