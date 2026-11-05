"""User chat 2026-11-05: "swap chanel 1 and 2 in this imlage pls" on an LSM
whose LUTs had been reset (the file's own RED, GREEN, BLUE): set_lut GREEN,
RED was refused as "not named"; a swap moves the colours already shown."""
import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.errors import NeedsClarification

STATE = {'panel_references': [{'panel_id': '1/1', 'letters': ['e'], 'luts': None,
                               'channel_colours': ['RED', 'GREEN', 'BLUE']}]}


def _call(luts):
    return {'tool_name': 'set_lut', 'arguments': {'panel_ref': 'e', 'luts': luts}}


def test_swapping_the_shown_colours_needs_no_names():
    adapter = PyFiguresAdapter('unused')
    request = 'swap chanel 1 and 2 in this imlage pls'
    adapter.validate_tool_call('use_pyfigures_tool', _call(['GREEN', 'RED', None]), STATE, request)
    adapter.validate_tool_call('use_pyfigures_tool', _call(['GREEN', 'RED', 'BLUE']), STATE, request)
    adapter.validate_tool_call('use_pyfigures_tool', _call(['BLUE', 'GREEN', 'RED']), STATE, 'exchange the colours of channels 1 and 3 in e')


def test_a_colour_the_image_does_not_show_still_needs_the_users_word():
    adapter = PyFiguresAdapter('unused')
    with pytest.raises(NeedsClarification):
        adapter.validate_tool_call('use_pyfigures_tool', _call(['MAGENTA', 'RED', None]), STATE, 'swap channels 1 and 2 in e')
    # not a swap: a new colour must be named
    with pytest.raises(NeedsClarification):
        adapter.validate_tool_call('use_pyfigures_tool', _call(['GREEN', 'RED', None]), STATE, 'make e look nicer')


def test_keeping_a_channels_file_colour_needs_no_name():
    adapter = PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool', _call(['MAGENTA', 'GREEN', 'BLUE']), STATE, 'make channel 1 of e magenta')
