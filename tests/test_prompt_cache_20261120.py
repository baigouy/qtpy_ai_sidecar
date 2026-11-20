"""Replay 2026-11-20 (Qwen on llama.cpp): every system message was merged into the leading
one, so the per-turn host state changed the start of the prompt and llama.cpp re-read the
whole conversation at each turn (234 of 712 calls, 78 of 104 min of prompt processing).
cache_friendly keeps what was already sent identical."""
from qtpy_ai_sidecar.backend import cache_friendly, HOST_NOTE

GUIDE = {'role': 'system', 'content': 'Connected application MCP guidance:\n{"x": 1}'}


def _turn(history, n, nudge=False):
    """The messages of one request in turn *n* (as engine.py builds them)."""
    msgs = list(history)
    msgs += [{'role': 'user', 'content': f'request {n}'},
             {'role': 'system', 'content': f'[CURRENT_HOST_STATE]\nstate {n}'},
             {'role': 'system', 'content': '[ACTION_MODE] Edits affect the live application document.'}]
    out = msgs + [GUIDE]
    if nudge:
        out.append({'role': 'system', 'content': 'You have looked 3 times in a row.'})
    return msgs, out


def test_a_new_turn_keeps_what_was_sent_before():
    base = [{'role': 'system', 'content': 'SYSTEM'}]
    hist1, req1 = _turn(base, 1)
    t1 = cache_friendly(req1)
    hist1 = [m for m in hist1 if not m['content'].startswith('[ACTION_MODE]')]
    hist1 += [{'role': 'assistant', 'content': 'done 1'}]
    _hist2, req2 = _turn(hist1, 2, nudge=True)
    t2 = cache_friendly(req2)
    assert t2[:len(t1)] == t1                     # nothing already sent changed
    assert t1[0]['content'].startswith('SYSTEM') and 'MCP guidance' in t1[0]['content']
    assert t1[1]['content'] == 'request 1\n\n' + HOST_NOTE + '[CURRENT_HOST_STATE]\nstate 1'
    assert 'looked 3 times' in t2[-1]['content'] and t2[-1]['role'] == 'user'
    assert sum(m['role'] == 'system' for m in t2) == 1


def test_a_note_after_an_assistant_reply_goes_with_the_next_message():
    msgs = [{'role': 'system', 'content': 'S'}, {'role': 'user', 'content': 'u'},
            {'role': 'assistant', 'content': 'a'}, {'role': 'system', 'content': 'Human host action undo'},
            {'role': 'user', 'content': 'v'}]
    t = cache_friendly(msgs)
    assert t[2] == {'role': 'assistant', 'content': 'a'}
    assert t[3]['content'].startswith('v\n\n' + HOST_NOTE + 'Human host action')
    parts = cache_friendly([{'role': 'system', 'content': 'S'},
                            {'role': 'tool', 'tool_call_id': '1', 'content': [{'type': 'text', 'text': 'r'}]},
                            {'role': 'system', 'content': 'note'}])
    assert parts[1]['content'][-1]['text'].endswith('note')


# --- the paid providers (user, 2026-11-20: "can this fix also be applied to api to gain
# credit consumption"): fake server, fake key, no real API

import asyncio
import json
import threading

from test_backend import endpoint  # noqa: F401  (fixture)
from qtpy_ai_sidecar.backend import ModelClient
from qtpy_ai_sidecar.config import Config

