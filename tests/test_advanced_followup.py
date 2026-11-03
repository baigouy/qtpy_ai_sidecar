import asyncio,importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

base=Path(__file__).resolve().parents[1]
prototype=base.parent/'pyfigures_pkg/chatGPT_validation/live_mcp_gui'

def test_selection_clause_cannot_be_replaced_by_style():
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *a:{'selection':{'selected_panels':[]}}
    result=adapter.finalize_response('Select h and make only its letter yellow.','Done. The letter is now yellow.',{})
    assert result['evidence']['status']=='incomplete_selection'
    adapter.request=lambda *a:{'selection':{'selected_panels':[{'panel_id':'1/3','letters':['h']}]}}
    assert adapter.finalize_response('Select h and make only its letter yellow.','Done.',{}) is None

def test_readiness_without_a_known_target_asks_which_journal():
    """'Is it ready?' with no journal named and none stored: a question, not an
    'ERROR: specify a target width' (PyFigures Figure 3 chat trials, 2026-11-02)."""
    adapter=PyFiguresAdapter('unused')
    def request(op,*a):
        if op=='submission_review':raise ValueError('NO_TARGET: no journal or figure width is known')
        return {'selection':{'selected_panels':[]}}
    adapter.request=request
    result=adapter.finalize_response('is the figure ready for submission?','Yes.',{})
    assert result['evidence']['status']=='needs_target'
    assert result['content'].startswith('Which journal')

def test_an_empty_figure_sends_a_short_state():
    """'Tell me more about the fig' on an empty window cost a cloud model two slow
    tool steps (2026-11-03): the state and guidance let it answer at once."""
    adapter=PyFiguresAdapter('unused')
    summary={'empty':True,'answer':'The figure is empty.','how_to_add_content':'add_image ...'}
    adapter.request=lambda *a:{'figure_summary':summary,'selection':{'selected_panels':[]},'panel_references':[],
                               'verified_letter_specification':{},'native_gui_available':True,'revision':1,'dirty':False}
    state=adapter.context()
    assert set(state)=={'figure_summary','native_gui_available','revision','dirty'}
    guidance=adapter.context_instructions(state)
    assert 'without tools' in guidance and len(guidance)<300
    adapter.request=lambda *a:{'figure_summary':{'empty':False,'answer':'2 image panel(s)'},'panel_references':[{'panel_id':'0/0'}]}
    state=adapter.context()
    assert state['figure_summary']['answer']=='2 image panel(s)' and state['panel_references']
    assert 'without calling inspect_figure again' in adapter.context_instructions(state)

def test_selection_verifier_checks_all_explicit_targets():
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *a:{'selection':{'selected_panels':[{'panel_id':'0/0','letters':['a']},{'panel_id':'0/1','letters':['b']}]}}
    result=adapter._verify_requested_selection('Select a, b and c.','Done.')
    assert result['evidence']['missing']==['c']

def test_native_wrappers_expose_named_panels_and_text_indices():
    if not prototype.exists():pytest.skip('Optional prototype absent')
    sys.path.insert(0,str(prototype));sys.path.insert(0,str(prototype.parents[1]))
    import original_registry
    from mcp.server.fastmcp import FastMCP
    calls=[]
    def send(operation,*args):
        if operation=='inspect':return {'session_id':'test','revision':1}
        calls.append(args[-1])
        return {'tool_result':'OK','document_changed':False,'metadata_changed':False,'revision':1}
    server=FastMCP('test wrappers')
    original_registry.register_all(server,send)
    tool=server._tool_manager._tools['add_annotation']
    assert 'panel_ref' in tool.parameters['properties']
    assert 'group_path' not in tool.parameters.get('required',[])
    tool.fn(panel_ref='h',text='sample')
    assert calls[-1]['arguments']['panel_ref']=='h'
    assert 'group_path' not in calls[-1]['arguments']
    text=server._tool_manager._tools['style_annotation']
    assert 'text_index' in text.parameters['required']
    assert 'annotation_index' not in text.parameters['properties']
    text.fn(panel_ref='h',text_index=1,bold=True)
    assert calls[-1]['arguments']['annotation_index']==1
    assert 'text_index' not in calls[-1]['arguments']
    with pytest.raises(ValueError,match='Conflicting'):
        text.fn(panel_ref='h',text_index=1,annotation_index=2,bold=True)
    with pytest.raises(ValueError,match='explicit file'):
        tool.fn(pyf_path='some.pyf',panel_ref='h',text='sample')

