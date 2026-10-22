#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>
#include <utility>
namespace strata_ext::protocol {
// Transport identity only: actual producer/owner binding belongs to T28/T24.
struct Context {
    std::string request_id;
    uint64_t runtime_epoch=0;
    std::string bundle_id,asset_revision,tokenizer_identity,model_family,tokenizer_model,tokenizer_pre;
    uint32_t vocab_size=0;
};
struct TokenLogprob {float logprob=0;std::vector<std::pair<uint32_t,float>> alternatives;};
enum class Finish { Stop, Length, Cancel, NonFinite, Error };
class GenerationEmitter {
public:
    explicit GenerationEmitter(Context,bool metadata=false);
    ~GenerationEmitter();
    GenerationEmitter(const GenerationEmitter&)=delete;
    GenerationEmitter& operator=(const GenerationEmitter&)=delete;
    std::string begin();
    std::string tokens(const std::vector<uint32_t>& original_ids);
    std::string tokens(const std::vector<uint32_t>& original_ids,const std::vector<TokenLogprob>&);
    std::string finish(Finish,const std::string& stop_origin="");
private:
    struct State;
    std::unique_ptr<State> state_;
};
}
