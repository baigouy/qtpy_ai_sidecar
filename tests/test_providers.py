import asyncio
import json
import threading
from test_backend import endpoint
from qtpy_ai_sidecar.backend import ModelClient
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.anthropic_backend import convert_messages


def test_openai_payload_uses_completion_limit(endpoint,monkeypatch):
    url,received,chunks=endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
    chunks.append({'choices':[{'delta':{'content':'Hello'},'finish_reason':'stop'}]})
    config=Config(provider='openai',base_url=url,api_key_env='SIDECAR_TEST_KEY')
    answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *args:None))
    assert answer['content']=='Hello'
    assert received[0]['max_completion_tokens']==config.output_tokens
    assert 'max_tokens' not in received[0] and 'temperature' not in received[0]
    assert received[0]['store'] is False


def test_openrouter_transport(endpoint,monkeypatch):
    url,received,chunks=endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
    chunks.append({'choices':[{'delta':{'content':'Hello'},'finish_reason':'stop'}]})
    config=Config(provider='openrouter',base_url=url,api_key_env='SIDECAR_TEST_KEY')
    answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *args:None))
    assert answer['content']=='Hello' and 'max_tokens' in received[0]


def test_claude_signed_thinking_and_streamed_tool(endpoint,monkeypatch):
    url,received,chunks=endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
    chunks.extend([
        {'type':'message_start','message':{'usage':{'input_tokens':50}}},
        {'type':'content_block_start','index':0,'content_block':{'type':'thinking','thinking':'','signature':''}},
        {'type':'content_block_delta','index':0,'delta':{'type':'thinking_delta','thinking':'Checking'}},
        {'type':'content_block_delta','index':0,'delta':{'type':'signature_delta','signature':'signed-example'}},
        {'type':'content_block_stop','index':0},
        {'type':'content_block_start','index':1,'content_block':{'type':'tool_use','id':'tool1','name':'edit','input':{}}},
        {'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'{"color":"white"}'}},
        {'type':'content_block_stop','index':1},
        {'type':'message_delta','delta':{'stop_reason':'tool_use'},'usage':{'output_tokens':20}},
        {'type':'message_stop'}])
    config=Config(provider='anthropic',base_url=url,api_key_env='SIDECAR_TEST_KEY',thinking_backend='anthropic_adaptive',thinking='enabled',thinking_strength='low')
    answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Edit'}],[],threading.Event(),lambda *args:None))
    assert json.loads(answer['tool_calls'][0]['function']['arguments'])=={'color':'white'}
    assert answer['_anthropic_blocks'][0]['signature']=='signed-example'
    _,converted=convert_messages([answer,{'role':'tool','tool_call_id':'tool1','content':'Verified'}])
    assert converted[0]['content'][0]['signature']=='signed-example'
    assert converted[1]['content'][0]['type']=='tool_result'
    assert received[0]['thinking']=={'type':'adaptive'}
    assert received[0]['output_config']=={'effort':'low'}
