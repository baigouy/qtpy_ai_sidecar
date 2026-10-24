import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.errors import NeedsClarification

def test_vague_annotation_does_not_invent_content():
    adapter=PyFiguresAdapter('unused')
    for request in ('I want to add annotyations to panel o', 'annotate panel o', 'add annotations to this panel'):
        with pytest.raises(NeedsClarification,match='What would you like'):
            adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='add_annotation',arguments=dict(text='Panel o')),{},request)
    for operation in ('select_live_objects','open_annotation_editor','find_pyfigures_tools'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name=operation,arguments={}),{},'I want to add annotyations to panel o')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='add_arrow',arguments={}),{},'add an arrow annotation to panel o')
