"""Pending guard tests. Do not run while CLAUDE_ACTIVE_RUN.json exists."""
import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def scene():
    return {'panel_references':[
        {'panel_id':'0/0','group_path':[0],'image_index':0,'letters':['a']},
        {'panel_id':'1/1','group_path':[1],'image_index':1,'letters':['f']},
        {'panel_id':'1/3','group_path':[1],'image_index':3,'letters':['h']},
        {'panel_id':'2/2','group_path':[2],'image_index':2,'letters':['k']}]}

def guard(text,args):
    return PyFiguresAdapter._named_panel_address_guard('edit_panel_letters',args,scene(),text)

def test_wrong_numeric_address_is_refused_and_never_retargeted():
    args={'scope':'panels','panel_ids':['1/1'],'color':'yellow'}
    original=dict(args)
    with pytest.raises(ValueError,match=r'you targeted f \(1/1\); the request names h \(1/3\)'):
        guard('Select h and make only its letter yellow.',args)
    assert args==original

@pytest.mark.parametrize('utterance',[
    'Select h and make only its letter yellow. Leave every other letter alone.',
    'Make letter h yellow and keep all the others as they are.',
    'Make letter h yellow without changing any other letter.'])
def test_a_preservation_clause_does_not_disable_the_guard(utterance):
    with pytest.raises(ValueError,match='you targeted f'):
        guard(utterance,{'scope':'panels','panel_ids':['1/1']})

def test_matching_numeric_address_passes():
    guard('Make letter h yellow.',{'scope':'panels','panel_ids':['1/3']})

def test_request_without_a_named_letter_passes():
    guard('Make the selected letter yellow.',{'scope':'panels','panel_ids':['1/1']})

@pytest.mark.parametrize('target',['1/3','2/2'])
def test_any_one_of_several_named_panels_passes(target):
    guard('Make letters h and k yellow.',{'scope':'panels','panel_ids':[target]})

def test_group_path_and_index_are_checked():
    with pytest.raises(ValueError,match='you targeted f'):
        PyFiguresAdapter._named_panel_address_guard('add_annotation',{'group_path':[1],'image_index':1},scene(),'Add text to panel h.')

@pytest.mark.parametrize('utterance',['Make a and its neighbour yellow.','Make panel h and its neighbor yellow.'])
def test_relative_target_sets_are_not_guessed(utterance):
    guard(utterance,{'scope':'panels','panel_ids':['1/1']})

@pytest.mark.parametrize('utterance',['Make panel omega yellow.','Make letter z yellow.'])
def test_absent_or_greek_name_falls_through(utterance):
    guard(utterance,{'scope':'panels','panel_ids':['1/1']})

def test_named_reference_goes_to_existing_resolver():
    guard('Make letter h yellow.',{'panel_ref':'f'})

def test_numeric_panel_ref_is_an_address():
    with pytest.raises(ValueError,match='you targeted f'):
        guard('Make letter h yellow.',{'panel_ref':'1/1'})

def test_duplicate_labels_do_not_establish_a_certain_conflict():
    state=scene()
    state['panel_references'].append({'panel_id':'3/0','letters':['h']})
    PyFiguresAdapter._named_panel_address_guard('add_annotation',{'group_path':[1],'image_index':1},state,'Add text to panel h.')

def test_read_only_call_and_quoted_annotation_text_are_not_panel_mutations():
    PyFiguresAdapter._named_panel_address_guard('get_annotations',{'group_path':[1],'image_index':1},scene(),'Inspect panel h.')
    guard('Write "panel h" on the selected image.',{'scope':'panels','panel_ids':['1/1']})

def test_pre_dispatch_hook_refuses_before_other_lettering_checks():
    adapter=PyFiguresAdapter('unused')
    with pytest.raises(ValueError,match='you targeted f'):
        adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'edit_panel_letters','arguments':{'scope':'panels','panel_ids':['1/1'],'color':'yellow'}},scene(),'Select h and make only its letter yellow.')


@pytest.mark.parametrize('utterance',[
    'Make a scale bar on the selected image.',
    'Make a 10 \u00b5m scale bar on the selected image.',
    'Add a box to the selected image.',
])
def test_indefinite_article_is_not_panel_a(utterance):
    PyFiguresAdapter._named_panel_address_guard('set_scale_bar',
        {'group_path':[1],'image_index':1},scene(),utterance)

def test_explicit_panel_a_still_checks_the_address():
    guard('Make panel a yellow.',{'panel_ids':['0/0']})
    with pytest.raises(ValueError,match=r'the request names a \(0/0\)'):
        guard('Make panel a yellow.',{'panel_ids':['1/1']})

def test_mixed_greek_list_falls_through_without_false_conflict():
    guard('Make panels h and omega yellow.',{'panel_ids':['1/1']})
