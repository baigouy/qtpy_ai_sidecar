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


def pytest_configure(config):
    config.addinivalue_line('markers', 'real_terms: run the real terms acceptance')


def pytest_sessionstart(session):
    from pathlib import Path
    marker=Path(__file__).resolve().parents[1]/'validation/pyfigures/CLAUDE_ACTIVE_RUN.json'
    if marker.exists():
        pytest.exit('Claude Qt/model run is active. Wait until CLAUDE_ACTIVE_RUN.json is removed.',returncode=4)
