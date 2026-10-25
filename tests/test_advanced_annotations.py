"""Native rich-text/ROI regressions for the isolated PyFigures adapter."""
import importlib.util
from pathlib import Path
import pytest

prototype=Path(__file__).resolve().parents[2]/'pyfigures_pkg/chatGPT_validation/live_mcp_gui'
if not (prototype/'advanced_annotations.py').exists():
    pytest.skip('Optional PyFigures prototype integration is not installed',allow_module_level=True)
spec=importlib.util.spec_from_file_location('advanced_annotations',prototype/'advanced_annotations.py')
advanced=importlib.util.module_from_spec(spec)
spec.loader.exec_module(advanced)

@pytest.fixture
def text_shape(qt_application_lifetime):
    from qtpy.QtGui import QTextDocument
    class Text:
        is_letter=False
        def __init__(self):
            self.doc=QTextDocument()
            self.doc.setHtml('<span style="color:#ffffff">CO2 and <i>control</i> CO2</span>')
        def setText(self,html):self.doc.setHtml(html)
    return Text()

def char_format(doc,substring):
    return doc.find(substring).charFormat()

def test_ambiguous_substring_cannot_modify_document(text_shape):
    before=text_shape.doc.toHtml()
    with pytest.raises(ValueError,match='CLARIFICATION_REQUIRED'):
        advanced.prepare_text(text_shape,{'bold':True},'CO2')
    assert text_shape.doc.toHtml()==before

def test_range_format_preserves_other_spans_and_foreground(text_shape):
    advanced.prepare_text(text_shape,{'bold':True},'CO2',2)()
    doc=text_shape.doc
    assert char_format(doc,'control').fontItalic()
    assert char_format(doc,'control').foreground().color().name()=='#ffffff'
    first=doc.find('CO2')
    second=doc.find('CO2',first.selectionEnd())
    assert first.charFormat().fontWeight()<second.charFormat().fontWeight()
    assert second.charFormat().foreground().color().name()=='#ffffff'

def test_unicode_utf16_and_subscript(qt_application_lifetime,text_shape):
    from qtpy.QtGui import QTextCharFormat
    text_shape.doc.setPlainText('\U0001f642 CO2')
    advanced.prepare_text(text_shape,{'vertical_alignment':'subscript'},'2')()
    assert text_shape.doc.toPlainText()=='\U0001f642 CO2'
    assert char_format(text_shape.doc,'2').verticalAlignment()==QTextCharFormat.VerticalAlignment.AlignSubScript

def test_replacement_is_literal_and_local(text_shape):
    advanced.prepare_text(text_shape,{'text':'<alpha>'},'control')()
    assert '<alpha>' in text_shape.doc.toPlainText()
    assert text_shape.doc.toPlainText().count('CO2')==2

def test_panel_letters_use_policy_aware_tools(text_shape):
    text_shape.is_letter=True
    with pytest.raises(ValueError,match='panel-letter'):
        advanced.prepare_text(text_shape,{'bold':True})

def test_roi_partial_style_preserves_geometry(qt_application_lifetime):
    from qtpy.QtCore import QRectF
    class Rect2D(QRectF):
        color=0xffffff;fill_color=0x333333;stroke=2;opacity=1
    roi=Rect2D(5,6,30,40)
    advanced.prepare_roi(roi,{'fill_color':'none','stroke':3})()
    assert [roi.x(),roi.y(),roi.width(),roi.height()]==[5,6,30,40]
    assert roi.color==0xffffff and roi.fill_color is None and roi.stroke==3

def test_roi_validation_is_atomic(qt_application_lifetime):
    from qtpy.QtCore import QRectF
    class Rect2D(QRectF):
        color=0xffffff;stroke=2
    roi=Rect2D(5,6,30,40)
    with pytest.raises(ValueError):
        advanced.prepare_roi(roi,{'color':'red','geometry':[0,0,-1,4]})
    assert roi.color==0xffffff and roi.width()==30

def test_roi_token_changes_only_with_semantic_properties(qt_application_lifetime):
    from qtpy.QtCore import QRectF
    class Rect2D(QRectF):
        color=0xffffff;stroke=2
    roi=Rect2D(1,2,3,4)
    token=advanced.describe(roi)['token']
    roi.stroke=3
    assert advanced.describe(roi)['token']!=token


def test_native_font_normalization_is_equivalent(text_shape):
    from qtpy.QtGui import QFont
    other=type(text_shape)()
    text_shape.doc.setDefaultFont(QFont('Sans Serif',9))
    text_shape.doc.setHtml('<span style="color:#ffffff">CO2</span>')
    other.doc.setDefaultFont(QFont('Sans Serif',12))
    other.doc.setHtml('<span style="font-size:9pt;color:#ffffff">CO2</span>')
    assert advanced.draft_matches(text_shape,other)
    advanced.prepare_text(other,{'bold':True})()
    assert not advanced.draft_matches(text_shape,other)
