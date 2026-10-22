"""Independent host distribution / metadata expectations, no candidate import."""
import hashlib, math, struct
DOMAIN=b'strata-generation-metadata/v1\0'
def metadata(records,origin=''):
    h=hashlib.sha256(DOMAIN)
    for token,lp in records:
        h.update(struct.pack('<IB',token,int(lp is not None)))
        if lp is not None:
            value,alternatives=lp
            h.update(struct.pack('<fI',value,len(alternatives)))
            for other,probability in alternatives:h.update(struct.pack('<If',other,probability))
    raw=origin.encode('ascii');h.update(struct.pack('<I',len(raw))+raw)
    return h.hexdigest()
def distribution(logits,counts=None,frequency=0,presence=0,repeat=1,bias=None):
    values=list(map(float,logits))
    for token,count in (counts or {}).items():
        values[token]=(values[token]*repeat if values[token]<0 else values[token]/repeat)-frequency*count-presence
    for token,value in (bias or {}).items():values[token]+=value
    maximum=max(values);total=math.fsum(math.exp(x-maximum) for x in values)
    return [(x-maximum)-math.log(total) for x in values]


def prepare_model_expected(root):
    """Fixed prior independent graph; never imports candidate model code/output."""
    import importlib.util,json,shutil,sys
    from pathlib import Path
    import numpy as np
    root=Path(root);out=root/'build-deepseek-t28/normal/q';out.mkdir(parents=True,exist_ok=True)
    snapshot=out/'independent-source';original=root/'build-deepseek-t20/full-independent-source'
    chain=[]
    for row in json.loads((original/'source-map.json').read_text(encoding='utf-8')):
        source=Path(row['snapshot']);relative=source.relative_to(original);target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True)
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        if before!=row['sha256']:raise ValueError('accepted independent source changed')
        shutil.copy2(source,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=before:raise ValueError('copy changed')
        chain.append(dict(path=str(target),sha256=before))
    def load(name,path):
        spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
    actual=load('t28_actual_independent',snapshot/'Strata-extensions/tests/numerics/t25/reference.py')
    semantic=load('t28_semantic_independent',snapshot/'Strata-extensions/tests/core/reference.py')
    oracle=actual.ActualOracle(snapshot);full=semantic.FullModelOracle(oracle)
    # Literal expected IDs are official Recipe empty-user/nonthinking encoding,
    # separately tested against the unchanged installed official tokenizer.
    tokens=[0,128803,128804,128822]
    body=dict(model='strata',messages=[dict(role='user',content='')],thinking=dict(type='disabled'),temperature=0,max_tokens=1,logprobs=True,top_logprobs=3,top_k=0,seed=0)
    manifest=dict(schema='strata-t28-normal-Q/v1',request=body,input_ids=tokens,context=16,independent_source_chain=chain,outputs=[],GPU_executed=False)
    for position,token in enumerate(tokens):
        result=full.step(token,position);logits=np.asarray(result['logits'],dtype='<f4');path=out/(str(position)+'-logits.bin');logits.tofile(path)
        manifest['outputs'].append(dict(position=position,path=str(path),bytes=logits.nbytes,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        (out/'progress.json').write_text(json.dumps(dict(completed=position+1,total=len(tokens),GPU_executed=False)),encoding='utf-8')
        print('independent normal Q token',position,flush=True)
    values=logits.reshape(-1);order=sorted(range(len(values)),key=lambda i:(-float(values[i]),i));lp=distribution(values)
    manifest.update(expected_id=order[0],selected_logprob_f32=struct.unpack('<f',struct.pack('<f',lp[order[0]]))[0],top_logprobs=[dict(token_id=i,logprob=struct.unpack('<f',struct.pack('<f',lp[i]))[0])for i in order[:3]],source_reads=oracle.reads)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('normal Q sealed',hashlib.sha256((out/'manifest.json').read_bytes()).hexdigest(),flush=True)
