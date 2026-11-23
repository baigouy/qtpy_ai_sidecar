"""User 2026-11-23: "Estimated context budget reached ... Use Compress" with Mistral Large 4 (1M
tokens): "this is cloud model, why did its context got limited? ... it should be dealt by the
provider" / "shouldn't it be done automatically?". The chat's own estimate now guards local
models only; a local conversation is compressed on its own when the context fills; an online
model chosen again gets back its own context size, not the local model's 64k. No model API:
fake backends."""
import asyncio
import json

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine


class Answering:
    """Answers every request in plain text; a request with no tools is the compression."""
    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools, cancel, emit, max_tokens=None, final_only=False):
        self.calls.append(tools)
        if not tools and 'Summarize factual conversation memory' in str(messages[0].get('content')):
            return {'role': 'assistant', 'content': 'The user works on a figure.'}, {}
        return {'role': 'assistant', 'content': 'Done.'}, {}


def _records(engine):
    return [json.loads(line) for line in engine.journal.path.read_text(encoding='utf-8').splitlines()]


def test_an_online_model_is_never_stopped_by_the_chats_own_estimate(tmp_path):
    config = Config(state_dir=str(tmp_path), provider='mistral', base_url='https://api.mistral.ai/v1',
                    model='mistral-large-4', context_tokens=2048, output_tokens=1024)
    engine = Engine(config, backend=Answering())
    engine.messages.append({'role': 'user', 'content': 'a' * 20000})       # far over 2,048 tokens
    asyncio.run(engine.turn('enlarge the whole figure', lambda *a: None))
    assert not [r for r in _records(engine) if r['kind'] == 'error']
    assert engine.messages[-1]['content'] == 'Done.'


def test_a_local_conversation_is_compressed_on_its_own(tmp_path):
    config = Config(state_dir=str(tmp_path), context_tokens=8192, output_tokens=1024)
    model = Answering()
    engine = Engine(config, backend=model)
    for i in range(14):
        engine.messages.append({'role': 'user', 'content': f'request {i} ' + 'x' * 1200})
        engine.messages.append({'role': 'assistant', 'content': f'answer {i} ' + 'y' * 1200})
    asyncio.run(engine.turn('make the letters bold', lambda *a: None))
    kinds = [r['kind'] for r in _records(engine)]
    assert 'compression' in kinds and 'error' not in kinds
    assert any(m['content'].startswith('[CONVERSATION_MEMORY]') for m in engine.messages if m['role'] == 'system')


def test_back_online_the_online_context_returns(tmp_path, monkeypatch):
    from qtpy_ai_sidecar import discover
    from qtpy_ai_sidecar.connection import ConnectionDialog
    config = Config(application='Demo', state_dir=str(tmp_path), provider='mistral',
                    base_url='https://api.mistral.ai/v1', model='mistral-large-4', context_tokens=1000000)
    discover.apply(config, tmp_path / 'Qwen3.8-27B-Q4_K_M.gguf', tmp_path / 'llama-server.exe')
    assert config.context_tokens == 65536
    dialog = ConnectionDialog(config, online=True)            # starts on Mistral
    candidate = dialog.candidate()
    assert candidate.provider == 'mistral' and candidate.context_tokens == 1000000
    dialog.deleteLater()
