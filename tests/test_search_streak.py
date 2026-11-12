"""'yep 3-2-2-2' (2026-11-05): ~20 differently worded tool searches between two
refused moves used all 32 steps and ended in 'Tool-step limit reached'. Many
searches in a row without a successful call now stop and explain instead."""
import asyncio
from types import SimpleNamespace

import pytest

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine, MAX_SEARCH_STREAK
from qtpy_ai_sidecar.mcp_client import MCPHub


def _hub(results):
    class Hub:
        instructions = []

        def __init__(self, *a):
            self.calls = []
            self.tools = {'find': ('demo', None, SimpleNamespace(name='find_catalog_tools', annotations=SimpleNamespace(readOnlyHint=True))),
                          'move': ('demo', None, SimpleNamespace(name='move_image', annotations=SimpleNamespace(readOnlyHint=False)))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def model_tools(self):
            return []

        def direct_ids(self):
            return {'find_catalog_tools': 'find', 'move_image': 'move'}

        def is_discovery(self, ident):
            return ident == 'find'

        async def execute(self, ident, arguments, emit):
            self.calls.append(ident)
            return results(ident, len(self.calls))
    return Hub()


class Model:
    """Searches with a new wording every time; tries a move every few steps."""
    def __init__(self, move_every=0):
        self.calls = 0
        self.move_every = move_every

    async def complete(self, messages, tools, cancel, emit, final_only=False):
        self.calls += 1
        if final_only:
            return {'role': 'assistant', 'content': 'move_image refused: the move changes the letters. Nothing was changed.'}, {}
        move = self.move_every and self.calls % self.move_every == 0
        name, args = ('move_image', '{"x": 1}') if move else ('find_catalog_tools', '{"query": "wording %d"}' % self.calls)
        return {'role': 'assistant', 'content': '',
                'tool_calls': [{'id': str(self.calls), 'type': 'function', 'function': {'name': name, 'arguments': args}}]}, {}


def test_many_different_searches_stop_and_explain(tmp_path):
    hub = _hub(lambda ident, n: {'is_error': False, 'content': f'catalog page {n}'})
    model = Model()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('yep 3-2-2-2', lambda *a: events.append(a)))
    assert len(hub.calls) == MAX_SEARCH_STREAK < 32
    log = engine.journal.path.read_text(encoding='utf-8')
    assert 'search_loop_stopped' in log and 'Tool-step limit reached' not in log
    assert any(k == 'assistant' and 'refused' in v for k, v in events)


def test_refused_edits_do_not_reset_the_search_count(tmp_path):
    # the real loop: searches, a refused move, more searches...
    hub = _hub(lambda ident, n: {'is_error': True, 'error': 'MOVE_VERIFICATION_FAILED'} if ident == 'move'
               else {'is_error': False, 'content': f'catalog page {n}'})
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Model(move_every=4), hub_factory=lambda *a: hub)
    asyncio.run(engine.turn('yep 3-2-2-2', lambda *a: None))
    assert hub.calls.count('find') == MAX_SEARCH_STREAK and len(hub.calls) < 32
    assert 'search_loop_stopped' in engine.journal.path.read_text(encoding='utf-8')


def test_a_successful_edit_resets_the_count(tmp_path):
    hub = _hub(lambda ident, n: {'is_error': False, 'content': f'result {n}'})
    model = Model(move_every=MAX_SEARCH_STREAK - 1)
    engine = Engine(Config(state_dir=str(tmp_path), max_steps=20), backend=model, hub_factory=lambda *a: hub)
    try:
        asyncio.run(engine.turn('keep going', lambda *a: None))
    except RuntimeError:
        pass                                              # reaches its own step limit instead
    assert 'search_loop_stopped' not in engine.journal.path.read_text(encoding='utf-8')
    assert hub.calls.count('move') >= 2


