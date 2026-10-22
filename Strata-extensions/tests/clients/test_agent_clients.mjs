import assert from 'node:assert/strict';
import {supportsContext,thinkingMap,assertSameAuthority} from '../../clients/family_policy.mjs';
const descriptor={family:'deepseek41',context_domain:{minimum:1,maximum:1048576}};
for(const c of [1,524289,1048576])assert.equal(supportsContext(c,descriptor,[4096]),true);
for(const c of [true,0,1048577,1.2,null])assert.equal(supportsContext(c,descriptor,[4096]),false);
assert.equal(supportsContext(4096,null,[262144]),false);
assert.deepEqual(thinkingMap('deepseek41'),{off:'none',minimal:'minimal',low:'low',medium:'medium',high:'high',xhigh:'xhigh',max:'max'});
assert.equal(thinkingMap('legacy'),null);
const authority={family:'deepseek41',runtime_epoch:'1',bundle_id:'a'.repeat(64),package_id:'c'.repeat(64),config_sha256:'b'.repeat(64),native:{pid:7,created:1.25,exe:'C:/owned/native.exe',command:['C:/owned/native.exe','--serve','--runtime-epoch','1']}};
assertSameAuthority(authority,structuredClone(authority));
const large=structuredClone(authority);large.runtime_epoch='1792568209599735400';large.native.command.at(-1);large.native.command[large.native.command.length-1]=large.runtime_epoch;assertSameAuthority(large,JSON.parse(JSON.stringify(large)));
for(const value of ['1792568209599735401','1792568209599735399',1792568209599735400,true,'01','0']){const bad=structuredClone(large);bad.runtime_epoch=value;assert.throws(()=>assertSameAuthority(large,bad));}
const wrongArg=structuredClone(large);wrongArg.native.command[wrongArg.native.command.length-1]='1792568209599735401';assert.throws(()=>assertSameAuthority(wrongArg,structuredClone(wrongArg)));

for(const key of ['runtime_epoch','bundle_id','package_id','config_sha256','native']){const active=structuredClone(authority);active[key]=null;assert.throws(()=>assertSameAuthority(authority,active));}
assert.throws(()=>assertSameAuthority(authority,null));
console.log(JSON.stringify({scope:'T32 new pure family policy, no Pi/Harness integration',status:'passed'}));

const policy=await import('file:///C:/Develop/AI/Pi/policy.mjs');
const native=await import('file:///C:/Develop/AI/Pi/native-arguments.mjs');
const children=await import('file:///C:/Develop/AI/Pi/extensions/subagent/runtime.mjs');
const audit=await import('file:///C:/Develop/AI/Pi/thinking-audit.mjs');
const model='deepseek-v4.1-flash-1017-ud-q4_k_xl',legacy='huihui-ud-q4_k_xl_v2';
assert.equal(policy.supportedBinding(model,524289),true);assert.equal(policy.supportedBinding(legacy,524289),false);
assert.deepEqual(policy.modelConfig(model,524289).providers['strata-local'].models[0].thinkingLevelMap,thinkingMap('deepseek41'));
assert.equal(policy.modelConfig(legacy,262144).providers['strata-local'].models[0].thinkingLevelMap.high,'xhigh');
for(const level of policy.thinkingLevelsForModel(model)){
 assert.equal(native.splitManagedArguments(['--model',model,'--context','524289','--thinking',level]).thinking,level);
 assert.ok(children.childArguments(['--thinking',level,'Task: controlled'],{model,context:524289}).includes(level));
 const wire=thinkingMap('deepseek41')[level];assert.equal(audit.thinkingRequestMetadata({reasoning_effort:wire},level,model).reasoning_effort,wire);
}
assert.equal(audit.thinkingRequestMetadata({reasoning_effort:'ultra'},'max',model).reasoning_effort,'ultra');
const {default:installPiGuard}=await import('file:///C:/Develop/AI/Pi/guard-extension.mjs');
const original={...process.env};const binding={model,context:524289,pid:7,created:1.25,runtimeKind:'strata',fingerprint:'fixed',inputModalities:['text'],familyAuthority:authority};
let active=structuredClone(binding),checks=0;const callbacks=new Map();
try{
 process.env.PI_STRATA_ACTIVE=JSON.stringify(binding);delete process.env.PI_STRATA_VALIDATION;delete process.env.PI_STRATA_BRAVE_VERIFY;
 installPiGuard({on(name,fn){callbacks.set(name,[...(callbacks.get(name)||[]),fn]);},getThinkingLevel:()=> 'medium'},()=>{checks++;return active;});
 const ctx={model:{provider:'strata-local',id:model,contextWindow:524289}};
 const callback=callbacks.get('tool_call')[0];assert.equal(callback({toolName:'any-normal-tool'},ctx),undefined);assert.equal(checks,1);
 active={...active,fingerprint:'changed',familyAuthority:{...authority,runtime_epoch:2}};assert.equal(callback({toolName:'any-normal-tool'},ctx).block,true);assert.equal(checks,2);
}finally{for(const k of Object.keys(process.env))if(!(k in original))delete process.env[k];Object.assign(process.env,original);}
const {createToolGuard}=await import('file:///C:/Develop/AI/Harness/runtime_guard.mjs');
let nextCount=0;const signal=new AbortController().signal,exec={callId:'literal-call',name:'any-normal-tool',arguments:{},signal};
const success=createToolGuard(binding,async()=>binding);assert.equal(await success(exec,async()=>{nextCount++;return 'existing pipeline';}),'existing pipeline');assert.equal(nextCount,1);assert.equal(exec.signal,signal);assert.equal(exec.callId,'literal-call');
await assert.rejects(()=>createToolGuard(binding,async()=>({...binding,fingerprint:'stale'}))(exec,async()=>{nextCount++;}));assert.equal(nextCount,1);
await assert.rejects(()=>createToolGuard(binding,async()=>{throw new Error('unknown');})(exec,async()=>{nextCount++;}));assert.equal(nextCount,1);
assert.equal(await createToolGuard({model:legacy},async()=>{throw new Error('must not probe legacy tool');})(exec,async()=> 'legacy pipeline'),'legacy pipeline');
console.log(JSON.stringify({scope:'T32 actual Pi policy/arguments/audit/tool hook + Harness tool hook controlled CPU',model:false,settings:false,status:'passed'}));
