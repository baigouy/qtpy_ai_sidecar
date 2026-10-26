"""Oracle classifications must not hide persisted no-edit failures."""
import copy
import importlib.util
from pathlib import Path

def verifier():
    path=Path(__file__).resolve().parents[1]/'validation/pyfigures/checks.py'
    spec=importlib.util.spec_from_file_location('pending_oracle_checks',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.verify

def snapshot():
    return {'letters':{'panels':[]},'annotations':[],'rows':[],
            'document_digest':'same','caption_digest':'same'}

def events(name,refused):
    return [('tool_call',{'name':'use_pyfigures_tool','arguments':{'tool_name':name,'arguments':{}}}),
            ('tool_result',{'is_error':refused})]

def test_refused_attempt_is_efficiency_but_no_edit_state_still_checked():
    before=snapshot();after=copy.deepcopy(before)
    errors=verifier()({'no_edit':True},before,after,events('arrange_live_images',True),[])
    assert errors and all(x.startswith('Efficiency:') for x in errors)
    after['document_digest']='changed'
    errors=verifier()({'no_edit':True},before,after,events('arrange_live_images',True),[])
    assert 'Saved document_digest changed during a no-edit request' in errors

def test_successful_unallowed_edit_remains_state_failure():
    errors=verifier()({},snapshot(),snapshot(),events('arrange_live_images',False),[])
    assert any(x.startswith('Unexpected mutation operation:') for x in errors)

def test_cvd_preview_does_not_get_classified_as_a_document_edit():
    assert verifier()({'no_edit':True},snapshot(),snapshot(),events('simulate_color_blindness',False),[])==[]
