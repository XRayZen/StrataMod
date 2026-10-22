#include "generation.hpp"
#include <fstream>
#include <iostream>
#include <sstream>
using namespace strata_ext::protocol;
int main(int argc,char**argv){try{
 if(argc==2&&std::string(argv[1])=="--identity"){std::cout<<"{\"source_id\":\""<<T28_SOURCE_ID<<"\"}";return 0;}
 if(argc!=4)throw std::runtime_error("bundle, finish, explicit batches path required");
 Context c{"t28-controlled",28,argv[1],"f924b94f19c1fea02c06a65c8475b0a45e2b88b1","100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924","deepseek41","gpt2","joyai-llm",129280};GenerationEmitter emitter(c);std::cout<<emitter.begin()<<'\n';
 std::ifstream input(argv[3]);if(!input)throw std::runtime_error("fixture batch file");std::string line;
 while(std::getline(input,line)){std::stringstream s(line);std::string token;std::vector<uint32_t> ids;while(std::getline(s,token,','))ids.push_back(std::stoul(token));if(!ids.empty())std::cout<<emitter.tokens(ids)<<'\n';}
 std::string reason=argv[2];Finish f;if(reason=="stop")f=Finish::Stop;else if(reason=="length")f=Finish::Length;else if(reason=="cancel")f=Finish::Cancel;else if(reason=="error")f=Finish::Error;else if(reason=="nonfinite")f=Finish::NonFinite;else throw std::runtime_error("fixture finish");std::cout<<emitter.finish(f)<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<e.what();return 1;}}
