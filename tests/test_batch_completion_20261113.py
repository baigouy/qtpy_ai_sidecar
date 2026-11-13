"""A batch that did the whole request answers at once (user, 2026-11-13: "rotate all
image by 25 degrees" was done in 2 s, then an inspect of the whole figure and a re-read
of every rotation kept the prompt busy 45 s). Each batch item also passes the guards."""
import json

import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

CALL = {'tool_name': 'transform_image', 'arguments': {'rotation': 25},
        'batch': [{'panel_ref': r} for r in 'abcde']}


def _result(done=5, errors=(), verified=True):
    body = {'result': f'transform_image: {done} of 5 item(s) done in one call', 'batch_done': done,
            'batch_total': 5, 'document_changed': True, 'errors': list(errors)}
    if verified:
        body['verified'] = 'Each item was applied to the open figure and read back.'
    return {'is_error': False, 'content': json.dumps(body)}


def _reply(text, result=None, call=CALL):
    return PyFiguresAdapter('unused').verified_completion('use_pyfigures_tool', call, result or _result(), {}, text)


@pytest.mark.parametrize('text', ['rotate all image by 25 degrees', 'Rotate every panel by 25°.',
                                  'rotate them all 25 degrees please'])
def test_one_instruction_done_in_one_batch_is_answered_at_once(text):
    out = _reply(text)
    assert out and 'rotation=25' in out and '**a**' in out and '**e**' in out and 'read back' in out


@pytest.mark.parametrize('text', ['rotate all images by 25 degrees and crop them', 'rotate a, b and c then crop',
                                  'rotate everything by 25 degrees, then show me', 'rotate all by 25; make them red'])
def test_more_than_one_thing_asked_goes_back_to_the_model(text):
    assert _reply(text) is None


def test_many_items_name_each_panel_once():
    """81 ROIs were listed 'panels b, b, b, b, ...' (live replay, 2026-11-13)."""
    call = {'tool_name': 'set_roi_properties', 'arguments': {'stroke': 0.65},
            'batch': [{'panel_ref': 'b', 'annotation_index': i} for i in range(3)]
                     + [{'panel_ref': 'd', 'annotation_index': i} for i in range(2)]}
    out = _reply('make all strokes 0.65', call=call)
    assert out and '5 items in panels **b**, **d**' in out and out.count('**b**') == 1


def test_failed_partial_or_unverified_batches_go_back_to_the_model():
    assert _reply('rotate all by 25', _result(done=4, errors=[{'item': 5}])) is None
    assert _reply('rotate all by 25', _result(verified=False)) is None
    assert _reply('rotate all by 25', {'is_error': True, 'content': 'boom'}) is None
    single = {'tool_name': 'transform_image', 'arguments': {'rotation': 25, 'panel_ref': 'a'}}
    assert _reply('rotate a by 25', call=single) is None


def test_each_batch_item_passes_the_guards():
    """remove_rois without words asking for a removal is refused, also inside a batch."""
    with pytest.raises(ValueError, match='REMOVAL_NOT_REQUESTED'):
        PyFiguresAdapter('unused').validate_tool_call(
            'use_pyfigures_tool', {'tool_name': 'remove_rois', 'arguments': {},
                                   'batch': [{'panel_ref': 'a'}, {'panel_ref': 'b'}]}, {}, 'make the boxes red')
