"""'yep 3-2-2-2' (2026-11-05): ~20 differently worded tool searches between two
refused moves used all 32 steps and ended in 'Tool-step limit reached'. Many
searches in a row without a successful call now stop and explain instead."""
import asyncio
from types import SimpleNamespace

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
