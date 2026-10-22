"""Focused CPU only; no native constructor or publication."""
import sys,unittest,importlib.util,ast,copy,io,json,os,queue,threading,struct,tempfile,types
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runner as C
import live as L
class ContactSelection(unittest.TestCase):
 def test_unbound_new_id_refuses_instead_of_skipping(self):
  original=C.ID
  try:
   C.ID='1'*64
   with self.assertRaisesRegex(ValueError,'selected contact'):C.contact_selected()
  finally:C.ID=original

class CheckedDescriptor(unittest.TestCase):
 def test_real_bind_and_finite_native_closure_positive_and_negative(self):
  names=('ID','PACKAGE','BUNDLE','HOOK','PROFILE','CANDIDATE_INPUT','CANDIDATE_PROOF','CONTACT_ID','CONTACT_SOURCE','CONTACT_NATIVE','CONTACT_HOOK','CONTACT_INPUT','_SELECTED_CONTACT','_CONTACT_BOUND')
  saved={k:getattr(C,k)for k in names}
  try:
   with tempfile.TemporaryDirectory()as tmp:
    root=Path(tmp);package=root/('a'*64);package.mkdir()
    src=root/'source';src.mkdir();obj=root/'codeobjects';obj.mkdir();identity=root/'identity';identity.mkdir()
    def put(name,value):
     path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf8');return C.row(path)
    source=src/'production-body-CPU.cpp';source.write_text('explicit CPU fixture only',encoding='utf8')
    declared=root/'declared.tsv';declared.write_text(source.name+'|'+C.row(source)['sha256']+'\n',encoding='utf8')
    exe=identity/'Strata-CPU-only.exe';exe.write_bytes(b'CPU synthetic metadata; never executed')
    hook=src/'hook.py';hook.write_text('# CPU hook placeholder, not installed',encoding='utf8')
    dlls=[]
    for n in range(6):
     path=identity/('CPU-'+str(n)+'.dll');path.write_bytes(b'CPU DLL placeholder');dlls.append(C.row(path))
    objects=[]
    for arch in ('gfx1100','gfx1201'):
     path=obj/('CPU--'+arch);path.write_bytes(b'CPU codeobject placeholder');objects.append(C.row(path))
    common=put('identity/result.json',dict(wait_completed=True,exit=0,handle_closed=True,disposed=True,secondary_errors=[]))
    close=put('identity/close.json',dict(original_safehandle_closed=True,original_process_object_disposed=True))
    cpu=dict(flag='--identity',exit=0,stderr='',stdout=json.dumps(dict(source_set_sha256='b'*64,normal_audit_d2h=False)),exe=C.row(exe))
    for k in ('command','owner','stdout_file','stderr_file','outer'):cpu[k]=put('identity/'+k+'.json',dict(explicit_CPU_fixture=True))
    cpu.update(result=common,handle_closed=close)
    native=dict(schema='strata-t46-perf-native-manifest/v1',compiled_source_id='b'*64,math_abi='c'*64,normal=True,both_arch=True,source_root=str(src),
     source_closure=put('source-closure.json',dict(records=[dict(snapshot=C.row(source))])),
     native_closure=put('native-closure.json',dict(consumed_dependencies=[C.row(source)],declared_sources=C.row(declared),codeobjects=objects)),
     build=put('build.json',dict(explicit_CPU_fixture=True)),accepted_report=put('report.json',dict(explicit_CPU_fixture=True)),
     consumed=[C.row(source)],declared_tsv=C.row(declared),declared=[C.row(source)],codeobjects=objects,bundle_dlls=dlls,CPU=[cpu])
    nr=put('native.json',native)
    manifest=put('manifest.json',dict(id=package.name,native_manifest_sha256=nr['sha256']))
    profile=put('profile.json',dict(context=4096))
    inputs=dict(candidate_package_id=package.name,native_manifest=dict(source=nr['path'],bytes=nr['bytes'],sha256=nr['sha256']),
     native_compiled_source_id=native['compiled_source_id'],native_bundle_dlls=dlls,
     selected_files=[dict(relative_destination='native/Strata-deepseek.exe',source=str(exe),bytes=exe.stat().st_size,sha256=C.row(exe)['sha256']),
                     dict(relative_destination='Strata-extensions/models/deepseek41/server_hooks.py',source=str(hook),bytes=hook.stat().st_size,sha256=C.row(hook)['sha256'])])
    ir=put('input.json',inputs)
    descriptor=dict(input=ir,package_manifest=manifest,native_manifest=nr,source_root=str(src),codeobject_root=str(obj),identity_root=str(identity),
     consumed_roots=[str(src)],counts=dict(consumed=1,declared=1,source_snapshots=1,codeobjects_per_arch=1),math_abi='c'*64,runner=C.row(C.__file__))
    dr=put('selected-contact.json',descriptor)
    proof=dict(input=ir,package_manifest=manifest,package_root=str(package),profiles=[dict(candidate=profile)],selected_contact=dr)
    pr=put('proof.json',proof)
    C.bind_candidate(ir['path'],pr['path']);self.assertTrue(C.contact_selected())
    records=C.contact_native_records(inputs,native);self.assertTrue(records)
    for fault in ('missing','descriptor-hash','input','ABI','runner'):
     wrong=copy.deepcopy(proof)
     if fault=='missing':wrong.pop('selected_contact')
     elif fault=='descriptor-hash':wrong['selected_contact']['sha256']='0'*64
     else:
      d=copy.deepcopy(descriptor)
      if fault=='input':d['input']=manifest
      elif fault=='ABI':d['math_abi']='d'*64
      else:d['runner']=C.row(__file__)
      wrong['selected_contact']=put('bad-'+fault+'.json',d)
     bad=put('badproof-'+fault+'.json',wrong)
     C.bind_candidate(ir['path'],pr['path']);self.assertTrue(C.contact_selected())
     with self.subTest(fault=fault),self.assertRaises(ValueError):C.bind_candidate(ir['path'],bad['path'])
     with self.subTest(reentry=fault),self.assertRaisesRegex(ValueError,'selected contact'):C.contact_selected()
     with self.subTest(qualification=fault),self.assertRaisesRegex(ValueError,'selected contact'):C.qualify(root,{},None,None,None,None,persist=False)
    C.bind_candidate(ir['path'],pr['path'])
    wrong=copy.deepcopy(native);wrong['consumed'].append(wrong['consumed'][0])
    with self.assertRaises(ValueError):C.contact_native_records(inputs,wrong)
  finally:
   for k,v in saved.items():setattr(C,k,v)

