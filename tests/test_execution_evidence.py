import asyncio,json
from types import SimpleNamespace
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine
from qtpy_ai_sidecar.mcp_client import MCPHub
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def test_readiness_finalization_uses_measured_evidence_and_skips_manual_help():
    host=PyFiguresAdapter('unused');calls=[]
    def request(op,args):
        calls.append(op)
        return {'status':'blocked','blockers':['[FAIL] example panel: 417 pixels at target gives 173 DPI'],'read_only':True}
    host.request=request
    result=host.finalize_response('Could you check whether this is ready to submit?','Yes, ready.',{})
    assert 'not ready' in result['content'] and '173 DPI' in result['content']
    assert host.finalize_response('How do I check submission readiness manually?','instructions',{}) is None
    assert host.finalize_response('Make the selected letter blue','done',{}) is None
    assert calls==['submission_review','manual_guide']
    assert '173 DPI' in host.finalize_response('Would you submit this to a journal as it stands?','Yes.',{})['content']
    host.validate_tool_call('use_pyfigures_tool',{'tool_name':'review_submission_readiness','arguments':{}},{},'Assess this please')
    assert '173 DPI' in host.finalize_response('Assess this please','Looks good.',{})['content']

def test_engine_never_displays_unverified_ready_reply(tmp_path):
    host=PyFiguresAdapter('unused')
    host.context=lambda:{}
    host.begin=lambda *a:{}
    host.finish=lambda *a:{}
    host.request=lambda *a:{'status':'blocked','blockers':['[FAIL] measured resolution below target']}
    class Model:
        async def complete(self,*a,**kw):return {'role':'assistant','content':'Yes, ready for submission.'},{}
    engine=Engine(Config(state_dir=str(tmp_path)),host,backend=Model())
    events=[]
    asyncio.run(engine.turn('Is this ready for publication?',lambda *a:events.append(a)))
    assert any(k=='assistant' and 'not ready' in v for k,v in events)
    assert not any(k=='assistant' and 'Yes, ready' in v for k,v in events)
    assert 'model_reply_before_verification' in engine.journal.path.read_text()

def test_unchanged_discovery_is_bounded_without_mutations(tmp_path):
    class Hub:
        instructions=[]
        def __init__(self,*a):
            self.calls=0
            self.tools={'id':('demo',None,SimpleNamespace(name='find_catalog_tools',annotations=SimpleNamespace(readOnlyHint=True)))}
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def model_tools(self):return []
        def direct_ids(self):return {'find_catalog_tools':'id'}
        is_discovery=MCPHub.is_discovery
        async def execute(self,*a):
            self.calls+=1
            return {'is_error':False,'content':'same catalog'}
    class Model:
        calls=0
        async def complete(self,messages,tools,cancel,emit,final_only=False):
            self.calls+=1
            if final_only:return {'role':'assistant','content':'Discovery is unchanged; work remains unresolved.'},{}
            return {'role':'assistant','content':'','tool_calls':[{'id':str(self.calls),'type':'function','function':{'name':'find_catalog_tools','arguments':'{}'}}]},{}
    model=Model();hub=Hub()
    engine=Engine(Config(state_dir=str(tmp_path)),backend=model,hub_factory=lambda *a:hub)
    asyncio.run(engine.turn('Find what can do this',lambda *a:None))
    assert hub.calls==3 and model.calls==4
    assert 'discovery_loop_stopped' in engine.journal.path.read_text()

def test_step_budget_is_bounded_user_controlled_and_persistent(tmp_path):
    assert Config().max_steps==32
    assert Config(max_steps=12).max_steps==12
    config=Config(state_dir=str(tmp_path),max_steps=17)
    config.save_performance()
    profile=tmp_path/'profile.json'
    profile.write_text(json.dumps({'state_dir':str(tmp_path)}))
    assert Config.load(profile).max_steps==17


def test_false_bold_success_is_replaced_by_actual_readback():
    from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *args:{'panels':[{'panel_id':'0/0','letters':[{'text':'a','bold':False}]}]}
    result=adapter.finalize_response('Make all automatic panel letters bold.','Result: All letters have been set to bold.',{})
    assert result['evidence']['status']=='not_verified'
    assert 'cannot confirm' in result['content']
    adapter.request=lambda *args:{'panels':[{'panel_id':'0/0','letters':[{'text':'a','bold':True}]}]}
    assert adapter.finalize_response('Make all automatic panel letters bold.','Done.',{}) is None

def test_style_readback_uses_only_selected_scope():
    from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *args:{'panels':[{'panel_id':'0/0','letters':[{'text':'a','italic':True}]},{'panel_id':'0/1','letters':[{'text':'b','italic':False}]}]}
    state={'selection':{'selected_panels':[{'panel_id':'0/0'}]}}
    assert adapter.finalize_response('Make this letter italic.','Done.',state) is None

def test_annotation_style_request_preserving_letters_is_not_reinterpreted():
    from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
    adapter=PyFiguresAdapter('unused')
    assert adapter.finalize_response('Make the note bold, keep all panel letters unchanged.','Done.',{}) is None
