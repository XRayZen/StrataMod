// In-process mocks only: never import Playwright or launch a browser/HTTP server.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

// Import the actual module with test-owned fixed bindings. The opaque sentinel
// is not an image; no private RefImage file, browser or HTTP is opened.
const fixtureRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
fs.mkdirSync(path.join(fixtureRoot,'.vision-tmp'),{recursive:true});
const directory = fs.mkdtempSync(path.join(fixtureRoot,'.vision-tmp/webui-mock-'));
const fixtureImage = path.join(directory,'opaque-sentinel.jpeg');
const sentinel = Buffer.from('synthetic-non-image-bytes-for-routing-only');
fs.writeFileSync(fixtureImage,sentinel);
const fixtureEdge = path.join(directory,'edge.exe');fs.writeFileSync(fixtureEdge,'not-an-executable');
const sentinelSha = crypto.createHash('sha256').update(sentinel).digest('hex');
let moduleSource = fs.readFileSync(new URL('./webui_upload.mjs',import.meta.url),'utf8');
for (const [name,value] of Object.entries({ROOT:fixtureRoot,EDGE:fixtureEdge,NODE:process.execPath,
                                         REFERENCE_IMAGE:fixtureImage,REFERENCE_SHA:sentinelSha})) {
  const pattern = new RegExp(`export const ${name} = [^;]+;`);
  assert(pattern.test(moduleSource));moduleSource=moduleSource.replace(pattern,`export const ${name} = ${JSON.stringify(value)};`);
}
const {ROOT,EDGE,REFERENCE_IMAGE,REFERENCE_SHA,sha,validateInput,createRequestGate,parseResponse,runUpload} =
  await import('data:text/javascript;charset=utf-8,'+encodeURIComponent(moduleSource));
const priorTemp=process.env.TEMP,priorTmp=process.env.TMP;
process.env.TEMP=process.env.TMP=path.join(ROOT,'.vision-tmp');
let serial = 0;
const image = path.resolve(REFERENCE_IMAGE);
const imageBytes = fs.readFileSync(image), imageUrl = 'data:image/jpeg;base64,' + imageBytes.toString('base64');
assert.equal(sha(imageBytes), REFERENCE_SHA);
function input() { return {url:'http://127.0.0.1:18080/',browser_exe:EDGE,
  profile_dir:path.join(directory,'profile-'+serial++),image_path:image,image_sha256:sha(imageBytes),
  prompt:'Observe the people, clothing, room and touched furniture.',max_tokens:128,deadline_seconds:120}; }
function body(config) { return {model:'fixture',messages:[{role:'user',content:[{type:'text',text:config.prompt},
  {type:'image_url',image_url:{url:imageUrl}}]}],stream:true,reasoning_effort:'none',temperature:0,seed:42,max_tokens:128}; }
function route(config, value=body(config), url=config.url+'v1/chat/completions', method='POST') {
  const request={url:()=>url,method:()=>method,postDataBuffer:()=>Buffer.from(JSON.stringify(value))};
  return {request:()=>request,continued:0,aborted:0,
    async continue(){this.continued++;},async abort(){this.aborted++;}};
}
const responseText='{"people":1,"hair":"orange","top":"white","scene":"bedroom","object":"bed","position":"right"}';
const responseBytes=Buffer.from('data: '+JSON.stringify({choices:[{delta:{content:responseText},finish_reason:null}]})+
  '\n\ndata: '+JSON.stringify({choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:200,completion_tokens:5}})+'\n\ndata: [DONE]\n\n');

test('preflight binds private paths, image hash, fixed URL/browser/limits', () => {
  assert.equal(validateInput(input()).max_tokens,128);
  for (const change of [{url:'http://127.0.0.1:18080/?q=auto'},{max_tokens:129},{deadline_seconds:121},
                        {profile_dir:directory},{profile_dir:path.join(ROOT,'outside')},
                        {image_path:path.join(ROOT,'README.md')},{image_path:path.join(directory,'other.jpeg')},
                        {image_sha256:'0'.repeat(64)},
                        {browser_exe:process.execPath},{prompt:' x '}]) {
    assert.throws(()=>validateInput({...input(),...change}));
  }
  const previous=process.env.TEMP;
  try { process.env.TEMP=path.dirname(ROOT);assert.throws(()=>validateInput(input())); }
  finally { process.env.TEMP=previous; }
});
test('one real wire allowed; concurrent second write aborts before continue',async()=>{
  const config=input(),events=[],errors=[];
  const gate=createRequestGate(config,e=>events.push(e),e=>errors.push(e));
  const first=route(config),second=route(config);
  await Promise.all([gate.route(first),gate.route(second)]);
  assert.equal(first.continued,1);assert.equal(second.continued,0);assert.equal(second.aborted,1);
  assert.equal(gate.sent,1);assert.equal(gate.attempted,2);assert.equal(errors.length,1);
  const event=events[0];assert.equal(event.type,'generation_request');assert.equal(event.count,1);
  assert.deepEqual(event.post_data_json,body(config));
  assert.equal(event.full_wire_sha256,sha(Buffer.from(event.post_data_utf8)));
});
test('wrong actual image/cap/MCP, shared write and external requests never send',async()=>{
  for (const mutate of [b=>{b.max_tokens=256;},b=>{b.strata_mcp=true;},b=>{b.n=2;},
                        b=>{b.messages[0].content[1].image_url.url='data:image/png;base64,AAAA';}]) {
    const config=input(),b=body(config);mutate(b);
    const r=route(config,b),errors=[];
    await createRequestGate(config,()=>{},e=>errors.push(e)).route(r);
    assert.equal(r.continued,0);assert.equal(r.aborted,1);assert.equal(errors.length,1);
  }
  for (const [url,method] of [['http://127.0.0.1:18080/settings','POST'],['https://example.invalid/','GET'],
                              ['http://127.0.0.1:18080/load','GET']]) {
    const config=input(),r=route(config,{},url,method);
    await createRequestGate(config,()=>{},()=>{}).route(r);assert.equal(r.continued,0);assert.equal(r.aborted,1);
  }
});
test('expired generation deadline refuses before the sole POST is continued',async()=>{
  const config={...input(),deadline_at:Date.now()-1},r=route(config),errors=[];
  await createRequestGate(config,()=>{},e=>errors.push(e)).route(r);
  assert.equal(r.continued,0);assert.equal(r.aborted,1);assert.equal(errors.length,1);
});
test('SSE requires actual successful terminal/usage and no extra DONE',()=>{
  assert.equal(parseResponse(responseBytes,200).content,responseText);
  for (const [bytes,status] of [[responseBytes,503],[Buffer.from('data: [DONE]\n'),200],
    [Buffer.concat([responseBytes,Buffer.from('data: [DONE]\n')]),200],
    [Buffer.from(responseBytes.toString().replace('"completion_tokens":5','"completion_tokens":0')),200]]) {
    assert.throws(()=>parseResponse(bytes,status));
  }
});

