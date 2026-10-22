import tempfile
import copy
import hashlib
import json
import math
import struct
import unittest
from unittest import mock
import os
from pathlib import Path
import subprocess
import sys
import eager_bench as B
import build_verify as R

def context(request='test-A'):
 return dict(request_id=request,runtime_epoch=1,bundle_id='a'*64,asset_revision=B.DTO.REVISION,model_family='deepseek41',tokenizer_identity=B.DTO.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)

def info(counter=0,core=40):
 value=dict(family='deepseek41',**{key:counter for key in B.OWNER_COUNTERS},**{key:core for key in B.CORE_COUNTERS},**{key:4 for key in B.BUDGET})
 value.update(core_storage_device_owned=256,primary_device_owned=512,row_device_owned=64,actual_device_owned=832,owner_metadata_bytes=64,owned_host_owner_subset_bytes=2112,primary_received=None)
 for prefix in ('primary','row'):value.update({prefix+'_pinned_known':True,prefix+'_pinned_observed':True,prefix+'_pinned_subset':128,prefix+'_host_owned':1024})
 return value

def capture(ids=(37,1024),groups=None,request='test-A',start=1000):
 groups=groups if groups is not None else [[x] for x in ids];c=context(request);base=dict(schema='strata-generation/v1',request_id=request,runtime_epoch=1);events=[]
 def add(value,t):events.append(dict(line=json.dumps(value),t_ns=start+t))
 add(dict(base,kind='begin',**{k:v for k,v in c.items() if k not in ('request_id','runtime_epoch')}),10)
 events.append(dict(line='PP 0 4',t_ns=start+20));events.append(dict(line='PP 4 4',t_ns=start+30))
 flat=[]
 for i,group in enumerate(groups):add(dict(base,kind='token_batch',sequence=i,origin='native-generated',ids=group),40+i*20);flat.extend(group)
 digest=hashlib.sha256(b''.join(struct.pack('<I',x) for x in flat)).hexdigest()
 add(dict(base,kind='finish',sequence=len(groups),generated_count=len(flat),finish='stop' if flat and flat[-1]==1 else 'length',ids_sha256=digest),80)
 events.append(dict(line='DONE '+str(len(flat)),t_ns=start+90))
 return dict(context=c,process_id=123,request_index=0,workload_identity='f'*64,clock_domain='perf_counter_ns',clock_resolution_ns=1,request_start_ns=start,events=events,info_before=info(0,100),info_after=info(10,40))

