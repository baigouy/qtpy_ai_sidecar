from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def host_for(guide):
    host=PyFiguresAdapter('unused')
    host.request=lambda op,args: guide if op=='manual_guide' else (_ for _ in ()).throw(AssertionError(op))
    return host

def test_manual_response_uses_authored_steps_not_api_prose():
    host=host_for({'status':'explained','guide':'panel_letters','steps':['Choose Annotations > Panel letters.','Set Size, then Ok.']})
    result=host.finalize_response('Explain how to make letters bigger, do not edit.','Use edit_panel_letters(font_size=18).',{})
    assert 'Choose Annotations' in result['content']
    assert 'edit_panel_letters' not in result['content']
    assert result['evidence']['operation_executed'] is False

def test_explicit_code_and_recipe_remain_available():
    host=host_for({'status':'explained','steps':['GUI step']})
    for request in ('Show me Python code to rotate a panel','How do I do this with a recipe?'):
        assert host.finalize_response(request,'code',{}) is None
    assert host.finalize_response('How do I rotate without using Python?','code',{}) is not None

def test_unknown_help_is_not_certified_and_export_topics_not_substituted():
    assert host_for({'status':'ambiguous','candidates':['a','b']}).finalize_response('How do I do this?','?',{}) is None
    host=host_for({'status':'explained','guide':'export_pptx','steps':['Export PowerPoint.']})
    assert host.finalize_response('How do I export a PDF?','PDF steps',{}) is None

def test_manual_is_not_permission_to_execute_or_override_ordinary_edit_reply():
    host=host_for({'status':'explained','steps':['GUI step']})
    assert host.finalize_response('Make the letters yellow','Done',{}) is None