function fakeBrowser(config,{shared=false,closeError=false,finishedError=false}={}) {
  const values={'#s-max':'','#s-temp':'1','#s-seed':''},actions=[],waiters=[];
  let handler;
  const notify=response=>{for(const waiter of [...waiters]) if(waiter.predicate(response)){
    waiter.resolve(response);waiters.splice(waiters.indexOf(waiter),1);}};
  const page={setDefaultTimeout(){},waitForResponse(predicate){return new Promise(resolve=>waiters.push({predicate,resolve}));},
    async goto(){notify({url:()=>config.url+'health',async json(){return {images:true};}});},
    locator(selector){return {
      async click(){actions.push(['click',selector]);
        if(selector==='#sampling-btn')notify({url:()=>config.url+'settings',async json(){return {shared};}});
        if(selector==='#send-btn'){
          const r=route(config);await handler(r);
          if(r.continued)notify({url:r.request().url,request:r.request,async finished(){return finishedError?new Error('transport failed'):null;},
            async body(){return responseBytes;},status:()=>200});
        }
      },
      async fill(value){values[selector]=value;actions.push(['fill',selector,value]);},
      async press(){values[selector]='0';},async inputValue(){return values[selector];},
      async isVisible(){return false;},async setInputFiles(value){actions.push(['setInputFiles',value]);},
      async waitFor(){},async count(){return 0;},
      async innerText(){return selector==='#attachments .chip'?path.basename(config.image_path):responseText;},
      async getAttribute(){return imageUrl;},
    };}};
  const context={async route(pattern,callback){handler=callback;},pages:()=>[page],
    async close(){actions.push(['close']);if(closeError)throw new Error('close refused');}};
  return {actions,chromium:{async launchPersistentContext(profile,options){actions.push(['launch',profile,options]);return context;}}};
}
test('mock UI follows file input and public max controls, records honest chip/UI/API evidence',async()=>{
  const config=input(),fake=fakeBrowser(config),events=[];
  assert.equal(await runUpload(config,fake.chromium,e=>events.push(e)),true);
  assert.deepEqual(events.map(e=>e.type),['attachment','generation_request','final_answer','closed']);
  assert.equal(events[0].preview.kind,'filename_chip');assert.equal(events[0].preview.image_thumbnail,false);
  assert.equal(events[2].api_status,200);assert.equal(events[2].generation_count,1);
  assert.equal(events[3].cleanup_verified,false);assert.equal(events[3].process_proof_owner,'runtime');
  assert(fake.actions.some(a=>a[0]==='setInputFiles'&&a[1]===image));
  assert(fake.actions.some(a=>a[0]==='fill'&&a[1]==='#s-max'&&a[2]==='128'));
  assert.equal(fake.actions[0][2].serviceWorkers,'block');
  assert(fake.actions[0][2].env.TEMP.startsWith(config.profile_dir));
});
test('shared defaults refuse before any generation and close is never cohort proof',async()=>{
  const config=input(),fake=fakeBrowser(config,{shared:true}),events=[];
  assert.equal(await runUpload(config,fake.chromium,e=>events.push(e)),false);
  assert(events.some(e=>e.type==='error'&&e.message.includes('shared')));
  assert(!events.some(e=>e.type==='generation_request'));
  assert(!fake.actions.some(a=>a[1]==='#s-apply'));
});
test('context close refusal and transport failure cannot return successful exit result',async()=>{
  for(const options of [{closeError:true},{finishedError:true}]){
    const config=input(),fake=fakeBrowser(config,options),events=[];
    assert.equal(await runUpload(config,fake.chromium,e=>events.push(e)),false);
    assert(events.some(e=>e.type==='error'));
    assert.equal(events.at(-1).cleanup_verified,false);
  }
});
test.after(()=>{
  const absolute=path.resolve(directory);
  assert(absolute.startsWith(path.join(ROOT,'.vision-tmp','webui-mock-')));
  fs.rmSync(absolute,{recursive:true,force:false});
  if(priorTemp===undefined)delete process.env.TEMP;else process.env.TEMP=priorTemp;
  if(priorTmp===undefined)delete process.env.TMP;else process.env.TMP=priorTmp;
});
