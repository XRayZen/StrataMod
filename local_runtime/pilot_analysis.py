"""Offline P1 diagnostic, never a performance-adoption or kernel-coverage claim."""
from . import pilot_authority as a,manifest as m,timing_parser


def summarize(ctx,fixed):
    samples=[];runs=[];stock=[]
    for index,arm in enumerate(a.ORDER):
        completion=ctx.pilot/f'completion-{index}.json'
        result=ctx.runs/str(index)/'result.json'
        runs.append(dict(index=index,arm=arm,
                         completion=m.read_json(completion) if completion.is_file() else None,
                         result=m.read_json(result) if result.is_file() else None))
        ready=ctx.runs/str(index)/'ready.json'
        if ready.is_file():
            environments=m.read_json(ready)['actual_environment']
            stock.append(dict(index=index,arm=arm,observed_stock_defaults=[r['observed_stock_defaults'] for r in environments],
                              text_observation=environments[0].get('stock_default_observation'),
                              unobserved_names=environments[0].get('unobserved_stock_default_names'),
                              reader_flags=environments[1]['trial_flags']))
        for slot in range(3):
            path=ctx.pilot/f'request-{index}-{slot}.sample.json'
            if not path.exists():continue
            value=m.read_json(path);timings=value.get('timings',{})
            samples.append(dict(index=index,arm=arm,slot=slot,path=str(path),sha256=m.digest(path),status=value['status'],
                valid=value['valid'],censored=value.get('censored'),prompt_tokens=value.get('usage',{}).get('prompt_tokens'),
                ttft_s=value.get('first_token_seconds'),first_answer_s=value.get('first_answer_seconds'),wall_s=value.get('wall_seconds'),
                native_timings=timings,timing=value.get('timing'),errors=value.get('errors'),analysis_error=value.get('analysis_error'),
                accepted_api_requests=(value['metrics_after']['totals']['requests']-value['metrics_before']['totals']['requests'])
                    if 'metrics_after' in value and 'metrics_before' in value else None,
                accepted_tokens=value.get('usage',{}).get('completion_tokens'),finish=value.get('finish_reason'),
                text_chars=len(value.get('text','')),reasoning_chars=len(value.get('reasoning','')),
                answer_completed=value.get('finish_reason')=='stop' and bool(value.get('text'))))
    pairs=[]
    for pair in ((0,1),(3,2)):
        for slot in (1,2):
            off=next((s for s in samples if s['index']==pair[0] and s['slot']==slot),None)
            on=next((s for s in samples if s['index']==pair[1] and s['slot']==slot),None)
            row=dict(flags=a.ORDER[pair[0]][:2],slot=slot,n_each=1,valid=bool(off and on and off['valid'] and on['valid']))
            if row['valid']:
                for label,old,new in (
                    ('native_prompt_ms',off['native_timings']['prompt_ms'],on['native_timings']['prompt_ms']),
                    ('request_wall_s',off['wall_s'],on['wall_s']),('ttft_s',off['ttft_s'],on['ttft_s'])):
                    row[label]=dict(off=old,on=new,relative_on_minus_off=(new/old-1) if old else None)
            pairs.append(row)
    stock_equal=len(stock)==4 and all(r['observed_stock_defaults']==stock[0]['observed_stock_defaults'] and not r['reader_flags'] for r in stock)
    complete=(len(samples)==12 and all(s['valid'] for s in samples) and stock_equal and all(r['completion'] and r['completion'].get('complete') is True for r in runs))
    return dict(kind=a.KIND,source=fixed['source'],limits=a.LIMITS,
                reservations=dict(starts=sum((ctx.pilot/f'start-{i}.claim').exists() for i in range(4)),
                    requests=sum((ctx.pilot/f'request-{i}-{s}.claim').exists() for i in range(4) for s in range(3))),
                saved_samples=len(samples),
                actual_requests=sum(s['accepted_api_requests'] or 0 for s in samples),
                actual_request_evidence='Server metrics acceptance deltas; transport bytes/rejected HTTP attempts are not independently counted',
                request_count_unconfirmed_slots=[dict(index=i,slot=s) for i in range(4) for s in range(3)
                    if (ctx.pilot/f'request-{i}-{s}.claim').exists() and not any(v['index']==i and v['slot']==s and v['accepted_api_requests'] is not None for v in samples)],
                actual_starts=sum(bool(r['result'] and r['result'].get('server_popen')) for r in runs),
                complete=complete,samples=samples,runs=runs,timing_on_off_pairs=pairs,
                stock_defaults=dict(arms=stock,all_four_equal=stock_equal,
                    pair_equal={label:len(stock)==4 and stock[off]['observed_stock_defaults']==stock[on]['observed_stock_defaults'] for label,off,on in (('00',0,1),('11',3,2))},
                    historical_evidence='Old 15/45 actual_environment extracted two trial flags only; five default values were not directly collected then'),
                normal_performance_settings_adopted=False,native_builds=0,new_kernels=0,
                interpretation='n=1 diagnostic pilot; event phases include exposed waits and do not prove actual WMMA dispatch; file_mb is principally decode interval',
                phase_names=list(timing_parser.PHASES),quality='128-token speed fixture; length-limited/incomplete answers are not quality passes',
                later_stages='P1b/RGP/P2+ not authorized or run')
