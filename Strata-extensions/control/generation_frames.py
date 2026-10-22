"""T23 DTO validation; does not tokenize text, authenticate producers, or own runtimes."""
import hashlib
import json
import math
import re
import struct

CONTEXT={'request_id':str,'runtime_epoch':int,'bundle_id':str,'asset_revision':str,'model_family':str,
         'tokenizer_identity':str,'tokenizer_model':str,'tokenizer_pre':str,'vocab_size':int}
TOKENIZER_SHA='100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924'
REVISION='f924b94f19c1fea02c06a65c8475b0a45e2b88b1'

def require(condition,message):
    if not condition:raise ValueError(message)

def integer(value):return type(value) is int and 0<=value<=2**64-1

def context(value):
    require(type(value) is dict and set(value)==set(CONTEXT),'context fields missing/extra')
    require(all(type(value[k]) is t for k,t in CONTEXT.items()),'context field type mismatch')
    require(bool(value['request_id']) and integer(value['runtime_epoch']),'invalid request/epoch')
    require(re.fullmatch('[0-9a-f]{64}',value['bundle_id']) is not None,'invalid bundle identity')
    require(value['asset_revision']==REVISION and value['model_family']=='deepseek41','wrong model source/family')
    require(value['tokenizer_identity']==TOKENIZER_SHA and value['tokenizer_model']=='gpt2'
            and value['tokenizer_pre']=='joyai-llm' and value['vocab_size']==129280,'wrong fixed tokenizer identity')
    return dict(value)

def unique_object(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate JSON field');result[key]=value
    return result

def parse_frame(raw):
    require(type(raw) in (str,bytes),'frame must be original serialized object')
    return json.loads(raw,object_pairs_hook=unique_object,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

METADATA_SCHEMA='strata-generation-metadata/v1'
def logprob_record(value,vocabulary):
    require(type(value) is dict and set(value)=={'logprob','top_logprobs'},'logprob fields')
    def number(x):
        require(type(x) in (float,int) and math.isfinite(x) and x<=0,'invalid logprob')
        try:y=struct.unpack('<f',struct.pack('<f',x))[0]
        except (OverflowError,struct.error):raise ValueError('logprob outside F32')
        require(math.isfinite(y),'nonfinite F32 logprob');return y
    selected=number(value['logprob']);alternatives=value['top_logprobs']
    require(type(alternatives) is list and len(alternatives)<=20,'alternative count')
    seen=set();result=[]
    for item in alternatives:
        require(type(item) is dict and set(item)=={'token_id','logprob'},'alternative fields')
        token=item['token_id'];require(type(token) is int and 0<=token<vocabulary and token not in seen,'alternative original ID')
        seen.add(token);result.append((token,number(item['logprob'])))
    return selected,tuple(result)

class GenerationDTO:
    def __init__(self,expected_context):
        self.expected=context(expected_context);self.begun=False;self.ended=False
        self.sequence=0;self.ids=[];self.digest=hashlib.sha256();self.finish_reason=None
        self.metadata=False;self.metadata_digest=hashlib.sha256(METADATA_SCHEMA.encode()+b'\0')
        self.logprobs=[];self.stop_origin=None

    def feed(self,raw):
        frame=parse_frame(raw)
        require(type(frame) is dict,'frame must be an object')
        require(not self.ended,'frame after finalization')
        require(frame.get('schema')=='strata-generation/v1','unknown protocol schema')
        for key in ('request_id','runtime_epoch'):
            require(type(frame.get(key)) is CONTEXT[key] and frame[key]==self.expected[key],'request/epoch binding mismatch')
        common={'schema','kind','request_id','runtime_epoch'}
        kind=frame.get('kind')
        if kind=='begin':
            required=common|set(CONTEXT)
            require(not self.begun and set(frame) in (required,required|{'metadata_schema'}),'duplicate/bad begin')
            if 'metadata_schema' in frame:
                require(frame['metadata_schema']==METADATA_SCHEMA,'unknown metadata schema');self.metadata=True
            actual=context({key:frame[key] for key in CONTEXT})
            require(actual==self.expected,'launch/tokenizer binding mismatch');self.begun=True;return None
        require(self.begun,'missing begin')
        require(integer(frame.get('sequence')) and frame['sequence']==self.sequence,'missing/duplicate/reordered batch')
        if kind=='token_batch':
            required=common|{'sequence','origin','ids'}
            require(set(frame) in (required,required|{'logprobs'}) and ('logprobs' not in frame or self.metadata),'token batch fields missing/extra')
            require(frame['origin']=='native-generated','re-tokenized/synthetic token provenance is not original generation')
            ids=frame['ids'];require(type(ids) is list and bool(ids),'missing token IDs')
            require(all(type(token) is int and 0<=token<self.expected['vocab_size'] for token in ids),'invalid original token ID')
            require(len(self.ids)+len(ids)<=2**64-1 and self.sequence<2**64-1,'counter overflow')
            records=[None]*len(ids)
            if 'logprobs' in frame:
                require(type(frame['logprobs']) is list and len(frame['logprobs'])==len(ids),'logprob token association')
                records=[logprob_record(x,self.expected['vocab_size']) for x in frame['logprobs']]
            for token,lp in zip(ids,records):
                self.digest.update(struct.pack('<I',token))
                self.metadata_digest.update(struct.pack('<IB',token,int(lp is not None)))
                if lp is not None:
                    selected,alternatives=lp;self.metadata_digest.update(struct.pack('<fI',selected,len(alternatives)))
                    for other,probability in alternatives:self.metadata_digest.update(struct.pack('<If',other,probability))
            self.logprobs.extend(records)
            self.ids.extend(ids);self.sequence+=1;return tuple(ids)
        require(kind=='finish','unknown frame kind')
        required=common|{'sequence','generated_count','finish','ids_sha256'}
        require(set(frame)==(required|{'stop_origin','metadata_sha256'} if self.metadata else required),'finish fields missing/extra')
        require(integer(frame['generated_count']) and frame['generated_count']==len(self.ids),'generated count missing/mismatch')
        require(frame['finish'] in ('stop','length','cancel','nonfinite','error'),'invalid raw finish')
        require(type(frame['ids_sha256']) is str and frame['ids_sha256']==self.digest.hexdigest(),'original ID integrity mismatch')
        if self.metadata:
            origin=frame['stop_origin'];require(type(origin) is str and origin in ('','eos','recipe','limit','user_cancel','error','nonfinite'),'unknown stop origin')
            expected_reason={'eos':'stop','recipe':'stop','limit':'length','user_cancel':'cancel','error':'error','nonfinite':'nonfinite'}
            require(not origin or frame['finish']==expected_reason[origin],'origin/finish mismatch')
            raw=origin.encode('ascii');self.metadata_digest.update(struct.pack('<I',len(raw))+raw)
            require(type(frame['metadata_sha256']) is str and frame['metadata_sha256']==self.metadata_digest.hexdigest(),'metadata integrity mismatch')
            self.stop_origin=origin
        self.finish_reason=frame['finish'];self.ended=True
        return self.result()

    def result(self):
        require(self.begun and self.ended,'EOF before finish; incomplete generation')
        result=dict(context=dict(self.expected),original_token_ids=tuple(self.ids),generated_count=len(self.ids),
                    finish=self.finish_reason,generation_success=self.finish_reason in ('stop','length'),
                    ids_sha256=self.digest.hexdigest())
        if self.metadata:result.update(logprobs=tuple(self.logprobs),stop_origin=self.stop_origin,metadata_sha256=self.metadata_digest.hexdigest())
        return result