def test_after_its_edits_the_model_is_told_to_stop_rechecking(tmp_path):
    """'met un fond de couleur aleatoire pour chaque image' (2026-11-12): 9 edits done in
    41 s, each read back by its tool, then 37 s of re-reading them one by one."""
    from qtpy_ai_sidecar.engine import CHECK_NUDGE
    seen = []

    class Hub:
        instructions = []

        def __init__(self):
            self.calls = []
            self.tools = {'set': ('demo', None, SimpleNamespace(name='set_colour', annotations=SimpleNamespace(readOnlyHint=False))),
                          'get': ('demo', None, SimpleNamespace(name='get_colour', annotations=SimpleNamespace(readOnlyHint=True)))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def model_tools(self):
            return []

        def direct_ids(self):
            return {'set_colour': 'set', 'get_colour': 'get'}

        def is_read_only(self, ident):
            return ident == 'get'

        async def execute(self, ident, arguments, emit):
            self.calls.append(ident)
            return {'is_error': False, 'content': f'panel {arguments["panel"]}: colour = red (read back)'}

    class Checker:
        n = 0

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            nudged = any(m['role'] == 'system' and 'enough verification' in m['content'] for m in messages)
            seen.append(nudged)
            if nudged or final_only:
                return {'role': 'assistant', 'content': 'Done: 3 panels are red.'}, {}
            self.n += 1
            name = 'set_colour' if self.n <= 3 else 'get_colour'      # 3 edits, then re-reading forever
            return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(self.n), 'type': 'function', 'function': {
                'name': name, 'arguments': '{"panel": %d}' % (self.n % 3)}}]}, {}

    hub = Hub()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Checker(), hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('make the panels red', lambda *a: events.append(a)))
    assert hub.calls == ['set'] * 3 + ['get'] * CHECK_NUDGE              # no more re-reading
    assert seen[-1] and not any(seen[:-1])
    assert any(k == 'assistant' and 'Done' in v for k, v in events)
    assert any(k == 'status' and 'Stop keeps them' in v for k, v in events)