STOP = {'choices': [{'delta': {'content': 'Hello'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 900, 'completion_tokens': 5, 'prompt_tokens_details': {'cached_tokens': 768}}}


def _send(config, messages):
    return asyncio.run(ModelClient(config).complete(messages, [], threading.Event(), lambda *a: None))


def _two_turns():
    base = [{'role': 'system', 'content': 'SYSTEM'}]
    hist1, req1 = _turn(base, 1)
    hist1 = [m for m in hist1 if not m['content'].startswith('[ACTION_MODE]')]
    hist1 += [{'role': 'assistant', 'content': 'done 1'}]
    _, req2 = _turn(hist1, 2, nudge=True)
    return req1, req2


def test_mistral_and_openai_keep_the_prompt_start_and_send_one_cache_label(endpoint, monkeypatch):
    url, received, chunks = endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY', 'test-not-a-real-api-key')
    chunks.append(STOP)
    req1, req2 = _two_turns()
    for provider in ('mistral', 'openai'):
        received.clear()
        config = Config(provider=provider, base_url=url, model='m', api_key_env='SIDECAR_TEST_KEY')
        _, usage = _send(config, req1)
        _send(config, req2)
        first, second = received[0]['messages'], received[1]['messages']
        assert second[:len(first)] == first, provider          # what was sent stays the same
        assert sum(m['role'] == 'system' for m in second) == 1
        key = received[0]['prompt_cache_key']
        assert key == received[1]['prompt_cache_key'] and key.startswith('qtpy-sidecar-')
        assert 'request 1' not in key and 'SYSTEM' not in key  # a hash, not the conversation
        assert usage['cached_tokens'] == 768


def test_openrouter_marks_claude_and_gemini_prompts_for_the_cache(endpoint, monkeypatch):
    url, received, chunks = endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY', 'test-not-a-real-api-key')
    chunks.append(STOP)
    req1, _ = _two_turns()
    for model, marks in (('anthropic/claude-sonnet-5.5', 2), ('google/gemini-3-pro', 1), ('qwen/qwen3.8', 0)):
        received.clear()
        _send(Config(provider='openrouter', base_url=url, model=model, api_key_env='SIDECAR_TEST_KEY'), req1)
        sent = received[0]['messages']
        found = [m['role'] for m in sent if isinstance(m['content'], list)
                 and any('cache_control' in p for p in m['content'])]
        assert len(found) == marks, model
        if marks:
            assert found[0] == 'system' and sent[0]['content'][0]['text'].startswith('SYSTEM')
        assert 'prompt_cache_key' not in received[0]


def test_a_server_that_refuses_the_cache_label_gets_the_request_without_it(monkeypatch):
    from qtpy_ai_sidecar import backend as module
    bodies = []

    class Response:
        def __init__(self, status):
            self.status_code, self.headers = status, {}

        async def aread(self):
            return b'{"detail": "Extra inputs are not permitted: prompt_cache_key"}'

        async def aiter_lines(self):
            yield 'data: ' + json.dumps(STOP)
            yield 'data: [DONE]'

    class Stream:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            bodies.append(dict(self.payload))
            return Response(422 if 'prompt_cache_key' in self.payload else 200)

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(module, 'connect_stream', lambda client, url, payload, headers, emit: Stream(payload))
    monkeypatch.setenv('SIDECAR_TEST_KEY', 'test-not-a-real-api-key')
    config = Config(provider='mistral', base_url='http://127.0.0.1:9/v1', model='m', api_key_env='SIDECAR_TEST_KEY')
    answer, _ = _send(config, [{'role': 'user', 'content': 'Hi'}])
    assert answer['content'] == 'Hello'
    assert 'prompt_cache_key' in bodies[0] and 'prompt_cache_key' not in bodies[1]


def test_claude_gets_cache_marks_a_stable_system_prompt_and_its_cached_count(endpoint, monkeypatch):
    url, received, chunks = endpoint
    monkeypatch.setenv('SIDECAR_TEST_KEY', 'test-not-a-real-api-key')
    chunks.extend([
        {'type': 'message_start', 'message': {'usage': {'input_tokens': 40, 'cache_read_input_tokens': 3000,
                                                        'cache_creation_input_tokens': 200}}},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'Hello'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 5}},
        {'type': 'message_stop'}])
    config = Config(provider='anthropic', base_url=url, model='claude-sonnet-5-5', api_key_env='SIDECAR_TEST_KEY',
                    thinking_backend='anthropic_adaptive', thinking='disabled')
    req1, req2 = _two_turns()
    _, usage = _send(config, req1)
    _send(config, req2)
    one, two = received
    assert one['system'] == two['system'] and one['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert 'state 1' not in json.dumps(one['system'])         # the turn's state is not in it
    assert one['messages'][-1]['content'][-1]['cache_control'] == {'type': 'ephemeral'}

    def plain(blocks):
        return [{k: v for k, v in b.items() if k != 'cache_control'} for b in blocks]
    assert plain(two['messages'][0]['content']) == plain(one['messages'][0]['content'])
    assert usage['cached_tokens'] == 3000 and usage['prompt_tokens'] == 3240 and usage['completion_tokens'] == 5
