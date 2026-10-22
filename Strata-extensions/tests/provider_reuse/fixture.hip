#include <strata/core/device.hpp>
#define main historical_t20_main
#include "../core/core_fixture.cpp"
#undef main
namespace {
std::ofstream* provider_trace=nullptr;
std::string active_phase;
uint64_t take_count=0;
int actual_primary(){int count=0;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char pci[64]{};hip_ok(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(std::string(pci)=="0000:07:00.0")return i;}throw std::runtime_error("requested actual primary PCI absent");}
}
extern "C" void strata_t35_provider_trace(const char*event,uint64_t provider,uint64_t completed,uint64_t window,uint64_t logical,uint64_t requested,uint64_t metadata,uint64_t generation)noexcept{
 if(!provider_trace)return;
 *provider_trace<<active_phase<<'\t'<<event<<'\t'<<provider<<'\t'<<completed<<'\t'<<window<<'\t'<<logical<<'\t'<<requested<<'\t'<<metadata<<'\t'<<generation<<'\n';provider_trace->flush();if(std::string(event)=="take")++take_count;
}
namespace {
int execute(const fs::path&input,const fs::path&output){
 using namespace strata_ext;using namespace strata_ext::deepseek41;
 fs::create_directories(output);auto artifact=load_artifact(input);int device=actual_primary();hip_ok(hipSetDevice(device));
 std::ofstream trace(output/"trace.tsv"),stats(output/"stats.tsv"),controls(output/"controls.tsv");provider_trace=&trace;
 CoreStorage storage(device);auto x=storage.allocate("input",3,5120,DeviceScalar::Float32);auto workspace=storage.allocate("output",3,2304,DeviceScalar::Float32);unsigned checks=0;
 auto identity=fixture_identity();identity.request_id="T35-persistent-provider";
 struct Job{const char*id;const char*tensor;uint64_t matrix,rows;};
 for(auto job:{Job{"p0","blk.0.ffn_gate_exps.weight",38,64},Job{"p16","blk.0.attn_kv.weight",0,32}}){
  auto source=artifact.source_tensor(job.tensor);auto tile=source_tile(source,job.matrix,0,job.rows);cache::SupplyMatrix matrix{tile.original,tile.absolute_offset,tile.bytes,tile.type,size_t(tile.row_count),size_t(tile.k)};matrix.row_tile=true;matrix.original_matrix=tile.matrix;matrix.output_row_first=tile.row_first;const auto n=source.span.dims_ggml.at(1);
  auto host=read_file<float>(input/(std::string(job.id)+"-x.bin"));must(host.size()==3*5120,"fixed three-row activation");storage.upload(x,host.data(),x.bytes);
  for(bool permit:{true,false}){
   if(!permit)active_phase=std::string(job.id)+"-legacy";
   cache::PrimarySupply weight({2,2,262144,4,4,device,permit});auto y=workspace;y.columns=n;y.bytes=3*n*4;
   auto deadline=[&](auto start){must(std::chrono::steady_clock::now()-start<std::chrono::seconds(60),"finite fixture operation deadline");};
   auto evict=[&](){for(unsigned i=0;i<2;++i)must(weight.evict_device(i),"idle device eviction");weight.evict_ram();};
   auto ready=[&](bool variable){must(weight.begin(matrix,identity),"demand begin");uint64_t issued=0;auto start=std::chrono::steady_clock::now();while(weight.state()!=cache::SupplyState::Ready){deadline(start);must(weight.state()!=cache::SupplyState::Cancelled&&weight.state()!=cache::SupplyState::Quarantined,"unexpected demand cancellation");if(permit){auto bytes=variable&&issued==0?4096:65536;if(weight.issue_reads(1,bytes))++issued;weight.poll_io(10);weight.poll_device();}else weight.advance();}};
   auto numeric=[&](const std::string&name,bool cold,bool variable){active_phase=std::string(job.id)+"-"+name;if(cold)evict();auto before=weight.stats();hip_ok(hipMemsetAsync(y.data,255,y.bytes,reinterpret_cast<hipStream_t>(storage.stream())));uint64_t from=0;
    for(auto batch:batch_waves(3,8)){ready(variable);uint64_t dx=from*5120*4,dy=from*n*4;weight.launch_device(batch,reinterpret_cast<const float*>(static_cast<const char*>(x.data)+dx),x.bytes-dx,reinterpret_cast<float*>(static_cast<char*>(y.data)+dy),y.bytes-dy,n,storage.stream(),*x.owner);auto start=std::chrono::steady_clock::now();while(weight.state()!=cache::SupplyState::Done){deadline(start);weight.poll_device();}must(weight.take_device(identity),"actual output accepted");from+=batch;}
    storage.drain();std::vector<float> result(3*job.rows);hip_ok(hipMemcpy2DAsync(result.data(),job.rows*4,y.data,n*4,job.rows*4,3,hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(storage.stream())));storage.drain();write_file(output/(active_phase+".bin"),result);
    auto after=weight.stats();stats<<active_phase<<'\t'<<after.weight_read-before.weight_read<<'\t'<<after.aligned_read-before.aligned_read<<'\t'<<after.issued_read-before.issued_read<<'\t'<<after.issued_reads-before.issued_reads<<'\t'<<after.weight_h2d-before.weight_h2d<<'\t'<<after.gpu_hits-before.gpu_hits<<'\t'<<after.ram_hits-before.ram_hits<<'\t'<<after.metadata<<'\n';stats.flush();
   };
   numeric(permit?"cold64":"legacy",true,false);
   if(!permit){must(weight.try_close(),"legacy normal close");continue;}
   numeric("resident",false,false);for(unsigned i=0;i<2;++i)must(weight.evict_device(i),"RAM-path device eviction");numeric("ram",false,false);numeric("variable",true,true);
   auto cancelled=[&](const std::string&name,int mode){active_phase=std::string(job.id)+"-"+name;evict();must(weight.begin(matrix,identity),"cancel demand begin");must(weight.issue_reads(0,65536)==0&&weight.issue_reads(1,4095)==0,"no grant no issue");for(int i=0;i<3;++i)weight.poll_io(0);must(weight.progress().issued_read_bytes==0,"poll-only issues no read");checks+=2;
    if(mode){auto prior=take_count;must(weight.issue_reads(1,65536)>0,"real cancel window issued");if(mode==1){auto start=std::chrono::steady_clock::now();while(take_count==prior){deadline(start);weight.poll_io(10);}must(weight.state()==cache::SupplyState::Reading,"between-window cancellation");}}
    weight.cancel();auto start=std::chrono::steady_clock::now();while(weight.state()!=cache::SupplyState::Cancelled){deadline(start);weight.poll_io(10);weight.poll_device();}must(weight.take(identity).empty()&&weight.state()==cache::SupplyState::Idle,"cancelled result unpublished/taken");++checks;controls<<active_phase<<"\tcancelled\t"<<mode<<'\n';
   };
   cancelled("cancel-before",0);numeric("fresh-before",true,false);cancelled("cancel-between",1);numeric("fresh-between",true,false);cancelled("cancel-issued",2);numeric("fresh-issued",true,false);
   active_phase=std::string(job.id)+"-prefetch-between";evict();must(weight.begin(matrix,identity,true),"finite prefetch begin");auto previous=take_count;must(weight.issue_reads(1,65536)>0,"prefetch actual issue");auto start=std::chrono::steady_clock::now();while(take_count==previous){deadline(start);weight.poll_io(10);}weight.cancel_prefetch();while(weight.prefetch_state()!=cache::SupplyState::Cancelled){deadline(start);weight.poll_io(10);}must(!weight.take_prefetch(identity),"cancelled prefetch unpublished");++checks;controls<<active_phase<<"\tcancelled\t3\n";numeric("fresh-prefetch",true,false);
   active_phase=std::string(job.id)+"-source-error";evict();auto missing=matrix;missing.original.source.original_path=output/"missing-original-do-not-create.gguf";must(!fs::exists(missing.original.source.original_path),"owned missing source control");bool failed=false;try{must(weight.begin(missing,identity),"source-error begin");weight.issue_reads(1,65536);}catch(const std::exception&){failed=true;}must(failed,"original source error not hidden");weight.cancel();start=std::chrono::steady_clock::now();while(weight.state()!=cache::SupplyState::Cancelled){deadline(start);weight.poll_io(10);}must(weight.take(identity).empty(),"failed original output unpublished");++checks;controls<<active_phase<<"\terror\t0\n";numeric("fresh-error",true,false);
   must(weight.try_close(),"actual persistent owner close");
  }
 }
 provider_trace=nullptr;trace.close();stats.close();controls.close();must(bool(trace)&&bool(stats)&&bool(controls),"complete fixture records");
 HMODULE handles[2048];DWORD needed=0;must(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"actual runtime modules");std::ofstream modules(output/"loaded-modules.txt");for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768]{};must(GetModuleFileNameA(handles[i],path,sizeof(path))>0,"actual module path");modules<<path<<'\n';}
 std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"checks\":"<<checks<<",\"device\":"<<device<<",\"model_performance_qualified\":false}"<<'\n';return 0;
}
}
int main(int argc,char**argv){try{if(argc==2&&std::string(argv[1])=="--host")return historical_t20_main(1,argv);must(argc==3,"input output required");return execute(fs::u8path(argv[1]),fs::u8path(argv[2]));}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
