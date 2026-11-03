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


def test_mistral_transport_and_vision(endpoint,monkeypatch):
    """Mistral: no stream_options (not a documented field); vision read from
    its keyed model list, where mistral-large-latest is an alias."""
    import httpx
    from qtpy_ai_sidecar import vision
    url,received,chunks=endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
    chunks.append({'choices':[{'delta':{'content':'Hello'},'finish_reason':'stop'}]})
    config=Config(provider='mistral',base_url=url,model='mistral-large-latest',api_key_env='SIDECAR_TEST_KEY')
    answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *args:None))
    assert answer['content']=='Hello'
    assert 'stream_options' not in received[0] and received[0]['model']=='mistral-large-latest'
    # Mistral Large 4 streams content as typed chunks: thinking kept out of the reply
    chunks.clear()
    chunks.append({'choices':[{'delta':{'content':[{'type':'thinking','thinking':[{'type':'text','text':'Hmm.'}]}]},'finish_reason':None}]})
    chunks.append({'choices':[{'delta':{'content':[{'type':'text','text':'Hel'}]},'finish_reason':None}]})
    chunks.append({'choices':[{'delta':{'content':'lo'},'finish_reason':'stop'}]})
    answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *args:None))
    assert answer['content']=='Hello' and 'Hmm.' not in answer['content']
    seen=[]
    class Reply:
        def __init__(self,models):self.models=models
        def json(self):return {'data':self.models}
    models=[{'id':'mistral-large-2610','aliases':['mistral-large-latest'],'capabilities':{'vision':True}},
            {'id':'codestral-latest','capabilities':{'vision':False}}]
    monkeypatch.setattr(httpx,'get',lambda u,timeout=0,headers=None:seen.append((u,headers)) or Reply(models))
    remote=Config(provider='mistral',base_url='https://api.mistral.ai/v1',model='mistral-large-latest',api_key_env='SIDECAR_TEST_KEY')
    assert vision.detect(remote) is True
    assert seen[0]==('https://api.mistral.ai/v1/models',{'Authorization':'Bearer test-not-a-real-api-key'})
    remote.model='codestral-latest'
    assert vision.detect(remote) is False
    remote.model='unlisted'
    assert vision.detect(remote) is False


