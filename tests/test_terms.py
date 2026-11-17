"""The user accepts responsibility once before the first message (2026-11-17).

User: "the user is responsible of what he says and will be sending even if he is
not doing it directly".
"""
import json

import pytest
from qtpy.QtWidgets import QApplication
from qtpy_ai_sidecar import terms
from qtpy_ai_sidecar.config import Config

pytestmark = pytest.mark.real_terms


def _ask(monkeypatch, answer):
    asked = []
    monkeypatch.setattr(terms, 'ask_user', lambda parent, title, html: asked.append(html) or answer[0])
    return asked


def test_declined_nothing_is_sent_and_the_text_stays(tmp_path, monkeypatch):
    from qtpy_ai_sidecar.widgets import AssistantDock
    QApplication.instance() or QApplication([])
    answer = [False]
    asked = _ask(monkeypatch, answer)
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    called = []

    async def turn(text, emit, preview=False):
        called.append(text)
    dock.engine.turn = turn
    dock.input.setPlainText('Make the letters bold')
    dock.send()
    assert not called and not dock.busy and dock.input.toPlainText() == 'Make the letters bold'
    assert 'not accepted' in dock.status.text()
    text = asked[0]
    assert 'You are responsible for what you ask' in text and 'without you typing it yourself' in text
    assert 'no liability' in text
    assert not (tmp_path / terms.FILE).exists()
    dock.close()


def test_accepted_once_per_kind_and_online_says_what_leaves(tmp_path, monkeypatch):
    answer = [True]
    asked = _ask(monkeypatch, answer)
    local = Config(application='Demo', state_dir=str(tmp_path))
    assert terms.accepted(local) and terms.accepted(local) and len(asked) == 1      # asked once
    online = Config(application='Demo', state_dir=str(tmp_path), provider='mistral',
                    base_url='https://api.mistral.ai/v1', model='mistral-large-4')
    assert terms.accepted(online) and len(asked) == 2                               # online: asked again
    text = asked[1]
    assert 'api.mistral.ai' in text and 'leave this computer' in text
    assert 'You alone are responsible</b> for what is sent, even when the chat sends it for you' in text
    assert "provider's terms" in text and 'institution' in text and 'no liability' in text
    assert terms.accepted(online) and len(asked) == 2
    assert set(json.loads((tmp_path / terms.FILE).read_text())) == {'local', 'online'}


def test_online_first_covers_local(tmp_path, monkeypatch):
    asked = _ask(monkeypatch, [True])
    online = Config(application='Demo', state_dir=str(tmp_path), provider='openai',
                    base_url='https://api.openai.com/v1', model='m')
    assert terms.accepted(online)
    assert terms.accepted(Config(application='Demo', state_dir=str(tmp_path))) and len(asked) == 1