class LegacyRebind(unittest.TestCase):
 def test_legacy_failed_rebind_is_not_implicitly_selected(self):
  source=C.CONTACT_PREP/'inputs-perf-r1.json';proof=C.B/'package-candidate-de662662c8da/verification.json'
  C.bind_candidate(source,proof);self.assertTrue(C.contact_selected())
  with tempfile.TemporaryDirectory()as tmp:
   path=Path(tmp)/'bad-proof.json';value=C.load(proof);value['CPU_rebind_fault']=True;path.write_text(json.dumps(value),encoding='utf8')
   with self.assertRaises(ValueError):C.bind_candidate(source,path)
   with self.assertRaisesRegex(ValueError,'selected contact'):C.contact_selected()
   with self.assertRaisesRegex(ValueError,'selected contact'):C.qualify(Path(tmp),{},None,None,None,None,persist=False)
  C.bind_candidate(source,proof);self.assertTrue(C.contact_selected())

class ProductionBodies(unittest.TestCase):
    def setUp(self):
        names=('ID','PACKAGE','BUNDLE','HOOK','PROFILE','CANDIDATE_INPUT','CANDIDATE_PROOF','CONTACT_ID','CONTACT_SOURCE','CONTACT_NATIVE','CONTACT_HOOK','_SELECTED_CONTACT','_CONTACT_BOUND')
        saved={k:getattr(C,k)for k in names}
        self.addCleanup(lambda:[setattr(C,k,v)for k,v in saved.items()])
        C.bind_candidate(C.CONTACT_PREP/'inputs-perf-r1.json',C.B/'package-candidate-de662662c8da/verification.json')


    def publisher_semantics(self,numeric,a,sealed):
        module_path=Path(__file__).resolve().parents[2]/'providers/runtime_stage.py'
        spec=importlib.util.spec_from_file_location('contact_publisher_cpu',module_path);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
        node=next(x for x in ast.parse(module_path.read_text(encoding='utf8')).body if isinstance(x,ast.FunctionDef)and x.name=='execution_publication_inputs')
        helpers=[x for x in node.body if isinstance(x,ast.FunctionDef)and x.name in ('require','exact')]
        def assign(node,name):return isinstance(node,ast.Assign)and any(isinstance(x,ast.Name)and x.id==name for x in node.targets)
        start=next(i for i,x in enumerate(node.body)if assign(x,'numeric'))
        end=next(i for i,x in enumerate(node.body)if assign(x,'protection'))
        segment=ast.FunctionDef(name='contact_segment',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=n)for n in ('value','accepted_numeric','candidate','manifest')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=helpers+node.body[start:end],decorator_list=[])
        tree=ast.fix_missing_locations(ast.Module(body=[segment],type_ignores=[]))
        namespace=dict(M.__dict__)
        def exact_module(name,path):
            self.assertEqual(Path(path).resolve(),Path(C.__file__).resolve())
            return C # real C.replay_final_single_numeric, not a mocked success.
        namespace['module']=exact_module
        exec(compile(tree,str(module_path),'exec'),namespace)
        original_numeric=C.load(numeric['path'])
        candidate=C.load(original_numeric['candidate']['path'])
        descriptor=a/'selected-publisher-contact.json'
        descriptor.write_text(json.dumps(dict(input=original_numeric['input'],package_manifest=original_numeric['package_manifest'],runner=C.row(C.__file__))),encoding='utf8')
        candidate['selected_contact']=C.row(descriptor)
        accepted=dict(reviewed_source_map=original_numeric['source_map'])
        manifest=dict(id=C.ID,native_manifest_sha256=C.BUNDLE)
        value=dict(numeric=numeric,candidate=original_numeric['candidate'])
        targets=[a/('never-published-'+str(i))for i in range(8)]
        for target in targets:target.write_bytes(b'protected CPU destination')
        before=[C.row(x)for x in targets]
        namespace['contact_segment'](value,accepted,candidate,manifest)
        self.assertEqual(before,[C.row(x)for x in targets])
        for field in ('native_stderr','native_stderr_capture','wait_validation','fresh_INFO'):
            for fault in ('missing','foreign','hash'):
                changed=copy.deepcopy(original_numeric)
                if fault=='missing':changed.pop(field)
                elif fault=='foreign':changed[field]=C.row(a/'owner.json')
                else:changed[field]['sha256']='0'*64
                bad=a/('field-'+field+'-'+fault+'.json');bad.write_text(json.dumps(changed),encoding='utf8')
                with self.subTest(required_field=field,fault=fault),self.assertRaises(ValueError):
                    namespace['contact_segment'](dict(value,numeric=C.row(bad)),accepted,candidate,manifest)
                self.assertEqual(before,[C.row(x)for x in targets])
        names=('fresh-INFO-receipt.json','native-stderr.raw','native-stderr.json')
        original={n:(a/n).read_bytes()for n in names}
        for fault in ('fresh-clock','aggregate-open'):
            changed=copy.deepcopy(original_numeric)
            if fault=='fresh-clock':
                fresh=C.load(a/'fresh-INFO-receipt.json');fresh['send_ns']=0
                (a/'fresh-INFO-receipt.json').write_text(json.dumps(fresh),encoding='utf8')
                changed['fresh_INFO']=C.row(a/'fresh-INFO-receipt.json')
            else:
                raw=(a/'native-stderr.raw').read_text(encoding='utf8').splitlines()
                aggregate=json.loads(raw[0].split(' ',1)[1]);aggregate['metrics']['Prefill']['open']=1
                raw[0]='T46_WAIT_AGGREGATE '+json.dumps(aggregate)
                (a/'native-stderr.raw').write_text('\n'.join(raw)+'\n',encoding='utf8')
                receipt=C.load(a/'native-stderr.json');receipt['raw']=C.row(a/'native-stderr.raw')
                (a/'native-stderr.json').write_text(json.dumps(receipt),encoding='utf8')
                changed['native_stderr']=C.row(a/'native-stderr.raw');changed['native_stderr_capture']=C.row(a/'native-stderr.json')
            bad=a/('semantic-'+fault+'.json');bad.write_text(json.dumps(changed),encoding='utf8')
            # All record hashes are current; only the real semantic replay rejects.
            C.checked([x for x in changed.values()if isinstance(x,dict)and set(x)=={'path','bytes','sha256'}])
            with self.subTest(rehashed_semantic=fault),self.assertRaisesRegex(ValueError,'fresh INFO|aggregate open'):
                namespace['contact_segment'](dict(value,numeric=C.row(bad)),accepted,candidate,manifest)
            self.assertEqual(before,[C.row(x)for x in targets])
            for name,data in original.items():(a/name).write_bytes(data)

    def contact_aggregates(self):
        base = [json.loads(r['line']) for r in [json.loads(x) for x in (C.B / 'observer-newpackage-r2-probe/observer.jsonl').read_text(encoding='utf8').splitlines()] if r['event'] == 'receive' and isinstance(r.get('line'), str) and r['line'].startswith('{')]
        requests = []
        rows = []
        for i, (finish, origin, count) in enumerate([('cancel', 'user_cancel', 1), ('length', 'limit', 2)]):
            context = {k: base[0][k] for k in ('request_id', 'runtime_epoch', 'bundle_id')}
            context.update(request_id='contact-' + str(i), bundle_id=C.CONTACT_NATIVE)
            raw = dict(context=context, finish=finish, stop_origin=origin, generated_count=count)
            requests.append(dict(cookie=[context['request_id'], 1], raw=raw, cancel=i == 0))
            metric = dict(coverage='covered', calls=0, iterations=0, completed=0, success=0, not_ready=0, error=0, work=0, open=0, wall_ns=0, partial_observed_ns=None, observer_invalid=False)
            row = dict(schema='T46-single-wait-phase-aggregate/v1', mode='single', request_id=context['request_id'], bundle_id=context['bundle_id'], epoch=1, drain_confirmed=True, collector_complete=True, source_set_sha256=C.CONTACT_SOURCE, host_wall_semantics='inclusive_overlapping_API_envelopes', clock='steady_clock_nanoseconds', clock_observed_resolution_ns=None, clock_period_num=1, clock_period_den=1000000000, OS_wait_execution=None, physical_SSD_IO=None, expert=dict(coverage='not_selected', calls=None, wall_ns=None), metrics={k: dict(metric) for k in C.WAIT_METRICS}, terminal_status_code=2 if i == 0 else 1, generated_count=count, stop_origin=origin)
            row['metrics']['ProjectionCallbacks']['calls'] = 3
            rows.append(row)
        binding = dict(runtime_epoch=1, hook_sha256='d73dffd348ee35f771eefa7c665e92958374e8d7df5cf6809a29d41ac3df121e', owner=dict(engine=dict(pid=9, birth=1), server=dict(pid=8, birth=1)))
        return (rows, requests, binding)

    def test_contact_aggregate_strict_domain_and_types(self):
        rows, requests, binding = self.contact_aggregates()
        encode = lambda r: ('\n'.join(('T46_WAIT_AGGREGATE ' + json.dumps(x) for x in r)) + '\n').encode()
        good = C.parse_wait_aggregates(encode(rows), requests, binding)
        self.assertEqual(good['aggregates'][0]['metrics']['ProjectionCallbacks']['completed'], 0)
        self.assertIsNone(good['aggregates'][0]['physical_SSD_IO'])
        for fault in ('duplicate', 'missing', 'foreign', 'source', 'epoch', 'terminal', 'count', 'bool', 'negative', 'unknown', 'metric-missing', 'invalid', 'open', 'drain', 'nan', 'duplicate-key'):
            bad = copy.deepcopy(rows)
            if fault == 'duplicate':
                bad.append(bad[0])
            elif fault == 'missing':
                bad.pop()
            elif fault == 'foreign':
                bad[0]['request_id'] = 'foreign'
            elif fault == 'source':
                bad[0]['source_set_sha256'] = '0' * 64
            elif fault == 'epoch':
                bad[0]['epoch'] = 2
            elif fault == 'terminal':
                bad[0]['terminal_status_code'] = 1
            elif fault == 'count':
                bad[0]['generated_count'] = 0
            elif fault == 'unknown':
                bad[0]['extra'] = 0
            elif fault == 'metric-missing':
                bad[0]['metrics'].pop('Prefill')
            elif fault == 'drain':
                bad[0]['drain_confirmed'] = False
            elif fault == 'invalid':
                bad[0]['metrics']['Prefill']['observer_invalid'] = True
            elif fault == 'open':
                bad[0]['metrics']['Prefill']['open'] = 1
            else:
                bad[0]['metrics']['Prefill']['calls'] = {'bool': True, 'negative': -1, 'nan': float('nan'), 'duplicate-key': 0}[fault]
            data = encode(bad)
            if fault == 'duplicate-key':
                data = data.replace(b'"calls": 0', b'"calls": 0, "calls": 0', 1)
            with self.subTest(fault=fault), self.assertRaises((ValueError, TypeError)):
                C.parse_wait_aggregates(data, requests, binding)
        wrong = copy.deepcopy(requests)
        wrong[0]['raw']['context']['bundle_id'] = '2c12eedaa97e137ed7125935ce74f1cf9eb8a8e9807e46bd44b50cf8e817afdc'
        with self.assertRaises(ValueError):
            C.parse_wait_aggregates(encode(rows), wrong, binding)

    def test_contact_late_stderr_after_original_close(self):
        with tempfile.TemporaryDirectory(dir=C.HERE) as tmp:
            t = L.ActualTransport.__new__(L.ActualTransport)
            t.attempt = Path(tmp)
            log = (Path(tmp) / 'native.log').open('w', encoding='utf8')
            calls = []
            rows, requests, binding = self.contact_aggregates()
            payload = '\n'.join(('T46_WAIT_AGGREGATE ' + json.dumps(x) for x in rows)) + '\n'
            p = types.SimpleNamespace(pid=9, poll=lambda: 0 if 'wait' in calls else None)

            def close():
                calls.append('late-stderr')
                log.write(payload)
                calls.append('wait')
                log.close()
                e.proc = None
            e = types.SimpleNamespace(proc=p, log=log, log_path=str(Path(tmp) / 'native.log'), close=close)
            t.binding = binding
            t.cfg = dict(runtime_epoch=1)
            t.retain_stderr(e, p)
            t.engine = e
            t.process = p
            t.http = None
            t.spec = None
            t.state = None
            t.memory = []
            t.memory_now = lambda *a: None
            t.check_cohort = lambda: None
            t.cli = lambda *a: None
            t.start = lambda: None
            t.capture = lambda: calls.append('stdout-DONE')

            def qualify(actual):
                self.assertEqual(p.poll(), 0)
                self.assertTrue(log.closed)
                calls.append('parse')
                return C.contact_wait_evidence(t.attempt, dict(requests=requests), binding)
            with patch.multiple(C, ID=C.CONTACT_ID, BUNDLE=C.CONTACT_NATIVE):
                result = L.run_stage(t, qualify)
            receipt = C.load(t.attempt / 'native-stderr.json')
            self.assertEqual(calls, ['stdout-DONE', 'late-stderr', 'wait', 'parse'])
            self.assertTrue(receipt['complete'])
            self.assertIsNone(receipt['explicit_native_handle_close'])
            self.assertEqual(result['aggregate_count'], 2)
            self.assertEqual(Path(receipt['raw']['path']).read_bytes(), payload.replace('\n', os.linesep).encode())

    def test_read_only_final_single_replay_synthetic_and_missing_reject(self):
        """Temporary synthetic records only; never retained as actual evidence."""
        import hashlib
        with tempfile.TemporaryDirectory(dir=C.HERE) as tmp:
            root = Path(tmp)
            a = root / 'attempt'
            a.mkdir()
            sealed = root / 'sealed'
            sealed.mkdir()
            cfg = C.load(C.PROFILE)
            cfg['runtime_epoch'] = 1
            unit = C.minimum('single')
            cfg['cache_budget']['ram_cache_payload_bytes'] = unit
            observer = C.module('t46_cpu_replay_capture', C.B / 'observer-capture.py')
            spec = observer.spec(a, cfg)
            base = [json.loads(x) for x in (C.B / 'observer-newpackage-r2-probe/observer.jsonl').read_text(encoding='utf8').splitlines()]
            complete = [json.loads(r['line']) for r in base if r['event'] == 'receive' and isinstance(r['line'], str) and r['line'].startswith('{')]
            complete[1]['logprobs'][1]['top_logprobs'] = [dict(token_id=55753, logprob=-1.25), dict(token_id=1, logprob=-2), dict(token_id=2, logprob=-3)]
            qref = C.module('t46_cpu_metadata_ref', C.R / 'Strata-extensions/tests/serve_provider/q_reference.py')
            complete[-1]['metadata_sha256'] = qref.metadata([(i, (lp['logprob'], [(r['token_id'], r['logprob']) for r in lp['top_logprobs']])) for i, lp in zip(C.IDS, complete[1]['logprobs'])], 'limit')
            cookie = ['7-1', 1]
            controlcookie = ['7-0', 1]
            for frame in complete:
                frame['request_id'] = cookie[0]
                frame['runtime_epoch'] = 1
            complete[0]['bundle_id'] = C.BUNDLE
            begin = copy.deepcopy(complete[0])
            begin['request_id'] = controlcookie[0]
            finish = copy.deepcopy(complete[-1])
            finish.update(request_id=controlcookie[0], sequence=0, generated_count=0, finish='cancel', ids_sha256=hashlib.sha256(b'').hexdigest(), stop_origin='user_cancel', metadata_sha256=qref.metadata([], 'user_cancel'))
            owner = dict(server=dict(pid=404, birth=1.0), engine=dict(pid=405, birth=2.0))
            binding = dict(owner=owner, hook_sha256=C.HOOK, runtime_epoch=1)
            info = dict(family='deepseek41', context=4096, core_position=5, configured_mode='single', effective_mode='single', primary_pci=cfg['primary_pci'], requested_secondary_pci=None, actual_secondary_pci=None, device_slots=1, ram_slots=1, row_device_slots=1, row_ram_slots=1, device_cache_payload_bytes=unit, ram_cache_payload_bytes=unit, declared_device_cache_payload_bytes=None, declared_ram_cache_payload_bytes=unit, auto_cache_fraction=0.5, auto_row_fraction=1 / 64, actual_device_owned=19, actual_primary_device_owned=19, actual_all_role_device_owned=19, resolved_ram_cache_target_bytes=unit, cache_unused_ram_bytes=0, cache_secondary_device_owned=0, cache_secondary_slots=0, cache_slot_capacity=0, cache_secondary_target_bytes=0, cache_secondary_unused_bytes=0, loaded_runtime_modules={n: str(C.PACKAGE / 'native' / n) for n in ('amdhip64_7.dll', 'amd_comgr.dll', 'rocm_kpack.dll')})
            rows = []

            def emit(event, **fields):
                rows.append(dict(schema='strata-t46-observer/v1', event=event, sequence=len(rows), run_id=spec['run_id'], monotonic_ns=len(rows), **fields))
            emit('header', **binding, package_id=C.ID, bundle_id=C.BUNDLE, mode='single')
            gen = next((r['line'] for r in base if r['event'] == 'send' and r['line'].startswith('GEN ')))
            for iscontrol, c, frames in [(True, controlcookie, [begin, finish]), (False, cookie, complete)]:
                emit('request', cookie=c, owner=owner)
                emit('send', cookie=c, line=gen.replace('request_id=7-1', 'request_id=' + c[0]))
                emit('receive', cookie=c, line=json.dumps(frames[0]))
                if iscontrol:
                    emit('cancel_fixture', cookie=c)
                    emit('send', cookie=c, line='STOP request_id=7-0 epoch=1 reason=user_cancel')
                for frame in frames[1:]:
                    emit('receive', cookie=c, line=json.dumps(frame))
                emit('receive', cookie=c, line='DONE ' + str(0 if iscontrol else 2))
            emit('summary', owner=owner, observer_error=None, close_error=None, cookies=[controlcookie, cookie])
            (a / 'observer.jsonl').write_text(''.join((json.dumps(r) + '\n' for r in rows)), encoding='utf8')
            sys.path[:0] = [str(C.PACKAGE / 'base'), str(C.PACKAGE / 'base/tools')]
            server = C.module('serve.server', C.PACKAGE / 'native/server/serve/server.py')
            hook = C.module('t46_cpu_numeric_hook', C.PACKAGE / 'Strata-extensions/models/deepseek41/server_hooks.py')
            hook.install(server, cfg)
            tok = hook.TokenizerFacade(C.PACKAGE / 'resources/tokenizer.json')
            shell = types.SimpleNamespace(max_context=4096, info=info, batch=0, alive=lambda: True)
            ids, thinking, maximum = server.Service(shell, tok, None, sampling_defaults={}).prepare(C.request()['messages'], None, {}, req=C.request())
            context = {k: complete[0][k] for k in hook.codec._dto.CONTEXT}
            codec = hook.codec.CodecSession(context, ids.prepared, tok.recipe)
            for frame in complete:
                codec.feed(json.dumps(frame))
            replay = codec.end_of_stream()
            choice = replay['response']['choices'][0]
            observed_meta = dict(id='chatcmpl-CPU-synthetic', object='chat.completion.chunk', created=1700000000)
            chunks = [dict(**observed_meta, model=C.MODEL, choices=[dict(index=0, delta=dict(content=choice['message']['content']), logprobs=choice['logprobs'], finish_reason=None)]), dict(**observed_meta, model=C.MODEL, choices=[dict(index=0, delta={}, finish_reason='length')], usage=replay['response']['usage']), '[DONE]']
            model9 = C.protected_sources(cfg)
            helper = C.module('t46_cpu_numeric_nativeargs', C.R / 'Strata-extensions/control/deepseek_launch.py')
            data = {'config': cfg, 'request': C.request(), 'spec': spec, 'complete-sse': chunks, 'final-info': info, 'cleanup': dict(ok=True, errors=[]), 'memory': [], 'clock': dict(TPOT_seconds=None), 'owner': dict(binding=binding, cohort=[]), 'argv-and-INFO': dict(epoch=1, native_argv=helper.native_command(cfg), config=None, startup=info, final=info), 'model9-before': model9, 'model9-after': model9, 'protected-before': [], 'protected-after': []}
            for name, value in data.items():
                C.save(a / (name + '.json'), value)
            C.save(a / 'control-cancellation.json', dict(cookie=controlcookie, binding=binding, raw=dict(finish='cancel')))
            C.save(a / 'complete-http.json', dict(HTTP_DONE=True))
            C.save(a / 'complete-clock.json', dict(end_ns=100))
            boundary = C.fresh_INFO_boundary(a, spec, binding)
            receipt = dict(ok=True, error=None, boundary=boundary, config=C.row(a / 'config.json'), send='INFO', send_ns=101, responses=[dict(line='INFO ' + json.dumps(info), monotonic_ns=102)], parsed=info, owner_before=owner['engine'], owner_after=owner['engine'], generation=1)
            C.save(a / 'fresh-INFO-receipt.json', receipt)
            if C.contact_selected():
                waitrows, _, _ = self.contact_aggregates()
                observed = observer.validate_capture(a / 'observer.jsonl', spec, binding)
                for aggregate, request_value in zip(waitrows, observed['requests'], strict=True):
                    raw = request_value['raw']
                    aggregate.update(request_id=request_value['cookie'][0], epoch=raw['context']['runtime_epoch'], bundle_id=raw['context']['bundle_id'], generated_count=raw['generated_count'], stop_origin=raw['stop_origin'], terminal_status_code={'cancel': 2, 'length': 1}[raw['finish']])
                native_log = a / 'native.log'
                native_log.write_bytes(('\n'.join(('T46_WAIT_AGGREGATE ' + json.dumps(x) for x in waitrows)) + '\n').encode())
                log = native_log.open('a', encoding='utf8')
                p = types.SimpleNamespace(pid=binding['owner']['engine']['pid'], poll=lambda: 0)
                e = types.SimpleNamespace(proc=p, log=log, log_path=str(native_log))
                t = L.ActualTransport.__new__(L.ActualTransport)
                t.attempt = a
                t.binding = binding
                t.cfg = cfg
                t.retain_stderr(e, p)
                log.close()
                t.snapshot_stderr()
            capture_path = a / 'observer.jsonl'
            original_capture = capture_path.read_text(encoding='utf8')
            original_rows = [json.loads(x) for x in original_capture.splitlines()]
            original_GEN = next((r['line'] for r in original_rows if r['event'] == 'send' and r.get('cookie') == cookie and r['line'].startswith('GEN ')))
            for name, line, accepted in [('legal-float-spelling', original_GEN.replace('temperature=0.0', 'temperature=0').replace('top_p=1.0', 'top_p=1'), True), ('completion-seed', original_GEN.replace('seed=0', 'seed=01'), False), ('completion-temperature', original_GEN.replace('temperature=0.0', 'temperature=0.5'), False), ('completion-ID-suffix', original_GEN + '9', False), ('completion-duplicate', original_GEN.replace('seed=0', 'seed=0 seed=0'), False), ('completion-extra', original_GEN.replace('seed=0', 'seed=0 unexpected=0'), False)]:
                changed = copy.deepcopy(original_rows)
                next((r for r in changed if r['event'] == 'send' and r.get('cookie') == cookie and r['line'].startswith('GEN ')))['line'] = line
                capture_path.write_text(''.join((json.dumps(r) + '\n' for r in changed)), encoding='utf8')
                with self.subTest(final_GEN=name):
                    if accepted:
                        C.qualify(a, cfg, binding, hook.codec, ids, tok, persist=False)
                    else:
                        with self.assertRaisesRegex(ValueError, 'control GEN'):
                            C.qualify(a, cfg, binding, hook.codec, ids, tok, persist=False)
            capture_path.write_text(original_capture, encoding='utf8')
            originals = {n: (a / n).read_text(encoding='utf8') for n in ('fresh-INFO-receipt.json', 'final-info.json', 'argv-and-INFO.json')}
            for mutation in ('failed', 'cookie', 'owner', 'clock', 'response', 'position0'):
                bad = json.loads(originals['fresh-INFO-receipt.json'])
                if mutation == 'failed':
                    bad['ok'] = False
                elif mutation == 'cookie':
                    bad['boundary']['cookie'][0] = 'foreign'
                elif mutation == 'owner':
                    bad['owner_after']['birth'] += 1
                elif mutation == 'clock':
                    bad['send_ns'] = 0
                elif mutation == 'response':
                    bad['responses'][0]['line'] = 'INFO {}'
                else:
                    bad['parsed']['core_position'] = 0
                    bad['responses'][0]['line'] = 'INFO ' + json.dumps(bad['parsed'])
                    (a / 'final-info.json').write_text(json.dumps(bad['parsed']), encoding='utf8')
                    argv = json.loads(originals['argv-and-INFO.json'])
                    argv['final'] = bad['parsed']
                    (a / 'argv-and-INFO.json').write_text(json.dumps(argv), encoding='utf8')
                (a / 'fresh-INFO-receipt.json').write_text(json.dumps(bad), encoding='utf8')
                with self.subTest(fresh_INFO=mutation), self.assertRaisesRegex(ValueError, 'Core position 5' if mutation == 'position0' else 'fresh INFO'):
                    C.qualify(a, cfg, binding, hook.codec, ids, tok, persist=False)
                for name, text in originals.items():
                    (a / name).write_text(text, encoding='utf8')
            C.qualify(a, cfg, binding, hook.codec, ids, tok)
            smap = dict(records=[C.row(C.__file__)], original_Model9=model9, package_id=C.ID, bundle_id=C.BUNDLE)
            C.save(sealed / 'source-map.json', smap)
            C.save(sealed / 'seal.json', dict(candidate_input=C.row(C.CANDIDATE_INPUT), candidate_proof=C.row(C.CANDIDATE_PROOF),package_id=C.ID,bundle_id=C.BUNDLE,records=smap['records']))
            numeric = C.final_single_numeric(a, sealed / 'seal.json')
            before = list(a.iterdir())
            with patch('time.time', return_value=4102444800):
                result = C.replay_final_single_numeric(numeric['path'])
            self.assertTrue(result['replayed'])
            self.assertEqual(result['write_count'], 0)
            self.assertEqual(before, list(a.iterdir()))
            self.assertEqual(C.load(a / 'complete-sse.json')[0]['created'], 1700000000)
            self.assertEqual(C.load(a / 'service-result.json')['response']['created'], 0)
            # Execute the unmodified actual publisher contact-preflight AST
            # slice, after its separately tested assembly prefix and before mutation.
            self.publisher_semantics(numeric,a,sealed)
            if C.contact_selected():
                for mutation in ('missing', 'wrongpath', 'SHA'):
                    wrong = C.load(numeric['path'])
                    if mutation == 'missing':
                        wrong.pop('fresh_INFO')
                    elif mutation == 'wrongpath':
                        wrong['fresh_INFO'] = C.row(a / 'final-info.json')
                    else:
                        wrong['fresh_INFO']['sha256'] = '0' * 64
                    badpath = a / ('fresh-ref-' + mutation + '.json')
                    C.save(badpath, wrong)
                    with self.subTest(numeric_fresh_ref=mutation), self.assertRaises(ValueError):
                        C.replay_final_single_numeric(badpath)
                wrong = C.load(numeric['path'])
                old_input = C.B / 'package-input-r5/inputs.json'
                old_proof = C.B / 'package-candidate-86cce0ea5929/verification.json'
                old = C.load(old_proof)
                wrong.update(input=C.row(old_input), candidate=C.row(old_proof), package_manifest=old['package_manifest'])
                C.save(a / 'transplanted-numeric.json', wrong)
                with self.assertRaisesRegex(ValueError, 'source map candidate/native|selected contact record required|numeric selected manifest/Q exact'):
                    C.replay_final_single_numeric(a / 'transplanted-numeric.json')
                C.bind_candidate(C.CONTACT_PREP / 'inputs-perf-r1.json', C.B / 'package-candidate-de662662c8da/verification.json')
            verification = C.row(a / 'verification.json')
            verified = C.load(verification['path'])
            previous = dict(verified, verification=verification, numeric_record=numeric, config_total_RAM=unit)
            reviewfile = root / 'existing-review.txt'
            reviewfile.write_text('CPU fixture existing review', encoding='utf8')
            accepted = dict(numeric=numeric, reviewed_source_map=C.row(sealed / 'source-map.json'), existing_review_record=C.row(reviewfile), scope='T46-final-single-publication-prerequisite')
            with patch.object(C, 'publication_join', return_value=True):
                stage = C.stage_receipts('cache-only', [previous], accepted, dict(CPU_fixture=True))
                self.assertEqual(stage['single_baseline'], C.load(a / 'raw-complete.json')['raw'])
                bad = copy.deepcopy(previous)
                bad['raw']['logprobs'][1][0] = -1.75
                with self.assertRaisesRegex(ValueError, 'receipt differs from saved verification'):
                    C.stage_receipts('cache-only', [bad], accepted, {})
                bad = copy.deepcopy(previous)
                bad['config_total_RAM'] += 1
                with self.assertRaisesRegex(ValueError, 'explicit RAM'):
                    C.stage_receipts('cache-only', [bad], accepted, {})
            (a / 'raw-complete.json').unlink()
            with self.assertRaises(FileNotFoundError):
                C.replay_final_single_numeric(numeric['path'])

    def test_startup_selected_server_fake_Popen_exact_env_and_original_error(self):
        """Selected server constructor reaches fake popen with the same mapping."""
        for record_failure in (False, True):
            with self.subTest(record_failure=record_failure), tempfile.TemporaryDirectory(dir=C.HERE) as tmp:
                calls = []
                mapping = []
                server_module = []

                class Handle:
                    closed = False

                    def Close(self):
                        calls.append('handle')
                        self.closed = True

                class Process:
                    pid = 998
                    returncode = 3221225477
                    _handle = Handle()
                    stdin = io.StringIO()
                    stdout = io.StringIO('')

                    def poll(self):
                        self_test.assertFalse(self._handle.closed, 'no Popen reads after explicit Handle.Close')
                        return self.returncode

                    def wait(self, *args, **kwargs):
                        self_test.assertFalse(self._handle.closed)
                        calls.append('wait')
                        return self.returncode
                self_test = self
                process = Process()
                real_module = C.module
                real_save = C.save
                t = L.ActualTransport.__new__(L.ActualTransport)
                t.attempt = Path(tmp)
                t.psutil = types.SimpleNamespace()
                cfg = C.load(C.PROFILE)
                cfg['runtime_epoch'] = 1

                def popen(label, argv, **kwargs):
                    self.assertIs(kwargs['env'], mapping[0])
                    self.assertEqual(kwargs['cwd'], cfg['cwd'])
                    self.assertEqual(argv, [cfg['exe'], '--serve', *t.nativeargs])
                    calls.append('fake-Popen')
                    return process

                def module(name, path):
                    m = real_module(name, path)
                    if name == 'serve.server':
                        m.popen = popen
                        m.contain = lambda p: None
                        m.narrate_start = lambda *a: None
                        m.transient_start_failure = lambda *a: False
                        server_module.append(m)
                    return m
                env_method = t.startup_environment

                def environment(*args):
                    value = env_method(*args)
                    mapping.append(value[0])
                    return value
                t.startup_environment = environment

                def save(path, value):
                    if record_failure and Path(path).name == 'constructor-failure.json':
                        raise OSError('controlled secondary record failure')
                    return real_save(path, value)
                helper = C.module('t46_startup_test_args', C.PACKAGE / 'Strata-extensions/models/deepseek41/server_hooks.py')
                t.nativeargs = helper.native_args(cfg)
                before = dict(os.environ)
                with patch.object(C, 'module', side_effect=module), patch.object(C, 'save', side_effect=save):
                    with self.assertRaises(Exception) as caught:
                        t.service(cfg)
                self.assertIsInstance(caught.exception, server_module[0].EngineDied)
                self.assertEqual(dict(os.environ), before)
                receipt = C.load(next(Path(tmp).glob('startup-*/execution-environment.json')))
                self.assertEqual(receipt['final'], L.environment_projection(mapping[0]))
                self.assertEqual(receipt['native_argv'], [cfg['exe'], '--serve', *t.nativeargs])
                self.assertEqual(mapping[0]['STRATA_FAMILY_SOURCE_ROOT'], str(C.PACKAGE / 'base'))
                self.assertEqual(calls, ['fake-Popen', 'wait', 'wait', 'handle'])
                if record_failure:
                    self.assertIn('controlled secondary record failure', str(caught.exception.__notes__))
        for old in (None, '', 'prior-root'):
            with self.subTest(loader_failure=old), patch.dict(os.environ):
                key = 'STRATA_FAMILY_SOURCE_ROOT'
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
                before = dict(os.environ)

                def fail_load(name, path):
                    self.assertEqual(os.environ[key], str(C.PACKAGE / 'base'))
                    raise ImportError('controlled loader failure')
                with patch.object(C, 'module', side_effect=fail_load):
                    with self.assertRaisesRegex(ImportError, 'controlled loader failure'):
                        t.service(cfg)
                self.assertEqual(dict(os.environ), before)
    def test_fresh_INFO_original_queue_boundary_and_failures(self):
        self.assertTrue(C.contact_selected()) # selected new tuple also exercises this production body
        for case in ('good', 'stale', 'active', 'cookie', 'owner', 'generation', 'ERR', 'EOF', 'timeout', 'malformed', 'object', 'bool', 'string', 'negative', 'unexpected', 'position0', 'save-error', 'nestedNaN', 'nestedInfinity'):
            with self.subTest(INFO=case), tempfile.TemporaryDirectory(dir=C.HERE) as tmp:
                a = Path(tmp)
                old = C.ORIGINAL_HERE / 'matching-contact-actual-attempt-02'
                for name in ('config', 'control-cancellation', 'complete-http', 'complete-clock', 'complete-sse', 'startup-info'):
                    C.save(a / (name + '.json'), C.load(old / (name + '.json')))
                rows = [json.loads(x) for x in (old / 'observer.jsonl').read_text(encoding='utf8').splitlines()]
                rows = rows[:-1]
                binding = {k: rows[0][k] for k in ('owner', 'hook_sha256', 'runtime_epoch')}
                spec = C.load(old / 'spec.json')
                self.rebind_observer_fixture(rows, spec)
                spec['output'] = str(a / 'observer.jsonl')
                C.save(a / 'spec.json', spec)
                if case == 'cookie':
                    rows[-1]['cookie'] = ['foreign', binding['runtime_epoch']]
                (a / 'observer.jsonl').write_text(''.join((json.dumps(x) + '\n' for x in rows)), encoding='utf8')
                cfg = C.load(a / 'config.json')
                info = C.load(a / 'startup-info.json')
                info['core_position'] = 5
                info['nullable_CPU'] = None
                value = {'bool': True, 'string': '5', 'negative': -1, 'position0': 0}.get(case, 5)
                info['core_position'] = value
                if case in ('nestedNaN', 'nestedInfinity'):
                    info['extra'] = [dict(nested=float('nan' if case == 'nestedNaN' else 'inf'))]
                response = 'INFO ' + json.dumps(info)
                if case == 'ERR':
                    response = 'ERR measurement failed'
                elif case == 'EOF':
                    response = None
                elif case == 'malformed':
                    response = 'INFO {'
                elif case == 'object':
                    response = 'INFO []'
                elif case == 'unexpected':
                    response = 'DONE 2'
                lines = queue.Queue()
                calls = []
                original = types.SimpleNamespace(pid=binding['owner']['engine']['pid'])
                engine = types.SimpleNamespace(proc=original, gen=1, ctl=threading.Lock(), lines=lines, active_cookie=None, alive=lambda: True, trial_observer=types.SimpleNamespace(owner=binding['owner'], active=None, cookies=[r['cookie'] for r in rows if r['event'] == 'request']))

                def send(text):
                    calls.append(text)
                    if case == 'generation':
                        engine.gen += 1
                    if case != 'timeout':
                        lines.put(response)
                engine._send = send
                if case == 'stale':
                    lines.put('INFO ' + json.dumps(info))
                if case == 'active':
                    engine.active_cookie = ['foreign', cfg['runtime_epoch']]
                birth = binding['owner']['engine']['birth'] + (1 if case == 'owner' else 0)
                t = L.ActualTransport.__new__(L.ActualTransport)
                t.attempt = a
                t.cfg = cfg
                t.spec = spec
                t.binding = binding
                t.engine = engine
                t.info_parser = json.loads
                t.psutil = types.SimpleNamespace(Process=lambda pid: types.SimpleNamespace(pid=pid, create_time=lambda: birth))
                closed = []
                t.start = lambda: None
                t.cleanup = lambda: closed.append(True) or dict(ok=True)
                t.capture = lambda: t.fresh_INFO()
                if case == 'good':
                    result = t.fresh_INFO()
                    self.assertEqual(result, info)
                    self.assertIsNone(result['nullable_CPU'])
                    self.assertEqual(C.load(a / 'startup-info.json')['core_position'], 0)
                elif case == 'position0':
                    result = t.fresh_INFO()
                    self.assertEqual(result['core_position'], 0)
                    self.assertNotEqual(result['core_position'], 5)
                elif case == 'timeout':
                    with patch.object(L.time, 'monotonic', side_effect=[0.0, 301.0]), self.assertRaisesRegex(ValueError, 'timeout'):
                        L.run_stage(t, lambda t: self.fail('qualification'))
                elif case == 'save-error':
                    engine.lines.put('stale')
                    with patch.object(C, 'save', side_effect=OSError('receipt disk fault')), self.assertRaisesRegex(ValueError, 'queue not clean'):
                        t.fresh_INFO()
                else:
                    with self.assertRaises((ValueError, TypeError)):
                        L.run_stage(t, lambda t: self.fail('qualification'))
                self.assertFalse(engine.ctl.locked())
                self.assertLessEqual(len(calls), 1)
                self.assertTrue(all((v == 'INFO' for v in calls)))
                if case not in ('good', 'position0', 'save-error'):
                    self.assertEqual(closed, [True])
                if case != 'save-error':
                    saved = C.load(a / 'fresh-INFO-receipt.json')
                    self.assertEqual(saved['ok'], case in ('good', 'position0'))
                    if case in ('ERR', 'EOF', 'malformed', 'object', 'bool', 'string', 'negative', 'unexpected'):
                        self.assertEqual(saved['responses'][0]['line'], response)
                    if case in ('nestedNaN', 'nestedInfinity'):
                        self.assertEqual(saved['responses'][0]['line'], response)
                        self.assertIsNone(saved['parsed'])
                        self.assertIsNotNone(saved['error'])
    def rebind_observer_fixture(self, rows, spec):
        spec['package_id'] = C.ID
        spec['bundle_id'] = C.BUNDLE
        rows[0]['package_id'] = C.ID
        rows[0]['bundle_id'] = C.BUNDLE
        for value in rows:
            line = value.get('line')
            if value['event'] == 'receive' and isinstance(line, str) and line.startswith('{'):
                frame = json.loads(line)
                if 'bundle_id' in frame:
                    frame['bundle_id'] = C.BUNDLE
                value['line'] = json.dumps(frame)

