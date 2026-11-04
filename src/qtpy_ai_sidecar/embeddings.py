"""Optional text embeddings for host applications (litsearch indexes PDFs with
them). Off unless the user chooses a source in the panel's tools menu
(Embeddings…); nothing here is imported by the chat itself, and it needs no
package beyond the sidecar's own.

Two sources, shared by every application using the sidecar (embeddings.json
in the sidecar's user data folder, beside providers.json):
- "mistral": the Mistral AI API (mistral-embed), with the key already in the
  OS vault for the Mistral chat provider. Sends the texts to Mistral.
- "local": any OpenAI-compatible /v1/embeddings server on this computer
  (llama.cpp's llama-server --embedding, Ollama, LM Studio).

An index built with one model can only be searched with that same model:
Embedder.model_id names it, for the host to record beside its vectors.

Optional image descriptions (PyFigures' image search): Embedder.describe()
asks a vision model to describe a picture in words, which are then embedded.
Mistral: mistral-small-latest unless another vision model is set; local: only
when a vision model is named (the server must serve it). Sends the picture.
"""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

SOURCES = ('off', 'mistral', 'local')
MISTRAL_URL = 'https://api.mistral.ai/v1'
DEFAULTS = {'mistral': {'model': 'mistral-embed', 'base_url': MISTRAL_URL,
                        'vision_model': 'mistral-small-latest'},
            'local': {'model': 'nomic-embed-text', 'base_url': 'http://127.0.0.1:8081/v1',
                      'vision_model': ''}}
BATCH_TEXTS = 64          # texts per request
BATCH_CHARS = 40000       # ~10k tokens: under Mistral's per-request token limit
RETRIES = 4


class EmbeddingsUnavailable(RuntimeError):
    """Embeddings are off, misconfigured, or the source cannot be reached."""


def path():
    from platformdirs import user_data_path
    return user_data_path('qtpy-ai-sidecar', appauthor=False) / 'embeddings.json'


