import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from qtpy_ai_sidecar.backend import ModelClient
from qtpy_ai_sidecar.config import Config


@pytest.fixture
def endpoint():
    received = []
    responses = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for chunk in responses:
                self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield 'http://127.0.0.1:' + str(server.server_port) + '/v1', received, responses
    server.shutdown()
    server.server_close()
    thread.join()


def test_streamed_function_arguments_and_thinking_controls(endpoint):
    url, received, chunks = endpoint
    chunks.extend([
        {'choices': [{'delta': {'reasoning_content': 'Checking'}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call1', 'function': {'name': 'edit', 'arguments': '{"co'}}]}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': 'lor":"white"}'}}]}, 'finish_reason': 'tool_calls'}]},
        {'choices': [], 'usage': {'prompt_tokens': 99, 'completion_tokens': 12}}])
    config = Config(base_url=url, provider='compatible', thinking_backend='llama_cpp', thinking='disabled')
    answer, usage = asyncio.run(ModelClient(config).complete(
        [{'role': 'system', 'content': 'First'}, {'role': 'user', 'content': 'Edit'}, {'role': 'system', 'content': 'Current host state'}],
        [], threading.Event(), lambda *args: None))
    assert json.loads(answer['tool_calls'][0]['function']['arguments']) == {'color': 'white'}
    assert received[0]['chat_template_kwargs'] == {'enable_thinking': False}
    assert received[0]['reasoning_effort'] == 'none'
    assert sum(m['role'] == 'system' for m in received[0]['messages']) == 1
    assert usage['prompt_tokens'] == 99


def test_truncated_tool_call_never_returned(endpoint):
    url, _, chunks = endpoint
    chunks.append({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'x', 'function': {'name': 'edit', 'arguments': '{'}}]}, 'finish_reason': 'length'}]})
    with pytest.raises(RuntimeError, match='No partial tool call executed'):
        asyncio.run(ModelClient(Config(base_url=url, provider='compatible')).complete([], [], threading.Event(), lambda *args: None))


def test_raw_markup_not_executed(endpoint):
    url, _, chunks = endpoint
    chunks.append({'choices': [{'delta': {'content': '<tool_call>edit'}, 'finish_reason': 'stop'}]})
    with pytest.raises(RuntimeError, match='raw tool markup'):
        asyncio.run(ModelClient(Config(base_url=url, provider='compatible')).complete([], [], threading.Event(), lambda *args: None))


def test_owned_qwen_raw_tool_protocol(endpoint):
    from types import SimpleNamespace
    url, received, chunks = endpoint
    raw = 'Plan</think><tool_call><function=edit><parameter=color>white</parameter></function></tool_call>'
    chunks.append({'choices':[{'delta':{'content':raw},'finish_reason':'stop'}]})
    config = Config(provider='compatible', base_url=url, thinking_backend='llama_cpp', thinking='enabled')
    client = ModelClient(config)
    async def ensure(cancel,emit):
        return url.removesuffix('/v1'), 'local-test-key'
    client.runtime = SimpleNamespace(raw_qwen=True, ensure=ensure)
    tools = [{'type':'function','function':{'name':'edit','parameters':{'type':'object','properties':{'color':{'type':'string'}},'required':['color']}}}]
    answer,_=asyncio.run(client.complete([{'role':'user','content':'Edit'}],tools,threading.Event(),lambda *args:None))
    assert answer['reasoning_content']=='Plan'
    assert answer['tool_calls'][0]['function']['name']=='edit'
    assert json.loads(answer['tool_calls'][0]['function']['arguments'])=={'color':'white'}
