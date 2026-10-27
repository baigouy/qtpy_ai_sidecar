"""Network-free timeout tests; no local runtime, credentials, Qt or model startup."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

target=Path(os.environ.get('SIDECAR_BACKEND_UNDER_TEST',str(Path(__file__).resolve().parents[1]/'src/qtpy_ai_sidecar/backend.py')))
spec=importlib.util.spec_from_file_location('timeout_backend_subject',target)
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)

class SummaryTimeoutTests(unittest.TestCase):
    def fake_complete(self,budget,final_only=True,delay=35,cancelled=False,tool_call=False,response_timeout_s=30):
        clock=SimpleNamespace(value=0)
        self.events=[];self.requests=[]
        original_sleep=asyncio.sleep
        async def tick(seconds):
            if seconds==0.1:clock.value+=1
            await original_sleep(0)
        class Runtime:
            raw_qwen=False
            async def ensure(self,*_):return 'http://unused.invalid','fake-key'
        owner=self
        class Response:
            status_code=200
            async def __aenter__(self):return self
            async def __aexit__(self,*_):return False
            async def aiter_lines(self):
                while clock.value<delay:await original_sleep(0)
                delta={'content':'Verified summary.'}
                finish='stop'
                if tool_call:
                    delta={'tool_calls':[{'index':0,'id':'fake','function':{'name':'mutation','arguments':'{}'}}]}
                    finish='tool_calls'
                yield 'data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':finish}]})
                yield 'data: [DONE]'
        class Client:
            def __init__(self,**_):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*_):return False
            def stream(self,*_,**kwargs):
                owner.requests.append(kwargs['json'])
                return Response()
        config=SimpleNamespace(provider='local',base_url='http://unused.invalid',model='fake',
            output_tokens=16,thinking_backend='llama_cpp',thinking='enabled',
            thinking_strength='default',generation_timeout_seconds=budget,response_timeout_s=response_timeout_s)
        client=backend.ModelClient.__new__(backend.ModelClient)
        client.config=config;client.runtime=Runtime();client.secret_sink=lambda _:None
        cancel=threading.Event()
        if cancelled:cancel.set()
        async def run():
            with patch.object(backend,'time',SimpleNamespace(monotonic=lambda:clock.value)), \
                 patch.object(backend.httpx,'AsyncClient',Client), \
                 patch.object(backend.asyncio,'sleep',tick):
                return await client.complete([{'role':'user','content':'Summarize verified evidence.'}],
                    [],cancel,lambda k,v:self.events.append((k,v)),final_only=final_only)
        return asyncio.run(run())

    def test_final_summary_can_arrive_after_30s_within_configured_budget(self):
        message,_=self.fake_complete(120,delay=35,response_timeout_s=120)
        self.assertEqual(message['content'],'Verified summary.')
        self.assertFalse(any(k=='generation_timeout' for k,_ in self.events))
        self.assertNotIn('tools',self.requests[0])
        self.assertFalse(self.requests[0]['chat_template_kwargs']['enable_thinking'])
    def test_explicit_shorter_budget_still_expires(self):
        with self.assertRaises(backend.GenerationTimeout):
            self.fake_complete(20,delay=35)
        timeout=next(v for k,v in self.events if k=='generation_timeout')
        self.assertEqual(timeout['effective_timeout_seconds'],20)
        self.assertEqual(timeout['configured_timeout_seconds'],20)
    def test_regular_generation_budget_is_unchanged(self):
        message,_=self.fake_complete(120,final_only=False,delay=35)
        self.assertEqual(message['content'],'Verified summary.')
    def test_cancel_still_stops_recovery(self):
        with self.assertRaises(InterruptedError):
            self.fake_complete(120,cancelled=True)
    def test_recovery_still_rejects_a_tool_call(self):
        with self.assertRaisesRegex(RuntimeError,'Text-only recovery returned a tool call'):
            self.fake_complete(120,delay=1,tool_call=True)


    def test_default_recovery_budget_preserves_qwen_30_seconds(self):
        with self.assertRaises(backend.GenerationTimeout):
            self.fake_complete(120,delay=35)
        event=next(v for k,v in self.events if k=='generation_timeout')
        self.assertEqual(event['effective_timeout_seconds'],30)
    def test_primary_deadline_still_caps_recovery(self):
        with self.assertRaises(backend.GenerationTimeout):
            self.fake_complete(20,delay=35,response_timeout_s=120)
        event=next(v for k,v in self.events if k=='generation_timeout')
        self.assertEqual(event['effective_timeout_seconds'],20)

class ResponseProfileTests(unittest.TestCase):
    def test_profile_loads_its_own_recovery_budget(self):
        from qtpy_ai_sidecar.config import Config
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'performance.json').write_text(json.dumps({'response_timeout_s':999}),encoding='utf-8')
            for configured,wanted in [({},30),({'response_timeout_s':120},120)]:
                profile=root/'profile.json'
                profile.write_text(json.dumps({'state_dir':directory,**configured}),encoding='utf-8')
                config=Config.load(profile)
                self.assertEqual(config.response_timeout_s,wanted)
                config.save_performance()
                self.assertNotIn('response_timeout_s',json.loads((root/'performance.json').read_text(encoding='utf-8')))
    def test_invalid_recovery_budgets_are_rejected(self):
        from qtpy_ai_sidecar.config import Config
        for value in (0,9,3601,True,'120'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):Config(response_timeout_s=value)

if __name__=='__main__':
    assert not any(n=='qtpy' or n.startswith(('PyQt','PySide')) for n in sys.modules)
    unittest.main()
