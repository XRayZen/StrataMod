"""Real native-emitter / official-codec controlled qualification, no inference."""
import copy,hashlib,importlib.util,json,struct,subprocess,sys
from pathlib import Path
import deepseek_recipe as recipe

def module(path):
 s=importlib.util.spec_from_file_location('t28_hook',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def qualify(root,exe,bundle,out):
 root=Path(root);out=Path(out);out.mkdir(exist_ok=True);hook=module(root/'Strata-extensions/models/deepseek41/serve_codec.py');tokenizer=recipe.Tokenizer.from_file(str(root/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json'));source=json.loads((root/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json').read_text(encoding='utf-8'));source['added_tokens']=[];plain=recipe.Tokenizer.from_str(json.dumps(source));checks=[];captures=[]
 def check(value,label):
  if not value:raise AssertionError(label)
  checks.append(label)
 body={'model':'strata','messages':[{'role':'user','content':'Hi'}],'thinking':{'type':'disabled'}}
 def frames(name,batches,finish='stop'):
  p=out/(name+'.batches');p.write_text(''.join(','.join(map(str,x))+'\n' for x in batches),encoding='utf-8');r=subprocess.run([str(exe),bundle,finish,str(p)],capture_output=True,check=True,encoding='utf-8');check(r.stderr=='','native stderr');return r.stdout.splitlines()
 def session(lines,extra=None):
  ctx={k:json.loads(lines[0])[k] for k in hook._dto.CONTEXT};prepared=hook.prepare_chat({**body,**(extra or {})},tokenizer,262144);return hook.CodecSession(ctx,prepared,tokenizer)
 def consume(name,batches,finish='stop',extra=None):
  lines=frames(name,batches,finish);s=session(lines,extra);events=[]
  for line in lines:events.extend(s.feed(line))
  result=s.end_of_stream();flat=[x for batch in batches for x in batch];check(result['raw']['original_token_ids']==tuple(flat),name+' original IDs');check(result['raw']['ids_sha256']==hashlib.sha256(b''.join(struct.pack('<I',x) for x in flat)).hexdigest(),name+' original hash');check(result['raw']['generated_count']==len(flat),name+' original count')
  if 1 in flat:
   index=flat.index(1);check(result['first_eos_index']==index and result['recipe_input_ids']==tuple(flat[:index]) and result['recipe_input_count']==index,name+' exact EOS prefix');check(result['push_calls']==(3 if index else 2),name+' no post-EOS push')
  captures.append(dict(name=name,frames=lines,events=events,result=result));return result,events
 text='日本語🦀';ids=plain.encode(text)
 for name,batches in [('group',[ids]),('singleton',[[i] for i in ids]),('eos-suffix',[ids+[1]+plain.encode('suffix')]),('eos-next',[ids+[1],plain.encode('suffix')])]:
  r,events=consume(name,batches);check(r['success'] and r['response']['choices'][0]['message']['content']==text,name+' content');check(sum(c.get('finish_reason') is not None for e in events for c in e.get('choices',[]))==1,name+' terminal once')
 for finish in ['cancel','error','nonfinite']:
  r,events=consume('eos-'+finish,[ids+[1],plain.encode('suffix')],finish);check(not r['success'] and r['response'] is None,finish+' unsuccessful');check(not any(c.get('finish_reason') is not None for e in events for c in e.get('choices',[])),finish+' terminal withheld')
 for name,batches in [('eos-alone',[[1]]),('eos-leading',[[1]+ids]),('empty',[])]:
  r,_=consume(name,batches);check(r['success'] and r['response']['choices'][0]['message']['content'] in [None,''],name+' empty normalized content')
 eos_text='<｜end▁of▁sentence｜>';literal_eos=[token for char in eos_text for token in plain.encode(char)];check(1 not in literal_eos,'ordinary EOS spelling IDs');r,_=consume('literal-eos',[literal_eos]);check(r['response']['choices'][0]['message']['content']==eos_text and r['first_eos_index'] is None,'literal EOS is content')
 r,_=consume('length',[ids],'length');check(r['success'] and r['raw']['finish']=='length' and r['normalized_finish']=='length','length retained')
 r,_=consume('stop-string',[plain.encode('beforeSTOPafter')],extra={'stop':['STOP']});check(r['response']['choices'][0]['message']['content']=='before','official stop string')
 r,events=consume('stop-then-error',[plain.encode('beforeSTOPafter')],'error',extra={'stop':['STOP']});check(not r['success'] and not any(c.get('finish_reason') is not None for e in events for c in e.get('choices',[])),'stop then error no terminal')
 for kind in ['hash','count','epoch','sequence','origin','duplicate','EOF']:
  lines=frames('bad-'+kind,[ids+[1],plain.encode('suffix')]);s=session(lines);events=[]
  if kind=='EOF':lines=lines[:-1]
  else:
   p=json.loads(lines[-1] if kind not in ['sequence','origin'] else lines[2]);key={'hash':'ids_sha256','count':'generated_count','epoch':'runtime_epoch','sequence':'sequence','origin':'origin'}.get(kind)
   if key:p[key]='0'*64 if kind=='hash' else 'utf8-retokenized' if kind=='origin' else 999
   lines[-1 if kind not in ['sequence','origin'] else 2]=json.dumps(p)
   if kind=='duplicate':lines.insert(-1,lines[1])
  try:
   for line in lines:events.extend(s.feed(line))
   s.end_of_stream()
  except hook.CodecError:check(not any(c.get('finish_reason') is not None for e in events for c in e.get('choices',[])),kind+' no successful terminal')
  else:raise AssertionError(kind+' accepted')
  fresh,_=consume('fresh-'+kind,[ids]);check(fresh['success'],kind+' fresh request')
 literal='<｜DSML｜ calls>\n<｜DSML｜ invoke name="f">\n<｜DSML｜ parameter name="x" string="true">v</｜DSML｜ parameter>\n</｜DSML｜ invoke>\n</｜DSML｜ calls>'
 tools=[{'type':'function','function':{'name':'f','parameters':{'type':'object','properties':{'x':{'type':'string'}}}}}]
 r,_=consume('literal-dsml',[plain.encode(literal)],extra={'tools':tools});check(r['response']['choices'][0]['message']['content']==literal,'literal DSML unchanged')
 r,_=consume('control-dsml',[tokenizer.encode(literal)],extra={'tools':tools});calls=r['response']['choices'][0]['message']['tool_calls'];check(calls[0]['function']['name']=='f' and json.loads(calls[0]['function']['arguments'])=={'x':'v'},'special DSML control')
 r,_=consume('thinking',[plain.encode('reason')+tokenizer.encode('</think>')+ids],extra={'thinking':{'type':'enabled'}});message=r['response']['choices'][0]['message'];check(message['content']==text and message['reasoning_content']=='reason','ThinkingEnd original IDs')
 for label,extra,expected in [('disabled',{'thinking':{'type':'disabled'}},8192),('enabled',{'thinking':{'type':'enabled'}},65536),('max',{'reasoning_effort':'max','thinking':{'type':'enabled'}},131072)]:
  check(hook.prepare_chat({**body,**extra},tokenizer,262144)['max_tokens']==expected,'official default '+label)
 check(hook.prepare_chat({**body,'max_tokens':200000},tokenizer,262144)['max_tokens']==200000,'explicit allowance retained')
 runtime=module(root/'Strata-extensions/tests/codec/codec_fixture.py')
 return dict(assertions=len(checks),checks=checks,captures=captures,loaded_modules=runtime.loaded_modules(),recipe_module=recipe.__file__,model_inference=False,normal_server=False,normal_caps_changed=False)

if __name__=='__main__':
 result=qualify(*sys.argv[1:5]);Path(sys.argv[5]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(dict(assertions=result['assertions'])))

