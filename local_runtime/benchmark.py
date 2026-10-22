"""Fixed synthetic T1/T2 screen, not the quality or full acceptance suite."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from tools.strata_tokenizer import Tokenizer
from serve.frontend import ChatTemplate

LENGTHS = (('short',256,120),('4k',4096,600),('32k',32768,1800))
INSTRUCTION = ('\nTask: Write a numbered list of 200 detailed observations about the document. '
               'Keep writing until item 200; do not summarize or stop early.\n')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def prompts(tokenizer_path):
    directory = Path(tokenizer_path)
    vocab = json.loads((directory/'vocab.json').read_text(encoding='utf-8'))
    tokens = [None]*len(vocab)
    for word,index in vocab.items():
        tokens[index] = word
    tokenizer = Tokenizer(tokens,(directory/'merges.txt').read_text(encoding='utf-8').split('\n'),
                          json.loads((directory/'token_type.json').read_text(encoding='utf-8')))
    template = ChatTemplate(directory/'chat_template.jinja')
    def encode(content):
        return tokenizer.encode(template.render([dict(role='user',content=content)],enable_thinking=False),
                                parse_special=True)
    overhead = len(encode(INSTRUCTION))
    result = []
    for name,target,deadline in LENGTHS:
        content = ' information'*(target-overhead-1)+INSTRUCTION
        encoded = encode(content)
        if len(encoded) != target:
            raise RuntimeError('Fixed screen tokenizer/template no longer produces the exact target')
        result.append(dict(name=name,content=content,prompt_tokens=target,initial_deadline_seconds=deadline,
                           input_sha256=sha(content.encode('utf-8')),
                           token_sha256=sha(json.dumps(encoded,separators=(',',':')).encode('ascii'))))
    return result


def protocol(cases):
    return dict(version=1,max_tokens=128,seed=42,temperature=0,top_k=1,top_p=1,min_p=0,
                reasoning_effort='none',prompt_cache=0,warmups_per_length=1,measured_per_length=3,
                cases=[{key:row[key] for key in ('name','prompt_tokens','input_sha256','token_sha256',
                                                 'initial_deadline_seconds')} for row in cases],
                purpose='synthetic throughput screen only; no quality or adoption claim')


def requests(cases,suite):
    if suite == 'diagnostic':
        return [dict(phase='diagnostic',case=case,repeat=0) for case in cases]
    if suite != 'screen':
        raise RuntimeError('Unsupported screen suite')
    return ([dict(phase='warmup',case=case,repeat=0) for case in cases]+
            [dict(phase='measured',case=case,repeat=repeat) for case in cases for repeat in range(1,4)])


def validate_sample(sample,case,log):
    reasons = []
    usage,timings = sample.get('usage',{}),sample.get('timings',{})
    if (usage.get('prompt_tokens') != case['prompt_tokens'] or timings.get('prompt_n') != case['prompt_tokens']
            or usage.get('completion_tokens') != 128 or timings.get('predicted_n') != 128
            or sample.get('finish_reason') != 'length'):
        reasons.append('exact input/output token counts or length finish missing')
    if usage.get('prompt_tokens_details',{}).get('cached_tokens') != 0 or timings.get('cache_n') != 0:
        reasons.append('nonzero or missing API cached tokens')
    matched = re.findall(r'prompt (\d+) tokens = (\d+) reused \+ (\d+) read',log)
    if matched != [(str(case['prompt_tokens']),'0',str(case['prompt_tokens']))]:
        reasons.append('one fresh engine-log sample with zero reused tokens required')
    if sample.get('reasoning') or not sample.get('text'):
        reasons.append('reasoning must be empty and answer nonempty')
    values = [sample.get('wall_seconds'),sample.get('first_sse_seconds'),sample.get('first_answer_seconds')]
    values.extend(timings.get(key) for key in ('prompt_ms','prompt_per_second','predicted_ms','predicted_per_second'))
    if any(type(value) not in (float,int) or not math.isfinite(value) or value < 0 for value in values):
        reasons.append('missing/nonfinite/negative timing')
    elif any(value <= 0 for value in (sample['wall_seconds'],sample['first_answer_seconds'],
                                      timings['prompt_per_second'],timings['predicted_per_second'])):
        reasons.append('positive wall/answer/throughput required')
    return reasons


def summarize(rows):
    result = {}
    for name,_,_ in LENGTHS:
        samples = [row['sample'] for row in rows if row['phase'] == 'measured' and row['case'] == name and row['valid']]
        if len(samples) != 3:
            raise RuntimeError('A complete valid three-sample screen is required')
        result[name] = {key:statistics.median(sample[key] for sample in samples)
                        for key in ('wall_seconds','first_sse_seconds','first_answer_seconds')}
        result[name].update({key:statistics.median(sample['timings'][key] for sample in samples)
                             for key in ('prompt_ms','prompt_per_second','predicted_ms','predicted_per_second')})
        result[name]['measured_samples'] = 3
    return result


def tuning_observation(log):
    return dict(enabled=re.findall(r'hipBLASLt tuning enabled \((\d+) rows, ([^,]+), version (\d+)\)',log),
                summaries=[dict(launches=int(a),fallbacks=int(b),unique_fallback_shapes=int(c)) for a,b,c in
                    re.findall(r'hipBLASLt summary launches=(\d+) fallbacks=(\d+) unique_fallback_shapes=(\d+)',log)],
                lines=[line for line in log.splitlines() if 'prefill gemm:' in line],
                performance_use='diagnostic only; verbose suite excluded from timing comparison')
