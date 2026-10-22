// Pure family policy. Legacy callers keep their existing policy when this returns null.
export const ABI='strata-client-family/v1';
export const SDK_LEVELS=Object.freeze(['off','minimal','low','medium','high','xhigh','max']);
const MAP=Object.freeze({off:'none',minimal:'minimal',low:'low',medium:'medium',high:'high',xhigh:'xhigh',max:'max'});
export function thinkingMap(family){return family==='deepseek41'?{...MAP}:null;}
export function supportsContext(context,descriptor,presets){
 if(!Number.isSafeInteger(context))return false;
 if(descriptor?.family==='deepseek41')return context>=descriptor.context_domain.minimum&&context<=descriptor.context_domain.maximum;
 return presets.includes(context);
}
export function assertSameAuthority(expected,active){
 if(expected?.family!=='deepseek41'||active?.family!=='deepseek41')throw new Error('Family authority unavailable; recheck or reselect runtime');
 for(const key of ['runtime_epoch','bundle_id','package_id','config_sha256','native']){
  if(expected[key]==null||active[key]==null||JSON.stringify(expected[key])!==JSON.stringify(active[key]))throw new Error('Selected runtime changed; recheck or reselect runtime');
 }
 for(const binding of [expected,active]){
  if(typeof binding.runtime_epoch!=='string'||!(/^[1-9][0-9]*$/).test(binding.runtime_epoch))throw new Error('Exact runtime epoch unavailable');
  const argv=binding.native?.command;
  if(!Array.isArray(argv)||argv.filter(x=>x==='--runtime-epoch').length!==1||argv[argv.indexOf('--runtime-epoch')+1]!==binding.runtime_epoch)throw new Error('Native epoch argv mismatch');
 }
 return true;
}
