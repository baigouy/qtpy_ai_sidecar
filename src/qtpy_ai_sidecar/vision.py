"""Images returned by tools (a figure preview) sent to a vision model.

Without them a local model built figures it could not see: a duplicated panel
and a magnified region beside its target went unnoticed through every
revision, while a model that looked at each preview caught its own mistakes
(PyFigures Figure 3 trials, 2026-11-02). Only the latest image is sent, made
smaller, so the context stays bounded.
"""
import base64
import io
import json
import urllib.request
from urllib.parse import urlsplit

MAX_SIDE = 1024          # px: longest side of an image sent to the model
IMAGE_TOKENS = 1200      # context estimate per image (servers count them differently)
SYSTEM_NOTE = ('[VISION] Images returned by tools are attached for you to inspect. Look at the '
               'latest one before saying a visual request is done: check the layout, the panels, '
               'what a magnified region shows, colours and labels; fix what does not match.')
ATTACHED = '[Image attached in the next message for you to inspect.]'
TEXT_ONLY = '[Image shown to the human. This text-only model cannot inspect its pixels.]'
# cloud models known to take images ('auto' sends previews to these; their
# model lists do not say): Groq console.groq.com/docs/vision; NVIDIA NIM's VL model
KNOWN_VISION_MODELS = {'groq': ('qwen/qwen3.8-27b',),
                       'nvidia': ('nvidia/nemotron-3.5-super-vl-120b-a12b',)}


def _lm_studio_reports_vision(base_url, model, timeout=1.5):
    """LM Studio's REST API says type 'vlm' for a vision model; None when it
    cannot tell (another server, or the model is not listed)."""
    root = base_url.rsplit('/v1', 1)[0]
    try:
        with urllib.request.urlopen(root + '/api/v0/models', timeout=timeout) as r:
            models = json.loads(r.read().decode('utf-8')).get('data', [])
    except Exception:
        return None
    for m in models:
        if m.get('id') == model:
            return m.get('type') == 'vlm'
    return None


def detect(config):
    """Whether images go to the model: config.vision 'on' / 'off', or 'auto'
    (a local server that reports a vision model; the owned llama-server
    runtime is started without a multimodal projector, so not that one)."""
    mode = getattr(config, 'vision', 'auto')
    if mode != 'auto':
        return mode == 'on'
    if getattr(config, 'runtime', None):
        return False
    if urlsplit(config.base_url).hostname in ('127.0.0.1', 'localhost', '::1'):
        return bool(_lm_studio_reports_vision(config.base_url, config.model))
    if getattr(config, 'provider', '') in KNOWN_VISION_MODELS:
        return config.model in KNOWN_VISION_MODELS[config.provider]
    if getattr(config, 'provider', '') == 'openrouter':
        return bool(_openrouter_reports_vision(config.base_url, config.model))
    return False


def _openrouter_reports_vision(base_url, model, timeout=5):
    """OpenRouter's public model list gives each model's input modalities;
    None when it cannot tell (no network, or the model is not listed). httpx,
    as for the model calls: urllib's HTTPS failed here (SSL ASN1 error, conda
    Python, 2026-11-02), so previews never went to an OpenRouter model."""
    import httpx
    try:
        models = httpx.get(base_url.rstrip('/') + '/models', timeout=timeout).json().get('data', [])
    except Exception:
        return None
    for m in models:
        if m.get('id') == model:
            return 'image' in (m.get('architecture') or {}).get('input_modalities', [])
    return None


def shrink(data, mime):
    """(base64, mime) of the image with its longest side at most MAX_SIDE px,
    as JPEG unless it has transparency; the original when it cannot be read."""
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(base64.b64decode(data)))
        image.load()
    except Exception:
        return data, mime
    if max(image.size) <= MAX_SIDE and mime in ('image/png', 'image/jpeg'):
        return data, mime
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    if image.mode in ('RGBA', 'LA', 'P'):
        image.save(out, 'PNG', optimize=True)
        mime = 'image/png'
    else:
        image.convert('RGB').save(out, 'JPEG', quality=85)
        mime = 'image/jpeg'
    return base64.b64encode(out.getvalue()).decode('ascii'), mime


def image_message(tool, image):
    """The user-role message carrying the latest tool image (OpenAI format;
    the Anthropic backend converts it)."""
    data, mime = shrink(image['data'], image.get('mime') or 'image/png')
    return {'role': 'user', '_vision': True, 'content': [
        {'type': 'text', 'text': f'Image returned by {tool} (the current state):'},
        {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{data}'}}]}


def for_estimate(messages):
    """The messages with image data replaced by a placeholder of about
    IMAGE_TOKENS tokens, for the context estimate."""
    out = []
    for m in messages:
        if isinstance(m.get('content'), list):
            parts = []
            for part in m['content']:
                if part.get('type') == 'image_url':
                    parts.append({'type': 'image', 'estimate': 'x' * (IMAGE_TOKENS * 3)})
                else:
                    parts.append(part)
            m = dict(m, content=parts)
        out.append(m)
    return out
