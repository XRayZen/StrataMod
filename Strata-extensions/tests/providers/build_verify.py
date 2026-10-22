"""Fixed CPU-only T29 pure-provider qualification; never register or launch."""
import hashlib,importlib.util,json,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[3];EXT=ROOT/'Strata-extensions';DATA=ROOT.parents[1];BUILD=ROOT/'build-deepseek-t29';OWN=[EXT/'control/providers/__init__.py',EXT/'control/providers/deepseek41.py',DATA/'model_catalog.py',*(EXT/'tests/providers'/x for x in ('contract.json','test_provider.py','build_verify.py'))]
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def record(p):p=pathlib.Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def protected():return {str(p):sha(p) for p in (DATA/'profiles').glob('*.json')}
def verify():
 BUILD.mkdir(exist_ok=True);contract=load(EXT/'tests/providers/contract.json');assert sha(ROOT/contract['plan'])==contract['plan_sha256'];assert sha(BUILD/'before/model_catalog.py')==contract['before_catalog_sha256']
 inputs=[EXT/'tests/artifact/source-files.json',EXT/'tests/artifact/header-inventory.json',EXT/'tests/artifact/full-model-receipt.json',ROOT/'build-deepseek-t10/bundle-offline-r7/full-source-verification.json',ROOT/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json',BUILD/'before/model_catalog.py',DATA/'profile_defaults.py',EXT/'control/contracts.py',EXT/'native/artifact/full_acquire.py',pathlib.Path(sys.executable)]
 bound={str(p.resolve()):sha(p) for p in OWN+inputs};before=protected()
 result=subprocess.run([sys.executable,'-B','-X','utf8',str(EXT/'tests/providers/test_provider.py')],capture_output=True,text=True,encoding='utf-8');(BUILD/'tests.stdout.txt').write_text(result.stdout,encoding='utf-8');(BUILD/'tests.stderr.txt').write_text(result.stderr,encoding='utf-8');assert result.returncode==0,result.stderr
 provider=module('t29_provider_actual',EXT/'control/providers/deepseek41.py');acquire=module('t29_existing_source_validation',EXT/'native/artifact/full_acquire.py');source,inventory,fixtures=acquire.load_fixed();receipt=load(EXT/'tests/artifact/full-model-receipt.json');acquire.validate_receipt(receipt,acquire.DESTINATION,source,inventory,fixtures)
 # Exercise actual original files with the historical native capture as an
 # explicit fixture placeholder. This cannot claim T28 normal binary readiness.
 asset=dict(artifact_root=str(acquire.DESTINATION),native_paths=provider.paths(str(acquire.DESTINATION)),fixedrevision=provider.REVISION,layout=provider.LAYOUT,tokenizer=str(inputs[4]),exe=str(ROOT/'build-deepseek-t20/full-core-attempt-1/captured-native.exe'))
 bound[asset['exe']]=sha(asset['exe']);checked=provider.assets(asset)
 spans=[dict(shard_index=shard['index'],absolute_offset=t['absolute_offset'],bytes=t['bytes'],type_id=t['type_id'],dims=t['dims_ggml'],row_bytes=t['row_bytes']) for shard in inventory['shards'] for t in shard['tensors']];provider.source_spans(checked,spans);assert len(spans)==1043
 profile=provider.profile(asset,262144,dict(primary_pci='0000:07:00.0',secondary=None,cache_budget=dict(device_cache_payload_bytes='auto',ram_cache_payload_bytes='auto'),host='127.0.0.1',port=18080,env={}))
 generated=BUILD/'isolated-generated-profile.json';generated.write_text(json.dumps(profile,indent=2)+'\n',encoding='utf-8');provider.validate_profile(load(generated),262144)
 acquire.validate_receipt(receipt,acquire.DESTINATION,source,inventory,fixtures);assert protected()==before,'existing profile bytes changed'
 assert all(sha(path)==digest for path,digest in bound.items()),'bound source/input/runtime changed'
 proof=dict(schema='strata-T29-pure-provider-result/v1',source_binding=bound,protected_profiles=before,protected_profiles_before_after=True,tests=12,qualified_source_paths=checked['sources'],original_spans=1043,fixture_generated_profile=record(generated),normal_producer_used=False,normal_profile_published=False,official_registration=False,manager_or_CLI_launch=False,declared_budget_not_resolved=True,T28_dependency_complete=False,task_complete=False,scope=contract['scope'],source_before_after=True,CPU_runtime=dict(executable=record(sys.executable),version=sys.version))
 out=BUILD/'verification.json';out.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8');print(json.dumps(record(out)))
if __name__=='__main__':
 if sys.argv[1:]==['--runtime-stage']:
  import runtime_stage
  runtime_stage.stage()
 elif len(sys.argv)==3 and sys.argv[1]=='--runtime-replay':
  import runtime_stage
  print(json.dumps(runtime_stage.replay(sys.argv[2])))
 elif len(sys.argv)==3 and sys.argv[1]=='--deployment-candidate':
  import runtime_stage
  runtime_stage.deployment_candidate(sys.argv[2])
 elif len(sys.argv)==3 and sys.argv[1]=='--publish':
  import runtime_stage
  runtime_stage.publish(sys.argv[2])
 elif len(sys.argv)==3 and sys.argv[1]=='--publication-verify':
  import runtime_stage
  runtime_stage.verify_publication(sys.argv[2])
 elif not sys.argv[1:]:verify()
 else:raise SystemExit('expected no arguments or --runtime-stage')
