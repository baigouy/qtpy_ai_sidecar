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
    assert candidate.base_url == 'https://openrouter.ai/api/v1' and candidate.model == 'openrouter/free'
    for provider, url, model in (('iteracompute', 'https://api.iteracompute.com/v1', 'qwen/qwen3.8-27b'),
                                 ('nvidia', 'https://integrate.api.nvidia.com/v1', 'nvidia/nemotron-3.5-super-vl-120b-a12b'),
                                 ('mistral', 'https://api.mistral.ai/v1', 'mistral-large-4')):
        dialog.provider.setCurrentIndex(dialog.provider.findData(provider))
        candidate = dialog.candidate()
        assert (candidate.provider, candidate.base_url, candidate.model) == (provider, url, model)
        assert candidate.thinking_backend == ('unsupported' if provider == 'nvidia' else 'reasoning_effort')
    dialog.close()


def test_a_key_for_another_provider_is_not_saved(tmp_path, monkeypatch):
    """A Mistral key pasted while OpenRouter is still selected must not replace
    the stored OpenRouter key."""
    from qtpy_ai_sidecar import connection
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.connection import ConnectionDialog
    app = QApplication.instance() or QApplication([])
    stored = []
    monkeypatch.setattr(connection, 'set_key', lambda config, key: stored.append((config.provider, key)))
    dialog = ConnectionDialog(Config(state_dir=str(tmp_path), provider='openrouter',
                                     base_url='https://openrouter.ai/api/v1', model='openrouter/free'))
    dialog.key.setText('test-not-a-real-mistral-key')
    dialog.save()
    assert stored == [] and dialog.result_config is None and 'not a key for OpenRouter' in dialog.error.text()
    assert not (tmp_path / 'connection.json').exists()
    dialog.provider.setCurrentIndex(dialog.provider.findData('mistral'))     # no prefix to check
    dialog.key.setText('test-not-a-real-mistral-key')
    dialog.save()
    assert stored == [('mistral', 'test-not-a-real-mistral-key')] and dialog.result_config.provider == 'mistral'
    dialog.close()


def test_mistral_model_list_keeps_tool_chat_models_and_marks_vision(tmp_path, monkeypatch):
    """Mistral's list (capabilities per model, Z.ai GLM included): embedding/OCR/
    speech models dropped, models that read images marked, the mark not kept."""
    import httpx
    from qtpy.QtWidgets import QInputDialog
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.connection import ConnectionDialog, READS_IMAGES
    app = QApplication.instance() or QApplication([])
    chat = {'completion_chat': True, 'function_calling': True}

    class Reply:
        status_code = 200
        text = ''
        def json(self):
            return {'data': [{'id': 'mistral-large-4', 'capabilities': dict(chat, vision=True)},
                             {'id': 'zai-glm-latest', 'capabilities': dict(chat, vision=False)},
                             {'id': 'mistral-embed', 'capabilities': {'completion_chat': False}},
                             {'id': 'voxtral-mini-latest', 'capabilities': {'completion_chat': True}}]}
    monkeypatch.setattr(httpx, 'get', lambda url, timeout=0, headers=None: Reply())
    shown = []

    def get_item(parent, title, label, items, current, editable):
        shown.extend(items)
        return items[0], True
    monkeypatch.setattr(QInputDialog, 'getItem', staticmethod(get_item))
    dialog = ConnectionDialog(Config(state_dir=str(tmp_path), provider='compatible', model='x'))
    dialog.provider.setCurrentIndex(dialog.provider.findData('mistral'))
    dialog.key.setText('test-not-a-real-key')
    dialog.choose_model()
    assert shown == ['mistral-large-4' + READS_IMAGES, 'zai-glm-latest']
    assert dialog.model.text() == 'mistral-large-4'
    dialog.close()


def test_list_models_asks_the_provider_with_the_key(tmp_path, monkeypatch):
    """'List models…' shows what the key can use, free ones first."""
    import httpx
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.connection import ConnectionDialog
    app = QApplication.instance() or QApplication([])
    seen = {}

    class Reply:
        status_code = 200
        text = ''
        def json(self):
            return {'data': [{'id': 'b/paid'}, {'id': 'qwen/qwen3.8-27b', 'is_free': True}, {'id': 'a/paid'}]}

    def get(url, timeout=0, headers=None):
        seen.update(url=url, headers=headers)
        return Reply()
    monkeypatch.setattr(httpx, 'get', get)
    dialog = ConnectionDialog(Config(state_dir=str(tmp_path), provider='compatible', model='x'))
    dialog.provider.setCurrentIndex(dialog.provider.findData('iteracompute'))
    dialog.key.setText('test-not-a-real-key')
    assert dialog.available_models() == ['qwen/qwen3.8-27b', 'a/paid', 'b/paid']
    assert seen['url'] == 'https://api.iteracompute.com/v1/models'
    assert seen['headers'] == {'Authorization': 'Bearer test-not-a-real-key'}
    dialog.close()
