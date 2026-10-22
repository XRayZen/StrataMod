#include "generation.hpp"
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace strata_ext::protocol;
int main(int argc,char** argv){try{
    if(argc==2 && std::string(argv[1])=="--identity"){std::cout<<"{\"source_sha256\":\""<<T23_SOURCE_SHA<<"\"}\n";return 0;}
    if(argc!=3)throw std::invalid_argument("expected fixture name and bundle identity");
    std::string name=argv[1];
    Context context{"request-23",7,argv[2],"f924b94f19c1fea02c06a65c8475b0a45e2b88b1",
        "100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924","deepseek41","gpt2","joyai-llm",129280};
    if(name=="unicode")context.request_id=u8"要求\"\\\n\t23";
    GenerationEmitter emitter(context);
    if(name=="before-begin"){emitter.tokens({17});throw std::runtime_error("accepted before begin");}
    std::cout<<emitter.begin()<<'\n';
    if(name=="duplicate-begin"){emitter.begin();throw std::runtime_error("accepted duplicate begin");}
    if(name=="empty-batch"){emitter.tokens({});throw std::runtime_error("accepted empty batch");}
    if(name=="invalid-id"){emitter.tokens({129280});throw std::runtime_error("accepted invalid ID");}
    if(name!="empty"){
        std::cout<<emitter.tokens({0,17})<<'\n';
        if(name!="cancel" && name!="error" && name!="nonfinite")std::cout<<emitter.tokens({129279})<<'\n';
    }
    Finish finish=name=="cancel"?Finish::Cancel:name=="error"?Finish::Error:name=="nonfinite"?Finish::NonFinite:name=="length"?Finish::Length:Finish::Stop;
    std::cout<<emitter.finish(finish)<<'\n';
    if(name=="after-finish"){emitter.tokens({1});throw std::runtime_error("accepted after finish");}
    if(name=="duplicate-finish"){emitter.finish(Finish::Stop);throw std::runtime_error("accepted second finish");}
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
