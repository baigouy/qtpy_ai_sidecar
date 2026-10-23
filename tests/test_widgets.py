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
    assert dock.compress.text() == 'Compress'
    assert not dock.choice_buttons
    dock.engine.journal.record('user', 'Test')
    dock.engine.journal.export(tmp_path / 'debug.zip')
    assert (tmp_path / 'debug.zip').is_file()
    dock.grab().save(str(tmp_path / 'widget.png'))
    dock.shutdown()
    dock.close()


def test_completion_summary_is_not_choices():
    assert choices('Done:\n1. Color changed\n2. Layout preserved') == []
