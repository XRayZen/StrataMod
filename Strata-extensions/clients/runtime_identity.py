"""HTTP family identity only. This does not grant DATA process ownership."""
import copy
import re

FIELDS=('schema','family','bundle_id','package_id','runtime_epoch','model','context')

def normalize(value):
    if type(value)is not dict:raise ValueError('runtime identity unavailable')
    if value.get('schema')!='strata-runtime-identity/v1' or value.get('family')!='deepseek41':raise ValueError('runtime identity family/schema')
    for key in ('bundle_id','package_id'):
        if type(value.get(key))is not str or re.fullmatch('[0-9a-f]{64}',value[key])is None:raise ValueError('runtime identity '+key)
    epoch=value.get('runtime_epoch')
    if type(epoch)is not str or re.fullmatch('[1-9][0-9]*',epoch)is None or len(epoch)>20 or int(epoch)>2**64-1:raise ValueError('lossless runtime epoch required')
    if type(value.get('context'))is not int or not 1<=value['context']<=1048576:raise ValueError('runtime context')
    if type(value.get('model'))is not str or not value['model']:raise ValueError('runtime model')
    return {key:copy.deepcopy(value[key])for key in FIELDS}

def same(expected,observed):
    try:return normalize(expected)==normalize(observed)
    except ValueError:return False

def history_for_context(history):
    # Untagged and completed old turns remain ordinary reusable history.
    return [copy.deepcopy(message)for message in history if not message.get('strata_incomplete',False)]


def from_config(config):
    epoch=config.get('runtime_epoch')
    if type(epoch)is not int or not 0<epoch<=2**64-1:raise ValueError('exact launch epoch required')
    return normalize(dict(schema='strata-runtime-identity/v1',family=config.get('family'),
                          bundle_id=config.get('bundle_id'),package_id=(config.get('runtime_package')or{}).get('id'),
                          runtime_epoch=str(epoch),model=config.get('model_name'),context=config.get('context')))


def install(server,config):
    """Add HTTP metadata after the selected family hook; preserve its generators."""
    if config.get('family')!='deepseek41':return
    identity=from_config(config)
    installed=getattr(server,'_deepseek_runtime_identity',None)
    if installed is not None:
        if not same(installed,identity):raise ValueError('cannot replace identity of an installed server')
        return
    import functools
    metrics=server.Service.metrics
    chunks=server.openai_chunks
    @functools.wraps(metrics)
    def family_metrics(self,*args,**kwargs):
        result=metrics(self,*args,**kwargs)
        return dict(result,strata_runtime=copy.deepcopy(identity))if type(result)is dict else result
    @functools.wraps(chunks)
    def family_chunks(*args,**kwargs):
        for chunk in chunks(*args,**kwargs):
            yield dict(chunk,strata_runtime=copy.deepcopy(identity))if type(chunk)is dict else chunk
    server.Service.metrics=family_metrics
    server.openai_chunks=family_chunks
    server._deepseek_runtime_identity=copy.deepcopy(identity)
