import asyncio
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine, size_estimate

def test_context_meter_counts_the_mcp_guidance_the_guard_counts(tmp_path):
    # the meter showed 28404 + 4096 < 32768 while the guard, which adds the
    # connected MCP guidance, already refused: both must count the same payload
    guidance=['x'*20000]
    class Hub:
        instructions=guidance
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def model_tools(self):return []
        def direct_ids(self):return {}
    sent=[]
    class Model:
        async def complete(self,messages,tools,cancel,emit,final_only=False):
            sent.append(size_estimate(messages))
            return {'role':'assistant','content':'ok'},{}
    engine=Engine(Config(state_dir=str(tmp_path)),backend=Model(),hub_factory=lambda *a:Hub())
    events=[]
    asyncio.run(engine.turn('Hello',lambda *e:events.append(e)))
    meters=[v['estimated_tokens'] for k,v in events if k=='context']
    assert sent[0] in meters          # the reading shown before the request is what was sent
