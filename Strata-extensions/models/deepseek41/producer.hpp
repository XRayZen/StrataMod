#pragma once
#include "sampling.hpp"
#include "routing_policy.hpp"
#include <filesystem>
#include <memory>
#include <string>
#include <optional>
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
#include <functional>
#ifdef STRATA_T38_GLOBAL_FIXTURE
#include "dspark/target_adapter.hpp"
#endif
namespace strata_ext::dspark::t38 {struct Asset;struct ActorResult;struct RequestBinding;class ActorTarget;class ActorDraft;class DraftNetwork;}
#endif
namespace strata_ext::deepseek41 {
#ifdef STRATA_T38_GLOBAL_FIXTURE
struct DeviceAudit;
#endif
struct ProducerConfig {
 bool projection_graph=false;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 // Fixture root is copied into Owners before Core construction. It outlives Core.
 std::shared_ptr<DeviceAudit> fixture_audit_root;
#endif
 std::filesystem::path artifact_root;std::vector<std::filesystem::path> native_paths;
 std::string primary_pci,bundle_id,mode="single",secondary_pci;uint64_t runtime_epoch=0,context=0;
 std::optional<uint64_t> device_cache_payload_bytes,ram_cache_payload_bytes,secondary_device_cache_payload_bytes;
 std::optional<std::vector<uint32_t>> secondary_experts;
 std::optional<uint32_t> layer_cut;
 double auto_cache_fraction=.5,auto_row_fraction=1.0/64;
 uint64_t tile_bytes=2*1024*1024,tile_rows=256,active_batch=8;
 // Optional normal native DSpark launch configuration; absent preserves legacy GEN.
 std::string dspark_draft,dspark_prefix;
 std::optional<uint64_t> dspark_draft_credit,dspark_target_credit;
 uint64_t dspark_width=5,dspark_deferred_host_bytes=0;
 routing::Config routing;
};
// Normal process entry. Existing owner/control launches it; no runtime registry.
int serve(const ProducerConfig&);
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
namespace t38=strata_ext::dspark::t38;
using T38FixtureBody=std::function<t38::ActorResult(t38::ActorTarget&,t38::ActorDraft&,t38::DraftNetwork&,const t38::RequestBinding&)>;
#ifdef STRATA_T38_GLOBAL_FIXTURE
struct T38FixtureNext {std::string request_id;t38::RequestBinding binding;T38FixtureBody body;};
struct T38GlobalFixture {T38FixtureBody body;std::optional<T38FixtureNext> next;std::shared_ptr<DeviceAudit> audit;};
T38GlobalFixture make_t38_global_fixture(std::string input_manifest,std::string output_directory);
#endif
t38::ActorResult t38_actual_fixture(const ProducerConfig&,const std::string& request_id,
 const std::string& draft_path,const t38::Asset&,uint64_t draft_credit,uint64_t target_credit,
 t38::RequestBinding,T38FixtureBody
#ifdef STRATA_T38_GLOBAL_FIXTURE
 ,std::optional<T38FixtureNext> next={}
#endif
 );
T38FixtureBody make_t38_seed_body(std::string input_manifest,std::string output_directory);
#endif
}
