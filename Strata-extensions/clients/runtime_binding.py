"""Pure DeepSeek client declaration/observation helpers; caller retains ownership checks."""


import copy


import math


import re


ABI='strata-client-family/v1'


FAMILY='deepseek41'

SDK_EFFORT_MAP=dict(off='none',minimal='minimal',low='low',medium='medium',high='high',xhigh='xhigh',max='max')



def thinking_map(family):return dict(SDK_EFFORT_MAP)if family==FAMILY else None





def descriptor(model,item,presets):


 if item.get('family')!=FAMILY:return None


 return dict(family=FAMILY,model=model,presets=list(presets),context_domain=dict(minimum=1,maximum=1048576))





def supports_context(context,decl,presets):


 if type(context)is not int:return False


 if decl is not None and decl.get('family')==FAMILY:


  domain=decl['context_domain'];return domain['minimum']<=context<=domain['maximum']


 return context in presets





def validate_models(rows,model,context,aliases):


 """Exactly one canonical row; only declared aliases with matching metadata."""


 if type(context)is not int or not 1<=context<=1048576:raise ValueError('invalid family context')
 if type(rows)is not list or not rows:raise ValueError('model rows unavailable')


 seen=set();canonical=0


 for row in rows:


  if type(row)is not dict:raise ValueError('invalid model row')


  name=row.get('id')


  if type(name)is not str or name in seen:raise ValueError('duplicate model identity')


  seen.add(name)


  if name==model:


   canonical+=1


   if row.get('alias_of')is not None:raise ValueError('canonical row is an alias')


  elif name not in aliases or row.get('alias_of')!=model:raise ValueError('undeclared or foreign alias')


  if type(row.get('meta',{}).get('n_ctx'))is not int or row['meta']['n_ctx']!=context or row.get('status',{}).get('value')!='loaded':raise ValueError('model/context/readiness mismatch')


 if canonical!=1:raise ValueError('one canonical model required')


 return True





def _require(condition,message):


 if not condition:raise ValueError(message)





def _hash(value):return type(value)is str and re.fullmatch('[0-9a-f]{64}',value)is not None





def observed_authority(state,observation):


 """Normalize an already fresh manager observation, never infer authority from HTTP."""


 _require(state.get('family')==FAMILY and state.get('phase')=='ready','family runtime not READY')


 launch=state.get('launch_binding');_require(type(launch)is dict,'missing launch binding')


 _require(type(observation)is dict and observation.get('identity_source')=='fresh owned native exact argv','fresh native observation required')


 epoch=launch.get('runtime_epoch');bundle=launch.get('bundle_id');package=launch.get('runtime_package')or{}


 _require(type(epoch)is int and epoch>0 and type(observation.get('runtime_epoch'))is int and observation['runtime_epoch']==epoch,'runtime epoch mismatch')


 _require(_hash(bundle)and observation.get('bundle_id')==bundle,'native bundle mismatch')


 _require(_hash(launch.get('config_sha256'))and launch.get('config')==state.get('config'),'config binding mismatch')


 _require(_hash(package.get('id')),'package identity unavailable')


 native=observation.get('native')or{};identity=native.get('identity')or{};command=native.get('command')


 _require(type(command)is list and command and all(type(x)is str for x in command),'native command unavailable')
 _require(command.count('--runtime-epoch')==1,'native epoch option unavailable')
 index=command.index('--runtime-epoch')
 _require(index+1<len(command)and command[index+1]==str(epoch),'native epoch argv mismatch')


 _require(identity in state.get('owned_identities',[]),'native identity outside owned cohort')


 for row in (state,identity):


  _require(type(row.get('pid'))is int and row['pid']>0 and type(row.get('created'))in(int,float)and math.isfinite(row['created'])and row['created']>0,'invalid process birth')


 native_normalized={k:copy.deepcopy(identity.get(k))for k in ('pid','created','exe')};native_normalized['command']=list(command)


 return dict(abi=ABI,family=FAMILY,runtime_epoch=str(epoch),bundle_id=bundle,package_id=package['id'],config_sha256=launch['config_sha256'],config=state['config'],model=state['model'],context=state['context'],owner=dict(pid=state['pid'],created=state['created']),native=native_normalized,primary_pci=observation.get('primary_pci'),native_INFO_identity_fields=copy.deepcopy(observation.get('native_INFO_identity_fields')or{k:None for k in ('bundle_id','runtime_epoch','primary_pci')}))


