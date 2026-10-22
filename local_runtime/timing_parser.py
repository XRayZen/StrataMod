"""Strict stock prefill event-timer parser, scoped to one saved request delta."""
import math
import re

PHASES=('embed+steps','hc read','gdn','qsa proj','qsa indexer','qsa select','qsa attn','router+shared',
        'host grouping','gather','wait copy','dequant','gemm gate/up','gemm down','combine','ple','kv stage',
        'gdn conv+gates','gdn recurrence','gdn out proj','hc write')
HEADER=re.compile(r'^strata prefill timing: (\S+) tokens, GPU timeline (\S+) ms, wall (\S+) ms, host staging (\S+) ms:(.*)$')
HOST=re.compile(r'^strata prefill timing: host: chunk setup \(PLE rows, the expert stream plan\) (\S+) ms, waiting for each chunk (\S+) ms, after each chunk \(the draft layer, progress\) (\S+) ms, PLE (\S+) ms$')
PHASE=re.compile(r'\s+('+'|'.join(re.escape(p) for p in sorted(PHASES,key=len,reverse=True))+r') (\S+) \((\S+)%\)')


class TimingSchemaError(RuntimeError):pass


def number(text):
    try:value=float(text)
    except (TypeError,ValueError):raise TimingSchemaError('Non-numeric stock timing value') from None
    if not math.isfinite(value) or value<0:raise TimingSchemaError('Non-finite/negative stock timing value')
    return value


def parse(log,*,timing,prompt_tokens,quantitative):
    blocks=[];pending=None
    for line_index,line in enumerate(log.splitlines(),1):
        if not line.startswith('strata prefill timing'):continue
        if not timing:raise TimingSchemaError('Timer output exists in timing-unset arm')
        header=HEADER.fullmatch(line);host=HOST.fullmatch(line)
        if header:
            if pending is not None:raise TimingSchemaError('Timer header has no matching host row')
            token,timeline,wall,staging,tail=header.groups()
            if not token.isdecimal() or not 0<int(token)<=prompt_tokens:raise TimingSchemaError('Timer token count outside request scope')
            phases={p:None for p in PHASES};percent={};pos=0
            while pos<len(tail):
                match=PHASE.match(tail,pos)
                if match is None:raise TimingSchemaError('Stock phase schema changed or malformed')
                name,ms,pct=match.groups()
                if name in percent:raise TimingSchemaError('Duplicate stock timer phase')
                phases[name]=number(ms);percent[name]=number(pct)
                if percent[name]>100:raise TimingSchemaError('Stock phase fraction outside [0,100]')
                pos=match.end()
            gpu=number(timeline)
            if not percent:raise TimingSchemaError('Stock timer contains no phase records')
            if abs(sum(v for v in phases.values() if v is not None)-gpu)>(len(percent)+1)*.51+1:
                raise TimingSchemaError('Rounded phase values disagree with GPU timeline')
            pending=dict(tokens=int(token),gpu_timeline_ms=gpu,wall_ms=number(wall),host_staging_ms=number(staging),
                         phases_ms=phases,phase_percent=percent,header_line=line_index,raw_header=line)
        elif host:
            if pending is None:raise TimingSchemaError('Stock host row has no matching header')
            pending.update(host=dict(zip(('chunk_setup_ms','chunk_wait_ms','after_chunk_ms','ple_ms'),map(number,host.groups()))),
                           host_line=line_index,raw_host=line)
            blocks.append(pending);pending=None
        else:raise TimingSchemaError('Unrecognized stock timing schema')
    if pending is not None:raise TimingSchemaError('Final timer header has no host row')
    total_tokens=sum(b['tokens'] for b in blocks)
    if total_tokens>prompt_tokens:raise TimingSchemaError('Timer blocks exceed current cold input token range')
    if timing and quantitative and not blocks:raise TimingSchemaError('Timed quantitative request has no stock timer blocks')
    return dict(status='measured' if blocks else ('not_observed_warmup' if timing else 'disabled'),
                scope='request log offset; prefill timer blocks, not kernel-exclusive',
                api_prompt_tokens=prompt_tokens,timer_tokens=total_tokens,blocks=blocks,
                gpu_timeline_ms=sum(b['gpu_timeline_ms'] for b in blocks) if blocks else None,
                wall_ms=sum(b['wall_ms'] for b in blocks) if blocks else None,
                host_staging_ms=sum(b['host_staging_ms'] for b in blocks) if blocks else None,
                missing_phase_policy='null/unobserved; never zero-filled',
                overlap_policy='compute event timeline includes exposed waits; do not add host/copy/peer wall')
