"""Small adapter over existing manager guards. No new owner authority."""
import json
import importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location("t24_binding",Path(__file__).with_name("bootstrap_binding.py"))
binding=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(binding)

def exact(a,b):return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)
def check_confirmed(expected,current):
    if not isinstance(expected,dict) or not isinstance(current,dict):raise ValueError('owner snapshot missing')
    for key in ('pid','created','exe','config','attempt','runtime_epoch','bundle_id','snapshot_id'):
        if key not in expected or key not in current or not exact(expected[key],current[key]):raise ValueError('owner changed: '+key)
    if current.get('runtime_provider')!='t24_fixture':raise ValueError('adapter fixture provider only')
    return current

def check_handshake(state,snapshot,hello,manager):
    if not isinstance(hello,dict) or hello.get('scope')!='t24-owner-fixture' or hello.get('generation_qualified') is not False:raise ValueError('fixture handshake required')
    binding.require_target_unchanged(snapshot)
    target=snapshot['target']
    for key,value in [('snapshot_id',snapshot['snapshot_id']),('attempt',snapshot['attempt']),('runtime_epoch',target['runtime_epoch']),('bundle_id',target['bundle_id']),('model',target['model_id']),('context',target['context']),('pid',state['pid']),('created',state['created']),('exe',state['exe']),('port',manager.PORT)]:
        if key not in hello or not exact(hello[key],value):raise ValueError('handshake binding: '+key)
    for key in ('snapshot_id','attempt','runtime_epoch','bundle_id'):
        if not exact(state[key],hello[key]):raise ValueError('state binding: '+key)
    manager.owned(state);manager.verified_cohort(state);manager.require_owned_listener(state)
    return dict(scope='t24-owner-fixture',generation_qualified=False)

def require_cleanup_listener(manager,state):
    status=manager.process_identity_status(state,require_command=True)
    root=manager.require_identity(status) # Unknown always rejects.
    if root is not None:
        return manager.require_owned_listener(state,allow_absent=True)
    # Root independently exited. Preserve the existing saved-birth cleanup path,
    # while retaining listener exclusion before any child termination.
    if manager.process_presence(state['pid'])!='gone':raise manager.OwnershipUnverifiable('root absence not independently confirmed')
    identities={}
    for row in state.get('owned_identities',[]):
        process=manager.require_identity(manager.process_identity_status(row))
        if process is None:continue
        identities[process.pid]=manager.captured_identity(process)
        for child in manager.descendants(process,state['config']):identities[child.pid]=manager.captured_identity(child)
    listeners=[c for c in manager.psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==manager.PORT and c.status==manager.psutil.CONN_LISTEN]
    for listener in listeners:
        if listener.pid not in identities:raise manager.OwnershipUnverifiable('listener outside saved verified cohort')
        manager.fresh_cleanup_candidate(identities[listener.pid])
    return bool(listeners)

def stop_confirmed(manager,expected,snapshot):
    with manager.state_lock():
        current=manager.read_state();check_confirmed(expected,current)
        binding.require_target_unchanged(snapshot)
        for key in ('snapshot_id','attempt'):
            if not exact(current[key],snapshot[key]):raise ValueError('stop snapshot changed')
        try:
            require_cleanup_listener(manager,current)
            stopped=manager.stop_owned(current)
            manager.check_port_available(manager.PORT)
        except Exception as error:
            current.update(phase='cleanup_pending',cleanup_error=str(error));manager.save(current);raise
        current.update(phase='stopped');manager.save(current);return stopped


def start_fixture(manager,snapshot,spawn,observe,await_hello):
    """Test/provider adapter transaction; callbacks never invoke official start.

    Existing manager state is the only tracking authority. The caller holds the
    existing outer CLI lock; this function holds its existing inner state lock.
    """
    with manager.state_lock():
        binding.require_target_unchanged(snapshot)
        previous=manager.read_state()
        if previous and manager.runtime_active(previous):raise RuntimeError('existing owned runtime still active')
        t=snapshot['target']
        state=dict(config=t['profile'],model=t['model_id'],context=t['context'],runtime_epoch=t['runtime_epoch'],
                   bundle_id=t['bundle_id'],snapshot_id=snapshot['snapshot_id'],attempt=snapshot['attempt'],
                   runtime_provider='t24_fixture',phase='starting',owned_identities=[])
        manager.save(state) # Intent replaces any old READY before Popen.
        process=None;observation=dict(identities=[],unknown=[],errors=[])
        try:
            process=spawn()
            root,observation=observe(process)
            state.update(root,phase='loading',owned_identities=observation['identities'],spawn_observation=observation)
            manager.save(state) # Retained Popen + birth observed before waiting.
            hello=await_hello(process,state)
            check_handshake(state,snapshot,hello,manager)
            state['phase']='ready';manager.save(state)
            return state,hello,process
        except Exception as error:
            report=dict(status='completed')
            if process is not None:
                try:report=manager.cleanup_spawn_handle(process,observation,t['profile'],include_identities=bool(observation['identities']))
                except Exception as cleanup_error:report=dict(status='failed',error=str(cleanup_error))
            state.update(phase='failed' if report.get('status')=='completed' else 'cleanup_pending',error=str(error),cleanup=report)
            manager.save(state)
            raise
