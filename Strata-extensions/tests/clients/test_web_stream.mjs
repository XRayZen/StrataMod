import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {CompletionStream,Turn} from '../../clients/web_stream.js';
const e=(delta={},finish=null,usage=undefined)=>`data: ${JSON.stringify({choices:[{index:0,delta,finish_reason:finish}],...(usage===undefined?{}:{usage})})}\n\n`;
const encode=x=>new TextEncoder().encode(x);
function parse(raw,step=1){let p=new CompletionStream();let b=encode(raw);for(let i=0;i<b.length;i+=step)p.feed(b.slice(i,i+step));return p.finish();}
const done='data: [DONE]\n\n';
for(const n of [1,2,7,4096])assert.deepEqual(parse(': waiting\r\n\r\n'+e({reasoning_content:'考'})+e({content:'您'},'length')+done,n).choices[0].message,{role:'assistant',content:'您',reasoning_content:'考'});
for(const bad of [e({content:'partial'}),e({content:'partial'})+done,e({},'stop'),e({},'stop')+done+done,'data: {bad}\n\n','data: {"error":{"message":"failed"}}\n\n'])assert.throws(()=>parse(bad));
const a={tool_calls:[{index:0,id:'call1',type:'function',function:{name:'rea',arguments:'{"p'}}]};
const b={tool_calls:[{index:0,function:{name:'d',arguments:'ath":"x"}'}}]};
assert.deepEqual(parse(e(a)+e(b,'tool_calls')+done).choices[0].message.tool_calls,[{id:'call1',type:'function',function:{name:'read',arguments:'{"path":"x"}'}}]);
assert.throws(()=>parse(e(a,'tool_calls')+done));
assert.equal(parse(e({reasoning_content:'only'},'stop')+done).usage,null);
assert.throws(()=>parse(e({content:'x'},'stop', {completion_tokens:true})+done));
let p=new CompletionStream();assert.throws(()=>p.feed(new Uint8Array([255])));
const old=[{role:'user',content:'old'},{role:'assistant',content:'answer'}];
let turn=new Turn(old,{role:'user',content:'new'});turn.feed(encode(e({content:'partial'})));turn.cancel();assert.throws(()=>turn.commit());assert.deepEqual(turn.history,old);assert.equal(old.length,2);
turn=new Turn(old,{role:'user',content:'new'});turn.feed(encode(e({content:'您'},'stop')+done));turn.commit();assert.deepEqual(turn.history,[...old,{role:'user',content:'new'},{role:'assistant',content:'您'}]);assert.throws(()=>turn.commit());
let failed=new CompletionStream();failed.feed(encode(e({content:'partial'})));assert.throws(()=>failed.finish());assert.throws(()=>failed.feed(encode(e({},'stop')+done)));
assert.deepEqual(parse(e({function_call:{name:'read',arguments:'{"path":'}})+e({function_call:{arguments:'"x"}'}},'function_call')+done).choices[0].message.function_call,{name:'read',arguments:'{"path":"x"}'});
assert.throws(()=>parse('data: {"choices":[],"extra":NaN}\n\n'));
console.log(JSON.stringify({scope:'T31 new shared parser only, not derived WebUI integration',byte_chunk_patterns:4,model:false,normal_settings_modified:false,status:'passed'}));