class BenchTests(unittest.TestCase):
 def test_key_lookup_strict_metadata_result(self):
  value=dict(schema='T35-key-lookup/v1',key_hex='41',cases=[],original_weight_read_bytes=0,GPU=0,physical_io=None,model_performance_qualified=False)
  with self.assertRaises((ValueError,RuntimeError)):R.validate_key_lookup(value,'41')
  value['original_weight_read_bytes']=True
  with self.assertRaises((ValueError,RuntimeError)):R.validate_key_lookup(value,'41')
 def metadata_input(self):
  record=lambda p:dict(path=str(Path(p).resolve()),sha256='1'*64)
  refs={name:record(path)for name,path in R.ACCEPTED_REFS.items()};refs['normal']=record(R.BUILD/'metadata-only-normal-receipt.json')
  c=dict(schema='T35-actual-execution-input/v1',phase='pilot',command=[sys.executable,'--serve','--context','4096','--bundle-id','a'*64,'--runtime-epoch','1'],executable=record(sys.executable),prompt_ids=[0,37],implicit_BOS=False,maximum_new_tokens=3,context=4096,bundle_id='a'*64,runtime_epoch=1,sampling=dict(temperature=0,seed=0,top_k=0,top_p=1,min_p=0,logprobs=False),flags=dict(graph=False,dspark=False,secondary=False),qualification_refs=refs,prompt_encoding_evidence=record(R.BUILD/'metadata-only-encoding.json'),normal_bundle_manifest=record(R.BUILD/'metadata-only-native-manifest.json'),environment={},cwd=str(Path(__file__).parent))
  encoding=dict(raw_prompt_ids=[0,37],input_count=2,context=4096,reserved_generated_tokens=3,implicit_BOS=False,contract=record(R.HERE/'eager_contract.json'),tokenizer=record(R.BUILD/'metadata-only-tokenizer'),recipe_module=record(R.BUILD/'metadata-only-recipe'))
  def read(path):
   if str(path)==c['prompt_encoding_evidence']['path']:return encoding
   if str(path)==c['normal_bundle_manifest']['path']:return dict(bindings=[record(sys.executable)])
   raise AssertionError('unexpected metadata read')
  return c,record,read
 def test_native_model_and_loaded_DLL_closure(self):
  import tempfile
  with tempfile.TemporaryDirectory()as directory:
   root=Path(directory);models=[];dlls={}
   for index in range(9):
    p=root/('source'+str(index)+'.gguf');p.write_bytes(b'fixture');models.append(dict(path=str(p),identity=R.stat_identity(p)))
   for name in ('amdhip64_7.dll','amd_comgr.dll','rocm_kpack.dll'):
    p=root/name;p.write_bytes(b'ownedfixture');dlls[name]=R.row(p)
   manifest=root/'manifest.json';R.save(manifest,dict(bindings=list(dlls.values())))
   config=dict(model_identity=models,normal_bundle_manifest=R.row(manifest),owned_runtime_modules=dlls)
   info=dict(loaded_runtime_modules={name:r['path']for name,r in dlls.items()})
   self.assertTrue(R.runtime_snapshot(config,info)['loaded_modules_complete'])
   unknown=R.runtime_snapshot(config,{});self.assertIsNone(unknown['loaded_modules_complete']);self.assertIsNone(unknown['loaded_modules']['amdhip64_7.dll']['observed_path'])
   bad=copy.deepcopy(info);bad['loaded_runtime_modules']['amdhip64_7.dll']=str(root/'foreign.dll')
   with self.assertRaises(ValueError):R.runtime_snapshot(config,bad)
   Path(models[0]['path']).write_bytes(b'changed')
   with self.assertRaises(ValueError):R.runtime_snapshot(config,info)
 def test_execution_metadata_only_no_binary_or_GPU_run(self):
  c,record,read=self.metadata_input()
  with mock.patch.object(R,'row',side_effect=record),mock.patch.object(R,'read',side_effect=read):self.assertIs(R.validate_input(c),c)
 def test_execution_declaration_faults_do_not_reach_process(self):
  c,record,read=self.metadata_input()
  for fault in ('bool_seed','bool_logits','numeric_flag','secret_env','unknown_phase','implicitBOS','bool_ID','launch_context','named_refs'):
   value=copy.deepcopy(c)
   if fault=='bool_seed':value['sampling']['seed']=False
   if fault=='bool_logits':value['sampling']['logprobs']=0
   if fault=='numeric_flag':value['flags']['graph']=0
   if fault=='secret_env':value['environment']['API_KEY']='do-not-store'
   if fault=='unknown_phase':value['phase']='guess'
   if fault=='implicitBOS':value['implicit_BOS']=True
   if fault=='bool_ID':value['prompt_ids'][0]=False
   if fault=='launch_context':value['command'][3]='16'
   if fault=='named_refs':value['qualification_refs'].pop('T26')
   with mock.patch.object(R,'row',side_effect=record),mock.patch.object(R,'read',side_effect=read):
    with self.assertRaises(ValueError,msg=fault):R.validate_input(value)
 def test_raw_original_count_hash_and_clock(self):
  value=B.analyze_run(capture());self.assertEqual(value['original_ids'],[37,1024]);self.assertEqual(value['generated_count'],2);self.assertEqual(value['TTFT_pipe_seconds']['value'],4e-8);self.assertEqual(value['aggregate_TPOT_pipe_seconds']['value'],2e-8);self.assertEqual(value['counters']['core_storage_upload_bytes'],40)
 def test_EOS_is_counted_even_without_visible_text(self):
  value=B.analyze_run(capture((1,)));self.assertEqual(value['generated_count'],1);self.assertEqual(value['finish'],'stop');self.assertIsNotNone(value['TTFT_pipe_seconds']['value']);self.assertIsNone(value['aggregate_TPOT_pipe_seconds']['value'])
 def test_zero_tokens_is_not_missing_and_TPOT_null(self):
  value=B.analyze_run(capture((),groups=[]));self.assertEqual(value['generated_count'],0);self.assertIsNone(value['TTFT_pipe_seconds']['value']);self.assertIsNone(value['output_tokens_per_request_second']['value'])
 def test_same_frame_coalescing_is_not_native_zero_TPOT(self):
  value=B.analyze_run(capture(groups=[[37,1024]]));self.assertEqual(value['raw_first_last_arrival_span_ns'],0);self.assertIsNone(value['aggregate_TPOT_pipe_seconds']['value'])
 def test_different_frames_same_stamp_or_resolution_unknown(self):
  for stamp,resolution in [(1040,1),(1060,20)]:
   value=capture();value['events'][4]['t_ns']=stamp;value['clock_resolution_ns']=resolution
   self.assertIsNone(B.analyze_run(value)['aggregate_TPOT_pipe_seconds']['value'])
 def test_strict_clock_types_order_domain_and_finite(self):
  for key,value in [('clock_resolution_ns',0),('clock_resolution_ns',True),('clock_domain','wall_clock'),('request_start_ns',float('nan'))]:
   c=capture();c[key]=value
   with self.assertRaises(ValueError):B.analyze_run(c)
  c=capture();c['events'][2]['t_ns']=1
  with self.assertRaises(ValueError):B.analyze_run(c)
 def test_missing_duplicate_reordered_hash_epoch_ID(self):
  for fault in ('missing','duplicate','sequence','hash','epoch','bool_ID'):
   c=capture()
   if fault=='missing':c['events'].pop(-2)
   elif fault=='duplicate':c['events'].insert(4,copy.deepcopy(c['events'][3]))
   else:
    idx=-2 if fault=='hash' else 3;frame=json.loads(c['events'][idx]['line'])
    if fault=='sequence':frame['sequence']=2
    if fault=='hash':frame['ids_sha256']='0'*64
    if fault=='epoch':frame['runtime_epoch']=2
    if fault=='bool_ID':frame['ids']=[True]
    c['events'][idx]['line']=json.dumps(frame)
   with self.assertRaises(ValueError,msg=fault):B.analyze_run(c)
 def test_DONE_not_transport_piece_count(self):
  c=capture();c['events'][-1]['line']='DONE 4'
  with self.assertRaises(ValueError):B.analyze_run(c)
  c=capture();c['events'].pop()
  with self.assertRaises(ValueError):B.analyze_run(c)
 def test_error_cancel_nonfinite_not_success(self):
  for finish in ('cancel','error','nonfinite'):
   c=capture();frame=json.loads(c['events'][-2]['line']);frame['finish']=finish;c['events'][-2]['line']=json.dumps(frame)
   with self.assertRaises(ValueError):B.analyze_run(c)
  c=capture();c['events'][3]['line']='ERR failed'
  with self.assertRaises(ValueError):B.analyze_run(c)
 def test_counter_cumulative_delta_vs_new_Core_absolute(self):
  value=B.info_delta(info(0,1000),info(10,40));self.assertEqual(value['primary_h2d'],10);self.assertEqual(value['core_constant_source_bytes'],40);self.assertEqual(value['known_logical_source_bytes'],60);self.assertIsNone(value['primary_received']);self.assertIsNone(value['physical_io'])
 def test_counter_reset_bool_missing_and_fake_primary_received(self):
  for fault in ('reset','bool','missing','received'):
   a,b=info(10),info(20)
   if fault=='reset':b['primary_h2d']=9
   if fault=='bool':b['row_received']=False
   if fault=='missing':del b['primary_aligned_read']
   if fault=='received':b['primary_received']=0
   with self.assertRaises(ValueError,msg=fault):B.info_delta(a,b)
 def test_owned_alias_pinned_subset_and_unknown_are_not_zero(self):
  c=capture();c['info_after']['primary_pinned_known']=False;c['info_after']['primary_pinned_subset']=None;value=B.analyze_run(c);self.assertIsNone(value['memory']['pinned_subset']['primary']);self.assertEqual(value['device_owned']['actual_device_owned'],832)
  for name,value in [('actual_device_owned',1024),('primary_pinned_subset',2048),('row_pinned_known',0)]:
   c=capture();c['info_after'][name]=value
   with self.assertRaises(ValueError):B.analyze_run(c)
 def test_pair_same_actual_owner_budget_and_output(self):
  a,b=capture(),capture(request='test-B');b['request_index']=1;b['info_before']=info(10,40);b['info_after']=info(20,40)
  self.assertEqual(B.analyze_pair(a,b)['ratios']['TTFT_pipe_seconds']['value'],1)
  for fault in ('budget','process','output','workload','request_index'):
   altered=copy.deepcopy(b)
   if fault=='budget':altered['info_before']['device_slots']=altered['info_after']['device_slots']=5
   if fault=='process':altered['process_id']=124
   if fault=='output':altered=capture((5,6),request='test-B');altered['request_index']=1
   if fault=='workload':altered['workload_identity']='other'
   if fault=='request_index':altered['request_index']=True
   with self.assertRaises(ValueError,msg=fault):B.analyze_pair(a,altered)
 def test_pair_cold_must_be_empty_and_epoch_must_match(self):
  a,b=capture(),capture(request='B');b['request_index']=1;a['info_before']['primary_gpu_hits']=1
  with self.assertRaises(ValueError):B.analyze_pair(a,b)
 def test_cold_counter_zero_is_not_successful_transfer_measurement(self):
  a,b=capture(),capture(request='B');b['request_index']=1
  for field in ('primary_logical_read','primary_aligned_read','primary_issued_reads','primary_h2d','primary_ssd_misses'):
   altered=copy.deepcopy(a);altered['info_after'][field]=0
   with self.assertRaises(ValueError,msg=field):B.analyze_pair(altered,b)
 def test_paired_interval_incomplete_equal_improvement_and_nonfinite(self):
  self.assertEqual(B.paired_interval([1]*5)['effect'],'unjudged');self.assertEqual(B.paired_interval([2]*5)['effect'],'improved');self.assertEqual(B.paired_interval([.5]*5)['effect'],'worse');self.assertIsNone(B.paired_interval([2]*4)['value'])
  for bad in ([0]*5,[True]*5,[math.nan]*5,[math.inf]*5):
   with self.assertRaises(ValueError):B.paired_interval(bad)
  self.assertIsNone(B.paired_interval([1e300,1e-300,1e300,1e-300,1.])['value'])
 def test_host_pipe_controller_only_not_model_performance(self):
  value=capture();lines=[e['line'] for e in value['events']];program='import sys,json\ninfo='+repr(json.dumps(info()))+'\nframes='+repr(lines)+'\nprint("INFO "+info,flush=True)\nprint("READY 4096 stop",flush=True)\nfor line in sys.stdin:\n if line.startswith("INFO"):print("INFO "+info,flush=True)\n elif line.startswith("GEN"):\n  for f in frames:print(f,flush=True)\n elif line.startswith("QUIT"):break\n'
  session=B.ProcessSession([sys.executable,'-u','-c',program],Path(__file__).parent,os.environ.copy())
  try:
   actual=session.request('GEN 2',context(),'host-pipe-only');result=B.analyze_run(actual);self.assertEqual(result['original_ids'],[37,1024]);self.assertEqual(actual['request_index'],0);self.assertEqual(actual['process_id'],session.proc.pid)
  finally:session.close()
  self.assertIsNotNone(session.proc.poll());self.assertTrue(session.proc.stdout.closed);self.assertTrue(session.proc.stderr.closed)
 def test_minimal_pilot_contract_retains_normal_domains(self):
  c=json.loads((Path(__file__).parent/'eager_contract.json').read_text());self.assertEqual(c['messages'],[{'role':'user','content':''}]);self.assertEqual(c['maximum_new_tokens'],2);self.assertFalse(c['fixture_maximum_is_normal_limit']);self.assertEqual(c['cache_budget']['device_cache_payload_bytes'],'auto');self.assertEqual(c['cache_budget']['ram_cache_payload_bytes'],'auto')
 def test_startup_failure_reaps_owned_child_and_preserves_primary_error(self):
  original=subprocess.Popen;children=[]
  def launch(*args,**kwargs):
   child=original(*args,**kwargs);children.append(child);return child
  with mock.patch.object(B.subprocess,'Popen',side_effect=launch):
   with self.assertRaisesRegex(ValueError,'startup-fault')as raised:B.ProcessSession([sys.executable,'-u','-c','print("ERR startup-fault",flush=True);raise SystemExit(3)'],Path(__file__).parent,os.environ.copy())
  self.assertEqual(children[0].poll(),3);self.assertEqual(raised.exception.process_evidence['exit_code'],3);self.assertIn('ERR startup-fault',raised.exception.process_evidence['events'][0]['line'])

