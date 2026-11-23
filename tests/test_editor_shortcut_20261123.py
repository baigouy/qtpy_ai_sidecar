"""User chat 2026-11-23 ("it opened the crop for the wrong panel"): after the chat cropped a,
"have me edit it manually" opened the editor of the SELECTED panel b on its Annotations tab;
"I meant I wanna edit crop in a" opened "panel **the selected panel**" (the lone "a" was read
as an article); "show me how to do that manually" (a projection) opened d's Annotations tab
instead of showing where to click."""
import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

STATE = {'selection': {'selected_panels': [{'panel_id': '0/1'}]},
         'panel_references': [{'panel_id': f'0/{i}', 'letters': [l]} for i, l in enumerate('abcd')]}


def _adapter(tmp_path):
    adapter = PyFiguresAdapter(tmp_path / 'bridge.json')
    opened = []

    def request(operation, arguments=None):
        if operation == 'inspect':
            return STATE
        if operation == 'open_annotation_editor':
            opened.append(arguments)
            return {'status': 'scheduled'}
        raise AssertionError(operation)
    adapter.request = request
    return adapter, opened


def _crop_a(adapter):
    adapter.preflight_manual_response('crop panel a so that I only see the top right object')
    adapter.validate_tool_call('preview_panel', {'panel_ref': 'a', 'view': 'source'}, STATE,
                               'crop panel a so that I only see the top right obejct')
    adapter.validate_tool_call('use_pyfigures_tool', {'tool_name': 'transform_image', 'arguments': {
        'panel_ref': 'a', 'crop_left': 145, 'crop_right': 19, 'crop_top': 18, 'crop_bottom': 68}},
        STATE, 'crop panel a so that I only see the top right obejct')


def test_edit_it_manually_after_a_crop_opens_that_panels_crop(tmp_path):
    adapter, opened = _adapter(tmp_path)
    _crop_a(adapter)
    out = adapter.preflight_manual_response('have me edit it manually')
    assert opened == [{'panel_ref': 'a', 'tab': 'crop'}]
    assert 'panel **a**' in out['content'] and 'Rotate + Crop' in out['content']


@pytest.mark.parametrize('text', ['I meant I wanna edit crop in a', 'let me edit the crop of a',
                                  'I want to adjust the crop for a myself'])
def test_a_lone_a_at_the_end_names_panel_a(tmp_path, text):
    adapter, opened = _adapter(tmp_path)
    out = adapter._open_editor_for_self_edit(text)
    assert opened == [{'panel_ref': 'a', 'tab': 'crop'}], (text, opened)
    assert 'panel **a**' in out['content']


def test_a_in_the_middle_is_still_an_article(tmp_path):
    adapter, _ = _adapter(tmp_path)
    assert adapter._named_panel('let me edit the crop in a minute', STATE) is None


def test_show_me_how_is_left_to_the_model(tmp_path):
    adapter, opened = _adapter(tmp_path)
    for text in ('shwo me how to do that manually', 'show me how to do it myself', 'how do I do that by hand'):
        assert adapter._open_editor_for_self_edit(text) is None and opened == [], text


def test_the_selected_panel_is_named_by_its_letter(tmp_path):
    adapter, opened = _adapter(tmp_path)
    out = adapter._open_editor_for_self_edit('let me edit the crop myself')
    assert opened == [{'panel_ref': '0/1', 'tab': 'crop'}]
    assert 'panel **b**' in out['content'] and 'the selected panel' not in out['content']
