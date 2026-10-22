import assert from 'node:assert/strict';
import {normalizeIdentity,sameIdentity,historyForContext} from '../../clients/runtime_identity.js';
const tag=()=>({schema:'strata-runtime-identity/v1',family:'deepseek41',bundle_id:'a'.repeat(64),package_id:'b'.repeat(64),runtime_epoch:'1792568209599735400',model:'deepseek-v4.1',context:4096});
assert.deepEqual(normalizeIdentity(tag()),tag());assert.equal(sameIdentity(tag(),tag()),true);
for(const value of [true,1,1.0,'01','0','-1','18446744073709551616'])assert.throws(()=>normalizeIdentity({...tag(),runtime_epoch:value}));
assert.equal(sameIdentity(tag(),{...tag(),runtime_epoch:'1792568209599735401'}),false);assert.equal(sameIdentity(null,null),false);
const old=[{role:'assistant',content:'old'}],partial={role:'assistant',content:'partial',strata_incomplete:true,strata_runtime:tag()};
assert.deepEqual(historyForContext([...old,partial]),old);assert.equal(historyForContext([...old,{...partial,strata_incomplete:false}]).length,2);
assert.deepEqual(old,[{role:'assistant',content:'old'}]);console.log('T33 identity literal passed');

const {CompletionStream,Turn}=await import('../../clients/web_stream.js');
const policy={normalize:normalizeIdentity,same:sameIdentity};
const sse=identity=>new TextEncoder().encode('data: '+JSON.stringify({choices:[{index:0,delta:{content:'answer'},finish_reason:'stop'}],...(identity?{strata_runtime:identity}:{})})+'\n\ndata: [DONE]\n\n');
const turn=new Turn([{role:'assistant',content:'old'}],{role:'user',content:'next'},tag(),policy);turn.feed(sse(tag()));turn.commit(tag());assert.deepEqual(turn.history.at(-1).strata_runtime,tag());
for(const identity of [null,{...tag(),runtime_epoch:'1792568209599735401'}]){const parser=new CompletionStream(tag(),policy);assert.throws(()=>parser.feed(sse(identity)));}
const stale=new Turn([],{role:'user',content:'next'},tag(),policy);stale.feed(sse(tag()));assert.throws(()=>stale.commit({...tag(),runtime_epoch:'1792568209599735401'}));assert.equal(stale.committed,false);assert.deepEqual(stale.history,[]);
const legacy=new CompletionStream();legacy.feed(sse(null));assert.deepEqual(legacy.finish().choices[0].message,{role:'assistant',content:'answer'});
console.log('T33 optional stream identity and fresh commit passed');

// Actual selected send/apiMessages and local store functions, controlled DOM/HTTP only.
if(process.argv[2]){
 const fs=await import('node:fs'),vm=await import('node:vm');const source=fs.readFileSync(process.argv[2],'utf8');
 const prefix=source.slice(0,source.indexOf('// --- T31 actual app boundary ---'));
 const fn=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
 const code=prefix+'\n'+fn('const store = {','function toast(')+'\n'+fn('function saveChat()','function timeStr(')+fn('function apiMessages()','function setBusy(')+fn('function setBusy(','$("composer").onsubmit');
 for(const mode of ['same','commitChanged','streamChanged','unknownBefore']){
  const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'hi',textContent:'',lastElementChild:{}});return nodes.get(id);};
  const original=[{role:'user',text:'old'},{role:'assistant',text:'old answer'}],storage=new Map([['strata.chat',JSON.stringify(original)]]),requests=[],transports=[];let identity=tag(),metrics=0;
  const ctx={console,TextDecoder,Uint8Array,structuredClone,AbortController,performance,messages:structuredClone(original),attachments:[],busy:null,health:{model:'deepseek-v4.1'},settings:{thinking:'minimal',temperature:0,seed:0,max:'',mcp:false},mcpInfo:{tools:0},$:node,
   localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},renderAttachments(){},autosize(){},renderChat(){},updateAssistant(){},scrollDown(){},toast(){},fmt:String,projectionLoaded:()=>false,samplingUntouched:()=>true,headers:()=>({}),requestAnimationFrame:()=>1,cancelAnimationFrame(){},userText:m=>m.text,onTool(){},
   fetch:async(url,options)=>{
    if(url==='metrics'){
     metrics++;assert.equal(options.cache,'no-store');
     if(mode==='unknownBefore'&&metrics===1)return {ok:true,json:async()=>({})};
     if(mode==='commitChanged'&&requests.length===1)identity={...tag(),runtime_epoch:'1792568209599735401'};
     return {ok:true,json:async()=>({strata_runtime:structuredClone(identity)})};
    }
    assert.equal(url,'v1/chat/completions');requests.push(JSON.parse(options.body));const initial=structuredClone(identity),bad=mode==='streamChanged'&&requests.length===1;
    const data=(d,f,i)=>'data: '+JSON.stringify({choices:[{index:0,delta:d,finish_reason:f}],strata_runtime:i})+'\n\n';
    const raw=data({reasoning_content:'partial'},null,initial)+data({content:'answer'},'stop',bad?{...initial,runtime_epoch:'1792568209599735401'}:initial)+'data: [DONE]\n\n';
    const bytes=new TextEncoder().encode(raw),chunks=[];for(let i=0;i<bytes.length;i+=7)chunks.push(bytes.slice(i,i+7));const state={cancels:0,releases:0,signal:options.signal};transports.push(state);
    return {ok:true,body:{getReader:()=>({read:async()=>chunks.length?{done:false,value:chunks.shift()}:{done:true},cancel:async()=>{state.cancels++;chunks.length=0;},releaseLock:()=>{state.releases++;}})}};
   }};
  vm.createContext(ctx);vm.runInContext(code+'\nglobalThis.run=send;globalThis.prompt=apiMessages;globalThis.reload=()=>{messages=store.get("chat",[]);};',ctx);
  await ctx.run();const saved=JSON.parse(storage.get('strata.chat'));assert.deepEqual(saved.slice(0,2).map(({role,text})=>({role,text})),original);ctx.reload();
  if(mode==='same'){assert.equal(saved[3].strata_incomplete,undefined);assert.deepEqual(saved[3].strata_runtime,tag());}
  else {assert.equal(saved[2].strata_incomplete,true);assert.equal(saved[3].strata_incomplete,true);if(mode==='unknownBefore')assert.equal(requests.length,0);}
  if(transports.length){assert.equal(transports[0].releases,1);if(mode!=='same'){assert.equal(transports[0].signal.aborted,true);assert.equal(transports[0].cancels,1);}}
  node('input').value='next';await ctx.run();const next=requests.at(-1);assert.deepEqual(next.messages.slice(0,2),[{role:'user',content:'old'},{role:'assistant',content:'old answer'}]);
  assert.equal(next.messages.at(-1).content,'next');if(mode!=='same')assert.equal(next.messages.length,3);assert.equal(ctx.messages.at(-1).error,undefined);
 }
 console.log('T33 actual bound send/store/nextprompt 4 identity cases passed; browser/model false');
}
