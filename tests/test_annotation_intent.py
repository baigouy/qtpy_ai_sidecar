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

def test_exact_caption_keeps_its_final_period():
    adapter=PyFiguresAdapter('unused')
    request='Set the légende to exactly: Cellules traitées.'
    with pytest.raises(ValueError,match="CAPTION_NOT_EXACT.*'Cellules traitées.'"):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_figure_caption',arguments={'caption':'Cellules traitées'}),{},request)
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_figure_caption',arguments={'caption':'Cellules traitées.'}),{},request)

@pytest.mark.parametrize('operation',['export_source_data','consolidate_figure','set_scale_bar'])
def test_how_to_questions_never_edit(operation):
    adapter=PyFiguresAdapter('unused')
    for request in ('How do I export the original source data alongside a finished figure?','How can I make a portable copy?','Can I add a scale bar?'):
        with pytest.raises(ValueError,match='HOW_TO_NO_EDIT'):
            adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name=operation,arguments={}),{},request)
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='explain_how',arguments={'operation':'x'}),{},'How do I export the source data?')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='export_source_data',arguments={}),{},'Export the source data for me.')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='export_source_data',arguments={}),{},'How do I export the source data? Please do it for me.')

SWAP_STATE={'panel_references':[{'panel_id':'0/0','letters':['a']},{'panel_id':'0/2','letters':['c']},{'panel_id':'0/1','letters':['b']}]}

def test_swap_never_substitutes_a_missing_reference():
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(ValueError,match='SWAP_REFERENCE_MISMATCH'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='swap_live_panels',arguments={'first':'a','second':'c'}),SWAP_STATE,'Swap aa with c please.')
    for first,second,request in (('a','c','Swap a with c.'),('c','a','Swap a and c'),('0/0','c','Swap a with c.'),('a','0/0','Swap a with panel 0/0.')):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='swap_live_panels',arguments={'first':first,'second':second}),SWAP_STATE,request)

def test_an_impossible_layout_never_turns_into_a_deletion():
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(ValueError,match='REMOVAL_NOT_REQUESTED'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='delete_last_rows',arguments={'count':2}),{},'Put 0 pictures per row.')
    for request in ('Delete the last two rows.','Keep only the first four rows.','Remove the final row','Get rid of the bottom row'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='delete_last_rows',arguments={'count':2}),{},request)

def test_a_missing_named_panel_is_never_retargeted():
    adapter=PyFiguresAdapter('unused')
    for call in (('select_live_objects',{'panel_ids':['0/0']}),('edit_panel_letters',{'action':'style','scope':'selection','color':'#0000ff'})):
        with pytest.raises(NeedsClarification,match="no panel 'aa'"):
            adapter.validate_tool_call(call[0] if call[0]=='select_live_objects' else 'use_pyfigures_tool',
                                       call[1] if call[0]=='select_live_objects' else dict(tool_name=call[0],arguments=call[1]),
                                       SWAP_STATE,'Select image aa, then make its letter blue.')
    adapter.validate_tool_call('select_live_objects',{'panel_ids':['0/0']},SWAP_STATE,'Select image a, then make its letter blue.')
    adapter.validate_tool_call('select_live_objects',{'panel_ids':['0/0']},SWAP_STATE,'Select panel 0/0 and move the image to the right.')
    adapter.validate_tool_call('inspect_figure',{},SWAP_STATE,'Is there an image aa?')

def test_caption_after_a_colon_keeps_its_final_period():
    adapter=PyFiguresAdapter('unused')
    request='Use this caption and italicize the species name: Cells of Drosophila melanogaster.'
    with pytest.raises(ValueError,match='CAPTION_NOT_EXACT'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_figure_caption',arguments={'caption':'Cells of Drosophila melanogaster','caption_markdown':'Cells of *Drosophila melanogaster*'}),{},request)
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_figure_caption',arguments={'caption':'Cells of Drosophila melanogaster.'}),{},request)
    # a caption that differs in wording is not this guard's business
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_figure_caption',arguments={'caption':'Drosophila cells'}),{},request)

LUT_STATE={'panel_references':[{'panel_id':'1/0','letters':['e'],'luts':['MAGENTA','GREEN','BLUE']}]}

def test_unchanged_channels_need_no_lut_name():
    adapter=PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_lut',arguments={'panel_ref':'e','luts':['MAGENTA','YELLOW','BLUE']}),
                               LUT_STATE,'Make the second channel of panel e yellow and leave the other channels alone.')

def test_a_changed_channel_still_needs_a_named_lut():
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(NeedsClarification,match='PURPLE'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_lut',arguments={'panel_ref':'e','luts':['PURPLE','GREEN','BLUE']}),
                                   LUT_STATE,'Set panel e to use a blorple LUT.')

@pytest.mark.parametrize('lut,request_text',[
    ('MATPLOTLIB_viridis_r','Invert the colors (use the reversed viridis LUT, so dark-light swap)'),
    ('GRAY_INVERTED','make panel e inverted gray'),
    ('MATPLOTLIB_viridis','use viridis on panel e')])
def test_an_inverted_or_matplotlib_lut_counts_as_named(lut,request_text):
    """'reversed viridis' named MATPLOTLIB_viridis_r but was refused (2026-11-03)."""
    PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool',dict(tool_name='set_lut',arguments={'panel_ref':'e','luts':[lut,None,None]}),
                                                  LUT_STATE,request_text)

def test_an_inverted_lut_needs_an_inverting_word():
    with pytest.raises(NeedsClarification,match='GRAY_INVERTED'):
        PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool',dict(tool_name='set_lut',arguments={'panel_ref':'e','luts':['GRAY_INVERTED',None,None]}),
                                                      LUT_STATE,'make panel e gray')

def test_an_answer_to_the_models_question_keeps_the_original_request(tmp_path):
    """'use magenta and green' -> 'Which one do you mean?' -> 'the merge panel (d)':
    the colours were named one message earlier (Mistral Large 4, 2026-11-03)."""
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.engine import Engine
    engine=Engine(Config(state_dir=str(tmp_path)),backend=object())
    engine.messages+=[{'role':'user','content':'use magenta and green'},
                      {'role':'assistant','content':'Which of these should become magenta and green: the channels, the labels or the ROI?'}]
    text=engine._guard_text('the merge panel (d)')
    assert text=='use magenta and green\nthe merge panel (d)'
    adapter=PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='set_lut',arguments={'panel_ref':'e','luts':['MAGENTA','GREEN',None]}),
                               LUT_STATE,text)
    # a new request after a finished reply (no question) is checked on its own
    engine.messages.append({'role':'assistant','content':'Done: panel e uses magenta and green.'})
    assert engine._guard_text('make panel e purple')=='make panel e purple'


@pytest.mark.parametrize('call',[('remove_group',{'group_path':[5]}),('delete_last_rows',{'count':1})])
def test_one_picture_never_removes_a_row(call):
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(ValueError,match='SCOPE_MISMATCH.*remove_image'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name=call[0],arguments=call[1]),{},'Delete the very last picture.')
    for request in ('Delete the last row.','Remove the last two rows of images.','Delete the bottom group'):
        adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name=call[0],arguments=call[1]),{},request)

@pytest.mark.parametrize('request_text',['Make the letter of the third picture in the second row yellow.',
                                         'Make the letter of the top-left image yellow.'])
def test_positional_reference_is_an_explicit_target(request_text):
    adapter=PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool',dict(tool_name='edit_panel_letters',arguments={'action':'style','scope':'panels','panel_ids':['1/2'],'color':'#ffff00'}),
                               {'selection':{'selected_panels':[]}},request_text)
