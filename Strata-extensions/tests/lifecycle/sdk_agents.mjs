import assert from 'node:assert/strict';
import installGuard from 'file:///C:/Develop/AI/Pi/guard-extension.mjs';
import {ExtensionRunner} from 'file:///C:/Develop/AI/Pi/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/runner.js';
import {AgentSession} from 'file:///C:/Develop/AI/Pi/node_modules/@earendil-works/pi-coding-agent/dist/core/agent-session.js';
import {SessionManager} from 'file:///C:/Develop/AI/Pi/node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.js';
import {runAgentLoop} from 'file:///C:/Develop/AI/Pi/node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js';
import {transformMessages} from 'file:///C:/Develop/AI/Pi/node_modules/@earendil-works/pi-ai/dist/api/transform-messages.js';

// Only construction peripherals are disabled; the pinned SDK message_end,
// in-place replacement, event listener and appendMessage functions run intact.
class CommitSession extends AgentSession {
 _installAgentToolHooks(){} _installAgentNextTurnRefresh(){} _installAgentRequestProjection(){}
 _installAgentBoundaryHooks(){} _installHiddenDeclarationsProjection(){} _installAgentForcedPromptProjection(){} _buildRuntime(){}
}
const model='deepseek-v4.1-flash-1017-ud-q4_k_xl',epoch='1792568209599735400';
const authority={family:'deepseek41',runtime_epoch:epoch,bundle_id:'a'.repeat(64),package_id:'b'.repeat(64),config_sha256:'c'.repeat(64),native:{pid:7,created:1.25,exe:'C:/owned/native.exe',command:['C:/owned/native.exe','--serve','--runtime-epoch',epoch]}};
const binding={model,context:4096,pid:7,created:1.25,runtimeKind:'strata',fingerprint:'fixed',inputModalities:['text'],familyAuthority:authority};
const ctx={model:{provider:'strata-local',id:model,contextWindow:4096}};
const env={...process.env};const results=[];
try {
 process.env.PI_STRATA_ACTIVE=JSON.stringify(binding);delete process.env.PI_STRATA_VALIDATION;delete process.env.PI_STRATA_BRAVE_VERIFY;
 for(const mode of ['same','changed','unknown','legacy','user']) {
  const callbacks=new Map();let active=structuredClone(binding);
  if(mode==='legacy'){delete active.familyAuthority;process.env.PI_STRATA_ACTIVE=JSON.stringify(active);}else process.env.PI_STRATA_ACTIVE=JSON.stringify(binding);
  installGuard({on(name,fn){callbacks.set(name,[...(callbacks.get(name)||[]),fn]);},getThinkingLevel:()=> 'minimal'},()=>{
   if(mode==='unknown')throw new Error('observation unavailable');return active;
  });
  assert.ok(callbacks.has('message_end'),'Pi commit-before hook missing');
  if(mode==='changed')active={...active,fingerprint:'changed',familyAuthority:{...authority,runtime_epoch:'1792568209599735401'}};
  const runner=new ExtensionRunner([{path:'controlled-guard',handlers:callbacks}],{},process.cwd(),null,null);runner.createContext=()=>ctx;
  const manager=SessionManager.inMemory(process.cwd());const agent={state:{messages:[]},subscribe:()=>()=>{}};
  const session=new CommitSession({agent,sessionManager:manager,settingsManager:{getRetrySettings:()=>({enabled:false})},resourceLoader:{},cwd:process.cwd()});session._extensionRunner=runner;
  const message=mode==='user'?{role:'user',content:[{type:'text',text:'hello'}],timestamp:1}:{role:'assistant',api:'openai-completions',provider:'strata-local',model,content:[{type:'thinking',thinking:'partial-reasoning'},{type:'toolCall',id:'real-shaped-call',name:'f',arguments:{}}],usage:{input:1,output:2,cacheRead:0,cacheWrite:0,totalTokens:3,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason:'toolUse',timestamp:1};
  const old=structuredClone(message);agent.state.messages.push(message);let listener;
  session.subscribe(event=>{if(event.type==='message_end')listener=structuredClone(event.message);});
  await session._handleAgentEvent({type:'message_end',message});
  const saved=manager.getBranch().filter(e=>e.type==='message').at(-1).message;
  assert.equal(agent.state.messages[0],message);assert.deepEqual(saved,message);assert.deepEqual(listener,message);
  if(mode==='changed'||mode==='unknown') {
   assert.equal(message.stopReason,'aborted');assert.deepEqual(message.content,old.content);assert.equal(typeof message.errorMessage,'string');
   assert.equal(transformMessages([message],{api:'openai-completions',provider:'strata-local',id:model,input:['text']}).length,0);
  }else assert.deepEqual(message,old);
  let toolExecutions=null;
  if(['same','changed','unknown'].includes(mode)) {
   toolExecutions=0;const generated=structuredClone(old);
   const streamFn=async()=>({async *[Symbol.asyncIterator](){yield {type:'done'};},async result(){return generated;}});
   const tool={name:'f',label:'controlled readonly',description:'controlled readonly',parameters:{type:'object',properties:{},additionalProperties:false},async execute(){toolExecutions++;return {content:[{type:'text',text:'seed'}],details:{}};}};
   const output=await runAgentLoop([{role:'user',content:[{type:'text',text:'controlled'}],timestamp:1}],{messages:[],tools:[tool]},
    {model:{provider:'strata-local',api:'openai-completions',id:model,input:['text']},convertToLlm:async x=>x,finishTurn:async()=>({action:'end'}),beforeToolCall:async event=>{for(const callback of callbacks.get('tool_call')||[]){const value=await callback({toolName:event.toolCall.name},ctx);if(value?.block)return {block:true,reason:value.reason};}}},
    async event=>{if(event.type==='message_end'&&event.message.role==='assistant')agent.state.messages.push(event.message);await session._handleAgentEvent(event);},undefined,streamFn);
   assert.equal(toolExecutions,mode==='same'?1:0);assert.equal(output.find(m=>m.role==='assistant').stopReason,mode==='same'?'toolUse':'aborted');
   if(mode==='same')assert.ok(manager.getBranch().some(e=>e.type==='message'&&e.message.role==='toolResult'));
  }
  results.push({mode,persistedStopReason:message.stopReason??null,toolExecutions,model:false});
 }
}finally{for(const key of Object.keys(process.env))if(!(key in env))delete process.env[key];Object.assign(process.env,env);}
console.log(JSON.stringify({scope:'T33 pinned Pi message_end/AgentSession commit CPU; no model or network',results}));
