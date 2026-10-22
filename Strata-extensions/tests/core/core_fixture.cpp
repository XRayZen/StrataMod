#include "../../models/deepseek41/core.hpp"
#include <iostream>
#include <stdexcept>
#include <hip/hip_runtime.h>
#include <fstream>
#include <sstream>
#include <cstring>
#include <windows.h>
#include <psapi.h>
using namespace strata_ext::deepseek41;

namespace {
namespace fs=std::filesystem;
void must(bool x,const char*m){if(!x)throw std::runtime_error(m);}
void hip_ok(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
std::vector<std::string> fields(const std::string&s){std::vector<std::string> out;std::istringstream f(s);std::string x;while(std::getline(f,x,'\t'))out.push_back(x);return out;}
template<class T>std::vector<T> read_file(const fs::path&p){std::ifstream f(p,std::ios::binary|std::ios::ate);must(bool(f),"input missing");auto n=f.tellg();must(n>=0&&n%sizeof(T)==0,"input element bytes");std::vector<T> x(size_t(n)/sizeof(T));f.seekg(0);f.read((char*)x.data(),n);must(bool(f),"input short");return x;}
template<class T>void write_file(const fs::path&p,const std::vector<T>&x){std::ofstream f(p,std::ios::binary);f.write((const char*)x.data(),x.size()*sizeof(T));must(bool(f),"output short");}
Artifact load_artifact(const fs::path&root){SourceSet sources;std::ifstream f(root/"sources.tsv");std::string line;while(std::getline(f,line)){auto a=fields(line);must(a.size()==5,"source table");SourceFile x{uint32_t(std::stoul(a[0])),fs::u8path(a[4]),std::stoull(a[1]),a[3],a[2]};if(sources.root.empty())sources.root=x.original_path.parent_path();sources.files.push_back(x);}std::ifstream pf(root/"prefixes.tsv");std::vector<strata_ext::artifact::PrefixIndex> prefixes;fs::path first;while(std::getline(pf,line)){auto a=fields(line);must(a.size()==2,"prefix table");if(first.empty())first=fs::u8path(a[1]);prefixes.push_back(strata_ext::artifact::inspect_prefix(fs::u8path(a[1]),std::stoull(a[0])));}return Artifact(strata_ext::artifact::merge_prefixes(prefixes),inspect_metadata(first),sources);}
strata_ext::measurement::Identity fixture_identity(){strata_ext::measurement::Identity x;x.fixture_sha256=x.asset_sha256=x.bundle_sha256=std::string(64,'a');x.request_id="T20-source-owner-fixture";x.epoch=1;return x;}
int owner_fixture(const fs::path&input,const fs::path&output,const std::string&pci,bool hot_only=false,bool capacity_credit=false){
 using namespace strata_ext;int count=0,selected=-1;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char id[64]{};hip_ok(hipDeviceGetPCIBusId(id,sizeof(id),i));if(pci==id)selected=i;}must(selected>=0,"PCI not found");hip_ok(hipSetDevice(selected));
 auto artifact=load_artifact(input);std::vector<cache::RowSourceView> source_views;for(const auto&t:artifact.tensors())if(t.name=="per_layer_token_embd.weight"){auto src=artifact.source_tensor(t.name).source;bool exists=false;for(const auto&v:source_views)exists|=v.source.shard_index==src.shard_index;if(!exists)source_views.push_back({src,{src.original_path,0,src.original_size}});}
 must(!source_views.empty(),"Engram full source views");
 cache::PrimarySupply weight({2,2,2097152,4,4,selected,true});cache::RowSupply rows({24,24,1,1,selected},artifact,cache::RowSourceViews(std::move(source_views)));CoreStorage storage(selected);
 auto xspace=storage.allocate("fixture-activation",19,6144,DeviceScalar::Float32),yspace=storage.allocate("fixture-output",19,5120,DeviceScalar::Float32),embedding=storage.allocate("fixture-row-output",1,6144,DeviceScalar::Bfloat16InFloat32);
 auto identity=fixture_identity();CoreProjection projection(weight,rows,identity,{1,capacity_credit?weight.read_window_capacity():4096});CoreConfig cfg;cfg.device=selected;cache::DemandOrder order;fs::create_directories(output);std::ofstream receipt(output/"owner.tsv");
 auto counters=[&](const std::string&name,const cache::SupplyStats&b,const cache::SupplyStats&a){receipt<<name<<'\t'<<a.weight_read-b.weight_read<<'\t'<<a.aligned_read-b.aligned_read<<'\t'<<a.weight_h2d-b.weight_h2d<<'\t'<<a.issued_reads-b.issued_reads<<'\t'<<a.input_h2d-b.input_h2d<<'\t'<<a.output_d2h-b.output_d2h<<'\n';};
 try{
 std::ifstream jobs(input/"owner-jobs.tsv");std::string line;while(std::getline(jobs,line)){auto j=fields(line);must(j.size()==5,"owner job columns");auto original=artifact.source_tensor(j[1]);auto matrix=std::stoull(j[2]),batch=std::stoull(j[3]);must(batch<=19,"declared fixture allocation");auto k=original.span.dims_ggml.at(0),n=original.span.dims_ggml.at(1);auto host=read_file<float>(input/j[4]);must(host.size()==batch*k,"fixture input geometry");DeviceView x=xspace,y=yspace;x.rows=batch;x.columns=k;x.bytes=batch*k*4;y.rows=batch;y.columns=n;y.bytes=batch*n*4;storage.upload(x,host.data(),x.bytes);

 for(size_t slot=0;slot<2;++slot)must(weight.evict_device(slot),"cold idle eviction");weight.evict_ram();
 auto tile=row_tiles(original,matrix,cfg.tile_bytes,cfg.tile_rows).back();auto active=batch_waves(batch).front();DeviceView hotx=x,hoty=y;hotx.rows=active;hotx.bytes=active*k*4;hoty.rows=active;hoty.bytes=active*n*4;
 if(!hot_only){auto before=weight.stats();tiled_projection(original,matrix,x,y,batch,cfg,storage.stream(),projection.callback());storage.drain();auto after=weight.stats();std::vector<float> got(batch*n);storage.download(y,got.data(),got.size()*4);write_file(output/(j[0]+".bin"),got);counters(j[0],before,after);}else{auto warm_before=weight.stats();projection(tile,hotx,hoty,active,storage.stream());storage.drain();if(capacity_credit)counters(j[0]+"-warm",warm_before,weight.stats());}
 // Poison only the actual target rows: a no-op hot launch cannot pass by
 // accidentally retaining the preceding cold/warm result. This is fixture-only.
 auto start=(char*)hoty.data+tile.row_first*4;hip_ok(hipMemset2DAsync(start,n*4,255,tile.row_count*4,active,reinterpret_cast<hipStream_t>(storage.stream())));
 auto before=weight.stats();projection(tile,hotx,hoty,active,storage.stream());storage.drain();auto after=weight.stats();counters(j[0]+"-hot",before,after);
 std::vector<float> hot_result(active*tile.row_count);hip_ok(hipMemcpy2DAsync(hot_result.data(),tile.row_count*4,start,n*4,tile.row_count*4,active,hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(storage.stream())));storage.drain();write_file(output/(j[0]+"-hot.bin"),hot_result);

 }
 

 if(hot_only){HMODULE handles[2048];DWORD needed=0;must(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"hot modules");std::ofstream loaded(output/"loaded-modules.txt");for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768]{};must(GetModuleFileNameA(handles[i],path,sizeof(path))>0,"hot module path");loaded<<path<<'\n';}must(weight.try_close()&&rows.try_close(),"hot owner close");receipt.flush();std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"hot_only\":true}\n";return 0;}
 // New no-issue polls retain the existing permit-only contract. These are real
 // original-source requests, not fabricated completion or placeholder buffers.
 unsigned control_checks=0;auto require_control=[&](bool ok){must(ok,"owner control contract");++control_checks;};
 auto original=artifact.source_tensor("blk.0.ffn_up_exps.weight");auto tile=source_tile(original,38,0,1);cache::SupplyMatrix cm{tile.original,tile.absolute_offset,tile.bytes,tile.type,1,size_t(tile.k)};cm.row_tile=true;cm.original_matrix=38;
 for(size_t slot=0;slot<2;++slot)must(weight.evict_device(slot),"control cold eviction");weight.evict_ram();
 auto bcontrol=weight.stats();require_control(weight.begin(cm,identity));for(unsigned i=0;i<3;++i){weight.poll_io(0);weight.poll_device();}auto acontrol=weight.stats();require_control(acontrol.issued_reads==bcontrol.issued_reads&&acontrol.weight_read==bcontrol.weight_read);weight.cancel();while(weight.state()!=cache::SupplyState::Cancelled){weight.poll_io(10);weight.poll_device();}require_control(weight.take(identity).empty());
 require_control(weight.begin(cm,identity));require_control(weight.issue_reads(1,4096)==4096);auto outstanding=weight.stats();require_control(outstanding.outstanding_reads<=1&&outstanding.outstanding_read_bytes<=4096);weight.cancel();while(weight.state()!=cache::SupplyState::Cancelled){weight.poll_io(10);weight.poll_device();}require_control(weight.take(identity).empty());
 // The next normal device request must succeed after actual issued-I/O drain.
 auto cx=xspace,cy=yspace;cx.rows=cy.rows=1;cx.columns=tile.k;cx.bytes=tile.k*4;cy.columns=original.span.dims_ggml[1];cy.bytes=cy.columns*4;projection(tile,cx,cy,1,storage.stream());require_control(weight.state()==cache::SupplyState::Idle);std::vector<float> control_next(1);storage.download(cy,control_next.data(),4);write_file(output/"control-next.bin",control_next);
 receipt<<"control\t"<<control_checks<<'\n';
 std::vector<cache::RowLookup> lookups;for(unsigned h=0;h<24;++h)lookups.push_back({14,h,artifact.head_rows(14,h)-1});
 for(unsigned pass=0;pass<3;++pass){if(pass==2)for(const auto&q:lookups)must(rows.evict(q),"row device eviction");auto b=rows.stats();gather_engram_device(weight,rows,order,lookups,identity,{1,4096},embedding,storage.stream());storage.drain();auto a=rows.stats();std::vector<float> got(6144);storage.download(embedding,got.data(),got.size()*4);write_file(output/("rows-"+std::to_string(pass)+".bin"),got);receipt<<"rows-"<<pass<<'\t'<<a.logical_read-b.logical_read<<'\t'<<a.requested_read-b.requested_read<<'\t'<<a.weight_h2d-b.weight_h2d<<'\t'<<a.issued-b.issued<<'\t'<<a.output_d2h-b.output_d2h<<'\t'<<a.control_d2h-b.control_d2h<<'\n';}
 HMODULE handles[2048];DWORD needed=0;must(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"runtime module enumeration");std::ofstream loaded(output/"loaded-modules.txt");for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768]{};must(GetModuleFileNameA(handles[i],path,sizeof(path))>0,"module path");loaded<<path<<'\n';}
 
 // Both real owners consume one common physical 4KiB credit. Positive deltas
 // alone advance demand order; polls and zero candidates cannot consume turns.
 for(size_t slot=0;slot<2;++slot)must(weight.evict_device(slot),"fair cold eviction");weight.evict_ram();
 auto fresh=lookups.front();--fresh.row;auto row_request=rows.enqueue({fresh},identity);must(bool(row_request),"fair row admission");must(weight.begin(cm,identity),"fair weight admission");cache::DemandOrder fair;std::string turns;
 while(weight.state()!=cache::SupplyState::Ready||rows.state(*row_request)!=cache::RowState::Ready){auto before_w=weight.stats();auto before_r=rows.stats();auto issued=advance_core_io(weight,rows,fair,{1,4096},cache::Kind::Expert,10);auto after_w=weight.stats();auto after_r=rows.stats();auto wd=after_w.issued_read-before_w.issued_read,rd=after_r.issued_requested-before_r.issued_requested;must(wd+rd==issued.requested_bytes&&wd+rd<=4096&&issued.operations<=1,"shared actual read credit");must(after_w.outstanding_reads+after_r.outstanding_reads<=1&&after_w.outstanding_read_bytes+after_r.outstanding_read_bytes<=4096,"joint outstanding gauge");if(wd)turns+='E';if(rd)turns+='R';}
 must(turns=="ERE","actual fair class progress");weight.cancel();must(weight.take(identity).empty(),"Ready weight cancellation");rows.cancel(*row_request);must(rows.take(*row_request,identity).cancelled,"Ready row cancellation");receipt<<"fair\t"<<turns<<'\n';
 // Core's borrowed output remains owner-live through cancellation until the
 // caller returns its last-use stream event. Invalid return never releases it.
 row_request=rows.enqueue({lookups.front()},identity);must(bool(row_request),"borrow cancellation admission");while(rows.state(*row_request)!=cache::RowState::Ready)advance_core_io(weight,rows,order,{1,4096},cache::Kind::Expert,10);rows.launch_gather(*row_request);while(rows.state(*row_request)==cache::RowState::Kernel)rows.poll_device();auto borrowed=rows.borrow_device_output(*row_request);auto invalid=borrowed;invalid.cursor++;bool rejected=false;try{rows.return_device_output(*row_request,invalid,storage.stream());}catch(const std::exception&){rejected=true;}must(rejected,"wrong borrowed cursor rejected");rows.cancel(*row_request);must(!rows.enqueue({lookups.back()},identity),"borrowed cancelled request cannot reuse cursor");rows.return_device_output(*row_request,borrowed,storage.stream());while(rows.state(*row_request)!=cache::RowState::Cancelled)rows.poll_device();must(rows.take(*row_request,identity).cancelled,"borrow cancellation actual event drain");
 gather_engram_device(weight,rows,order,lookups,identity,{1,4096},embedding,storage.stream());storage.drain();std::vector<float> next(6144);storage.download(embedding,next.data(),next.size()*4);write_file(output/"rows-next.bin",next);receipt<<"borrow_cancel\t3\n";
 auto w=weight.stats();auto r=rows.stats();receipt<<"allocation\t"<<storage.explicit_owned_bytes()<<'\t'<<w.device_owned<<'\t'<<r.device_owned<<'\t'<<w.host_owned<<'\t'<<r.host_payload<<'\n';must(weight.try_close()&&rows.try_close(),"owner close after actual drain");
 }catch(...){if(weight.state()!=cache::SupplyState::Idle&&weight.state()!=cache::SupplyState::Quarantined)weight.cancel();rows.cancel_all();while(!weight.try_close()||!rows.try_close()){weight.poll_io(10);weight.poll_device();rows.poll_io(10);rows.poll_device();if(weight.state()==cache::SupplyState::Cancelled){try{weight.take_device(identity);}catch(...){weight.take(identity);}}for(auto t:rows.cancel_all())if(rows.state(t)==cache::RowState::Cancelled)rows.take(t,identity);}throw;}
 receipt.flush();must(bool(receipt),"owner receipt write");std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"owner_fixture\":true,\"device\":"<<selected<<"}\n";return 0;
}
int full_fixture(const fs::path&input,const fs::path&output,const std::string&pci){
 using namespace strata_ext;int count=0,dev=-1;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char id[64]{};hip_ok(hipDeviceGetPCIBusId(id,sizeof(id),i));if(pci==id)dev=i;}must(dev>=0,"full PCI selection");hip_ok(hipSetDevice(dev));fs::create_directories(output);
 auto artifact=load_artifact(input);std::ifstream prefixes(input/"prefixes.tsv");std::string line;must(bool(std::getline(prefixes,line)),"full Engram metadata prefix");auto config=engram::inspect_metadata(fs::u8path(fields(line).at(1)));auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
 auto weight=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,dev,true});auto rows=std::make_unique<cache::RowSupply>(cache::RowConfig{24,24,1,1,dev},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));auto id=fixture_identity();id.request_id="T20-full40-prefill2-append1";CoreConfig cfg;cfg.device=dev;cfg.full_logits=true;cfg.audit=nullptr;
 auto sequence=std::make_unique<CoreSequence>(artifact,config,*weight,*rows,id,cfg,3);
 try{
 auto initial=sequence->runtime_stats();std::ofstream progress(output/"full-progress.tsv");progress<<"created\t"<<initial.storage_device_owned<<'\n';progress.flush();
 auto first=sequence->prefill({3,37},0);must(first.rows==2&&first.vocabulary==129280&&first.logits.size()==2*129280&&sequence->position()==2,"finite prefill output/state");write_file(output/"prefill2-logits.bin",first.logits);progress<<"prefill\t"<<sequence->position()<<'\n';progress.flush();
 auto last=sequence->step(1024,2);must(last.size()==129280&&sequence->position()==3,"append output/state");write_file(output/"append-logits.bin",last);auto runtime=sequence->runtime_stats();auto w=weight->stats();auto r=rows->stats();
 std::ofstream result(output/"full-stats.tsv");result<<"core\t"<<runtime.storage_device_owned<<'\t'<<runtime.constant_source_bytes<<'\t'<<runtime.storage_upload_bytes<<'\t'<<runtime.requested_output_or_fixture_download_bytes<<'\n';result<<"owners\t"<<w.device_owned<<'\t'<<r.device_owned<<'\t'<<w.input_h2d<<'\t'<<w.output_d2h<<'\t'<<r.output_d2h<<'\n';result<<"read_credit\t"<<weight->read_window_capacity()<<'\n';result<<"progress\t"<<sequence->position()<<"\t40\t2\t1\n";result<<"total_owned\t"<<sequence->explicit_device_owned()<<'\n';result<<"source_logical\t"<<w.weight_read<<'\t'<<r.logical_read<<'\t'<<runtime.constant_source_bytes<<'\n';for(unsigned layer=0;layer<40;++layer){result<<"route-"<<layer<<'\t'<<runtime.routed_tokens[layer];for(auto bits:runtime.route_union[layer])result<<'\t'<<bits;result<<'\n';}result<<"route_metadata\t"<<runtime.route_metadata_bytes<<'\n';result<<"state_positions";for(auto value:runtime.state_positions)result<<'\t'<<value;result<<'\n';result<<"compressed_rows";for(auto value:runtime.compressed_rows)result<<'\t'<<value;result<<'\n';result<<"key_rows";for(auto value:runtime.key_rows)result<<'\t'<<value;result<<'\n';result.flush();
 HMODULE handles[2048];DWORD needed=0;must(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"full module list");std::ofstream modules(output/"loaded-modules.txt");for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768]{};must(GetModuleFileNameA(handles[i],path,sizeof(path))>0,"full module path");modules<<path<<'\n';}
 sequence.reset();must(weight->try_close()&&rows->try_close(),"full actual owner drain");std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"full40_progress\":true,\"tokens\":3,\"numeric_verified_in_native\":false,\"caller_comparison_required\":true}\n";return 0;
 }catch(const std::exception&e){std::cerr<<"full original error: "<<e.what()<<'\n'<<std::flush;sequence.reset();if(weight->state()!=cache::SupplyState::Idle&&weight->state()!=cache::SupplyState::Quarantined)weight->cancel();rows->cancel_all();for(unsigned attempt=0;attempt<10000&&(!weight->try_close()||!rows->try_close());++attempt){weight->poll_io(10);weight->poll_device();rows->poll_io(10);rows->poll_device();if(weight->state()==cache::SupplyState::Cancelled){try{weight->take_device(id);}catch(...){weight->take(id);}}for(auto t:rows->cancel_all())if(rows->state(t)==cache::RowState::Cancelled)rows->take(t,id);}if(!weight->try_close())weight.release();if(!rows->try_close())rows.release();throw;}
}