def test_named_panel_resolution_rejects_guessed_indices(monkeypatch):
    if not prototype.exists():pytest.skip('Optional prototype absent')
    sys.path.insert(0,str(prototype));sys.path.insert(0,str(prototype.parents[1]))
    import gui_selection
    panel=object()
    monkeypatch.setattr(gui_selection,'panels',lambda roots:[((1,),3,panel)])
    monkeypatch.setattr(gui_selection,'letters',lambda p:[SimpleNamespace(getPlainText=lambda:'h')])
    window=SimpleNamespace(paint=SimpleNamespace(EZFIG_panel=SimpleNamespace(shapes_to_draw=[])))
    assert gui_selection.resolve_panel_arguments(window,{'panel_ref':'h'})=={'group_path':[1],'image_index':3}
    with pytest.raises(ValueError,match='PANEL_ADDRESS_CONFLICT'):
        gui_selection.resolve_panel_arguments(window,{'panel_ref':'h','group_path':[1],'image_index':2})

def test_ambiguous_roi_asks_without_broadening():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    state={'panel_references':[{'panel_id':'1/3','letters':['h']}],
           'roi_annotations':[{'panel_id':'1/3','type':'Rectangle2D','annotation_index':i} for i in (1,2)]}
    with pytest.raises(NeedsClarification,match='Which rectangle'):
        adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'set_roi_properties','arguments':{'panel_ref':'h','annotation_index':1,'stroke':3}},state,'Make the box outline 3 pixels wide.')

def test_verified_clause_recovery_is_bounded(tmp_path):
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.engine import Engine
    class Adapter:
        def context(self):return {}
        def context_instructions(self,state):return ''
        def begin(self,*a):pass
        def finish(self,*a):return None
        def finalize_response(self,*a):
            return {'content':'Requested selection is incomplete.','evidence':{'status':'incomplete_selection'}}
    class Model:
        count=0
        async def complete(self,*a,**kw):
            self.count+=1
            return {'role':'assistant','content':'Done.'},{}
    class Hub:
        instructions={}
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def model_tools(self):return []
        def direct_ids(self):return {}
    model=Model()
    engine=Engine(Config(state_dir=str(tmp_path)),adapter=Adapter(),backend=model,hub_factory=lambda *a:Hub())
    events=[]
    asyncio.run(engine.turn('Select h.',lambda *a:events.append(a)))
    assert model.count==2
    assert [v for k,v in events if k=='assistant']==['Requested selection is incomplete.']


def test_substring_oracle_preserves_other_spans():
    path=base/'validation/pyfigures/checks.py'
    spec=importlib.util.spec_from_file_location('advanced_oracle_test',path);checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
    plain={'panel_id':'1/3','index':2,'text':'CO2','runs':[{'start':0,'length':3,'text':'CO2','bold':False,'vertical_alignment':'normal'}]}
    changed={**plain,'runs':[{'start':0,'length':2,'text':'CO','bold':False,'vertical_alignment':'normal'},{'start':2,'length':1,'text':'2','bold':False,'vertical_alignment':'subscript'}]}
    before={'letters':{'panels':[{'panel_id':'1/3','letters':[{'text':'h'}]}]},'annotations':[plain]}
    after={'annotations':[changed]}
    expected={'text_spans':[{'ref':'h','text':'CO2','match':'2','vertical_alignment':'subscript','preserve_outside':True}]}
    assert checks.verify_advanced(expected,before,after)==[]
    changed['runs'][0]['bold']=True
    assert 'Unrequested rich-text formatting changed' in checks.verify_advanced(expected,before,after)


def test_font_choice_article_is_not_a_panel_reference():
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *a:pytest.fail('No selection inspection for a font-choice request')
    assert adapter._verify_requested_selection('Pick a font for all letters.','Done.') is None


def test_note_cannot_be_written_to_a_different_numeric_panel():
    adapter=PyFiguresAdapter('unused')
    state={'panel_references':[{'panel_id':'1/3','letters':['h'],'group_path':[1],'image_index':3}]}
    with pytest.raises(ValueError,match='PANEL_ADDRESS_MISMATCH'):
        adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'add_annotation','arguments':{'group_path':[1],'image_index':2,'text':'sample'}},state,'Write sample on image h, then swap pictures h and j.')
    adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'add_annotation','arguments':{'panel_ref':'h','text':'sample'}},state,'Write sample on image h, then swap pictures h and j.')


def test_preserving_panel_letter_does_not_block_note_formatting():
    adapter=PyFiguresAdapter('unused')
    adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':1,'match':'treated','bold':True}},{},"On h, make only treated bold in the note. Leave CO2 and the panel letter alone.")