class HostIoContractTests(unittest.TestCase):
 def test_host_io_literal_and_meaningful_negatives(self):
  import build_verify as V
  def arm(label):
   chunk=65536 if label=='A' else 2097152
   return dict(arm=label,chunk=chunk,lifecycles=2097152//chunk,logical_requested=2097152,logical_delivered=2097152,read_requested=2097152,received=2097152,direct_reads=2097152//chunk,buffered_reads=0,mapped_reads=0,errors=0,short_reads=0,unknown=0,overread_requested=0,outstanding=0,outstanding_bytes=0,peak_outstanding=1,peak_bytes=chunk,buffer_capacity=chunk,metadata_capacity=4000,host_lifecycle_seconds=.1,enqueue_drain_seconds=.05,exact_bytes=True,sha256='a'*64,closed=True)
  valid=dict(schema='T35-host-io/v1',arms=[arm(x)for x in 'ABBA'],expected_sha256='a'*64,physical_io=None,GPU=0,destination_bytes=2097152,expected_ram_bytes=2097152)
  self.assertTrue(V.validate_host_io(valid,'a'*64)['clean_pair'])
  for fault in ('wrongcount','short','changedbyte','unknownphysical','cleanup','boolcounter'):
   bad=copy.deepcopy(valid)
   if fault=='wrongcount':bad['arms'][0]['direct_reads']=31
   if fault=='short':bad['arms'][0]['received']-=1
   if fault=='changedbyte':bad['arms'][0]['exact_bytes']=False
   if fault=='unknownphysical':bad['physical_io']=0
   if fault=='cleanup':bad['arms'][0]['closed']=False
   if fault=='boolcounter':bad['arms'][0]['received']=True
   with self.assertRaises(ValueError,msg=fault):V.validate_host_io(bad,'a'*64)
  fallback=copy.deepcopy(valid);fallback['arms'][0]['buffered_reads']=1;fallback['arms'][0]['read_requested']+=65536
  self.assertFalse(V.validate_host_io(fallback,'a'*64)['clean_pair'])

class FormalMemoryTests(unittest.TestCase):
 def test_three_pair_interval_and_legacy(self):
  r=B.paired_interval([2,2,2],expected_count=3)
  self.assertEqual(r['value'],[2,2]);self.assertEqual(r['geometric_mean'],2);self.assertEqual(r['relative_precision'],0);self.assertEqual(r['df'],2)
  self.assertIsNone(B.paired_interval([2,2],expected_count=3)['value'])
  self.assertEqual(B.paired_interval([2]*5)['effect'],'improved')
  for bad in (True,4,0):
   with self.assertRaises(ValueError):B.paired_interval([2]*3,expected_count=bad)
 def test_formal_CI_all_conditions_unknown_and_incomplete(self):
  import build_verify as V
  def pair(condition):return dict(memory_condition=dict(condition_met=condition),analysis=dict(ratios={k:dict(value=2)for k in ('TTFT_pipe_seconds','aggregate_TPOT_pipe_seconds')}))
  condition,interval=V.formal_intervals(B,[pair(True)]*3);self.assertIs(condition,True);self.assertEqual(interval['TTFT_pipe_seconds']['df'],2)
  for flag in (False,None):
   condition,interval=V.formal_intervals(B,[pair(True),pair(flag),pair(True)]);self.assertIs(condition,flag);self.assertEqual(interval['TTFT_pipe_seconds']['value'],[2,2])
  with self.assertRaises(ValueError):V.formal_intervals(B,[pair(True)]*2)
 def test_derived_precision_overflow_is_unknown(self):
  result=B.paired_interval([math.exp(-310),math.exp(-20),math.exp(270)],expected_count=3)
  self.assertIsNone(result['value']);self.assertEqual(result['reason'],'unrepresentable_derived_precision');json.dumps(result,allow_nan=False)
 def test_saved_memory_status_identity_and_order_are_rederived(self):
  rows=[dict(point=p,pid=123,birth=10,identity_verified=True,global_status=True,available_physical_bytes=B.DRAM_AIM)for p in ('constructed','A-before','A-monitor','A-after','B-before','B-monitor','B-after')]
  self.assertIs(B.memory_condition(rows)['condition_met'],True)
  for fault in ('status','statusnumber','pid','birth','zero','duplicate','order','outside-monitor'):
   bad=copy.deepcopy(rows)
   if fault=='status':bad[2]['global_status']=False
   if fault=='statusnumber':bad[2]['global_status']=1
   if fault=='pid':bad[2]['pid']=999
   if fault=='birth':bad[2]['birth']=11
   if fault=='zero':bad[0]['birth']=0
   if fault=='duplicate':bad.insert(1,copy.deepcopy(bad[0]))
   if fault=='order':bad[1],bad[3]=bad[3],bad[1]
   if fault=='outside-monitor':bad[1],bad[2]=bad[2],bad[1]
   with self.assertRaises(ValueError,msg=fault):B.memory_condition(bad)
  unknown=copy.deepcopy(rows);unknown[2].update(global_status=False,available_physical_bytes=None)
  self.assertIsNone(B.memory_condition(unknown)['condition_met'])
  failedEX2=copy.deepcopy(rows);failedEX2[2].update(process_status=False,private_working_set_bytes=None)
  self.assertIs(B.memory_condition(failedEX2)['condition_met'],True)
 def test_checked_physical_budget_selection(self):
  unit=2097152+264;g=1073741824
  self.assertEqual(B.select_ram_payload(12*g,unit,unit),unit+int(3.5*g))
  self.assertEqual(B.select_ram_payload(8*g,unit,unit),unit)
  self.assertEqual(B.select_ram_payload(9*g,unit,unit),unit)
  for available,ram,deferred in ((1,unit,0),(True,unit,0),(12*g,True,0),(12*g,2**64-1,0),(12*g,unit,-1)):
   with self.assertRaises(ValueError):B.select_ram_payload(available,ram,unit,deferred)
  self.assertEqual(B.explicit_ram_slots(unit*3+7,2097152),dict(weight=3,row=3,payload_bytes=unit*3,unused_bytes=7))
 def test_memory_condition_unknown_excursion_and_no_monitor(self):
  def point(label,value=8589934592):return dict(point=label,available_physical_bytes=value,identity_verified=True,global_status=True,pid=123,birth=10)
  rows=[point(x)for x in ('constructed','A-before','A-monitor','A-after','B-before','B-monitor','B-after')]
  self.assertIs(B.memory_condition(rows)['condition_met'],True)
  bad=copy.deepcopy(rows);bad[2]['available_physical_bytes']=8589934591
  self.assertIs(B.memory_condition(bad)['condition_met'],False)
  bad=copy.deepcopy(rows);bad[2]['available_physical_bytes']=None;bad[2]['global_status']=False
  self.assertIsNone(B.memory_condition(bad)['condition_met'])
  self.assertIsNone(B.memory_condition(rows[:-2]+rows[-1:])['condition_met'])
  for value in (True,1.0,-1):
   bad=copy.deepcopy(rows);bad[0]['available_physical_bytes']=value
   with self.assertRaises(ValueError):B.memory_condition(bad)

class FormalWrapperTests(unittest.TestCase):
 def test_win32_memory_scope_and_birth(self):
  import build_verify as V
  x=V.physical_memory(os.getpid());self.assertIs(x['global_status'],True);self.assertIs(x['process_status'],True);self.assertIs(x['identity_verified'],True)
  self.assertGreater(x['working_set_bytes'],0);self.assertGreater(x['private_working_set_bytes'],0);self.assertGreater(x['private_commit_bytes'],0)
  self.assertIs(V.physical_memory(os.getpid(),x['birth']+1)['identity_verified'],False)
  failed=V.physical_memory(0);self.assertIsNone(failed['working_set_bytes']);self.assertIsNone(failed['private_working_set_bytes']);self.assertIsNone(failed['birth'])
 def test_owner_minimum_inside_band_is_retained_without_GEN(self):
  import build_verify as V
  with tempfile.TemporaryDirectory()as d:
   session=mock.Mock();session.info.return_value=dict(ram_slots=1,row_ram_slots=1,ram_cache_payload_bytes=2097416,deferred_host_sampling=4000)
   sample=dict(available_physical_bytes=B.DRAM_LOW,identity_verified=True,birth=1,point='constructed')
   cfg=dict(command=['exe','--tile-bytes','2097152','--ram-cache-payload-bytes','auto'],cwd=d)
   with mock.patch.object(B,'ProcessSession',return_value=session)as launch,mock.patch.object(V,'runtime_snapshot',return_value={}),mock.patch.object(V,'sample_memory',return_value=sample):
    result,selection,_=V.select_owner(cfg,{},Path(d));self.assertIs(result,session);self.assertEqual(len(selection),1);self.assertIsNone(selection[0]['valid_model_payload_bytes']);session.request.assert_not_called();session.close.assert_not_called();self.assertEqual(launch.call_args.args[0][-1],'2097416')
 def test_single_candidate_band_outside_does_not_repeat_allocation(self):
  import build_verify as V
  made=[]
  def launch(command,*args):
   payload=int(command[-1]);slots=B.explicit_ram_slots(payload,2097152)
   session=mock.Mock();session.proc.returncode=0;session.info.return_value=dict(ram_slots=slots['weight'],row_ram_slots=slots['row'],ram_cache_payload_bytes=slots['payload_bytes'],deferred_host_sampling=4000);made.append(session);return session
  sample=dict(available_physical_bytes=12*1073741824,identity_verified=True,birth=1,point='constructed')
  with tempfile.TemporaryDirectory()as d:
   cfg=dict(command=['exe','--tile-bytes','2097152','--ram-cache-payload-bytes','auto'],cwd=d)
   with mock.patch.object(B,'ProcessSession',side_effect=launch),mock.patch.object(V,'runtime_snapshot',return_value={}),mock.patch.object(V,'sample_memory',return_value=sample):
    result,selection,_=V.select_owner(cfg,{},Path(d))
   self.assertEqual(len(made),2);self.assertIs(result,made[1]);made[0].close.assert_called_once();made[1].close.assert_not_called()
   for child in made:child.request.assert_not_called()
 def test_band_outside_or_unknown_does_not_block_GEN(self):
  import build_verify as V
  for available in (None,1,14*1073741824):
   session=mock.Mock();samples=[]
   def sample(_session,point,birth):return dict(point=point,pid=123,birth=birth,identity_verified=True,global_status=available is not None,available_physical_bytes=available)
   with tempfile.TemporaryDirectory()as d,mock.patch.object(V,'sample_memory',side_effect=sample):
    V.measured_request(session,'GEN',{},'x','A',10,samples,Path(d))
   session.request.assert_called_once()
 def test_formal_variant_keeps_old_measurement_and_pilot_paths(self):
  import build_verify as V
  self.assertEqual(V.measurement_root(dict(phase='pilot')),V.BUILD)
  self.assertEqual(V.measurement_root(dict(phase='measurement',measurement_variant='approx-8g-r1')),V.BUILD/'approx-8g-r1')
  for variant in ('../foreign','measurement','settled-r1'):
   with self.assertRaises(ValueError):V.measurement_root(dict(phase='measurement',measurement_variant=variant))
 def test_monitor_finally_records_after_and_reaps_monitor_on_request_error(self):
  import build_verify as V
  session=mock.Mock();session.request.side_effect=ValueError('original-request-error');rows=[]
  def sample(_session,point,birth):return dict(point=point,identity_verified=True,available_physical_bytes=B.DRAM_AIM,birth=birth)
  with tempfile.TemporaryDirectory()as d,mock.patch.object(V,'sample_memory',side_effect=sample):
   with self.assertRaisesRegex(ValueError,'original-request-error'):V.measured_request(session,'GEN',{},'x','A',1,rows,Path(d))
  self.assertEqual([r['point']for r in rows],['A-before','A-after'])
 def test_monitor_failure_after_success_is_retained_unknown(self):
  import build_verify as V
  import threading
  for failure in ('observe','save'):
   done=threading.Event();session=mock.Mock();session.proc.pid=123;session.request.side_effect=lambda *a:done.wait(2);rows=[];count=0
   def sample(_session,point,birth):
    nonlocal count
    if point=='A-monitor':
     count+=1
     if failure=='observe'and count==2:done.set();raise OSError('observation-failure')
    return dict(point=point,pid=123,birth=10,identity_verified=True,global_status=True,available_physical_bytes=B.DRAM_AIM)
   original_save=V.save
   def save(path,value):
    if failure=='save'and value[-1]['point']=='A-monitor'and count==2:done.set();raise OSError('monitor-save-failure')
    return original_save(path,value)
   with tempfile.TemporaryDirectory()as d,mock.patch.object(V,'sample_memory',side_effect=sample),mock.patch.object(V,'save',side_effect=save):
    V.measured_request(session,'GEN',{},'x','A',10,rows,Path(d),monitor_interval_seconds=.001)
   self.assertTrue(done.is_set());self.assertEqual(sum(r['point']=='A-monitor'and r.get('monitor_error')is not None for r in rows),1)
   full=[dict(point='constructed',pid=123,birth=10,identity_verified=True,global_status=True,available_physical_bytes=B.DRAM_AIM)]+rows
   full.extend(dict(point=p,pid=123,birth=10,identity_verified=True,global_status=True,available_physical_bytes=B.DRAM_AIM)for p in ('B-before','B-monitor','B-after'))
   self.assertIsNone(B.memory_condition(full)['condition_met'])
 def test_foreign_or_unknown_memory_identity_is_not_met(self):
  rows=[dict(point=p,available_physical_bytes=B.DRAM_AIM,identity_verified=True,global_status=True,pid=123,birth=10)for p in ('constructed','A-before','A-monitor','A-after','B-before','B-monitor','B-after')]
  rows[3]['identity_verified']=False;self.assertIsNone(B.memory_condition(rows)['condition_met'])
 def test_formal_archived_replay_and_semantic_rejections(self):
  import build_verify as V
  import shutil
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);archive=root/'source';maps=[]
   for origin in (Path(B.__file__),B._dto_path):
    target=archive/origin.relative_to(B.ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target);maps.append(dict(original=V.row(origin),snapshot=V.row(target)))
   config=dict(command=['exe','--tile-bytes','2097152','--ram-cache-payload-bytes','auto'],prompt_ids=[0],sampling={},maximum_new_tokens=2,context=4096,flags={},bundle_id='a'*64,runtime_epoch=1)
   wid=hashlib.sha256(json.dumps({k:config[k]for k in ('prompt_ids','sampling','maximum_new_tokens','context','flags')},sort_keys=True,separators=(',',':')).encode()).hexdigest()
   V.save(root/'input.json',config);V.save(root/'seal.json',dict(source_snapshots=maps,input_snapshot=V.row(root/'input.json'),input=config));seal=V.row(root/'seal.json')
   pairs=[];records=[]
   for index in range(3):
    folder=root/str(index);folder.mkdir();a,b=capture(request=f't35-measurement-{index}-A'),capture(request=f't35-measurement-{index}-B');b['request_index']=1;b['info_before']=info(10,40);b['info_after']=info(20,40)
    for raw in (a,b):
     raw.update(process_id=123+index,workload_identity=wid)
     for meta in (raw['info_before'],raw['info_after']):meta.update(context=4096,ram_cache_payload_bytes=2097416*4,cache_unused_ram_bytes=0,mandatory_measurement_device=1,deferred_constant_device=1,deferred_host_sampling=1)
    for name,value in (('A',a),('B',b)):V.save(folder/(name+'.json'),value)
    memory=[dict(point=q,identity_verified=True,available_physical_bytes=B.DRAM_AIM,global_status=True,pid=123+index,birth=10+index)for q in ('constructed','A-before','A-monitor','A-after','B-before','B-monitor','B-after')]
    V.save(folder/'memory.json',memory)
    proof=dict(pair_index=index,seal=seal,analysis=B.analyze_pair(a,b),memory_condition=B.memory_condition(memory),raw_captures=[V.row(folder/(c+'.json'))for c in ('A','B')],memory_capture=V.row(folder/'memory.json'))
    final=dict(declared_ram_payload_bytes=2097416*4,command=V.ram_command(config,2097416*4),actual_slots=B.explicit_ram_slots(2097416*4,2097152),info=a['info_before'],memory=memory[0])
    selected=dict(pair=index,seal=seal,workload_identity=wid,final_owner=final)
    for key,value in dict(selected_input=selected,selection=[final],closed=dict(pid=123+index,birth=10+index,closed=True,exit_code=0),stderr={}).items():
     V.save(folder/(key+'.json'),value);proof[key]=V.row(folder/(key+'.json'))
    self.assertEqual(V.validate_formal_pair(proof,config,seal),(123+index,10+index))
    V.save(folder/'verification.json',proof);pairs.append(proof);records.append(V.row(folder/'verification.json'))
   condition,interval=V.formal_intervals(B,pairs);aggregate=dict(schema='T35-formal-aggregate/v1',seal=seal,pairs=records,DRAM_observed_condition_met=condition,intervals=interval);V.save(root/'verification.json',aggregate)
   self.assertEqual(V.replay(root)['CPU_replay'],'passed')
   for fault in ('interval','duplicate','missing'):
    bad=copy.deepcopy(aggregate)
    if fault=='interval':bad['intervals']['TTFT_pipe_seconds']['value']=[9,10]
    if fault=='duplicate':bad['pairs'][1]=bad['pairs'][0]
    if fault=='missing':bad['pairs'].pop()
    with self.assertRaises(ValueError,msg=fault):V.replay_formal(root,bad)
   original=copy.deepcopy(pairs[0]);folder=root/'0'
   for fault in ('boolpair','floatpair','wrongpair','context','workload','selectedbudget','pid','birth','closed','command'):
    bad=copy.deepcopy(original);selected=V.read(folder/'selected_input.json');raw=V.read(folder/'A.json');closed=V.read(folder/'closed.json');memory=V.read(folder/'memory.json')
    old={name:(folder/name).read_bytes()for name in ('selected_input.json','A.json','closed.json','memory.json')}
    try:
     if fault=='boolpair':bad['pair_index']=False
     if fault=='floatpair':bad['pair_index']=0.0
     if fault=='wrongpair':bad['pair_index']=1
     if fault=='context':raw['context']['bundle_id']='b'*64
     if fault=='workload':raw['workload_identity']='0'*64
     if fault=='selectedbudget':selected['final_owner']['info']['device_slots']+=1
     if fault=='pid':raw['process_id']+=1
     if fault=='birth':memory[-1]['birth']+=1
     if fault=='closed':closed['birth']+=1
     if fault=='command':selected['final_owner']['command'][0]='foreign.exe'
     V.save(folder/'selected_input.json',selected);V.save(folder/'A.json',raw);V.save(folder/'closed.json',closed);V.save(folder/'memory.json',memory)
     with self.assertRaises(ValueError,msg=fault):V.validate_formal_pair(bad,config,seal)
    finally:
     for name,value in old.items():(folder/name).write_bytes(value)
 def test_RAM_override_is_test_command_copy(self):
  import build_verify as V
  cfg=dict(command=['exe','--ram-cache-payload-bytes','auto','--device-cache-payload-bytes','auto'])
  self.assertEqual(V.ram_command(cfg,100)[2],'100');self.assertEqual(cfg['command'][2],'auto')
  with self.assertRaises(ValueError):V.ram_command(cfg,True)

