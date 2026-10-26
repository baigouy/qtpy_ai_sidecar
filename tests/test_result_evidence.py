"""Result evidence preserves requested edits and makes limitations observable."""
import importlib.util,json
from pathlib import Path
import sys
import pytest
prototype=Path(__file__).resolve().parents[2]/'pyfigures_pkg/chatGPT_validation/live_mcp_gui'
if not (prototype/'result_evidence.py').exists():
    pytest.skip('Optional prototype not installed',allow_module_level=True)
spec=importlib.util.spec_from_file_location('result_evidence_unit',prototype/'result_evidence.py')
evidence=importlib.util.module_from_spec(spec);spec.loader.exec_module(evidence)
STATUS={'requested':'Helvetica','installed':False,'drawn_as':'Arial','alternatives':['Arial','DejaVu Sans']}
def test_missing_font_evidence_preserves_original_result_and_request():
    original={'verified_changes':[{'font_family':'Helvetica'}],'note':'Previous note.'}
    result=evidence.with_font_evidence(original,'Helvetica',lookup=lambda family:dict(STATUS))
    assert result['font_check']==STATUS
    assert 'not installed' in result['note'] and 'Arial' in result['note']
    assert result['note'].startswith('Previous note.')
    assert original=={'verified_changes':[{'font_family':'Helvetica'}],'note':'Previous note.'}
    assert result['verified_changes']==original['verified_changes']
def test_installed_font_has_no_false_missing_note():
    original={'success':True}
    assert evidence.with_font_evidence(original,'Arial',lookup=lambda family:{'installed':True}) is original
def test_no_requested_family_does_not_query_fonts():
    def forbidden(_):raise AssertionError('Unrequested font query')
    value={'result':'ok'}
    assert evidence.with_font_evidence(value,None,lookup=forbidden) is value
def test_failed_font_check_keeps_the_completed_edit_result():
    def unavailable(_):raise RuntimeError('font process unavailable')
    result=evidence.with_font_evidence({'changed':True},'Helvetica',lookup=unavailable)
    assert result['changed'] is True
    assert 'font_check_error' in result and 'font_check' not in result
    assert 'could not be verified' in result['note']
def test_inventory_is_bounded_and_does_not_mutate_native_report():
    names=['Font '+str(i) for i in range(100)]+['Arial','DejaVu Sans']
    original={'installed_families':names,'count':102,'has_arial':True}
    result=evidence.compact_font_inventory(json.dumps(original))
    assert result['count']==102 and result['total_count']==102
    assert result['returned_count']==20 and result['truncated'] is True
    assert result['installed_families'][:2]==['Arial','DejaVu Sans']
    assert len(names)==102 and 'query' in result['guidance']
def test_small_inventory_retains_every_family():
    result=evidence.compact_font_inventory({'installed_families':['Arial'],'count':1})
    assert result['installed_families']==['Arial'] and result['truncated'] is False
@pytest.mark.parametrize('caption',['Cells.','Cells',''])
def test_caption_echo_reads_persisted_text_not_requested_text(tmp_path,caption):
    path=tmp_path/'current.caption.json'
    path.write_text(json.dumps({'title':'Figure 1','caption':caption,'caption_markdown':'*Cells*.'}),encoding='utf-8')
    result=evidence.caption_evidence(path)
    assert result['caption_text']==caption
    assert result['caption_ends_with_period']==caption.endswith('.')
    assert result['caption_title']=='Figure 1'
def test_missing_caption_does_not_invent_an_echo(tmp_path):
    result=evidence.caption_evidence(tmp_path/'absent.json')
    assert 'caption_readback_error' in result and 'caption_text' not in result

def test_font_limitations_survive_the_engine_result_prefix_bound():
    large={'operation_result':{'verified_panels':['long detail '*1000]*24},'document_changed':True}
    result=evidence.with_font_evidence(large,'Helvetica',lookup=lambda family:dict(STATUS))
    # MCP carries the JSON result as text; the engine serializes that outer object.
    model_payload=json.dumps({'is_error':False,'content':json.dumps(result,indent=2)},ensure_ascii=False)
    assert len(model_payload)>24000
    assert 0<=model_payload.index('font_check')<1000
    assert 0<=model_payload.index('not installed')<1000
    assert 'drawn/exported as Arial' in model_payload[:24000]
    assert result['operation_result']==large['operation_result']
