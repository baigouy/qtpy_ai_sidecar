"""Optional embeddings: settings, the local source against a stand-in
/v1/embeddings server, the Mistral key from the vault, and the dialog."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qtpy_ai_sidecar import embeddings as E


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(E, 'path', lambda: tmp_path / 'embeddings.json')


@pytest.fixture
def server():
    """Answers like llama-server --embedding; the first request of each test
    can be made to fail with HTTP 429 to check the retry."""
    state = {'calls': [], 'fail_first': False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['calls'].append(body)
            if state['fail_first'] and len(state['calls']) == 1:
                self.send_response(429)
                self.send_header('Retry-After', '0.5')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if self.path.endswith('/chat/completions'):     # a vision model describing the picture
                parts = body['messages'][0]['content']
                image = next(p['image_url']['url'] for p in parts if p['type'] == 'image_url')
                text = f"{body['model']} saw {image.split(';')[0]} after: {parts[0]['text']}"
                reply = json.dumps({'choices': [{'message': {'content': text}}]}).encode()
            else:
                data = [{'index': i, 'embedding': [float(len(t)), float(i)]} for i, t in enumerate(body['input'])]
                reply = json.dumps({'data': data[::-1]}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}/v1', state
    httpd.shutdown()
    httpd.server_close()


def test_off_until_chosen():
    assert E.load()['source'] == 'off' and E.configured() is None


def test_settings_are_validated_before_saving():
    with pytest.raises(ValueError, match='on this computer'):
        E.save({'source': 'local', 'model': 'm', 'base_url': 'http://example.org/v1'})
    with pytest.raises(ValueError, match='uses https://api.mistral.ai/v1'):
        E.save({'source': 'mistral', 'model': 'mistral-embed', 'base_url': 'https://evil.example/v1'})
    with pytest.raises(ValueError, match='model name'):
        E.save({'source': 'mistral', 'model': ' ', 'base_url': E.MISTRAL_URL})
    E.save({'source': 'mistral', 'model': 'mistral-embed', 'base_url': E.MISTRAL_URL + '/'})
    assert E.configured().model_id == 'mistral/mistral-embed'
    assert 'key' not in json.dumps(E.load()).lower()      # no credential in the settings file


def test_local_source_keeps_order_batches_and_retries(server, monkeypatch):
    url, state = server
    monkeypatch.setattr(E.time, 'sleep', lambda s: None)
    monkeypatch.setattr(E, 'BATCH_TEXTS', 2)
    state['fail_first'] = True
    E.save({'source': 'local', 'model': 'nomic-embed-text', 'base_url': url})
    vectors = E.configured().embed(['a', 'bb', 'ccc', ''])
    assert vectors == [[1.0, 0.0], [2.0, 1.0], [3.0, 0.0], [1.0, 1.0]]   # '' sent as ' '
    assert [c['input'] for c in state['calls']] == [['a', 'bb'], ['a', 'bb'], ['ccc', ' ']]
    assert {c['model'] for c in state['calls']} == {'nomic-embed-text'}


def test_batches_respect_the_character_budget(monkeypatch):
    monkeypatch.setattr(E, 'BATCH_CHARS', 10)
    assert list(E.Embedder.batches(['x' * 6, 'y' * 6, 'z'])) == [['x' * 6], ['y' * 6, 'z']]


def test_unreachable_local_server_is_explained(monkeypatch):
    monkeypatch.setattr(E.time, 'sleep', lambda s: None)
    embedder = E.Embedder({'source': 'local', 'model': 'm', 'base_url': 'http://127.0.0.1:9/v1'}, timeout=2)
    with pytest.raises(E.EmbeddingsUnavailable, match='Cannot reach'):
        embedder.embed(['x'])


def test_mistral_uses_the_vault_key_of_the_chat_provider(monkeypatch):
    from qtpy_ai_sidecar import credentials
    asked = []
    monkeypatch.setattr(credentials, 'get_key', lambda c: asked.append((c.provider, c.base_url)) or 'k-123')
    embedder = E.Embedder({'source': 'mistral', 'model': 'mistral-embed', 'base_url': E.MISTRAL_URL})
    assert embedder._headers()['Authorization'] == 'Bearer k-123'
    assert asked == [('mistral', E.MISTRAL_URL)]     # the same vault entry as Mistral chat

    def missing(c):
        raise ValueError('No API key stored for this provider endpoint.')
    monkeypatch.setattr(credentials, 'get_key', missing)
    with pytest.raises(E.EmbeddingsUnavailable, match='plug icon'):
        embedder._headers()


def test_dialog_saves_and_tests(server):
    from qtpy.QtWidgets import QApplication
    from qtpy_ai_sidecar.embeddings_dialog import EmbeddingsDialog
    QApplication.instance() or QApplication([])
    url, _ = server
    dialog = EmbeddingsDialog()
    assert dialog.source.currentData() == 'off' and not dialog.model.isEnabled()
    dialog.source.setCurrentIndex(dialog.source.findData('local'))
    assert dialog.model.text() == 'nomic-embed-text' and dialog.url.isEnabled()
    dialog.url.setText(url)
    dialog.test()
    assert dialog.result.text() == 'Works: 2 numbers per text.'
    dialog.accept()
    assert E.load() == {'source': 'local', 'model': 'nomic-embed-text', 'base_url': url, 'vision_model': ''}
    dialog.source.setCurrentIndex(dialog.source.findData('mistral'))
    assert dialog.vision.text() == 'mistral-small-latest'
    dialog.source.setCurrentIndex(dialog.source.findData('local'))
    dialog.url.setText(url)
    dialog.source.setCurrentIndex(dialog.source.findData('mistral'))
    assert 'Sends the texts' in dialog.note.text() and not dialog.url.isEnabled()
    assert EmbeddingsDialog().url.text() == url      # reopened: the saved settings


def test_image_descriptions(server, monkeypatch):
    url, state = server
    local = E.Embedder({'source': 'local', 'model': 'm', 'base_url': url})
    assert local.vision_id == ''                       # local: only with a named vision model
    with pytest.raises(E.EmbeddingsUnavailable, match='vision model'):
        local.describe(b'jpeg', 'Describe it.')
    assert state['calls'] == []
    state['fail_first'] = True
    vision = E.Embedder({'source': 'local', 'model': 'm', 'base_url': url, 'vision_model': 'pixtral'})
    monkeypatch.setattr(E.time, 'sleep', lambda s: None)
    assert vision.vision_id == 'local/pixtral'
    assert vision.describe(b'jpeg', 'Describe it.') == 'pixtral saw data:image/jpeg after: Describe it.'
    assert len(state['calls']) == 2                   # the busy answer was retried


def test_mistral_describes_with_a_small_vision_model_by_default():
    settings = {'source': 'mistral', 'model': 'mistral-embed', 'base_url': E.MISTRAL_URL}
    assert E.Embedder(settings).vision_id == 'mistral/mistral-small-latest'
    assert E.Embedder({**settings, 'vision_model': 'pixtral-large-latest'}).vision_id == 'mistral/pixtral-large-latest'
    E.save({**settings, 'vision_model': ' pixtral-large-latest '})
    assert E.load()['vision_model'] == 'pixtral-large-latest'
