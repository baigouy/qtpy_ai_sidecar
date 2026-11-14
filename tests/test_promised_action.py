"""'I'll rotate panel a to the right by 30 degrees:' and the turn ended with no tool
call (Qwen3.5-9B, live replay of the merged PyFigures chat, 2026-11-14: 4 of the first
50 requests). A reply that announces a step it has not taken gets one automatic
reminder to make the call."""
import asyncio
from types import SimpleNamespace

import pytest

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine, promises_action


@pytest.mark.parametrize('text', [
    "I'll rotate panel a to the right by 30 degrees:",
    'Great! I found `add_scripted_image`. Let me check its schema and use it to fill the panels:',
    'I need to first detect the vesicles in panel b. Let me detect objects in panel b:',
    'For black, I can use "black" or 0. Let me try with "black":',
    'Now I will apply the crop.',
])
def test_announced_steps(text):
    assert promises_action(text)


@pytest.mark.parametrize('text', [
    'Done! I rotated panel a by 30 degrees.',
    'Would you like me to add more panels?',
    "Let me know if you want another colour.",
    'Panel b now uses the reversed viridis LUT.',
    '',
])
def test_finished_replies_and_questions(text):
    assert not promises_action(text)


class Hub:
    instructions = []

    def __init__(self):
        self.calls = []
        self.tools = {'rot': ('demo', None, SimpleNamespace(name='rotate', annotations=SimpleNamespace(readOnlyHint=False)))}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def model_tools(self):
        return [{'type': 'function', 'function': {'name': 'rotate', 'parameters': {'type': 'object', 'properties': {}}}}]

    def direct_ids(self):
        return {'rotate': 'rot'}

    async def execute(self, ident, arguments, emit):
        self.calls.append(ident)
        return {'is_error': False, 'content': 'panel a: rotation = 30 (read back)'}


class Announcer:
    """Announces the rotation; makes the call only once reminded (or never)."""
    def __init__(self, obeys=True):
        self.obeys, self.reminded = obeys, 0

    async def complete(self, messages, tools, cancel, emit, final_only=False):
        last = [m for m in messages if m['role'] != 'system'][-1]       # the guidance comes last
        if last['role'] == 'tool':
            return {'role': 'assistant', 'content': 'Done: panel a is rotated by 30 degrees.'}, {}
        if last['role'] == 'user' and last['content'].startswith('(Automatic message'):
            self.reminded += 1
            if self.obeys:
                return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': '1', 'type': 'function', 'function': {
                    'name': 'rotate', 'arguments': '{"degrees": 30}'}}]}, {}
        return {'role': 'assistant', 'content': "I'll rotate panel a to the right by 30 degrees:"}, {}


@pytest.mark.parametrize('obeys', [True, False])
def test_one_reminder_then_the_call_or_the_reply_stands(tmp_path, obeys):
    hub, model = Hub(), Announcer(obeys)
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('rotate a to the right by about 30 degrees', lambda *a: events.append(a)))
    assert model.reminded == 1                                  # once, never in a loop
    assert hub.calls == (['rot'] if obeys else [])
    assert 'promised_action_recovery' in engine.journal.path.read_text(encoding='utf-8')
    if obeys:
        assert any(k == 'assistant' and v.startswith('Done') for k, v in events)
