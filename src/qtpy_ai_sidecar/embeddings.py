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
"""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

SOURCES = ('off', 'mistral', 'local')
MISTRAL_URL = 'https://api.mistral.ai/v1'
DEFAULTS = {'mistral': {'model': 'mistral-embed', 'base_url': MISTRAL_URL},
            'local': {'model': 'nomic-embed-text', 'base_url': 'http://127.0.0.1:8081/v1'}}
BATCH_TEXTS = 64          # texts per request
BATCH_CHARS = 40000       # ~10k tokens: under Mistral's per-request token limit
RETRIES = 4


class EmbeddingsUnavailable(RuntimeError):
    """Embeddings are off, misconfigured, or the source cannot be reached."""


def path():
    from platformdirs import user_data_path
    return user_data_path('qtpy-ai-sidecar', appauthor=False) / 'embeddings.json'


def load():
    """{'source', 'model', 'base_url'}; source 'off' when never configured."""
    try:
        value = json.loads(Path(path()).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        value = {}
    if not isinstance(value, dict) or value.get('source') not in SOURCES:
        return {'source': 'off', 'model': '', 'base_url': ''}
    return {'source': value['source'], 'model': str(value.get('model') or ''),
            'base_url': str(value.get('base_url') or '')}


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
                'base_url': str(settings.get('base_url') or '').strip().rstrip('/')}
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
        self.timeout = timeout

    @property
    def model_id(self):
        """What a host records beside its vectors, e.g. 'mistral/mistral-embed'."""
        return self.source + '/' + self.model

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
        import httpx
        from .backend import rate_limit_wait, SERVER_ERRORS
        url = self.base_url + '/embeddings'
        for attempt in range(RETRIES + 1):
            try:
                reply = client.post(url, headers=headers, json={'model': self.model, 'input': batch})
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
            data = sorted(reply.json().get('data', []), key=lambda d: d.get('index', 0))
            if len(data) != len(batch):
                raise EmbeddingsUnavailable(f'{url} returned {len(data)} vectors for {len(batch)} texts')
            return [d['embedding'] for d in data]
