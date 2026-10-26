"""Font answers must match independent state and read-only question contracts."""
import importlib.util
from pathlib import Path
import pytest
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('font_checks',root/'validation/pyfigures/checks.py')
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
def events(reply,query='Helvetica'):
    args={} if query is None else {'query':query}
    return [('tool_call',{'name':'use_pyfigures_tool','arguments':{'tool_name':'list_fonts','arguments':args}}),('assistant',reply)]
def state(installed=False):
    return {'font_status':{'Helvetica':{'installed':installed,'drawn_as':'Arial','alternatives':['Arial','DejaVu Sans']}}}
def test_missing_font_reports_actual_substitution():
    assert checks.verify_font_reply({'kind':'query','query':'Helvetica'},state(),events('Helvetica is not installed. It is drawn and exported as Arial; Arial is an installed alternative.'))==[]
@pytest.mark.parametrize('reply',[
    'Helvetica is installed.',
    'Helvetica is not installed.',
    'Helvetica is not installed. It is rendered as Times New Roman.',
])
def test_unverified_font_claims_fail(reply):
    assert checks.verify_font_reply({'kind':'query','query':'Helvetica'},state(),events(reply))
def test_installed_font_cannot_be_called_missing():
    assert checks.verify_font_reply({'kind':'query','query':'Helvetica'},state(True),events('Helvetica is not installed.'))
def test_font_question_needs_the_query_tool():
    assert checks.verify_font_reply({'kind':'query','query':'Helvetica'},state(),[('assistant','Helvetica is not installed; rendered as Arial, an alternative.')])
def test_inventory_needs_unfiltered_list():
    assert checks.verify_font_reply({'kind':'inventory'},{},events('Available font families include Arial.',None))==[]
    assert checks.verify_font_reply({'kind':'inventory'},{},events('Available font families include Arial.'))
def test_edit_requires_substitution_note_when_missing():
    assert checks.verify_font_reply({'kind':'edit','query':'Helvetica'},state(),[('assistant','Done, Helvetica applied.')])
    assert checks.verify_font_reply({'kind':'edit','query':'Helvetica'},state(),[('assistant','Helvetica requested. It is not installed; rendered as Arial, an installed alternative.')])==[]

def test_installed_font_reply_can_also_mention_another_missing_font():
    assert checks.verify_font_reply({'kind':'query','query':'Helvetica'},state(True),events('Helvetica is installed. Other fonts such as Nimbus Sans are not installed.'))==[]

def test_native_preflight_is_independent_of_offscreen_font_database():
    spec=importlib.util.spec_from_file_location('font_oracle',root/'validation/pyfigures/font_oracle.py')
    oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    import json
    truth={'requested':'Helvetica','installed':False,'drawn_as':'Arial','alternatives':['Arial']}
    calls=[]
    def native(**kwargs):
        calls.append(kwargs)
        return json.dumps({'font_check':truth,'count':0,'installed_families':[]})
    statuses,evidence=oracle.read_font_truth(['Helvetica','Helvetica'],native)
    assert calls==[{'query':'Helvetica'}]
    assert statuses=={'Helvetica':truth} and evidence['Helvetica']['font_check']==truth

@pytest.mark.parametrize('status',[None,{}, {'requested':'Arial','installed':True}, {'requested':'Helvetica','installed':'false'}])
def test_native_preflight_rejects_incomplete_or_wrong_truth(status):
    spec=importlib.util.spec_from_file_location('font_oracle',root/'validation/pyfigures/font_oracle.py')
    oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    with pytest.raises(ValueError):
        oracle.read_font_truth(['Helvetica'],lambda **kw:{'font_check':status})
