import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def test_selected_letter_guidance_and_scope_guard(tmp_path):
    adapter=PyFiguresAdapter(tmp_path/'bridge.json')
    state={'selection':{'selection_kind':'image2d','selected_panels':[{'panel_id':'2/0'}]}}
    assert '2/0' in adapter.context_instructions(state)
    assert 'do not ask' in adapter.context_instructions(state)
    wrap=lambda args:{'tool_name':'edit_panel_letters','arguments':args}
    adapter.validate_tool_call('use_pyfigures_tool',wrap({'scope':'panels','panel_ids':['2/0'],'color':'white'}),state,'make this letter white')
    adapter.validate_tool_call('use_pyfigures_tool',wrap({'scope':'selection','color':'white'}),state,'make this letter white')
    with pytest.raises(ValueError,match='only panel'):
        adapter.validate_tool_call('use_pyfigures_tool',wrap({'color':'white'}),state,'make this letter white')
    with pytest.raises(ValueError,match='only panel'):
        adapter.validate_tool_call('use_pyfigures_tool',wrap({'scope':'panels','panel_ids':['0/0']}),state,'make this letter white')
    adapter.validate_tool_call('use_pyfigures_tool',wrap({'color':'white'}),state,'make all letters white')


def test_pronoun_followup_and_omitted_scope(tmp_path):
    adapter=PyFiguresAdapter(tmp_path/'bridge.json')
    state={'selection':{'selected_panels':[{'panel_id':'2/0'}]}}
    args={'tool_name':'edit_panel_letters','arguments':{'panel_ids':['2/0'],'color':'blue'}}
    adapter.validate_tool_call('use_pyfigures_tool',args,state,'I changed my mind make it blue')
    assert args['arguments']['scope']=='panels'
    with pytest.raises(ValueError):
        adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'edit_panel_letters','arguments':{'color':'blue'}},state,'make it blue')

def test_verified_color_finishes_only_for_exact_target(tmp_path):
    import json
    adapter=PyFiguresAdapter(tmp_path/'bridge.json')
    state={'selection':{'selected_panels':[{'panel_id':'2/0'}]}}
    result={'is_error':False,'content':json.dumps({'operation_result':{'matched_panel_ids':['2/0'],'changed':1,'verified_changes':[{'property':'color'}],'verified_panels':[{'panel_id':'2/0','letters':[{'color':'#0000ff'}]}]}})}
    summary=adapter.verified_completion('use_pyfigures_tool',{'tool_name':'edit_panel_letters'},result,state,'make it blue')
    assert '2/0' in summary and 'blue' in summary
    state['selection']['selected_panels']=[{'panel_id':'0/0'}]
    assert adapter.verified_completion('use_pyfigures_tool',{'tool_name':'edit_panel_letters'},result,state,'make it blue') is None
