"""Pending help/scope tests; not executed against the live application."""
import asyncio
import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def test_where_is_uses_reviewed_guide_without_model_discovery():
    adapter=PyFiguresAdapter('unused')
    calls=[]
    adapter.request=lambda operation,arguments: calls.append((operation,arguments)) or {
        'status':'source_reviewed','guide':'horizontal_flip','title':'Horizontal image flip',
        'steps':['Select the image.','Ask for a horizontal flip.']}
    result=adapter.preflight_manual_response('Where is the horizontal-flip control for a single image?')
    assert result and result['evidence']['operation_executed'] is False
    assert calls==[('manual_guide',{'topic':'Where is the horizontal-flip control for a single image?'})]

@pytest.mark.parametrize('utterance',[
    'Where is the flip control? Then flip the selected image.',
    'Where is it and rotate the panel?',
    'Where is the flip control? Show code.',
])
def test_actions_and_code_still_take_the_normal_path(utterance):
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *a:pytest.fail('No guide short-circuit is allowed for this request')
    assert adapter.preflight_manual_response(utterance) is None

def test_unreviewed_help_does_not_claim_a_verified_guide():
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *a:{'status':'needs_review','steps':['Old path']}
    assert adapter.preflight_manual_response('Where is the flip control?') is None
