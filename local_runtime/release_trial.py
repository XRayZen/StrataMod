"""Finite, source-bound Windows prompt trial; never changes normal selection."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time

from . import manifest as m, release_revision as release

FLAGS=('STRATA_HIP_WMMA','STRATA_PF_FUSED')
ARMS={'U':{},'00':dict(zip(FLAGS,('0','0'))),'10':dict(zip(FLAGS,('1','0'))),
      '01':dict(zip(FLAGS,('0','1'))),'11':dict(zip(FLAGS,('1','1')))}
ORDER=(('U','00','10','01','11'),('00','10','01','11','U'),('10','01','11','U','00'))
LIMITS=dict(starts=15,requests=45,request_seconds=120,max_tokens=128,rounds=3)


def sha(data):return hashlib.sha256(data).hexdigest()


def cases(tokenizer_path):
    from tools.strata_tokenizer import Tokenizer
    from serve.frontend import ChatTemplate
    directory=Path(tokenizer_path);vocab=m.read_json(directory/'vocab.json');tokens=[None]*len(vocab)
    for word,index in vocab.items():tokens[index]=word
    tok=Tokenizer(tokens,(directory/'merges.txt').read_text(encoding='utf-8').split('\n'),m.read_json(directory/'token_type.json'))
    template=ChatTemplate(directory/'chat_template.jinja')
    def encode(text):return tok.encode(template.render([dict(role='user',content=text)]),parse_special=True)
    instruction=('\nRecord ALPHA=7419 and BETA=2307. Python fragment: def total(a,b): return a+b. '
                 'Report ALPHA, BETA, total(7,9), and one sentence explaining the function.\n')
    result=[]
    for name,target in (('4k',4096),('20k',20480)):
        count=target-len(encode(instruction));text=' information'*count+instruction
        # Template suffix/token merges may contribute one boundary token.
        for _ in range(5):
            ids=encode(text)
            if len(ids)==target:break
            count+=target-len(ids);text=' information'*count+instruction
        if len(ids)!=target:raise RuntimeError('Trial exact prompt token length unavailable')
        result.append(dict(name=name,content=text,prompt_tokens=target,input_sha256=sha(text.encode()),
                           token_sha256=sha(json.dumps(ids,separators=(',',':')).encode())))
    return result


def prepare(n,directory):
    directory=m.local_path(Path(directory));directory.mkdir(parents=True,exist_ok=False)
    pointer,value=n.selected()
    if 'release_revision' not in value:raise RuntimeError('Trial requires the new release authority')
    cfg=m.read_json(value['profile']);protocol=cases(cfg['tokenizer'])
    result=dict(version=1,kind='release-prompt-trial',source=release.revision(),sources=n.source_files(),
        normal_receipt=pointer,profile_sha256=value['profile_sha256'],release_revision=value['release_revision'],
        arms=ARMS,order=[list(r) for r in ORDER],limits=LIMITS,common_prompt_cache=0,normal_prompt_cache=6,
        fixture=protocol,warmup='A separate warmup: name the three primary colors.',
        additional_rounds='only if all pilot arms comparable and protection/cleanup errors absent')
    path=directory/'manifest.json';n.write(path,result)
    return dict(manifest=str(path),sha256=m.digest(path))


def validate(n,trial,pointer,value):
    path=m.local_path(Path(trial['manifest']));n.no_links(path)
    if (path.parent/'aborted.json').exists():raise RuntimeError('Trial stopped after an incomplete/invalid request; no continuation')
    if m.digest(path)!=trial['sha256']:raise RuntimeError('Exact trial manifest changed')
    fixed=m.read_json(path)
    if (fixed.get('kind')!='release-prompt-trial' or fixed.get('version')!=1 or fixed.get('limits')!=LIMITS
            or fixed.get('arms')!=ARMS or fixed.get('order')!=[list(r) for r in ORDER]
            or fixed.get('common_prompt_cache')!=0 or fixed.get('normal_prompt_cache')!=6):raise RuntimeError('Finite trial protocol changed')
    if fixed.get('source')!=release.revision() or fixed.get('sources')!=n.source_files():raise RuntimeError('Trial source changed')
    if fixed.get('normal_receipt')!=pointer or fixed.get('profile_sha256')!=value['profile_sha256'] or fixed.get('release_revision')!=value.get('release_revision'):
        raise RuntimeError('Trial normal/closure/fullproof authority changed')
    if fixed.get('fixture')!=cases(m.read_json(value['profile'])['tokenizer']):raise RuntimeError('Trial prompt bytes/token IDs changed')
    index=trial.get('index')
    if type(index) is not int or not 0<=index<15:raise RuntimeError('Trial start index outside fixed budget')
    return fixed


def config(n,trial,pointer,value,cfg):
    fixed=validate(n,trial,pointer,value);index=trial['index'];arm=ORDER[index//5][index%5]
    directory=Path(trial['manifest']).parent
    if index:
        prior=directory/f'completion-{index-1}.json'
        if not prior.is_file() or m.read_json(prior).get('complete') is not True:raise RuntimeError('Previous trial request/cohort did not complete')
    if index>=5:
        pilot=directory/'pilot-comparable.json'
        if not pilot.is_file() or m.read_json(pilot)!=dict(all_arms_comparable=True,cleanup_errors=0):
            raise RuntimeError('Additional rounds require every pilot arm comparable and cleanup proved')
    with (directory/f'start-{index}.claim').open('x',encoding='utf-8') as f:f.write(str(time.time()))
    result=copy.deepcopy(cfg);result['env']=dict(ARMS[arm])
    result['args']=n.cal.with_arg(result['args'],'--prompt-cache','0')
    return result


def body(content,*,quantitative=False):
    result=dict(model=m.MODEL,messages=[dict(role='user',content=content)],stream=True,stream_options=dict(include_usage=True))
    if quantitative:result.update(max_tokens=128,seed=42,temperature=0,top_k=1,top_p=1,min_p=0)
    return result


def client_ready(n,state):
    """Read existing normal client authority; never grant start/stop/Job rights.

    The foreground owner retains its Job handle and continuous checks. A separate
    client uses normal.status's immutable authority/birth/argv/listener checks.
    """
    observed=n.status()
    if (observed.get('running') is not True or observed.get('state')!=state
            or state.get('phase')!='ready' or state.get('request_cleanup_pending')):
        raise RuntimeError('Read-only client runtime identity/state changed; no request permitted')
    fixed=n.authority(state);pointer=m.read_json(n.SELECTION)
    if pointer.get('receipt')!=fixed['receipt'] or pointer.get('sha256')!=fixed['receipt_sha256']:
        raise RuntimeError('Read-only client normal receipt selection changed')
    health=observed.get('health',{})
    if not (health.get('service')=='strata' and health.get('status')=='ok' and health.get('loaded') is True
            and health.get('model')==m.MODEL and health.get('max_context')==m.CONTEXT):
        raise RuntimeError('Read-only client health/model/context changed')
    models=n.safety.get_json('/v1/models').get('data',[])
    if len(models)!=1 or models[0].get('id')!=m.MODEL or models[0].get('meta',{}).get('n_ctx')!=m.CONTEXT or models[0].get('status',{}).get('value')!='loaded':
        raise RuntimeError('Read-only client model list changed')
    return observed


def reserve_request(n,state,trial):
    pointer,value=n.selected();fixed=validate(n,trial,pointer,value)
    directory=Path(trial['manifest']).parent;index=trial['index']
    if not (directory/f'start-{index}.claim').is_file():raise RuntimeError('Trial was not started through its finite authority')
    authority=n.authority(state)
    if authority.get('trial')!=trial:raise RuntimeError('Request trial differs from immutable launch authority')
    cfg=authority['snapshot_config'];base=m.read_json(value['profile'])
    expected=copy.deepcopy(base);expected['log']=cfg['log'];expected['vision']['temp_dir']=cfg['vision']['temp_dir']
    expected['env']=dict(ARMS[ORDER[index//5][index%5]])
    expected['args']=n.cal.with_arg(expected['args'],'--prompt-cache','0')
    if cfg!=expected:raise RuntimeError('Trial effective snapshot differs from exact arm')
    for slot in range(3):
        path=directory/f'request-{index}-{slot}.claim'
        if slot:
            prior=directory/f'request-{index}-{slot-1}.sample.json'
            if not prior.exists() or m.read_json(prior).get('valid') is not True:
                raise RuntimeError('Previous request has no complete valid result')
        try:
            with path.open('x',encoding='utf-8') as f:f.write(str(time.time()))
        except FileExistsError:continue
        content=fixed['warmup'] if slot==0 else fixed['fixture'][slot-1]['content']
        return slot,content
    raise RuntimeError('Trial three-request budget exhausted')


def request(n,state,monitor,content,*,quantitative=False,trial=None):
    """Uses the existing socket shutdown/join implementation, preserving partials."""
    if quantitative:
        if trial is None:raise RuntimeError('Quantitative generation requires exact trial authority')
        slot,expected=reserve_request(n,state,trial)
        if content!=expected:raise RuntimeError('Trial fixed request order/content differs')
    sample=dict(submitted_at=time.time(),submitted_monotonic=time.monotonic(),deadline_seconds=120)
    log=Path(state['engine_log']);offset=log.stat().st_size
    sample.update(log_offset=offset,status='failed',valid=False)
    try:
        n.runner.stream_request(state,monitor,content,deadline_s=120,partial=sample,
                                request_body=body(content,quantitative=quantitative),require_answer=not quantitative,
                                ready_check=lambda current:client_ready(n,current))
        sample.update(status='completed',generation_status='completed',censored=False)
        sample['request_release_started_at']=time.time()
        n.runner.wait_request_release(state,ready_check=lambda current:client_ready(n,current))
        sample['request_release_confirmed_at']=time.time()
    except (TimeoutError, OSError) as error:
        timeout=bool(sample.get('timeout_requested_at'))
        generation=sample.get('generation_status','timeout' if timeout else 'failed')
        sample.update(status='timeout' if timeout else ('cleanup_failed' if generation=='completed' else 'failed'),
                      generation_status=generation,censored=timeout,error_type=type(error).__name__)
    finally:
        sample['client_terminal_at']=time.time()
        with log.open('rb') as f:
            f.seek(offset);sample['engine_log_delta']=f.read().decode('utf-8',errors='replace')
        if quantitative:
            fixed=m.read_json(trial['manifest'])
            sample['errors']=(cold_errors(sample,fixed['fixture'][slot-1],sample['engine_log_delta']) if slot else
                              ([] if sample['status']=='completed' else ['Warmup incomplete']))
            sample['valid']=not sample['errors']
            directory=Path(trial['manifest']).parent
            n.write(directory/f'request-{trial["index"]}-{slot}.sample.json',sample)
            if not sample['valid']:n.write(directory/'aborted.json',dict(index=trial['index'],slot=slot,status=sample['status']))
    return sample


def cold_errors(sample,case,log):
    usage=sample.get('usage',{});timings=sample.get('timings',{});errors=[]
    if usage.get('prompt_tokens')!=case['prompt_tokens'] or timings.get('prompt_n')!=case['prompt_tokens']:
        errors.append('Actual prompt token count differs')
    if usage.get('prompt_tokens_details',{}).get('cached_tokens')!=0 or timings.get('cache_n')!=0:
        errors.append('API cache count missing/nonzero')
    expected=[(str(case['prompt_tokens']),'0',str(case['prompt_tokens']))]
    if re.findall(r'prompt (\d+) tokens = (\d+) reused \+ (\d+) read',log)!=expected:
        errors.append('Request log offset does not prove exact cold input')
    if sample.get('status')!='completed' or sample.get('censored'):errors.append('Request incomplete/censored')
    completion=usage.get('completion_tokens')
    if type(completion) is not int or not 0<completion<=128 or timings.get('predicted_n')!=completion:
        errors.append('Actual accepted/output token counts unavailable or outside fixture')
    numbers=[sample.get('first_token_seconds'),sample.get('wall_seconds')]
    numbers.extend(timings.get(k) for k in ('prompt_ms','prompt_per_second','predicted_ms','predicted_per_second'))
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in numbers):
        errors.append('Positive finite TTFT/prefill/decode window required')
    return errors
