import time
from qtpy.QtWidgets import QApplication, QComboBox
from qtpy.QtCore import Qt
from qtpy.QtTest import QTest
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.widgets import AssistantDock, choices


def test_widget_keyboard_choices_busy_and_export(tmp_path):
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.resize(630, 850)
    dock.show()
    dock.receive('assistant', 'Which should change?\n- Images\n- Letters')
    dock.finished()
    assert len(dock.choice_buttons) == 2
    dock.choice_buttons[1].click()
    assert dock.input.toPlainText() == 'Letters'
    assert not dock.choice_buttons
    dock.input.clear()
    QTest.keyClicks(dock.input, 'Line one')
    QTest.keyClick(dock.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(dock.input, 'Line two')
    assert dock.input.toPlainText() == 'Line one\nLine two'
    called = []
    async def answer(text, emit, preview=False):
        called.append(text)
        emit('assistant', 'Complete.')
    dock.engine.turn = answer
    QTest.keyClick(dock.input, Qt.Key.Key_Return)
    for _ in range(100):
        app.processEvents()
        if not dock.busy:
            break
        time.sleep(.01)
    assert called == ['Line one\nLine two']
    assert dock.input.isEnabled() and not dock.progress.isVisible()
    assert dock.compress.accessibleName() == 'Compress'
    assert not dock.choice_buttons
    dock.engine.journal.record('user', 'Test')
    dock.engine.journal.export(tmp_path / 'debug.zip')
    assert (tmp_path / 'debug.zip').is_file()
    dock.grab().save(str(tmp_path / 'widget.png'))
    dock.shutdown()
    dock.close()


def test_markdown_in_choices_is_formatted_and_sent_as_plain_text(tmp_path):
    """Models write options as '**Add images** — …': the button shows bold
    text, not asterisks, and choosing it sends the plain words."""
    from qtpy.QtWidgets import QLabel
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.show()
    dock.receive('assistant', 'How do you want to start?\n- **Add images** — give me the paths\n'
                              '- **Lay out a grid first** — placeholder panels')
    dock.finished()
    labels = [b.findChild(QLabel) for b in dock.choice_buttons]
    assert [l.textFormat() for l in labels] == [Qt.TextFormat.MarkdownText] * 2
    assert dock.choice_buttons[0].toolTip() == 'Add images — give me the paths'
    dock.choice_buttons[1].click()
    assert dock.input.toPlainText() == 'Lay out a grid first — placeholder panels'
    dock.shutdown()
    dock.close()


def test_model_picker_in_composer_lists_switches_and_shows_key_state(tmp_path, monkeypatch):
    """The composer's model picker: hidden for local models; says whether the
    API key is stored; lists the provider's models when opened; switching keeps
    the conversation and is saved."""
    from qtpy_ai_sidecar import connection, credentials
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.show()
    assert dock.model_picker.isHidden()                       # local: Model Library chooses
    stored = {}
    monkeypatch.setattr(credentials, 'get_key', lambda config: stored.get(config.provider) or
                        (_ for _ in ()).throw(ValueError('No API key stored')))
    config = Config(application='Demo', state_dir=str(tmp_path), provider='mistral',
                    base_url='https://api.mistral.ai/v1', model='mistral-large-4')
    dock.replace_engine(config)
    picker = dock.model_picker
    assert picker.isVisible() and picker.itemText(0) == 'mistral-large-4' + picker.NO_KEY
    assert 'No API key' in picker.toolTip()
    asked = []
    info = {'mistral-large-4': {'vision': True, 'reasoning': True, 'context': 1048576},
            'zai-glm-latest': {'vision': False, 'reasoning': True, 'context': 131072}}
    monkeypatch.setattr(connection, 'list_models', lambda c: asked.append(c.model) or
                        (['mistral-large-4', 'zai-glm-latest'], info))
    monkeypatch.setattr(QComboBox, 'showPopup', lambda self: None)  # no real popup offscreen
    from qtpy_ai_sidecar.widgets import ModelPicker
    ModelPicker.showPopup(picker)
    assert asked == [] and 'No API key' in dock.status.text()       # nothing asked without a key
    stored['mistral'] = 'test-not-a-real-key'
    dock.replace_engine(config)                                      # the list comes in the background
    assert 'stored' in picker.toolTip()
    for _ in range(200):
        app.processEvents()
        if picker.loaded_for:
            break
        time.sleep(.01)
    assert asked == ['mistral-large-4']
    dock.add_message('user', 'Earlier message')
    before = len(dock.engine.messages)
    ModelPicker.showPopup(picker)
    assert asked == ['mistral-large-4']                              # not asked again
    assert [picker.itemText(i) for i in range(picker.count())] == ['mistral-large-4', 'zai-glm-latest']
    tips = [picker.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(2)]
    assert tips == ['mistral-large-4: reads images, thinks before answering, context window 1,048,576 tokens',
                    'zai-glm-latest: text only, thinks before answering, context window 131,072 tokens']
    assert 'model window 1,048,576' in dock.context.text() and 'smaller' not in dock.context.text()
    assert picker.view().minimumWidth() > picker.view().fontMetrics().horizontalAdvance('mistral-large-4')
    assert picker.view().textElideMode() == Qt.TextElideMode.ElideMiddle      # the name's end stays visible
    assert 'stored' in picker.key_label.toolTip()
    # icons, not fixed 1x pixmaps: drawn at the screen's own scale, so sharp on high-DPI screens
    assert not picker.key_label.icon().isNull()
    from qtpy_ai_sidecar.widgets import badges
    from qtpy.QtCore import QSize
    sharp = badges({'vision': True, 'reasoning': True}).pixmap(QSize(38, 18), 2.0)
    assert (sharp.width(), sharp.height(), sharp.devicePixelRatio()) == (76, 36, 2.0)
    picker.activated.emit(1)
    assert dock.engine.config.model == 'zai-glm-latest' and 'zai-glm-latest' in dock.connection_label.text()
    assert len(dock.engine.messages) == before                     # conversation kept
    dock.engine.config.context_tokens = 200000
    dock.show_context()
    assert 'model window 131,072 — smaller than the setting' in dock.context.text()
    import json
    assert json.loads((tmp_path / 'connection.json').read_text(encoding='utf-8'))['model'] == 'zai-glm-latest'
    dock.shutdown()
    dock.close()


def test_server_usage_is_one_short_phrase_not_raw_json(tmp_path):
    """The provider's token report filled the context line with several lines
    of JSON, which vanished at the next update."""
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.receive('usage', {'prompt_tokens': 8447, 'total_tokens': 8878, 'completion_tokens': 431,
                           'prompt_tokens_details': {'cached_tokens': 0},
                           'completion_tokens_details': {'reasoning_tokens': 409}, 'service_tier': 'standard'})
    text = dock.context.text()
    assert '{' not in text and 'last reply: 8,447 tokens sent, 431 written (409 thinking)' in text
    dock.receive('context', {'estimated_tokens': 9000, 'context_tokens': 32768, 'output_tokens': 8192})
    assert 'Context ≈ 9,000' in dock.context.text() and 'last reply' in dock.context.text()   # kept
    dock.shutdown()
    dock.close()


def test_model_aliases_are_listed_once():
    """Mistral lists each alias as its own model: one entry per model, named
    by the current model, else its -latest alias, else the shortest name."""
    from qtpy_ai_sidecar.connection import one_name_per_model
    models = [{'id': 'mistral-medium-latest', 'aliases': ['mistral-medium', 'mistral-medium-2604']},
              {'id': 'mistral-medium', 'aliases': ['mistral-medium-latest', 'mistral-medium-2604']},
              {'id': 'mistral-large-4', 'aliases': ['mistral-large-4-0']},
              {'id': 'mistral-large-4-0', 'aliases': ['mistral-large-4']},
              {'id': 'zai-glm-5-3', 'aliases': ['zai-glm-5', 'zai-glm-latest']},
              {'id': 'zai-glm-5-3-flash', 'aliases': []}]
    names = [m['id'] for m in one_name_per_model(models)]
    assert names == ['mistral-medium-latest', 'mistral-large-4', 'zai-glm-latest', 'zai-glm-5-3-flash']
    assert [m['id'] for m in one_name_per_model(models, 'zai-glm-5')][2] == 'zai-glm-5'


def test_completion_summary_is_not_choices():
    assert choices('Done:\n1. Color changed\n2. Layout preserved') == []


def test_short_cards_do_not_stretch_and_text_reflows(tmp_path):
    from qtpy.QtWidgets import QFrame
    from qtpy_ai_sidecar.widgets import MessageBrowser
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='PyFigures', state_dir=str(tmp_path)))
    dock.resize(720, 1000)
    dock.show()
    dock.add_message('user', 'Put letters at the center.')
    for _ in range(8):
        app.processEvents()
    cards = [w for w in dock.findChildren(QFrame) if w.property('role') in ('user', 'assistant')]
    assert all(w.height() < 130 for w in cards), [w.height() for w in cards]
    dock.add_message('assistant', 'A longer explanation with wrapped text. ' * 35)
    for _ in range(8):
        app.processEvents()
    browser = dock.findChildren(MessageBrowser)[-1]
    wider = browser.height()
    dock.resize(480, 1000)
    for _ in range(8):
        app.processEvents()
    assert browser.height() >= wider
    dock.shutdown()
    dock.close()


