"""Pure preflight tests; no model calls or GUI construction."""
import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def test_rows_is_not_silently_interpreted_as_columns():
    with pytest.raises(ValueError,match='Use columns'):
        PyFiguresAdapter._efficient_arguments('arrange_live_images',{'rows':4},{})

def test_annotation_hint_does_not_retarget_or_autofill():
    state={'panel_references':[{'panel_id':'1/3','letters':['h']}],
           'text_annotations':[{'panel_id':'1/3','annotation_index':1,'token':'fresh'}]}
    args={'panel_ref':'h','annotation_index':1,'changes':{'bold':True}}
    with pytest.raises(ValueError,match='token=fresh'):
        PyFiguresAdapter._efficient_arguments('edit_annotation_properties',args,state)
    assert 'token' not in args
    args['token']='fresh'
    PyFiguresAdapter._efficient_arguments('edit_annotation_properties',args,state)

def test_dump_noops_are_removed_but_changes_refused():
    state={'verified_letter_specification':{'uniform_letter_style':{'bold':False,'opacity':1.0}}}
    args={'action':'style','scope':'all','color':'yellow','bold':False,'opacity':1.0}
    PyFiguresAdapter._efficient_arguments('edit_panel_letters',args,state)
    assert args=={'action':'style','scope':'all','color':'yellow'}
    with pytest.raises(ValueError,match='No edit submitted'):
        PyFiguresAdapter._efficient_arguments('edit_panel_letters',{'bold':True},state)

def test_draft_object_token_has_priority():
    state={'panel_references':[{'panel_id':'1/3','letters':['h']}],
           'annotation_editor_open':True,
           'annotation_editor':{'editor_panel_id':'1/3','editor_draft_objects':[{'annotation_index':1,'token':'draft'}]},
           'roi_annotations':[{'panel_id':'1/3','annotation_index':1,'token':'main'}]}
    with pytest.raises(ValueError,match='token=draft'):
        PyFiguresAdapter._efficient_arguments('edit_annotation_properties',{'panel_ref':'h','annotation_index':1,'token':'main'},state)
