import time
from qtpy.QtWidgets import QApplication
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
    assert dock.send_button.text() == ''
    assert dock.send_button.accessibleName() == 'Send'
    assert dock.thinking_slider.mapTo(dock.composer_frame, dock.thinking_slider.rect().topLeft()).y() > dock.thinking_mode.mapTo(dock.composer_frame, dock.thinking_mode.rect().topLeft()).y()
    dock.shutdown()
    dock.close()
