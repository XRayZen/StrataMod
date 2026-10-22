"""DeepSeek family adapters for the existing Strata server, not another server."""
import contextlib
import copy
import hashlib
import importlib.util
import json
import math
import os
import queue
import sys
import threading
import time
from pathlib import Path
import deepseek_recipe as recipe

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
codec=module('deepseek_normal_codec',Path(__file__).with_name('serve_codec.py'))
EFFORTS=('none','minimal','low','medium','high','xhigh','ultra','max')
ALIASES={'repeat_penalty':'repetition_penalty','repeat_last_n':'penalty_last_n'}
ROUTING_KEYS=('routing_primary_bonus','routing_secondary_bonus','routing_ssd_penalty')
FIELDS=set(ROUTING_KEYS)|{'temperature','top_p','top_k','min_p','frequency_penalty','presence_penalty','repetition_penalty','penalty_last_n','seed','reasoning_effort','thinking','max_tokens','max_completion_tokens','logprobs','top_logprobs','stop','logit_bias','reasoning_budget_tokens'}
def validate_options(value,*,settings=False):
    if type(value)is not dict:raise ValueError('sampling settings must be an object')
    out=copy.deepcopy(value)
    for alias,canonical in ALIASES.items():
        if alias in out:
            if canonical in out and out[canonical]is not None:raise ValueError('conflicting sampling alias: '+alias)
            out[canonical]=out.pop(alias)
    if settings and set(out)-FIELDS:raise ValueError('unknown family setting: '+','.join(sorted(set(out)-FIELDS)))
    for key,v in list(out.items()):
        if key in ROUTING_KEYS and not(type(v)in(int,float)and math.isfinite(v)and 0<=v<=1):raise ValueError('routing coefficient finite [0,1]: '+key)
        if v is None:continue
        number=type(v)in(int,float) and math.isfinite(v)
        if key=='temperature' and not(number and 0<=v<=2):raise ValueError('temperature [0,2]')
        if key=='top_p' and not(number and 0<v<=1):raise ValueError('top_p (0,1]')
        if key=='min_p' and not(number and 0<=v<=1):raise ValueError('min_p [0,1]')
        if key in ('frequency_penalty','presence_penalty') and not(number and -2<=v<=2):raise ValueError('penalty [-2,2]')
        if key=='repetition_penalty' and not(number and v>0):raise ValueError('repetition penalty positive')
        if key in ('top_k','seed','penalty_last_n','max_tokens','max_completion_tokens','top_logprobs','reasoning_budget_tokens'):
            if type(v)is not int:raise ValueError(key+' integer required')
            if key in ('top_k','reasoning_budget_tokens') and v<0:raise ValueError(key+' nonnegative')
            if key=='seed' and not 0<=v<2**63:raise ValueError('official seed [0,2^63)')
            if key=='top_logprobs' and not 0<=v<=20:raise ValueError('top_logprobs 0..20')
        if key=='logprobs' and type(v)is not bool:raise ValueError('logprobs boolean')
        if key=='reasoning_effort' and v not in EFFORTS:raise ValueError('official reasoning effort')
        if key=='thinking' and (type(v)is not dict or v.get('type')not in('enabled','adaptive','disabled')):raise ValueError('official thinking mode')
        if key=='logit_bias':
            if type(v)is not dict:raise ValueError('logit_bias object')
            for token,bias in v.items():
                if not str(token).isdigit()or not 0<=int(token)<129280 or type(bias)not in(int,float)or not math.isfinite(bias):raise ValueError('original ID/finite bias')
    return out

def sampling_keys(value):
    s=validate_options(value);parts=[]
    names={'temperature':'temperature','top_p':'top_p','top_k':'top_k','min_p':'min_p','repetition_penalty':'penalty_repeat','frequency_penalty':'penalty_freq','presence_penalty':'penalty_present','penalty_last_n':'penalty_last_n','seed':'seed','logprobs':'logprobs','top_logprobs':'top_logprobs'}
    names.update({key:key for key in ROUTING_KEYS})
    for key,native in names.items():
        if key in s and s[key]is not None:parts.append(native+'='+str(0 if key in ROUTING_KEYS and s[key]==0 else(int(s[key])if type(s[key])is bool else s[key])))
    if s.get('logit_bias'):parts.append('logit_bias='+','.join(str(int(k))+':'+repr(v)for k,v in sorted(s['logit_bias'].items(),key=lambda x:int(x[0]))))
    return ''.join(' '+x for x in parts)

