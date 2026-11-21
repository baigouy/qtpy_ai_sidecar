"""Replays 2026-11-20 (Mistral and Qwen): "make b letter red" -> edit_panel_letters(color=
"red", panel_ids=[b]) without color_request was refused, then sent again with the same
words. When the request's own words name the letter, they are filled in as the quote."""
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

STATE = {'panel_references': [{'panel_id': '0/0/1', 'letters': ['b']}],
         'selection': {}}


def _call(**args):
    return {'tool_name': 'edit_panel_letters',
            'arguments': {'action': 'style', 'scope': 'panels', 'panel_ids': ['0/0/1'], **args}}


def test_the_users_words_naming_the_letter_become_the_quote():
    adapter = PyFiguresAdapter('unused')
    call = _call(color='red')
    adapter.validate_tool_call('use_pyfigures_tool', call, STATE, 'make b letter red')
    assert call['arguments']['color_request'] == 'make b letter red'
    call = _call(background='black')
    adapter.validate_tool_call('use_pyfigures_tool', call, STATE, 'add a black box behind the letter of b')
    assert call['arguments']['background_request'] == 'add a black box behind the letter of b'


def test_words_that_do_not_name_the_letter_are_not_quoted():
    adapter = PyFiguresAdapter('unused')
    call = _call(color='red')
    try:
        adapter.validate_tool_call('use_pyfigures_tool', call, STATE, 'change the colour of b to red')
    except Exception:
        pass                                    # the guard (PyFigures side) may ask
    assert 'color_request' not in call['arguments']
    call = _call(color='red', color_request='the letter b in red')   # the model's own quote is kept
    adapter.validate_tool_call('use_pyfigures_tool', call, STATE, 'make b letter red')
    assert call['arguments']['color_request'] == 'the letter b in red'
