import asyncio
import json
import sys
import threading
import zipfile
from pathlib import Path
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine
from qtpy_ai_sidecar.journal import Journal
from qtpy_ai_sidecar.mcp_client import MCPHub

DEMO = Path(__file__).resolve().parents[1] / 'examples' / 'demo_mcp.py'


def servers(path):
    return {'demo': {'command': sys.executable, 'args': ['-B', str(DEMO)], 'env': {'SIDECAR_DEMO_DOCUMENT': str(path)}}}


def test_real_stdio_mcp_roundtrip(tmp_path):
    async def run():
        async with MCPHub(servers(tmp_path / 'document.json')) as hub:
            assert len(hub.model_tools()) == 2
            found = hub.find('set all labels')
            ident = found['tools'][0]['tool_id']
            assert found['tools'][0]['arguments_schema']['required'] == ['color']
            result = await hub.execute(ident, {'color': 'white'}, lambda *args: None)
            assert not result['is_error']
            assert json.loads(result['content'])['verified_after']['color'] == 'white'
        async with MCPHub(servers(tmp_path / 'document.json')) as hub:
            item = hub.find('inspect')['tools'][0]
            result = await hub.execute(item['tool_id'], {}, lambda *args: None)
            assert json.loads(result['content'])['color'] == 'white'
    asyncio.run(run())


class ScriptedModel:
    def __init__(self):
        self.step = 0

    async def complete(self, messages, tools, cancel, emit, max_tokens=None):
        self.step += 1
        if self.step == 1:
            tool = next(t['function']['name'] for t in tools if 'set_all_labels' in t['function']['name'])
            return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'one', 'type': 'function',
                'function': {'name': tool, 'arguments': '{"color":"white"}'}}]}, {}
        return {'role': 'assistant', 'content': 'All four labels are white, verified by the tool result.'}, {'prompt_tokens': 321}


def test_engine_real_mcp_one_bulk_edit(tmp_path):
    config = Config(state_dir=str(tmp_path / 'state'), servers=servers(tmp_path / 'doc.json'))
    engine = Engine(config, backend=ScriptedModel())
    events = []
    asyncio.run(engine.turn('Make all labels white', lambda *args: events.append(args)))
    assert json.loads((tmp_path / 'doc.json').read_text())['color'] == 'white'
    records = [json.loads(line) for line in engine.journal.path.read_text().splitlines()]
    assert sum(e['kind'] == 'operation_intent' for e in records) == 1
    assert any(e[0] == 'assistant' and 'white' in e[1] for e in events)


def test_compression_preserves_recent_choices_and_raw_log(tmp_path):
    class Summary:
        async def complete(self, *args, **kwargs):
            return {'role': 'assistant', 'content': 'User requires white labels; preserve accepted layout. No pending edits.'}, {}
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Summary())
    for i in range(20):
        engine.messages.extend([{'role': 'user', 'content': 'Keep white labels. ' * 80}, {'role': 'assistant', 'content': 'Verified step ' + str(i)}])
    engine.messages.extend([{'role': 'assistant', 'content': 'Which?\n1. Images\n2. Labels'}, {'role': 'user', 'content': '2'}])
    recent = engine.messages[-10:]
    engine.journal.record('user', 'Raw original conversation retained')
    before = len(json.dumps(engine.messages))
    asyncio.run(engine.compact(lambda *args: None))
    assert engine.messages[-10:] == recent
    assert len(json.dumps(engine.messages)) < before
    assert 'Raw original conversation retained' in engine.journal.path.read_text()


def test_export_redacts_credentials(tmp_path):
    journal = Journal(tmp_path)
    journal.record('tool_result', {'api_key': 'secret', 'text': 'Bearer private-key', 'prompt_tokens': 100})
    path = tmp_path / 'export.zip'
    journal.export(path)
    with zipfile.ZipFile(path) as archive:
        data = archive.read('events.jsonl').decode()
        assert 'private-key' not in data and '"secret"' not in data
        assert '100' in data
        assert 'conversation.md' in archive.namelist()


def test_context_limit_prevents_submission(tmp_path):
    engine = Engine(Config(state_dir=str(tmp_path), context_tokens=2048, output_tokens=1024))
    engine.messages.append({'role': 'user', 'content': 'a' * 10000})
    import pytest
    with pytest.raises(ValueError, match='context is full'):
        asyncio.run(engine.turn('edit', lambda *args: None))


def test_empty_reply_recovers_without_replaying_edit(tmp_path):
    from qtpy_ai_sidecar.backend import EmptyModelReply
    class Model(ScriptedModel):
        async def complete(self, messages, tools, cancel, emit, max_tokens=None, final_only=False):
            if final_only:
                assert tools == []
                return {'role': 'assistant', 'content': 'Verified labels are white.'}, {}
            if self.step == 1:
                self.step += 1
                raise EmptyModelReply('No final reply')
            return await super().complete(messages, tools, cancel, emit)
    config = Config(state_dir=str(tmp_path/'state'), servers=servers(tmp_path/'doc.json'))
    model = Model()
    engine = Engine(config, backend=model)
    events = []
    asyncio.run(engine.turn('Make all labels white', lambda *args: events.append(args)))
    records = [json.loads(line) for line in engine.journal.path.read_text().splitlines()]
    assert sum(e['kind'] == 'operation_intent' for e in records) == 1
    assert sum(e['kind'] == 'reply_recovery' for e in records) == 1
    assert any(kind == 'assistant' and 'white' in value for kind,value in events)