class TokenizerFacade:
    def __init__(self,path):
        self.path=Path(path);self.recipe=recipe.Tokenizer.from_file(str(path));data=json.loads(self.path.read_text(encoding='utf-8'))
        self.special={row['id']:row['content'].encode('utf-8')for row in data.get('added_tokens',[])}
        self.vocabulary={int(v):k for k,v in data['model']['vocab'].items()}
        base=list(range(33,127))+list(range(161,173))+list(range(174,256));chars=base[:];extra=0
        for byte in range(256):
            if byte not in base:base.append(byte);chars.append(256+extra);extra+=1
        self.byte_decoder={chr(char):byte for byte,char in zip(base,chars)}
        data['added_tokens']=[];self.plain=recipe.Tokenizer.from_str(json.dumps(data));self.vocab_size=129280
    def encode(self,text,parse_special=False,**kwargs):return (self.recipe if parse_special else self.plain).encode(text)
    def decode(self,ids,**kwargs):return b''.join(self.token_bytes(i)for i in ids).decode('utf-8',errors='replace')
    def token_bytes(self,token):
        if token in self.special:return self.special[token]
        return bytes(self.byte_decoder[c]for c in self.vocabulary[int(token)])

class PreparedIDs(list):
    def __init__(self,prepared,body):super().__init__(prepared['input_ids']);self.prepared=prepared;self.body=body

def native_args(config):
    # T29 declares intended values; this factory passes them to native allocation.
    args=['--serve','--artifact-root',config['artifact_root'],'--primary-pci',config['primary_pci'],'--context',str(config['context']),'--bundle-id',config['bundle_id'],'--runtime-epoch',str(config['runtime_epoch'])]
    placement=config.get('placement')
    if placement is not None:
        contracts=module('deepseek_placement_contract',Path(__file__).resolve().parents[2]/'control/contracts.py')
        contracts.validate_placement(placement)
        if placement['primary']!=config['primary_pci']or('secondary'in config and placement['secondary']!=config['secondary']):raise ValueError('placement PCI mismatch')
        if placement['mode']not in('single','cache-only','expert-assist','layer-split'):raise ValueError('placement mode')
        if placement['mode']!='single'and(not placement['secondary']or placement['secondary']==placement['primary']):raise ValueError('distinct secondary PCI required')
        args+=['--mode',placement['mode']]
        if placement['secondary']is not None:args+=['--secondary-pci',placement['secondary']]
        if placement['mode']=='expert-assist':args+=['--secondary-experts',','.join(str(value)for value in placement['assignment'])]
        if placement['mode']=='layer-split':args+=['--layer-cut',str(placement['cut'])]
    for i,path in enumerate(config.get('native_paths',[]),1):args+=['--source'+str(i),str(path)]
    for key,value in config.get('cache_budget',{}).items():args+=['--'+key.replace('_','-'),str(value)]
    for key in ('auto_cache_fraction','auto_row_fraction','tile_bytes','tile_rows','active_batch'):
        if key in config:args+=['--'+key.replace('_','-'),str(config[key])]
    contracts=module('deepseek_native_features',Path(__file__).resolve().parents[2]/'control/contracts.py')
    return args+contracts.native_feature_args(config)+list(config.get('args')or[])


