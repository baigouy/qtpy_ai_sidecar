"""'can you draw ROIs over every cell in e' (2026-11-13): two ROIs drawn, then one step's
reasoning used the whole 8192-token output limit and the turn ended on an error. A
long task is not an error: the reply now asks whether to continue."""
import asyncio
from types import SimpleNamespace

from qtpy_ai_sidecar.backend import OutputLimitReached
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine


class Hub:
    instructions = []
    tools = {'add': ('demo', None, SimpleNamespace(name='add_roi', annotations=SimpleNamespace(readOnlyHint=False)))}

    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def model_tools(self):
        return []

    def direct_ids(self):
        return {'add_roi': 'add'}

    async def execute(self, ident, arguments, emit):
        self.calls.append(arguments)
        return {'is_error': False, 'content': 'ROI added'}


class LongThinker:
    """Adds two ROIs, then runs out of room; on "continue" adds a third and answers."""
    def __init__(self):
        self.n = 0
        self.told_to_be_short = []

    async def complete(self, messages, tools, cancel, emit, final_only=False):
        self.n += 1
        self.told_to_be_short.append(any(m['role'] == 'system' and 'ran out of output space' in m['content'] for m in messages))
        if self.n == 3:
            raise OutputLimitReached('Model reached its 8192-token output limit.', 8192)
        if self.n in (1, 2, 4):
            return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(self.n), 'type': 'function',
                    'function': {'name': 'add_roi', 'arguments': '{"cell": %d}' % self.n}}]}, {}
        return {'role': 'assistant', 'content': 'Done: 3 cells have an ROI.'}, {}


def test_running_out_of_room_asks_to_continue(tmp_path):
    calls, model = [], LongThinker()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: Hub(calls))
    events = []
    asyncio.run(engine.turn('can you draw ROIs over every cell in e', lambda *a: events.append(a)))
    replies = [v for k, v in events if k == 'assistant']
    assert len(calls) == 2 and 'Should I go on?' in replies[-1] and '- Continue' in replies[-1]
    assert 'changes made so far are in the figure' in replies[-1]
    assert not any(k == 'error' for k, *_ in events)
    assert 'output_limit' in engine.journal.path.read_text(encoding='utf-8')
    asyncio.run(engine.turn('Continue', lambda *a: events.append(a)))
    assert len(calls) == 3 and model.told_to_be_short[3] and not model.told_to_be_short[4]
    assert [v for k, v in events if k == 'assistant'][-1] == 'Done: 3 cells have an ROI.'


import pytest


class Busy:
    """Adds ROIs forever (placing ellipses by eye, one call each)."""
    def __init__(self):
        self.n = 0
        self.notes = []

    async def complete(self, messages, tools, cancel, emit, final_only=False):
        self.n += 1
        self.notes.append(next((m['content'] for m in messages if m['role'] == 'system' and 'continue the same request' in m['content']), ''))
        return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(self.n), 'type': 'function',
                'function': {'name': 'add_roi', 'arguments': '{"cell": %d}' % self.n}}]}, {}


def test_the_step_limit_asks_to_continue(tmp_path):
    """'great now segment nuclei in d' (2026-11-13): 32 steps of ellipses placed by eye,
    then 'Tool-step limit reached' as an error."""
    calls, model = [], Busy()
    engine = Engine(Config(state_dir=str(tmp_path), max_steps=4), backend=model, hub_factory=lambda *a: Hub(calls))
    events = []
    asyncio.run(engine.turn('segment nuclei in d', lambda *a: events.append(a)))
    replies = [v for k, v in events if k == 'assistant']
    assert len(calls) == 4 and 'used all 4 steps' in replies[-1] and '- Continue' in replies[-1]
    assert not any(k == 'error' for k, *_ in events) and 'step_limit' in engine.journal.path.read_text(encoding='utf-8')
    asyncio.run(engine.turn('continue', lambda *a: None))
    assert 'used all its tool steps' in model.notes[4]


@pytest.mark.parametrize('text', ['Stop here', 'please make the letters bold', 'yes but make them yellow'])
def test_another_message_after_the_limit_is_a_new_request(tmp_path, text):
    """The buttons never block: typing something else is as if "Stop here" was pressed."""
    calls, model = [], LongThinker()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: Hub(calls))
    asyncio.run(engine.turn('can you draw ROIs over every cell in e', lambda *a: None))
    asyncio.run(engine.turn(text, lambda *a: None))
    assert not any(model.told_to_be_short)


@pytest.mark.parametrize('text', ['continue', 'Yes, go on please', 'ok continue!', 'keep going thanks'])
def test_continue_wordings(tmp_path, text):
    calls, model = [], LongThinker()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: Hub(calls))
    asyncio.run(engine.turn('can you draw ROIs over every cell in e', lambda *a: None))
    asyncio.run(engine.turn(text, lambda *a: None))
    assert model.told_to_be_short[3]