def test_editor_readback_request_has_current_session_revision(tmp_path,monkeypatch):
    import io,urllib.request
    descriptor=tmp_path/'connection.json';descriptor.write_text(json.dumps({'url':'http://127.0.0.1:1234','token':'test'}))
    adapter=PyFiguresAdapter(descriptor);seen=[]
    def respond(req,**kwargs):
        body=json.loads(req.data);seen.append(body)
        value={'session_id':'current','revision':7} if body['operation']=='inspect' else {'objects':[]}
        return io.BytesIO(json.dumps({'result':value}).encode())
    monkeypatch.setattr(urllib.request,'urlopen',respond)
    assert adapter.request('inspect_annotation_objects')=={'objects':[]}
    assert seen[-1]['session_id']=='current' and seen[-1]['expected_revision']==7

def test_parent_editor_is_not_inset_property_success():
    adapter=PyFiguresAdapter('unused')
    adapter.request=lambda *a:{'native_dialogs':['Annotate the image'],'annotation_editor_panel_id':'2/2','panel_references':[{'panel_id':'2/2','letters':['k']}]}
    result=adapter.finalize_response('Open the properties of the inset in k.','The editor is open.',{})
    assert result['evidence']['status']=='not_verified'
    adapter.request=lambda *a:{'native_dialogs':['Annotate the image','Edit Inset'],'annotation_editor_panel_id':'2/2','panel_references':[{'panel_id':'2/2','letters':['k']}]}
    assert adapter.finalize_response('Open the properties of the inset in k.','Open.',{}) is None

def test_host_completes_a_skipped_selection_clause():
    adapter=PyFiguresAdapter('unused')
    selected=[]
    def request(operation,arguments=None):
        if operation=='select_live_objects':
            selected.append({'panel_id':'1/3','letters':arguments['panel_refs']})
            return {}
        return {'selection':{'selected_panels':list(selected)}}
    adapter.request=request
    result=adapter.finalize_response('Select h and make only its letter yellow.','Done. The letter is now yellow.',{})
    assert result['evidence']['status']=='selection_completed_by_host'
    assert 'h is now selected' in result['content'] and result['content'].startswith('Done.')

def test_note_text_keeps_the_users_exact_wording():
    adapter=PyFiguresAdapter('unused')
    def call(text):
        return {'tool_name':'add_annotation','arguments':{'panel_ref':'h','text':text}}
    c=call('Sample')
    adapter.validate_tool_call('use_pyfigures_tool',c,{},'Write sample on image h, then swap pictures h and j.')
    assert c['arguments']['text']=='sample'
    c=call('SAMPLE')
    adapter.validate_tool_call('use_pyfigures_tool',c,{},'Write sample in capitals on image h.')
    assert c['arguments']['text']=='SAMPLE'
    c=call('Control')
    adapter.validate_tool_call('use_pyfigures_tool',c,{},'Label h as the control.')
    assert c['arguments']['text']=='Control'
    c=call('Wild type')
    adapter.validate_tool_call('use_pyfigures_tool',c,{},"Put a note reading 'wild type' on h.")
    assert c['arguments']['text']=='wild type'
    c=call('Treated cells')
    adapter.validate_tool_call('use_pyfigures_tool',c,{},'Add a note on h.')
    assert c['arguments']['text']=='Treated cells'

def test_a_word_once_on_its_own_is_not_ambiguous():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    def state(note):
        return {'panel_references':[{'panel_id':'1/3','letters':['h']}],
                'text_annotations':[{'panel_id':'1/3','text_index':0,'text':note}]}
    call={'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':0,'match':'treated','bold':True}}
    adapter.validate_tool_call('use_pyfigures_tool',call,state('treated and untreated'),"On h, make only 'treated' bold.")
    call={'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':0,'match':'control','bold':True}}
    with pytest.raises(NeedsClarification):
        adapter.validate_tool_call('use_pyfigures_tool',call,state('control vs control'),"On h, make only 'control' bold.")
    call={'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':0,'match':'2','vertical_align':'subscript'}}
    with pytest.raises(NeedsClarification):
        adapter.validate_tool_call('use_pyfigures_tool',call,state('CO2 at 2 h'),'Put the 2 in CO2 in subscript.')

