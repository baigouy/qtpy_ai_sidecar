"""Every chat bubble has a tiny copy icon, and copying shows it happened (user 2026-11-24:
"it's not obvious that the text is copied as nothing changes when I press the button")."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import time

from qtpy.QtWidgets import QApplication, QPushButton, QToolButton

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.widgets import AssistantDock, FLASH_STYLE, MessageBrowser, copy_with_feedback


def _wait(ms):
    app = QApplication.instance()
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def _dock(tmp_path):
    QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.show()
    return dock


def test_each_bubble_copies_its_text_and_blinks(tmp_path):
    dock = _dock(tmp_path)
    try:
        layout = dock.add_message('assistant', 'Set the width to **20 cm**: done.')
        browser = layout.itemAt(1).widget()
        assert isinstance(browser, MessageBrowser)            # still the second item
        copy = layout.parentWidget().copy_button
        assert isinstance(copy, QToolButton) and copy.toolTip() == 'Copy this message'
        QApplication.clipboard().setText('')
        copy.click()
        _wait(60)
        assert QApplication.clipboard().text() == browser.toPlainText()
        assert '20 cm' in QApplication.clipboard().text()
        assert FLASH_STYLE in browser.styleSheet()             # blinking
        assert copy.toolTip() == 'Copied to the clipboard'
        _wait(1700)
        assert FLASH_STYLE not in browser.styleSheet()
        assert copy.toolTip() == 'Copy this message'
        user = dock.add_message('user', 'make it 20 cm wide')
        assert user.parentWidget().copy_button is not None
    finally:
        # closed, not deleted: its model-list thread still reports to it (as test_widgets' docks)
        dock.close()


def test_another_ai_app_message_offers_to_close_the_chat(tmp_path):
    """User 2026-11-24: once another app is connected, the chat panel is of no use."""
    dock = _dock(tmp_path)
    try:
        dock.outside_app_ready()
        text = dock.findChildren(MessageBrowser)[-1].toPlainText()
        assert 'You can close this chat panel now' in text
        assert dock.isVisible()
        dock.outside_close_button.click()
        assert not dock.isVisible()
    finally:
        dock.close()


def test_a_deleted_message_is_not_blinked(tmp_path):
    """The delayed blink after Another AI app ran on a deleted message: an error in a Qt slot,
    which aborts a PyQt6 application."""
    import pytest
    sip = pytest.importorskip('PyQt6.sip')
    from qtpy.QtWidgets import QLabel
    QApplication.instance() or QApplication([])
    label, button = QLabel('x'), QPushButton('Copy')
    sip.delete(label)
    sip.delete(button)
    assert copy_with_feedback('hello', button=button, flash=label)     # no error
    _wait(600)
    assert QApplication.clipboard().text() == 'hello'


def test_text_buttons_say_copied_then_come_back(tmp_path):
    QApplication.instance() or QApplication([])
    button = QPushButton('Copy the prompt')
    try:
        assert copy_with_feedback('hello', button=button)
        assert button.text() == '✓ Copied' and QApplication.clipboard().text() == 'hello'
        copy_with_feedback('hello', button=button)             # twice: still comes back
        _wait(1700)
        assert button.text() == 'Copy the prompt'
    finally:
        button.deleteLater()
