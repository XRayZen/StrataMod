// Transactional OpenAI SSE accumulation. Does not own a network or tool executor.
const require=(ok,reason)=>{if(!ok)throw new Error(reason);};
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const copy=x=>structuredClone(x);
const canonical=x=>JSON.stringify(x,(_k,v)=>object(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
export class CompletionStream {
  constructor(expectedIdentity=null,identityPolicy=null){this.identityPolicy=identityPolicy;this.expectedIdentity=null;if(expectedIdentity!==null){require(identityPolicy&&typeof identityPolicy.normalize==='function'&&typeof identityPolicy.same==='function','runtime identity policy required');this.expectedIdentity=identityPolicy.normalize(expectedIdentity);}this.decoder=new TextDecoder('utf-8',{fatal:true});this.buffer='';this.data=[];this.choices=new Map();this.usage=null;this.done=false;this.cancelled=false;this.failed=null;this.finished=false;}
  cancel(){this.cancelled=true;}
  feed(chunk){
    require(!this.finished&&!this.cancelled&&!this.failed,'inactive stream');
    require(chunk instanceof Uint8Array,'transport bytes required');
    this.events=[];
    try {
      this.buffer+=this.decoder.decode(chunk,{stream:true});
      let nl;
      while((nl=this.buffer.indexOf('\n'))>=0){let line=this.buffer.slice(0,nl);this.buffer=this.buffer.slice(nl+1);if(line.endsWith('\r'))line=line.slice(0,-1);this.line(line);}
    }catch(error){this.failed=error.message;throw error;}
    return this.events;
  }
  line(line){
    if(!line){if(this.data.length){this.event(this.data.join('\n'));this.data=[];}return;}
    if(line.startsWith(':'))return;
    const index=line.indexOf(':');const name=index<0?line:line.slice(0,index);let value=index<0?'':line.slice(index+1);if(value.startsWith(' '))value=value.slice(1);
    if(name==='data')this.data.push(value);
  }
  event(data){
    require(!this.done,'completion event after DONE');
    if(data==='[DONE]'){require(this.choices.size&&[...this.choices.values()].every(x=>x.finish_reason!==null),'DONE without formal finish');this.done=true;return;}
    const value=JSON.parse(data);require(object(value),'completion object required');require(value.error===undefined||value.error===null,'provider error');
    if(this.expectedIdentity!==null)require(this.identityPolicy.same(this.expectedIdentity,value.strata_runtime),'runtime changed or unavailable in response');
    if(value.usage!==undefined&&value.usage!==null){
      require(object(value.usage),'usage object');
      for(const key of ['prompt_tokens','completion_tokens','total_tokens'])if(key in value.usage)require(Number.isSafeInteger(value.usage[key])&&value.usage[key]>=0,'invalid usage counter');
      if(this.usage!==null)require(canonical(this.usage)===canonical(value.usage),'conflicting usage');this.usage=copy(value.usage);
    }
    const rows=value.choices??[];require(Array.isArray(rows),'choices list');
    for(const row of rows){
      require(object(row)&&Number.isSafeInteger(row.index)&&row.index>=0,'choice index');
      if(!this.choices.has(row.index))this.choices.set(row.index,{content:'',reasoning_content:'',tools:new Map(),legacy:null,finish_reason:null});
      const state=this.choices.get(row.index);const delta=row.delta??{};require(object(delta),'delta object');require(state.finish_reason===null||Object.keys(delta).length===0,'delta after formal finish');
      if('role'in delta)require(delta.role==='assistant','assistant role required');
      for(const key of ['content','reasoning_content'])if(delta[key]!==undefined&&delta[key]!==null){require(typeof delta[key]==='string','text delta');state[key]+=delta[key];}
      if('tool_calls'in delta){
        require(state.legacy===null,'mixed legacy/modern function delta');
        require(Array.isArray(delta.tool_calls),'tool delta list');
        for(const tool of delta.tool_calls){
          require(object(tool)&&Number.isSafeInteger(tool.index)&&tool.index>=0,'tool index');
          if(!state.tools.has(tool.index))state.tools.set(tool.index,{id:'',type:'function',function:{name:'',arguments:''}});
          const target=state.tools.get(tool.index);
          if(tool.id){require(typeof tool.id==='string'&&(!target.id||target.id===tool.id),'tool id changed');target.id=tool.id;}
          if('type'in tool)require(tool.type==='function','tool type');
          const fn=tool.function??{};require(object(fn),'function delta');for(const key of ['name','arguments'])if(key in fn){require(typeof fn[key]==='string','function text delta');target.function[key]+=fn[key];}
        }
      }
      if('function_call'in delta){require(!state.tools.size,'mixed legacy/modern function delta');const fn=delta.function_call;require(object(fn),'legacy function delta');state.legacy??={name:'',arguments:''};for(const key of ['name','arguments'])if(key in fn){require(typeof fn[key]==='string','legacy function text delta');state.legacy[key]+=fn[key];}}
      if(row.finish_reason!==undefined&&row.finish_reason!==null){require(['stop','length','tool_calls','function_call','content_filter'].includes(row.finish_reason),'unrecognized formal finish');require(state.finish_reason===null,'duplicate formal finish');state.finish_reason=row.finish_reason;}
    }
    this.events.push(copy(value));
  }
  finish(){
    require(!this.finished&&!this.cancelled&&!this.failed,'stream did not complete');this.finished=true;
    this.buffer+=this.decoder.decode();require(!this.buffer&&!this.data.length&&this.done,'EOF before complete DONE event');
    const choices=[];
    for(const [index,state]of [...this.choices.entries()].sort((a,b)=>a[0]-b[0])){
      const message={role:'assistant',content:state.content};if(this.expectedIdentity!==null)message.strata_runtime=copy(this.expectedIdentity);if(state.reasoning_content)message.reasoning_content=state.reasoning_content;
      if(state.tools.size){const tools=[...state.tools.entries()].sort((a,b)=>a[0]-b[0]).map(([,t])=>copy(t));const ids=new Set();
        for(const tool of tools){require(tool.id&&!ids.has(tool.id)&&tool.function.name,'incomplete or duplicate tool identity');ids.add(tool.id);require(object(JSON.parse(tool.function.arguments)),'tool arguments must be an object');}
        message.tool_calls=tools;
      }
      if(state.legacy!==null){require(state.legacy.name&&object(JSON.parse(state.legacy.arguments)),'incomplete legacy function');message.function_call=copy(state.legacy);}
      choices.push({index,message,finish_reason:state.finish_reason});
    }
    return {choices,usage:copy(this.usage)};
  }
}
export class Turn {
  constructor(history,draft,expectedIdentity=null,identityPolicy=null){this.history=copy(history);this.draft=copy(draft);this.stream=new CompletionStream(expectedIdentity,identityPolicy);this.committed=false;}
  feed(chunk){this.stream.feed(chunk);}
  cancel(){this.stream.cancel();}
  commit(observedIdentity=null){if(this.stream.expectedIdentity!==null)require(this.stream.identityPolicy.same(this.stream.expectedIdentity,observedIdentity),'runtime changed or unavailable before history commit');require(!this.committed,'turn already committed');const result=this.stream.finish();require(result.choices.length===1,'interactive turn requires one selected response');this.history.push(copy(this.draft),result.choices[0].message);this.committed=true;return result;}
}
