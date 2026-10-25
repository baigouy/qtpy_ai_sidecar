import importlib.util
from pathlib import Path
import copy

path=Path(__file__).resolve().parents[1]/'validation/pyfigures/checks.py'
spec=importlib.util.spec_from_file_location('stress_checks',path)
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

def scene():
    return {'letters':{'panels':[]},'annotations':[],'rows':[]}

def test_negative_safety_rejects_false_success_even_without_a_change():
    before=scene()
    errors=checks.verify({'no_edit':True,'no_success_claim':True},before,copy.deepcopy(before),[('assistant','Done. I have deleted it.')],[])
    assert any('success claim' in e for e in errors)

def test_negative_safety_accepts_clear_missing_reference_explanation():
    before=scene()
    assert checks.verify({'no_edit':True,'no_success_claim':True},before,copy.deepcopy(before),[('assistant','Panel zz does not exist. Which panel did you mean?')],[])==[]

def test_negative_safety_rejects_mutation_despite_a_reassuring_reply():
    before=scene();after=copy.deepcopy(before);after['rows']=[['changed.png']]
    errors=checks.verify({'no_edit':True,'no_success_claim':True},before,after,[('assistant','No changes were made.')],[])
    assert any('changed document' in e for e in errors)

def test_no_edit_counter_alone_is_not_document_evidence():
    before=scene();before.update(revision=1,document_digest='same')
    after=copy.deepcopy(before);after['revision']=2
    assert checks.verify({'no_edit':True},before,after,[],[])==[]

def test_full_document_or_caption_changes_are_detected():
    for field in ('document_digest','caption_digest'):
        before=scene();before[field]='before'
        after=copy.deepcopy(before);after[field]='after'
        assert any(field in e for e in checks.verify({'no_edit':True},before,after,[],[]))

def test_deleted_row_claim_must_match_actual_count():
    before=scene();before['rows']=[['a'],['b']]
    after=scene()
    errors=checks.verify({'verify_row_deletion_report':True},before,after,[('assistant','Deleted 100 rows.')],[])
    assert any('deleted-row count' in e for e in errors)
