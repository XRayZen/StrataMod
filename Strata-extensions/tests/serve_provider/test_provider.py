import hashlib, importlib.util, json, math, struct, unittest
from pathlib import Path
from q_reference import metadata
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('frames',ROOT/'Strata-extensions/control/generation_frames.py')
frames=importlib.util.module_from_spec(spec);spec.loader.exec_module(frames)
CTX=dict(request_id='request0',runtime_epoch=1,bundle_id='a'*64,asset_revision=frames.REVISION,model_family='deepseek41',tokenizer_identity=frames.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)
def sequence(lp=True):
    common=dict(schema='strata-generation/v1',request_id='request0',runtime_epoch=1)
    begin=dict(common,kind='begin',**{k:v for k,v in CTX.items() if k not in ('request_id','runtime_epoch')},metadata_schema='strata-generation-metadata/v1')
    batch=dict(common,kind='token_batch',sequence=0,origin='native-generated',ids=[5,1],logprobs=[{'logprob':-1.0,'top_logprobs':[{'token_id':5,'logprob':-1.0}]},{'logprob':-2.0,'top_logprobs':[]}])
    records=[(5,(-1.0,[(5,-1.0)])),(1,(-2.0,[]))]
    end=dict(common,kind='finish',sequence=1,generated_count=2,finish='stop',ids_sha256=hashlib.sha256(struct.pack('<II',5,1)).hexdigest(),stop_origin='eos',metadata_sha256=metadata(records,'eos'))
    return [begin,batch,end]
class Frames(unittest.TestCase):
    def run_frames(self,values):
        dto=frames.GenerationDTO(CTX)
        for x in values:dto.feed(json.dumps(x))
        return dto.result()
    def test_metadata(self):
        r=self.run_frames(sequence());self.assertEqual(r['stop_origin'],'eos');self.assertEqual(len(r['logprobs']),2)
    def test_mutants(self):
        for axis,value in [('metadata_sha256','0'*64),('stop_origin','recipe')]:
            x=sequence();x[-1][axis]=value
            with self.assertRaises(ValueError):self.run_frames(x)
        for value in [None,[],[{'logprob':True,'top_logprobs':[]}], [{'logprob':1,'top_logprobs':[]}]*2]:
            x=sequence();x[1]['logprobs']=value
            with self.assertRaises(ValueError):self.run_frames(x)

class FamilyOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os,sys
        sys.path[:0]=[str(ROOT),str(ROOT/'tools')];os.environ['STRATA_FAMILY_SOURCE_ROOT']=str(ROOT)
        spec=importlib.util.spec_from_file_location('serve.server',ROOT/'build-deepseek-t28/normal/server/serve/server.py')
        cls.server=importlib.util.module_from_spec(spec);sys.modules['serve.server']=cls.server;spec.loader.exec_module(cls.server)
        spec=importlib.util.spec_from_file_location('t28_hooks',ROOT/'Strata-extensions/models/deepseek41/server_hooks.py')
        cls.h=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.h)
        cls.tokenizer=cls.h.TokenizerFacade(ROOT/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json')
    def test_literal_tokenizer_bytes(self):
        for text in ('hello','日本語🦀','<｜end▁of▁sentence｜>'):
            ids=self.tokenizer.encode(text)
            self.assertEqual(self.tokenizer.decode(ids),text)
            self.assertEqual(b''.join(self.tokenizer.token_bytes(i)for i in ids),text.encode())
        self.assertNotIn(1,self.tokenizer.encode('<｜end▁of▁sentence｜>'))
        self.assertIn(1,self.tokenizer.encode('<｜end▁of▁sentence｜>',parse_special=True))
    def test_option_values(self):
        for k in (0,1,65,129280,200000):
            value={'top_k':k,'seed':0,'frequency_penalty':-2,'presence_penalty':2,'temperature':0}
            resolved=self.h.validate_options(value,settings=True)
            keys=self.h.sampling_keys(resolved)
            self.assertIn(' top_k='+str(k),keys);self.assertIn(' seed=0',keys);self.assertIn('penalty_freq=-2',keys)
            self.assertNotIn('penalty_last_n=',keys)
        for effort in self.h.EFFORTS:self.h.validate_options({'reasoning_effort':effort},settings=True)
        for v in (True,-1,2.5):
            with self.assertRaises(ValueError):self.h.validate_options({'top_k':v},settings=True)
    def test_official_effective_and_legacy(self):
        body={'model':'strata','messages':[{'role':'user','content':'Hi'}],'thinking':{'type':'disabled'},'temperature':0,'top_p':.2}
        p=self.h.codec.prepare_chat(body,self.tokenizer.recipe,1048576)
        self.assertEqual(p['inference_options'].temperature,0);self.assertEqual(p['inference_options'].top_p,1);self.assertEqual(p['max_tokens'],8192)
        p=self.h.codec.prepare_chat({**body,'thinking':{'type':'enabled'}},self.tokenizer.recipe,1048576)
        self.assertEqual(p['inference_options'].temperature,1);self.assertEqual(p['inference_options'].top_p,struct.unpack('<f',struct.pack('<f',.95))[0])
        for context in (64,393216,1048576):
            p=self.h.codec.prepare_chat({**body,'max_tokens':0},self.tokenizer.recipe,context)
            self.assertEqual(p['max_tokens'],min(context-len(p['input_ids']),393216))
        with self.assertRaises(Exception):self.h.codec.prepare_chat({**body,'max_tokens':393217},self.tokenizer.recipe,1048576)
    def test_nonfamily_and_family_dispatch(self):
        import sys
        spec=importlib.util.spec_from_file_location('t28_untouched_server',ROOT/'build-deepseek-t28/normal/server/serve/server.py')
        base=importlib.util.module_from_spec(spec);sys.modules[spec.name]=base;spec.loader.exec_module(base)
        original=base.clean_shared_defaults
        self.assertFalse(self.h.install(base,{}));self.assertIs(base.clean_shared_defaults,original)
        self.assertEqual(base.default_model_name({}),'qwen3.8-flash-next')
        with self.assertRaises(ValueError):original({'top_k':0})
        self.assertTrue(self.h.install(base,{'family':'deepseek41','context':16,'runtime_epoch':1}))
        self.assertEqual(base.clean_shared_defaults({'top_k':0,'seed':0})['top_k'],0)
        self.assertEqual(base.default_model_name({}),'deepseek-v4.1-flash-1017-ud-q4_k_xl')
        self.assertEqual(base.default_model_name({'model_name':'caller-alias'}),'caller-alias')
        engine=base.StrataEngine('unused-normal.exe',[],lazy=True)
        self.assertEqual(engine.max_context,16)

class ServiceControls(FamilyOptions):
    def make_service(self,text,finish='stop',extra=None,stop_origin='eos',cancel=False):
        import types,threading
        server=self.server;h=self.h;h.install(server,{'family':'deepseek41','context':4096,'runtime_epoch':1})
        tokenizer=self.tokenizer;batch=tokenizer.encode(text);stops=[]
        engine=types.SimpleNamespace(max_context=4096,info={},last={},batch=0,alive=lambda:True)
        engine._send_stop=lambda reason,cookie:stops.append((reason,cookie))
        def native_frames(ids,maximum,sampling,event,transport):
            transport['cookie']=('request0',1)
            common=dict(schema='strata-generation/v1',request_id='request0',runtime_epoch=1)
            yield json.dumps(dict(common,kind='begin',**{k:v for k,v in CTX.items()if k not in('request_id','runtime_epoch')},metadata_schema='strata-generation-metadata/v1'))
            yield json.dumps(dict(common,kind='token_batch',sequence=0,origin='native-generated',ids=batch))
            if cancel:event.set()
            origin='recipe'if stops else stop_origin
            if finish=='cancel':origin='user_cancel'
            if finish in('error','nonfinite'):origin=finish
            yield json.dumps(dict(common,kind='finish',sequence=1,generated_count=len(batch),finish=finish,ids_sha256=hashlib.sha256(b''.join(struct.pack('<I',x)for x in batch)).hexdigest(),stop_origin=origin,metadata_sha256=metadata([(x,None)for x in batch],origin)))
            engine.last=dict(generated=len(batch),reused=0)
        engine.frames=native_frames
        service=server.Service(engine,tokenizer,None,sampling_defaults={'top_k':65})
        body=dict(model='strata',messages=[{'role':'user','content':'Hi'}],thinking={'type':'disabled'},temperature=0,max_tokens=32,**(extra or{}))
        ids,thinking,maximum=service.prepare(body['messages'],None,{},req=body)
        return service,ids,thinking,maximum,body,stops
    def test_normal_stopstring_controlled(self):
        import threading
        svc,ids,thinking,maximum,body,stops=self.make_service('beforeSTOPafter',extra={'stop':['STOP']})
        values=list(svc.run(ids,thinking,None,maximum,body,threading.Event()))
        self.assertEqual(''.join(x.text for kind,x in values if kind=='event'and x.kind=='content'),'before')
        self.assertEqual(stops,[('recipe_stop',('request0',1))]);self.assertEqual(values[-1][0],'done')
        self.assertEqual(svc.status['queued'],0);self.assertFalse(svc.status['busy']);self.assertEqual(svc.totals['requests'],1)
        self.assertTrue(svc.fifo.acquire(blocking=False));svc.fifo.release()
    def test_cancel_never_success(self):
        import threading
        svc,ids,thinking,maximum,body,_=self.make_service('partial',finish='cancel',cancel=True)
        output=[]
        with self.assertRaises(self.server.ClientGone):
            for item in svc.run(ids,thinking,None,maximum,body,threading.Event()):output.append(item)
        self.assertFalse(any(kind=='done'for kind,_ in output));self.assertFalse(svc.status['busy'])
    def test_existing_http_openai_controlled(self):
        import threading,urllib.request
        svc,_,_,_,body,_=self.make_service('hello')
        http=self.server.Server(('127.0.0.1',0),self.server.make_handler(svc))
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=10)as response:value=json.load(response)
            self.assertEqual(value['choices'][0]['message']['content'],'hello')
        finally:http.shutdown();http.server_close();thread.join()


