"""Previews returned by tools go to a vision model (config.vision): a local model
that could not see the figure kept a duplicated panel and a misplaced zoom
through every revision (PyFigures Figure 3 trials, 2026-11-02)."""
import asyncio
import base64
import io
import json
from types import SimpleNamespace

import pytest

from qtpy_ai_sidecar import vision
from qtpy_ai_sidecar.anthropic_backend import convert_messages
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine, size_estimate


def _png(w=2000, h=1500):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (w, h), (200, 30, 120)).save(out, 'PNG')
    return base64.b64encode(out.getvalue()).decode('ascii')


def _run(tmp_path, setting, previews=2):
    """One turn in which the model calls render_preview `previews` times, then answers."""
    class Hub:
        instructions = []

        def __init__(self, *a):
            self.tools = {'id': ('demo', None, SimpleNamespace(name='render_preview',
                                                                annotations=SimpleNamespace(readOnlyHint=False)))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def model_tools(self):
            return []

        def direct_ids(self):
            return {'render_preview': 'id'}

        def is_discovery(self, ident):
            return False

        async def execute(self, ident, arguments, emit):
            return {'is_error': False, 'content': 'Preview rendered.\n' + vision.TEXT_ONLY,
                    'images': [{'data': _png(), 'mime': 'image/png'}]}

    class Model:
        def __init__(self):
            self.sent = []

        async def complete(self, messages, tools, cancel, emit, final_only=False, **kw):
            self.sent.append(messages)
            if len(self.sent) <= previews:
                n = len(self.sent)
                return {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'id': str(n), 'type': 'function',
                     'function': {'name': 'render_preview', 'arguments': '{}'}}]}, {}
            return {'role': 'assistant', 'content': 'Done; the preview shows the change.'}, {}

    model = Model()
    engine = Engine(Config(state_dir=str(tmp_path), vision=setting), backend=model,
                    hub_factory=lambda *a: Hub())
    events = []
    asyncio.run(engine.turn('make the inset larger', lambda *a: events.append(a)))
    return engine, model, events


def _images(messages):
    return [p for m in messages if isinstance(m.get('content'), list)
            for p in m['content'] if p.get('type') == 'image_url']


def test_a_vision_model_sees_the_latest_preview_only(tmp_path):
    engine, model, events = _run(tmp_path, 'on')
    last = model.sent[-1]
    assert len(_images(last)) == 1                       # the latest preview, the earlier one dropped
    assert any('only the latest is kept' in str(m.get('content')) for m in last)
    assert not any('_vision' in m for m in last)         # internal marker never sent
    tool_texts = [m['content'] for m in last if m.get('role') == 'tool']
    assert all(vision.ATTACHED in t and vision.TEXT_ONLY not in t for t in tool_texts)
    assert any(m.get('role') == 'system' and m['content'] == vision.SYSTEM_NOTE for m in last)
    # the image follows the tool results of its reply (protocol pairing kept)
    i = next(k for k, m in enumerate(last) if _images([m]))
    assert last[i - 1]['role'] == 'tool'
    # made smaller: longest side <= MAX_SIDE
    from PIL import Image
    url = _images(last)[0]['image_url']['url']
    img = Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1])))
    assert max(img.size) <= vision.MAX_SIDE
    assert ('image_sent_to_model', {'tool': 'render_preview'}) in events
    assert engine.adapter.vision is True


def test_off_keeps_the_text_only_model_as_before(tmp_path):
    engine, model, events = _run(tmp_path, 'off')
    last = model.sent[-1]
    assert not _images(last)
    assert all(vision.TEXT_ONLY in m['content'] for m in last if m.get('role') == 'tool')
    assert not any(m.get('role') == 'system' and m['content'] == vision.SYSTEM_NOTE for m in last)
    assert ('vision', {'images_sent_to_model': False, 'setting': 'off'}) in events


def test_auto_asks_the_local_server(monkeypatch):
    cfg = Config(state_dir='', vision='auto', model='qwen3.5-9b', provider='compatible')
    monkeypatch.setattr(vision, '_lm_studio_reports_vision', lambda url, model, timeout=1.5: True)
    assert vision.detect(cfg) is True
    monkeypatch.setattr(vision, '_lm_studio_reports_vision', lambda url, model, timeout=1.5: None)
    assert vision.detect(cfg) is False                   # cannot tell: text only
    assert vision.detect(Config(state_dir='', vision='on')) is True
    remote = Config(state_dir='', vision='auto', provider='openai', base_url='https://api.openai.com/v1')
    assert vision.detect(remote) is False                # auto never assumes a remote model sees


def test_bad_setting_is_refused():
    with pytest.raises(ValueError):
        Config(state_dir='', vision='maybe')


def test_an_image_counts_as_a_fixed_size_in_the_context_estimate():
    msg = vision.image_message('render_preview', {'data': _png(), 'mime': 'image/png'})
    assert size_estimate([msg]) < vision.IMAGE_TOKENS + 200
    assert len(json.dumps(msg)) > 3 * (vision.IMAGE_TOKENS + 200)   # its real text is much larger


def test_claude_receives_the_image_as_an_image_block():
    msg = vision.image_message('render_preview', {'data': _png(40, 30), 'mime': 'image/png'})
    msg = {k: v for k, v in msg.items() if k != '_vision'}
    _system, converted = convert_messages([{'role': 'user', 'content': 'hi'}, msg])
    blocks = converted[-1]['content']
    assert any(b['type'] == 'image' and b['source']['media_type'] == 'image/png' for b in blocks)


def test_the_setting_is_saved_with_the_performance_settings(tmp_path):
    cfg = Config(state_dir=str(tmp_path), vision='off')
    cfg.save_performance()
    assert json.loads((tmp_path / 'performance.json').read_text())['vision'] == 'off'