@pytest.mark.parametrize('calls_anyway', [False, True])
def test_a_model_that_ignores_the_nudge_answers_without_tools(tmp_path, calls_anyway):
    """calls_anyway: Mistral Large 4 answered the tool-less request with a tool call and the
    turn ended on 'Text-only recovery returned a tool call' (2026-11-12)."""
    from qtpy_ai_sidecar.backend import TextOnlyToolCall
    from qtpy_ai_sidecar.engine import CHECK_STOP
    asked = []

    class Stubborn:
        n = 0

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            if final_only or not tools:
                asked.append(messages[-1]['content'])
                if calls_anyway:
                    raise TextOnlyToolCall('Text-only recovery returned a tool call; nothing executed')
                return {'role': 'assistant', 'content': 'Done: 3 panels are red.'}, {}
            self.n += 1
            name = 'set_colour' if self.n <= 3 else 'get_colour'       # never stops reading
            return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(self.n), 'type': 'function', 'function': {
                'name': name, 'arguments': '{"panel": %d}' % self.n}}]}, {}

    calls = []

    class Hub:
        instructions = []
        tools = {'set': ('demo', None, SimpleNamespace(name='set_colour', annotations=SimpleNamespace(readOnlyHint=False))),
                 'get': ('demo', None, SimpleNamespace(name='get_colour', annotations=SimpleNamespace(readOnlyHint=True)))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def model_tools(self):
            return [{'type': 'function', 'function': {'name': 'get_colour'}}]

        def direct_ids(self):
            return {'set_colour': 'set', 'get_colour': 'get'}

        def is_read_only(self, ident):
            return ident == 'get'

        async def execute(self, ident, arguments, emit):
            calls.append(ident)
            return {'is_error': False, 'content': 'colour = red (read back)'}

    engine = Engine(Config(state_dir=str(tmp_path)), backend=Stubborn(), hub_factory=lambda *a: Hub())
    events = []
    asyncio.run(engine.turn('make the panels red', lambda *a: events.append(a)))
    assert calls == ['set'] * 3 + ['get'] * CHECK_STOP
    assert 'check_loop_stopped' in engine.journal.path.read_text(encoding='utf-8')
    # never a blind "done": the model is asked to say which part is still missing
    assert 'has NOT been done yet' in asked[0] and 'never call it done' in asked[0]
    expected = 'ask me to continue' if calls_anyway else 'Done'
    assert any(k == 'assistant' and expected in v for k, v in events)


def test_reads_between_two_edits_are_not_cut_short(tmp_path):
    """'rotate A, then make the letters bold on every rotated panel': an edit, three
    lookups, then the next edit. The lookups are not re-checking; the turn goes on."""
    from qtpy_ai_sidecar.engine import CHECK_STOP
    plan = ['set'] + ['get'] * (CHECK_STOP - 1) + ['set']
    calls = []

    class Planner:
        n = 0

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            if self.n >= len(plan) or final_only:
                return {'role': 'assistant', 'content': 'A is rotated and its letter is bold.'}, {}
            name = {'set': 'set_colour', 'get': 'get_colour'}[plan[self.n]]
            self.n += 1
            return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(self.n), 'type': 'function', 'function': {
                'name': name, 'arguments': '{"panel": %d}' % self.n}}]}, {}

    class Hub:
        instructions = []
        tools = {'set': ('demo', None, SimpleNamespace(name='set_colour', annotations=SimpleNamespace(readOnlyHint=False))),
                 'get': ('demo', None, SimpleNamespace(name='get_colour', annotations=SimpleNamespace(readOnlyHint=True)))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def model_tools(self):
            return []

        def direct_ids(self):
            return {'set_colour': 'set', 'get_colour': 'get'}

        def is_read_only(self, ident):
            return ident == 'get'

        async def execute(self, ident, arguments, emit):
            calls.append(ident)
            return {'is_error': False, 'content': 'ok'}

    engine = Engine(Config(state_dir=str(tmp_path)), backend=Planner(), hub_factory=lambda *a: Hub())
    asyncio.run(engine.turn('rotate A, then make the letters bold on every rotated panel', lambda *a: None))
    assert calls == plan                                         # the second edit ran
    assert 'check_loop_stopped' not in engine.journal.path.read_text(encoding='utf-8')


def test_reads_before_any_edit_are_not_cut_short(tmp_path):
    """A question ('which panels are red?') may read as much as it needs."""
    hub = _hub(lambda ident, n: {'is_error': False, 'content': f'catalog page {n}'})
    seen = []

    class Reader(Model):
        async def complete(self, messages, tools, cancel, emit, final_only=False):
            seen.append(any(m['role'] == 'system' and 'enough verification' in m['content'] for m in messages))
            return await super().complete(messages, tools, cancel, emit, final_only)
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Reader(), hub_factory=lambda *a: hub)
    asyncio.run(engine.turn('which panels are red?', lambda *a: None))
    assert not any(seen)


def test_after_three_searches_the_model_is_told_to_act_or_answer(tmp_path):
    """'put the letters outside the images': no operation does it; the model
    searched eight times and the user got 'I stopped before finishing'."""
    from qtpy_ai_sidecar.engine import SEARCH_NUDGE
    seen = []

    class Listening(Model):
        async def complete(self, messages, tools, cancel, emit, final_only=False):
            nudged = any(m['role'] == 'system' and 'Do not search again' in m['content'] for m in messages)
            seen.append(nudged)
            if nudged and not final_only:
                return {'role': 'assistant', 'content': 'Letters outside each image are not available; I can put one letter per row.'}, {}
            return await super().complete(messages, tools, cancel, emit, final_only)

    hub = _hub(lambda ident, n: {'is_error': False, 'content': f'catalog page {n}'})
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Listening(), hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('put the letters outside the images', lambda *a: events.append(a)))
    assert seen == [False] * SEARCH_NUDGE + [True]          # told once three searches were made
    assert len(hub.calls) == SEARCH_NUDGE < MAX_SEARCH_STREAK
    assert any(k == 'assistant' and 'not available' in v for k, v in events)
    assert not any(m.get('role') == 'system' and 'Do not search again' in str(m.get('content')) for m in engine.messages)

