"""User 2026-11-23: "the sidecar kept saying Mistral API and did not show MCP or alike" while
Hermes Agent edited the figure through the live MCP server. The model line now says when another
AI app uses the figure (the adapter's outside_activity), and stops saying it afterwards."""
import time
from types import SimpleNamespace

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.config import Config


def _dock_with(session):
    return SimpleNamespace(window=lambda: SimpleNamespace(_live_session=session))


def test_the_pyfigures_adapter_reports_a_recent_outside_request():
    assert PyFiguresAdapter.outside_activity(_dock_with(None)) is None
    assert PyFiguresAdapter.outside_activity(_dock_with(SimpleNamespace(last_external=None))) is None
    now = PyFiguresAdapter.outside_activity(_dock_with(SimpleNamespace(last_external=(time.time(), 'inspect'))))
    assert now == 'another AI app is using this figure through MCP (just now)'
    later = PyFiguresAdapter.outside_activity(_dock_with(SimpleNamespace(last_external=(time.time() - 130, 'x'))))
    assert '2 min ago' in later
    assert PyFiguresAdapter.outside_activity(_dock_with(SimpleNamespace(last_external=(time.time() - 3600, 'x')))) is None


def test_choosing_another_ai_app_says_what_to_paste(tmp_path, monkeypatch):
    """User 2026-11-23: after Model > Another AI app the chat stayed on "Mistral API", with no word
    of MCP nor a prompt to give the other app."""
    from qtpy.QtWidgets import QApplication, QPushButton
    from qtpy_ai_sidecar.model_choice import ModelChoice
    from qtpy_ai_sidecar.widgets import AssistantDock
    dock = AssistantDock(Config(application='PyFigures', state_dir=str(tmp_path), provider='mistral',
                                base_url='https://api.mistral.ai/v1', model='mistral-large-4'))
    opened = []
    dock.engine.adapter.open_mcp_setup = lambda d: opened.append('mcp window')
    dock.engine.adapter.outside_app_prompt = PyFiguresAdapter.outside_app_prompt
    dock.engine.adapter.outside_activity = lambda d: None
    monkeypatch.setattr(ModelChoice, 'exec', lambda self: setattr(self, 'choice', 'other_app') or 0)
    dock.choose_model()
    assert opened == ['mcp window']
    assert 'pyfigures-live' in QApplication.clipboard().text()
    assert '🔌 Ready for another AI app' in dock.connection_label.text()
    buttons = [b.text() for b in dock.findChildren(QPushButton)]
    assert 'Copy the prompt' in buttons
    dock.close()
    dock.deleteLater()


def test_the_model_line_says_it(tmp_path):
    from qtpy_ai_sidecar.widgets import AssistantDock
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path), provider='mistral',
                                base_url='https://api.mistral.ai/v1', model='mistral-large-4'))
    said = [None]
    dock.engine.adapter.outside_activity = lambda d: said[0]
    dock.update_connection_label()
    assert dock.connection_label.text().startswith('Model: Online · Mistral') and '🔌' not in dock.connection_label.text()
    said[0] = 'another AI app is using this figure through MCP (just now)'
    dock.update_connection_label()
    assert '🔌 Another AI app is using this figure through MCP (just now)' in dock.connection_label.text()
    dock.close()
    dock.deleteLater()
