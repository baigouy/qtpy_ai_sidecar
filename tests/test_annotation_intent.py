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


def test_singular_scale_bar_cannot_broaden_to_all_panels():
    adapter=PyFiguresAdapter('unused')
    for request in ('Give a a 10 micrometre scale bar', 'Add a scale bar to the selected image', 'Give panel c a scale bar'):
        with pytest.raises(ValueError,match='SCOPE_MISMATCH'):
            adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_scale_bar_all',arguments={}),{},request)
    for request in ('Give each image a scale bar','Add scale bars','Give all panels a scale bar'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_scale_bar_all',arguments={}),{},request)
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_scale_bar',arguments={}),{},'Give a a scale bar')


@pytest.mark.parametrize('request_text,panel',[('Give a a 10 micrometre scale bar','a'),('Give panel c a scale bar','c'),
                                               ('Put b a 5 um scale bar','b'),('Add a scale bar to the selected image',None),
                                               ('Give the selected panel a 10 um scale bar',None),('Give this image a 10 um scale bar',None),
                                               ('Give panel a a 10 um scale bar','a')])
def test_scope_mismatch_names_the_requested_panel(request_text,panel):
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(ValueError) as error:
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_scale_bar_all',arguments={}),{},request_text)
    if panel:
        assert f"names panel '{panel}': call set_scale_bar with panel_ref='{panel}'" in str(error.value)
    else:
        assert 'names panel' not in str(error.value) and 'Ask which image' in str(error.value)

@pytest.mark.parametrize('call',[
    ('set_panel_letter_position',{'placement':'bottom left'}),
    ('edit_panel_letters',{'scope':'all','placement':'bottom left'}),
])
def test_unknown_corner_is_never_replaced_by_a_real_one(call):
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(NeedsClarification,match='flarble corner'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name=call[0],arguments=call[1]),{},'Put all letters in the flarble corner.')

def test_known_corner_passes_the_corner_guard():
    adapter=PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_panel_letter_position',arguments={'placement':'bottom right'}),{},'Put all letters in the bottom right corner.')
