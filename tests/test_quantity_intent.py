import pytest
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.errors import NeedsClarification

def validate(operation,args,text):
    host=PyFiguresAdapter('unused')
    return host.validate_tool_call('use_pyfigures_tool',{'tool_name':operation,'arguments':args},{'selection':{}},text)

def test_zero_columns_cannot_be_silently_replaced():
    with pytest.raises(NeedsClarification):
        validate('arrange_live_images',{'columns':4},'Put 0 pictures per row.')
    validate('arrange_live_images',{'columns':3},'Put 3 pictures per row.')

def test_absolute_negative_font_cannot_turn_into_a_positive_size():
    with pytest.raises(NeedsClarification):
        validate('edit_panel_letters',{'font_size':9},'Make all letters minus 3 points tall.')
    with pytest.raises(NeedsClarification):
        validate('edit_panel_letters',{'font_size':3},'Make all letters -3 pt tall.')
    validate('edit_panel_letters',{'font_size':15},'Make all letters 3 points bigger.')
    validate('edit_panel_letters',{'font_size':9},'Reduce all letters by 3 points.')

def test_user_accepted_row_overflow_is_not_blocked():
    validate('delete_last_rows',{'count':100},'Delete the last 100 rows.')
    validate('delete_last_rows',{'count':6},'Delete the last 100 rows.')

def test_plural_letter_backgrounds_are_not_a_single_missing_selection():
    validate('edit_panel_letters',{'action':'style','scope':'all','background':'none'},'Take away the letter backgrounds, keeping the white text.')

def test_singular_letter_background_still_needs_a_target():
    with pytest.raises(NeedsClarification):
        validate('edit_panel_letters',{'action':'style','scope':'all','background':'none'},'Remove the letter background.')
