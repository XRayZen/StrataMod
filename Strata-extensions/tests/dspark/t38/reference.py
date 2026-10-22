"""Independent bounded CPU oracles, never a draft-network implementation."""
from fractions import Fraction

def decision(p,q,proposal,accept_u,residual_u):
    p=list(map(Fraction,p));q=list(map(Fraction,q))
    if len(p)!=len(q) or not p or sum(p)!=1 or sum(q)!=1 or min(p+q)<0:
        raise ValueError('distribution')
    if not 0<=proposal<len(q) or not q[proposal]:raise ValueError('proposal support')
    a=min(Fraction(1),p[proposal]/q[proposal])
    if Fraction(accept_u)<a:return True,proposal
    r=[max(x-y,0) for x,y in zip(p,q)];total=sum(r)
    if not total:raise ValueError('unreachable residual')
    r=[x/total for x in r];u=Fraction(residual_u);c=0
    for i,x in enumerate(r):
        c+=x
        if u<c:return False,i
    return False,len(r)-1

def path_mass(p,q):
    """Exact enumeration of one-step accepted and rejected probability mass."""
    p=list(map(Fraction,p));q=list(map(Fraction,q));out=[Fraction(0)]*len(p)
    rejected=sum(max(b-a,0) for a,b in zip(p,q))
    residual=[max(a-b,0) for a,b in zip(p,q)];z=sum(residual)
    for i in range(len(p)):out[i]+=min(p[i],q[i])
    if z:
        for i,x in enumerate(residual):out[i]+=rejected*x/z
    return out

def ledger(maximum,ids,eos=1,stop_after=-1):
    emitted=[];processed=[];finish='length' if maximum==0 else 'running'
    if stop_after==0 and maximum>0:return dict(emitted=[],processed=[],cursor=4,pending=[],finish='cancel')
    for token in ids:
        if finish!='running':break
        emitted.append(token)
        if token==eos:finish='eos'
        elif len(emitted)==maximum:finish='length'
        elif len(emitted)==stop_after:finish='cancel'
        if finish!='running':break
        processed.append(token)
    return dict(emitted=emitted,processed=processed,cursor=4+len(processed),pending=emitted[len(processed):],finish=finish)

MASK=(1<<64)-1
class MT64:
    def __init__(self,seed):
        self.s=[seed&MASK]
        for i in range(1,312):self.s.append((6364136223846793005*(self.s[-1]^(self.s[-1]>>62))+i)&MASK)
        self.i=312
    def draw(self):
        if self.i==312:
            for i in range(312):
                x=(self.s[i]&0xffffffff80000000)|(self.s[(i+1)%312]&0x7fffffff)
                self.s[i]=self.s[(i+156)%312]^(x>>1)^(0xb5026f5aa96619e9 if x&1 else 0)
            self.i=0
        y=self.s[self.i];self.i+=1
        y^=(y>>29)&0x5555555555555555;y^=(y<<17)&0x71d67fffeda60000;y^=(y<<37)&0xfff7eee000000000;y^=y>>43
        return y&MASK

def mix(z):
    z=((z^(z>>30))*0xbf58476d1ce4e5b9)&MASK
    z=((z^(z>>27))*0x94d049bb133111eb)&MASK
    return z^(z>>31)


# Numerical Q additions: independent CPU formulas. Provenance is T04
# tests/numerics/reference.py FP32/BF16, T11 tests/ffn/reference.py router,
# and T37 tests/dspark/reference.py finite F16/HC/confidence contracts.
# No candidate decoder, HIP, wave planner or candidate output is imported.
import math
import struct


def f32(value):
    """IEEE binary32 round-to-nearest-even; keep gradual underflow and -0."""
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def f32_word(value):
    return struct.unpack('<I', struct.pack('<f', f32(value)))[0]


def bf16(value):
    word = f32_word(value)
    if word & 0x7f800000 == 0x7f800000:
        raise ValueError('finite BF16 source required')
    rounded = ((word + 0x7fff + ((word >> 16) & 1)) & 0xffffffff) & 0xffff0000
    return struct.unpack('<f', struct.pack('<I', rounded))[0]


def f16_widen_bits(word):
    """Independent IEEE format formula, with raw NaN payload words preserved.

    Finite values use an exact integer significand and power of two, then a
    lossless binary32 representation. This is F16->F32, never BF16->F16.
    """
    if type(word) is not int or not 0 <= word <= 65535:
        raise ValueError('F16 word')
    sign, exponent, fraction = word >> 15, (word >> 10) & 31, word & 1023
    if exponent == 31:
        return (sign << 31) | 0x7f800000 | (fraction << 13)
    magnitude = (math.ldexp(fraction, -24) if exponent == 0 else
                 math.ldexp(1024 + fraction, exponent - 25))
    return f32_word(math.copysign(magnitude, -1. if sign else 1.))


