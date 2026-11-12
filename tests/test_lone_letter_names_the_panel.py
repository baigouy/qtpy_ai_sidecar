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


@pytest.mark.parametrize('text', ['same scale bar everywhere, 20 um', 'bars in black', 'une barre de 10 µm partout'])
def test_everywhere_and_plural_bars_mean_every_panel(text):
    """'same scale bar everywhere' was refused four times as a single-panel request (2026-11-12)."""
    call(text, 'set_scale_bar_all', {'bar_width_in_units': 20})


def test_one_bar_is_still_not_every_panel():
    with pytest.raises(ValueError, match='SCOPE_MISMATCH'):
        call('add a 20 um scale bar', 'set_scale_bar_all', {'bar_width_in_units': 20})


@pytest.mark.parametrize('text', ['make the letter bigger', 'the letter is hard to see', 'add a label in a corner'])
def test_no_panel_named_still_asks(text):
    with pytest.raises(NeedsClarification, match='tell me its panel label'):
        call(text, 'edit_panel_letters', {'action': 'style', 'scope': 'panels', 'panel_ids': ['2/0'], 'font_size': 18})
