"""Read-only reuse must not suppress edits, stale reads after edits, or safety budgets."""
import asyncio
import json
from itertools import count
from types import SimpleNamespace
import pytest
from qtpy_ai_sidecar.read_cache import TurnReadCache
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine
from qtpy_ai_sidecar.mcp_client import MCPHub
from qtpy_ai_sidecar.adapters import NullAdapter
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def test_cache_keys_are_server_tool_and_argument_specific():
    assert TurnReadCache.key('a',{'x':1,'y':2})==TurnReadCache.key('a',{'y':2,'x':1})
    assert TurnReadCache.key('a',{'x':1})!=TurnReadCache.key('b',{'x':1})
    assert TurnReadCache.key('a',{'x':1})!=TurnReadCache.key('a',{'x':2})
    assert TurnReadCache.key('a',{'x':float('nan')}) is None

def test_reuse_preserves_data_errors_and_original_objects():
    cache=TurnReadCache();key=cache.key('read',{})
    result={'is_error':True,'error':'Unknown field','structured':{'items':[1]}}
    cache.remember(key,result)
    first=cache.lookup(key)
    assert first['is_error'] is True and first['error']=='Unknown field'
    assert 'Already returned above; answer from it' in first['cache_notice']
    first['structured']['items'].append(2)
    assert cache.lookup(key)['structured']['items']==[1]
    assert result=={'is_error':True,'error':'Unknown field','structured':{'items':[1]}}
    assert cache.repeated(key)

def test_invalidation_and_capacity():
    cache=TurnReadCache(limit=1)
    a,b=cache.key('a',{}),cache.key('b',{})
    cache.remember(a,{'content':'a'});cache.remember(b,{'content':'b'})
    assert cache.lookup(a) is None and cache.lookup(b)['content']=='b'
    cache.invalidate()
    assert cache.lookup(b) is None and not cache.repeated(b)

def test_application_policy_never_caches_inner_mutations_or_gui_actions():
    adapter=PyFiguresAdapter('unused')
    assert adapter.is_read_only_call('use_pyfigures_tool',{'tool_name':'inspect_native_gui'}) is True
    for name in ('edit_panel_letters','set_image_property','undo_redo','select_live_objects','open_annotation_editor','show_me_how'):
        assert adapter.is_read_only_call('use_pyfigures_tool',{'tool_name':name}) is False
    for name in ('select_live_objects','undo_redo','show_me_how','open_native_menu'):
        assert adapter.is_read_only_call(name,{}) is False

class Hub:
    instructions=[]
    is_read_only=MCPHub.is_read_only
    def __init__(self,read_only=True,fail_mutation=False):
        self.reads=0;self.mutations=0;self.value=0;self.fail_mutation=fail_mutation
        self.tools={
            'r':('test',None,SimpleNamespace(name='inspect_values',annotations=SimpleNamespace(readOnlyHint=read_only,destructiveHint=False))),
            'm':('test',None,SimpleNamespace(name='change_values',annotations=SimpleNamespace(readOnlyHint=False,destructiveHint=True)))}
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def model_tools(self):return []
    def direct_ids(self):return {'inspect_values':'r','change_values':'m'}
    def is_discovery(self,ident):return False
    async def execute(self,ident,arguments,emit):
        if ident=='r':
            self.reads+=1
            return {'is_error':False,'content':str(self.value)}
        self.mutations+=1
        if self.fail_mutation:return {'is_error':True,'error':'Refused safely'}
        self.value+=1
        return {'is_error':False,'content':'changed'}

_call_ids=count()
def call(name='inspect_values',args=None):
    return {'role':'assistant','content':'','tool_calls':[{'id':'call-'+str(next(_call_ids)),
            'type':'function','function':{'name':name,'arguments':json.dumps(args or {})}}]}
def answer(text='Verified answer.'):
    return {'role':'assistant','content':text}
class Model:
    def __init__(self,responses):
        self.responses=iter(responses);self.calls=0;self.recoveries=0
    async def complete(self,messages,tools,cancel,emit,final_only=False):
        self.calls+=1
        if final_only:
            self.recoveries+=1
            assert tools==[]
            return answer('Answer from earlier verified facts; unresolved work remains.'),{}
        return next(self.responses),{}
def engine(tmp_path,hub,model,max_steps=4,adapter=None):
    return Engine(Config(state_dir=str(tmp_path),max_steps=max_steps),adapter=adapter,
                  backend=model,hub_factory=lambda *_:hub)
def run(subject,text='Inspect the current values.'):
    events=[]
    asyncio.run(subject.turn(text,lambda k,v:events.append((k,v))))
    return events

def test_repeated_observation_runs_once_and_does_not_use_a_tool_step(tmp_path):
    hub=Hub();model=Model([call(args={'a':1,'b':2}),call(args={'b':2,'a':1}),answer()])
    subject=engine(tmp_path,hub,model,max_steps=2)
    events=run(subject)
    assert hub.reads==1 and model.calls==3
    assert len([v for k,v in events if k=='tool_cache_hit'])==1
    assert 'Already returned above' in subject.journal.path.read_text(encoding='utf-8')

def test_identical_mutations_are_never_cached(tmp_path):
    hub=Hub();model=Model([call('change_values'),call('change_values'),answer()])
    events=run(engine(tmp_path,hub,model))
    assert hub.mutations==2 and hub.value==2
    assert not any(k=='tool_cache_hit' for k,v in events)