class TrialObserver:
    """Finite, explicit T46 fixture. Never observes an ordinary request."""
    SAMPLE={'temperature':0,'top_k':0,'top_p':1,'min_p':0,'seed':0,'logprobs':True,'top_logprobs':3}
    IDS=[0,128803,128804,128822]

    def __init__(self, spec_path, config):
        import uuid
        path=Path(spec_path)
        if not path.is_absolute():raise ValueError('observer spec requires absolute path')
        path=path.resolve(strict=True)
        spec=json.loads(path.read_text(encoding='utf-8'))
        if spec.get('schema')!='strata-t46-observer-spec/v1':raise ValueError('observer spec schema')
        if str(uuid.UUID(spec['run_id']))!=spec['run_id']:raise ValueError('observer run UUID')
        package=config['runtime_package'];manifest=Path(package['manifest']).resolve(strict=True)
        declaration=json.loads(manifest.read_text(encoding='utf-8-sig'))
        hook=Path(__file__).resolve();root=manifest.parent.parent
        rows=[row for row in declaration['files'] if Path(row['path']).resolve()==hook]
        if (root.name!=package['id'] or declaration.get('id')!=package['id'] or
                declaration.get('schema')!='strata-t29-runtime-package/v1' or
                not hook.is_relative_to(root) or len(rows)!=1 or
                rows[0]['bytes']!=hook.stat().st_size or rows[0]['sha256']!=hashlib.sha256(hook.read_bytes()).hexdigest()):
            raise ValueError('observer selected hook/package binding')
        mode=config.get('placement',{}).get('mode','single')
        expected=dict(package_id=package['id'],bundle_id=config['bundle_id'],mode=mode,context=4096,
                      input_ids=self.IDS,max_tokens=2,sampling=self.SAMPLE)
        if config['context']!=4096 or any(spec.get(k)!=v for k,v in expected.items()):raise ValueError('observer config/fixture mismatch')
        if type(spec.get('cancel_first_matching_begin'))is not bool:raise ValueError('observer cancel fixture boolean')
        output=Path(spec['output'])
        if not output.is_absolute() or output.resolve().parent!=path.parent:raise ValueError('observer output must be in sealed attempt directory')
        self.spec=spec;self.spec_path=path;self.config=config;self.sequence=0;self.error=None;self.active=None;self.cookies=[]
        self.cancel_pending=spec['cancel_first_matching_begin'];self.closed=False;self.owner=None
        self.stream=output.open('x',encoding='utf-8',newline='\n')
        self.hook_sha256=rows[0]['sha256']

    def identity(self, engine):
        import psutil
        def birth(pid):
            process=psutil.Process(pid)
            return dict(pid=process.pid,birth=process.create_time())
        return dict(server=birth(os.getpid()),engine=birth(engine.proc.pid))

    def emit(self, event, **fields):
        if self.error or self.closed:return False
        try:
            row=dict(schema='strata-t46-observer/v1',run_id=self.spec['run_id'],sequence=self.sequence,
                     monotonic_ns=time.monotonic_ns(),event=event,**fields)
            self.stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');self.stream.flush()
            self.sequence+=1
            return True
        except Exception as error:
            self.error=type(error).__name__
            return False

    def start(self, engine):
        try:
            self.owner=self.identity(engine)
            self.emit('header',owner=self.owner,hook_sha256=self.hook_sha256,package_id=self.spec['package_id'],
                      bundle_id=self.config['bundle_id'],mode=self.spec['mode'],runtime_epoch=self.config['runtime_epoch'])
        except Exception as error:self.error=type(error).__name__

    def request(self, engine, ids, maximum, sampling, cookie):
        self.active=None
        if self.error or self.closed:return
        if list(ids)!=self.IDS or maximum!=2 or any(sampling.get(k)!=v for k,v in self.SAMPLE.items()):return
        # Extra effective sampling overrides would invalidate the declared fixture.
        if any(k not in self.SAMPLE and v is not None and k not in ('thinking','reasoning_effort','max_tokens','max_completion_tokens') for k,v in sampling.items()):return
        if sampling.get('thinking',{'type':'disabled'})!={'type':'disabled'} or sampling.get('reasoning_effort','none')!='none':return
        self.active=cookie;self.cookies.append(list(cookie))
        try:
            owner=self.identity(engine)
            if owner!=self.owner:self.error='owner_changed'
            self.emit('request',cookie=cookie,owner=owner,runtime_epoch=cookie[1])
        except Exception as error:self.error=type(error).__name__

    def sent(self, text, error=False):
        if self.active is not None and (text.startswith('GEN ') or text.startswith('STOP ')):
            self.emit('send_error' if error else 'send',cookie=self.active,line=text)

    def line(self, line, phase, cancel):
        if self.active is None or self.error or self.closed:return
        self.emit('receive',cookie=self.active,phase=phase,line=line)
        if self.error:return
        if line is not None and line.startswith('{'):
            try:
                frame=json.loads(line)
                if (frame.get('request_id'),frame.get('runtime_epoch'))!=self.active:
                    self.error='frame_cookie_mismatch';return
                if frame.get('kind')=='begin' and self.cancel_pending:
                    if self.emit('cancel_fixture',cookie=self.active):
                        self.cancel_pending=False
                        cancel.set()
            except Exception as error:self.error=type(error).__name__

    def finish(self, close_error=None):
        if self.closed:return
        try:
            # A prior logging failure disables further records; missing summary is a failed capture.
            self.emit('summary',owner=self.owner,cookies=self.cookies,observer_error=self.error,close_error=close_error)
        finally:
            self.closed=True
            try:self.stream.close()
            except Exception as error:self.error=type(error).__name__


def _trial_row(path):
    path=Path(path).resolve()
    return dict(path=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def _trial_save(path,value):
    with Path(path).open('x',encoding='utf8',newline='\n')as stream:
        json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2);stream.write('\n')

