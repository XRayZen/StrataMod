"""Independent NumPy Q. No candidate native decoder or GPU output is imported."""
import numpy as np

BLOCKS = {0:(1,4),8:(32,34),39:(32,17),43:(32,33)}

def decode(kind, raw):
    if kind not in BLOCKS: raise ValueError('unqualified type')
    count,size = BLOCKS[kind]
    if not raw or len(raw)%size: raise ValueError('partial/empty block')
    if kind == 0: return np.frombuffer(raw,dtype='<f4').copy()
    data = np.frombuffer(raw,dtype=np.uint8).reshape(-1,size)
    with np.errstate(all='ignore'):
        if kind == 8:
            scales = data[:,:2].copy().reshape(-1).view('<f2').astype(np.float32)
            values = data[:,2:].copy().view(np.int8).astype(np.float32)
            return np.multiply(scales[:,None],values,dtype=np.float32).reshape(-1)
        if kind == 39:
            codes = np.concatenate((data[:,1:]&15,data[:,1:]>>4),axis=1)
            magnitudes = np.array([0,.5,1,1.5,2,3,4,6],dtype=np.float64)[codes&7]
            values = np.ldexp(magnitudes,data[:,0].astype(np.int32)[:,None]-127)
            values = np.where((codes&8)!=0,-values,values)
            values[codes%8==0] = 0.0
            return values.astype(np.float32).reshape(-1)
        codes = data[:,1:]
        exp,frac = (codes>>3)&15,codes&7
        values = np.where(exp==0,frac.astype(np.float32)/512,
                          np.ldexp(1+frac.astype(np.float32)/8,exp.astype(np.int32)-7)).astype(np.float32)
        values = np.where((codes&128)!=0,-values,values)
        values[(exp==15)&(frac==7)] = np.nan
        scales = np.ldexp(np.ones(len(data),np.float64),data[:,0].astype(np.int32)-127).astype(np.float32)
        return np.multiply(values,scales[:,None],dtype=np.float32).reshape(-1)

def ordered(weights, inputs):
    w,x = np.asarray(weights,dtype=np.float32),np.asarray(inputs,dtype=np.float32)
    if w.ndim!=2 or x.ndim!=2 or w.shape[1]!=x.shape[1] or not w.shape[1]: raise ValueError('shape')
    if not np.isfinite(w).all() or not np.isfinite(x).all(): raise ValueError('nonfinite input')
    result = np.empty((len(x),len(w)),np.float32)
    # One B lane / tiled rows: bounded CPU memory; explicit +0 precedes product0.
    for b in range(len(x)):
        for start in range(0,len(w),64):
            product = np.multiply(w[start:start+64],x[b],dtype=np.float32)
            accum = np.cumsum(np.concatenate((np.zeros((len(product),1),np.float32),product),axis=1),axis=1,dtype=np.float32)
            result[b,start:start+len(product)] = accum[:,-1]
    if not np.isfinite(result).all(): raise ValueError('nonfinite projection')
    return result

def diagnostic(weights,inputs,expected):
    w,x = weights.astype(np.float64),inputs.astype(np.float64)
    k=w.shape[1]
    def gamma(n,u): return np.nextafter(n*u/(1-n*u),np.inf)
    g64,g32=gamma(k,2.**-53),gamma(2*k,2.**-24)
    exact=np.empty(expected.shape,np.float64); bounds=np.empty_like(exact)
    for b in range(len(x)):
        p=w*x[b]
        exact[b]=np.sum(p,axis=1,dtype=np.float64)
        sums=np.sum(np.abs(p),axis=1,dtype=np.float64)
        denominator=np.nextafter(1-g64,0)
        sup=np.nextafter(sums/denominator,np.inf)
        term=np.nextafter(np.nextafter(g32+g64,np.inf)*sup,np.inf)
        bounds[b]=np.nextafter(term+np.nextafter(2*k*2.**-149,np.inf),np.inf)
    error=np.abs(expected.astype(np.float64)-exact)
    if not np.isfinite(exact).all() or not np.isfinite(bounds).all() or not (error<=bounds).all():
        raise ValueError('ordered Q violates conservative FP32 bound')
    return {'max_abs_fp64_error':float(error.max()),'max_bound':float(bounds.max()),
            'nrmse':float(np.sqrt(np.mean(error*error))/max(np.sqrt(np.mean(exact*exact)),2.**-149)),
            'gamma_2K32':float(g32),'gamma_K64':float(g64)}

def boundaries():
    tiny=np.float32(2.**-149)
    cases=[('nonFMA',[-1,1+2.**-23],[1,1-2.**-23],0),
           ('ordered',[1e8,1,-1e8],[1,1,1],0),
           ('gradual',[tiny,tiny],[1,1],2),
           ('product-underflow',[tiny],[.5],0),
           ('negative-zero-plus-positive-initial-zero',[-0.],[1],0),
           ('signed-subnormal',[-tiny],[1],0x80000001)]
    return [{'name':n,'weights':np.array([w],np.float32),'inputs':np.array([x],np.float32),
             'expected_bits':bits} for n,w,x,bits in cases]