@pytest.mark.parametrize('refused',[False,True])
def test_mutating_attempt_invalidates_earlier_read(tmp_path,refused):
    hub=Hub(fail_mutation=refused)
    model=Model([call(),call('change_values'),call(),answer()])
    events=run(engine(tmp_path,hub,model))
    assert hub.reads==2 and hub.mutations==1
    assert not any(k=='tool_cache_hit' for k,v in events)

def test_unknown_or_mutating_metadata_is_not_inferred_from_name(tmp_path):
    hub=Hub(read_only=False);model=Model([call(),call(),answer()])
    run(engine(tmp_path,hub,model))
    assert hub.reads==2

def test_repetition_is_bounded_with_one_text_only_recovery(tmp_path):
    hub=Hub();model=Model([call(),call(),call(),call()])
    subject=engine(tmp_path,hub,model,max_steps=2)
    run(subject)
    assert hub.reads==1 and hub.mutations==0
    assert model.calls==4 and model.recoveries==1
    assert not subject.uncertain

def test_cache_is_not_reused_across_human_turns(tmp_path):
    hub=Hub();model=Model([call(),answer(),call(),answer()])
    subject=engine(tmp_path,hub,model)
    run(subject);run(subject)
    assert hub.reads==2

def test_dispatcher_readonly_hint_cannot_hide_an_inner_edit(tmp_path):
    class Adapter(NullAdapter):
        is_read_only_call=PyFiguresAdapter.is_read_only_call
    hub=Hub()
    hub.tools={'d':('test',None,SimpleNamespace(name='use_pyfigures_tool',
        annotations=SimpleNamespace(readOnlyHint=True,destructiveHint=False)))}
    hub.direct_ids=lambda:{'use_pyfigures_tool':'d'}
    sent=[]
    async def execute(ident,args,emit):
        sent.append(args)
        return {'is_error':False,'content':'submitted'}
    hub.execute=execute
    mutation={'tool_name':'edit_panel_letters','arguments':{'scope':'all','color':'red'}}
    model=Model([call('use_pyfigures_tool',mutation),call('use_pyfigures_tool',mutation),answer()])
    run(engine(tmp_path,hub,model,adapter=Adapter()))
    assert len(sent)==2

def test_readonly_metadata_must_be_explicit_and_non_destructive():
    for annotations,wanted in [
        (None,False),
        (SimpleNamespace(),False),
        (SimpleNamespace(readOnlyHint=True,destructiveHint=True),False),
        (SimpleNamespace(readOnlyHint=True),True),
        (SimpleNamespace(readOnlyHint=False),False)]:
        fake=SimpleNamespace(tools={'x':('app',None,SimpleNamespace(annotations=annotations))})
        assert MCPHub.is_read_only(fake,'x') is wanted

def test_pending_background_results_are_not_frozen():
    cache=TurnReadCache();key=cache.key('poll',{})
    for result in ({'status':'queued'},{'content':json.dumps({'jobs':[{'status':'running'}]})},{'pending_refresh':True}):
        cache.remember(key,result)
        assert cache.lookup(key) is None
    cache.remember(key,{'content':json.dumps({'status':'ready'})})
    assert cache.lookup(key) is not None

def test_async_readonly_poll_can_become_ready_before_reuse(tmp_path):
    hub=Hub()
    async def execute(ident,args,emit):
        hub.reads+=1
        return {'is_error':False,'content':json.dumps({'status':'running' if hub.reads==1 else 'ready'})}
    hub.execute=execute
    model=Model([call(),call(),call(),answer()])
    events=run(engine(tmp_path,hub,model,max_steps=3))
    assert hub.reads==2 and model.calls==4
    assert len([v for k,v in events if k=='tool_cache_hit'])==1

def test_explicit_mutating_metadata_wins_over_app_name_allowlist(tmp_path):
    class Adapter(NullAdapter):
        is_read_only_call=PyFiguresAdapter.is_read_only_call
    hub=Hub(read_only=False)
    hub.tools['r'][2].name='inspect_figure'
    hub.direct_ids=lambda:{'inspect_figure':'r','change_values':'m'}
    model=Model([call('inspect_figure'),call('inspect_figure'),answer()])
    run(engine(tmp_path,hub,model,adapter=Adapter()))
    assert hub.reads==2

def test_epoch_is_part_of_the_observation_key():
    assert TurnReadCache.key('r',{},'revision1')!=TurnReadCache.key('r',{},'revision2')

def test_external_host_change_invalidates_observation_without_an_edit_call(tmp_path):
    class Adapter(NullAdapter):
        epoch=0
        def read_cache_epoch(self):return self.epoch
    adapter=Adapter();hub=Hub()
    class ExternalChangeModel(Model):
        async def complete(self,*args,**kwargs):
            if self.calls==1:adapter.epoch+=1
            return await super().complete(*args,**kwargs)
    model=ExternalChangeModel([call(),call(),answer()])
    run(engine(tmp_path,hub,model,adapter=adapter,max_steps=3))
    assert hub.reads==2

def test_pyfigures_epoch_tracks_selection_and_editor_without_edits():
    adapter=PyFiguresAdapter('unused')
    current={'session_id':'s','revision':1,'selection':{'token':'one'},'native_gui_jobs':[]}
    calls=[]
    def request(operation,*args):
        calls.append(operation)
        return dict(current)
    adapter.request=request
    before=adapter.read_cache_epoch()
    current['selection']={'token':'two'}
    assert adapter.read_cache_epoch()!=before
    assert calls==['inspect','inspect']
