#include "../../models/deepseek41/sampling.hpp"
#include "../../native/protocol/generation.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
using namespace strata_ext::deepseek41;
static unsigned checks=0;
void require(bool x){++checks;if(!x)throw std::runtime_error("sampler assertion "+std::to_string(checks));}
template<class F>void rejects(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}require(caught);}
int main(int argc,char**argv){try{
 if(argc==2&&std::string(argv[1])=="--frames" || (argc==2&&std::string(argv[1])=="--frames-zero")){
  strata_ext::protocol::Context c{"request0",1,std::string(64,'a'),"f924b94f19c1fea02c06a65c8475b0a45e2b88b1","100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924","deepseek41","gpt2","joyai-llm",129280};
  strata_ext::protocol::GenerationEmitter e(c,true);std::cout<<e.begin()<<'\n'<<e.tokens({5,1},{{std::string(argv[1])=="--frames-zero"?-0.0f:-1.0f,{{5,-1}}},{-2,{}}})<<'\n'<<e.finish(strata_ext::protocol::Finish::Stop,"eos")<<'\n';return 0;
 }
 SamplingOptions o;o.temperature=0;std::vector<float> v(129280,-10);v[120001]=4;
 require(sample_logits(v,{},o,0).id==120001);
 v.assign(129280,0);o.temperature=1;o.top_k=0;
 require(sample_logits(v,{},o,.999999).id==129279);
 o.top_k=65;require(sample_logits(v,{},o,.999).id==64);
 o.top_k=0;o.temperature=0;v={2,1,.5f};o.frequency_penalty=2;
 require(sample_logits(v,{0},o,0).id==1);
 o.frequency_penalty=-2;require(sample_logits(v,{1},o,0).id==1);
 o.frequency_penalty=0;o.presence_penalty=2;require(sample_logits(v,{0},o,0).id==1);
 o.penalty_last_n=0;require(sample_logits(v,{0},o,0).id==0);
 o.penalty_last_n=1;require(sample_logits(v,{0,1},o,0).id==0);
 o.penalty_last_n=-1;require(sample_logits(v,{0,1},o,0).id==2);
 o=SamplingOptions{};o.temperature=0;o.logprobs=true;o.top_logprobs=3;
 auto s=sample_logits({0,0,0},{},o,0);require(s.id==0&&s.alternatives.size()==3);
 require(std::abs(s.logprob-float(-std::log(3.0)))<1e-7);
 for(unsigned i=0;i<3;++i)require(s.alternatives[i].first==i);
 o.logit_bias={{2,5}};require(sample_logits({0,0,0},{},o,0).id==2);
 o=SamplingOptions{};o.top_p=.5;require(sample_logits({0,0,0,0},{},o,.99).id==1);
 o.top_p=1;o.min_p=1;require(sample_logits({1,0},{},o,.99).id==0);
 auto bad=o;bad.temperature=-1;rejects([&]{sample_logits(v,{},bad,0);});
 bad=o;bad.top_k=-1;rejects([&]{sample_logits(v,{},bad,0);});
 bad=o;bad.frequency_penalty=2.1;rejects([&]{sample_logits(v,{},bad,0);});
 rejects([&]{sample_logits({}, {},o,0);});
 rejects([&]{sample_logits({std::numeric_limits<float>::infinity()}, {},o,0);});
 rejects([&]{sample_logits(v,{3},o,0);});
 rejects([&]{sample_logits(v,{},o,1);});
 RequestSampler a(0),b(0);for(unsigned i=0;i<100;++i)require(a.sample({0,0,0},{},SamplingOptions{}).id==b.sample({0,0,0},{},SamplingOptions{}).id);
 std::cout<<"{\"assertions\":"<<checks<<"}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
