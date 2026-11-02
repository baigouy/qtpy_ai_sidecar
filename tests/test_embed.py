from qtpy.QtWidgets import QApplication, QMainWindow
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.adapters.pyfigures import attach_to_window

def test_packaged_sidecar_embeds_in_host(tmp_path):
    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    name = app.applicationName()
    dock = attach_to_window(host, Config(state_dir=str(tmp_path)), tmp_path / 'bridge.json')
    host.show()
    app.processEvents()
    assert dock.parent() is host
    assert not dock.isFloating()
    assert dock.isVisible()
    assert app.applicationName() == name
    dock.shutdown()
    host.close()


def test_the_model_notice_is_always_shown_and_hosts_can_word_it(tmp_path):
    from qtpy_ai_sidecar.config import DEFAULT_NOTICE
    app = QApplication.instance() or QApplication([])
    for given, shown in (('', DEFAULT_NOTICE), ('Check every scale bar.', 'Check every scale bar.')):
        host = QMainWindow()
        dock = attach_to_window(host, Config(state_dir=str(tmp_path), notice=given), tmp_path / 'bridge.json')
        host.show()
        app.processEvents()
        assert dock.notice.isVisible() and dock.notice.text().endswith(shown)
        dock.shutdown()
        host.close()

def test_long_choices_stay_in_message_and_do_not_expand_host(tmp_path):
    from qtpy.QtWidgets import QWidget
    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    host.setCentralWidget(QWidget())
    dock = attach_to_window(host, Config(state_dir=str(tmp_path)), tmp_path / 'bridge.json')
    host.show()
    app.processEvents()
    width = host.width()
    dock.receive('assistant', 'Choose an action?\n- ' + 'Long descriptive choice ' * 20 + '\n- Another option')
    dock.finished()
    for _ in range(5):
        app.processEvents()
    assert host.width() == width
    assert dock.width() <= min(560, host.width() * .4) + 2
    assert host.centralWidget().width() > host.width() * .5
    assert dock.choice_buttons[0].parentWidget() is dock.last_assistant_layout.parentWidget()
    dock.choice_buttons[0].click()
    assert dock.input.toPlainText().startswith('Long descriptive choice')
    host.resize(1100, 800)
    app.processEvents()
    assert dock.maximumWidth() <= 440
    dock.shutdown()
    host.close()


def test_connection_dialog_groq_preset(tmp_path):
    """Choosing Groq fills its endpoint, Qwen3.8-27B and reasoning_effort."""
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.connection import ConnectionDialog
    app = QApplication.instance() or QApplication([])
    dialog = ConnectionDialog(Config(state_dir=str(tmp_path), provider='compatible', model='qwen3.5-9b'))
    dialog.provider.setCurrentIndex(dialog.provider.findData('groq'))
    candidate = dialog.candidate()
    assert candidate.provider == 'groq' and candidate.base_url == 'https://api.groq.com/openai/v1'
    assert candidate.model == 'qwen/qwen3.8-27b' and candidate.thinking_backend == 'reasoning_effort'
    dialog.provider.setCurrentIndex(dialog.provider.findData('openrouter'))   # free, 1M context, reads images
    candidate = dialog.candidate()
    assert candidate.base_url == 'https://openrouter.ai/api/v1' and candidate.model == 'nvidia/nemotron-3.5-super-vl:free'
    dialog.close()