def actual_http(attempt):
    import os,sys,threading,urllib.request,importlib.util,copy,time
    attempt=Path(attempt);binding=json.loads((attempt/'manifest.json').read_text(encoding='utf-8'));cfg=json.loads((attempt/'config.json').read_text(encoding='utf-8'));q=json.loads(Path(binding['q_manifest']['path']).read_text(encoding='utf-8'))
    FamilyOptions.setUpClass();server=FamilyOptions.server;hooks=FamilyOptions.h;hooks.install(server,cfg)
    native_env=dict(os.environ);native_env.update(cfg['env']);native_env['PATH']=os.pathsep.join([str(Path(cfg['exe']).parent),'C:/Windows/System32','C:/Windows'])
    engine=server.StrataEngine(cfg['exe'],hooks.native_args(cfg),cwd=str(ROOT),env=native_env,log=str(attempt/'native.log'))
    startup=copy.deepcopy(engine.info);sent=[];raw=[];original_send=engine._send;original_frames=engine.frames
    def send(line):sent.append(line);return original_send(line)
    def frames(*args,**kwargs):
        for line in original_frames(*args,**kwargs):
            if line is not None:raw.append(json.loads(line))
            yield line
    engine._send=send;engine.frames=frames
    svc=server.Service(engine,FamilyOptions.tokenizer,None,sampling_defaults={'top_k':0})
    http=server.Server(('127.0.0.1',0),server.make_handler(svc));thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        body=q['request'];prepared=svc.prepare(body['messages'],None,{},req=body)[0]
        if list(prepared)!=q['input_ids']:raise ValueError('actual common entry prompt IDs differ')
        request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=900)as response:value=json.load(response)
        batches=[x for x in raw if x['kind']=='token_batch'];ids=[i for x in batches for i in x['ids']]
        if ids!=[q['expected_id']]:raise ValueError('actual normal producer original ID differs')
        records=[x for b in batches for x in b['logprobs']]
        ulp=lambda a,b:abs(struct.unpack('<I',struct.pack('<f',a))[0]-struct.unpack('<I',struct.pack('<f',b))[0])
        if ulp(records[0]['logprob'],q['selected_logprob_f32'])>2:raise ValueError('actual LP exceeds local 2ULP envelope')
        if len(records[0]['top_logprobs'])!=len(q['top_logprobs']):raise ValueError('top LP coverage')
        for got,want in zip(records[0]['top_logprobs'],q['top_logprobs'],strict=True):
            if got['token_id']!=want['token_id']or ulp(got['logprob'],want['logprob'])>2:raise ValueError('top LP differs')
        if value['choices'][0]['finish_reason']!='length'or value['usage']['completion_tokens']!=1:raise ValueError('HTTP terminal/count')
        result=dict(status='pending independent review',http_response=value,raw_frames=raw,sent=sent,startup_info=startup,engine_last=engine.last,actual_native_producer=True,controlled_engine=False,request_ids=list(prepared),normal_profile_published=False)
        (attempt/'capture.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    finally:
        http.shutdown();http.server_close();thread.join();engine.close()

if __name__=='__main__':
    import sys
    if len(sys.argv)==3 and sys.argv[1]=='--actual-http':actual_http(sys.argv[2])
    else:unittest.main()


