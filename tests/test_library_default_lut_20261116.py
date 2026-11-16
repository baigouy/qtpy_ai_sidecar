"""'I changed my mind use the default matplot lib lut' (Mistral Large 4,
2026-11-16): MATPLOTLIB_viridis was refused three times as "removing a LUT
means going back to the image's own colours" and the turn ended. A library's
default colour table is named by naming the library; "the default LUT" or
"default colours" alone is still the image file's own LUT (NONE)."""
import asyncio
from types import SimpleNamespace

import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine
from qtpy_ai_sidecar.errors import NeedsClarification

STATE = {'panel_references': [{'panel_id': '0/2', 'letters': ['c'], 'luts': ['RED_HOT'],
                               'channel_colours': ['GRAY']}]}


def _call(luts):
    return {'tool_name': 'set_lut', 'arguments': {'panel_ref': 'c', 'luts': luts}}


@pytest.mark.parametrize('words', ['I changed my mind use the default matplot lib lut',
                                   'use the matplotlib default colormap on c',
                                   "matplotlib's default lut please"])
def test_the_default_matplotlib_lut_is_viridis(words):
    PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', _call(['MATPLOTLIB_viridis']), STATE, words)


def test_the_default_fiji_lut_is_gray():
    PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', _call(['GRAY']), STATE,
                                                  'use the fiji default lut on c')


@pytest.mark.parametrize('words', ['use the default lut', 'back to the default colours',
                                   'restore the original lut of c'])
def test_the_default_lut_alone_is_still_the_images_own(words):
    adapter = PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool', _call(['NONE']), STATE, words)
    with pytest.raises((ValueError, NeedsClarification)):
        adapter.validate_tool_call('use_pyfigures_tool', _call(['MATPLOTLIB_viridis']), STATE, words)


def _lut(luts):
    return {'tool_name': 'set_lut', 'arguments': {'panel_ref': 'c', 'luts': luts}}


def test_default_luts_on_an_rgb_file_are_its_own():
    """The file's own colours ARE red, green, blue: both readings agree."""
    state = {'panel_references': [{'panel_id': '0/2', 'letters': ['c'], 'luts': ['GRAY', 'GRAY', 'GRAY'],
                                   'channel_colours': ['RED', 'GREEN', 'BLUE']}]}
    adapter = PyFiguresAdapter('unused')
    for luts in (['RED', 'GREEN', 'BLUE'], ['NONE', 'NONE', 'NONE']):
        adapter.validate_tool_call('use_pyfigures_tool', _lut(luts), state, 'put the default luts back on c')


def test_default_luts_ask_when_the_file_is_not_red_green_blue():
    """'default' may mean the file's own (here grays) or red, green, blue (user,
    2026-11-16: "for many people default LUT may also mean RGB ... if unsure ask")."""
    state = {'panel_references': [{'panel_id': '0/2', 'letters': ['c'], 'luts': ['MAGENTA', 'CYAN', 'YELLOW'],
                                   'channel_colours': ['GRAY', 'GRAY', 'GRAY']}]}
    adapter = PyFiguresAdapter('unused')
    from qtpy_ai_sidecar.widgets import choices
    for luts in (['RED', 'GREEN', 'BLUE'], ['NONE', 'NONE', 'NONE']):
        with pytest.raises(NeedsClarification, match='red, green, blue') as asked:
            adapter.validate_tool_call('use_pyfigures_tool', _lut(luts), state, 'put the default luts back on c')
    # the two answers are clickable, and either one settles it
    own, rgb = choices(str(asked.value))
    assert rgb == 'red, green, blue' and own.startswith("the image's own colours"), (own, rgb)
    adapter.validate_tool_call('use_pyfigures_tool', _lut(['RED', 'GREEN', 'BLUE']), state, rgb)
    adapter.validate_tool_call('use_pyfigures_tool', _lut(['NONE', 'NONE', 'NONE']), state, own)
    with pytest.raises((ValueError, NeedsClarification)):        # not the plain order: not "default"
        adapter.validate_tool_call('use_pyfigures_tool', _lut(['MAGENTA', 'GREEN', 'BLUE']), state,
                                   'put the default luts back on c')


def test_a_library_default_does_not_pass_another_lut():
    with pytest.raises((ValueError, NeedsClarification)):
        PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', _call(['MATPLOTLIB_magma']), STATE,
                                                      'use the default matplotlib lut')


class Hub:
    instructions = []
    tools = {'lut': ('demo', None, SimpleNamespace(name='set_lut', annotations=SimpleNamespace(readOnlyHint=False)))}

    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def model_tools(self):
        return []

    def direct_ids(self):
        return {'set_lut': 'lut'}

    async def execute(self, ident, arguments, emit):
        self.calls.append(arguments)
        if len(self.calls) <= 3:
            return {'is_error': True, 'error': 'refused: No LUT was changed.'}
        return {'is_error': False, 'content': 'LUT set'}


class Stubborn:
    """The same refused call three times; after "Continue", the call works."""
    def __init__(self):
        self.n = 0
        self.notes = []

    async def complete(self, messages, tools, cancel, emit, final_only=False):
        self.n += 1
        self.notes.append(any(m['role'] == 'system' and 'was stopped (repeated searches or refusals)' in m['content']
                              for m in messages))
        if final_only:
            return {'role': 'assistant', 'content': 'set_lut was refused three times.'}, {}
        if any('LUT set' in str(m.get('content')) for m in messages if m['role'] == 'tool'):
            return {'role': 'assistant', 'content': 'Done.'}, {}
        return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(self.n), 'type': 'function',
                'function': {'name': 'set_lut', 'arguments': '{"luts": ["MATPLOTLIB_viridis"]}'}}]}, {}


def test_a_stopped_turn_offers_continue_as_a_choice(tmp_path):
    calls, model = [], Stubborn()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: Hub(calls))
    events = []
    asyncio.run(engine.turn('use viridis on c', lambda *a: events.append(a)))
    reply = [v for k, v in events if k == 'assistant'][-1]
    assert reply.endswith('Should I go on?\n- Continue\n- Stop here'), reply
    assert 'Say "continue"' not in reply
    asyncio.run(engine.turn('Continue', lambda *a: events.append(a)))
    assert len(calls) == 4 and any(model.notes)
