"""A lone letter in the request names the panel: "make g bigger" then "the
letter", and "add a label to b", were both refused with "Please select the
panel with the hard-to-see letter" although the panel was named (Mistral
Large 4 on a nine-panel figure, 2026-11-10)."""
import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.errors import NeedsClarification

STATE = {'selection': {'selected_panels': []},
         'panel_references': [{'panel_id': '0/1', 'letters': ['B']}, {'panel_id': '2/0', 'letters': ['G']}]}


def call(text, tool, arguments):
    PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', {'tool_name': tool, 'arguments': arguments}, STATE, text)


@pytest.mark.parametrize('text', ['make g bigger\nthe letter', 'change the colour of a to red\nthe letter',
'the letter of G should be bigger', 'make the letter in g bigger'])
def test_a_lone_letter_names_the_panel_of_a_letter_edit(text):
    call(text, 'edit_panel_letters', {'action': 'style', 'scope': 'panels', 'panel_ids': ['2/0'], 'font_size': 18})


@pytest.mark.parametrize('text', ['add a label to b', 'put a label on a', 'I want a label in i.'])
def test_a_label_for_a_named_panel_is_not_refused(text):
    call(text, 'select_live_objects', {'panel_refs': ['B']})


@pytest.mark.parametrize('text', ['make the letter bigger', 'the letter is hard to see', 'add a label in a corner'])
def test_no_panel_named_still_asks(text):
    with pytest.raises(NeedsClarification, match='tell me its panel label'):
        call(text, 'edit_panel_letters', {'action': 'style', 'scope': 'panels', 'panel_ids': ['2/0'], 'font_size': 18})