if(process.argv[2]){
 const source=fs.readFileSync(process.argv[2],'utf8');
 const prefix=source.slice(0,source.indexOf('// --- T31 actual app boundary ---'));
 const fn=(first,last)=>source.slice(source.indexOf(first),source.indexOf(last,source.indexOf(first)));
 const storageCode=fn('const store = {', 'function toast(');
 const stopCode=source.match(/\$\("stop-btn"\)\.onclick = [^\n]+/)[0];
 const functions=fn('function saveChat()', 'function timeStr(')+fn('function apiMessages()', 'function setBusy(')+fn('function setBusy(', '$("composer").onsubmit');
 new vm.Script(source); // Full classic script parses, including untouched top-level app declarations.
 for(const mode of ['complete','multidata','EOF','cancel','error','malformed',...(process.argv[3]?['actualSSE']:[])]){
  const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'hi',textContent:'',lastElementChild:{}});return nodes.get(id);};
  const old=[{role:'user',text:'old'},{role:'assistant',text:'old answer'}];const requests=[],transports=[],renders=[],updates=[],storage=new Map([['strata.chat',JSON.stringify(old)]]);let tools=0;
  const ctx={console,TextDecoder,Uint8Array,structuredClone,AbortController,performance,messages:structuredClone(old),attachments:[],busy:null,
   health:{model:'selected'},settings:{thinking:'high',temperature:0,seed:0,max:'',mcp:true},mcpInfo:{tools:1},$ :node,
   localStorage:{getItem:key=>storage.has(key)?storage.get(key):null,setItem:(key,value)=>storage.set(key,value)},
   renderAttachments(){},autosize(){},renderChat(){renders.push(structuredClone(ctx.messages));},updateAssistant(_el,m,streaming){updates.push({message:structuredClone(m),streaming});},scrollDown(){},toast(){},
   fmt:String,projectionLoaded:()=>false,samplingUntouched:()=>true,headers:()=>({}),requestAnimationFrame:()=>1,cancelAnimationFrame(){},
   userText:m=>m.text,onTool(){tools++;},
   fetch:async(_url,options)=>{
    requests.push(JSON.parse(options.body));let chunks=[];
    const transport={signal:options.signal,cancels:0,releases:0,unread:0};transports.push(transport);
    if(requests.length===1&&mode==='error')return {ok:false,status:500,json:async()=>({error:{message:'controlled'}})};
    const partial=requests.length===1&&mode==='EOF';
    let raw=(mode==='malformed'&&requests.length===1)?'data: {bad}\n\n'+e({content:'unread tail'})+done:
      e({reasoning_content:'考'})+'data: '+JSON.stringify({choices:[],strata_mcp:{kind:'fixture'}})+'\n\n'+e({content:'您'},partial?null:'stop')+(partial?'':done);
    if(mode==='multidata')raw=e({reasoning_content:'考'})+'data: '+JSON.stringify({choices:[],strata_mcp:{kind:'fixture'}})+'\n\n'+
      'data: {"choices":\n'+'data: [{"index":0,"delta":{"content":"您"},"finish_reason":"stop"}]}\n\n'+done;
    if(mode==='multidata')raw=raw.replaceAll('\n','\r\n');
    if(mode==='actualSSE'&&requests.length===1)raw=fs.readFileSync(process.argv[3],'utf8');
    const bytes=encode(raw),step=mode==='multidata'?bytes.length:mode==='cancel'?encode(e({reasoning_content:'考'})).length:2;for(let i=0;i<bytes.length;i+=step)chunks.push(bytes.slice(i,i+step));
    return {ok:true,body:{getReader:()=>({cancel:async()=>{transport.cancels++;transport.unread=chunks.length;chunks=[];},releaseLock:()=>{transport.releases++;},read:async()=>{
     if(requests.length===1&&mode==='cancel'&&transport.reads===1){
      return await new Promise((_resolve,reject)=>{options.signal.addEventListener('abort',()=>{const error=new Error('cancelled');error.name='AbortError';reject(error);},{once:true});node('stop-btn').onclick();});
     }
     transport.reads=(transport.reads||0)+1;
     return chunks.length?{done:false,value:chunks.shift()}:{done:true};
    }})}};
   }};
  vm.createContext(ctx);vm.runInContext(prefix+'\n'+storageCode+'\n'+functions+'\n'+stopCode+'\nglobalThis.testSend=send;globalThis.testHistory=apiMessages;globalThis.testReload=()=>{messages=store.get("chat",[]);};',ctx);
  ctx.testReload();assert.deepEqual(JSON.parse(JSON.stringify(ctx.messages)),old);
  await ctx.testSend();assert.ok(storage.has('strata.chat'));const saved=JSON.parse(storage.get('strata.chat'));ctx.testReload();assert.deepEqual(JSON.parse(JSON.stringify(ctx.messages)),saved);
  assert.equal(saved[0]._t31_incomplete,undefined);
  if(!['complete','multidata','actualSSE'].includes(mode)){assert.equal(saved[2]._t31_incomplete,true);assert.equal(saved[3]._t31_incomplete,true);}
  if(mode==='cancel'){assert.equal(transports[0].signal.aborted,true);assert.equal(transports[0].cancels,1);assert.equal(transports[0].releases,1);assert.ok(updates.some(x=>x.message.stopped===true&&!x.streaming&&x.message.reasoning==='考'));}
  if(mode==='EOF')assert.ok(updates.some(x=>x.message.text==='您'&&x.message.error&&!x.streaming));
  assert.ok(renders.length>0);assert.ok(updates.length>0);
  node('input').value='next';await ctx.testSend();
  if(['complete','multidata','actualSSE'].includes(mode))assert.equal(ctx.messages[3].error,undefined,ctx.messages[3].error);
  const second=requests[1];assert.equal(second.seed,0);assert.equal(second.max_tokens,undefined);assert.equal(second.strata_mcp,true);
  assert.equal(transports[1].releases,1);assert.equal(transports[1].signal.aborted,false);
  if(mode==='malformed'){assert.equal(transports[0].signal.aborted,true);assert.equal(transports[0].cancels,1);assert.equal(transports[0].releases,1);assert.ok(transports[0].unread>0);}
  const history=JSON.parse(JSON.stringify(second.messages));
  assert.deepEqual(history.slice(0,2),[{role:'user',content:'old'},{role:'assistant',content:'old answer'}]);
  if(['complete','multidata','actualSSE'].includes(mode))assert.deepEqual(history.slice(2),[{role:'user',content:'hi'},{role:'assistant',content:'您',...(mode==='actualSSE'?{}:{reasoning_content:'考'})},{role:'user',content:'next'}]);
  else assert.deepEqual(history.slice(2),[{role:'user',content:'next'}]);
  assert.equal(ctx.messages[0].text,'old');if(['complete','multidata'].includes(mode))assert.ok(tools>0);
 }
 console.log(JSON.stringify({scope:'actual derived WebUI send/apiMessages controlled CPU',cases:process.argv[3]?7:6,captured_actual_provider_SSE:!!process.argv[3],model:false,browser:false,status:'passed'}));
}