def load():
    """{'source', 'model', 'base_url', 'vision_model'}; source 'off' when never
    configured. vision_model '' = the source's default (none for local)."""
    try:
        value = json.loads(Path(path()).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        value = {}
    if not isinstance(value, dict) or value.get('source') not in SOURCES:
        return {'source': 'off', 'model': '', 'base_url': '', 'vision_model': ''}
    return {'source': value['source'], 'model': str(value.get('model') or ''),
            'base_url': str(value.get('base_url') or ''),
            'vision_model': str(value.get('vision_model') or '')}


def validate(settings):
    source = settings.get('source')
    if source not in SOURCES:
        raise ValueError('Unknown embeddings source')
    if source == 'off':
        return
    if not str(settings.get('model') or '').strip():
        raise ValueError('Give the embedding model name (e.g. ' + DEFAULTS[source]['model'] + ')')
    url = str(settings.get('base_url') or '')
    if source == 'mistral' and url.rstrip('/') != MISTRAL_URL:
        raise ValueError('The Mistral source uses ' + MISTRAL_URL)
    if source == 'local' and urlsplit(url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('A local embeddings server must be on this computer (127.0.0.1 or localhost)')
    from .credentials import validate_endpoint
    validate_endpoint(url)


def save(settings):
    settings = {'source': settings.get('source', 'off'), 'model': str(settings.get('model') or '').strip(),
                'base_url': str(settings.get('base_url') or '').strip().rstrip('/'),
                'vision_model': str(settings.get('vision_model') or '').strip()}
    validate(settings)
    target = Path(path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    return settings


def configured():
    """The Embedder the user chose, or None when embeddings are off."""
    settings = load()
    return None if settings['source'] == 'off' else Embedder(settings)


class Embedder:
    """embed(texts) -> one vector per text, in order. Synchronous: hosts call
    it from their own worker threads."""

    def __init__(self, settings, timeout=60):
        validate(settings)
        self.source = settings['source']
        self.model = settings['model'].strip()
        self.base_url = settings['base_url'].rstrip('/')
        self.vision_model = (str(settings.get('vision_model') or '').strip()
                             or DEFAULTS[self.source]['vision_model'])
        self.timeout = timeout

    @property
    def model_id(self):
        """What a host records beside its vectors, e.g. 'mistral/mistral-embed'."""
        return self.source + '/' + self.model

    @property
    def vision_id(self):
        """The model describe() uses, e.g. 'mistral/mistral-small-latest'; '' when none."""
        return self.source + '/' + self.vision_model if self.vision_model else ''

    def _headers(self):
        headers = {'Content-Type': 'application/json'}
        if self.source == 'mistral':
            from .credentials import get_key
            try:
                key = get_key(SimpleNamespace(provider='mistral', base_url=MISTRAL_URL, api_key_env=''))
            except (ValueError, RuntimeError) as exc:
                raise EmbeddingsUnavailable('No Mistral API key in the OS vault: add it with the plug icon '
                                            '(provider Mistral AI API). ' + str(exc)) from None
            headers['Authorization'] = 'Bearer ' + key
        return headers

    @staticmethod
    def batches(texts):
        batch, size = [], 0
        for text in texts:
            if batch and (len(batch) >= BATCH_TEXTS or size + len(text) > BATCH_CHARS):
                yield batch
                batch, size = [], 0
            batch.append(text)
            size += len(text)
        if batch:
            yield batch

    def embed(self, texts, model=None):
        """model is ignored (hosts pass their own default): the model is the
        one chosen in Embeddings…, so the vectors always match model_id."""
        import httpx
        texts = [t if t.strip() else ' ' for t in texts]   # some servers refuse empty input
        headers, out = self._headers(), []
        with httpx.Client(timeout=self.timeout) as client:
            for batch in self.batches(texts):
                out.extend(self._post(client, headers, batch))
        return out

    def _post(self, client, headers, batch):
        url = self.base_url + '/embeddings'
        data = sorted(self._request(client, url, headers, {'model': self.model, 'input': batch}).get('data', []),
                      key=lambda d: d.get('index', 0))
        if len(data) != len(batch):
            raise EmbeddingsUnavailable(f'{url} returned {len(data)} vectors for {len(batch)} texts')
        return [d['embedding'] for d in data]

    @staticmethod
    def _request(client, url, headers, payload):
        """POST with retries on busy (429) and server errors; the JSON reply."""
        import httpx
        from .backend import rate_limit_wait, SERVER_ERRORS
        for attempt in range(RETRIES + 1):
            try:
                reply = client.post(url, headers=headers, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt >= RETRIES:
                    raise EmbeddingsUnavailable(f'Cannot reach {url}: {exc}') from None
                time.sleep(min(30.0, 2.0 * 2 ** attempt))
                continue
            if reply.status_code == 429 or reply.status_code in SERVER_ERRORS:
                if attempt >= RETRIES:
                    raise EmbeddingsUnavailable(f'{url} answered HTTP {reply.status_code}: {reply.text[:300]}')
                time.sleep(rate_limit_wait(reply.headers, attempt))
                continue
            if reply.status_code != 200:
                raise EmbeddingsUnavailable(f'{url} answered HTTP {reply.status_code}: {reply.text[:300]}')
            return reply.json()
        raise EmbeddingsUnavailable(f'{url}: no answer')   # pragma: no cover

    def describe(self, image, prompt, mime='image/jpeg', max_tokens=300):
        """The vision model's text answer to *prompt* about *image* (encoded
        bytes, e.g. a JPEG thumbnail). Sends the picture to the source."""
        import base64
        import httpx
        if not self.vision_model:
            raise EmbeddingsUnavailable('No vision model for image descriptions: name one in Embeddings… '
                                        '(the local server must serve it)')
        url = self.base_url + '/chat/completions'
        payload = {'model': self.vision_model, 'max_tokens': max_tokens, 'temperature': 0,
                   'messages': [{'role': 'user', 'content': [
                       {'type': 'text', 'text': prompt},
                       {'type': 'image_url', 'image_url': {
                           'url': 'data:' + mime + ';base64,' + base64.b64encode(image).decode()}}]}]}
        with httpx.Client(timeout=self.timeout) as client:
            reply = self._request(client, url, self._headers(), payload)
        try:
            content = reply['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            raise EmbeddingsUnavailable(f'{url} returned no description') from None
        if isinstance(content, list):      # content chunks
            content = ' '.join(c.get('text', '') for c in content if isinstance(c, dict))
        return str(content or '').strip()
