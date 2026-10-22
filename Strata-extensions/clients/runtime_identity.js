// HTTP identity does not grant DATA process ownership.
export function normalizeIdentity(value) {
  if(!value||typeof value!=='object'||Array.isArray(value)||value.schema!=='strata-runtime-identity/v1'||value.family!=='deepseek41')throw new Error('Runtime identity unavailable');
  for(const key of ['bundle_id','package_id'])if(typeof value[key]!=='string'||!(/^[0-9a-f]{64}$/).test(value[key]))throw new Error('Invalid runtime '+key);
  const epoch=value.runtime_epoch;
  if(typeof epoch!=='string'||!(/^[1-9][0-9]*$/).test(epoch)||epoch.length>20||BigInt(epoch)>18446744073709551615n)throw new Error('Lossless runtime epoch required');
  if(!Number.isSafeInteger(value.context)||value.context<1||value.context>1048576||typeof value.model!=='string'||!value.model)throw new Error('Invalid runtime model/context');
  return Object.fromEntries(['schema','family','bundle_id','package_id','runtime_epoch','model','context'].map(key=>[key,value[key]]));
}
export function sameIdentity(expected,observed) {
  try{return JSON.stringify(normalizeIdentity(expected))===JSON.stringify(normalizeIdentity(observed));}catch{return false;}
}
export function historyForContext(history) {return history.filter(message=>!message.strata_incomplete).map(message=>structuredClone(message));}