class NewDomainProduction(unittest.TestCase):
 def test_real_capture_qualify_emit_and_readonly_replay_new_id(self):
  # External final artifact binding has its own selection tests; this is a
  # synthetic transport domain over the real installed CPU Service/Recipe body.
  saved={k:getattr(C,k)for k in ('ID','PACKAGE','BUNDLE','HOOK','PROFILE','CANDIDATE_INPUT','CANDIDATE_PROOF','CONTACT_ID','CONTACT_SOURCE','CONTACT_NATIVE','CONTACT_HOOK','_SELECTED_CONTACT','_CONTACT_BOUND')}
  try:
   C.bind_candidate(C.CONTACT_PREP/'inputs-perf-r1.json',C.B/'package-candidate-de662662c8da/verification.json')
   C.ID='1'*64;C.BUNDLE=C.CONTACT_NATIVE='2'*64;C.CONTACT_SOURCE='3'*64
   C._SELECTED_CONTACT=dict(package_id=C.ID)
   self.assertNotEqual(C.ID,C.CONTACT_ID)
   original_load=C.load;cfg=original_load(C.PROFILE);cfg['runtime_package']['id']=C.ID;cfg['bundle_id']=C.BUNDLE
   with tempfile.TemporaryDirectory()as tmp:
    fixture_root=Path(tmp)/C.ID;hook=fixture_root/'Strata-extensions/models/deepseek41/server_hooks.py';hook.parent.mkdir(parents=True)
    hook.write_bytes((C.PACKAGE/'Strata-extensions/models/deepseek41/server_hooks.py').read_bytes())
    manifest=fixture_root/'evidence/package-manifest.json';manifest.parent.mkdir()
    manifest.write_text(json.dumps(dict(schema='strata-t29-runtime-package/v1',id=C.ID,files=[C.row(hook)],execution_extension=dict(abi='strata-deepseek-execution/v1'))),encoding='utf8')
    cfg['runtime_package']['manifest']=str(manifest)
    def load(path):return copy.deepcopy(cfg)if Path(path)==C.PROFILE else original_load(path)
    # External candidate assembly is a separate fixture boundary. Actual replay,
    # qualify, selected hook capability, wait/fresh and emission are NOT mocked.
    with patch.object(C,'load',side_effect=load),patch.object(C,'bind_candidate',return_value=None):
     case=ProductionBodies('test_read_only_final_single_replay_synthetic_and_missing_reject')
     case.test_startup_selected_server_fake_Popen_exact_env_and_original_error()
     case.test_fresh_INFO_original_queue_boundary_and_failures()
     case.test_read_only_final_single_replay_synthetic_and_missing_reject()
  finally:
   for k,v in saved.items():setattr(C,k,v)

if __name__=='__main__':
 with patch('subprocess.Popen',side_effect=AssertionError('CPU no native')):
  unittest.main(verbosity=2)