class ProviderLifecycleTests(unittest.TestCase):
 def test_owner_close_after_observation_failure(self):
  import build_verify as V
  events=[]
  class Owner:
   def close(self):events.append('close')
  def failed():events.append('observe');raise OSError('sample unavailable')
  result=V.lifecycle_close(Owner(),failed)
  self.assertEqual(events,['observe','close']);self.assertIsNone(result['sample']);self.assertIn('sample unavailable',result['observation_error'])
  class FailedOwner:
   def close(self):raise ValueError('real close failure')
  with self.assertRaisesRegex(ValueError,'real close failure'):V.lifecycle_close(FailedOwner(),failed)
 def capture(self):
  data=json.loads((B.ROOT/'build-deepseek-t35/host-io/attempt-1/stdout.json').read_text(encoding='utf-8'))
  a=next(x for x in data['arms']if x['arm']=='A')
  data['schema']='T35-host-lifecycle/v1';data['arms']=[copy.deepcopy(a)for _ in range(4)]
  for label,arm in zip('ACCA',data['arms']):
   arm.update(arm=label,lifecycles=1 if label=='C' else 32,construct_seconds=0.0001,close_seconds=0.0001)
  return data
 def test_equal_windows_lifecycle_only(self):
  value=self.capture();result=B.validate_provider_lifecycle(value,value['expected_sha256'])
  self.assertTrue(result['clean_comparison']);self.assertEqual(result['useful_bytes'],8388608)
  self.assertFalse(result['model_performance_qualified']);self.assertIsNone(result['physical_io'])
 def test_meaningful_mutations(self):
  original=self.capture()
  for key,bad in [('chunk',2097152),('lifecycles',32),('direct_reads',1),('logical_requested',65536),('outstanding',1),('closed',False),('sha256','x'*64),('construct_seconds',float('nan'))]:
   value=copy.deepcopy(original);value['arms'][1][key]=bad
   with self.assertRaises(ValueError,msg=key):B.validate_provider_lifecycle(value,value['expected_sha256'])
  value=copy.deepcopy(original);value['arms'][1]['buffered_reads']=1
  self.assertFalse(B.validate_provider_lifecycle(value,value['expected_sha256'])['clean_comparison'])

if __name__=='__main__':unittest.main()