def test_new_messages_follow_delayed_layout_growth(tmp_path):
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QLabel
    app=QApplication.instance() or QApplication([])
    dock=AssistantDock(Config(state_dir=str(tmp_path)))
    dock.resize(620,520)
    dock.show()
    for i in range(20):
        dock.add_message('assistant','Message '+str(i))
    QTest.qWait(50)
    bar=dock.scroll.verticalScrollBar()
    assert bar.maximum()>0 and bar.value()==bar.maximum()
    bar.sliderPressed.emit()
    bar.setValue(0)
    layout=dock.add_message('assistant','New result')
    def expand():
        extra=QLabel('Late preview/control content')
        extra.setFixedHeight(260)
        layout.addWidget(extra)
    QTimer.singleShot(10,expand)
    QTest.qWait(100)
    assert bar.value()==bar.maximum()
    dock.shutdown()
    dock.close()

def test_preview_image_fits_available_width():
    from qtpy.QtGui import QImage
    from qtpy_ai_sidecar.widgets import PreviewImage
    app=QApplication.instance() or QApplication([])
    image=QImage(1200,600,QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    preview=PreviewImage(image)
    preview.resize(180,100)
    preview.show()
    app.processEvents()
    preview.fit_image()
    assert preview.pixmap().width()<=preview.width()
    assert abs(preview.pixmap().width()/preview.pixmap().height()-2)<.05
    preview.close()

    
def test_inline_thinking_and_single_send_stop(tmp_path):
    import asyncio
    app = QApplication.instance() or QApplication([])
    config = Config(state_dir=str(tmp_path), thinking_backend='llama_cpp')
    dock = AssistantDock(config)
    dock.show()
    dock.thinking_mode.setCurrentIndex(dock.thinking_mode.findData('enabled'))
    dock.thinking_slider.setValue(3)
    assert config.thinking == 'enabled' and config.thinking_strength == 'high'
    assert dock.thinking_value.text() == 'High'
    dock.thinking_mode.setCurrentIndex(dock.thinking_mode.findData('disabled'))
    assert not dock.thinking_slider.isEnabled()
    dock.thinking_mode.setCurrentIndex(dock.thinking_mode.findData('enabled'))
    async def wait_for_stop(text, emit, preview=False):
        while not dock.engine.cancel.is_set():
            await asyncio.sleep(.01)
    dock.engine.turn = wait_for_stop
    dock.input.setPlainText('Test')
    dock.send_button.click()
    assert dock.busy and dock.send_button.accessibleName() == 'Stop'
    assert dock.send_button.isEnabled() and not dock.thinking_mode.isEnabled()
    dock.send_button.click()
    assert dock.engine.cancel.is_set()
    for _ in range(100):
        app.processEvents()
        if not dock.busy:
            break
        time.sleep(.01)
    assert not dock.busy and dock.send_button.accessibleName() == 'Send'
    assert dock.send_button.isEnabled() and dock.thinking_mode.isEnabled()
    dock.shutdown()
    dock.close()

    
def test_composer_integrates_editor_thinking_and_send(tmp_path):
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(state_dir=str(tmp_path), thinking_backend='llama_cpp'))
    dock.resize(480, 850)
    dock.show()
    app.processEvents()
    for widget in (dock.input,dock.thinking_mode,dock.thinking_slider,dock.send_button,dock.compress):
        assert dock.composer_frame.isAncestorOf(widget)
    assert dock.thinking_slider.geometry().right() < dock.thinking_value.geometry().left()
    assert dock.thinking_value.width() >= dock.thinking_value.fontMetrics().horizontalAdvance('Default')
    assert dock.send_button.text() == ''
    assert dock.send_button.accessibleName() == 'Send'
    assert dock.thinking_slider.mapTo(dock.composer_frame, dock.thinking_slider.rect().topLeft()).y() > dock.thinking_mode.mapTo(dock.composer_frame, dock.thinking_mode.rect().topLeft()).y()
    dock.shutdown()
    dock.close()