def decode_f16(raw, finite=True):
    if not isinstance(raw, bytes) or not raw or len(raw) % 2:
        raise ValueError('complete nonempty F16 bytes')
    words = struct.unpack('<' + 'H' * (len(raw) // 2), raw)
    widened = [f16_widen_bits(word) for word in words]
    if finite and any((word & 0x7f800000) == 0x7f800000 for word in widened):
        raise ValueError('nonfinite F16 model source')
    return [struct.unpack('<f', struct.pack('<I', word))[0] for word in widened]


def _finite(values):
    rounded = [f32(v) for v in values]
    if not rounded or not all(math.isfinite(v) for v in rounded):
        raise ValueError('nonempty finite FP32 values')
    return rounded


def ordered_dot(weights, inputs):
    """+0 then ascending-K separate FP32 product/add, with no QDQ/FMA."""
    if not weights or len(weights) != len(inputs):
        raise ValueError('full-K dot shape')
    w, x = _finite(weights), _finite(inputs)
    accum = 0.0
    for a, b in zip(w, x):
        product = f32(a * b)
        accum = f32(accum + product)
    if not math.isfinite(accum):
        raise ValueError('nonfinite model dot result')
    return accum


def projection_rows(weights, inputs):
    if not weights or not inputs:
        raise ValueError('projection geometry')
    return [[ordered_dot(row, x) for row in weights] for x in inputs]


def hc_mean(hc, hidden=5120):
    if type(hidden) is not int or hidden < 1 or len(hc) != 4 or any(len(h) != hidden for h in hc):
        raise ValueError('HC4 mean shape')
    source = [_finite(h) for h in hc]
    result = []
    for i in range(hidden):
        total = 0.0
        for h in range(4):
            total = f32(total + source[h][i])
        result.append(bf16(f32(total * .25)))
    return result


def raw_confidence(hidden, markov, weights):
    """Unnormalized HC-pre collapsed5120 + prior-ID Markov256; no sigmoid."""
    if len(hidden) != 5120 or len(markov) != 256 or len(weights) != 5376:
        raise ValueError('confidence concat5376 geometry')
    return ordered_dot(weights, list(hidden) + list(markov))


def router128(logits, learned_bias):
    """T11 formula specialized independently to draft128/top3.

    Stable minimum-ID ties define native Q only, not Torch topk tie order.
    Bias selects; only original unbiased scores determine route weights.
    """
    if len(logits) != 128 or len(learned_bias) != 128:
        raise ValueError('draft128 router geometry')
    x, bias = _finite(logits), _finite(learned_bias)
    softplus = [z if z > 20. else f32(math.log1p(math.exp(z))) for z in x]
    scores = [f32(math.sqrt(v)) for v in softplus]
    corrected = [f32(a + b) for a, b in zip(scores, bias)]
    if not all(math.isfinite(v) for v in corrected):
        raise ValueError('nonfinite corrected route score')
    ids = sorted(range(128), key=lambda i: (-corrected[i], i))[:3]
    denominator = 0.0
    for i in ids:
        denominator = f32(denominator + scores[i])
    denominator = f32(denominator + f32(1e-20))
    weights = [f32(f32(scores[i] / denominator) * 1.5) for i in ids]
    return dict(ids=ids, weights=weights, scores=scores, corrected=corrected,
                softplus=softplus, denominator=denominator)


def noise_input_ids(previous, width):
    if type(previous) is not int or not 0 <= previous < 129280 or type(width) is not int or width < 1:
        raise ValueError('noise input original ID/width')
    return [previous] + [128799] * (width - 1)


def noise_attention_indices(position, width):
    if type(position) is not int or position < 1 or type(width) is not int or width < 1:
        raise ValueError('start0 seeds only; positive proposal width/position')
    return list(range(min(128, position + 1))) + list(range(128, 128 + width))


def seed_ring_bytes(ring, key, position):
    if not isinstance(ring, bytes) or len(ring) != 128 * 512 * 4 or not isinstance(key, bytes) or len(key) != 512 * 4 or type(position) is not int or position < 0:
        raise ValueError('exact ring128/key512 bytes/position')
    first = (position % 128) * len(key)
    return ring[:first] + key + ring[first + len(key):]