struct BranchAudit final:DeviceAudit {
 fs::path output;uint64_t calls=0,bytes=0;
 explicit BranchAudit(fs::path path):output(std::move(path)){}
 void stage(const std::string&name,const DeviceView&v,void*stream)override{
  ++calls;if(name!="block_output"&&name!="block_next_pre")return;
  std::vector<float> result(v.rows*v.columns);hip_ok(hipMemcpyAsync(result.data(),v.data,result.size()*4,hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));hip_ok(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));bytes+=result.size()*4;write_file(output/("audit-"+name+".bin"),result);
 }
};
int branch_fixture(const fs::path&input,const fs::path&output,const std::string&pci){
 using namespace strata_ext;int count=0,dev=-1;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char id[64]{};hip_ok(hipDeviceGetPCIBusId(id,sizeof(id),i));if(pci==id)dev=i;}must(dev>=0,"branch PCI selection");hip_ok(hipSetDevice(dev));fs::create_directories(output);
 auto artifact=load_artifact(input);std::ifstream prefixes(input/"prefixes.tsv");std::string line;must(bool(std::getline(prefixes,line)),"branch metadata");auto config=engram::inspect_metadata(fs::u8path(fields(line).at(1)));auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
 auto weight=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,dev,true});auto rows=std::make_unique<cache::RowSupply>(cache::RowConfig{24,24,1,1,dev},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));auto id=fixture_identity();id.request_id="T20-defaultlast-audit-fresh";CoreConfig cfg;cfg.device=dev;must(!cfg.full_logits&&cfg.audit==nullptr,"actual default configuration");std::unique_ptr<CoreSequence> sequence;
 try{
 sequence=std::make_unique<CoreSequence>(artifact,config,*weight,*rows,id,cfg,3);auto last=sequence->prefill({3,37},0);must(last.rows==1&&last.vocabulary==129280&&last.logits.size()==129280&&sequence->position()==2,"default last row/state");write_file(output/"last-logits.bin",last.logits);auto stats=sequence->runtime_stats();auto reads=weight->stats().weight_read;
 auto reject=[&](auto action){bool refused=false;try{action();}catch(const std::exception&){refused=true;}must(refused,"branch expected rejection");};
 reject([&]{sequence->step(129280,2);});reject([&]{sequence->step(3,2);});must(sequence->position()==2&&weight->stats().weight_read==reads,"failed sequence not reused/no new read");sequence.reset();
 auto residual=read_file<float>(input/"residual.bin"),pre=read_file<float>(input/"pre.bin");BranchAudit audit(output);std::ofstream counter(output/"branch-stats.tsv");counter<<"default\t"<<last.rows<<'\t'<<last.vocabulary<<"\t2\t"<<stats.requested_output_or_fixture_download_bytes<<'\t'<<stats.storage_upload_bytes<<'\t'<<stats.storage_device_owned<<'\t'<<reads<<'\n';counter<<"failure\t2\t2\n";
 for(unsigned enabled=0;enabled<2;++enabled){auto fresh=id;fresh.epoch+=enabled+1;cfg.audit=enabled?&audit:nullptr;sequence=std::make_unique<CoreSequence>(artifact,config,*weight,*rows,fresh,cfg,1);must(sequence->position()==0,"fresh position zero");auto before=sequence->runtime_stats();auto result=sequence->audit_layers(0,1,3,0,residual,pre);must(sequence->position()==1,"fresh layer progress");write_file(output/(enabled?"on-residual.bin":"off-residual.bin"),result.residual);write_file(output/(enabled?"on-pre.bin":"off-pre.bin"),result.pre);auto after=sequence->runtime_stats();counter<<(enabled?"audit-on":"audit-off")<<'\t'<<sequence->position()<<'\t'<<(after.requested_output_or_fixture_download_bytes-before.requested_output_or_fixture_download_bytes)<<'\t'<<(enabled?audit.calls:0)<<'\t'<<(enabled?audit.bytes:0)<<"\t0\n";sequence.reset();}
 counter.flush();must(weight->try_close()&&rows->try_close(),"branch owner drain");HMODULE handles[2048];DWORD needed=0;must(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"branch module list");std::ofstream modules(output/"loaded-modules.txt");for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768]{};must(GetModuleFileNameA(handles[i],path,sizeof(path))>0,"branch module path");modules<<path<<'\n';}std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"branch_fixture\":true,\"GPU_used\":true,\"caller_comparison_required\":true}\n";return 0;
 }catch(const std::exception&e){std::cerr<<"branch original error: "<<e.what()<<'\n'<<std::flush;sequence.reset();if(!weight->try_close())weight.release();if(!rows->try_close())rows.release();throw;}
}

}
int main(int argc,char**argv){try{
 if(argc==5&&std::string(argv[1])=="--capacity-owner")return owner_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4],true,true);
 if(argc==5&&std::string(argv[1])=="--branch-core")return branch_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4]);
 if(argc==5&&std::string(argv[1])=="--full-core")return full_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4]);
 if(argc==5&&std::string(argv[1])=="--hot-owner")return owner_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4],true);
 if(argc==5&&std::string(argv[1])=="--owner")return owner_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),"0000:07:00.0"==std::string(argv[4])?"0000:07:00.0":argv[4]);
 if(argc==2&&std::string(argv[1])=="--identity"){std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\"}\n";return 0;}
 unsigned n=0;auto check=[&](bool x){if(!x)throw std::runtime_error("core host assertion");++n;};
 auto reject=[&](auto f){try{f();}catch(const std::exception&){++n;return;}throw std::runtime_error("missing rejection");};
 strata_ext::cache::DemandOrder order;using K=strata_ext::cache::Kind;
 check(order.candidates()==std::array<K,3>{K::Expert,K::Row,K::Prefetch});
 // A denied/zero-read candidate does not call issued: same order is retained.
 check(order.candidates()[0]==K::Expert);order.issued(K::Row);check(order.candidates()[0]==K::Expert);
 order.issued(K::Expert);check(order.candidates()[0]==K::Row);order.issued(K::Prefetch);check(order.candidates()[0]==K::Row);
 reject([&]{order.issued(static_cast<K>(99));});
 auto pure=attention_role(0);check(pure.ratio==0&&pure.kv_writer==40&&pure.index_writer==40);
 check(attention_role(7).kv_writer==2&&attention_role(8).kv_writer==8);
 check(attention_role(13).kv_writer==8&&attention_role(14).kv_writer==14);
 check(attention_role(19).ratio==2&&attention_role(20).ratio==1);
 check(attention_role(23).index_writer==20&&attention_role(24).index_writer==24);
 check(attention_role(39).kv_writer==20&&attention_role(39).index_writer==36);
 reject([&]{attention_role(40);});
 SourceTensor s;s.source={2,"candidate-full.gguf",10000000000ULL,std::string(40,'a'),std::string(64,'b')};
 s.span={2,39,"blk.0.ffn_up_exps.weight",{5120,2304,384},2720,100000,2720ULL*2304*384};
 auto t=source_tile(s,38,2300,4);check(t.absolute_offset==100000+(38ULL*2304+2300)*2720&&t.bytes==10880&&t.original.span.dims_ggml.size()==3);
 reject([&]{source_tile(s,384,0,1);});reject([&]{source_tile(s,0,2303,2);});reject([&]{source_tile(s,0,0,0);});
 auto tiles=row_tiles(s,38,2097152,256);check(tiles.size()==9&&tiles.back().row_count==256);check(tiles.front().k==5120&&tiles.back().row_first==2048);
 auto wrong=s;wrong.span.row_bytes++;reject([&]{source_tile(wrong,0,0,1);});wrong=s;wrong.source.shard_index=3;reject([&]{source_tile(wrong,0,0,1);});wrong=s;wrong.source.original_size=1;reject([&]{source_tile(wrong,0,0,1);});
 check(batch_waves(19)==std::vector<uint32_t>({8,8,2,1}));reject([&]{batch_waves(0);});reject([&]{row_tiles(s,0,1,256);});
 check(concurrent_peak({{"state",0,10,100},{"weight",1,5,40},{"output",2,8,20},{"scratch",3,4,30}})==190);
 check(concurrent_peak({{"a",0,1,5},{"b",1,2,7}})==7);reject([&]{concurrent_peak({{"same",0,1,1},{"same",1,2,1}});});
 check(CoreMemory{1,2,3,4,5,6}.explicit_owned()==21);
 strata_ext::quant::ProjectionLease owner;DeviceView in{reinterpret_cast<void*>(1),19ULL*5120*4,19,5120,DeviceScalar::Float32,0,&owner,owner.generation};DeviceView out{reinterpret_cast<void*>(2),19ULL*2304*4,19,2304,DeviceScalar::Float32,0,&owner,owner.generation};
 CoreConfig cfg;unsigned callbacks=0;tiled_projection(s,38,in,out,19,cfg,reinterpret_cast<void*>(3),[&](const auto& tile,const auto&x,const auto&y,uint64_t batch,void*){check((batch==8||batch==2||batch==1)&&x.rows==batch&&y.rows==batch&&x.columns==5120&&y.columns==2304&&tile.k==5120);++callbacks;});check(callbacks==36);
 owner.active=false;reject([&]{validate_device_view(in,0);});owner.active=true;owner.generation++;reject([&]{validate_device_view(in,0);});
 std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"host_assertions\":"<<n<<",\"GPU_used\":false,\"full_source_qualified\":false}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
