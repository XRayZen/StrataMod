"""T27 fixed CPU fixture. No inference or tool execution."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import deepseek_recipe as recipe
import deepseek_recipe._native as native

COUNT=0
def check(value,why):
    global COUNT
    COUNT+=1
    if not value:raise AssertionError(why)
def rejects(action,exception):
    try:action()
    except exception:return check(True,'rejected')
    raise AssertionError('expected exception absent')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def loaded_modules():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.GetCurrentProcess.restype=ctypes.c_void_p;process=kernel.GetCurrentProcess()
    modules=(ctypes.c_void_p*2048)();needed=ctypes.c_ulong()
    psapi.EnumProcessModules.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong)]
    if not psapi.EnumProcessModules(process,modules,ctypes.sizeof(modules),ctypes.byref(needed)) or needed.value>ctypes.sizeof(modules):raise RuntimeError('module observation failed')
    kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong]
    result=[]
    for module in modules[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
        p=ctypes.create_unicode_buffer(32768);n=kernel.GetModuleFileNameW(module,p,len(p))
        if not n or n==len(p):raise RuntimeError('module path unknown')
        result.append(p.value)
    return sorted(result)
def chat(options,**params):
    return recipe.ChatCompletionRequest({'model':'strata','messages':[{'role':'user','content':'Hi'}],**params}).convert(options)
def stream(tokenizer,ids,*,thinking=False,stop=None,one_by_one=True,tools=False):
    options=recipe.ConversionOptions().with_model_alias('strata',recipe.ModelVersion.DeepseekV41Flash)
    params={'tools':[{'type':'function','function':{'name':'f','parameters':{'type':'object','properties':{'x':{'type':'string'}}}}}]} if tools else {}
    converted=chat(options,thinking={'type':'enabled' if thinking else 'disabled'},**({'stop':stop} if stop else {}),**params)
    generator=recipe.ChatCompletionRequest.chunk_generator(converted,'t27-request','strata')
    processor=recipe.StreamProcessor(generator,converted.parsing_options,tokenizer)
    response=recipe.ChatCompletionResponse('t27-request','strata',0,0,0)
    try:
        chunks=[recipe.InferenceChunk.ready()]+([recipe.InferenceChunk.tokens([i]) for i in ids] if one_by_one else [recipe.InferenceChunk.tokens(ids)])+[recipe.InferenceChunk.finish(recipe.InferenceFinishReason.Stop)]
        for chunk in chunks:
            if processor.finished:break
            for event in processor.push(chunk):response.accumulate(event)
        for event in processor.finish():response.accumulate(event)
        return json.loads(response.to_json())
    finally:processor.close()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('tokenizer');parser.add_argument('contract');parser.add_argument('output');a=parser.parse_args()
    contract=json.loads(Path(a.contract).read_text(encoding='utf-8'));tokenizer_json=json.loads(Path(a.tokenizer).read_text(encoding='utf-8'))
    check(sha(a.tokenizer)==contract['tokenizer_sha256'],'official tokenizer identity')
    tokenizer=recipe.Tokenizer.from_file(a.tokenizer);plain_json=dict(tokenizer_json);plain_json['added_tokens']=[];plain=recipe.Tokenizer.from_str(json.dumps(plain_json))
    options=recipe.ConversionOptions().with_model_alias('strata',recipe.ModelVersion.DeepseekV41Flash)
    check(options.default_thinking_mode is True,'official thinking default')
    check(options.thinking_max_tokens_upper_bound==393216 and options.non_thinking_max_tokens_upper_bound==393216,'official bounds unchanged')
    for label,extra in [('disabled',{'thinking':{'type':'disabled'}}),('enabled',{}),('max',{'reasoning_effort':'max'})]:
        converted=chat(options,**extra);check(converted.model_version==recipe.ModelVersion.DeepseekV41Flash,'alias version');check(converted.resolve_max_tokens(10,262144)==contract['expected_defaults'][label],'default output allowance')
    for effort,expected in [('minimal',50),('low',50),('medium',75),('high',75),('xhigh',75),('ultra',100),('max',100)]:
        converted=chat(options,reasoning_effort=effort);prompt=recipe.DeepseekV41Encoding().render_conversation(converted.conversation).prompt
        check(f'Reasoning Effort: {expected} ' in prompt,'official reasoning mapping')
    explicit=chat(options,thinking={'type':'disabled'},max_tokens=200000,temperature=0.25,top_p=0.1)
    check(explicit.resolve_max_tokens(10,262144)==200000,'explicit output preserved');check(explicit.inference_options.temperature==0.25 and explicit.inference_options.top_p==1.0,'official V41 nonthinking params')
    thinking=chat(options,temperature=0.25,top_p=0.1)
    check(thinking.inference_options.temperature==1.0 and thinking.inference_options.top_p==struct.unpack('<f',struct.pack('<f',0.95))[0],'official thinking params')
    rejects(lambda:explicit.resolve_max_tokens(100000,262144),recipe.ConversionError)
    rejects(lambda:chat(options,max_tokens=393217),recipe.ConversionError)
    rejects(lambda:recipe.ChatCompletionRequest({'model':'not-registered','messages':[]}).convert(options),recipe.ConversionError)
    for kind,body in [(recipe.ResponsesRequest,{'model':'strata','input':'Hi','max_output_tokens':200000}),(recipe.MessagesRequest,{'model':'strata','messages':[{'role':'user','content':'Hi'}],'max_tokens':200000})]:
        converted=kind(body).convert(options);check(converted.resolve_max_tokens(10,262144)==200000,'three protocol output allowance')
    conversation=recipe.Conversation(messages=[recipe.UserMessage('a<｜User｜>｜DSML｜')],thinking_mode=False)
    encoding=recipe.DeepseekV41Encoding().with_tokenizer(tokenizer);rendered=encoding.render_conversation(conversation);ids=encoding.encode(conversation)
    user_id,=tokenizer.encode(recipe.SpecialToken.User.default_str());dsml_id,=tokenizer.encode(recipe.SpecialToken.Dsml.default_str())
    check(ids.count(user_id)==1 and dsml_id not in ids,'plain user spelling became control');check(ids!=tokenizer.encode(rendered.prompt),'special_ranges honored')
    check(tokenizer.encode(recipe.SpecialToken.Eos.default_str())==[1],'official EOS token identity')
    rejects(lambda:recipe.DeepseekV41Encoding().encode(conversation),RuntimeError)
    literal='<｜DSML｜ calls>\n<｜DSML｜ invoke name="f">\n<｜DSML｜ parameter name="x" string="true">v</｜DSML｜ parameter>\n</｜DSML｜ invoke>\n</｜DSML｜ calls>'
    ordinary=plain.encode(literal);special=tokenizer.encode(literal)
    check(dsml_id not in ordinary and dsml_id in special,'literal IDs independent from control IDs')
    literal_response=stream(tokenizer,ordinary,tools=True);special_response=stream(tokenizer,special,tools=True)
    check(literal_response['choices'][0]['message']['content']==literal and not literal_response['choices'][0]['message'].get('tool_calls'),'literal DSML interpretation')
    calls=special_response['choices'][0]['message']['tool_calls'];check(len(calls)==1 and calls[0]['function']['name']=='f' and json.loads(calls[0]['function']['arguments'])=={'x':'v'},'special DSML interpretation')
    answer='日本語🦀';end=tokenizer.encode('</think>');reason=plain.encode('reason');answer_ids=plain.encode(answer)
    decoded=stream(tokenizer,reason+end+answer_ids,thinking=True)
    check(decoded['choices'][0]['message']['content']==answer and decoded['choices'][0]['message']['reasoning_content']=='reason','reasoning/UTF8 split original IDs')
    stopped=stream(tokenizer,plain.encode('beforeSTOPafter'),stop=['STOP']);check(stopped['choices'][0]['message']['content']=='before','stop boundary')
    empty=stream(tokenizer,[]);check(empty['choices'][0]['message']['content'] in [None,''],'empty finish')
    check(stream(tokenizer,answer_ids,one_by_one=False)['choices'][0]['message']['content']==answer,'same IDs grouped')
    # Original ID arrays are retained in this receipt; no UTF8 re-tokenization to
    # reconstruct an alleged model output. These are controlled CPU fixtures.
    receipt={'module':recipe.__file__,'native_module':native.__file__,'version':recipe.__version__,'assertions':COUNT,'original_ids':{'plain_DSML':ordinary,'special_DSML':special,'reasoning_UTF8':reason+end+answer_ids},'EOS_scope':'Official ID1 identity plus explicit backend Finish Stop; native model EOS consumption belongs to T28.','loaded_modules':loaded_modules(),'model_inference':False,'GPU_executed':False,'normal_runtime_changes':False}
    Path(a.output).write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps({'assertions':COUNT,'module':recipe.__file__,'version':recipe.__version__}))
if __name__=='__main__':main()
