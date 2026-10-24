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
