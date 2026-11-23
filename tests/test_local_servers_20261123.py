"""User 2026-11-23: "for the API in fact it can also be local through LM Studio local server".
A model server running on this computer (LM Studio, Ollama) is offered in the Model window and
filled in: no key, nothing sent online. HTTP answers are faked: no real server is asked."""
import pytest

from qtpy_ai_sidecar import discover
from qtpy_ai_sidecar.config import Config

REAL = (('LM Studio', 'http://127.0.0.1:1234/v1', 'http://127.0.0.1:1234/api/v0/models'),
        ('Ollama', 'http://127.0.0.1:11434/v1', 'http://127.0.0.1:11434/api/ps'))


class _Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def _fake_http(monkeypatch, answers):
    import httpx

    def get(url, timeout=None, **kw):
        if url not in answers:
            raise httpx.ConnectError('refused')
        return _Reply(answers[url])
    monkeypatch.setattr(httpx, 'get', get)


@pytest.mark.real_servers
def test_running_servers_are_found_with_the_loaded_model_first(monkeypatch):
    monkeypatch.setattr(discover, 'LOCAL_SERVERS', REAL)
    _fake_http(monkeypatch, {
        'http://127.0.0.1:1234/v1/models': {'data': [{'id': 'gemma-4-12b'}, {'id': 'qwen3.8-27b'},
                                                     {'id': 'text-embedding-nomic'}]},
        'http://127.0.0.1:1234/api/v0/models': {'data': [{'id': 'qwen3.8-27b', 'state': 'loaded', 'type': 'llm'},
                                                         {'id': 'gemma-4-12b', 'state': 'not-loaded', 'type': 'llm'}]}})
    servers = discover.local_servers()
    assert servers == [{'name': 'LM Studio', 'base_url': 'http://127.0.0.1:1234/v1',
                        'models': ['qwen3.8-27b', 'gemma-4-12b'], 'loaded': ['qwen3.8-27b']}]


@pytest.mark.real_servers
def test_ollama_server_and_none_running(monkeypatch):
    monkeypatch.setattr(discover, 'LOCAL_SERVERS', REAL)
    _fake_http(monkeypatch, {'http://127.0.0.1:11434/v1/models': {'data': [{'id': 'qwen3.8:27b'}]},
                             'http://127.0.0.1:11434/api/ps': {'models': []}})
    assert [(s['name'], s['models']) for s in discover.local_servers()] == [('Ollama', ['qwen3.8:27b'])]
    _fake_http(monkeypatch, {})
    assert discover.local_servers() == []


def test_the_model_window_offers_the_server_and_fills_it_in(tmp_path, monkeypatch):
    from qtpy_ai_sidecar.connection import ConnectionDialog
    from qtpy_ai_sidecar.model_choice import ModelChoice, running
    monkeypatch.setattr(discover, 'LOCAL_SERVERS', REAL)
    server = {'name': 'LM Studio', 'base_url': 'http://127.0.0.1:1234/v1',
              'models': ['qwen3.8-27b', 'gemma-4-12b'], 'loaded': ['qwen3.8-27b']}
    config = Config(application='Demo', state_dir=str(tmp_path))
    choice = ModelChoice(config, servers=[server])
    assert len(choice.server_buttons) == 1
    text = choice.server_buttons[0].text()
    assert "LM Studio's server on this computer" in text and 'qwen3.8-27b' in text and 'nothing is sent online' in text
    choice.server_buttons[0].click()
    assert choice.choice is server
    choice.deleteLater()
    dialog = ConnectionDialog(config, server=server)
    assert dialog.provider.currentData() == 'compatible' and dialog.url.text() == 'http://127.0.0.1:1234/v1'
    assert dialog.model.text() == 'qwen3.8-27b'
    candidate = dialog.candidate()                       # no API key asked for a local server
    assert running(candidate) == 'Local server · LM Studio · qwen3.8-27b'
    dialog.deleteLater()


def test_no_server_running_no_extra_choice(tmp_path):
    from qtpy_ai_sidecar.model_choice import ModelChoice
    choice = ModelChoice(Config(application='Demo', state_dir=str(tmp_path)))
    assert choice.server_buttons == []
    choice.deleteLater()