def test_a_brief_provider_outage_is_retried(monkeypatch):
    """Mistral answered HTTP 503 'upstream connect error' for ~25 s (2026-11-03),
    which ended turns half done: 5xx answers are now sent again."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from qtpy_ai_sidecar import backend
    real_sleep=asyncio.sleep
    waits=[]
    async def fast(seconds):
        waits.append(seconds)
        await real_sleep(0)
    monkeypatch.setattr(backend.asyncio,'sleep',fast)
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if len(received)<=3:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'upstream connect error or disconnect/reset before headers')
                return
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':'Hello'},'finish_reason':'stop'}]})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
        config=Config(provider='mistral',base_url=f'http://127.0.0.1:{server.server_port}/v1',model='m',api_key_env='SIDECAR_TEST_KEY')
        events=[]
        answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *a:events.append(a)))
    finally:
        server.shutdown()
        server.server_close()
    assert answer['content']=='Hello' and len(received)==4
    assert [w for w in waits if w>=1]==[2.0,4.0,8.0]          # (0.1 s: the cancel watcher's polling)
    assert any(kind=='status' and 'HTTP 503' in text for kind,text in events)


def test_groq_transport_vision_and_rate_limit(monkeypatch):
    """Groq (cloud Qwen3.8-27B): reasoning kept out of the text, previews sent
    by 'auto', and an HTTP 429 waited out and retried."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from qtpy_ai_sidecar import backend,vision
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if len(received)==1:
                self.send_response(429)
                self.send_header('retry-after','0.5')
                self.end_headers()
                self.wfile.write(b'{"error":"rate limit"}')
                return
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':'Hello'},'finish_reason':'stop'}]})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
        config=Config(provider='groq',base_url=f'http://127.0.0.1:{server.server_port}/v1',model='qwen/qwen3.8-27b',
                      api_key_env='SIDECAR_TEST_KEY',thinking_backend='reasoning_effort',thinking='disabled')
        events=[]
        answer,_=asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *a:events.append(a)))
    finally:
        server.shutdown()
        server.server_close()
    assert answer['content']=='Hello' and len(received)==2
    assert received[1]['reasoning_format']=='hidden' and received[1]['reasoning_effort']=='none'
    assert any(kind=='status' and 'Rate limited' in text for kind,text in events)
    remote=Config(provider='groq',base_url='https://api.groq.com/openai/v1',model='qwen/qwen3.8-27b')
    assert vision.detect(remote) is True
    remote.model='llama-3.3-70b-versatile'
    assert vision.detect(remote) is False
    assert backend.rate_limit_wait({'x-ratelimit-reset-tokens':'7.66s'},0)==7.66
    assert backend.rate_limit_wait({},1)==4.0
    # the real Groq free-tier refusal (2026-11-02): explained, not dumped as JSON
    detail=('{"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_x` service tier '
            '`on_demand` on input tokens per minute (ITPM): Limit 7000, Requested 7490, please reduce your message size"}}')
    text=backend.per_minute_limit_message(detail)
    assert '7490' in text and '7000' in text and 'paid tier' in text
    assert backend.per_minute_limit_message('{"error":"other"}') is None
    daily='{"error":{"message":"Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day","code":429}}'
    assert 'daily request quota' in backend.per_minute_limit_message(daily)
    gated=('{"error":{"message":"thinkingmachines/inkling:free is only available on agentic harnesses.","code":403,'
           '"metadata":{"failed_routing_step":"Gate Free Endpoints by Agentic Harness"}}}')
    assert 'approved list' in backend.per_minute_limit_message(gated)


def test_iteracompute_thinks_low_unless_asked(monkeypatch):
    """IteraCompute's Qwen3.8-27B thinks at 'xhigh' by default (its /models list):
    a two-line chat reply took 30-120 s (2026-11-03). Low unless set otherwise."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':'Hi'},'finish_reason':'stop'}]})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        monkeypatch.setenv('SIDECAR_TEST_KEY','test-not-a-real-api-key')
        for strength in ('default','high','medium'):
            config=Config(provider='iteracompute',base_url=f'http://127.0.0.1:{server.server_port}/v1',model='qwen/qwen3.8-27b',
                          api_key_env='SIDECAR_TEST_KEY',thinking_backend='reasoning_effort',thinking_strength=strength)
            asyncio.run(ModelClient(config).complete([{'role':'user','content':'Hi'}],[],threading.Event(),lambda *a:None))
    finally:
        server.shutdown()
        server.server_close()
    assert [r['reasoning_effort'] for r in received]==['low','xhigh','medium']


def test_openrouter_free_model_vision_is_read_from_its_model_list(monkeypatch):
    """'auto' sends previews to an OpenRouter model whose listed input
    modalities include images (thinkingmachines/inkling:free)."""
    from qtpy_ai_sidecar import vision
    listing={'data':[{'id':'thinkingmachines/inkling:free','architecture':{'input_modalities':['text','image','audio']}},
                     {'id':'some/text-only:free','architecture':{'input_modalities':['text']}}]}
    import httpx
    class Reply:
        def json(self):return listing
    seen=[]
    monkeypatch.setattr(httpx,'get',lambda url,timeout=0:seen.append(url) or Reply())
    config=Config(provider='openrouter',base_url='https://openrouter.ai/api/v1',model='thinkingmachines/inkling:free')
    assert vision.detect(config) is True and seen==['https://openrouter.ai/api/v1/models']
    config.model='some/text-only:free'
    assert vision.detect(config) is False
    config.model='not/listed'
    assert vision.detect(config) is False


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
