import asyncio
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine
from qtpy_ai_sidecar.qwen_protocol import ReplyProtocolError

def test_repeated_invalid_tool_names_recover_without_submission(tmp_path):
    class Hub:
        instructions=[]
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def model_tools(self):return [{'type':'function','function':{'name':'wrapper','parameters':{'properties':{'tool_name':{},'arguments':{}}}}}]
        def direct_ids(self):return {}
        async def execute(self,*a):raise AssertionError('Rejected call executed')
    class Model:
        calls=0
        async def complete(self,messages,tools,cancel,emit,final_only=False):
            self.calls+=1
            if self.calls==2:
                assert 'advertised dispatcher wrapper' in messages[-1]['content']
                assert 'tool_name=\"inner\"' in messages[-1]['content']
            if self.calls<=2:
                raise ReplyProtocolError('Unknown function in model reply; no tool submitted: inner')
            assert tools==[] and final_only
            return {'role':'assistant','content':'The edit remains unresolved; no tool was submitted.'},{}
    model=Model()
    engine=Engine(Config(state_dir=str(tmp_path)),backend=model,hub_factory=lambda *a:Hub())
    events=[]
    asyncio.run(engine.turn('Do this',lambda *e:events.append(e)))
    assert model.calls==3
    assert any(k=='assistant' and 'unresolved' in v for k,v in events)
    assert not any(k=='tool_call' for k,v in events)
    assert 'protocol_text_recovery' in engine.journal.path.read_text()
