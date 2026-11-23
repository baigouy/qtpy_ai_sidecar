"""Keep one Qt application alive for the entire GUI test session."""
import pytest

@pytest.fixture(scope='session',autouse=True)
def qt_application_lifetime():
    from qtpy.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def private_provider_list(tmp_path,monkeypatch):
    """Tests never read or write the user's own providers.json."""
    from qtpy_ai_sidecar import providers
    monkeypatch.setattr(providers,'path',lambda:tmp_path/'providers.json')


@pytest.fixture(autouse=True)
def terms_accepted(request, monkeypatch):
    """The first message asks the user to accept the terms (a modal dialog):
    accepted in tests, and never written to the user's own folder. Tests of
    the dialog itself are marked real_terms."""
    if request.node.get_closest_marker('real_terms') is None:
        from qtpy_ai_sidecar import terms
        monkeypatch.setattr(terms, 'accepted', lambda config, parent=None: True)


@pytest.fixture(autouse=True)
def no_local_model_setup(request, monkeypatch):
    """Sending in local mode with no model sets one up (searches this computer, may offer a
    download): skipped in tests, which use fake engines. Tests of it are marked real_setup."""
    if request.node.get_closest_marker('real_setup') is None:
        from qtpy_ai_sidecar import widgets
        monkeypatch.setattr(widgets.AssistantDock, 'local_model_ready', lambda self: True)


@pytest.fixture(autouse=True)
def private_model_folders(request, tmp_path, monkeypatch):
    """The model search (LM Studio, Ollama, Hugging Face cache) looks in an empty home."""
    from qtpy_ai_sidecar import discover
    monkeypatch.setattr(discover, 'HOME', tmp_path / 'home')
    monkeypatch.delenv('OLLAMA_MODELS', raising=False)
    # never ask the user's own LM Studio / Ollama server (tests of it fake the answers)
    monkeypatch.setattr(discover, 'LOCAL_SERVERS', (('LM Studio', 'http://127.0.0.1:9/v1', 'http://127.0.0.1:9/api'),))
    if request_has_real_servers(request):
        return
    monkeypatch.setattr(discover, 'local_servers', lambda timeout=0.6: [])


def request_has_real_servers(request):
    return request.node.get_closest_marker('real_servers') is not None


def pytest_configure(config):
    config.addinivalue_line('markers', 'real_terms: run the real terms acceptance')
    config.addinivalue_line('markers', 'real_setup: run the real local-model setup on send')
    config.addinivalue_line('markers', 'real_servers: run discover.local_servers (with faked HTTP answers)')


def pytest_sessionstart(session):
    from pathlib import Path
    marker=Path(__file__).resolve().parents[1]/'validation/pyfigures/CLAUDE_ACTIVE_RUN.json'
    if marker.exists():
        pytest.exit('Claude Qt/model run is active. Wait until CLAUDE_ACTIVE_RUN.json is removed.',returncode=4)