def test_every_match_needs_words_that_ask_for_it():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    call={'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':0,'match':'treated','occurrence':'all','bold':True}}
    adapter.validate_tool_call('use_pyfigures_tool',call,{},"On h, make everything containing 'treated' bold.")
    adapter.validate_tool_call('use_pyfigures_tool',call,{},"On h, make all the 'treated' bold.")
    with pytest.raises(NeedsClarification):
        adapter.validate_tool_call('use_pyfigures_tool',call,{},"On h, make only 'treated' bold.")
    with pytest.raises(NeedsClarification):
        adapter.validate_tool_call('use_pyfigures_tool',call,{},"On h, make the first 'treated' bold.")

def test_a_colour_table_must_be_one_the_user_named():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    call={'tool_name':'set_lut','arguments':{'panel_ref':'a','luts':['PURPLE']}}
    with pytest.raises(NeedsClarification,match='PURPLE'):
        adapter.validate_tool_call('use_pyfigures_tool',call,{},'Set panel a to use a blorple LUT.')
    adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'set_lut','arguments':{'panel_ref':'a','luts':['Grays']}},{},'Make panel a grey.')
    adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'set_lut','arguments':{'panel_ref':'a','luts':['Fire']}},{},'Use the fire LUT on a.')

def test_a_panel_named_like_a_greek_letter_must_exist():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    call={'tool_name':'edit_panel_letters','arguments':{'action':'remove','scope':'panels','panel_ids':['3/2']}}
    with pytest.raises(NeedsClarification,match='no panel called omega'):
        adapter.validate_tool_call('use_pyfigures_tool',call,{'panel_references':[{'panel_id':'3/2','letters':['p']}]},'Remove the letter from panel omega.')
    named={'panel_references':[{'panel_id':'3/2','letters':['omega']}]}
    adapter.validate_tool_call('use_pyfigures_tool',{'tool_name':'remove_annotation','arguments':{}},named,'Remove the arrow from panel omega.')

def test_what_if_and_slides_questions_get_the_authored_guide():
    adapter=PyFiguresAdapter('unused')
    seen=[]
    def request(operation,arguments=None):
        seen.append(arguments['topic'])
        guide='export_pptx' if 'slides' in arguments['topic'] else 'add_scale_bars'
        return {'status':'explained','guide':guide,'title':guide,'steps':['Choose a menu.']}
    adapter.request=request
    assert adapter.finalize_manual_response('What if different images have different pixel sizes when I add scale bars?')['evidence']['guide']['guide']=='add_scale_bars'
    assert adapter.finalize_manual_response('How do I export slides with editable text rather than one flattened screenshot?')['evidence']['guide']['guide']=='export_pptx'
    adapter.request=lambda *a:{'status':'explained','guide':'export_pptx','title':'x','steps':['Choose a menu.']}
    assert adapter.finalize_manual_response('How do I export a PDF?') is None

def test_sources_have_no_mangled_utf8():
    # UTF-8 re-read as cp1252 turns "—" into "â€”" in the user-facing status texts.
    bad=[str(p) for p in (base/'src').rglob('*.py') if 'â€' in p.read_text(encoding='utf-8')]
    assert not bad

def test_an_ambiguous_match_is_not_resolved_by_the_model():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    call={'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':0,'match':'treated','occurrence':1,'bold':True}}
    with pytest.raises(NeedsClarification,match='appears more than once'):
        adapter.validate_tool_call('use_pyfigures_tool',call,{},"On h, make only 'treated' bold.")
    adapter.validate_tool_call('use_pyfigures_tool',call,{},"On h, make the first 'treated' bold.")


def test_ambiguous_substring_asks_before_the_first_edit():
    from qtpy_ai_sidecar.errors import NeedsClarification
    adapter=PyFiguresAdapter('unused')
    state={'panel_references':[{'panel_id':'1/3','letters':['h']}], 'text_annotations':[{'panel_id':'1/3','text_index':1,'annotation_index':2,'text':'treated and untreated'}]}
    call={'tool_name':'style_annotation','arguments':{'panel_ref':'h','text_index':1,'match':'treated','bold':True}}
    # User decision: the one whole word "treated" is meant, no question
    adapter.validate_tool_call('use_pyfigures_tool',call,state,"On h, make only 'treated' bold.")
    adapter.validate_tool_call('use_pyfigures_tool',call,state,"On h, make the first 'treated' bold.")
    state['text_annotations'][0]['text']='treated vs treated'
    with pytest.raises(NeedsClarification,match='matches 2 places'):
        adapter.validate_tool_call('use_pyfigures_tool',call,state,"On h, make only 'treated' bold.")
    state['text_annotations'][0]['text']='control and treated'
    adapter.validate_tool_call('use_pyfigures_tool',call,state,"On h, make only 'treated' bold.")
