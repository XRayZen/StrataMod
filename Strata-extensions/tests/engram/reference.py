"""Independent integer N/Q and source-specific MXFP8 oracle, never G-derived."""
import hashlib
import json
import math
import struct
import numpy as np

def compressed_map(path):
    from tokenizers import Tokenizer, Regex, normalizers
    tok=Tokenizer.from_file(str(path));sentinel='\ue000'
    norm=normalizers.Sequence([normalizers.NFKC(),normalizers.NFD(),normalizers.StripAccents(),normalizers.Lowercase(),
        normalizers.Replace(Regex(r'[ \t\r\n]+'),' '),normalizers.Replace(Regex(r'^ $'),sentinel),normalizers.Strip(),normalizers.Replace(sentinel,' ')])
    keys={};result=[];fallback=invalid=0
    for i in range(tok.get_vocab_size(with_added_tokens=True)):
        text=tok.decode([i],skip_special_tokens=False)
        if '\ufffd' in text:key=tok.id_to_token(i);invalid+=1
        else:
            normalized=norm.normalize_str(text)
            key=normalized or text
            if not normalized:fallback+=1
        result.append(keys.setdefault(key,len(keys)))
    return result,len(keys),dict(empty_normalization_fallback=fallback,invalid_UTF8_raw_spelling=invalid)

def constants():
    seen=set();primes=[]
    def prime(n):
        return n>=2 and all(n%d for d in range(2,math.isqrt(n)+1))
    for layer in [1,14]:
        for ngram in range(3):
            n=15999999
            for head in range(8):
                n+=1
                while n in seen or not prime(n):n+=1
                seen.add(n);primes.append(n)
    bound=((1<<63)-1)//99092//2
    mult=[int(x) for layer in [1,14] for x in np.random.default_rng(10007*layer).integers(0,bound,4,dtype=np.int64)*2+1]
    offsets=[];total=0
    for p in primes:offsets.append(total);total+=p
    return mult,primes,offsets

def hashes(raw,mask,tm,mult,primes,offsets):
    # Separate scalar traversal: start/dead accumulates across all older slots.
    compressed=[tm[x] if live else -1 for x,live in zip(raw,mask)];out=[]
    for pos in range(len(raw)):
        history=[];blocked=False
        for shift in range(4):
            blocked=blocked or pos<shift or compressed[pos-shift]==-1
            history.append(tm[2] if blocked else compressed[pos-shift])
        rows=[]
        for layer in range(2):
            value=history[0]*mult[layer*4]
            for n in range(1,4):
                value^=history[n]*mult[layer*4+n]
                for head in range(8):
                    j=layer*24+(n-1)*8+head;rows.append(value%primes[j]+offsets[j])
        out.append(rows)
    return out

def tuples(raw,tm,mult,primes,offsets):
    result=[]
    for pos,rows in enumerate(hashes(raw,[True]*len(raw),tm,mult,primes,offsets)):
        for li,layer in enumerate([1,14]):
            for n in range(3):
                for h in range(8):
                    j=li*24+n*8+h;global_row=rows[j]
                    result.append([pos,layer,n+2,h,global_row-offsets[j],global_row])
    return result

def tuple_sha(value):return hashlib.sha256(json.dumps(value,separators=(',',':')).encode()).hexdigest()

def decode(raw):
    if len(raw)%264:raise ValueError('native row bytes')
    result=[]
    for block in range(0,len(raw),33):
        exponent=raw[block]
        scale=math.ldexp(1.,exponent-127) if exponent<255 else math.inf
        for c in raw[block+1:block+33]:
            e=(c>>3)&15;m=c&7
            v=math.nan if e==15 and m==7 else math.ldexp(m,-9) if e==0 else math.ldexp(8+m,e-10)
            if c&128:v=-v
            # Materialize FP32 scale before the FP32 product, including e255.
            with np.errstate(invalid='ignore',over='ignore'):
                result.append(np.float32(v)*np.float32(scale))
    return np.asarray(result,dtype='<f4')

def bf16(values):
    bits=np.asarray(values,dtype='<f4').view('<u4');result=[]
    for x in bits:
        x=int(x)
        result.append(((x>>16)|0x40) if (x&0x7fffffff)>0x7f800000 else ((x+0x7fff+((x>>16)&1))>>16)&0xffff)
    return np.asarray(result,dtype='<u2')

def literals():
    return b''.join(bytes([e])+bytes(range(block*32,(block+1)*32)) for e in [0,1,126,127,128,254,255] for block in range(8))

def selftest():
    # Independent literal holdout: exact E4M3 codes and RNE ties.
    x=np.array([1.,-0.,1.+2**-8,1.+3*2**-8],dtype='<f4')
    assert bf16(x).tolist()==[0x3f80,0x8000,0x3f80,0x3f82]
    r=bytes([127])+bytes([0,128,56,184]+[0]*28)
    assert decode(r*8).view('<u4')[:4].tolist()==[0,0x80000000,0x3f800000,0xbf800000]
    m,p,o=constants();tm=list(range(129280))
    a=hashes([3,4,5,6],[1,1,0,1],tm,m,p,o)
    b=hashes([6],[1],tm,m,p,o)
    assert a[-1]==b[-1]
    assert len(p)==48 and len(set(p))==48 and all(x&1 for x in m)
    return 7