def _trial_public_INFO(engine,config):
    """One explicit C4096 observer fixture, after its saved HTTP/native DONE.
    The ordinary /metrics path never calls this function.
    """
    observer=engine.trial_observer;attempt=Path(observer.spec['output']).parent
    boundary_path=attempt/'fresh-INFO-boundary.json'
    if not boundary_path.is_file():return
    process=engine.proc;generation=engine.gen;locked=False
    original_owner=copy.deepcopy(observer.owner);original_cookies=copy.deepcopy(observer.cookies)
    epoch=config['runtime_epoch'];hook_sha256=observer.hook_sha256
    receipt=dict(schema='strata-t46-fresh-INFO/v1',ok=False,error=None,send=None,send_ns=None,responses=[],parsed=None,
                 config=None,generation=generation,source='public observer-only GET /metrics, original ctl/queue')
    def require(ok,message):
        if not ok:raise ValueError('public INFO: '+message)
    def owner():
        require(engine.proc is process and engine.gen==generation and engine.alive(),'original generation changed')
        value=observer.identity(engine)
        require(type(generation)is int and value==original_owner==observer.owner and config['runtime_epoch']==epoch and observer.hook_sha256==hook_sha256 and observer.cookies==original_cookies,'owner/epoch/cookies changed')
        require(engine.active_cookie is None and observer.active is None,'request still active')
        return value['engine']
    try:
        while not locked:
            owner();locked=engine.ctl.acquire(timeout=.5)
        state=getattr(engine,'_trial_public_info_state',None)
        if state=='complete':return
        if state=='failed':raise engine._trial_public_info_error
        require(state is None,'reentrant refresh')
        engine._trial_public_info_state='pending'
        receipt['owner_before']=owner()
        require(observer.error is None and not observer.closed,'observer failed/closed')
        wrapper=json.loads(boundary_path.read_text(encoding='utf8'));json.dumps(wrapper,allow_nan=False)
        require(wrapper.get('schema')=='strata-t46-public-INFO-boundary/v1'and wrapper.get('spec')==_trial_row(observer.spec_path),'boundary spec')
        cfg_path=attempt/'config.json'
        require(wrapper.get('config')==_trial_row(cfg_path)and json.loads(cfg_path.read_text(encoding='utf8'))==config,'boundary config')
        boundary=wrapper['boundary'];bound=dict(owner=observer.owner,hook_sha256=observer.hook_sha256,runtime_epoch=config['runtime_epoch'])
        require(boundary['binding']==bound and boundary['cookies']==observer.cookies and len(observer.cookies)==2 and boundary['cookie']==observer.cookies[1]and observer.cookies[0]!=observer.cookies[1],'boundary cookies/owner')
        require(all(cookie[1]==config['runtime_epoch']for cookie in observer.cookies),'cookie epoch')
        rows=[json.loads(line)for line in Path(observer.spec['output']).read_text(encoding='utf8').splitlines()]
        require(rows and rows[0].get('event')=='header'and rows[0].get('owner')==observer.owner and rows[0].get('hook_sha256')==observer.hook_sha256,'original header')
        for key,value in [('package_id',observer.spec['package_id']),('bundle_id',config['bundle_id']),('mode',config['placement']['mode']),('runtime_epoch',config['runtime_epoch'])]:
            require(rows[0].get(key)==value,'original header '+key)
        previous=-1
        for index,row in enumerate(rows):
            require(row.get('schema')=='strata-t46-observer/v1'and row.get('run_id')==observer.spec['run_id']and type(row.get('sequence'))is int and row['sequence']==index and type(row.get('monotonic_ns'))is int and row['monotonic_ns']>=previous,'original observer sequence/clock')
            previous=row['monotonic_ns']
        requests=[row for row in rows if row.get('event')=='request']
        require([row.get('cookie')for row in requests]==observer.cookies and all(row.get('owner')==observer.owner and row.get('runtime_epoch')==config['runtime_epoch']for row in requests),'original request owner/cookies')
        require(rows[-1]==boundary['native_DONE']and type(rows[-1].get('line'))is str and rows[-1]['line'].startswith('DONE ')and rows[-1]['line'].split()==['DONE','2']and rows[-1].get('cookie')==boundary['cookie'],'original terminal boundary')
        for key in ('HTTP','HTTP_clock'):
            require(boundary[key]==_trial_row(attempt/('complete-http.json'if key=='HTTP'else'complete-clock.json')),'HTTP record')
        http=json.loads((attempt/'complete-http.json').read_text(encoding='utf8'))
        clock=json.loads((attempt/'complete-clock.json').read_text(encoding='utf8'))
        chunks=json.loads((attempt/'complete-sse.json').read_text(encoding='utf8'))
        require(http['HTTP_DONE']is True and chunks[-1]=='[DONE]'and type(clock['end_ns'])is int and boundary['HTTP_end_ns']==clock['end_ns'],'HTTP DONE/end')
        receipt['boundary']=boundary;receipt['config']=wrapper['config']
        try:pending=engine.lines.get_nowait()
        except queue.Empty:pass
        else:
            receipt['responses'].append(dict(line=pending,monotonic_ns=time.monotonic_ns(),before_send=True))
            raise ValueError('public INFO: original control queue not clean')
        receipt['send']='INFO';receipt['send_ns']=time.monotonic_ns()
        require(receipt['send_ns']>=max(clock['end_ns'],boundary['native_DONE']['monotonic_ns']),'post-DONE clock')
        engine._send('INFO');deadline=time.monotonic()+300.0
        while True:
            owner();remaining=deadline-time.monotonic();require(remaining>0,'response timeout')
            try:line=engine.lines.get(timeout=max(.1,min(1.,remaining)))
            except queue.Empty:continue
            receipt['responses'].append(dict(line=line,monotonic_ns=time.monotonic_ns()))
            require(type(line)is str and line.startswith('INFO '),'EOF/error/unexpected response')
            parsed=json.loads(line[5:]);json.dumps(parsed,allow_nan=False)
            require(type(parsed)is dict and type(parsed.get('core_position'))is int and parsed['core_position']>=0,'position type')
            receipt['parsed']=parsed;receipt['owner_after']=owner();receipt['ok']=True
            engine.info.update(copy.deepcopy(parsed))
            engine._trial_public_info_state='complete'
            return
    except BaseException as error:
        # A repeated metrics call must not resend or overwrite a failed receipt.
        if getattr(engine,'_trial_public_info_state',None)=='failed':raise
        engine._trial_public_info_state='failed';engine._trial_public_info_error=error
        receipt['error']=dict(type=type(error).__name__,message=str(error))
        raise
    finally:
        pending=sys.exception()
        try:
            path=attempt/'fresh-INFO-receipt.json'
            if not path.exists():_trial_save(path,receipt)
        except BaseException as save_error:
            if pending is None:
                engine._trial_public_info_state='failed';engine._trial_public_info_error=save_error
                raise
            pending.add_note('fresh INFO receipt save failed: '+repr(save_error))
        finally:
            if locked:engine.ctl.release()