def test_taskgroup_error_exposes_leaf():
    import sys
    if sys.version_info < (3,11):
        return
    from qtpy_ai_sidecar.errors import error_details
    error = ExceptionGroup('outer', [ExceptionGroup('inner', [RuntimeError('Actual model error')])])
    assert error_details(error) == 'Actual model error'


def test_tool_history_and_ids_survive_followup(tmp_path):
    class Followup:
        names=[]
        async def complete(self,messages,tools,cancel,emit,**kwargs):
            latest=max(i for i,m in enumerate(messages) if m['role']=='user')
            if any(m['role']=='tool' for m in messages[latest:]):
                return {'role':'assistant','content':'Verified.'},{}
            if 'blue' in messages[latest]['content']:
                assert any(m['role']=='tool' for m in messages[:latest])
            name=next(t['function']['name'] for t in tools if 'set_all_labels' in t['function']['name'])
            self.names.append(name)
            color='blue' if 'blue' in messages[latest]['content'] else 'white'
            return {'role':'assistant','content':'','tool_calls':[{'id':'call'+str(len(self.names)),'type':'function','function':{'name':name,'arguments':json.dumps({'color':color})}}]},{}
    model=Followup()
    engine=Engine(Config(state_dir=str(tmp_path/'state'),servers=servers(tmp_path/'doc.json')),backend=model)
    asyncio.run(engine.turn('make labels white',lambda *args:None))
    asyncio.run(engine.turn('make them blue',lambda *args:None))
    assert len(model.names)==2 and model.names[0]==model.names[1]
    assert json.loads((tmp_path/'doc.json').read_text())['color']=='blue'


def test_verified_host_completion_avoids_extra_generation(tmp_path):
    from qtpy_ai_sidecar.adapters import NullAdapter
    class Adapter(NullAdapter):
        def verified_completion(self,name,args,result,state,text):
            value=json.loads(result['content'])
            assert value['verified_after']['color']=='white'
            return 'Verified white labels.'
    model=ScriptedModel()
    engine=Engine(Config(state_dir=str(tmp_path/'state'),servers=servers(tmp_path/'doc.json')),Adapter(),backend=model)
    events=[]
    asyncio.run(engine.turn('Make all labels white',lambda *args:events.append(args)))
    assert model.step==1
    assert any(k=='verified_completion' for k,v in events)


def test_missing_target_asks_without_executing_tool(tmp_path):
    from qtpy_ai_sidecar.adapters import NullAdapter
    from qtpy_ai_sidecar.errors import NeedsClarification
    class Adapter(NullAdapter):
        def validate_tool_call(self,*args):
            raise NeedsClarification('Please select the panel.')
    model=ScriptedModel()
    engine=Engine(Config(state_dir=str(tmp_path/'state'),servers=servers(tmp_path/'doc.json')),Adapter(),backend=model)
    events=[]
    asyncio.run(engine.turn('one letter is not visible',lambda *args:events.append(args)))
    assert model.step==1
    assert not (tmp_path/'doc.json').exists()
    records=[json.loads(l) for l in engine.journal.path.read_text().splitlines()]
    assert not any(e['kind']=='operation_intent' for e in records)
    assert any(k=='assistant' and 'select the panel' in v for k,v in events)

def test_protocol_recovery_never_replays_completed_edit(tmp_path):
    from qtpy_ai_sidecar.qwen_protocol import ReplyProtocolError
    class Model(ScriptedModel):
        rejected=False
        async def complete(self,messages,tools,cancel,emit,**kwargs):
            if self.step==1 and not self.rejected:
                self.rejected=True
                raise ReplyProtocolError('Unknown function; no tool submitted')
            return await super().complete(messages,tools,cancel,emit)
    model=Model()
    engine=Engine(Config(state_dir=str(tmp_path/'state'),servers=servers(tmp_path/'doc.json')),backend=model)
    asyncio.run(engine.turn('Make labels white',lambda *a:None))
    records=[json.loads(l) for l in engine.journal.path.read_text().splitlines()]
    assert sum(r['kind']=='operation_intent' for r in records)==1
    assert sum(r['kind']=='protocol_recovery' for r in records)==1
    assert json.loads((tmp_path/'doc.json').read_text())['color']=='white'

def test_protocol_recovery_is_bounded_without_submission(tmp_path):
    from qtpy_ai_sidecar.qwen_protocol import ReplyProtocolError
    import pytest
    class Bad:
        calls=0
        async def complete(self,*a,**kw):
            self.calls+=1
            raise ReplyProtocolError('Malformed tool call; no tool submitted')
    model=Bad()
    engine=Engine(Config(state_dir=str(tmp_path/'state'),servers=servers(tmp_path/'doc.json')),backend=model)
    with pytest.raises(BaseException):
        asyncio.run(engine.turn('Make labels white',lambda *a:None))
    # Initial reply, one format correction, then one text-only attempt.
    assert model.calls==3
    assert not (tmp_path/'doc.json').exists()

def test_direct_names_are_readable_stable_and_collision_safe():
    from types import SimpleNamespace
    hub=MCPHub({})
    def tool(name): return SimpleNamespace(name=name,description='',inputSchema={'type':'object'})
    hub.tools={'ta':('one',None,tool('inspect_figure'))}
    assert hub.direct_ids()=={'inspect_figure':'ta'}
    hub.tools['tb']=('two',None,tool('inspect_figure'))
    names=hub.direct_ids()
    assert len(names)==2 and set(names.values())=={'ta','tb'}
    assert names==hub.direct_ids()
    assert all(len(n)<=64 for n in names)
    hub.tools['tc']=('three',None,tool('execute_application_tool'))
    assert 'execute_application_tool' not in hub.direct_ids()
