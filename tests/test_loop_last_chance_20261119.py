"""2026-11-19 (user): "fix the trim so it always finishes". In a live Mistral Large 4 replay
four turns ended on "I stopped before finishing (my closing answer tried to run a tool)":
a loop stop (looks, repeated reads, the same refused call) switched every tool off, and the
model answered the text-only request with the tool call it wanted to make. Now the first
loop stop of a request switches off only reads and searches (or, for a refused call, just
says not to resend it) and lets the model make the edit or answer."""
import asyncio
from types import SimpleNamespace

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine, LOOK_STOP


class _Hub:
    instructions = []

    def __init__(self, refuse=()):
        self.calls = []
        self.refuse = refuse
        self.tools = {'look': ('demo', None, SimpleNamespace(name='preview', annotations=SimpleNamespace(readOnlyHint=True))),
                      'draw': ('demo', None, SimpleNamespace(name='add_arrow', annotations=SimpleNamespace(readOnlyHint=False)))}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def model_tools(self):
        return [{'type': 'function', 'function': {'name': n}} for n in ('preview', 'add_arrow')]

    def direct_ids(self):
        return {'preview': 'look', 'add_arrow': 'draw'}

    def is_read_only(self, ident):
        return ident == 'look'

    async def execute(self, ident, arguments, emit):
        self.calls.append((ident, arguments))
        if arguments.get('x') in self.refuse:
            return {'is_error': True, 'error': 'ARROW_OUTSIDE_IMAGE: x is past the right edge'}
        return {'is_error': False, 'content': f'{ident} done'}


def _call(n, name, args):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': str(n), 'type': 'function', 'function': {'name': name, 'arguments': args}}]}, {}


def _last_chance_given(messages):
    return any(m['role'] == 'user' and 'Automatic message' in str(m['content']) and 'ONE step' in str(m['content'])
               for m in messages)


def test_after_looking_too_long_the_model_still_makes_the_edit(tmp_path):
    class Looker:
        n = 0

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            self.n += 1
            if final_only or not tools:
                return {'role': 'assistant', 'content': 'Arrow added at my best estimate.'}, {}
            if self.n > LOOK_STOP + 1:
                return {'role': 'assistant', 'content': 'Done: an arrow points at the dividing cell (estimate).'}, {}
            if _last_chance_given(messages):
                return _call(self.n, 'add_arrow', '{"x": 40}')
            return _call(self.n, 'preview', '{"region": %d}' % self.n)

    hub = _Hub()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Looker(), hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('put an arrow at the dividing cell in A', lambda *a: events.append(a)))
    assert [c[0] for c in hub.calls] == ['look'] * LOOK_STOP + ['draw']
    log = engine.journal.path.read_text(encoding='utf-8')
    assert 'loop_last_chance' in log and 'look_loop_stopped' not in log
    assert any(k == 'assistant' and 'arrow points' in v for k, v in events)


def test_a_look_after_the_last_chance_does_not_run(tmp_path):
    class Stubborn:
        n = 0

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            self.n += 1
            if final_only or not tools:
                return {'role': 'assistant', 'content': 'Is it the bright cell at the top left?'}, {}
            return _call(self.n, 'preview', '{"region": %d}' % self.n)

    hub = _Hub()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Stubborn(), hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('put an arrow at the dividing cell in A', lambda *a: events.append(a)))
    assert len(hub.calls) == LOOK_STOP                       # the extra look was refused, not run
    assert 'look_loop_stopped' in engine.journal.path.read_text(encoding='utf-8')
    assert any(k == 'assistant' and 'bright cell' in v for k, v in events)


def test_after_three_identical_refusals_a_corrected_call_runs(tmp_path):
    class Retrier:
        n = 0

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            self.n += 1
            if final_only or not tools:
                return {'role': 'assistant', 'content': 'The arrow could not be placed.'}, {}
            if any(m['role'] == 'tool' and 'draw done' in str(m['content']) for m in messages):
                return {'role': 'assistant', 'content': 'Done: the arrow is inside the image now.'}, {}
            if _last_chance_given(messages):
                return _call(self.n, 'add_arrow', '{"x": 40}')
            return _call(self.n, 'add_arrow', '{"x": 900}')

    hub = _Hub(refuse=(900,))
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Retrier(), hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('add an arrow on the right', lambda *a: events.append(a)))
    assert [c[1]['x'] for c in hub.calls] == [900, 900, 900, 40]
    log = engine.journal.path.read_text(encoding='utf-8')
    assert 'loop_last_chance' in log and 'rejected_call_loop_stopped' not in log
    assert any(k == 'assistant' and 'inside the image' in v for k, v in events)