def install(server,config):
    """Only invoked for selected DeepSeek family. Non-family main is untouched."""
    if config.get('family')!='deepseek41':return False
    original_engine,original_service=server.StrataEngine,server.Service
    original_openai,original_anthropic=server.openai_to_messages,server.anthropic_to_messages
    def object_option(req,key):
        value=req.get(key)
        if value is None:return {}
        if type(value)is not dict:raise ValueError(key+' object required')
        return value
    def effective_effort(req):
        value=req.get('reasoning_effort')
        if value is None:value=object_option(req,'reasoning').get('effort')
        if value is None:value=object_option(req,'output_config').get('effort')
        if value is None:value=object_option(req,'chat_template_kwargs').get('reasoning_effort')
        if value is not None and value not in EFFORTS:raise ValueError('official reasoning effort')
        return value
    def family_openai(req):
        effective_effort(req);raw=copy.deepcopy(req)
        raw.pop('reasoning_effort',None);raw.pop('reasoning',None)
        if isinstance(raw.get('chat_template_kwargs'),dict):raw['chat_template_kwargs'].pop('reasoning_effort',None)
        messages,tools,kwargs=original_openai(raw)
        for source,destination in zip(req.get('messages',[]),messages):
            if 'tool_call_id'in source:destination['tool_call_id']=source['tool_call_id']
            for original,call in zip(source.get('tool_calls',[]),destination.get('tool_calls',[])):
                for key in('id','type'):
                    if key in original:call[key]=original[key]
        return messages,tools,kwargs
    def family_anthropic(req,*args,**kwargs):
        effective_effort(req);raw=copy.deepcopy(req)
        if isinstance(raw.get('output_config'),dict):raw['output_config'].pop('effort',None)
        return original_anthropic(raw,*args,**kwargs)
    server.openai_to_messages=family_openai;server.anthropic_to_messages=family_anthropic
    server.responses_api.template_kwargs=lambda req,shared:({'reasoning_effort':effective_effort(req)or shared.get('reasoning_effort')}if effective_effort(req)or shared.get('reasoning_effort')else{})
    from serve.frontend import ToolCall
    server.default_model_name=lambda selected:selected.get('model_name')or'deepseek-v4.1-flash-1017-ud-q4_k_xl'
    server.FAMILY_TOKENIZER_FACTORY=lambda path:TokenizerFacade(path)
    server.FAMILY_INFO_PARSER=json.loads
    server.clean_shared_defaults=lambda value:validate_options(value or{},settings=True)
    server.sampling_defaults_from_config=lambda cfg:validate_options(dict(cfg.get('sampling')or{}),settings=True)
    server.check_request_sampling=lambda value:validate_options(value)
    server.effort_end_args=lambda *args,**kw:[]
    server.lift_reasoning_effort_arg=lambda cfg:None
    server.engine_args=native_args
    class DeepSeekEngine(original_engine):
        sampling_keys=staticmethod(sampling_keys)
        def __init__(self,*args,**kwargs):
            self.family_config=config;self.transport_counter=0;self.active_cookie=None;self.frame_session=None
            spec=os.environ.get('DEEPSEEK_T46_OBSERVER_SPEC')
            self.trial_observer=TrialObserver(spec,config) if spec else None
            try:super().__init__(*args,**kwargs)
            except BaseException:
                if self.trial_observer:self.trial_observer.finish('engine_init_failed')
                raise
            self.info['logit_bias']=1
            if self.trial_observer:self.trial_observer.start(self)
            if self.unloaded:self.max_context=int(config['context'])
        def _send_stop(self,reason='user_cancel',cookie=None):
            cookie=cookie or self.active_cookie
            if cookie:self._send('STOP request_id='+cookie[0]+' epoch='+str(cookie[1])+' reason='+reason)
        def _send(self,text):
            # Base finally/error paths may still call _send; bind all STOPs.
            if text.strip()=='STOP':self._send_stop();return
            try:result=super()._send(text)
            except BaseException:
                if self.trial_observer:self.trial_observer.sent(text,error=True)
                raise
            if self.trial_observer:self.trial_observer.sent(text)
            return result
        def close(self):
            if not self.trial_observer:return super().close()
            failure=None
            try:return super().close()
            except BaseException as error:
                failure=type(error).__name__;raise
            finally:self.trial_observer.finish(failure)
        def generate(self,ids,max_new,sampling,cancel):
            transport={};dto=None
            for line in self.frames(ids,max_new,sampling,cancel,transport):
                if line is None:yield None;continue
                frame=json.loads(line)
                if frame['kind']=='begin':dto=codec._dto.GenerationDTO({k:frame[k]for k in codec._dto.CONTEXT})
                if dto is None:raise ValueError('native omitted begin')
                value=dto.feed(line)
                if frame['kind']=='token_batch':yield from value
            if dto is None:raise ValueError('native generation missing')
            result=dto.result()
            if result['finish']=='nonfinite':raise server.EngineNonFinite('native nonfinite')
            if result['finish']=='error':raise ValueError('native generation error')
        def frames(self,ids,maximum,sampling,cancel,session):
            acquired=False;done=False;sent_cancel=False;failure=None
            waiter=self._take_control(cancel,len(ids),new=True)
            while True:
                try:next(waiter);yield None
                except StopIteration as result:acquired=bool(result.value);break
            if not acquired:return
            if config.get('placement',{}).get('mode')=='cache-only':
                if self.info.get('configured_mode')!='cache-only'or self.info.get('effective_mode')not in('cache-only','cache-bypass'):
                    self.ctl.release();raise ValueError('native did not resolve requested cache-only role')
                if self.info.get('requested_secondary_pci')!=config['placement']['secondary']:
                    self.ctl.release();raise ValueError('native secondary role mismatch')
            self.transport_counter+=1
            cookie=(str(self.ctl_epoch)+'-'+str(self.transport_counter),int(config['runtime_epoch']))
            self.active_cookie=cookie
            session['cookie']=cookie
            if self.trial_observer:self.trial_observer.request(self,ids,maximum,sampling,cookie)
            if self.trial_observer:allow=0
            try:
                self._send('GEN '+str(maximum)+self.sampling_keys(sampling)+' request_id='+cookie[0]+' epoch='+str(cookie[1])+' '+','.join(map(str,ids)))
                beat=heard=time.monotonic();silence=float(getattr(self,'silence_s',0)or 0)
                allow=silence+min(len(ids),server.PP_CHUNK_MAX)/server.PP_FLOOR_TOK_S if silence>0 else 0
                stall={}
                while True:
                    if cancel.is_set()and not sent_cancel:self._send_stop('user_cancel',cookie);sent_cancel=True
                    try:line=self.lines.get(timeout=.25)
                    except queue.Empty:
                        if not self.alive():raise server.EngineDied('native producer exited')
                        if allow>0 and time.monotonic()-heard>=allow:
                            done=True;raise self._silent('native producer exceeded existing silence setting')
                        if server.ENGINE_STALL_S:self._stall_check(heard,stall,server.ENGINE_STALL_S)
                        if time.monotonic()-beat>=10:beat=time.monotonic();yield None
                        continue
                    if self.trial_observer:self.trial_observer.line(line,'normal',cancel)
                    if line is None:raise server.EngineDied('native EOF before DONE')
                    heard=time.monotonic();stall.clear()
                    if line.startswith('{'):
                        yield line
                    elif line.startswith('PP '):
                        fields=line.split();self.progress=(int(fields[1]),int(fields[2]));yield None
                    elif line.startswith('INFO '):
                        try:self.info.update(json.loads(line[5:]))
                        except ValueError:pass
                    elif line.startswith('ERR '):failure=line[4:].strip()
                    elif line.startswith('DONE'):
                        done=True
                        self.last=dict(generated=int(line.split()[1]),prompt_read=len(ids),reused=0)
                        if failure:session['native_error']=failure
                        return
            finally:
                if self.trial_observer:
                    pending=sys.exception()
                    try:
                        if not done:
                            self._send_stop('user_cancel',cookie)
                            # Existing native safe-boundary drain; no second pipe reader.
                            drained_at=time.monotonic()
                            while self.alive():
                                try:line=self.lines.get(timeout=.25)
                                except queue.Empty:
                                    if allow>0 and time.monotonic()-drained_at>=allow:raise self._silent('native did not drain within existing silence setting')
                                    continue
                                if self.trial_observer:self.trial_observer.line(line,'drain',cancel)
                                if line is None or line.startswith('DONE'):break
                    except BaseException:
                        if pending is None:raise
                    finally:
                        self.trial_observer.active=None
                        self.active_cookie=None;self.ctl.release()
                else:
                    if not done:
                        self._send_stop('user_cancel',cookie)
                        # Existing native safe-boundary drain; no second pipe reader.
                        drained_at=time.monotonic()
                        while self.alive():
                            try:line=self.lines.get(timeout=.25)
                            except queue.Empty:
                                if allow>0 and time.monotonic()-drained_at>=allow:raise self._silent('native did not drain within existing silence setting')
                                continue
                            if self.trial_observer:self.trial_observer.line(line,'drain',cancel)
                            if line is None or line.startswith('DONE'):break
                    self.active_cookie=None;self.ctl.release()
    class DeepSeekService(original_service):
        family="deepseek41"
        def metrics(self,*args,**kwargs):
            # Ordinary callers and the accepted direct single fixture delegate
            # without any refresh I/O, clock or changed exception behavior.
            observer=getattr(self.engine,'trial_observer',None)
            if observer is not None and config.get('placement',{}).get('mode','single')!='single':
                _trial_public_INFO(self.engine,config)
            return original_service.metrics(self,*args,**kwargs)
        def __init__(self,*args,**kwargs):
            kwargs.setdefault('model_name',server.default_model_name(config))
            super().__init__(*args,**kwargs);self.stop_ids={1};self.model_arch='deepseek41'
        def encode_prompt(self,messages,tools,kwargs,store=True):
            return list(self.prepare(messages,tools,kwargs)[0])
        def with_shared(self,req,api):
            # Validate explicit routing values before shared fallback can erase null.
            validate_options({k:req[k]for k in ROUTING_KEYS if k in req})
            # Presence is significant: explicit zero/negative legacy maximum wins.
            result=dict(req)
            for key,value in self.shared.items():
                if key not in result or result[key]is None:result[key]=copy.deepcopy(value)
            if result.get('reasoning_effort')is None and not result.get('thinking')and self.config_effort:result['reasoning_effort']=self.config_effort
            return result
        def prepare(self,messages,tools,kwargs,max_new=None,force=None,req=None,cancel=None):
            if cancel is not None and cancel.is_set():raise server.ClientGone()
            # Explicit routing null is invalid; missing keys preserve native startup defaults.
            validate_options({k:req[k]for k in ROUTING_KEYS if req is not None and k in req})
            body={**self.sampling_defaults,**self.shared,**{k:v for k,v in(req or{}).items()if v is not None}}
            messages=copy.deepcopy(messages)
            for message in messages:
                for call in message.get('tool_calls',[]):
                    function=call.get('function',call)
                    if not isinstance(function.get('arguments'),str):function['arguments']=json.dumps(function.get('arguments')or{},ensure_ascii=False)
            body.update(model='strata',messages=messages)
            effort=effective_effort(body)
            if effort is not None:body['reasoning_effort']=effort
            if tools:body['tools']=[t if t.get('type')=='function'else {'type':'function','function':t}for t in tools]
            if not any(k in body for k in('max_tokens','max_completion_tokens')):
                if req is None and max_new is not None:body['max_tokens']=max_new
                elif req is not None and 'max_output_tokens'in req:body['max_tokens']=req['max_output_tokens']
            ctk=body.get('chat_template_kwargs')or{}
            if 'thinking'not in body:
                if 'enable_thinking'in ctk:body['thinking']={'type':'enabled'if ctk['enable_thinking']else'disabled'}
                elif 'reasoning_effort'not in body and 'enable_thinking'in kwargs:body['thinking']={'type':'enabled'if kwargs['enable_thinking']else'disabled'}
            validate_options(body)
            prepared=codec.prepare_chat(body,self.tok.recipe,int(config['context']))
            thinking=body.get('thinking',{}).get('type')!='disabled'and body.get('reasoning_effort')!='none'
            return PreparedIDs(prepared,body),thinking,prepared['max_tokens']
        def _run(self,ids,thinking,tools,max_new,sampling,cancel,force=None):
            if not isinstance(ids,PreparedIDs):raise ValueError('normal DeepSeek request lacks official prepared IDs')
            prepared=ids.prepared
            # Converted official effective values, not raw request overrides.
            options=prepared['inference_options'];native={k:v for k,v in ids.body.items()if k in FIELDS and v is not None}
            for key in('temperature','top_p','seed','logprobs','top_logprobs'):
                value=getattr(options,key,None)
                if value is not None:native[key]=value
            native.setdefault('top_k',0);native.setdefault('min_p',0)
            started=time.time();waiting=True;got=False;generated=0;raw=None;complete=None;failure=None
            with self.status_lock:self.status['queued']+=1
            try:
                while not got:
                    got=self.fifo.acquire(timeout=server.QUEUE_BEAT_S)
                    if not got:
                        if cancel.is_set():return
                        yield 'ping',None
                with self.status_lock:
                    self.status['queued']-=1;waiting=False
                    self.status.update(busy=True,phase='reading the prompt',started=started,first_token=None,prompt_tokens=len(ids),generated=0,max_tokens=max_new)
                self.ensure_loaded();self.rate.clear()
                # Same existing FIFO/control/child lifecycle, fresh Codec per retry.
                for attempt in range(2):
                    transport={};session=None;pending=[];call_parts={};terminal_chunks=[]
                    stream=self.engine.frames(ids,max_new,native,cancel,transport)
                    try:
                        for line in stream:
                            if line is None:yield 'ping',None;continue
                            frame=json.loads(line)
                            if frame['kind']=='begin':
                                context={k:frame[k]for k in codec._dto.CONTEXT}
                                expected_cookie=transport['cookie']
                                if(context['request_id'],context['runtime_epoch'])!=expected_cookie:raise codec.CodecError('normal request context mismatch')
                                def stop_recipe():self.engine._send_stop('recipe_stop',expected_cookie)
                                session=codec.CodecSession(context,prepared,self.tok.recipe,on_recipe_stop=stop_recipe,cancelled=cancel.is_set)
                            if session is None:raise codec.CodecError('normal producer omitted begin')
                            for chunk in session.feed(line):
                                for choice in chunk.get('choices',[]):
                                    if choice.get('finish_reason')is not None:terminal_chunks.append(chunk)
                                    delta=choice.get('delta',{})
                                    for key,kind in(('content','content'),('reasoning_content','reasoning')):
                                        if delta.get(key):
                                            with self.status_lock:
                                                if self.status.get('first_token')is None:self.status['first_token']=time.time()
                                            yield 'event',server.Event(kind,delta[key])
                                    if choice.get('logprobs'):yield 'logprobs',choice['logprobs']
                                    for tc in delta.get('tool_calls',[]):
                                        index=tc.get('index',0);part=call_parts.setdefault(index,{'id':'','name':'','arguments':''});part['id']=tc.get('id')or part['id'];fn=tc.get('function',{});part['name']+=fn.get('name','');part['arguments']+=fn.get('arguments','')
                            generated=len(session.dto.ids)
                            with self.status_lock:self.status['generated']=generated
                        if session is None:
                            if cancel.is_set():raise server.ClientGone()
                            raise codec.CodecError('missing native generation')
                        complete=session.end_of_stream();raw=complete['raw']
                        if raw['finish']=='nonfinite'and not generated and attempt==0:continue
                        if not complete['success']:
                            if raw['finish']=='nonfinite':raise server.EngineNonFinite('native nonfinite generation')
                            if raw['finish']not in('cancel',):raise codec.CodecError('unsuccessful native generation: '+str(raw['finish']))
                            failure=raw['finish'];break
                        if cancel.is_set():failure='cancel';break
                        # Commit completed tools only after raw terminal/DONE/cancel check.
                        for part in complete['response']['choices'][0]['message'].get('tool_calls',[]):
                            function=part['function'];arguments=json.loads(function['arguments']);yield 'event',server.Event('tool_call',call=ToolCall(function['name'],arguments,part['id']))
                        break
                    finally:
                        stream.close()
                        if session and not session.closed:session.close()
                if raw is None:raise codec.CodecError('native terminal missing')
                if cancel.is_set()or failure=='cancel':raise server.ClientGone()
                finish=complete['normalized_finish']or raw['finish']
                yield 'done',dict(finish=finish,completion_tokens=generated,reused=0,timings=None,reasoning_tokens=0,reasoning_recoveries=0)
            finally:
                if got:self.fifo.release()
                with self.status_lock:
                    if waiting:self.status['queued']-=1
                    self.status['busy']=False
                    self.totals['requests']+=int(got);self.totals['prompt_tokens']+=len(ids)if got else 0;self.totals['output_tokens']+=generated
                    if got:self.history.append(dict(time=started,duration_s=time.time()-started,prompt_tokens=len(ids),output_tokens=generated,finish=raw['finish']if raw else'error'))
                self.last_request_at=time.time()
    server.StrataEngine=DeepSeekEngine;server.Service=DeepSeekService
    return True
