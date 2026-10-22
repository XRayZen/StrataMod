"""Small strict numerical wrapper. Missing rows never become a shorter PASS."""
import math
import struct


def validate_manifest(row):
    shape=row.get('shape')
    if not isinstance(shape,list) or len(shape)!=2 or not all(type(d) is int and d>0 for d in shape):
        raise ValueError('invalid shape integer contract')
    for key in ('token_ids','positions','next_token_ids'):
        values=row.get(key)
        if not isinstance(values,list) or len(values)!=shape[0] or not all(type(v) is int and v>=0 for v in values):
            raise ValueError('invalid token/position integer contract')
        if key!='positions' and any(v>=shape[1] for v in values):
            raise ValueError('token outside declared vocabulary')
    if type(row.get('bos_shift')) is not int or not isinstance(row.get('dtype'),str) or not row['dtype']:
        raise ValueError('invalid BOS/dtype contract')
    values=row.get('values')
    if (not isinstance(values,list) or len(values)!=math.prod(shape)
            or not all(type(v) in (int,float) and math.isfinite(v) for v in values)):
        raise ValueError('empty/truncated/nonfinite payload')


def compare(expected, observed, tolerance):
    validate_manifest(expected)
    validate_manifest(observed)
    for key in ('shape','dtype','token_ids','positions','next_token_ids','bos_shift'):
        if key not in expected or expected[key] != observed.get(key):
            raise ValueError('expected manifest mismatch: ' + key)
    shape=expected['shape']
    if not isinstance(shape,list) or not shape or not all(type(d) is int and d>0 for d in shape):
        raise ValueError('invalid expected shape')
    if len(shape)!=2 or any(not isinstance(expected[k],list) or len(expected[k])!=shape[0]
                            for k in ('token_ids','positions','next_token_ids')):
        raise ValueError('expected token/position coverage mismatch')
    if (any(type(v) is not int or v<0 for k in ('token_ids','positions','next_token_ids') for v in expected[k])
            or any(v>=shape[1] for k in ('token_ids','next_token_ids') for v in expected[k])
            or type(expected['bos_shift']) is not int):
        raise ValueError('invalid expected token vocabulary/position/BOS contract')
    count=math.prod(shape)
    x,y=expected['values'],observed.get('values',[])
    if len(x)!=count or len(y)!=count or not all(math.isfinite(v) for v in x+y):
        raise ValueError('empty, truncated or nonfinite numerical payload')
    if not all(k in tolerance and math.isfinite(tolerance[k]) and tolerance[k]>=0
               for k in ('atol','rtol','max_nrmse','zero_norm_atol')):
        raise ValueError('invalid tolerance contract')
    errors=[abs(a-b) for a,b in zip(x,y,strict=True)]
    squared_error=sum(e*e for e in errors)
    squared_norm=sum(v*v for v in x)
    if not math.isfinite(squared_error) or not math.isfinite(squared_norm):
        raise ValueError('nonfinite derived metric')
    maximum=max(errors)
    if squared_norm == 0:
        nrmse=0. if maximum<=tolerance['zero_norm_atol'] else math.inf
        within_absolute_relative=maximum<=tolerance['zero_norm_atol']
    else:
        nrmse=math.sqrt(squared_error/squared_norm)
        within_absolute_relative=all(e<=tolerance['atol']+tolerance['rtol']*abs(a)
                                     for e,a in zip(errors,x,strict=True))
    if (not math.isfinite(nrmse) or nrmse>tolerance['max_nrmse']
            or not within_absolute_relative):
        raise ValueError('numerical tolerance failure')
    return dict(max_abs=maximum,nrmse=nrmse,count=count)


def check_selection(case,selected):
    """Validate a declared synthetic rounded-score tie boundary, not a router."""
    scores,mask,candidates,k=(case[name] for name in ('rounded_scores','valid_mask','candidates','top_k'))
    if (not isinstance(scores,list) or not scores or len(mask)!=len(scores)
            or not all(type(v) in (int,float) and math.isfinite(v) for v in scores)
            or not all(type(v) is bool for v in mask)
            or not all(type(i) is int and 0<=i<len(scores) for i in candidates)
            or len(set(candidates))!=len(candidates) or type(k) is not int or k<=0):
        raise ValueError('invalid synthetic score/mask/candidate contract')
    if any(struct.unpack('<f',struct.pack('<f',v))[0]!=v for v in scores):
        raise ValueError('scores must already be rounded to declared FP32')
    active=[i for i in candidates if mask[i]]
    if k>len(active):
        raise ValueError('not enough valid candidates')
    cut=sorted((scores[i] for i in active),reverse=True)[k-1]
    mandatory={i for i in active if scores[i]>cut}
    tied={i for i in active if scores[i]==cut}
    declared_ties=case['allowed_tie_ids'];declared_mandatory=case['mandatory_ids']
    if (not all(type(i) is int for i in declared_ties+declared_mandatory)
            or len(set(declared_ties))!=len(declared_ties) or set(declared_ties)!=tied
            or len(set(declared_mandatory))!=len(declared_mandatory) or set(declared_mandatory)!=mandatory):
        raise ValueError('declared allowed set does not match rounded scores/mask/candidates')
    if (not isinstance(selected,list) or len(selected)!=k or not all(type(i) is int for i in selected)
            or len(set(selected))!=k or not mandatory.issubset(selected)
            or not set(selected).issubset(mandatory|tied)
            or any(scores[a]<scores[b] for a,b in zip(selected,selected[1:]))):
        raise ValueError('selection violates allowed tie boundary/order')
